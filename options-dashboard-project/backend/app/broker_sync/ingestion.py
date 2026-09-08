"""Day 39 Task 2 — Durable broker-event ingestion pipeline.

Durable pipeline:
    BrokerSyncEvent
        ↓
    validation
        ↓
    tenant / identity checks
        ↓
    durable idempotency (PostgreSQL)
        ↓
    terminal-state enforcement (against durable projection)
        ↓
    durable normalized projection
        ↓
    Day38 lifecycle/audit persistence
        ↓
    single transaction commit

All operations share the caller's transaction.  On any failure the caller
rolls back the entire transaction — no partial durable state.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import Session

from app.broker_sync import (
    BrokerEventSourceMode,
    BrokerEventType,
    BrokerSyncEvent,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
)
from app.broker_sync.models import BrokerOrderProjection, BrokerSyncIdempotency
from app.trade_lifecycle.persistence import append_lifecycle_event

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
        parts["metadata"] = dict(event.metadata) if hasattr(event.metadata, "items") else event.metadata
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
        BrokerEventType.ORDER_RECOVERED: CanonicalOrderState.UNKNOWN,
    }
    return mapping.get(event.event_type, CanonicalOrderState.UNKNOWN)


# ---------------------------------------------------------------------------
# Projection builder
# ---------------------------------------------------------------------------

def _build_projection(
    event: BrokerSyncEvent,
    previous: BrokerOrderProjection | None,
) -> BrokerOrderProjection:
    """Build a new BrokerOrderProjection from the event and previous state."""
    state = _event_canonical_state(event)
    is_terminal = _is_terminal(state)

    # Determine quantities
    total_quantity: int | None = None
    cumulative_filled: int = 0
    remaining_quantity: int | None = None
    average_price: float | None = None
    last_fill_price: float | None = None
    last_fill_quantity: int | None = None
    fill_count: int = 0
    last_fill_id: str | None = None
    rejection_reason: str | None = None

    if event.order_facts is not None:
        total_quantity = event.order_facts.total_quantity
        cumulative_filled = event.order_facts.cumulative_filled or 0
        average_price = event.order_facts.average_price
        last_fill_price = event.order_facts.last_fill_price
        last_fill_quantity = event.order_facts.last_fill_quantity
        rejection_reason = event.order_facts.rejection_reason

    if event.fill_facts is not None:
        ff = event.fill_facts
        last_fill_id = ff.fill_id
        last_fill_price = ff.fill_price
        last_fill_quantity = ff.fill_quantity
        cumulative_filled = ff.cumulative_filled_after or cumulative_filled
        remaining_quantity = ff.remaining_after
        fill_count = 1
        if ff.fill_price is not None and ff.fill_quantity is not None:
            # Weighted average price
            if previous is not None and previous.cumulative_filled > 0:
                prev_total_price = previous.average_price * previous.cumulative_filled
                new_total_price = ff.fill_price * ff.fill_quantity
                new_cumulative = cumulative_filled
                if new_cumulative > 0:
                    average_price = (prev_total_price + new_total_price) / new_cumulative
            else:
                average_price = ff.fill_price

    # For non-fill events, carry forward previous quantities
    if event.event_type not in (
        BrokerEventType.PARTIAL_FILL,
        BrokerEventType.FILL_RECORDED,
        BrokerEventType.FULL_FILL,
    ):
        if previous is not None:
            if total_quantity is None:
                total_quantity = previous.total_quantity
            if cumulative_filled == 0:
                cumulative_filled = previous.cumulative_filled
            if remaining_quantity is None:
                remaining_quantity = previous.remaining_quantity
            if average_price is None:
                average_price = previous.average_price
            fill_count = previous.fill_count

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
        occurred_at=occurred_at,
        received_at=event.received_at,
    )


# ---------------------------------------------------------------------------
# Day38 lifecycle event mapping
# ---------------------------------------------------------------------------

def _append_lifecycle_from_event(
    db: Session,
    event: BrokerSyncEvent,
) -> None:
    """Append a Day38 lifecycle event derived from the canonical broker event."""
    aggregate_id = event.broker_order_id or event.canonical_id
    sequence = event.canonical_sequence or 1

    payload = {
        "canonical_id": event.canonical_id,
        "broker": event.broker,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "provider_event_id": event.provider_event_id,
        "source_mode": event.source_mode.value,
        "broker_order_id": event.broker_order_id,
    }
    if event.event_timestamp is not None:
        payload["event_timestamp"] = event.event_timestamp.isoformat()
    if event.order_facts is not None:
        payload["order_facts"] = {
            "status": event.order_facts.status.value,
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

    append_lifecycle_event(
        db=db,
        aggregate_type="broker_order",
        aggregate_id=aggregate_id,
        event_type=event.event_type,
        event_version=event.event_version,
        tenant_id=event.tenant_id,
        sequence=sequence,
        position_sequence=None,
        quantity_delta=None,
        position_identity=None,
        occurred_at=event.event_timestamp or event.received_at,
        payload=payload,
        metadata=None,
    )


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

    # --- Terminal-state enforcement ---
    # Find the latest projection for this broker order
    if event.broker_order_id:
        latest_proj = db.execute(
            select(BrokerOrderProjection)
            .where(
                BrokerOrderProjection.tenant_id == event.tenant_id,
                BrokerOrderProjection.broker == event.broker,
                BrokerOrderProjection.broker_order_id == event.broker_order_id,
            )
            .order_by(BrokerOrderProjection.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if latest_proj is not None and latest_proj.is_terminal:
            new_state = _event_canonical_state(event)
            # Allow recovery events to pass through
            if event.event_type != BrokerEventType.ORDER_RECOVERED:
                return {
                    "canonical_id": canonical_id,
                    "action": "REJECTED",
                    "normalized_state": None,
                    "reason": (
                        f"terminal state mutation rejected: order is {latest_proj.status}, "
                        f"cannot apply {event.event_type}"
                    ),
                }

    # --- Build and persist projection ---
    previous = None
    if event.broker_order_id:
        previous = db.execute(
            select(BrokerOrderProjection)
            .where(
                BrokerOrderProjection.tenant_id == event.tenant_id,
                BrokerOrderProjection.broker == event.broker,
                BrokerOrderProjection.broker_order_id == event.broker_order_id,
            )
            .order_by(BrokerOrderProjection.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    projection = _build_projection(event, previous)
    db.add(projection)
    db.flush()  # Get the ID assigned

    # --- Persist idempotency record ---
    idem = BrokerSyncIdempotency(
        canonical_id=canonical_id,
        tenant_id=event.tenant_id,
        broker=event.broker,
        broker_order_id=event.broker_order_id,
        canonical_sequence=event.canonical_sequence,
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

    # --- Day38 lifecycle integration ---
    try:
        _append_lifecycle_from_event(db, event)
    except SAIntegrityError:
        # Day38 conflict — let it propagate so the caller rolls back
        raise
    except Exception:
        # Any lifecycle failure — let it propagate so the caller rolls back
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
