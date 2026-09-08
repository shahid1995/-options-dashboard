"""Day 39 Task 2 — Durable broker-event ingestion pipeline.

Durable pipeline:
    BrokerSyncEvent
        ↓
    validation (identity, tenant, quantity invariants)
        ↓
    tenant / order identity
        ↓
    broker ordering validation (sequence gap / stale / out-of-order)
        ↓
    durable idempotency
        ↓
    terminal-state enforcement (against durable projection)
        ↓
    durable normalized projection
        ↓
    explicit Day38 lifecycle mapping
        ↓
    single transaction (all three commit or all roll back)

All operations share the caller's transaction.  On any failure the caller
rolls back the entire transaction — no partial durable state.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import Session

from app.broker_sync import (
    BrokerEventType,
    BrokerSyncEvent,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
)
from app.broker_sync.models import BrokerOrderProjection, BrokerSyncIdempotency, BrokerSyncSequenceAnchor
from app.trade_lifecycle.persistence import append_lifecycle_event, next_event_sequence

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised when event ingestion fails."""

    def __init__(self, reason: str, action: str = "REJECTED"):
        self.reason = reason
        self.action = action
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Content fingerprint for conflict detection
# ---------------------------------------------------------------------------

def _content_fingerprint(event: BrokerSyncEvent) -> str:
    """Deterministic canonical-content fingerprint.

    Covers every semantically relevant field so that two events with the
    same canonical_id but different content produce different fingerprints.
    """
    parts: dict[str, Any] = {
        "tenant_id": event.tenant_id,
        "broker": event.broker,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "provider_event_id": event.provider_event_id,
        "source_mode": event.source_mode.value,
        "broker_order_id": event.broker_order_id,
        "canonical_sequence": event.canonical_sequence,
    }
    if event.event_timestamp is not None:
        parts["event_timestamp"] = event.event_timestamp.isoformat()
    if event.order_facts is not None:
        parts["order_facts"] = {
            "order_id": event.order_facts.order_id,
            "broker_order_id": event.order_facts.broker_order_id,
            "status": event.order_facts.status.value,
            "total_quantity": event.order_facts.total_quantity,
            "cumulative_filled": event.order_facts.cumulative_filled,
            "average_price": event.order_facts.average_price,
            "last_fill_price": event.order_facts.last_fill_price,
            "last_fill_quantity": event.order_facts.last_fill_quantity,
            "rejection_reason": event.order_facts.rejection_reason,
            "is_terminal": event.order_facts.is_terminal,
        }
    if event.fill_facts is not None:
        parts["fill_facts"] = {
            "fill_id": event.fill_facts.fill_id,
            "fill_quantity": event.fill_facts.fill_quantity,
            "fill_price": event.fill_facts.fill_price,
            "fill_timestamp": (
                event.fill_facts.fill_timestamp.isoformat()
                if event.fill_facts.fill_timestamp is not None
                else None
            ),
            "cumulative_filled_after": event.fill_facts.cumulative_filled_after,
            "remaining_after": event.fill_facts.remaining_after,
        }
    if event.metadata is not None:
        parts["metadata"] = dict(event.metadata)
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Terminal-state enforcement
# ---------------------------------------------------------------------------

_TERMINAL_STATES = {
    CanonicalOrderState.FILLED,
    CanonicalOrderState.CANCELLED,
    CanonicalOrderState.REJECTED,
    CanonicalOrderState.EXPIRED,
}


def _is_terminal(state: CanonicalOrderState) -> bool:
    return state in _TERMINAL_STATES


# ---------------------------------------------------------------------------
# Broker-to-Day38 lifecycle event mapping
# ---------------------------------------------------------------------------

_BROKER_TO_LIFECYCLE: dict[str, str] = {
    BrokerEventType.ORDER_SUBMITTED.value: "OrderSubmitted",
    BrokerEventType.ORDER_ACCEPTED.value: "OrderSubmitted",
    BrokerEventType.PARTIAL_FILL.value: "OrderFilled",
    BrokerEventType.FILL_RECORDED.value: "FillRecorded",
    BrokerEventType.FULL_FILL.value: "OrderFilled",
    BrokerEventType.ORDER_CANCELLED.value: "OrderCancelled",
    BrokerEventType.ORDER_REJECTED.value: "OrderRejected",
    BrokerEventType.ORDER_EXPIRED.value: "OrderCancelled",
}


def _map_to_lifecycle_event_type(event_type: str) -> str:
    """Map a canonical broker event type to the existing Day38 lifecycle event type.

    Uses the approved Day38 vocabulary (OrderSubmitted, OrderFilled,
    FillRecorded, OrderCancelled, OrderRejected).
    Does NOT invent new Day38 event names.
    Raises IngestionError for events that cannot be mapped.
    """
    mapped = _BROKER_TO_LIFECYCLE.get(event_type)
    if mapped is not None:
        return mapped
    raise IngestionError(
        f"cannot map broker event type '{event_type}' to a Day38 lifecycle event type",
        action="REJECTED",
    )


def _event_canonical_state(event: BrokerSyncEvent) -> CanonicalOrderState:
    """Map event type to canonical order state."""
    mapping = {
        BrokerEventType.ORDER_SUBMITTED: CanonicalOrderState.SUBMITTED,
        BrokerEventType.ORDER_ACCEPTED: CanonicalOrderState.OPEN,
        BrokerEventType.ORDER_REJECTED: CanonicalOrderState.REJECTED,
        BrokerEventType.ORDER_CANCELLED: CanonicalOrderState.CANCELLED,
        BrokerEventType.ORDER_EXPIRED: CanonicalOrderState.EXPIRED,
        BrokerEventType.PARTIAL_FILL: CanonicalOrderState.PARTIALLY_FILLED,
        BrokerEventType.FILL_RECORDED: CanonicalOrderState.PARTIALLY_FILLED,
        BrokerEventType.FULL_FILL: CanonicalOrderState.FILLED,
        # ORDER_RECOVERED is NOT mapped to UNKNOWN — it is a future recovery
        # event type.  For Task 2 it is rejected at the mapping layer.
    }
    return mapping.get(event.event_type, CanonicalOrderState.UNKNOWN)


# ---------------------------------------------------------------------------
# Broker ordering validation — PostgreSQL-safe atomic pattern
# ---------------------------------------------------------------------------

def _validate_broker_sequence_position(
    db: Session,
    event: BrokerSyncEvent,
) -> dict | None:
    """Validate canonical_sequence ordering position without advancing.

    Returns a dict with position info, or None if sequence is unknown.

    The returned dict contains:
    - ``incoming``: the event's canonical_sequence
    - ``last_sequence``: the current anchor's last_sequence
    - ``is_duplicate``: True if incoming == last_sequence (duplicate seq)
    - ``broker_order_id``: the normalized broker order ID

    Raises IngestionError for gap/stale sequences.

    Does NOT fabricate missing sequences.  Does NOT advance the anchor.
    """
    if event.canonical_sequence is None:
        return None

    incoming = event.canonical_sequence
    broker_order_id = event.broker_order_id or ""

    # --- Ensure anchor exists ---
    db.execute(
        text(
            """
            INSERT INTO broker_sync_sequence_anchor
                (tenant_id, broker, broker_order_id, last_sequence, created_at, updated_at)
            VALUES
                (:tenant_id, :broker, :broker_order_id, 0, :now, :now)
            ON CONFLICT (tenant_id, broker, broker_order_id) DO NOTHING
            """
        ),
        {
            "tenant_id": event.tenant_id,
            "broker": event.broker,
            "broker_order_id": broker_order_id,
            "now": datetime.now(timezone.utc),
        },
    )
    db.flush()

    # --- Read current anchor state ---
    anchor = db.execute(
        select(BrokerSyncSequenceAnchor).where(
            BrokerSyncSequenceAnchor.tenant_id == event.tenant_id,
            BrokerSyncSequenceAnchor.broker == event.broker,
            BrokerSyncSequenceAnchor.broker_order_id == broker_order_id,
        )
    ).scalar_one_or_none()

    if anchor is None:
        raise IngestionError(
            f"failed to ensure sequence anchor for order {broker_order_id}",
            action="REJECTED",
        )

    last_sequence = anchor.last_sequence

    # --- Validate position ---

    if incoming < last_sequence:
        raise IngestionError(
            f"stale canonical_sequence={incoming} "
            f"(last applied={last_sequence}) — "
            f"stale/out-of-order event rejected",
            action="REJECTED",
        )

    if incoming > last_sequence + 1:
        raise IngestionError(
            f"sequence gap: received canonical_sequence={incoming}, "
            f"expected {last_sequence + 1} (last applied={last_sequence}) — "
            f"quarantined as synchronization gap",
            action="REJECTED",
        )

    return {
        "incoming": incoming,
        "last_sequence": last_sequence,
        "is_duplicate": incoming == last_sequence,
        "broker_order_id": broker_order_id,
    }


def _advance_broker_sequence(
    db: Session,
    event: BrokerSyncEvent,
    position_info: dict | None,
) -> None:
    """Atomically advance the broker sequence anchor AFTER successful application.

    This is the serialization point for concurrent consumers.  It must be
    called AFTER the projection, idempotency record, and Day38 lifecycle event
    have all been persisted (inside the same SAVEPOINT) so that a failed
    advancement rolls back all durable effects together.

    Raises IngestionError if a concurrent worker already advanced the anchor.
    """
    if position_info is None:
        return

    if position_info["is_duplicate"]:
        return  # Duplicate sequence — idempotency layer handles it

    incoming = position_info["incoming"]
    expected = position_info["last_sequence"]
    broker_order_id = position_info["broker_order_id"]

    result = db.execute(
        text(
            """
            UPDATE broker_sync_sequence_anchor
            SET last_sequence = :advance_to,
                updated_at = :now
            WHERE tenant_id = :tenant_id
              AND broker = :broker
              AND broker_order_id = :broker_order_id
              AND last_sequence = :expected
            """
        ),
        {
            "advance_to": incoming,
            "expected": expected,
            "tenant_id": event.tenant_id,
            "broker": event.broker,
            "broker_order_id": broker_order_id,
            "now": datetime.now(timezone.utc),
        },
    )
    db.flush()

    if result.rowcount == 1:
        return

    # Concurrent worker advanced — signal failure for re-classification
    raise IngestionError(
        f"concurrent worker advanced broker sequence past {incoming}",
        action="CONFLICT",
    )


# ---------------------------------------------------------------------------
# Quantity invariant validation
# ---------------------------------------------------------------------------

def _validate_quantity_invariants(
    event: BrokerSyncEvent,
    previous: BrokerOrderProjection | None,
) -> None:
    """Validate fill and cumulative quantity semantics before persisting.

    Rejects:
    - cumulative_filled_after < previous cumulative_filled (regression)
    - cumulative_filled_after > total_quantity (overfill)
    - fill_quantity < 0 (negative fill)
    - remaining inconsistent with total/cumulative
    - cumulative_filled_after < previous cumulative + fill_quantity (fill arithmetic)

    Does not silently repair — fails closed.
    """
    ff = event.fill_facts
    if ff is None:
        return

    # Negative fill quantity
    if ff.fill_quantity is not None and ff.fill_quantity < 0:
        raise IngestionError(
            f"negative fill_quantity={ff.fill_quantity} rejected",
            action="REJECTED",
        )

    total_quantity = None
    if event.order_facts is not None and event.order_facts.total_quantity is not None:
        total_quantity = event.order_facts.total_quantity
    elif previous is not None:
        total_quantity = previous.total_quantity

    # Cumulative must not regress
    prev_cumulative = previous.cumulative_filled if previous is not None else 0
    if ff.cumulative_filled_after is not None and ff.cumulative_filled_after < prev_cumulative:
        raise IngestionError(
            f"cumulative_filled_after={ff.cumulative_filled_after} "
            f"regresses previous cumulative={prev_cumulative}",
            action="REJECTED",
        )

    # FIX 3: Fill arithmetic consistency — cumulative_filled_after must account
    # for the full incremental fill.  Catches cases where cumulative_after
    # doesn't include the current fill's contribution.
    if (
        previous is not None
        and ff.fill_quantity is not None
        and ff.cumulative_filled_after is not None
    ):
        expected_minimum = prev_cumulative + ff.fill_quantity
        if ff.cumulative_filled_after < expected_minimum:
            raise IngestionError(
                f"cumulative_filled_after={ff.cumulative_filled_after} is less than "
                f"previous_cumulative={prev_cumulative} + fill_quantity={ff.fill_quantity} "
                f"(expected >= {expected_minimum})",
                action="REJECTED",
            )

    # Cumulative must not exceed total
    if ff.cumulative_filled_after is not None and total_quantity is not None:
        if ff.cumulative_filled_after > total_quantity:
            raise IngestionError(
                f"cumulative_filled_after={ff.cumulative_filled_after} "
                f"exceeds total_quantity={total_quantity} (overfill)",
                action="REJECTED",
            )

    # Remaining consistency check
    if ff.remaining_after is not None and total_quantity is not None and ff.cumulative_filled_after is not None:
        expected_remaining = total_quantity - ff.cumulative_filled_after
        if ff.remaining_after != expected_remaining:
            raise IngestionError(
                f"remaining_after={ff.remaining_after} inconsistent with "
                f"total={total_quantity} - cumulative={ff.cumulative_filled_after} "
                f"(expected {expected_remaining})",
                action="REJECTED",
            )

    # Fill quantity must not exceed total
    if ff.fill_quantity is not None and total_quantity is not None:
        if ff.fill_quantity > total_quantity:
            raise IngestionError(
                f"fill_quantity={ff.fill_quantity} exceeds total_quantity={total_quantity}",
                action="REJECTED",
            )


# ---------------------------------------------------------------------------
# Projection builder
# ---------------------------------------------------------------------------

def _build_projection(
    event: BrokerSyncEvent,
    previous: BrokerOrderProjection | None,
    canonical_sequence: int | None,
) -> BrokerOrderProjection:
    """Build a new BrokerOrderProjection from the event and previous state."""
    state = _event_canonical_state(event)
    is_terminal = _is_terminal(state)

    total_quantity: int | None = None
    cumulative_filled: int = 0
    remaining_quantity: int | None = None
    average_price: float | None = None
    last_fill_price: float | None = None
    last_fill_quantity: int | None = None
    fill_count: int = 0
    last_fill_id: str | None = None
    rejection_reason: str | None = None

    if previous is not None and canonical_sequence is not None:
        # Carry forward previous state unless overridden by this event
        total_quantity = previous.total_quantity
        cumulative_filled = previous.cumulative_filled
        remaining_quantity = previous.remaining_quantity
        average_price = previous.average_price
        fill_count = previous.fill_count
        last_fill_id = previous.last_fill_id

    if event.order_facts is not None:
        of = event.order_facts
        if of.total_quantity is not None:
            total_quantity = of.total_quantity
        if of.cumulative_filled is not None and of.cumulative_filled != 0:
            cumulative_filled = of.cumulative_filled
        if of.average_price is not None:
            average_price = of.average_price
        if of.last_fill_price is not None:
            last_fill_price = of.last_fill_price
        if of.last_fill_quantity is not None:
            last_fill_quantity = of.last_fill_quantity
        if of.rejection_reason is not None:
            rejection_reason = of.rejection_reason

    if event.fill_facts is not None:
        ff = event.fill_facts
        last_fill_id = ff.fill_id
        last_fill_price = ff.fill_price
        last_fill_quantity = ff.fill_quantity
        if ff.cumulative_filled_after is not None:
            cumulative_filled = ff.cumulative_filled_after
        remaining_quantity = ff.remaining_after
        fill_count += 1
        if ff.fill_price is not None and ff.fill_quantity is not None:
            if previous is not None and previous.cumulative_filled > 0 and average_price is not None:
                prev_total_price = (average_price or 0.0) * previous.cumulative_filled
                new_total_price = ff.fill_price * ff.fill_quantity
                if cumulative_filled > 0:
                    average_price = (prev_total_price + new_total_price) / cumulative_filled
            else:
                average_price = ff.fill_price

    # Compute remaining if we have total and cumulative
    if remaining_quantity is None and total_quantity is not None:
        remaining_quantity = total_quantity - cumulative_filled

    # Rejection reason from event
    if event.event_type == BrokerEventType.ORDER_REJECTED:
        if event.order_facts is not None and event.order_facts.rejection_reason:
            rejection_reason = event.order_facts.rejection_reason

    occurred_at = event.event_timestamp or event.received_at

    return BrokerOrderProjection(
        tenant_id=event.tenant_id,
        broker=event.broker,
        broker_order_id=event.broker_order_id or "",
        canonical_id=event.canonical_id,
        event_type=event.event_type,
        status=state.value,
        total_quantity=total_quantity,
        cumulative_filled=cumulative_filled,
        remaining_quantity=remaining_quantity,
        average_price=average_price,
        last_fill_price=last_fill_price,
        last_fill_quantity=last_fill_quantity,
        rejection_reason=rejection_reason,
        is_terminal=is_terminal,
        fill_count=fill_count,
        last_fill_id=last_fill_id,
        canonical_sequence=canonical_sequence,
        occurred_at=occurred_at,
        received_at=event.received_at,
    )


# ---------------------------------------------------------------------------
# Day38 lifecycle event mapping
# ---------------------------------------------------------------------------

def _append_lifecycle_from_event(
    db: Session,
    event: BrokerSyncEvent,
    day38_sequence: int,
) -> None:
    """Append a Day38 lifecycle event derived from the canonical broker event.

    Maps the broker event type to the approved Day38 vocabulary and uses
    ``next_event_sequence`` to allocate the Day38 aggregate sequence
    independently of ``canonical_sequence``.
    """
    lifecycle_event_type = _map_to_lifecycle_event_type(event.event_type)

    aggregate_id = event.broker_order_id or event.canonical_id

    payload: dict[str, Any] = {
        "canonical_id": event.canonical_id,
        "broker": event.broker,
        "broker_event_type": event.event_type,
        "broker_event_version": event.event_version,
        "provider_event_id": event.provider_event_id,
        "source_mode": event.source_mode.value,
        "broker_order_id": event.broker_order_id,
    }
    if event.event_timestamp is not None:
        payload["event_timestamp"] = event.event_timestamp.isoformat()
    if event.order_facts is not None:
        payload["order_facts"] = {
            "total_quantity": event.order_facts.total_quantity,
            "cumulative_filled": event.order_facts.cumulative_filled,
            "average_price": event.order_facts.average_price,
            "is_terminal": event.order_facts.is_terminal,
        }
    if event.fill_facts is not None:
        payload["fill_facts"] = {
            "fill_id": event.fill_facts.fill_id,
            "fill_quantity": event.fill_facts.fill_quantity,
            "fill_price": event.fill_facts.fill_price,
            "cumulative_filled_after": event.fill_facts.cumulative_filled_after,
            "remaining_after": event.fill_facts.remaining_after,
        }

    # FIX 2: Day38 lifecycle replay-compatible payload fields.
    # The replay state machine (app/trade_lifecycle/replay.py) requires specific
    # top-level payload keys for each event type:
    #   - order_id (str): required by OrderSubmitted, OrderFilled, OrderCancelled,
    #     OrderRejected, FillRecorded
    #   - cumulative_filled (int >= 1): required by OrderFilled
    #   - fill_quantity (int >= 1): required by FillRecorded
    # Only include when they have positive integer values because the replay
    # handler uses _require_payload_positive_int which rejects values < 1.

    # order_id: from event.order_facts.order_id if present, else event.broker_order_id
    order_id_value = None
    if event.order_facts is not None and event.order_facts.order_id:
        order_id_value = event.order_facts.order_id
    elif event.broker_order_id:
        order_id_value = event.broker_order_id
    if order_id_value:
        payload["order_id"] = order_id_value

    # cumulative_filled (int >= 1): from order_facts.cumulative_filled, else
    # fill_facts.cumulative_filled_after — only if positive
    cumulative_value = 0
    if (
        event.order_facts is not None
        and event.order_facts.cumulative_filled is not None
        and event.order_facts.cumulative_filled > 0
    ):
        cumulative_value = event.order_facts.cumulative_filled
    elif (
        event.fill_facts is not None
        and event.fill_facts.cumulative_filled_after is not None
        and event.fill_facts.cumulative_filled_after > 0
    ):
        cumulative_value = event.fill_facts.cumulative_filled_after
    if cumulative_value > 0:
        payload["cumulative_filled"] = cumulative_value

    # fill_quantity (int >= 1): from event.fill_facts.fill_quantity — only if positive
    if (
        event.fill_facts is not None
        and event.fill_facts.fill_quantity is not None
        and event.fill_facts.fill_quantity > 0
    ):
        payload["fill_quantity"] = event.fill_facts.fill_quantity

    # Map broker order to Day38 order identity
    order_id = event.broker_order_id or event.canonical_id

    append_lifecycle_event(
        db=db,
        aggregate_type="execution",
        aggregate_id=order_id,
        event_type=lifecycle_event_type,
        event_version=event.event_version,
        tenant_id=event.tenant_id,
        sequence=day38_sequence,
        position_sequence=None,
        quantity_delta=None,
        position_identity=None,
        occurred_at=event.event_timestamp or event.received_at,
        payload=payload,
        metadata=None,
    )


def _allocate_day38_sequence(db: Session, event: BrokerSyncEvent) -> int:
    """Allocate the next Day38 aggregate sequence.

    Uses the existing Day38 ``next_event_sequence`` mechanism.
    The Day38 sequence is allocated independently of ``canonical_sequence``.
    """
    aggregate_id = event.broker_order_id or event.canonical_id
    return next_event_sequence(db, event.tenant_id, "execution", aggregate_id)


# ---------------------------------------------------------------------------
# Main ingestion entry point
# ---------------------------------------------------------------------------

def ingest_canonical_event(
    event: BrokerSyncEvent,
    db: Session,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Consume a canonical broker event exactly once semantically.

    Durable pipeline: all operations share the caller's transaction.
    On any failure the caller must roll back the entire transaction.

    Args:
        event: A canonical ``BrokerSyncEvent`` (already constructed).
        db: A SQLAlchemy ``Session`` for durable persistence.
        tenant_id: Optional tenant context for projection.  If provided,
            the event's tenant_id must match.

    Returns:
        A result dictionary with:
        - ``canonical_id`` (str)
        - ``action``: ``APPLIED``, ``DUPLICATE_NOOP``, ``REJECTED``, ``CONFLICT``
        - ``normalized_state``: projected state dict when applied, else ``None``
        - ``reason``: explanation (None when action is APPLIED)
    """
    try:
        return _do_ingest(event, db, tenant_id)
    except IngestionError as e:
        return {
            "canonical_id": event.canonical_id,
            "action": e.action,
            "normalized_state": None,
            "reason": e.reason,
        }


def _do_ingest(
    event: BrokerSyncEvent,
    db: Session,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    canonical_id = event.canonical_id

    # --- Malformed event check ---
    if not canonical_id:
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": "empty canonical identity",
        }

    # --- Tenant isolation ---
    if tenant_id is not None and not event.belongs_to_tenant(tenant_id):
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": (
                f"tenant mismatch: event tenant '{event.tenant_id}' "
                f"!= projection tenant '{tenant_id}'"
            ),
        }

    # --- Compute content fingerprint ---
    fingerprint = _content_fingerprint(event)

    # --- Broker sequence position validation (BEFORE idempotency check) ---
    # Validates ordering without advancing the anchor.  Advancement happens
    # inside the SAVEPOINT after all durable effects succeed, so a failed
    # application rolls back the sequence anchor too.
    sequence_position = _validate_broker_sequence_position(db, event)
    validated_sequence = sequence_position["incoming"] if sequence_position else None

    # --- Durable idempotency check ---
    existing_idem = db.execute(
        select(BrokerSyncIdempotency).where(
            BrokerSyncIdempotency.canonical_id == canonical_id
        )
    ).scalar_one_or_none()

    if existing_idem is not None:
        if existing_idem.content_fingerprint == fingerprint:
            # Identical duplicate — no-op
            return {
                "canonical_id": canonical_id,
                "action": "DUPLICATE_NOOP",
                "normalized_state": None,
                "reason": "already applied (durable)",
            }
        # Same identity, different content — conflict
        return {
            "canonical_id": canonical_id,
            "action": "CONFLICT",
            "normalized_state": None,
            "reason": (
                f"canonical_id {canonical_id} exists with different content "
                f"(stored={existing_idem.content_fingerprint[:16]}..., "
                f"incoming={fingerprint[:16]}...)"
            ),
        }

    # --- FIX 2: Reclassify same-sequence race through idempotency ---
    # When the broker sequence position indicates a duplicate sequence
    # (incoming == last_sequence), check if a DIFFERENT canonical event has
    # already claimed this sequence for the same broker order.  If so, this
    # is a same-sequence conflict, not an independent observation.
    if sequence_position is not None and sequence_position["is_duplicate"]:
        existing_for_sequence = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.tenant_id == event.tenant_id,
                BrokerSyncIdempotency.broker == event.broker,
                BrokerSyncIdempotency.broker_order_id == event.broker_order_id,
                BrokerSyncIdempotency.canonical_sequence == validated_sequence,
                BrokerSyncIdempotency.canonical_id != canonical_id,
            )
        ).scalar_one_or_none()
        if existing_for_sequence is not None:
            raise IngestionError(
                f"canonical_sequence={validated_sequence} already consumed by a "
                f"different event for order {event.broker_order_id} "
                f"(existing={existing_for_sequence.canonical_id[:16]}..., "
                f"incoming={canonical_id[:16]}...)",
                action="CONFLICT",
            )

    # --- Map to Day38 lifecycle event type (explicit mapping) ---
    # This will raise IngestionError for unmappable types (e.g. ORDER_RECOVERED)
    _lifecycle_event_type = _map_to_lifecycle_event_type(event.event_type)

    # --- Find previous projection (deterministic: ordered by canonical_sequence) ---
    # FIX 4: canonical_sequence is the primary ordering key; id is a deterministic
    # tiebreaker only (not a causal ordering mechanism) for events where
    # canonical_sequence is NULL.  The id column is stable within a database
    # session and provides a consistent, repeatable order for projection lookup.
    previous: BrokerOrderProjection | None = None
    if event.broker_order_id:
        previous = db.execute(
            select(BrokerOrderProjection)
            .where(
                BrokerOrderProjection.tenant_id == event.tenant_id,
                BrokerOrderProjection.broker == event.broker,
                BrokerOrderProjection.broker_order_id == event.broker_order_id,
            )
            .order_by(
                BrokerOrderProjection.canonical_sequence.desc().nullslast(),
                BrokerOrderProjection.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()

    # --- Terminal-state enforcement (before quantity validation) ---
    new_state = _event_canonical_state(event)
    if previous is not None and previous.is_terminal:
        # Terminal orders remain terminal — no post-terminal mutation allowed
        # ORDER_RECOVERED is rejected by the mapping layer, so it never
        # reaches here
        raise IngestionError(
            f"terminal state mutation rejected: order is {previous.status}, "
            f"cannot apply {event.event_type}",
            action="REJECTED",
        )

    # --- Validate quantity invariants ---
    _validate_quantity_invariants(event, previous)

    # --- Build projection ---
    projection = _build_projection(event, previous, validated_sequence)

    # --- Allocate Day38 sequence (independent of canonical_sequence) ---
    day38_sequence = _allocate_day38_sequence(db, event)

    # --- Durable mutation, wrapped in a nested SAVEPOINT ---
    # Concurrency safety (FIX 1): two concurrent workers may pass the same
    # canonical_sequence (both read the same anchor, both advance it in their
    # own transaction).  Only one may win.  The loser's insert of the
    # idempotency record (PK canonical_id) will hit the DB-level unique
    # constraint.  We catch SAIntegrityError at the SAVEPOINT so the caller's
    # outer transaction stays intact and we can re-classify as a graceful
    # DUPLICATE_NOOP / CONFLICT instead of leaking an exception.
    #
    # FIX 1 (sequence coupling): the broker sequence anchor is advanced INSIDE
    # the SAVEPOINT, AFTER projection + idempotency + lifecycle have all been
    # persisted.  If any step fails, the SAVEPOINT rolls back all four effects
    # together, so the sequence anchor never represents an unapplied event.
    try:
        with db.begin_nested():
            # Persist projection
            db.add(projection)
            db.flush()

            # Persist idempotency record
            idem = BrokerSyncIdempotency(
                canonical_id=canonical_id,
                tenant_id=event.tenant_id,
                broker=event.broker,
                broker_order_id=event.broker_order_id,
                canonical_sequence=validated_sequence,
                event_type=event.event_type,
                event_version=event.event_version,
                content_fingerprint=fingerprint,
                source_mode=event.source_mode.value,
                provider_event_id=event.provider_event_id,
                received_at=event.received_at,
                status="APPLIED",
            )
            db.add(idem)
            db.flush()

            # Day38 lifecycle integration
            _append_lifecycle_from_event(db, event, day38_sequence)

            # Advance broker sequence anchor AFTER all durable effects succeed.
            # This is the serialization point: if a concurrent worker already
            # advanced the anchor, this raises IngestionError(CONFLICT) which
            # rolls back the SAVEPOINT and triggers re-classification below.
            _advance_broker_sequence(db, event, sequence_position)
    except SAIntegrityError:
        # The SAVEPOINT was rolled back; the caller's outer transaction is
        # intact.  A concurrent worker committed the same canonical_id first.
        # Re-read the idempotency record to classify.
        concurrent_idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id == canonical_id
            )
        ).scalar_one_or_none()
        if concurrent_idem is not None:
            if concurrent_idem.content_fingerprint == fingerprint:
                return {
                    "canonical_id": canonical_id,
                    "action": "DUPLICATE_NOOP",
                    "normalized_state": None,
                    "reason": "concurrent worker applied identical event (durable)",
                }
            return {
                "canonical_id": canonical_id,
                "action": "CONFLICT",
                "normalized_state": None,
                "reason": (
                    f"concurrent worker applied canonical_id {canonical_id} "
                    f"with different content"
                ),
            }
        # No visible duplicate — a concurrent worker is mid-transaction.
        # Fail closed.
        return {
            "canonical_id": canonical_id,
            "action": "CONFLICT",
            "normalized_state": None,
            "reason": (
                f"concurrent write conflict on canonical_id {canonical_id} "
                f"(no committed idempotency record visible)"
            ),
        }
    except IngestionError as e:
        # Sequence advancement lost a race — re-classify through idempotency.
        if e.action == "CONFLICT":
            concurrent_idem = db.execute(
                select(BrokerSyncIdempotency).where(
                    BrokerSyncIdempotency.canonical_id == canonical_id
                )
            ).scalar_one_or_none()
            if concurrent_idem is not None:
                if concurrent_idem.content_fingerprint == fingerprint:
                    return {
                        "canonical_id": canonical_id,
                        "action": "DUPLICATE_NOOP",
                        "normalized_state": None,
                        "reason": "concurrent worker applied identical event (durable)",
                    }
                return {
                    "canonical_id": canonical_id,
                    "action": "CONFLICT",
                    "normalized_state": None,
                    "reason": (
                        f"concurrent worker applied canonical_id {canonical_id} "
                        f"with different content"
                    ),
                }
            return {
                "canonical_id": canonical_id,
                "action": "CONFLICT",
                "normalized_state": None,
                "reason": (
                    f"concurrent write conflict on canonical_id {canonical_id} "
                    f"(no committed idempotency record visible)"
                ),
            }
        raise

    # --- Build result ---
    normalized_state = {
        "canonical_id": projection.canonical_id,
        "tenant_id": projection.tenant_id,
        "broker_order_id": projection.broker_order_id,
        "event_type": projection.event_type,
        "status": projection.status,
        "total_quantity": projection.total_quantity,
        "cumulative_filled": projection.cumulative_filled,
        "remaining_quantity": projection.remaining_quantity,
        "average_price": projection.average_price,
        "last_fill_price": projection.last_fill_price,
        "last_fill_quantity": projection.last_fill_quantity,
        "is_terminal": projection.is_terminal,
        "fill_count": projection.fill_count,
        "last_fill_id": projection.last_fill_id,
        "rejection_reason": projection.rejection_reason,
    }

    return {
        "canonical_id": canonical_id,
        "action": "APPLIED",
        "normalized_state": normalized_state,
        "reason": None,
    }
