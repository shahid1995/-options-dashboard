"""Day 38 Task 6 — Concurrency-safe position sequence allocation and rollback.

Verifies that position sequence allocation and lifecycle-event persistence
participate in the SAME caller-owned PostgreSQL transaction.

PostgreSQL is REQUIRED for concurrency/transaction correctness.  When
TEST_DATABASE_URL is not set, the PostgreSQL-specific tests are skipped.
SQLite tests verify transaction-boundary logic only (not concurrency).

Scenarios:
  A. Successful transaction: allocate + event + commit -> both persist
  B. Rollback after allocation (no event) -> sequence not burned
  C. Rollback after failed event persistence -> no orphan sequence
  D. Commit preserves both: anchor and event agree
  E. Caller transaction ownership (no internal commit/rollback)
  F. Full PositionIdentity namespace independence
"""

import os
import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import sessionmaker

from app.trade_lifecycle.persistence import (
    TradeLifecycleEvent,
    PositionSequenceAnchor,
    append_lifecycle_event,
    allocate_position_sequence,
    event_id,
    IntegrityError,
)
from app.db import Base


# ---------------------------------------------------------------------------
# Fixtures (SQLite in-memory for deterministic local tests)
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}
)
TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def fresh_db():
    """Create all tables and drop after each test for isolation."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


def _session():
    return TestSession()


def _alloc(db, tenant, user, symbol, expiry, strike, option_type):
    return allocate_position_sequence(
        db=db, tenant_id=tenant, user_id=user, symbol=symbol,
        expiry=expiry, strike=strike, option_type=option_type,
    )


def _append_event(db, *, position_sequence, aggregate_id="exec-1", sequence=1,
                  quantity_delta=10, metadata=None):
    return append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id=aggregate_id,
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=sequence,
        position_sequence=position_sequence,
        quantity_delta=quantity_delta,
        position_identity={
            "user_id": "u1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={"symbol": "NIFTY"},
        metadata=metadata,
    )


# ===========================================================================
# Scenario A — Successful transaction: allocate + event + commit
# ===========================================================================

def test_scenario_a_allocate_and_event_commit_together(fresh_db):
    """Within one transaction: allocate sequence, append event, commit -> both persist."""
    db = _session()
    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    assert seq == 1

    ev = _append_event(db, position_sequence=seq)
    db.commit()

    # Verify anchor
    anchor = db.execute(
        text("SELECT last_position_sequence FROM position_sequence_anchor "
             "WHERE tenant_id = 'tenant-1' AND user_id = 'user-1' "
             "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
             "AND strike = 24000.0 AND option_type = 'CE'")
    ).scalar()
    assert anchor == 1

    # Verify event
    event_ps = db.execute(
        text("SELECT position_sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": ev.event_id},
    ).scalar()
    assert event_ps == 1
    db.close()


# ===========================================================================
# Scenario B — Rollback after allocation (no event persisted)
# ===========================================================================

def test_scenario_b_rollback_after_allocation_does_not_burn_sequence(fresh_db):
    """Allocate sequence, do NOT persist event, ROLLBACK -> sequence not burned."""
    db = _session()
    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    assert seq == 1
    db.rollback()
    db.close()

    # New transaction: allocation returns 1 again
    db2 = _session()
    seq2 = _alloc(db2, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db2.commit()
    assert seq2 == 1, f"Rollback must not burn sequence, got {seq2}"
    db2.close()


# ===========================================================================
# Scenario C — Rollback after failed event persistence
# ===========================================================================

def test_scenario_c_rollback_after_failed_event_no_orphan_sequence(fresh_db):
    """Allocate sequence, attempt event insert that fails, ROLLBACK -> no orphan."""
    db = _session()
    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    assert seq == 1

    # Append first event (succeeds)
    _append_event(db, position_sequence=seq)
    db.commit()

    # Now try to append a conflicting event (same event_id, different content)
    # This should raise IntegrityError
    try:
        _append_event(db, position_sequence=seq, quantity_delta=-10)
    except IntegrityError:
        pass
    db.rollback()
    db.close()

    # Verify: only the first event exists, anchor is at 1
    db2 = _session()
    count = db2.execute(
        text("SELECT COUNT(*) FROM trade_lifecycle_events WHERE tenant_id = 'tenant-1'")
    ).scalar()
    assert count == 1

    anchor = db2.execute(
        text("SELECT last_position_sequence FROM position_sequence_anchor "
             "WHERE tenant_id = 'tenant-1' AND user_id = 'user-1' "
             "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
             "AND strike = 24000.0 AND option_type = 'CE'")
    ).scalar()
    assert anchor == 1
    db2.close()


# ===========================================================================
# Scenario D — Commit preserves both
# ===========================================================================

def test_scenario_d_commit_preserves_anchor_and_event(fresh_db):
    """After commit: anchor.last_position_sequence == event.position_sequence."""
    db = _session()
    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    ev = _append_event(db, position_sequence=seq)
    db.commit()

    # Verify agreement
    anchor = db.execute(
        text("SELECT last_position_sequence FROM position_sequence_anchor "
             "WHERE tenant_id = 'tenant-1' AND user_id = 'user-1' "
             "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
             "AND strike = 24000.0 AND option_type = 'CE'")
    ).scalar()
    event = db.execute(
        text("SELECT position_sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": ev.event_id},
    ).fetchone()

    assert anchor == seq
    assert event.position_sequence == seq
    assert anchor == event.position_sequence
    db.close()


# ===========================================================================
# Scenario E — Caller transaction ownership
# ===========================================================================

def test_scenario_e_caller_owns_transaction_no_internal_commit(fresh_db):
    """The helper must NOT commit the caller's transaction."""
    db = _session()
    db.execute(text("CREATE TABLE scratch_txn (id INTEGER PRIMARY KEY, note TEXT)"))
    db.execute(text("INSERT INTO scratch_txn (id, note) VALUES (1, 'caller-work')"))

    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    _append_event(db, position_sequence=seq)

    # Caller commits
    db.commit()

    notes = db.execute(text("SELECT note FROM scratch_txn ORDER BY id")).scalars().all()
    assert notes == ["caller-work"]
    db.close()


def test_scenario_e_caller_owns_rollback(fresh_db):
    """The helper must NOT roll back the caller's transaction on conflict."""
    db = _session()
    db.execute(text("CREATE TABLE scratch_txn_2 (id INTEGER PRIMARY KEY, note TEXT)"))
    db.execute(text("INSERT INTO scratch_txn_2 (id, note) VALUES (1, 'caller-work-A')"))

    seq = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    _append_event(db, position_sequence=seq)

    # Conflict triggers IntegrityError inside helper
    try:
        _append_event(db, position_sequence=seq, quantity_delta=-10)
    except IntegrityError:
        pass

    # Caller's transaction must still be usable
    db.execute(text("INSERT INTO scratch_txn_2 (id, note) VALUES (2, 'caller-work-B')"))
    db.commit()

    notes = db.execute(text("SELECT note FROM scratch_txn_2 ORDER BY id")).scalars().all()
    assert notes == ["caller-work-A", "caller-work-B"]
    db.close()


# ===========================================================================
# Scenario F — Full PositionIdentity namespace independence
# ===========================================================================

def test_scenario_f_independent_by_option_type(fresh_db):
    """Same user/symbol/expiry/strike, different option_type -> independent sequences."""
    db = _session()
    s1 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "PE")
    s3 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()
    assert s1 == 1
    assert s2 == 1  # independent namespace
    assert s3 == 2  # same namespace advances
    db.close()


def test_scenario_f_independent_by_strike(fresh_db):
    """Same user/symbol/expiry/option_type, different strike -> independent sequences."""
    db = _session()
    s1 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 25000.0, "CE")
    s3 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()
    assert s1 == 1
    assert s2 == 1  # independent
    assert s3 == 2
    db.close()


def test_scenario_f_independent_by_expiry(fresh_db):
    """Same user/symbol/strike/option_type, different expiry -> independent sequences."""
    db = _session()
    s1 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2027-01-31", 24000.0, "CE")
    s3 = _alloc(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()
    assert s1 == 1
    assert s2 == 1  # independent
    assert s3 == 2
    db.close()


def test_scenario_f_independent_by_user(fresh_db):
    """Same instrument, different user -> independent sequences."""
    db = _session()
    s1 = _alloc(db, "tenant-1", "user-A", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = _alloc(db, "tenant-1", "user-B", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()
    assert s1 == 1
    assert s2 == 1
    db.close()


def test_scenario_f_independent_by_tenant(fresh_db):
    """Same PositionIdentity, different tenant -> independent sequences."""
    db = _session()
    s1 = _alloc(db, "tenant-A", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = _alloc(db, "tenant-B", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s3 = _alloc(db, "tenant-A", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()
    assert s1 == 1
    assert s2 == 1  # tenant-B independent
    assert s3 == 2  # tenant-A advances
    db.close()


# ===========================================================================
# PostgreSQL-only tests (skipped when TEST_DATABASE_URL not set)
# ===========================================================================

PG_DB_URL = os.getenv("TEST_DATABASE_URL", "")
_pg_tests_available = bool(PG_DB_URL and PG_DB_URL.startswith(("postgresql+psycopg://", "postgresql://")))

if _pg_tests_available:
    PG_ENGINE = create_engine(PG_DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)
    PGSession = sessionmaker(bind=PG_ENGINE, autocommit=False, autoflush=False)

    @pytest.fixture(scope="module")
    def pg_tables():
        Base.metadata.create_all(bind=PG_ENGINE)
        yield
        Base.metadata.drop_all(bind=PG_ENGINE)

    def _pg_session():
        return PGSession()


@pytest.mark.skipif(not _pg_tests_available, reason="TEST_DATABASE_URL must point to PostgreSQL")
class TestPostgresTransactionalAllocation:
    """PostgreSQL-specific transactional allocation tests."""

    def test_pg_allocate_and_event_commit_together(self, pg_tables):
        """Scenario A on PostgreSQL: allocate + event + commit -> both persist."""
        db = _pg_session()
        seq = allocate_position_sequence(
            db=db, tenant_id="pg-txn", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        assert seq == 1

        ev = append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="pg-exec-1",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="pg-txn",
            sequence=1,
            position_sequence=seq,
            quantity_delta=10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            payload={},
        )
        db.commit()

        anchor = db.execute(
            text("SELECT last_position_sequence FROM position_sequence_anchor "
                 "WHERE tenant_id = 'pg-txn' AND user_id = 'user-1' "
                 "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
                 "AND strike = 24000.0 AND option_type = 'CE'")
        ).scalar()
        assert anchor == 1

        event_ps = db.execute(
            text("SELECT position_sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
            {"eid": ev.event_id},
        ).scalar()
        assert event_ps == 1
        db.close()

    def test_pg_rollback_does_not_burn_sequence(self, pg_tables):
        """Scenario B on PostgreSQL: rollback after allocation -> sequence not burned."""
        db = _pg_session()
        seq = allocate_position_sequence(
            db=db, tenant_id="pg-roll", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        assert seq == 1
        db.rollback()
        db.close()

        db2 = _pg_session()
        seq2 = allocate_position_sequence(
            db=db2, tenant_id="pg-roll", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        db2.commit()
        assert seq2 == 1, f"Rollback must not burn sequence, got {seq2}"
        db2.close()

    def test_pg_rollback_after_failed_event_no_orphan(self, pg_tables):
        """Scenario C on PostgreSQL: failed event + rollback -> no orphan sequence."""
        db = _pg_session()
        seq = allocate_position_sequence(
            db=db, tenant_id="pg-fail", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        assert seq == 1

        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="pg-exec-fail",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="pg-fail",
            sequence=1,
            position_sequence=seq,
            quantity_delta=10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            payload={},
        )
        db.commit()

        # Now try conflicting event
        try:
            append_lifecycle_event(
                db=db,
                aggregate_type="execution",
                aggregate_id="pg-exec-fail",
                event_type="PositionOpened",
                event_version="1.0",
                tenant_id="pg-fail",
                sequence=1,
                position_sequence=seq,
                quantity_delta=-10,  # different content -> conflict
                position_identity={
                    "user_id": "user-1",
                    "symbol": "NIFTY",
                    "expiry": "2026-12-31",
                    "strike": 24000.0,
                    "option_type": "CE",
                },
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                payload={},
            )
        except IntegrityError:
            pass
        db.rollback()
        db.close()

        db2 = _pg_session()
        count = db2.execute(
            text("SELECT COUNT(*) FROM trade_lifecycle_events WHERE tenant_id = 'pg-fail'")
        ).scalar()
        assert count == 1

        anchor = db2.execute(
            text("SELECT last_position_sequence FROM position_sequence_anchor "
                 "WHERE tenant_id = 'pg-fail' AND user_id = 'user-1' "
                 "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
                 "AND strike = 24000.0 AND option_type = 'CE'")
        ).scalar()
        assert anchor == 1
        db2.close()

    def test_pg_commit_preserves_both(self, pg_tables):
        """Scenario D on PostgreSQL: anchor and event agree after commit."""
        db = _pg_session()
        seq = allocate_position_sequence(
            db=db, tenant_id="pg-agree", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        ev = append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="pg-exec-agree",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="pg-agree",
            sequence=1,
            position_sequence=seq,
            quantity_delta=10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            payload={},
        )
        db.commit()

        anchor = db.execute(
            text("SELECT last_position_sequence FROM position_sequence_anchor "
                 "WHERE tenant_id = 'pg-agree' AND user_id = 'user-1' "
                 "AND symbol = 'NIFTY' AND expiry = '2026-12-31' "
                 "AND strike = 24000.0 AND option_type = 'CE'")
        ).scalar()
        event = db.execute(
            text("SELECT position_sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
            {"eid": ev.event_id},
        ).fetchone()

        assert anchor == seq
        assert event.position_sequence == seq
        db.close()

    def test_pg_caller_owns_transaction(self, pg_tables):
        """Scenario E on PostgreSQL: caller owns commit/rollback."""
        db = _pg_session()
        # Clean up any leftover scratch table from previous runs
        db.execute(text("DROP TABLE IF EXISTS pg_scratch"))
        db.commit()
        db.execute(text("CREATE TABLE pg_scratch (id INTEGER PRIMARY KEY, note TEXT)"))
        db.execute(text("INSERT INTO pg_scratch (id, note) VALUES (1, 'caller-work')"))

        seq = allocate_position_sequence(
            db=db, tenant_id="pg-owner", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="pg-exec-owner",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="pg-owner",
            sequence=1,
            position_sequence=seq,
            quantity_delta=10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            payload={},
        )
        db.commit()

        notes = db.execute(text("SELECT note FROM pg_scratch ORDER BY id")).scalars().all()
        assert notes == ["caller-work"]
        db.execute(text("DROP TABLE pg_scratch"))
        db.close()

    def test_pg_full_namespace_independence(self, pg_tables):
        """Scenario F on PostgreSQL: full PositionIdentity namespace independence."""
        db = _pg_session()
        # Different option_type
        s1 = allocate_position_sequence(
            db=db, tenant_id="pg-ns", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        s2 = allocate_position_sequence(
            db=db, tenant_id="pg-ns", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="PE",
        )
        # Different strike
        s3 = allocate_position_sequence(
            db=db, tenant_id="pg-ns", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=25000.0, option_type="CE",
        )
        # Different expiry
        s4 = allocate_position_sequence(
            db=db, tenant_id="pg-ns", user_id="user-1", symbol="NIFTY",
            expiry="2027-01-31", strike=24000.0, option_type="CE",
        )
        # Different user
        s5 = allocate_position_sequence(
            db=db, tenant_id="pg-ns", user_id="user-2", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        # Different tenant
        s6 = allocate_position_sequence(
            db=db, tenant_id="pg-ns-2", user_id="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        )
        db.commit()

        assert s1 == 1
        assert s2 == 1  # different option_type
        assert s3 == 1  # different strike
        assert s4 == 1  # different expiry
        assert s5 == 1  # different user
        assert s6 == 1  # different tenant
        db.close()
