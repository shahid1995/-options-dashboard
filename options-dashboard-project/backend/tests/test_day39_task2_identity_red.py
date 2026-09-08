"""Day 39 Task 2 — RED tests for v5 identity resolution.

Proves the current implementation is WRONG:
- It uses broker_order_id directly as the Day38 lifecycle aggregate identity
- It does NOT resolve broker events to the actual StrikeNova execution

These tests must fail against the current implementation at d60cad6.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

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
from app.trade_lifecycle.persistence import TradeLifecycleEvent

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    """Provide a clean SQLite database session (deterministic)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    import app.models  # noqa: F401  (registers all tables on Base.metadata)
    import app.broker_sync.models  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401  (TradeLifecycleEvent)

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


def _seed_execution(db, *, execution_id="EXEC-ALPHA", order_client_id="APP-ORD-1", tenant="tenant-1"):
    """Seed an authoritative StrategyExecution + PaperOrder via the real models."""
    from app.models import PaperOrder, StrategyExecution

    exec_row = StrategyExecution(
        user_id=tenant,
        execution_id=execution_id,
        client_order_id=f"exec-{execution_id}",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol="NIFTY",
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    )
    db.add(exec_row)
    db.flush()

    order = PaperOrder(
        user_id=tenant,
        client_order_id=order_client_id,
        execution_id=execution_id,
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
    )
    db.add(order)
    db.flush()
    return execution_id


def _make_broker_event(*, tenant, broker_order_id, order_id, sequence, event_type, status, total_quantity):
    return make_broker_sync_event(
        tenant_id=tenant,
        broker="broker-test",
        event_type=event_type,
        event_version="1.0",
        broker_order_id=broker_order_id,
        canonical_sequence=sequence,
        order_facts=OrderFacts(
            broker_order_id=broker_order_id,
            order_id=order_id,
            status=status,
            total_quantity=total_quantity,
        ),
        received_at=_NOW,
    )


def test_task2_resolves_to_actual_execution_aggregate(db):
    """Task2 must resolve broker event to the real execution, not broker_order_id."""
    tenant = "tenant-1"
    exec_id = _seed_execution(db, tenant=tenant)

    event = _make_broker_event(
        tenant=tenant,
        broker_order_id="BROKER-ORD-42",
        order_id="APP-ORD-1",
        sequence=1,
        event_type=BrokerEventType.ORDER_SUBMITTED.value,
        status=CanonicalOrderState.SUBMITTED,
        total_quantity=100,
    )

    result = ingest_canonical_event(event, db)
    assert result["action"] == "APPLIED"

    # The lifecycle aggregate must be the ACTUAL execution, not the broker order
    lifecycle_rows = db.execute(
        select(TradeLifecycleEvent).where(TradeLifecycleEvent.tenant_id == tenant)
    ).scalars().all()
    assert len(lifecycle_rows) == 1
    assert lifecycle_rows[0].aggregate_id == exec_id, (
        f"expected aggregate_id={exec_id} (actual execution), got {lifecycle_rows[0].aggregate_id}"
    )
    assert lifecycle_rows[0].aggregate_id != "BROKER-ORD-42"


def test_task2_rejects_unknown_broker_order(db):
    """Unknown broker order must FAIL CLOSED — no fabricated aggregate."""
    tenant = "tenant-1"
    _seed_execution(db, tenant=tenant)

    event = _make_broker_event(
        tenant=tenant,
        broker_order_id="BROKER-UNKNOWN-99",
        order_id="APP-ORD-NOT-EXIST",
        sequence=1,
        event_type=BrokerEventType.ORDER_SUBMITTED.value,
        status=CanonicalOrderState.SUBMITTED,
        total_quantity=100,
    )

    result = ingest_canonical_event(event, db)
    assert result["action"] == "REJECTED"
    assert "unknown" in result["reason"].lower() or "unresolved" in result["reason"].lower()

    # No projection, no idempotency, no lifecycle, no sequence anchor
    assert db.execute(select(BrokerOrderProjection)).scalars().all() == []
    assert db.execute(select(BrokerSyncIdempotency)).scalars().all() == []
    assert db.execute(select(TradeLifecycleEvent)).scalars().all() == []
    assert db.execute(select(BrokerSyncSequenceAnchor)).scalars().all() == []