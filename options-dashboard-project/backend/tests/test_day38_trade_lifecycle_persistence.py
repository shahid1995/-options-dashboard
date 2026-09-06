"""Day 38 Task 1: Trade lifecycle persistence foundation tests.

TDD: RED first (create these before implementation), then GREEN.

Covers the approved design requirements:
- lifecycle event persistence
- tenant association
- event_id (deterministic, tenant-scoped)
- aggregate identity
- aggregate sequence (tenant-scoped)
- position_sequence
- signed quantity_delta
- event type/version
- occurred timestamp
- position identity fields
- uniqueness for deterministic lifecycle sequencing (tenant-scoped)
- PositionSequenceAnchor scoped by complete PositionIdentity
- complete canonical duplicate / idempotency constraints
- rollback-safe sequence allocation foundation
- cross-tenant isolation
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
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
# Fixtures
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def fresh_db():
    """Create all tables and drop after each test for isolation."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


def _session():
    return TestSession()


# ---------------------------------------------------------------------------
# 1. Deterministic event_id (tenant-scoped)
# ---------------------------------------------------------------------------

def test_event_id_is_deterministic():
    eid = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    assert eid == event_id("t1", "execution", "exec-a", "PositionOpened", 1)


def test_event_id_differs_by_tenant():
    a = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    b = event_id("t2", "execution", "exec-a", "PositionOpened", 1)
    assert a != b


def test_event_id_differs_by_aggregate_type():
    a = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    b = event_id("t1", "position", "exec-a", "PositionOpened", 1)
    assert a != b


def test_event_id_differs_by_aggregate_id():
    a = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    b = event_id("t1", "execution", "exec-b", "PositionOpened", 1)
    assert a != b


def test_event_id_differs_by_event_type():
    a = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    b = event_id("t1", "execution", "exec-a", "PositionClosed", 1)
    assert a != b


def test_event_id_differs_by_sequence():
    a = event_id("t1", "execution", "exec-a", "PositionOpened", 1)
    b = event_id("t1", "execution", "exec-a", "PositionOpened", 2)
    assert a != b


# ---------------------------------------------------------------------------
# 2. Lifecycle event persistence
# ---------------------------------------------------------------------------

def test_append_lifecycle_event_persists(fresh_db):
    db = _session()
    ev = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={"symbol": "NIFTY"},
    )
    db.commit()

    assert ev.event_id is not None
    assert ev.aggregate_id == "exec-a"
    assert ev.event_type == "PositionOpened"
    assert ev.quantity_delta == 10
    db.close()


def test_append_position_event_persists(fresh_db):
    db = _session()
    ev = append_lifecycle_event(
        db=db,
        aggregate_type="position",
        aggregate_id="pos-1",
        event_type="PositionClosed",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=2,
        position_sequence=1,
        quantity_delta=-10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
        payload={},
    )
    db.commit()

    assert ev.event_type == "PositionClosed"
    assert ev.quantity_delta == -10
    db.close()


# ---------------------------------------------------------------------------
# 3. Tenant association
# ---------------------------------------------------------------------------

def test_event_has_tenant_id(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-A",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    rows = db.execute(text("SELECT tenant_id FROM trade_lifecycle_events")).scalars().all()
    assert rows == ["tenant-A"]
    db.close()


# ---------------------------------------------------------------------------
# 4. Aggregate identity
# ---------------------------------------------------------------------------

def test_event_stores_aggregate_id(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-abc",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text("SELECT aggregate_id FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "execution", "exec-abc", "PositionOpened", 1)},
    ).scalar()
    assert row == "exec-abc"
    db.close()


# ---------------------------------------------------------------------------
# 5. Aggregate sequence (tenant-scoped)
# ---------------------------------------------------------------------------

def test_event_stores_sequence(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=5,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text("SELECT sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "execution", "exec-a", "PositionOpened", 5)},
    ).scalar()
    assert row == 5
    db.close()


# ---------------------------------------------------------------------------
# 6. position_sequence
# ---------------------------------------------------------------------------

def test_event_stores_position_sequence(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="position",
        aggregate_id="pos-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=3,
        quantity_delta=5,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text("SELECT position_sequence FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "position", "pos-1", "PositionOpened", 1)},
    ).scalar()
    assert row == 3
    db.close()


# ---------------------------------------------------------------------------
# 7. Signed quantity_delta
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta", [10, -5, 0, -10])
def test_quantity_delta_accepts_signed_values(fresh_db, delta):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=delta,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text("SELECT quantity_delta FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "execution", "exec-a", "PositionOpened", 1)},
    ).scalar()
    assert row == delta
    db.close()


# ---------------------------------------------------------------------------
# 8. Event type / version
# ---------------------------------------------------------------------------

def test_event_type_and_version_stored(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionClosed",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=-10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text("SELECT event_type, event_version FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "execution", "exec-a", "PositionClosed", 1)},
    ).fetchone()
    assert row.event_type == "PositionClosed"
    assert row.event_version == "1.0"
    db.close()


# ---------------------------------------------------------------------------
# 9. Occurred timestamp
# ---------------------------------------------------------------------------

def test_occurred_at_stored(fresh_db):
    db = _session()
    ts = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=ts,
        payload={},
    )
    db.commit()

    # SQLite stores DateTime as string; compare ISO format prefix
    row = db.execute(
        text("SELECT occurred_at FROM trade_lifecycle_events WHERE event_id = :eid"),
        {"eid": event_id("tenant-1", "execution", "exec-a", "PositionOpened", 1)},
    ).scalar()
    assert row.startswith("2026-06-15 10:30:00")
    db.close()


# ---------------------------------------------------------------------------
# 10. Position identity fields
# ---------------------------------------------------------------------------

def test_position_identity_fields_stored(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="position",
        aggregate_id="pos-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-X",
            "symbol": "BANKNIFTY",
            "expiry": "2026-06-25",
            "strike": 50000.0,
            "option_type": "PE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    row = db.execute(
        text(
            "SELECT position_identity_user_id, position_identity_symbol, "
            "position_identity_expiry, position_identity_strike, position_identity_option_type "
            "FROM trade_lifecycle_events WHERE event_id = :eid"
        ),
        {"eid": event_id("tenant-1", "position", "pos-1", "PositionOpened", 1)},
    ).fetchone()
    assert row.position_identity_user_id == "user-X"
    assert row.position_identity_symbol == "BANKNIFTY"
    assert row.position_identity_expiry == "2026-06-25"
    assert row.position_identity_strike == 50000.0
    assert row.position_identity_option_type == "PE"
    db.close()


# ---------------------------------------------------------------------------
# 11. Tenant-scoped aggregate sequence uniqueness
# ---------------------------------------------------------------------------

def test_tenant_scoped_aggregate_sequence_unique_constraint(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    # Same tenant + same aggregate + same sequence + different content → conflict
    with pytest.raises(IntegrityError):
        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="exec-a",
            event_type="PositionClosed",
            event_version="1.0",
            tenant_id="tenant-1",
            sequence=1,
            position_sequence=1,
            quantity_delta=-10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime.now(timezone.utc),
            payload={},
        )
    db.close()


# ---------------------------------------------------------------------------
# 12. PositionSequenceAnchor scoped by complete PositionIdentity
# ---------------------------------------------------------------------------

def test_position_sequence_anchor_scoped_by_complete_identity(fresh_db):
    db = _session()

    seq1 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    assert seq1 == 1

    # Different option_type = different identity = independent sequence
    seq2 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="PE",
    )
    assert seq2 == 1

    # Same identity advances
    seq3 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    assert seq3 == 2

    db.close()


# ---------------------------------------------------------------------------
# 13. Duplicate / idempotency constraints (complete canonical comparison)
# ---------------------------------------------------------------------------

def test_identical_duplicate_is_idempotent(fresh_db):
    db = _session()
    ev1 = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={"symbol": "NIFTY"},
    )
    db.commit()

    # Same canonical content: should return existing event, not raise
    ev2 = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={"symbol": "NIFTY"},
    )
    db.commit()

    assert ev1.event_id == ev2.event_id
    count = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")).scalar()
    assert count == 1
    db.close()


def test_conflicting_duplicate_raises(fresh_db):
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-a",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={
            "user_id": "user-1",
            "symbol": "NIFTY",
            "expiry": "2026-12-31",
            "strike": 24000.0,
            "option_type": "CE",
        },
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={"symbol": "NIFTY"},
    )
    db.commit()

    # Same event_id but different canonical content → conflict
    with pytest.raises(IntegrityError):
        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="exec-a",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="tenant-1",
            sequence=1,
            position_sequence=1,
            quantity_delta=-10,
            position_identity={
                "user_id": "user-1",
                "symbol": "NIFTY",
                "expiry": "2026-12-31",
                "strike": 24000.0,
                "option_type": "CE",
            },
            occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            payload={"symbol": "NIFTY"},
        )
    db.close()


# ---------------------------------------------------------------------------
# 14. Rollback-safe sequence allocation foundation
# ---------------------------------------------------------------------------

def test_rollback_does_not_burn_sequence(fresh_db):
    db = _session()

    seq1 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    assert seq1 == 1
    db.rollback()

    # After rollback, a new allocation starts fresh at 1
    seq2 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    assert seq2 == 1
    db.close()


def test_concurrent_first_event_allocation_is_safe(fresh_db):
    """Sequential allocations advance correctly.

    Concurrent safety is proven by the atomic upsert at the DB level.
    SQLite does not provide real row-level locking, so this test
    verifies sequential correctness only.  PostgreSQL concurrency is
    tested separately in test_day38_postgres_concurrency.py.
    """
    db = _session()

    seq1 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    seq2 = allocate_position_sequence(
        db=db,
        tenant_id="tenant-1",
        user_id="user-1",
        symbol="NIFTY",
        expiry="2026-12-31",
        strike=24000.0,
        option_type="CE",
    )
    db.commit()

    assert seq1 == 1
    assert seq2 == 2
    db.close()


# ===========================================================================
# CROSS-TENANT ISOLATION TESTS (Remediation 4)
# ===========================================================================

def test_cross_tenant_event_ids_differ(fresh_db):
    """Remediation 4A: Same event fields in different tenants produce different event IDs."""
    id_a = event_id("tenant-A", "execution", "exec-1", "PositionOpened", 1)
    id_b = event_id("tenant-B", "execution", "exec-1", "PositionOpened", 1)
    assert id_a != id_b


def test_cross_tenant_same_aggregate_coexists(fresh_db):
    """Remediation 4B: Two tenants can both persist (exec, seq=1) without conflict."""
    db = _session()

    ev_a = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-A",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    ev_b = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-B",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    count = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")).scalar()
    assert count == 2
    assert ev_a.event_id != ev_b.event_id
    db.close()


def test_cross_tenant_conflict_same_aggregate(fresh_db):
    """Remediation 4C: Same tenant + same aggregate + same sequence + different content → conflict."""
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-A",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    with pytest.raises(IntegrityError):
        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="exec-1",
            event_type="PositionClosed",
            event_version="1.0",
            tenant_id="tenant-A",
            sequence=1,
            position_sequence=1,
            quantity_delta=-10,
            position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
            occurred_at=datetime.now(timezone.utc),
            payload={},
        )
    db.close()


def test_identical_duplicate_same_tenant_is_idempotent(fresh_db):
    """Remediation 4D: Same tenant + same aggregate + same sequence + same content → idempotent."""
    db = _session()
    ev1 = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-A",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={},
    )
    db.commit()

    ev2 = append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-A",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        payload={},
    )
    db.commit()

    assert ev1.event_id == ev2.event_id
    count = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")).scalar()
    assert count == 1
    db.close()


# ===========================================================================
# POSITION SEQUENCE ISOLATION (Remediation 5 regression)
# ===========================================================================

def test_position_sequence_anchor_independent_by_tenant(fresh_db):
    """Remediation 5: Same PositionIdentity in different tenants gets independent sequences."""
    db = _session()

    s1 = allocate_position_sequence(db, "tenant-A", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = allocate_position_sequence(db, "tenant-B", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s3 = allocate_position_sequence(db, "tenant-A", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()

    assert s1 == 1  # tenant-A, first
    assert s2 == 1  # tenant-B, independent
    assert s3 == 2  # tenant-A, second
    db.close()


def test_position_sequence_anchor_independent_by_user(fresh_db):
    """Remediation 5: Same instrument, different user → independent sequences."""
    db = _session()

    s1 = allocate_position_sequence(db, "tenant-1", "user-A", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = allocate_position_sequence(db, "tenant-1", "user-B", "NIFTY", "2026-12-31", 24000.0, "CE")
    db.commit()

    assert s1 == 1
    assert s2 == 1
    db.close()


def test_position_sequence_anchor_independent_by_symbol(fresh_db):
    """Remediation 5: Same user, different symbol → independent sequences."""
    db = _session()

    s1 = allocate_position_sequence(db, "tenant-1", "user-1", "NIFTY", "2026-12-31", 24000.0, "CE")
    s2 = allocate_position_sequence(db, "tenant-1", "user-1", "BANKNIFTY", "2026-12-31", 50000.0, "CE")
    db.commit()

    assert s1 == 1
    assert s2 == 1
    db.close()


# ===========================================================================
# POSITION IDENTITY INSERTED FROM dict (Remediation 3 regression)
# ===========================================================================

def test_complete_canonical_content_includes_all_fields(fresh_db):
    """Remediation 3: Canonical comparison uses ALL semantically relevant fields.

    Insert event A, then event B with the same event_id (same aggregate/seq)
    but a different position_identity field → must raise IntegrityError.
    """
    db = _session()
    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        tenant_id="tenant-1",
        sequence=1,
        position_sequence=1,
        quantity_delta=10,
        position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 24000.0, "option_type": "CE"},
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    db.commit()

    # Same aggregate+seq but different position identity (strike changed)
    with pytest.raises(IntegrityError):
        append_lifecycle_event(
            db=db,
            aggregate_type="execution",
            aggregate_id="exec-1",
            event_type="PositionOpened",
            event_version="1.0",
            tenant_id="tenant-1",
            sequence=1,
            position_sequence=1,
            quantity_delta=10,
            position_identity={"user_id": "u1", "symbol": "NIFTY", "expiry": "2026-12-31", "strike": 25000.0, "option_type": "CE"},
            occurred_at=datetime.now(timezone.utc),
            payload={},
        )
    db.close()