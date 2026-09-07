"""Day 38 Task 4 — Position lifecycle replay + position sequence semantics.

Pure-domain module (no SQLAlchemy, no DB, no broker, no paper-trading
write-back, no ``datetime.now()``, no ``uuid``): reconstructs the
instrument-netted *position* lifecycle from an ordered stream of Task 2
``TradeLifecycleEventEnvelope`` values carrying ``position_identity``,
``quantity_delta`` and ``position_sequence``.

Scope (approved Day 38 design §5d / plan Task 4):

- Position is **user/instrument-netted and authoritative-state owning** — it is
  NOT execution-owned.  ``aggregate_id`` (an execution) is attribution only;
  many executions contribute to the same position identity.
- Permanent ``PositionIdentity = (user_id, symbol, expiry, strike,
  option_type)``.  A *lifecycle instance* is one period of non-zero exposure
  for that identity, scoped by ``position_sequence``:
  ``OPEN → CLOSED``; ``CLOSED`` is terminal for that instance.  A later
  ``PositionOpened`` with a new ``position_sequence`` starts a NEW instance —
  never ``CLOSED → OPEN`` on the same instance.
- ``quantity_delta`` is the signed contribution of the event.
  ``net_quantity = Σ quantity_delta`` over the current instance.
  ``PositionClosed`` must carry the exact signed delta that brings the
  instance net to zero.
- An update may never silently cross zero (or land on zero) inside one
  instance; a crossing request is expressed as ``PositionClosed`` to zero
  followed (when a remainder exists) by ``PositionOpened`` of the remainder.
  ``decompose_position_delta()`` is the small pure helper for that.

Execution replay (``app.trade_lifecycle.replay``) is untouched and remains a
separate state machine; this module reuses its lifecycle exception types so
there is one consistent error hierarchy.

Replay is deterministic and side-effect free: it never writes, never calls a
broker, never generates timestamps/identifiers, never mutates its inputs, and
returns an immutable frozen ``PositionLifecycleState``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple

from app.trade_lifecycle.envelope import PositionIdentity, TradeLifecycleEventEnvelope
from app.trade_lifecycle.replay import (
    LifecycleReplayError,
    LifecycleSequenceError,
    ReplaySequenceGap,
    ReplayInvalidTransition,
    ReplaySecurityError,
    ReplayUnknownVersion,
    ReplayCorruptPayload,
    SUPPORTED_EVENT_VERSIONS,
)

# Event types handled by position replay (position lifecycle scope only).
POSITION_EVENT_TYPES = frozenset({"PositionOpened", "PositionUpdated", "PositionClosed"})


class PositionStatus(str, Enum):
    """Lifecycle status of the current (latest) position instance."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PositionInstanceState:
    """One reconstructed position lifecycle instance."""

    position_sequence: int
    status: PositionStatus
    net_quantity: int


@dataclass(frozen=True)
class PositionLifecycleState:
    """Deterministic instrument-netted position lifecycle projection.

    Reconstructed purely from the event stream — never written back to the
    authoritative ``Position`` model or any database.
    """

    tenant_id: str
    position_identity: PositionIdentity
    status: PositionStatus
    net_quantity: int
    position_sequence: int
    last_sequence: int
    instances: Mapping[int, PositionInstanceState] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mutable accumulator used during replay (never escapes the module)
# ---------------------------------------------------------------------------

class _InstanceAcc:
    __slots__ = ("position_sequence", "status", "net_quantity")

    def __init__(self, position_sequence: int, delta: int) -> None:
        self.position_sequence = position_sequence
        self.status = PositionStatus.OPEN
        self.net_quantity = delta


class _PositionAcc:
    __slots__ = ("tenant_id", "position_identity", "instances", "open_ps",
                 "used_max", "last_sequence")

    def __init__(self, first: TradeLifecycleEventEnvelope) -> None:
        identity = _require_identity(first)
        self.tenant_id = first.tenant_id
        self.position_identity = identity
        self.instances: dict[int, _InstanceAcc] = {}
        self.open_ps: Optional[int] = None
        self.used_max = 0
        self.last_sequence = 0


# ---------------------------------------------------------------------------
# Per-event field extraction (deterministic validation, no silent coercion)
# ---------------------------------------------------------------------------

def _require_identity(ev: TradeLifecycleEventEnvelope) -> PositionIdentity:
    identity = ev.position_identity
    if identity is None:
        raise ReplayCorruptPayload(
            ev.event_type,
            "position events must carry a position_identity "
            "(user_id, symbol, expiry, strike, option_type)",
            ev.event_id,
        )
    return identity


def _require_position_sequence(ev: TradeLifecycleEventEnvelope) -> int:
    ps = ev.position_sequence
    if ps is None or not isinstance(ps, int) or isinstance(ps, bool) or ps < 1:
        raise ReplayCorruptPayload(
            ev.event_type,
            "position events must carry a positive integer position_sequence "
            "(lifecycle-instance sequence, scoped to the full PositionIdentity)",
            ev.event_id,
        )
    return ps


def _require_quantity_delta(ev: TradeLifecycleEventEnvelope) -> int:
    delta = ev.quantity_delta
    if delta is None or not isinstance(delta, int) or isinstance(delta, bool):
        raise ReplayCorruptPayload(
            ev.event_type,
            "position events must carry an integer quantity_delta (signed "
            "contribution; quantity_delta is a relational column, not "
            "payload-only)",
            ev.event_id,
        )
    return delta


# ---------------------------------------------------------------------------
# Transition handlers (centralized transition rules)
# ---------------------------------------------------------------------------

def _apply_position_opened(acc: _PositionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    ps = _require_position_sequence(ev)
    delta = _require_quantity_delta(ev)
    if acc.open_ps is not None:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"cannot open a new lifecycle instance while instance "
            f"{acc.open_ps} is still OPEN",
            from_state="OPEN",
        )
    if delta == 0:
        raise ReplayInvalidTransition(
            ev.event_type,
            "a PositionOpened must establish non-zero exposure",
        )
    if ps in acc.instances:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"position_sequence {ps} already exists (a CLOSED lifecycle "
            f"instance may not be reused)",
            from_state="CLOSED",
        )
    # Lifecycle-instance sequences are allocated per identity via the anchor,
    # so consecutive in-stream instances must advance by exactly one.
    if acc.used_max > 0 and ps != acc.used_max + 1:
        raise ReplaySequenceGap(acc.used_max + 1, ps, ev.event_id)
    acc.instances[ps] = _InstanceAcc(ps, delta)
    acc.open_ps = ps
    acc.used_max = ps


def _apply_position_updated(acc: _PositionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    ps = _require_position_sequence(ev)
    delta = _require_quantity_delta(ev)
    if acc.open_ps is None:
        raise ReplayInvalidTransition(
            ev.event_type,
            "PositionUpdated requires an OPEN lifecycle instance",
        )
    if ps != acc.open_ps:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"PositionUpdated targets position_sequence {ps} but the open "
            f"instance is {acc.open_ps}",
            from_state=acc.instances[acc.open_ps].status.value,
        )
    instance = acc.instances[ps]
    new_net = instance.net_quantity + delta
    if new_net == 0:
        raise ReplayInvalidTransition(
            ev.event_type,
            "PositionUpdated may not land exactly on zero — express the final "
            "contribution as PositionClosed",
            from_state="OPEN",
        )
    # A same-instance update must never cross zero (opposite sign).
    if (instance.net_quantity > 0 and new_net < 0) or (
        instance.net_quantity < 0 and new_net > 0
    ):
        raise ReplayInvalidTransition(
            ev.event_type,
            f"update {delta} on net {instance.net_quantity} would cross zero "
            f"inside lifecycle instance {ps}; decompose as PositionClosed + "
            f"PositionOpened",
            from_state="OPEN",
        )
    instance.net_quantity = new_net


def _apply_position_closed(acc: _PositionAcc, ev: TradeLifecycleEventEnvelope) -> None:
    ps = _require_position_sequence(ev)
    delta = _require_quantity_delta(ev)
    if acc.open_ps is None:
        raise ReplayInvalidTransition(
            ev.event_type,
            "PositionClosed requires an OPEN lifecycle instance",
        )
    if ps != acc.open_ps:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"PositionClosed targets position_sequence {ps} but the open "
            f"instance is {acc.open_ps}",
            from_state=acc.instances[acc.open_ps].status.value,
        )
    instance = acc.instances[ps]
    new_net = instance.net_quantity + delta
    if new_net != 0:
        raise ReplayInvalidTransition(
            ev.event_type,
            f"PositionClosed delta {delta} leaves net {new_net} — it must "
            f"bring the instance to exactly zero",
            from_state="OPEN",
        )
    instance.status = PositionStatus.CLOSED
    instance.net_quantity = 0
    acc.open_ps = None


_POSITION_HANDLERS = {
    "PositionOpened": _apply_position_opened,
    "PositionUpdated": _apply_position_updated,
    "PositionClosed": _apply_position_closed,
}


# ---------------------------------------------------------------------------
# Zero-crossing decomposition (pure)
# ---------------------------------------------------------------------------

def decompose_position_delta(
    current_quantity: int,
    requested_delta: int,
) -> Optional[list[tuple[str, int]]]:
    """Decompose a delta that would cross zero into close + reopen events.

    A position lifecycle instance may never cross zero (or land on zero)
    through an update.  When ``requested_delta`` has the opposite sign of
    ``current_quantity`` and its magnitude is at least that of the current
    quantity, the change must be expressed as:

    - ``("PositionClosed", -current_quantity)`` — close the open instance to
      exactly zero, followed by
    - ``("PositionOpened", remainder)`` — when a remainder exists, open a NEW
      lifecycle instance in the direction of the requested delta.

    Returns ``None`` when no crossing occurs (plain in-instance update or a
    fresh opening from flat), or the decomposed event list otherwise.

    Example: ``decompose_position_delta(10, -15)`` →
    ``[("PositionClosed", -10), ("PositionOpened", -5)]``.
    """
    for name, value in (("current_quantity", current_quantity),
                        ("requested_delta", requested_delta)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
    if requested_delta == 0:
        raise ValueError("requested_delta must be non-zero")
    if current_quantity == 0:
        return None  # opening from flat is PositionOpened, not a crossing
    same_sign = (current_quantity > 0) == (requested_delta > 0)
    if same_sign:
        return None
    if abs(requested_delta) < abs(current_quantity):
        return None  # in-instance reduction; no decomposition
    close_delta = -current_quantity
    remainder = requested_delta + current_quantity
    if remainder == 0:
        return [("PositionClosed", close_delta)]
    return [("PositionClosed", close_delta), ("PositionOpened", remainder)]


# ---------------------------------------------------------------------------
# Deterministic replay entry point
# ---------------------------------------------------------------------------

def replay_position_events(
    events: Sequence[TradeLifecycleEventEnvelope],
) -> PositionLifecycleState:
    """Deterministically reconstruct the netted position lifecycle.

    Pure and side-effect free:
    - never writes to a database or the authoritative ``Position`` model,
    - never calls a broker or the paper engine,
    - never generates timestamps or random identifiers,
    - never mutates the supplied events.

    The stream must carry one PositionIdentity (fail-closed otherwise) and
    contiguous aggregate ``sequence`` starting at 1; every position event must
    also carry the same tenant, a supported ``event_version``, and consistent
    ``position_sequence``/``quantity_delta`` relational values.
    """
    if not events:
        raise LifecycleSequenceError(
            "empty position lifecycle stream; expected sequence 1",
            expected_sequence=1,
            actual_sequence=None,
        )

    acc = _PositionAcc(events[0])
    expected_sequence = 1

    for ev in events:
        # --- PositionIdentity / tenant: fail closed ------------------------
        identity = _require_identity(ev)
        if identity != acc.position_identity:
            raise ReplaySecurityError(
                "POSITION_IDENTITY_MISMATCH",
                expected=repr(acc.position_identity),
                actual=repr(identity),
            )
        if ev.tenant_id != acc.tenant_id:
            raise ReplaySecurityError(
                "TENANT_MISMATCH", expected=acc.tenant_id, actual=ev.tenant_id
            )

        # --- Version guard ------------------------------------------------
        if ev.event_version not in SUPPORTED_EVENT_VERSIONS:
            raise ReplayUnknownVersion(ev.event_version, ev.event_id)

        # --- Causal ordering: contiguous sequence starting at 1 ------------
        if ev.sequence != expected_sequence:
            raise ReplaySequenceGap(expected_sequence, ev.sequence, ev.event_id)

        # --- Centralized transition dispatch -------------------------------
        handler = _POSITION_HANDLERS.get(ev.event_type)
        if handler is None:
            raise ReplayInvalidTransition(
                ev.event_type,
                "unsupported lifecycle event type for position replay "
                "(execution lifecycle is handled by replay.replay_execution_events)",
            )
        handler(acc, ev)

        acc.last_sequence = ev.sequence
        expected_sequence += 1

    if acc.open_ps is not None:
        open_instance = acc.instances[acc.open_ps]
        status, net, current_ps = (
            PositionStatus.OPEN, open_instance.net_quantity, acc.open_ps,
        )
    else:
        status, net, current_ps = (
            PositionStatus.CLOSED, 0, acc.used_max,
        )

    return PositionLifecycleState(
        tenant_id=acc.tenant_id,
        position_identity=acc.position_identity,
        status=status,
        net_quantity=net,
        position_sequence=current_ps,
        last_sequence=acc.last_sequence,
        instances=MappingProxyType(
            {
                ps: PositionInstanceState(
                    position_sequence=inst.position_sequence,
                    status=inst.status,
                    net_quantity=inst.net_quantity,
                )
                for ps, inst in acc.instances.items()
            }
        ),
    )


__all__ = [
    "PositionStatus",
    "PositionInstanceState",
    "PositionLifecycleState",
    "decompose_position_delta",
    "replay_position_events",
    "POSITION_EVENT_TYPES",
]
