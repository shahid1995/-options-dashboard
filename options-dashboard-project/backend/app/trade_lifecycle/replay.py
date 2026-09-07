"""Day 38 Task 3 — Execution lifecycle state machine + deterministic replay.

Pure-domain module (no SQLAlchemy, no DB, no broker, no paper-trading state,
no ``datetime.now()``, no ``uuid``): reconstructs the *execution* lifecycle of
a TradeLifecycle aggregate from an ordered stream of Task 2
``TradeLifecycleEventEnvelope`` values.

Scope (per the approved Day 38 design §5a–§5c/§6):

- Execution lifecycle: ``CREATED → ACTIVE → COMPLETED / FAILED / CANCELLED``
- Order lifecycle within the execution aggregate:
  ``PENDING → SUBMITTED → FILLED / PARTIALLY_FILLED`` with terminal
  ``CANCELLED`` / ``REJECTED``
- Fill history: append-only per-order ledger (``FillRecorded``)

The position lifecycle (``PositionOpened/Updated/Closed``) is deliberately
NOT handled here — Task 4.  Any position event in an execution stream fails
closed as an unsupported transition.

Semantics (documented):

- Replay is strict and deterministic: it never sorts, skips, invents, or
  repairs events.  Sequence must be contiguous ``1, 2, 3, ...``.
- Identity is tenant-scoped and aggregate-scoped: every event must carry the
  same ``tenant_id``, ``aggregate_id`` and ``aggregate_type`` as the first
  event; a mismatched stream fails closed with ``ReplaySecurityError``.
- ``OrderFilled`` drives the order sub-machine.  Its payload carries
  ``cumulative_filled`` (running total after the fill, per design §8b).  A
  cumulative equal to the order ``quantity`` reaches terminal ``FILLED``; a
  cumulative below it reaches non-terminal ``PARTIALLY_FILLED``; a cumulative
  above it (overfill) or not strictly increasing is rejected.
- ``FillRecorded`` is the append-only fill ledger.  It is valid once an order
  has been submitted (``SUBMITTED`` / ``PARTIALLY_FILLED`` / ``FILLED``) and
  may never push the per-order ledger past ``quantity``.
- ``ExecutionCompleted`` requires every created order to be ``FILLED``.
- After the execution reaches a terminal state (``COMPLETED`` / ``FAILED`` /
  ``CANCELLED``) no further event is accepted.
- ``replay_execution_events`` performs no writes and does not mutate the
  supplied events; the same input always produces an equal state.

Event type catalog handled here (design §8b, execution scope):
``TradeIntentCreated``, ``ExecutionActivated``, ``ExecutionCompleted``,
``ExecutionFailed``, ``ExecutionCancelled``, ``OrderCreated``,
``OrderSubmitted``, ``OrderFilled``, ``OrderCancelled``, ``OrderRejected``,
``FillRecorded``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple

from app.trade_lifecycle.envelope import TradeLifecycleEventEnvelope

# ---------------------------------------------------------------------------
# Supported event version
# ---------------------------------------------------------------------------

SUPPORTED_EVENT_VERSIONS = frozenset({"1.0"})


# ---------------------------------------------------------------------------
# Lifecycle-specific exceptions
# ---------------------------------------------------------------------------

class LifecycleReplayError(Exception):
    """Base class for deterministic lifecycle replay errors."""


class LifecycleSequenceError(LifecycleReplayError):
    """The event stream violates causal ordering.

    Raised when the stream is empty or cannot start at sequence 1.
    """

    def __init__(
        self,
        message: str,
        *,
        expected_sequence: Optional[int] = None,
        actual_sequence: Optional[int] = None,
        event_id: Optional[str] = None,
    ) -> None:
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        self.event_id = event_id
        super().__init__(message)


class ReplaySequenceGap(LifecycleSequenceError):
    """A specific causal-ordering violation: a missing / out-of-order event.

    Subclasses ``LifecycleSequenceError`` so ``except LifecycleSequenceError``
    also catches gaps.
    """

    def __init__(
        self,
        expected_sequence: int,
        actual_sequence: int,
        event_id: Optional[str] = None,
    ) -> None:
        self.expected_sequence = expected_sequence
        self.actual_sequence = actual_sequence
        self.event_id = event_id
        super().__init__(
            f"lifecycle sequence gap: expected sequence {expected_sequence}, "
            f"got {actual_sequence}"
            + (f" (event_id={event_id})" if event_id else ""),
            expected_sequence=expected_sequence,
            actual_sequence=actual_sequence,
            event_id=event_id,
        )


class ReplayInvalidTransition(LifecycleReplayError):
    """An event would apply an invalid or terminal-state transition."""

    def __init__(
        self,
        event_type: str,
        detail: str,
        *,
        from_state: Optional[str] = None,
    ) -> None:
        self.event_type = event_type
        self.from_state = from_state
        self.detail = detail
        super().__init__(
            f"invalid lifecycle transition: {event_type} "
            + (f"from {from_state} " if from_state else "")
            + f"-> {detail}"
        )


class ReplaySecurityError(LifecycleReplayError):
    """Tenant / aggregate identity violation — replay fails closed."""

    def __init__(self, reason: str, *, expected: str, actual: str) -> None:
        self.reason = reason
        self.expected = expected
        self.actual = actual
        super().__init__(f"{reason}: expected {expected!r}, got {actual!r}")


class ReplayUnknownVersion(LifecycleReplayError):
    """An event carries an unsupported ``event_version``."""

    def __init__(self, event_version: str, event_id: Optional[str] = None) -> None:
        self.event_version = event_version
        self.event_id = event_id
        super().__init__(
            f"unsupported lifecycle event_version {event_version!r}"
            + (f" (event_id={event_id})" if event_id else "")
        )


class ReplayCorruptPayload(LifecycleReplayError):
    """An event payload is structurally invalid for its event type."""

    def __init__(self, event_type: str, detail: str, event_id: Optional[str] = None) -> None:
        self.event_type = event_type
        self.detail = detail
        self.event_id = event_id
        super().__init__(
            f"corrupt lifecycle payload for {event_type}: {detail}"
            + (f" (event_id={event_id})" if event_id else "")
        )


# ---------------------------------------------------------------------------
# Explicit states
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    """Execution lifecycle states (design §5a)."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    """Order lifecycle states within the execution (design §5b)."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


EXECUTION_TERMINAL_STATES = frozenset(
    {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)
ORDER_TERMINAL_STATES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
)

# Event types the execution replay understands (design §8b execution scope).
EXECUTION_EVENT_TYPES = frozenset(
    {
        "TradeIntentCreated",
        "ExecutionActivated",
        "ExecutionCompleted",
        "ExecutionFailed",
        "ExecutionCancelled",
        "OrderCreated",
        "OrderSubmitted",
        "OrderFilled",
        "OrderCancelled",
        "OrderRejected",
        "FillRecorded",
    }
)


# ---------------------------------------------------------------------------
# Frozen projections
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillRecord:
    """A single append-only fill ledger entry (design §5c/§6)."""

    order_id: str
    fill_quantity: int
    fill_price: Optional[float] = None
    price_source: Optional[str] = None
    fill_timestamp: Any = None


@dataclass(frozen=True)
class OrderProjection:
    """Reconstructed order lifecycle projection."""

    order_id: str
    status: OrderStatus
    quantity: int
    cumulative_filled: int
    fills: Tuple[FillRecord, ...] = ()


@dataclass(frozen=True)
class ExecutionLifecycleState:
    """Deterministic execution lifecycle projection.

    Reconstructed purely from the event stream — never written back anywhere.
    """

    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    execution_status: ExecutionStatus
    orders: Mapping[str, OrderProjection] = field(default_factory=dict)
    last_sequence: int = 0

    @property
    def execution_id(self) -> str:
        """The execution aggregate id (alias of ``aggregate_id``)."""
        return self.aggregate_id

    @property
    def status(self) -> ExecutionStatus:
        """Alias for ergonomic access to ``execution_status``."""
        return self.execution_status


# ---------------------------------------------------------------------------
# Mutable accumulator used during replay (never escapes the module)
# ---------------------------------------------------------------------------

class _OrderAcc:
    __slots__ = ("order_id", "status", "quantity", "cumulative_filled", "fills",
                 "ledger_filled")

    def __init__(self, order_id: str, quantity: int) -> None:
        self.order_id = order_id
        self.status = OrderStatus.PENDING
        self.quantity = quantity
        self.cumulative_filled = 0
        self.fills: list[FillRecord] = []
        self.ledger_filled = 0


class _ExecutionAcc:
    __slots__ = ("tenant_id", "aggregate_type", "aggregate_id",
                 "execution", "orders", "last_sequence")

    def __init__(self, first: TradeLifecycleEventEnvelope) -> None:
        self.tenant_id = first.tenant_id
        self.aggregate_type = first.aggregate_type
        self.aggregate_id = first.aggregate_id
        self.execution: Optional[ExecutionStatus] = None
        self.orders: dict[str, _OrderAcc] = {}
        self.last_sequence = 0


# ---------------------------------------------------------------------------
# Payload helpers (deterministic validation — no silent coercion)
# ---------------------------------------------------------------------------

_MISSING = object()


def _require_payload_str(ev: TradeLifecycleEventEnvelope, key: str) -> str:
    value = ev.payload.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, str) or not value:
        raise ReplayCorruptPayload(
            ev.event_type, f"payload {key!r} must be a non-empty string",
            ev.event_id,
        )
    return value


def _require_payload_positive_int(ev: TradeLifecycleEventEnvelope, key: str) -> int:
    value = ev.payload.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ReplayCorruptPayload(
            ev.event_type, f"payload {key!r} must be an integer >= 1",
            ev.event_id,
        )
    return value


def _optional_positive_number(ev: TradeLifecycleEventEnvelope, key: str) -> Optional[float]:
    value = ev.payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ReplayCorruptPayload(
            ev.event_type, f"payload {key!r} must be a positive number",
            ev.event_id,
        )
    return float(value)


def _require_order_id(ev: TradeLifecycleEventEnvelope) -> str:
    return _require_payload_str(ev, "order_id")


def _get_order(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope, order_id: str) -> _OrderAcc:
    order = acc.orders.get(order_id)
    if order is None:
        raise ReplayInvalidTransition(
            ev.event_type, f"unknown order_id {order_id!r} in this execution"
        )
    return order


def _require_execution(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> ExecutionStatus:
    if acc.execution is None:
        raise ReplayInvalidTransition(
            ev.event_type, "execution has not been created (TradeIntentCreated missing)"
        )
    if acc.execution in EXECUTION_TERMINAL_STATES:
        raise ReplayInvalidTransition(
            ev.event_type, f"execution is in terminal state {acc.execution.value}"
        )
    if acc.execution not in (ExecutionStatus.CREATED, ExecutionStatus.ACTIVE):
        raise ReplayInvalidTransition(
            ev.event_type, f"execution is in state {acc.execution.value}"
        )
    return acc.execution


# ---------------------------------------------------------------------------
# Transition handlers (centralized transition rules)
# ---------------------------------------------------------------------------

def _apply_trade_intent_created(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    if acc.execution is not None:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"execution already exists in state {acc.execution.value}",
            from_state=acc.execution.value,
        )
    acc.execution = ExecutionStatus.CREATED


def _apply_execution_activated(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    if acc.execution != ExecutionStatus.CREATED:
        raise ReplayInvalidTransition(
            ev.event_type,
            "execution must be in CREATED state to activate",
            from_state=acc.execution.value if acc.execution else None,
        )
    acc.execution = ExecutionStatus.ACTIVE


def _apply_execution_terminal(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope,
                              target: ExecutionStatus) -> None:
    if acc.execution != ExecutionStatus.ACTIVE:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"execution must be ACTIVE to reach {target.value}",
            from_state=acc.execution.value if acc.execution else None,
        )
    acc.execution = target


def _apply_execution_completed(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    if acc.execution != ExecutionStatus.ACTIVE:
        raise ReplayInvalidTransition(
            ev.event_type,
            "execution must be ACTIVE to complete",
            from_state=acc.execution.value if acc.execution else None,
        )
    if not acc.orders:
        raise ReplayInvalidTransition(
            ev.event_type, "execution completed with no orders ever created"
        )
    not_filled = [
        oid for oid, o in acc.orders.items() if o.status != OrderStatus.FILLED
    ]
    if not_filled:
        raise ReplayInvalidTransition(
            ev.event_type,
            "execution completed while orders are not FILLED: "
            + ", ".join(sorted(not_filled)),
        )
    acc.execution = ExecutionStatus.COMPLETED


def _apply_order_created(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    _require_execution(acc, ev)
    order_id = _require_order_id(ev)
    if order_id in acc.orders:
        raise ReplayInvalidTransition(
            ev.event_type, f"order_id {order_id!r} already exists in this execution"
        )
    quantity = _require_payload_positive_int(ev, "quantity")
    acc.orders[order_id] = _OrderAcc(order_id, quantity)


def _apply_order_submitted(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    _require_execution(acc, ev)
    order = _get_order(acc, ev, _require_order_id(ev))
    if order.status != OrderStatus.PENDING:
        raise ReplayInvalidTransition(
            ev.event_type, "order must be PENDING to submit",
            from_state=order.status.value,
        )
    order.status = OrderStatus.SUBMITTED


def _apply_order_filled(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    _require_execution(acc, ev)
    order = _get_order(acc, ev, _require_order_id(ev))
    if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED):
        raise ReplayInvalidTransition(
            ev.event_type,
            "order must be SUBMITTED or PARTIALLY_FILLED to receive a fill",
            from_state=order.status.value,
        )
    cumulative_filled = _require_payload_positive_int(ev, "cumulative_filled")
    if cumulative_filled <= order.cumulative_filled:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"cumulative_filled {cumulative_filled} is not strictly greater than "
            f"the previous cumulative {order.cumulative_filled} (invalid fill ordering)",
            from_state=order.status.value,
        )
    if cumulative_filled > order.quantity:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"cumulative_filled {cumulative_filled} exceeds order quantity "
            f"{order.quantity} (overfill)",
            from_state=order.status.value,
        )
    # Optional fill facts are validated when present.
    _optional_positive_number(ev, "fill_price")
    order.cumulative_filled = cumulative_filled
    order.status = (
        OrderStatus.FILLED if cumulative_filled == order.quantity
        else OrderStatus.PARTIALLY_FILLED
    )


def _apply_order_terminal(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope,
                          target: OrderStatus) -> None:
    _require_execution(acc, ev)
    order = _get_order(acc, ev, _require_order_id(ev))
    if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED):
        raise ReplayInvalidTransition(
            ev.event_type,
            f"order must be SUBMITTED or PARTIALLY_FILLED to be {target.value}",
            from_state=order.status.value,
        )
    order.status = target


def _apply_fill_recorded(acc: _ExecutionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    _require_execution(acc, ev)
    order = _get_order(acc, ev, _require_order_id(ev))
    if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED,
                            OrderStatus.FILLED):
        raise ReplayInvalidTransition(
            ev.event_type,
            "a fill can only be recorded after the order is submitted and "
            "before it is cancelled/rejected",
            from_state=order.status.value,
        )
    fill_quantity = _require_payload_positive_int(ev, "fill_quantity")
    if order.ledger_filled + fill_quantity > order.quantity:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"fill ledger {order.ledger_filled} + {fill_quantity} exceeds order "
            f"quantity {order.quantity}",
            from_state=order.status.value,
        )
    fill_price = _optional_positive_number(ev, "fill_price")
    price_source = ev.payload.get("price_source")
    if price_source is not None and not isinstance(price_source, str):
        raise ReplayCorruptPayload(ev.event_type, "price_source must be a string", ev.event_id)
    fill_timestamp = ev.payload.get("fill_timestamp")
    order.fills.append(
        FillRecord(
            order_id=order.order_id,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            price_source=price_source,
            fill_timestamp=fill_timestamp,
        )
    )
    order.ledger_filled += fill_quantity


_TRANSITION_HANDLERS = {
    "TradeIntentCreated": _apply_trade_intent_created,
    "ExecutionActivated": _apply_execution_activated,
    "ExecutionCompleted": _apply_execution_completed,
    "ExecutionFailed": lambda a, e: _apply_execution_terminal(a, e, ExecutionStatus.FAILED),
    "ExecutionCancelled": lambda a, e: _apply_execution_terminal(a, e, ExecutionStatus.CANCELLED),
    "OrderCreated": _apply_order_created,
    "OrderSubmitted": _apply_order_submitted,
    "OrderFilled": _apply_order_filled,
    "OrderCancelled": lambda a, e: _apply_order_terminal(a, e, OrderStatus.CANCELLED),
    "OrderRejected": lambda a, e: _apply_order_terminal(a, e, OrderStatus.REJECTED),
    "FillRecorded": _apply_fill_recorded,
}


# ---------------------------------------------------------------------------
# Deterministic replay entry point
# ---------------------------------------------------------------------------

def replay_execution_events(
    events: Sequence[TradeLifecycleEventEnvelope],
) -> ExecutionLifecycleState:
    """Deterministically reconstruct execution lifecycle state.

    Pure and side-effect free:
    - never writes to a database,
    - never calls a broker or the paper engine,
    - never generates timestamps or random identifiers,
    - never mutates the supplied events.

    Raises a lifecycle-specific exception (all subclasses of
    ``LifecycleReplayError``) at the first offending event; partial state is
    never returned.
    """
    if not events:
        raise LifecycleSequenceError(
            "empty lifecycle stream; expected TradeIntentCreated at sequence 1",
            expected_sequence=1,
            actual_sequence=None,
        )

    acc = _ExecutionAcc(events[0])
    expected_sequence = 1

    for ev in events:
        # --- Tenant / aggregate identity: fail closed ---------------------
        if ev.tenant_id != acc.tenant_id:
            raise ReplaySecurityError(
                "TENANT_MISMATCH", expected=acc.tenant_id, actual=ev.tenant_id
            )
        if ev.aggregate_id != acc.aggregate_id:
            raise ReplaySecurityError(
                "AGGREGATE_MISMATCH", expected=acc.aggregate_id, actual=ev.aggregate_id
            )
        if ev.aggregate_type != acc.aggregate_type:
            raise ReplaySecurityError(
                "AGGREGATE_TYPE_MISMATCH",
                expected=acc.aggregate_type,
                actual=ev.aggregate_type,
            )

        # --- Version guard ------------------------------------------------
        if ev.event_version not in SUPPORTED_EVENT_VERSIONS:
            raise ReplayUnknownVersion(ev.event_version, ev.event_id)

        # --- Causal ordering: contiguous sequence starting at 1 ------------
        if ev.sequence != expected_sequence:
            raise ReplaySequenceGap(expected_sequence, ev.sequence, ev.event_id)

        # --- Terminal-state protection (execution level) -------------------
        if (
            acc.execution is not None
            and acc.execution in EXECUTION_TERMINAL_STATES
        ):
            raise ReplayInvalidTransition(
                ev.event_type,
                f"no lifecycle event may follow terminal execution state "
                f"{acc.execution.value}",
                from_state=acc.execution.value,
            )

        # --- Centralized transition dispatch -------------------------------
        handler = _TRANSITION_HANDLERS.get(ev.event_type)
        if handler is None:
            raise ReplayInvalidTransition(
                ev.event_type,
                "unsupported lifecycle event type for execution replay "
                "(position lifecycle is not part of execution replay)",
            )
        handler(acc, ev)

        acc.last_sequence = ev.sequence
        expected_sequence += 1

    return ExecutionLifecycleState(
        tenant_id=acc.tenant_id,
        aggregate_type=acc.aggregate_type,
        aggregate_id=acc.aggregate_id,
        execution_status=acc.execution or ExecutionStatus.CREATED,
        orders=MappingProxyType(
            {
                oid: OrderProjection(
                    order_id=oid,
                    status=o.status,
                    quantity=o.quantity,
                    cumulative_filled=o.cumulative_filled,
                    fills=tuple(o.fills),
                )
                for oid, o in acc.orders.items()
            }
        ),
        last_sequence=acc.last_sequence,
    )


__all__ = [
    "LifecycleReplayError",
    "LifecycleSequenceError",
    "ReplaySequenceGap",
    "ReplayInvalidTransition",
    "ReplaySecurityError",
    "ReplayUnknownVersion",
    "ReplayCorruptPayload",
    "ExecutionStatus",
    "OrderStatus",
    "FillRecord",
    "OrderProjection",
    "ExecutionLifecycleState",
    "replay_execution_events",
    "SUPPORTED_EVENT_VERSIONS",
    "EXECUTION_EVENT_TYPES",
]
