"""Day 39 Task 2 — RED tests for remediation v6.

Two remaining Control Center findings:

Issue #1 — broker_order_id must NOT be treated as an application order id.
    Resolution must be strictly:
        OrderFacts.order_id  →  PaperOrder.client_order_id  →  execution_id
    When the canonical application-order reference is missing or unknown the
    pipeline must FAIL CLOSED (REJECTED) with NO durable side effects:
    no projection, no idempotency record, no lifecycle event, no sequence
    anchor advancement, no fabricated aggregate.

Issue #2 — Day38 sequence allocation must be concurrency-safe.
    Before ``next_event_sequence`` (MAX+1) the actual ``StrategyExecution``
    row must be serialized with ``SELECT ... FOR UPDATE`` inside the same
    transaction, so two concurrent broker events for the same execution can
    never allocate the same Day38 lifecycle sequence.

The SQLite tests prove Issue #1 deterministically.  The PostgreSQL tests
prove Issue #2 with real row-level locking (SQLite cannot verify this).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
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

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

PG_DB_URL = os.getenv("TEST_DATABASE_URL", "")
_pg_available = bool(
    PG_DB_URL
    and PG_DB_URL.startswith(("postgresql+psycopg://", "postgresql://"))
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _seed_app_order(db, *, tenant, client_order_id, execution_id,
                    symbol="NIFTY"):
    """Seed the authoritative StrategyExecution + PaperOrder context."""
    from app.models import PaperOrder, StrategyExecution

    db.add(StrategyExecution(
        user_id=tenant,
        execution_id=execution_id,
        client_order_id=f"exec-{execution_id}",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol=symbol,
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    ))
    db.flush()
    _seed_paper_order(db, tenant=tenant, client_order_id=client_order_id,
                      execution_id=execution_id, symbol=symbol)


def _seed_paper_order(db, *, tenant, client_order_id, execution_id,
                      symbol="NIFTY"):
    """Seed one PaperOrder under an existing execution."""
    from app.models import PaperOrder

    db.add(PaperOrder(
        user_id=tenant,
        client_order_id=client_order_id,
        execution_id=execution_id,
        kind="entry",
        symbol=symbol,
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


def _make_submitted_event(*, tenant, broker_order_id, order_id=None,
                          canonical_sequence=1, broker="broker-test"):
    return make_broker_sync_event(
        tenant_id=tenant,
        broker=broker,
        event_type=BrokerEventType.ORDER_SUBMITTED.value,
        event_version="1.0",
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        received_at=_NOW + timedelta(seconds=1),
        order_facts=OrderFacts(
            broker_order_id=broker_order_id,
            order_id=order_id,
            status=CanonicalOrderState.SUBMITTED,
            total_quantity=100,
        ),
    )


def _assert_no_durable_side_effects(db, tenant):
    assert db.execute(
        select(func.count(BrokerOrderProjection.id))
    ).scalar() == 0, "no projection row may exist"
    assert db.execute(
        select(func.count(BrokerSyncIdempotency.canonical_id))
    ).scalar() == 0, "no idempotency record may exist"
    assert db.execute(
        select(func.count(BrokerSyncSequenceAnchor.tenant_id))
    ).scalar() == 0, "no broker sequence anchor may exist (fail closed)"
    from app.trade_lifecycle.persistence import TradeLifecycleEvent
    assert db.execute(
        select(func.count(TradeLifecycleEvent.event_id))
    ).scalar() == 0, "no Day38 lifecycle event may exist"


# ---------------------------------------------------------------------------
# SQLite fixtures — deterministic, no concurrency
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Issue #1 (RED) — missing application-order reference fails closed
# ---------------------------------------------------------------------------


def test_missing_app_order_reference_fails_closed(db):
    """order_facts.order_id=None must REJECT — never fall back to broker id."""
    tenant = "tenant-1"
    # An application order exists whose client_order_id HAPPENS to equal the
    # broker order id — the forbidden fallback would resolve through it.
    _seed_app_order(
        db, tenant=tenant,
        client_order_id="BROKER-ORD-FALLBACK", execution_id="EXEC-FB",
    )
    db.commit()

    event = _make_submitted_event(
        tenant=tenant,
        broker_order_id="BROKER-ORD-FALLBACK",
        order_id=None,  # canonical application-order reference is MISSING
    )
    result = ingest_canonical_event(event, db)
    assert result["action"] == "REJECTED", (
        f"expected REJECTED without order_facts.order_id, got "
        f"{result['action']}: {result.get('reason')}"
    )
    _assert_no_durable_side_effects(db, tenant)


def test_broker_order_id_is_never_accepted_as_application_id(db):
    """broker_order_id must never be silently reinterpreted as an app order id.

    Even when a PaperOrder with client_order_id == broker_order_id exists
    (which would make the forbidden fallback succeed), an event WITHOUT the
    explicit canonical application-order reference must fail closed.
    """
    tenant = "tenant-1"
    _seed_app_order(
        db, tenant=tenant,
        client_order_id="BROKER-ORD-X", execution_id="EXEC-X",
    )
    db.commit()

    event = _make_submitted_event(
        tenant=tenant,
        broker_order_id="BROKER-ORD-X",
        order_id=None,
    )
    result = ingest_canonical_event(event, db)
    assert result["action"] == "REJECTED"
    _assert_no_durable_side_effects(db, tenant)


def test_unknown_app_order_reference_fails_closed(db):
    """An explicit but unknown application-order reference must fail closed."""
    tenant = "tenant-1"
    _seed_app_order(
        db, tenant=tenant,
        client_order_id="APP-ORD-1", execution_id="EXEC-1",
    )
    db.commit()

    event = _make_submitted_event(
        tenant=tenant,
        broker_order_id="BROKER-ORD-99",
        order_id="APP-ORD-NOT-EXIST",
    )
    result = ingest_canonical_event(event, db)
    assert result["action"] == "REJECTED"
    assert "unresolved" in result["reason"].lower() or "unknown" in result["reason"].lower()
    _assert_no_durable_side_effects(db, tenant)


def test_explicit_app_order_reference_resolves_to_execution(db):
    """The strict path still works: order_facts.order_id → execution."""
    from app.trade_lifecycle.persistence import TradeLifecycleEvent

    tenant = "tenant-1"
    _seed_app_order(
        db, tenant=tenant,
        client_order_id="APP-ORD-1", execution_id="EXEC-1",
    )
    db.commit()

    event = _make_submitted_event(
        tenant=tenant,
        broker_order_id="BROKER-ORD-42",
        order_id="APP-ORD-1",
    )
    result = ingest_canonical_event(event, db)
    assert result["action"] == "APPLIED", result.get("reason")

    rows = db.execute(select(TradeLifecycleEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].aggregate_id == "EXEC-1"
    assert rows[0].aggregate_id != "BROKER-ORD-42"


# ---------------------------------------------------------------------------
# Issue #2 (RED, PostgreSQL-only) — execution-row serialization
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
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
    """Reset sync state and seed a deterministic app context (committed)."""
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    for table in (
        BrokerSyncIdempotency.__table__,
        BrokerOrderProjection.__table__,
        BrokerSyncSequenceAnchor.__table__,
    ):
        session.execute(table.delete())
    from app.models import PaperOrder, StrategyExecution
    from app.trade_lifecycle.persistence import TradeLifecycleEvent

    tenant = "tenant-pg-1"
    # Deterministic reset: clear rows the ingestion tests touch.
    session.execute(
        TradeLifecycleEvent.__table__.delete().where(
            TradeLifecycleEvent.tenant_id == tenant
        )
    )
    session.execute(
        PaperOrder.__table__.delete().where(
            PaperOrder.user_id == tenant
        )
    )
    session.execute(
        StrategyExecution.__table__.delete().where(
            StrategyExecution.user_id == tenant
        )
    )
    session.flush()
    # One execution E with two application orders A and B (multi-order case:
    # both broker orders must resolve to the SAME execution aggregate).
    from app.models import StrategyExecution

    session.add(StrategyExecution(
        user_id=tenant,
        execution_id="EXEC-CONC-1",
        client_order_id="exec-EXEC-CONC-1",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol="NIFTY",
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    ))
    session.flush()
    _seed_paper_order(
        session, tenant=tenant,
        client_order_id="ORD-CONC-A", execution_id="EXEC-CONC-1",
    )
    _seed_paper_order(
        session, tenant=tenant,
        client_order_id="ORD-CONC-B", execution_id="EXEC-CONC-1",
    )
    session.commit()
    session.close()


@pytest.mark.skipif(not _pg_available, reason="requires PostgreSQL")
class TestConcurrentSameExecutionSequencing:
    """Two concurrent broker events on ONE execution must serialize Day38 seq."""

    def test_concurrent_events_same_execution_unique_sequences(self, pg_engine):
        """Different broker orders, same execution, concurrent ingestion.

        Worker A → broker order A (canonical_sequence=1)
        Worker B → broker order B (canonical_sequence=1)
        Both belong to execution EXEC-CONC-1.

        Without the StrategyExecution row lock both workers observe
        MAX(sequence)=4 and both attempt sequence 5 — one fails via the
        unique constraint (improper allocation strategy).  With the lock the
        Day38 sequences are unique and correctly ordered.
        """
        from app.trade_lifecycle.persistence import (
            TradeLifecycleEvent,
            append_lifecycle_event,
        )

        _pg_reset_and_seed(pg_engine)
        tenant = "tenant-pg-1"
        exec_id = "EXEC-CONC-1"
        now = _NOW

        # Day38 lifecycle foundation (authoritative append path)
        Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
        setup = Session()
        append_lifecycle_event(
            db=setup, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
            event_type="TradeIntentCreated", event_version="1.0",
            tenant_id=tenant, sequence=1, position_sequence=None,
            quantity_delta=None, position_identity=None, occurred_at=now,
            payload={"strategy_id": "test-strategy"}, metadata=None,
        )
        append_lifecycle_event(
            db=setup, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
            event_type="ExecutionActivated", event_version="1.0",
            tenant_id=tenant, sequence=2, position_sequence=None,
            quantity_delta=None, position_identity=None,
            occurred_at=now + timedelta(seconds=1), payload={}, metadata=None,
        )
        append_lifecycle_event(
            db=setup, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
            event_type="OrderCreated", event_version="1.0",
            tenant_id=tenant, sequence=3, position_sequence=None,
            quantity_delta=None, position_identity=None,
            occurred_at=now + timedelta(seconds=1),
            payload={"order_id": "ORD-CONC-A", "quantity": 100}, metadata=None,
        )
        append_lifecycle_event(
            db=setup, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
            event_type="OrderCreated", event_version="1.0",
            tenant_id=tenant, sequence=4, position_sequence=None,
            quantity_delta=None, position_identity=None,
            occurred_at=now + timedelta(seconds=1),
            payload={"order_id": "ORD-CONC-B", "quantity": 100}, metadata=None,
        )
        setup.commit()
        setup.close()

        event_a = _make_submitted_event(
            tenant=tenant, broker_order_id="BROKER-CA",
            order_id="ORD-CONC-A", canonical_sequence=1,
        )
        event_b = _make_submitted_event(
            tenant=tenant, broker_order_id="BROKER-CB",
            order_id="ORD-CONC-B", canonical_sequence=1,
        )

        # Force a deterministic MAX+1 collision: both workers must read the
        # current MAX(sequence) concurrently.  The barrier has a short timeout
        # so that with the row-lock fix (workers serialize before allocating)
        # the barrier simply breaks and ingestion proceeds normally.
        import app.broker_sync.ingestion as ing

        original_next = ing.next_event_sequence
        barrier = threading.Barrier(2)

        def synchronized_next(db, tenant_id, aggregate_type, aggregate_id):
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass  # serialized already — proceed
            return original_next(db, tenant_id, aggregate_type, aggregate_id)

        ing.next_event_sequence = synchronized_next

        barrier2 = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(idx, event):
            Sess = sessionmaker(bind=pg_engine, expire_on_commit=False)
            sess = Sess()
            try:
                barrier2.wait(timeout=10)
                results[idx] = ingest_canonical_event(event, sess)
                sess.commit()
            except Exception as e:  # pragma: no cover - surfaced via errors
                errors[idx] = e
                sess.rollback()
            finally:
                sess.close()

        try:
            t1 = threading.Thread(target=worker, args=(0, event_a))
            t2 = threading.Thread(target=worker, args=(1, event_b))
            t1.start()
            t2.start()
            t1.join(timeout=20)
            t2.join(timeout=20)
        finally:
            ing.next_event_sequence = original_next

        assert errors[0] is None, f"worker A raised: {errors[0]}"
        assert errors[1] is None, f"worker B raised: {errors[1]}"
        assert results[0] is not None and results[0]["action"] == "APPLIED", (
            f"worker A: {(results[0] or {}).get('action')}: {(results[0] or {}).get('reason')}"
        )
        assert results[1] is not None and results[1]["action"] == "APPLIED", (
            f"worker B: {(results[1] or {}).get('action')}: {(results[1] or {}).get('reason')} "
            f"(a duplicate Day38 sequence allocation collided)")

        # Day38 sequences for the execution must be unique and contiguous.
        Session = sessionmaker(bind=pg_engine, expire_on_commit=False)
        verify = Session()
        try:
            rows = verify.execute(
                select(TradeLifecycleEvent)
                .where(
                    TradeLifecycleEvent.tenant_id == tenant,
                    TradeLifecycleEvent.aggregate_type == "TradeLifecycle",
                    TradeLifecycleEvent.aggregate_id == exec_id,
                )
                .order_by(TradeLifecycleEvent.sequence.asc())
            ).scalars().all()
            sequences = [r.sequence for r in rows]
            assert len(sequences) == len(set(sequences)), (
                f"duplicate Day38 sequences allocated: {sequences}"
            )
            assert sequences == list(range(1, len(sequences) + 1)), (
                f"Day38 sequences must be contiguous 1..N, got {sequences}"
            )
        finally:
            verify.close()

    def test_execution_row_lock_serializes_ingestion(self, pg_engine):
        """Direct proof: ingestion blocks while the execution row is locked.

        A foreign connection holds SELECT ... FOR UPDATE on the actual
        StrategyExecution row.  The ingestion worker must block until the
        lock is released — proving the lock is taken before sequence
        allocation.
        """
        from app.models import StrategyExecution

        _pg_reset_and_seed(pg_engine)
        tenant = "tenant-pg-1"
        exec_id = "EXEC-CONC-1"

        holder = sessionmaker(bind=pg_engine, expire_on_commit=False)()
        holder.execute(
            select(StrategyExecution)
            .where(
                StrategyExecution.user_id == tenant,
                StrategyExecution.execution_id == exec_id,
            )
            .with_for_update()
        )

        event = _make_submitted_event(
            tenant=tenant, broker_order_id="BROKER-LOCK-1",
            order_id="ORD-CONC-A", canonical_sequence=1,
        )
        result_box = {}
        worker_error = []

        def worker():
            Sess = sessionmaker(bind=pg_engine, expire_on_commit=False)
            sess = Sess()
            try:
                result_box["result"] = ingest_canonical_event(event, sess)
                sess.commit()
            except Exception as e:  # pragma: no cover
                worker_error.append(e)
                sess.rollback()
            finally:
                sess.close()

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=0.5)
        still_blocked = t.is_alive()
        holder.rollback()  # release the lock
        holder.close()
        t.join(timeout=15)

        assert worker_error == [], f"worker raised: {worker_error}"
        assert still_blocked, (
            "ingestion did NOT block on the StrategyExecution row lock — "
            "no SELECT ... FOR UPDATE serialization before sequence allocation"
        )
        assert result_box["result"]["action"] == "APPLIED", (
            result_box["result"].get("reason")
        )
