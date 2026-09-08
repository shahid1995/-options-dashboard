"""Day 39 Task 1 — Canonical broker-event synchronization contract.

Broker-neutral event contract required by the Day 39 event-driven
broker-state synchronization path.

Semantics:
- ``BrokerSyncEvent`` is the broker-neutral canonical event consumed by
  the synchronization layer.  Every field is broker-neutral — no Upstox
  field names, no provider status strings, no raw payload structures.
- Identity is tenant-scoped SHA-256 over ``\\x1f``-joined
  ``(tenant_id, broker, provider_event_id, event_type)`` when a durable
  provider event ID exists, otherwise
  ``(tenant_id, broker, event_type, broker_order_id, canonical_sequence?, fill_id | fill_facts_digest)``.
  ``broker_order_id`` is mandatory in the fallback path, plus at least
  one additional discriminator (``canonical_sequence`` or ``fill_facts``).
- Provider-specific normalization (Upstox status strings, instrument keys,
  raw payloads) belongs in the adapter boundary.  The canonical contract
  carries only provenance, not the raw upstream shape.
- ``BrokerSyncEvent`` is immutable (frozen dataclass) following Day 37/38
  conventions.  ``order_facts`` / ``fill_facts`` are frozen too.
- Events lacking sufficient deterministic identity are rejected at construction
  time — identity is never invented from object memory addresses, random
  UUIDs, or wall-clock timestamps.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional


# ---------------------------------------------------------------------------
# Canonical event type catalog — broker-neutral
# ---------------------------------------------------------------------------

class BrokerEventType(str, Enum):
    """Canonical broker-event types consumed by the sync layer.

    Provider-specific status strings are mapped to these at the adapter
    boundary; domain code never branches on provider values.
    """

    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FULL_FILL = "FULL_FILL"
    FILL_RECORDED = "FILL_RECORDED"
    ORDER_RECOVERED = "ORDER_RECOVERED"


class BrokerEventSourceMode(str, Enum):
    """How the canonical event reached the synchronization layer."""

    STREAM = "STREAM"          # real-time broker event stream / webhook
    RECOVERY = "RECOVERY"      # fetched during bounded exceptional recovery
    POLLED_SNAPSHOT = "POLLED_SNAPSHOT"  # explicit snapshot (not normal path)


class CanonicalOrderState(str, Enum):
    """Normalized order lifecycle state (design §5/§8).

    Maps onto the Day 38 ``OrderStatus`` vocabulary for replay parity."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Frozen value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderFacts:
    """Normalized order-level state carried by the canonical event.

    Every field is broker-neutral.  Missing/unavailable values stay
    ``None`` — never fabricated into 0 or sentinel strings.
    """

    order_id: str | None = None           # canonical execution/order reference
    broker_order_id: str | None = None    # broker's order identity
    status: CanonicalOrderState = CanonicalOrderState.UNKNOWN
    total_quantity: int | None = None
    cumulative_filled: int | None = None
    average_price: float | None = None
    last_fill_price: float | None = None
    last_fill_quantity: int | None = None
    rejection_reason: str | None = None
    is_terminal: bool = False


@dataclass(frozen=True)
class FillFacts:
    """Normalized fill information carried by the canonical event."""

    fill_id: str | None = None
    fill_quantity: int | None = None
    fill_price: float | None = None
    fill_timestamp: datetime | None = None
    cumulative_filled_after: int | None = None
    remaining_after: int | None = None

    def __post_init__(self) -> None:
        # fill_timestamp must be timezone-aware when provided
        if self.fill_timestamp is not None and self.fill_timestamp.tzinfo is None:
            raise ValueError("fill_timestamp must be timezone-aware")


# ---------------------------------------------------------------------------
# Deep-freeze helpers (reuse Day 38 envelope convention)
# ---------------------------------------------------------------------------

def _deep_freeze(value: Any) -> Any:
    """Recursively freeze a JSON-like value into an immutable, serializable form."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


# ---------------------------------------------------------------------------
# Deterministic event identity (tenant-scoped)
# ---------------------------------------------------------------------------

_CANONICAL_SEP = "\x1f"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Canonical Broker Sync Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BrokerSyncEvent:
    """Broker-neutral canonical synchronization event.

    Required identity:
        tenant_id, broker, event_type, canonical_id (derived)

    Provenance:
        provider_event_id (when available from the provider), source_mode,
        schema_version, received_at

    Time semantics:
        event_timestamp — broker-reported when the event occurred (when available)
        received_at     — local receipt timestamp (required, timezone-aware)

    Optional:
        provider_sequence — provider ordering sequence (None when unavailable)
        broker_order_id / order_facts / fill_fills — normalized state
        metadata — optional structured metadata (deep-frozen)

    Immutability: the dataclass is immutable and ``metadata`` is
    defensively copied at construction.
    """

    tenant_id: str
    broker: str
    event_type: str
    event_version: str
    received_at: datetime
    provider_event_id: Optional[str] = None
    event_timestamp: Optional[datetime] = None
    source_mode: BrokerEventSourceMode = BrokerEventSourceMode.STREAM
    provider_sequence: Optional[int] = None
    broker_order_id: Optional[str] = None
    canonical_sequence: Optional[int] = None
    order_facts: Optional[OrderFacts] = None
    fill_facts: Optional[FillFacts] = None
    metadata: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        # --- Required non-empty strings ---
        for name in ("tenant_id", "broker", "event_type", "event_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")

        # --- Time semantics ---
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if self.event_timestamp is not None and self.event_timestamp.tzinfo is None:
            raise ValueError("event_timestamp must be timezone-aware")

        # --- Provider sequence must be positive when present ---
        if self.provider_sequence is not None:
            if not isinstance(self.provider_sequence, int) or isinstance(self.provider_sequence, bool) or self.provider_sequence < 1:
                raise ValueError("provider_sequence must be a positive integer")

        # --- Canonical sequence must be positive when present ---
        if self.canonical_sequence is not None:
            if not isinstance(self.canonical_sequence, int) or isinstance(self.canonical_sequence, bool) or self.canonical_sequence < 1:
                raise ValueError("canonical_sequence must be a positive integer")

        # --- Metadata must be a mapping or None ---
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping or None")

        # --- Deep-freeze metadata so caller mutation cannot change canonical content ---
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _deep_freeze(self.metadata))

        # --- Fail closed: insufficient deterministic identity ---
        # Identity must never depend on object memory address, random UUIDs,
        # or wall-clock timestamps.  If insufficient stable identity is available,
        # reject the event at construction time.
        #
        # The fallback path requires broker_order_id as a mandatory anchor,
        # PLUS at least one additional discriminator (canonical_sequence or fill_facts).
        # broker_order_id alone is insufficient — multiple distinct events can share the same order.
        # canonical_sequence alone is insufficient — different orders can share the same sequence.
        # fill_facts alone is insufficient — broker_order_id is needed to scope the fill.
        if not self.provider_event_id:
            if not self.broker_order_id:
                raise ValueError(
                    "insufficient deterministic identity: "
                    "provider_event_id missing and broker_order_id required for fallback identity"
                )
            if self.canonical_sequence is None and self.fill_facts is None:
                raise ValueError(
                    "insufficient deterministic identity: "
                    "provider_event_id missing and broker_order_id alone is insufficient; "
                    "canonical_sequence or fill_facts required as additional discriminator"
                )

    # ------------------------------------------------------------------
    # Derived deterministic identity
    # ------------------------------------------------------------------

    @property
    def canonical_id(self) -> str:
        """Deterministic tenant-scoped event identity (design §6).

        Identity hierarchy:

        **Case A — Provider event ID exists:**
        ``(tenant_id, broker, provider_event_id, event_type)``

        **Case B — Provider event ID unavailable:**
        ``(tenant_id, broker, event_type, broker_order_id, canonical_sequence?, fill_id | fill_facts_digest)``

        Where:
        - ``broker_order_id`` is mandatory in the fallback path.
        - ``canonical_sequence`` is included when available (must be positive).
        - ``fill_id`` participates when ``fill_facts`` carries a stable fill ID.
        - ``fill_facts_digest`` is a SHA-256 digest of the canonical fill facts when no fill_id exists
          but fill facts are present.  This ensures two different fill events for the same order
          never collapse into one identity.

        Identity is derived from stable identifiers so that:
        - identical events produce the same canonical_id (idempotent);
        - different tenants with the same broker coordinates differ;
        - when no durable provider_event_id exists, the broker_order_id
          plus event_type and canonical_sequence distinguish legitimate
          state changes.

        Raises:
            ValueError: If insufficient stable identity information is available
                to deterministically identify the event.  This is a fail-closed
                mechanism — identity is never invented from object memory addresses,
                random UUIDs, or wall-clock timestamps.
        """
        if self.provider_event_id:
            parts = (self.tenant_id, self.broker, self.provider_event_id, self.event_type)
        else:
            # Fallback requires broker_order_id as mandatory anchor,
            # plus at least one of canonical_sequence or fill_facts.
            # This is guaranteed by __post_init__ validation.
            parts = [self.tenant_id, self.broker, self.event_type, self.broker_order_id]

            if self.canonical_sequence is not None:
                parts.append(str(self.canonical_sequence))

            if self.fill_facts is not None:
                if self.fill_facts.fill_id:
                    parts.append(self.fill_facts.fill_id)
                else:
                    # Use a stable digest of fill facts to distinguish events
                    # when fill_id is not available but fill facts are.
                    # Canonical serialization: sorted-key JSON of all non-None fill fields.
                    fill_dict = {}
                    for field_name in ("fill_quantity", "fill_price", "cumulative_filled_after", "remaining_after", "fill_timestamp"):
                        val = getattr(self.fill_facts, field_name)
                        if val is not None:
                            fill_dict[field_name] = val.isoformat() if isinstance(val, datetime) else str(val)
                    fill_digest = hashlib.sha256(
                        json.dumps(fill_dict, sort_keys=True, ensure_ascii=True).encode("utf-8")
                    ).hexdigest()
                    parts.append(fill_digest)

        canonical = _CANONICAL_SEP.join(str(p) for p in parts)
        return _sha256_hex(canonical)

    @property
    def event_id(self) -> str:
        """Alias for canonical_id — matches Day 37 DomainEvent vocabulary."""
        return self.canonical_id

    # ------------------------------------------------------------------
    # Tenant safety
    # ------------------------------------------------------------------

    def belongs_to_tenant(self, tenant_id: str) -> bool:
        """Fail-safe tenant check: returns False on mismatch."""
        return self.tenant_id == tenant_id

    # ------------------------------------------------------------------
    # Immutability guards are inherited from frozen=True


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def make_broker_sync_event(
    *,
    tenant_id: str,
    broker: str,
    event_type: str,
    event_version: str = "1.0",
    provider_event_id: Optional[str] = None,
    event_timestamp: Optional[datetime] = None,
    received_at: Optional[datetime] = None,
    source_mode: BrokerEventSourceMode = BrokerEventSourceMode.STREAM,
    provider_sequence: Optional[int] = None,
    broker_order_id: Optional[str] = None,
    canonical_sequence: Optional[int] = None,
    order_facts: Optional[OrderFacts] = None,
    fill_facts: Optional[FillFacts] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> BrokerSyncEvent:
    """Factory with sensible defaults for tests and adapters.

    Defaults:
    - event_version = "1.0"
    - source_mode = BrokerEventSourceMode.STREAM
    - received_at = datetime.now(timezone.utc) when not supplied
    """
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    return BrokerSyncEvent(
        tenant_id=tenant_id,
        broker=broker,
        event_type=event_type,
        event_version=event_version,
        provider_event_id=provider_event_id,
        event_timestamp=event_timestamp,
        received_at=received_at,
        source_mode=source_mode,
        provider_sequence=provider_sequence,
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        order_facts=order_facts,
        fill_facts=fill_facts,
        metadata=metadata,
    )


__all__ = [
    "BrokerSyncEvent",
    "BrokerEventType",
    "BrokerEventSourceMode",
    "CanonicalOrderState",
    "OrderFacts",
    "FillFacts",
    "make_broker_sync_event",
    "ingest_canonical_event",
    "IdempotencyState",
]

# ---------------------------------------------------------------------------
# Idempotent ingestion / normalized projection (Task 2)
# ---------------------------------------------------------------------------
# Task 2 scope: consume canonical broker events exactly once semantically,
# apply normalized local state updates transactionally, and maintain
# idempotency bookkeeping (duplicate = no-op, conflict = rejected).
#
# This is the narrowest ingestion/projection service possible — it does
# NOT contain provider-specific parsing (Task 3), does NOT introduce
# continuous polling (Task 4 is bounded exceptional recovery), and does
# NOT modify broker execution behavior (Task 1 contract only).

class IdempotencyState:
    """Durable idempotency bookkeeping for Task 2.

    Minimal in-memory representation — actual persistence is Task 4 scope.
    """

    def __init__(self) -> None:
        self.applied_ids: set[str] = set()
        self.rejected_ids: set[str] = set()
        self._applied_events: dict[str, BrokerSyncEvent] = {}

    def is_applied(self, canonical_id: str) -> bool:
        return canonical_id in self.applied_ids

    def is_rejected(self, canonical_id: str) -> bool:
        return canonical_id in self.rejected_ids

    def apply(self, canonical_id: str, event: BrokerSyncEvent) -> None:
        self.applied_ids.add(canonical_id)
        self._applied_events[canonical_id] = event

    def reject(self, canonical_id: str) -> None:
        self.rejected_ids.add(canonical_id)

    def get_applied_event(self, canonical_id: str) -> BrokerSyncEvent | None:
        return self._applied_events.get(canonical_id)


# Module-level default state for the narrowest service interface
_default_state: IdempotencyState = IdempotencyState()


def ingest_canonical_event(
    event: BrokerSyncEvent,
    state: IdempotencyState | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Consume a canonical broker event exactly once semantically.

    Rules (design §Task 2):
    - First event applies.
    - Identical duplicate (same canonical_id) is a no-op.
    - Conflicting same identity with different content is rejected.
    - Tenant mismatch is rejected (event tenant must match projection tenant).
    - Terminal events cannot be mutated after application.

    Args:
        event: A canonical ``BrokerSyncEvent`` (already constructed —
          malformed events are rejected at construction time by Task 1).
        state: Optional idempotency state; defaults to module-level state.
        tenant_id: Required tenant context for projection.  If provided,
          the event's tenant_id must match.

    Returns:
        A result dictionary:
        - ``canonical_id`` (str)
        - ``action``: ``APPLIED``, ``DUPLICATE_NOOP``, ``REJECTED``, ``CONFLICT``
        - ``normalized_state``: projected state dict when applied, else ``None``
        - ``reason``: human-readable explanation (None when action is APPLIED)
    """
    s = state if state is not None else _default_state
    canonical_id = event.canonical_id

    # --- Malformed event check: identity must be present ---
    if not canonical_id:
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": "empty canonical identity",
        }

    # --- Tenant isolation: event tenant must match projection tenant ---
    if tenant_id is not None and not event.belongs_to_tenant(tenant_id):
        s.reject(canonical_id)
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": f"tenant mismatch: event tenant '{event.tenant_id}' != projection tenant '{tenant_id}'",
        }

    # --- Idempotency: already applied = no-op ---
    if s.is_applied(canonical_id):
        return {
            "canonical_id": canonical_id,
            "action": "DUPLICATE_NOOP",
            "normalized_state": None,
            "reason": "already applied",
        }

    # --- Idempotency: previously rejected = stay rejected ---
    if s.is_rejected(canonical_id):
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": "previously rejected",
        }

    # --- Conflict detection: if an event with the same identity but
    #     different content was already processed under a different identity
    #     (which shouldn't happen with deterministic identity), reject ---
    # This is a safety net since deterministic identity means same event
    # => same canonical_id. A different event => different identity.

    # --- Terminal state enforcement ---
    # If a previous event for this order was terminal, reject non-recover
    # mutations.  (For narrowest service, terminal check is on the
    # normalized state projection.)
    # This is validated during projection below.

    # --- Normalized projection logic (Task 2 scope) ---
    projected_state = _project_normalized_state(event, s)
    if projected_state is None:
        # Event was rejected by terminal-state enforcement
        s.reject(canonical_id)
        return {
            "canonical_id": canonical_id,
            "action": "REJECTED",
            "normalized_state": None,
            "reason": "terminal state mutation rejected",
        }

    # Commit bookkeeping and return applied state
    s.apply(canonical_id, event)
    return {
        "canonical_id": canonical_id,
        "action": "APPLIED",
        "normalized_state": projected_state,
        "reason": None,
    }


def _project_normalized_state(
    event: BrokerSyncEvent,
    state: IdempotencyState,
) -> dict[str, Any] | None:
    """Derive normalized projection from a canonical event.

    Uses broker-neutral vocabulary only (no Upstox-specific fields).
    The projection is deterministic and idempotent.

    Returns ``None`` if the event would illegally mutate a terminal state.
    """
    result: dict[str, Any] = {
        "canonical_id": event.canonical_id,
        "tenant_id": event.tenant_id,
        "broker_order_id": event.broker_order_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "status": None,
        "fill_details": None,
        "is_terminal": False,
    }

    # Map event type to normalized canonical state
    if event.event_type == BrokerEventType.ORDER_ACCEPTED:
        result["status"] = CanonicalOrderState.OPEN
    elif event.event_type == BrokerEventType.ORDER_SUBMITTED:
        result["status"] = CanonicalOrderState.SUBMITTED
    elif event.event_type == BrokerEventType.ORDER_REJECTED:
        result["status"] = CanonicalOrderState.REJECTED
        result["is_terminal"] = True
    elif event.event_type == BrokerEventType.ORDER_CANCELLED:
        result["status"] = CanonicalOrderState.CANCELLED
        result["is_terminal"] = True
    elif event.event_type == BrokerEventType.ORDER_EXPIRED:
        result["status"] = CanonicalOrderState.EXPIRED
        result["is_terminal"] = True
    elif event.event_type in (BrokerEventType.PARTIAL_FILL, BrokerEventType.FILL_RECORDED):
        result["status"] = CanonicalOrderState.PARTIALLY_FILLED
    elif event.event_type == BrokerEventType.FULL_FILL:
        result["status"] = CanonicalOrderState.FILLED
        result["is_terminal"] = True
    else:
        result["status"] = CanonicalOrderState.UNKNOWN

    # Incorporate fill facts when present
    if event.fill_facts is not None:
        result["fill_details"] = {
            "fill_id": event.fill_facts.fill_id,
            "fill_quantity": event.fill_facts.fill_quantity,
            "fill_price": event.fill_facts.fill_price,
            "fill_timestamp": event.fill_facts.fill_timestamp.isoformat()
            if event.fill_facts.fill_timestamp is not None else None,
            "cumulative_filled_after": event.fill_facts.cumulative_filled_after,
            "remaining_after": event.fill_facts.remaining_after,
        }

    # Incorporate order facts when present
    if event.order_facts is not None:
        result["order_facts"] = {
            "status": event.order_facts.status.value if event.order_facts.status else None,
            "total_quantity": event.order_facts.total_quantity,
            "cumulative_filled": event.order_facts.cumulative_filled,
            "is_terminal": event.order_facts.is_terminal,
        }

    # Merge event identity into projection for auditability
    result["event_identity"] = {
        "canonical_id": event.canonical_id,
        "provider_event_id": event.provider_event_id,
        "received_at": event.received_at.isoformat(),
        "source_mode": event.source_mode.value,
    }

    return result
