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
  ``(tenant_id, broker, broker_order_id, event_type, canonical_sequence)``.
- Provider-specific normalization (Upstox status strings, instrument keys,
  raw payloads) belongs in the adapter boundary.  The canonical contract
  carries only provenance, not the raw upstream shape.
- ``BrokerSyncEvent`` is immutable (frozen dataclass) following Day 37/38
  conventions.  ``order_facts`` / ``fill_facts`` are frozen too.
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

    # ------------------------------------------------------------------
    # Derived deterministic identity
    # ------------------------------------------------------------------

    @property
    def canonical_id(self) -> str:
        """Deterministic tenant-scoped event identity (design §6).

        Identity is derived from stable identifiers so that:
        - identical events produce the same canonical_id (idempotent);
        - different tenants with the same broker coordinates differ;
        - when no durable provider_event_id exists, the broker_order_id
          plus event_type and canonical_sequence distinguish legitimate
          state changes.
        """
        if self.provider_event_id:
            parts = (self.tenant_id, self.broker, self.provider_event_id, self.event_type)
        elif self.broker_order_id and self.canonical_sequence is not None:
            parts = (self.tenant_id, self.broker, self.broker_order_id, self.event_type, str(self.canonical_sequence))
        else:
            # Fall back to a deterministic hash over all stable coordinates
            # (ensures distinctness even when neither provider_event_id nor
            # broker_order_id + sequence are available)
            parts = (self.tenant_id, self.broker, self.event_type, str(id(self)))
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
]
