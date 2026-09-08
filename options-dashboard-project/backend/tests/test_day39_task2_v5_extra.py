"""Additional v5 acceptance tests: multi-order + projection/replay consistency."""
from datetime import datetime, timedelta, timezone

import pytest
import json
from sqlalchemy import select, text

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
from app.models import PaperOrder, StrategyExecution
from app.trade_lifecycle.persistence import TradeLifecycleEvent


_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _seed_multi_order_context(db, *, tenant="tenant-1"):
    """Seed Execution E with two broker orders A and B mapping to the same execution."""
    exec_id = "EXEC-MULTI"
    exec_row = StrategyExecution(
        user_id=tenant,
        execution_id=exec_id,
        client_order_id=f"exec-{exec_id}",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol="NIFTY",
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    )
    db.add(exec_row)
    db.flush()

    ord_a = PaperOrder(
        user_id=tenant,
        client_order_id="BROKER-ORD-A",
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
    )
    db.add(ord_a)

    ord_b = PaperOrder(
        user_id=tenant,
        client_order_id="BROKER-ORD-B",
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
    )
    db.add(ord_b)
    db.flush()
    return exec_id


def _resolve_lifecycle_aggregates(db, tenant):
    """Return all lifecycle aggregate_ids for tenant."""
    return {
        r
        for r in db.execute(
            select(TradeLifecycleEvent.aggregate_id).where(
                TradeLifecycleEvent.tenant_id == tenant
            )
        ).scalars().all()
    }


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
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
    _seed_multi_order_context(session)
    session.commit()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)


def test_multi_order_both_map_to_same_execution(db):
    """Two broker orders (A, B) belonging to one execution map correctly.

    BrokerOrder A and BrokerOrder B each resolve to EXEC-MULTI through their
    respective PaperOrder.execution_id.  The lifecycle aggregates are identical
    and both are the real execution — not the broker order ids.
    """
    tenant = "tenant-1"
    exec_id = "EXEC-MULTI"

    submit_a = make_broker_sync_event(
        tenant_id=tenant, broker="broker-test",
        event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
        broker_order_id="BROKER-ORD-A", canonical_sequence=1,
        order_facts=OrderFacts(
            broker_order_id="BROKER-ORD-A", order_id="BROKER-ORD-A",
            status=CanonicalOrderState.SUBMITTED, total_quantity=100),
        received_at=_NOW,
    )
    submit_b = make_broker_sync_event(
        tenant_id=tenant, broker="broker-test",
        event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
        broker_order_id="BROKER-ORD-B", canonical_sequence=1,
        order_facts=OrderFacts(
            broker_order_id="BROKER-ORD-B", order_id="BROKER-ORD-B",
            status=CanonicalOrderState.SUBMITTED, total_quantity=100),
        received_at=_NOW + timedelta(seconds=1),
    )

    ra = ingest_canonical_event(submit_a, db)
    rb = ingest_canonical_event(submit_b, db)
    assert ra["action"] == "APPLIED"
    assert rb["action"] == "APPLIED"

    agg_ids = _resolve_lifecycle_aggregates(db, tenant)
    assert agg_ids == {exec_id}, f"expected only {exec_id}, got {agg_ids}"
    assert exec_id != "BROKER-ORD-A"
    assert exec_id != "BROKER-ORD-B"


def test_multi_order_fill_resolves_correct_aggregate(db):
    """A fill for BrokerOrder B maps to the correct execution aggregate.

    After both orders are submitted, a partial fill on B must write the
    lifecycle event against EXEC-MULTI (B's execution), not against A's
    broker id or a fabricated aggregate.
    """
    tenant = "tenant-1"
    exec_id = "EXEC-MULTI"

    submit_b = make_broker_sync_event(
        tenant_id=tenant, broker="broker-test",
        event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
        broker_order_id="BROKER-ORD-B", canonical_sequence=1,
        order_facts=OrderFacts(
            broker_order_id="BROKER-ORD-B", order_id="BROKER-ORD-B",
            status=CanonicalOrderState.SUBMITTED, total_quantity=100),
        received_at=_NOW,
    )
    fill_b = make_broker_sync_event(
        tenant_id=tenant, broker="broker-test",
        event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
        broker_order_id="BROKER-ORD-B", canonical_sequence=2,
        order_facts=OrderFacts(
            broker_order_id="BROKER-ORD-B", order_id="BROKER-ORD-B",
            status=CanonicalOrderState.PARTIALLY_FILLED,
            total_quantity=100, cumulative_filled=50),
        fill_facts=FillFacts(fill_id="fill-b-001", fill_quantity=50, fill_price=110.0,
                             cumulative_filled_after=50, remaining_after=50),
        received_at=_NOW + timedelta(seconds=1),
    )

    ingest_canonical_event(submit_b, db)
    result = ingest_canonical_event(fill_b, db)
    assert result["action"] == "APPLIED"
    agg_ids = _resolve_lifecycle_aggregates(db, tenant)
    assert agg_ids == {exec_id}

    filled = db.execute(
        select(TradeLifecycleEvent).where(
            TradeLifecycleEvent.tenant_id == tenant,
            TradeLifecycleEvent.event_type == "OrderFilled",
        )
    ).scalars().all()
    assert len(filled) == 1
    assert filled[0].aggregate_id == exec_id
    payload = json.loads(filled[0].payload_json)
    assert payload["order_id"] == "BROKER-ORD-B"


def test_projection_matches_replayed_state(db):
    """Normalized BrokerOrderProjection state matches Day38 replayed state.

    After ingesting ORDER_SUBMITTED → PARTIAL_FILL → FULL_FILL for one
    broker order, the replayed Day38 state must agree with the persistent
    normalized projection on status, cumulative_filled, and terminal-ness.
    """
    from app.trade_lifecycle.replay import replay_execution_events, LifecycleReplayError
    from app.trade_lifecycle.envelope import TradeLifecycleEventEnvelope

    tenant = "tenant-1"
    order_id = "ORD-PROP-1"
    broker = "broker-test"

    # Seed authoritative app context
    exec_id = f"EXEC-{order_id}"
    db.add(StrategyExecution(
        user_id=tenant, execution_id=exec_id,
        client_order_id=f"exec-{order_id}", strategy_id="strat-1",
        strategy_tag="Test", symbol="NIFTY", status="FILLED",
        entry_net=0.0, entry_at=_NOW,
    ))
    db.flush()
    db.add(PaperOrder(
        user_id=tenant, client_order_id=order_id, execution_id=exec_id,
        kind="entry", symbol="NIFTY", expiry="2026-10-29", strike=24500.0,
        option_type="CE", action="buy", quantity=100, lot_size=1,
        status="FILLED", filled_quantity=100, fill_price=100.0,
    ))
    db.flush()

    # Create Day38 lifecycle foundation (TradeIntentCreated, ExecutionActivated, OrderCreated)
    # using the authoritative append_lifecycle_event path — same as production Day38.
    from app.trade_lifecycle.persistence import append_lifecycle_event
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="TradeIntentCreated", event_version="1.0", tenant_id=tenant,
        sequence=1, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW,
        payload={"strategy_id": "test-strategy", "intent": "BUY"}, metadata=None,
    )
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="ExecutionActivated", event_version="1.0", tenant_id=tenant,
        sequence=2, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW + timedelta(seconds=1),
        payload={}, metadata=None,
    )
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="OrderCreated", event_version="1.0", tenant_id=tenant,
        sequence=3, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW + timedelta(seconds=1),
        payload={"order_id": order_id, "quantity": 100}, metadata=None,
    )

    events = [
        make_broker_sync_event(
            tenant_id=tenant, broker=broker,
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.SUBMITTED, total_quantity=100),
            received_at=_NOW,
        ),
        make_broker_sync_event(
            tenant_id=tenant, broker=broker,
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50),
            fill_facts=FillFacts(fill_id="fill-001", fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=1),
        ),
        make_broker_sync_event(
            tenant_id=tenant, broker=broker,
            event_type=BrokerEventType.FULL_FILL, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.FILLED,
                total_quantity=100, cumulative_filled=100, is_terminal=True),
            fill_facts=FillFacts(fill_id="fill-002", fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=100, remaining_after=0),
            received_at=_NOW + timedelta(seconds=2),
        ),
    ]

    for ev in events:
        result = ingest_canonical_event(ev, db)
        assert result["action"] == "APPLIED", f"expected APPLIED for seq {ev.canonical_sequence}, got {result['action']}: {result.get('reason')}"

    # --- Load projection ---
    proj = db.execute(
        select(BrokerOrderProjection).where(
            BrokerOrderProjection.tenant_id == tenant,
            BrokerOrderProjection.broker_order_id == order_id,
        ).order_by(BrokerOrderProjection.canonical_sequence.desc()).limit(1)
    ).scalar_one()
    assert proj.status == "FILLED"
    assert proj.cumulative_filled == 100
    assert proj.is_terminal is True
    assert proj.remaining_quantity == 0
    assert proj.fill_count == 2

    # --- Rebuild authoritative lifecycle foundation for replay ---
    db.execute(
        select(TradeLifecycleEvent).where(
            TradeLifecycleEvent.tenant_id == tenant,
            TradeLifecycleEvent.aggregate_id == exec_id,
        )
    ).scalars().all()  # sanity: lifecycle rows exist

    # Load the actual persisted lifecycle stream and replay it
    rows = db.execute(
        select(TradeLifecycleEvent).where(
            TradeLifecycleEvent.tenant_id == tenant,
            TradeLifecycleEvent.aggregate_id == exec_id,
        ).order_by(TradeLifecycleEvent.sequence.asc())
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

    state = replay_execution_events(envelopes)
    assert state.execution_status.value in ("CREATED", "ACTIVE")
    assert len(state.orders) == 1
    order = state.orders[order_id]
    assert order.status.value == proj.status  # both "FILLED"
    assert order.cumulative_filled == proj.cumulative_filled  # both 100
    # OrderStatus.FILLED already encodes terminal state (no separate is_terminal)
    assert order.status.value == "FILLED"  # terminal confirmed via status value
