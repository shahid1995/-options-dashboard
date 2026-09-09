"""Day 39 Task 2 — RED tests (v7): idempotency-vs-stale ordering.

Control Center finding (Day39 Task2, remaining defect):

The current ``_do_ingest()`` performs
``_validate_broker_sequence_position()`` BEFORE the durable
``BrokerSyncIdempotency`` lookup.  An exact replay of an already-applied
event (same canonical_id, same fingerprint) is therefore REJECTED as
STALE once a later broker event has advanced the sequence anchor —
even though the event is durably recorded.

Required invariant:
    canonical_id exists + same fingerprint  -> DUPLICATE_NOOP
    canonical_id exists + different content -> CONFLICT
    (both regardless of incoming canonical_sequence vs anchor)
    new canonical_id + old sequence         -> REJECTED (STALE)

A previously persisted event must not become STALE merely because later
events have already advanced the broker sequence.

These tests are behavioral: they assert actions, durable projection /
idempotency / lifecycle counts, and anchor stability — not internals.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync import (
    BrokerEventType,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
    make_broker_sync_event,
)
from app.broker_sync.ingestion import ingest_canonical_event
from app.broker_sync.models import (
    BrokerOrderProjection,
    BrokerSyncIdempotency,
    BrokerSyncSequenceAnchor,
)

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)

PG_DB_URL = os.getenv("TEST_DATABASE_URL", "")
_pg_available = bool(
    PG_DB_URL
    and PG_DB_URL.startswith(("postgresql+psycopg://", "postgresql://"))
)


# ---------------------------------------------------------------------------
# SQLite engine + fixtures (mirrors test_day39_task2_ingestion.py conventions)
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def _seed_app_order(db, broker_order_id: str, tenant_id: str = "tenant-1",
                    execution_id: str | None = None) -> str:
    """Seed an authoritative StrategyExecution + PaperOrder pair."""
    from app.models import PaperOrder, StrategyExecution

    exec_id = execution_id or f"EXEC-{broker_order_id}"
    db.add(StrategyExecution(
        user_id=tenant_id,
        execution_id=exec_id,
        client_order_id=f"exec-{broker_order_id}",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol="NIFTY",
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    ))
    db.flush()
    db.add(PaperOrder(
        user_id=tenant_id,
        client_order_id=broker_order_id,
        execution_id=exec_id,
        kind="entry",
        symbol="NIFTY",
        expiry="2026-10-29",
        strike=24500.0,
        option_type="CE",
        action="buy",
        quantity=100,
        lot_size=1,
        status="FILLED",
        filled_quantity=100,
        fill_price=100.0,
    ))
    db.flush()
    return exec_id


_ORDER_IDS = ["ORD-7A", "ORD-7B", "ORD-7C", "ORD-7D", "ORD-7X"]


@pytest.fixture()
def db():
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    for oid in _ORDER_IDS:
        _seed_app_order(session, oid)
    session.commit()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def _submitted(order_id: str, seq: int | None, *, tenant="tenant-1",
               broker="broker-test", received_at=None):
    return make_broker_sync_event(
        tenant_id=tenant, broker=broker,
        event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.SUBMITTED, total_quantity=100,
            cumulative_filled=0,
        ),
        received_at=received_at or (_NOW + timedelta(seconds=1)),
    )


def _accepted(order_id: str, seq: int | None, *, tenant="tenant-1",
              broker="broker-test", total_quantity=100, received_at=None):
    return make_broker_sync_event(
        tenant_id=tenant, broker=broker,
        event_type=BrokerEventType.ORDER_ACCEPTED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.OPEN, total_quantity=total_quantity,
        ),
        received_at=received_at or (_NOW + timedelta(seconds=2)),
    )


def _anchor_last_sequence(db, order_id: str):
    row = db.execute(
        select(BrokerSyncSequenceAnchor).where(
            BrokerSyncSequenceAnchor.broker_order_id == order_id
        )
    ).scalar_one_or_none()
    return None if row is None else row.last_sequence


# ---------------------------------------------------------------------------
# 1. Critical regression — exact replay after later sequences
# ---------------------------------------------------------------------------

class TestExactReplayAfterLaterSequence:
    """seq1 APPLY -> seq2 APPLY -> replay seq1 -> DUPLICATE_NOOP."""

    def test_exact_replay_of_seq1_after_seq2_is_duplicate_noop(self, db):
        """THE critical regression (task §7).

        A previously persisted event must not become STALE merely because
        later events have already advanced the broker sequence.
        """
        # 1. Apply canonical event X at sequence 1
        x = _submitted("ORD-7A", 1)
        r1 = ingest_canonical_event(x, db)
        assert r1["action"] == "APPLIED"

        # 2. Apply a later valid event Y at sequence 2
        y = _accepted("ORD-7A", 2)
        r2 = ingest_canonical_event(y, db)
        assert r2["action"] == "APPLIED"

        # 3. Re-ingest the EXACT original X (same canonical_id, same content)
        r3 = ingest_canonical_event(x, db)
        # 4. Durable identity must win: DUPLICATE_NOOP, not STALE/REJECTED
        assert r3["action"] == "DUPLICATE_NOOP", (
            f"exact replay of already-applied event classified as "
            f"{r3['action']}: {r3.get('reason')}"
        )

        # 5. No duplicate projection
        count = db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection "
                 "WHERE canonical_id = :cid"),
            {"cid": x.canonical_id},
        ).scalar()
        assert count == 1

        # 6. No additional lifecycle event
        lc = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")
                        ).scalar()
        assert lc == 2  # exactly the two applied events

        # 7. Broker sequence anchor does not regress / change
        assert _anchor_last_sequence(db, "ORD-7A") == 2

        # Idempotency record is untouched and single
        idem_count = db.execute(
            text("SELECT COUNT(*) FROM broker_sync_idempotency "
                 "WHERE canonical_id = :cid"),
            {"cid": x.canonical_id},
        ).scalar()
        assert idem_count == 1

    def test_exact_replay_of_seq1_after_seq3_is_duplicate_noop(self, db):
        """Exact replay after MULTIPLE later sequences (task §11 row 4)."""
        a = _submitted("ORD-7B", 1)
        assert ingest_canonical_event(a, db)["action"] == "APPLIED"
        b = _accepted("ORD-7B", 2)
        assert ingest_canonical_event(b, db)["action"] == "APPLIED"
        c = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-7B", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-7B", order_id="ORD-7B",
                status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50),
            fill_facts=FillFacts(
                fill_id="fill-7b-1", fill_quantity=50, fill_price=100.0,
                cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=3),
        )
        assert ingest_canonical_event(c, db)["action"] == "APPLIED"

        # Replay the exact seq-1 event after seq-3 was applied
        r = ingest_canonical_event(a, db)
        assert r["action"] == "DUPLICATE_NOOP", (
            f"exact replay after seq3 classified as {r['action']}: "
            f"{r.get('reason')}"
        )
        assert _anchor_last_sequence(db, "ORD-7B") == 3

        lc = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")
                        ).scalar()
        assert lc == 3

    def test_multi_event_ordering_then_replay_first(self, db):
        """seq1/seq2/seq3 applied, replay seq1 -> NOOP; new seq1 -> STALE (task §7)."""
        a = _submitted("ORD-7C", 1)
        b = _accepted("ORD-7C", 2)
        c = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-7C", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-7C", order_id="ORD-7C",
                status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=25),
            fill_facts=FillFacts(
                fill_id="fill-7c-1", fill_quantity=25, fill_price=99.0,
                cumulative_filled_after=25, remaining_after=75),
            received_at=_NOW + timedelta(seconds=3),
        )

        assert ingest_canonical_event(a, db)["action"] == "APPLIED"
        assert ingest_canonical_event(b, db)["action"] == "APPLIED"
        assert ingest_canonical_event(c, db)["action"] == "APPLIED"

        # Replay canonical A -> DUPLICATE_NOOP
        ra = ingest_canonical_event(a, db)
        assert ra["action"] == "DUPLICATE_NOOP", (
            f"replay of canonical A classified as {ra['action']}: "
            f"{ra.get('reason')}"
        )

        # New canonical D at seq1 for the SAME broker order -> REJECTED /
        # STALE (stale detection intact for genuinely new events)
        d = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id="ORD-7C", canonical_sequence=1,
            provider_event_id="provider-new-d-1",  # distinct identity
            order_facts=OrderFacts(
                broker_order_id="ORD-7C", order_id="ORD-7C",
                status=CanonicalOrderState.SUBMITTED, total_quantity=100,
                cumulative_filled=0,
            ),
            received_at=_NOW + timedelta(seconds=4),
        )
        rd = ingest_canonical_event(d, db)
        assert rd["action"] == "REJECTED"
        assert "stale" in rd["reason"].lower()

        # D must leave no durable trace
        assert db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection "
                 "WHERE canonical_id = :cid"),
            {"cid": d.canonical_id},
        ).scalar() == 0
        assert db.execute(
            text("SELECT COUNT(*) FROM broker_sync_idempotency "
                 "WHERE canonical_id = :cid"),
            {"cid": d.canonical_id},
        ).scalar() == 0
        assert _anchor_last_sequence(db, "ORD-7C") == 3


# ---------------------------------------------------------------------------
# 2. Conflict after later sequences
# ---------------------------------------------------------------------------

class TestConflictAfterLaterSequence:
    """same canonical_id + different content, after later sequence -> CONFLICT."""

    def test_same_canonical_id_different_content_after_later_seq_conflict(
        self, db,
    ):
        """Re-deriving the original canonical identity with tampered content
        must classify as CONFLICT (durable identity beats sequence position),
        not STALE."""
        # Original: submitted, seq 1, total=100
        x = _submitted("ORD-7X", 1)
        assert ingest_canonical_event(x, db)["action"] == "APPLIED"

        # Advance the anchor
        y = _accepted("ORD-7X", 2)
        assert ingest_canonical_event(y, db)["action"] == "APPLIED"

        # Same canonical identity (tenant/broker/provider-less identity =
        # tenant+broker+type+order+seq), DIFFERENT content (total=999)
        tampered = BrokerSyncEventTamperHelper.submitted_with_total(
            "ORD-7X", 1, total_quantity=999,
        )
        assert tampered.canonical_id == x.canonical_id, (
            "tampered event must preserve the original canonical identity "
            "so the fingerprint comparison is exercised"
        )

        r = ingest_canonical_event(tampered, db)
        assert r["action"] == "CONFLICT", (
            f"expected CONFLICT for same identity + different content after "
            f"later sequence, got {r['action']}: {r.get('reason')}"
        )

        # No durable mutation
        assert _anchor_last_sequence(db, "ORD-7X") == 2
        lc = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")
                        ).scalar()
        assert lc == 2

    def test_conflict_after_seq3_rejected_classification(self, db):
        """Same identity + different content after seq3 -> CONFLICT (task §11)."""
        a = _submitted("ORD-7X", 1)
        ingest_canonical_event(a, db)
        ingest_canonical_event(_accepted("ORD-7X", 2), db)
        ingest_canonical_event(_accepted("ORD-7X", 3,
                                         received_at=_NOW + timedelta(seconds=3)),
                               db)

        tampered = BrokerSyncEventTamperHelper.submitted_with_total(
            "ORD-7X", 1, total_quantity=555,
        )
        assert tampered.canonical_id == a.canonical_id
        r = ingest_canonical_event(tampered, db)
        assert r["action"] == "CONFLICT"
        assert _anchor_last_sequence(db, "ORD-7X") == 3


class BrokerSyncEventTamperHelper:
    """Builds events with the same fallback canonical identity but altered
    content (identity is tenant+broker+type+order_id+seq when no
    provider_event_id is present)."""

    @staticmethod
    def submitted_with_total(order_id: str, seq: int, *, total_quantity: int):
        return make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=seq,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.SUBMITTED,
                total_quantity=total_quantity,
                cumulative_filled=0,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )


# ---------------------------------------------------------------------------
# 3. Stale detection remains intact for genuinely NEW events
# ---------------------------------------------------------------------------

class TestStaleDetectionUnchanged:
    """new canonical_id + old sequence -> REJECTED (task §6 preserve)."""

    def test_new_event_old_sequence_rejected(self, db):
        # Apply 1 and 2
        a = _submitted("ORD-7A", 1)
        ingest_canonical_event(a, db)
        ingest_canonical_event(_accepted("ORD-7A", 2), db)

        # NEW event with an OLD sequence (different content -> different id)
        stale_new = _submitted("ORD-7A", 1)
        # Force a distinct canonical_id while keeping the stale sequence:
        # use a different broker order reference so identity differs.
        stale_new = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id="ORD-7A", canonical_sequence=1,
            provider_event_id="provider-replay-999",  # distinct identity
            order_facts=OrderFacts(
                broker_order_id="ORD-7A", order_id="ORD-7A",
                status=CanonicalOrderState.SUBMITTED, total_quantity=100,
                cumulative_filled=0,
            ),
            received_at=_NOW + timedelta(seconds=5),
        )
        r = ingest_canonical_event(stale_new, db)
        assert r["action"] == "REJECTED"
        assert "stale" in r["reason"].lower()

        # Anchor unchanged, no durable trace
        assert _anchor_last_sequence(db, "ORD-7A") == 2
        assert db.execute(
            text("SELECT COUNT(*) FROM broker_sync_idempotency "
                 "WHERE canonical_id = :cid"),
            {"cid": stale_new.canonical_id},
        ).scalar() == 0

    def test_new_event_sequence_gap_rejected(self, db):
        a = _submitted("ORD-7A", 1)
        ingest_canonical_event(a, db)

        gap = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_ACCEPTED, event_version="1.0",
            broker_order_id="ORD-7A", canonical_sequence=3,
            provider_event_id="provider-gap-1",
            order_facts=OrderFacts(
                broker_order_id="ORD-7A", order_id="ORD-7A",
                status=CanonicalOrderState.OPEN, total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        r = ingest_canonical_event(gap, db)
        assert r["action"] == "REJECTED"
        assert "gap" in r["reason"].lower()


# ---------------------------------------------------------------------------
# 4. Replay/projection safety: duplicate replay never mutates durable state
# ---------------------------------------------------------------------------

class TestReplaySafety:
    """Duplicate replay does not allocate Day38 sequences or mutate state."""

    def test_repeated_replay_is_stable_noop(self, db):
        a = _submitted("ORD-7A", 1)
        ingest_canonical_event(a, db)
        ingest_canonical_event(_accepted("ORD-7A", 2), db)

        baseline_lc = db.execute(
            text("SELECT COUNT(*) FROM trade_lifecycle_events")
        ).scalar()
        baseline_proj = db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection")
        ).scalar()
        baseline_idem = db.execute(
            text("SELECT COUNT(*) FROM broker_sync_idempotency")
        ).scalar()

        # Replay the original several times — state must never move
        for _ in range(3):
            r = ingest_canonical_event(a, db)
            assert r["action"] == "DUPLICATE_NOOP"

        assert db.execute(
            text("SELECT COUNT(*) FROM trade_lifecycle_events")
        ).scalar() == baseline_lc
        assert db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection")
        ).scalar() == baseline_proj
        assert db.execute(
            text("SELECT COUNT(*) FROM broker_sync_idempotency")
        ).scalar() == baseline_idem
        assert _anchor_last_sequence(db, "ORD-7A") == 2

    def test_replay_after_commit_across_sessions_is_noop(self, db):
        """Replay survives session recreation (durable, not session-local)."""
        a = _submitted("ORD-7A", 1)
        ingest_canonical_event(a, db)
        ingest_canonical_event(_accepted("ORD-7A", 2), db)
        db.commit()

        from app.db import Base
        Base.metadata.create_all(_engine)
        new_db = _TestSessionLocal()
        try:
            r = ingest_canonical_event(a, new_db)
            assert r["action"] == "DUPLICATE_NOOP"
            assert new_db.execute(
                text("SELECT COUNT(*) FROM broker_order_projection "
                     "WHERE canonical_id = :cid"),
                {"cid": a.canonical_id},
            ).scalar() == 1
        finally:
            new_db.rollback()
            new_db.close()


# ---------------------------------------------------------------------------
# 5. PostgreSQL — critical replay scenario against the real engine
# ---------------------------------------------------------------------------

PG_ORDER_IDS = ["ORD-PG7-1", "ORD-PG7-2", "ORD-PG7-X"]


@pytest.fixture(scope="module")
def pg_engine():
    """Module-scoped PostgreSQL engine for disposable testing."""
    if not _pg_available:
        pytest.skip("TEST_DATABASE_URL must point to PostgreSQL")
    engine = create_engine(
        PG_DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=5
    )
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def _pg_reset_and_seed(engine):
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401
    from app.models import PaperOrder, StrategyExecution

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    for table in (BrokerSyncIdempotency.__table__,
                  BrokerOrderProjection.__table__,
                  BrokerSyncSequenceAnchor.__table__):
        session.execute(table.delete())
    session.execute(text(
        "DELETE FROM trade_lifecycle_events WHERE tenant_id = 'tenant-pg-1'"))
    session.execute(text(
        "DELETE FROM paper_orders WHERE user_id = 'tenant-pg-1'"))
    session.execute(text(
        "DELETE FROM strategy_executions WHERE user_id = 'tenant-pg-1'"))
    session.flush()
    for oid in PG_ORDER_IDS:
        exec_id = f"EXEC-{oid}"
        session.add(StrategyExecution(
            user_id="tenant-pg-1", execution_id=exec_id,
            client_order_id=f"exec-{oid}", strategy_id="strat-pg",
            strategy_tag="Test", symbol="NIFTY", status="FILLED",
            entry_net=0.0, entry_at=_NOW,
        ))
        session.flush()
        session.add(PaperOrder(
            user_id="tenant-pg-1", client_order_id=oid,
            execution_id=exec_id, kind="entry", symbol="NIFTY",
            expiry="2026-10-29", strike=24500.0, option_type="CE",
            action="buy", quantity=100, lot_size=1, status="FILLED",
            filled_quantity=100, fill_price=100.0,
        ))
        session.flush()
    session.commit()
    session.close()


@pytest.mark.skipif(not _pg_available, reason="requires PostgreSQL")
class TestPostgresIdempotencyOrdering:
    """§8: repeat the critical replay scenario against real PostgreSQL."""

    def _fresh_session(self, engine):
        _pg_reset_and_seed(engine)
        return sessionmaker(bind=engine, expire_on_commit=False)()

    def test_pg_exact_replay_after_later_sequence_noop(self, pg_engine):
        """seq1 APPLIED -> seq2 APPLIED -> seq1 exact duplicate DUPLICATE_NOOP
        on real PostgreSQL (committed state, fresh session)."""
        db = self._fresh_session(pg_engine)
        try:
            x = _submitted("ORD-PG7-1", 1, tenant="tenant-pg-1", broker="broker-pg")
            r1 = ingest_canonical_event(x, db)
            assert r1["action"] == "APPLIED"
            y = _accepted("ORD-PG7-1", 2, tenant="tenant-pg-1", broker="broker-pg")
            r2 = ingest_canonical_event(y, db)
            assert r2["action"] == "APPLIED"
            db.commit()

            # Fresh session — replay the exact original
            replay = sessionmaker(bind=pg_engine, expire_on_commit=False)()
            try:
                r3 = ingest_canonical_event(x, replay)
                assert r3["action"] == "DUPLICATE_NOOP", (
                    f"PG replay classified {r3['action']}: {r3.get('reason')}"
                )
                assert replay.execute(
                    text("SELECT COUNT(*) FROM broker_order_projection "
                         "WHERE canonical_id = :cid"),
                    {"cid": x.canonical_id},
                ).scalar() == 1
                assert replay.execute(
                    text("SELECT last_sequence FROM broker_sync_sequence_anchor "
                         "WHERE broker_order_id = 'ORD-PG7-1'")
                ).scalar() == 2
            finally:
                replay.rollback()
                replay.close()
        finally:
            db.rollback()
            db.close()

    def test_pg_conflict_after_later_sequence(self, pg_engine):
        db = self._fresh_session(pg_engine)
        try:
            x = _submitted("ORD-PG7-X", 1, tenant="tenant-pg-1", broker="broker-pg")
            ingest_canonical_event(x, db)
            ingest_canonical_event(_accepted("ORD-PG7-X", 2, tenant="tenant-pg-1", broker="broker-pg"), db)
            db.commit()

            tampered = BrokerSyncEventTamperHelperPG.submitted_with_total_pg(
                "ORD-PG7-X", 1, total_quantity=999,
            )
            assert tampered.canonical_id == x.canonical_id

            replay = sessionmaker(bind=pg_engine, expire_on_commit=False)()
            try:
                r = ingest_canonical_event(tampered, replay)
                assert r["action"] == "CONFLICT", (
                    f"PG conflict-after-later-seq classified {r['action']}: "
                    f"{r.get('reason')}"
                )
            finally:
                replay.rollback()
                replay.close()
        finally:
            db.rollback()
            db.close()

    def test_pg_persisted_stream_replays_identically_after_duplicate_replay(self, pg_engine):
        """§12: duplicate replay must not mutate the durable lifecycle stream.

        Apply broker sequence, replay the exact original seq-1 event, then
        re-replay the persisted lifecycle stream: identical state, no new
        lifecycle event, no additional Day38 sequence, no projection growth,
        no anchor movement.
        """
        from app.trade_lifecycle.envelope import TradeLifecycleEventEnvelope
        from app.trade_lifecycle.persistence import (
            TradeLifecycleEvent,
            append_lifecycle_event,
        )
        from app.trade_lifecycle.replay import replay_execution_events

        tenant = "tenant-pg-1"
        order_id = "ORD-PG7-1"
        exec_id = f"EXEC-{order_id}"

        db = self._fresh_session(pg_engine)
        try:
            # Day38 lifecycle foundation (authoritative append path)
            append_lifecycle_event(
                db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
                event_type="TradeIntentCreated", event_version="1.0",
                tenant_id=tenant, sequence=1, position_sequence=None,
                quantity_delta=None, position_identity=None, occurred_at=_NOW,
                payload={"strategy_id": "test-strategy"}, metadata=None,
            )
            append_lifecycle_event(
                db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
                event_type="ExecutionActivated", event_version="1.0",
                tenant_id=tenant, sequence=2, position_sequence=None,
                quantity_delta=None, position_identity=None,
                occurred_at=_NOW + timedelta(seconds=1), payload={}, metadata=None,
            )
            append_lifecycle_event(
                db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
                event_type="OrderCreated", event_version="1.0",
                tenant_id=tenant, sequence=3, position_sequence=None,
                quantity_delta=None, position_identity=None,
                occurred_at=_NOW + timedelta(seconds=1),
                payload={"order_id": order_id, "quantity": 100}, metadata=None,
            )
            db.flush()

            # Broker sequence: seq1 SUBMITTED (APPLIED), seq2 PARTIAL_FILL (APPLIED)
            x = _submitted(order_id, 1, tenant=tenant, broker="broker-pg")
            assert ingest_canonical_event(x, db)["action"] == "APPLIED"
            fill = make_broker_sync_event(
                tenant_id=tenant, broker="broker-pg",
                event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
                broker_order_id=order_id, canonical_sequence=2,
                order_facts=OrderFacts(
                    broker_order_id=order_id, order_id=order_id,
                    status=CanonicalOrderState.PARTIALLY_FILLED,
                    total_quantity=100, cumulative_filled=50),
                fill_facts=FillFacts(
                    fill_id="fill-pg7-1", fill_quantity=50, fill_price=100.0,
                    cumulative_filled_after=50, remaining_after=50),
                received_at=_NOW + timedelta(seconds=2),
            )
            assert ingest_canonical_event(fill, db)["action"] == "APPLIED"
            db.commit()

            def _persisted_state():
                rows = db.execute(
                    select(TradeLifecycleEvent)
                    .where(TradeLifecycleEvent.tenant_id == tenant)
                    .where(TradeLifecycleEvent.aggregate_id == exec_id)
                    .order_by(TradeLifecycleEvent.sequence.asc())
                ).scalars().all()
                envelopes = []
                for row in rows:
                    occurred = row.occurred_at
                    if occurred.tzinfo is None:
                        occurred = occurred.replace(tzinfo=timezone.utc)
                    envelopes.append(TradeLifecycleEventEnvelope(
                        tenant_id=row.tenant_id,
                        aggregate_type=row.aggregate_type,
                        aggregate_id=row.aggregate_id,
                        event_type=row.event_type,
                        event_version=row.event_version,
                        sequence=row.sequence,
                        occurred_at=occurred,
                        payload=json.loads(row.payload_json) if row.payload_json else {},
                    ))
                return rows, replay_execution_events(envelopes)

            rows_before, state_before = _persisted_state()
            assert len(rows_before) == 5  # 3 foundation + 2 Task2

            # Duplicate replay of the EXACT original seq-1 event
            replay_sess = sessionmaker(bind=pg_engine, expire_on_commit=False)()
            try:
                r = ingest_canonical_event(x, replay_sess)
                assert r["action"] == "DUPLICATE_NOOP"
            finally:
                replay_sess.rollback()
                replay_sess.close()

            # Durable stream must be identical: no new lifecycle event, no
            # additional Day38 sequence allocation.
            rows_after, state_after = _persisted_state()
            assert len(rows_after) == len(rows_before)
            assert [r_.sequence for r_ in rows_after] == [
                r_.sequence for r_ in rows_before]
            assert [r_.event_type for r_ in rows_after] == [
                r_.event_type for r_ in rows_before]

            # Replay produces the IDENTICAL state.
            assert state_after.execution_status == state_before.execution_status
            order_before = state_before.orders[order_id]
            order_after = state_after.orders[order_id]
            assert order_after.status == order_before.status
            assert order_after.cumulative_filled == order_before.cumulative_filled

            # No projection growth; anchor unchanged.
            assert db.execute(
                text("SELECT COUNT(*) FROM broker_order_projection")
            ).scalar() == 2
            assert db.execute(
                text("SELECT last_sequence FROM broker_sync_sequence_anchor "
                     "WHERE broker_order_id = 'ORD-PG7-1'")
            ).scalar() == 2
        finally:
            db.rollback()
            db.close()

    def test_pg_new_event_stale_sequence_rejected(self, pg_engine):
        """New canonical_id + stale sequence -> REJECTED on real PG."""
        db = self._fresh_session(pg_engine)
        try:
            ingest_canonical_event(_submitted("ORD-PG7-2", 1, tenant="tenant-pg-1", broker="broker-pg"), db)
            ingest_canonical_event(_accepted("ORD-PG7-2", 2, tenant="tenant-pg-1", broker="broker-pg"), db)
            db.commit()

            stale_new = make_broker_sync_event(
                tenant_id="tenant-pg-1", broker="broker-pg",
                event_type=BrokerEventType.ORDER_SUBMITTED,
                event_version="1.0", broker_order_id="ORD-PG7-2",
                canonical_sequence=1,
                provider_event_id="pg-provider-stale-1",
                order_facts=OrderFacts(
                    broker_order_id="ORD-PG7-2", order_id="ORD-PG7-2",
                    status=CanonicalOrderState.SUBMITTED, total_quantity=100),
                received_at=_NOW + timedelta(seconds=5),
            )
            replay = sessionmaker(bind=pg_engine, expire_on_commit=False)()
            try:
                r = ingest_canonical_event(stale_new, replay)
                assert r["action"] == "REJECTED"
                assert "stale" in r["reason"].lower()
            finally:
                replay.rollback()
                replay.close()
        finally:
            db.rollback()
            db.close()


class BrokerSyncEventTamperHelperPG:
    """PG-tenant variant of the tamper helper."""

    @staticmethod
    def submitted_with_total_pg(order_id: str, seq: int, *,
                                total_quantity: int):
        return make_broker_sync_event(
            tenant_id="tenant-pg-1", broker="broker-pg",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=seq,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.SUBMITTED,
                total_quantity=total_quantity, cumulative_filled=0,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
