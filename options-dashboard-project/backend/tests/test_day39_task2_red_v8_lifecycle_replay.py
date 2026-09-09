"""Day 39 Task 2 — RED tests (v8): lifecycle mapping / replay compatibility.

Control Center finding:

Task2 maps BOTH ``ORDER_SUBMITTED`` and ``ORDER_ACCEPTED`` to the Day38
lifecycle event ``OrderSubmitted``.  The approved Day38 replay state machine
defines ``OrderSubmitted`` as a transition PENDING -> SUBMITTED, so a valid
persisted broker sequence:

    ORDER_SUBMITTED seq1
    ORDER_ACCEPTED  seq2

produces the lifecycle stream:

    OrderSubmitted
    OrderSubmitted

which replay attempts as PENDING -> SUBMITTED -> SUBMITTED and fails with
``ReplayInvalidTransition``.  The system must not produce a durable lifecycle
stream that its own replay engine cannot reconstruct.

Architectural resolution (per the approved Day38 design, §13/§14):
``OrderSubmitted`` is an audit record of the submission attempt and explicitly
"does not mean broker accepted"; "No lifecycle event implies broker state";
the design deliberately removed standalone broker-acceptance events from the
Day38 vocabulary.  Therefore broker acceptance carries NO Day38 lifecycle
state transition: the order is already SUBMITTED (working) in Day38 terms and
broker-observed state lives in the Task2 normalized projection.  ORDER_ACCEPTED
is ingested (durably projected + idempotency + ordering), but contributes no
lifecycle event.

These tests assert the replayed reconstructed state (execution status, order
identity, status, quantity, cumulative fill, terminality, sequences) — not
merely the absence of an exception.
"""
from __future__ import annotations

import json
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
from app.broker_sync.models import BrokerOrderProjection
from app.trade_lifecycle.envelope import TradeLifecycleEventEnvelope
from app.trade_lifecycle.persistence import (
    TradeLifecycleEvent,
    append_lifecycle_event,
)
from app.trade_lifecycle.replay import (
    LifecycleReplayError,
    replay_execution_events,
)

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant-1"

_ORDER_IDS = [
    "ORD-8A", "ORD-8B", "ORD-8C", "ORD-8D", "ORD-8E", "ORD-8F",
    "ORD-8H", "ORD-8REJ", "ORD-8PROJ", "ORD-8PROJ2",
]


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def _seed_app_order(db, broker_order_id: str, tenant_id: str = TENANT) -> str:
    from app.models import PaperOrder, StrategyExecution

    exec_id = f"EXEC-{broker_order_id}"
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


def _foundation(db, order_id: str, exec_id: str):
    """Persist the approved Day38 execution foundation (seq 1..3)."""
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="TradeIntentCreated", event_version="1.0", tenant_id=TENANT,
        sequence=1, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW,
        payload={"strategy_id": "test-strategy", "intent": "BUY"}, metadata=None,
    )
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="ExecutionActivated", event_version="1.0", tenant_id=TENANT,
        sequence=2, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW + timedelta(seconds=1),
        payload={}, metadata=None,
    )
    append_lifecycle_event(
        db=db, aggregate_type="TradeLifecycle", aggregate_id=exec_id,
        event_type="OrderCreated", event_version="1.0", tenant_id=TENANT,
        sequence=3, position_sequence=None, quantity_delta=None,
        position_identity=None, occurred_at=_NOW + timedelta(seconds=1),
        payload={"order_id": order_id, "quantity": 100}, metadata=None,
    )


def _submitted(order_id: str, seq: int):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.SUBMITTED, total_quantity=100,
            cumulative_filled=0,
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _accepted(order_id: str, seq: int):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.ORDER_ACCEPTED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.OPEN, total_quantity=100,
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _partial_fill(order_id: str, seq: int, *, fill_id: str = "fill-8-1",
                  fill_quantity: int = 50, cumulative_after: int = 50):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.PARTIALLY_FILLED,
            total_quantity=100, cumulative_filled=cumulative_after,
        ),
        fill_facts=FillFacts(
            fill_id=fill_id, fill_quantity=fill_quantity, fill_price=100.0,
            cumulative_filled_after=cumulative_after,
            remaining_after=100 - cumulative_after,
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _full_fill(order_id: str, seq: int):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.FULL_FILL, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.FILLED, total_quantity=100,
            cumulative_filled=100, is_terminal=True,
        ),
        fill_facts=FillFacts(
            fill_id=f"fill-8-{seq}", fill_quantity=50, fill_price=100.0,
            cumulative_filled_after=100, remaining_after=0,
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _cancelled(order_id: str, seq: int):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.ORDER_CANCELLED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.CANCELLED, total_quantity=100,
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _rejected(order_id: str, seq: int):
    return make_broker_sync_event(
        tenant_id=TENANT, broker="broker-test",
        event_type=BrokerEventType.ORDER_REJECTED, event_version="1.0",
        broker_order_id=order_id, canonical_sequence=seq,
        order_facts=OrderFacts(
            broker_order_id=order_id, order_id=order_id,
            status=CanonicalOrderState.REJECTED, total_quantity=100,
            rejection_reason="insufficient_margin",
        ),
        received_at=_NOW + timedelta(seconds=seq),
    )


def _persisted_envelopes(db, exec_id: str):
    """Load the ACTUAL persisted lifecycle stream Task2 wrote (no fabrication)."""
    rows = db.execute(
        select(TradeLifecycleEvent)
        .where(TradeLifecycleEvent.tenant_id == TENANT)
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
    return rows, envelopes


def _assert_replay_state(state, *, order_id: str, order_status: str,
                         cumulative_filled: int, quantity: int = 100):
    """Verify replayed semantics, not just absence of an exception."""
    assert state.execution_status.value == "ACTIVE"
    assert order_id in state.orders, (
        f"order {order_id} missing from replayed state: {list(state.orders)}"
    )
    order = state.orders[order_id]
    assert order.order_id == order_id
    assert order.status.value == order_status, (
        f"replayed order status {order.status.value} != {order_status}"
    )
    assert order.quantity == quantity
    assert order.cumulative_filled == cumulative_filled


# ---------------------------------------------------------------------------
# Case B — THE critical regression: SUBMITTED + ACCEPTED must replay
# ---------------------------------------------------------------------------

class TestSubmittedThenAcceptedReplay:
    def test_submitted_then_accepted_persisted_stream_replays(self, db):
        """RED: the exact Control Center defect.

        Persist ORDER_SUBMITTED seq1 + ORDER_ACCEPTED seq2, then replay the
        ACTUAL persisted lifecycle stream.  Must not raise an invalid
        transition, and the reconstructed state must be correct.
        """
        order_id = "ORD-8A"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)

        r1 = ingest_canonical_event(_submitted(order_id, 1), db)
        assert r1["action"] == "APPLIED"
        r2 = ingest_canonical_event(_accepted(order_id, 2), db)
        assert r2["action"] == "APPLIED", (
            f"ORDER_ACCEPTED must remain ingestable per approved semantics, "
            f"got {r2['action']}: {r2.get('reason')}"
        )

        rows, envelopes = _persisted_envelopes(db, exec_id)

        # The defect: two consecutive OrderSubmitted events cannot replay
        try:
            state = replay_execution_events(envelopes)
        except LifecycleReplayError as e:
            pytest.fail(
                f"persisted Task2 lifecycle stream is not replay-compatible: {e}"
            )

        # Semantics of the reconstructed state (§7)
        _assert_replay_state(
            state, order_id=order_id, order_status="SUBMITTED",
            cumulative_filled=0,
        )
        assert state.last_sequence == rows[-1].sequence

    def test_accepted_persists_no_duplicate_lifecycle_transition(self, db):
        """ORDER_ACCEPTED must not add a second OrderSubmitted transition."""
        order_id = "ORD-8B"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)

        ingest_canonical_event(_submitted(order_id, 1), db)
        ingest_canonical_event(_accepted(order_id, 2), db)

        rows, _ = _persisted_envelopes(db, exec_id)
        submitted_rows = [r for r in rows if r.event_type == "OrderSubmitted"]
        # Foundation has zero OrderSubmitted; the broker SUBMITTED event adds
        # exactly one.  The ACCEPTED event must not add another.
        assert len(submitted_rows) == 1, (
            f"expected exactly one OrderSubmitted lifecycle event, got "
            f"{len(submitted_rows)} — a duplicate state transition was persisted"
        )

    def test_accepted_still_persists_projection_and_idempotency(self, db):
        """Broker semantics remain durable: projection + idempotency + ordering."""
        order_id = "ORD-8C"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)

        ingest_canonical_event(_submitted(order_id, 1), db)
        result = ingest_canonical_event(_accepted(order_id, 2), db)

        assert result["action"] == "APPLIED"
        assert result["normalized_state"]["status"] == "OPEN"

        proj = db.execute(
            select(BrokerOrderProjection)
            .where(BrokerOrderProjection.broker_order_id == order_id)
            .order_by(BrokerOrderProjection.canonical_sequence.desc())
            .limit(1)
        ).scalar_one()
        assert proj.status == "OPEN"
        assert proj.canonical_sequence == 2

        from app.broker_sync.models import BrokerSyncIdempotency, BrokerSyncSequenceAnchor
        idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id ==
                _accepted(order_id, 2).canonical_id)
        ).scalar_one_or_none()
        assert idem is not None, "ORDER_ACCEPTED must remain durably idempotent"
        assert idem.status == "APPLIED"

        anchor = db.execute(
            select(BrokerSyncSequenceAnchor).where(
                BrokerSyncSequenceAnchor.broker_order_id == order_id)
        ).scalar_one()
        assert anchor.last_sequence == 2


# ---------------------------------------------------------------------------
# Replay matrix — §10
# ---------------------------------------------------------------------------

class TestReplayMatrix:
    def test_case_a_submitted_only(self, db):
        order_id = "ORD-8A"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="SUBMITTED", cumulative_filled=0)

    def test_case_b_submitted_accepted(self, db):
        order_id = "ORD-8B"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_accepted(order_id, 2), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="SUBMITTED", cumulative_filled=0)

    def test_case_c_submitted_accepted_partial_fill(self, db):
        order_id = "ORD-8C"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_accepted(order_id, 2), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_partial_fill(order_id, 3), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="PARTIALLY_FILLED", cumulative_filled=50)

    def test_case_d_submitted_accepted_full_fill(self, db):
        order_id = "ORD-8D"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_accepted(order_id, 2), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_partial_fill(order_id, 3,
                                                    fill_id="fill-8d-1",
                                                    fill_quantity=50,
                                                    cumulative_after=50),
                                      db)["action"] == "APPLIED"
        assert ingest_canonical_event(_full_fill(order_id, 4), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="FILLED", cumulative_filled=100)

    def test_case_e_submitted_accepted_cancelled(self, db):
        order_id = "ORD-8E"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_accepted(order_id, 2), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_cancelled(order_id, 3), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="CANCELLED", cumulative_filled=0)

    def test_case_f_submitted_rejected(self, db):
        order_id = "ORD-8F"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        assert ingest_canonical_event(_submitted(order_id, 1), db)["action"] == "APPLIED"
        assert ingest_canonical_event(_rejected(order_id, 2), db)["action"] == "APPLIED"

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)
        _assert_replay_state(state, order_id=order_id,
                             order_status="REJECTED", cumulative_filled=0)


# ---------------------------------------------------------------------------
# §11 — Projection vs replay consistency
# ---------------------------------------------------------------------------

class TestProjectionReplayConsistency:
    def test_projection_matches_replayed_state_submitted_accepted_fill(self, db):
        order_id = "ORD-8PROJ"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        ingest_canonical_event(_submitted(order_id, 1), db)
        ingest_canonical_event(_accepted(order_id, 2), db)
        ingest_canonical_event(_partial_fill(order_id, 3), db)

        proj = db.execute(
            select(BrokerOrderProjection)
            .where(BrokerOrderProjection.broker_order_id == order_id)
            .order_by(BrokerOrderProjection.canonical_sequence.desc())
            .limit(1)
        ).scalar_one()

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)

        # Execution identity
        assert state.aggregate_id == exec_id
        assert state.tenant_id == TENANT
        # Application order identity
        assert order_id in state.orders
        # Status agreement (projection stores canonical state; Day38 order
        # status uses the approved Day38 vocabulary)
        assert proj.status == state.orders[order_id].status.value
        # Cumulative fill agreement
        assert proj.cumulative_filled == state.orders[order_id].cumulative_filled
        # Remaining quantity agreement
        assert proj.remaining_quantity == (
            state.orders[order_id].quantity - state.orders[order_id].cumulative_filled
        )
        # Terminality agreement (PARTIALLY_FILLED is non-terminal)
        assert proj.is_terminal is False
        # No duplicate submission transition
        rows, _ = _persisted_envelopes(db, exec_id)
        assert len([r for r in rows if r.event_type == "OrderSubmitted"]) == 1

    def test_projection_matches_replayed_state_terminal_cancelled(self, db):
        order_id = "ORD-8PROJ2"
        exec_id = f"EXEC-{order_id}"
        _foundation(db, order_id, exec_id)
        ingest_canonical_event(_submitted(order_id, 1), db)
        ingest_canonical_event(_accepted(order_id, 2), db)
        ingest_canonical_event(_cancelled(order_id, 3), db)

        proj = db.execute(
            select(BrokerOrderProjection)
            .where(BrokerOrderProjection.broker_order_id == order_id)
            .order_by(BrokerOrderProjection.canonical_sequence.desc())
            .limit(1)
        ).scalar_one()

        _, envelopes = _persisted_envelopes(db, exec_id)
        state = replay_execution_events(envelopes)

        assert proj.status == "CANCELLED"
        assert state.orders[order_id].status.value == "CANCELLED"
        assert proj.is_terminal is True
        assert proj.cumulative_filled == state.orders[order_id].cumulative_filled == 0


# ---------------------------------------------------------------------------
# §13 — v7 idempotency regression (must not regress under the new mapping)
# ---------------------------------------------------------------------------

class TestV7IdempotencyRegression:
    def test_exact_duplicate_after_later_sequence_noop(self, db):
        order_id = "ORD-8H"
        _foundation(db, order_id, f"EXEC-{order_id}")
        x = _submitted(order_id, 1)
        assert ingest_canonical_event(x, db)["action"] == "APPLIED"
        y = _accepted(order_id, 2)
        assert ingest_canonical_event(y, db)["action"] == "APPLIED"

        r = ingest_canonical_event(x, db)
        assert r["action"] == "DUPLICATE_NOOP"

    def test_changed_content_conflict_after_later_sequence(self, db):
        order_id = "ORD-8H"
        _foundation(db, order_id, f"EXEC-{order_id}")
        x = _submitted(order_id, 1)
        ingest_canonical_event(x, db)
        ingest_canonical_event(_accepted(order_id, 2), db)

        tampered = make_broker_sync_event(
            tenant_id=TENANT, broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.SUBMITTED, total_quantity=999,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        assert tampered.canonical_id == x.canonical_id
        r = ingest_canonical_event(tampered, db)
        assert r["action"] == "CONFLICT"

    def test_new_canonical_id_stale_sequence_rejected(self, db):
        order_id = "ORD-8H"
        _foundation(db, order_id, f"EXEC-{order_id}")
        ingest_canonical_event(_submitted(order_id, 1), db)
        ingest_canonical_event(_accepted(order_id, 2), db)

        stale_new = make_broker_sync_event(
            tenant_id=TENANT, broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id=order_id, canonical_sequence=1,
            provider_event_id="provider-v8-stale-1",
            order_facts=OrderFacts(
                broker_order_id=order_id, order_id=order_id,
                status=CanonicalOrderState.SUBMITTED, total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=5),
        )
        r = ingest_canonical_event(stale_new, db)
        assert r["action"] == "REJECTED"
        assert "stale" in r["reason"].lower()
