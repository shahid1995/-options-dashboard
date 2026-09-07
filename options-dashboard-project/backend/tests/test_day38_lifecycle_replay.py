"""Day 38 Task 3: Execution lifecycle state machine + deterministic replay tests.

TDD: RED first (module does not exist yet), then GREEN.

Covers the approved Task 3 boundary (execution lifecycle ONLY — no position
lifecycle, no DB, no broker):
- valid execution lifecycle: CREATED -> ACTIVE -> COMPLETED
- terminal alternatives: FAILED / CANCELLED
- order lifecycle within the execution: PENDING -> SUBMITTED -> FILLED /
  PARTIALLY_FILLED, terminal CANCELLED / REJECTED
- fill history accumulation and order-quantity consistency
- deterministic replay (same stream -> equal state)
- strict sequence validation (gaps, out-of-order, non-1 start)
- strict invalid-transition rejection (OrderFilled before OrderSubmitted,
  ExecutionCompleted before ExecutionActivated, mutations after terminal)
- tenant / aggregate identity fail-closed
"""

from datetime import datetime, timezone

import pytest

from app.trade_lifecycle.envelope import TradeLifecycleEventEnvelope
from app.trade_lifecycle.replay import (
    ExecutionLifecycleState,
    ExecutionStatus,
    OrderStatus,
    replay_execution_events,
    LifecycleSequenceError,
    ReplaySequenceGap,
    ReplayInvalidTransition,
    ReplaySecurityError,
    ReplayCorruptPayload,
    ReplayUnknownVersion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT = "user-1"
EXEC_ID = "exec-1"
AGG_TYPE = "TradeLifecycle"
OCCURRED_AT = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)


def event(event_type, sequence, payload=None, *, tenant_id=TENANT,
          aggregate_id=EXEC_ID, aggregate_type=AGG_TYPE, event_version="1.0"):
    """Build a Task 2 lifecycle envelope with sensible defaults."""
    return TradeLifecycleEventEnvelope(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        event_version=event_version,
        sequence=sequence,
        occurred_at=OCCURRED_AT,
        payload=dict(payload or {}),
    )


def valid_stream(quantity=10, order_id="o1"):
    """The approved happy-path execution stream."""
    return [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": order_id, "quantity": quantity,
                                  "client_order_id": "co-1"}),
        event("OrderSubmitted", 4, {"order_id": order_id}),
        event("OrderFilled", 5, {"order_id": order_id, "fill_quantity": quantity,
                                 "cumulative_filled": quantity}),
        event("FillRecorded", 6, {"order_id": order_id, "fill_quantity": quantity,
                                  "fill_price": 120.5, "price_source": "paper_engine"}),
        event("ExecutionCompleted", 7, {"execution_id": EXEC_ID}),
    ]


# ---------------------------------------------------------------------------
# 1. Valid execution lifecycle reconstruction
# ---------------------------------------------------------------------------

def test_replay_valid_execution_lifecycle():
    state = replay_execution_events(valid_stream())
    assert state.execution_status == ExecutionStatus.COMPLETED
    assert state.execution_id == EXEC_ID
    assert state.aggregate_id == EXEC_ID
    assert state.tenant_id == TENANT
    assert state.last_sequence == 7
    order = state.orders["o1"]
    assert order.status == OrderStatus.FILLED
    assert order.quantity == 10
    assert order.cumulative_filled == 10


def test_replay_execution_failed_terminal_path():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("ExecutionFailed", 5, {"execution_id": EXEC_ID, "reason_code": "MarketClosed"}),
    ]
    state = replay_execution_events(stream)
    assert state.execution_status == ExecutionStatus.FAILED
    assert state.orders["o1"].status == OrderStatus.SUBMITTED


def test_replay_execution_cancelled_terminal_path():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("OrderCancelled", 5, {"order_id": "o1", "reason": "user"}),
        event("ExecutionCancelled", 6, {"execution_id": EXEC_ID, "reason": "user"}),
    ]
    state = replay_execution_events(stream)
    assert state.execution_status == ExecutionStatus.CANCELLED
    assert state.orders["o1"].status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# 2. Invalid order transitions
# ---------------------------------------------------------------------------

def test_replay_rejects_order_filled_before_submitted():
    # Case A: OrderFilled while the order is still PENDING (never submitted).
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderFilled", 4, {"order_id": "o1", "fill_quantity": 10,
                                 "cumulative_filled": 10}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_order_mutation_after_terminal():
    # Case E: order reached CANCELLED (terminal) -> further order mutation rejected.
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("OrderCancelled", 5, {"order_id": "o1", "reason": "user"}),
        event("OrderFilled", 6, {"order_id": "o1", "fill_quantity": 10,
                                 "cumulative_filled": 10}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


# ---------------------------------------------------------------------------
# 3. Execution-level invalid transitions
# ---------------------------------------------------------------------------

def test_replay_rejects_completion_before_activation():
    # Case B: ExecutionCompleted before ExecutionActivated (execution CREATED).
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionCompleted", 2, {"execution_id": EXEC_ID}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_mutation_after_terminal_state():
    # Case D: ExecutionFailed after ExecutionCompleted -> terminal mutation.
    stream = valid_stream() + [
        event("ExecutionFailed", 8, {"execution_id": EXEC_ID, "reason_code": "MarketClosed"}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_failure_after_completed():
    # Case C: ExecutionFailed after ExecutionCompleted must be rejected.
    stream = valid_stream() + [
        event("ExecutionFailed", 8, {"execution_id": EXEC_ID, "reason_code": "x"}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_duplicate_activation():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 3, {"execution_id": EXEC_ID}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


# ---------------------------------------------------------------------------
# 4. Sequence validation
# ---------------------------------------------------------------------------

def test_execution_replay_rejects_sequence_gap():
    events = [event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
              event("OrderCreated", 3, {"order_id": "o1", "quantity": 10})]
    with pytest.raises(LifecycleSequenceError):
        replay_execution_events(events)


def test_execution_replay_gap_is_lifecycle_sequence_error_subtype():
    events = [event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
              event("ExecutionActivated", 3, {"execution_id": EXEC_ID})]
    with pytest.raises(ReplaySequenceGap):
        replay_execution_events(events)
    with pytest.raises(LifecycleSequenceError):
        replay_execution_events(events)


def test_execution_replay_rejects_out_of_order_events():
    events = [event("TradeIntentCreated", 2, {"execution_id": EXEC_ID}),
              event("ExecutionActivated", 1, {"execution_id": EXEC_ID})]
    with pytest.raises(LifecycleSequenceError):
        replay_execution_events(events)


def test_execution_replay_rejects_stream_not_starting_at_sequence_one():
    events = [event("TradeIntentCreated", 5, {"execution_id": EXEC_ID})]
    with pytest.raises(LifecycleSequenceError):
        replay_execution_events(events)


# ---------------------------------------------------------------------------
# 5. Deterministic replay
# ---------------------------------------------------------------------------

def test_replay_is_deterministic():
    events = valid_stream()
    state_a = replay_execution_events(events)
    state_b = replay_execution_events(events)
    assert state_a == state_b
    assert state_a is not state_b


def test_replay_input_events_are_not_mutated():
    events = valid_stream()
    snapshots = [(e.event_type, e.sequence, dict(e.payload)) for e in events]
    replay_execution_events(events)
    for e, (etype, seq, payload) in zip(events, snapshots):
        assert e.event_type == etype
        assert e.sequence == seq
        assert dict(e.payload) == payload


# ---------------------------------------------------------------------------
# 6. Order lifecycle reconstruction and fill consistency
# ---------------------------------------------------------------------------

def test_replay_reconstructs_partial_then_full_fill_order_lifecycle():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("OrderFilled", 5, {"order_id": "o1", "fill_quantity": 4,
                                 "cumulative_filled": 4}),
        event("OrderFilled", 6, {"order_id": "o1", "fill_quantity": 6,
                                 "cumulative_filled": 10}),
        event("ExecutionCompleted", 7, {"execution_id": EXEC_ID}),
    ]
    state = replay_execution_events(stream)
    order = state.orders["o1"]
    assert order.status == OrderStatus.FILLED
    assert order.cumulative_filled == 10
    assert state.execution_status == ExecutionStatus.COMPLETED


def test_replay_fill_history_is_append_only_and_deterministic():
    stream = valid_stream()
    state = replay_execution_events(stream)
    fills = state.orders["o1"].fills
    assert len(fills) == 1
    assert fills[0].fill_quantity == 10
    assert fills[0].fill_price == 120.5
    assert fills[0].price_source == "paper_engine"
    # same stream -> same fill history
    assert replay_execution_events(stream).orders["o1"].fills == fills


def test_replay_rejects_order_overfill():
    # cumulative_filled must never exceed the order quantity.
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("OrderFilled", 5, {"order_id": "o1", "fill_quantity": 11,
                                 "cumulative_filled": 11}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_non_increasing_fill_cumulative():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("OrderFilled", 5, {"order_id": "o1", "fill_quantity": 4,
                                 "cumulative_filled": 4}),
        event("OrderFilled", 6, {"order_id": "o1", "fill_quantity": 2,
                                 "cumulative_filled": 4}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_fill_ledger_overfill():
    # FillRecorded must never push the per-order fill ledger past order.quantity.
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderSubmitted", 4, {"order_id": "o1"}),
        event("FillRecorded", 5, {"order_id": "o1", "fill_quantity": 10}),
        event("FillRecorded", 6, {"order_id": "o1", "fill_quantity": 1}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


def test_replay_rejects_fill_recorded_before_submit():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("FillRecorded", 4, {"order_id": "o1", "fill_quantity": 5}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


# ---------------------------------------------------------------------------
# 7. Multi-order execution
# ---------------------------------------------------------------------------

def test_replay_two_orders_both_filled_then_completed():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderCreated", 4, {"order_id": "o2", "quantity": 5}),
        event("OrderSubmitted", 5, {"order_id": "o1"}),
        event("OrderSubmitted", 6, {"order_id": "o2"}),
        event("OrderFilled", 7, {"order_id": "o1", "fill_quantity": 10,
                                 "cumulative_filled": 10}),
        event("OrderFilled", 8, {"order_id": "o2", "fill_quantity": 5,
                                 "cumulative_filled": 5}),
        event("ExecutionCompleted", 9, {"execution_id": EXEC_ID}),
    ]
    state = replay_execution_events(stream)
    assert state.orders["o1"].status == OrderStatus.FILLED
    assert state.orders["o2"].status == OrderStatus.FILLED
    assert state.execution_status == ExecutionStatus.COMPLETED


def test_replay_completion_requires_all_orders_filled():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1", "quantity": 10}),
        event("OrderCreated", 4, {"order_id": "o2", "quantity": 5}),
        event("OrderSubmitted", 5, {"order_id": "o1"}),
        event("OrderFilled", 6, {"order_id": "o1", "fill_quantity": 10,
                                 "cumulative_filled": 10}),
        # o2 never reaches FILLED
        event("ExecutionCompleted", 7, {"execution_id": EXEC_ID}),
    ]
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(stream)


# ---------------------------------------------------------------------------
# 8. Tenant / aggregate identity safety (fail closed)
# ---------------------------------------------------------------------------

def test_replay_rejects_tenant_mismatch():
    events = valid_stream()[:4]
    events.append(event("OrderSubmitted", 5, {"order_id": "o1"}, tenant_id="user-2"))
    with pytest.raises(ReplaySecurityError):
        replay_execution_events(events)


def test_replay_rejects_aggregate_mismatch():
    events = valid_stream()[:4]
    events.append(event("OrderSubmitted", 5, {"order_id": "o1"}, aggregate_id="exec-OTHER"))
    with pytest.raises(ReplaySecurityError):
        replay_execution_events(events)


# ---------------------------------------------------------------------------
# 9. Unknown event version / unknown event type / corrupt payload
# ---------------------------------------------------------------------------

def test_replay_rejects_unknown_event_version():
    events = valid_stream()[:2]
    events.append(event("OrderCreated", 3, {"order_id": "o1", "quantity": 10},
                        event_version="99.0"))
    with pytest.raises(ReplayUnknownVersion):
        replay_execution_events(events)


def test_replay_rejects_position_events_in_execution_stream():
    # Position lifecycle is Task 4 — execution replay must fail closed on it.
    events = valid_stream()[:2]
    events.append(event("PositionOpened", 3, {"position_identity": {"symbol": "NIFTY"}}))
    with pytest.raises(ReplayInvalidTransition):
        replay_execution_events(events)


def test_replay_rejects_order_created_without_quantity():
    stream = [
        event("TradeIntentCreated", 1, {"execution_id": EXEC_ID}),
        event("ExecutionActivated", 2, {"execution_id": EXEC_ID}),
        event("OrderCreated", 3, {"order_id": "o1"}),
    ]
    with pytest.raises(ReplayCorruptPayload):
        replay_execution_events(stream)


# ---------------------------------------------------------------------------
# 10. State shape
# ---------------------------------------------------------------------------

def test_replay_state_is_frozen_projection():
    state = replay_execution_events(valid_stream())
    assert isinstance(state, ExecutionLifecycleState)
    # The projection exposes order state explicitly (no scattered strings).
    assert state.orders["o1"].status in (OrderStatus.FILLED,)
