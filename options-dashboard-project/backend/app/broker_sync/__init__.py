"""Day 39 — Canonical broker-event synchronization contract + durable ingestion.

Task 1: Canonical event contract (BrokerSyncEvent, identity, validation).
Task 2: Durable ingestion pipeline (idempotency, projection, Day38 lifecycle).
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
    """Canonical broker-event types consumed by the sync layer."""

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

    STREAM = "STREAM"
    RECOVERY = "RECOVERY"
    POLLED_SNAPSHOT = "POLLED_SNAPSHOT"


class CanonicalOrderState(str, Enum):
    """Normalized order lifecycle state (design §5/§8)."""

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
    """Normalized order-level state carried by the canonical event."""

    order_id: str | None = None
    broker_order_id: str | None = None
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
        if self.fill_timestamp is not None and self.fill_timestamp.tzinfo is None:
            raise ValueError("fill_timestamp must be timezone-aware")


# ---------------------------------------------------------------------------
# Deep-freeze helpers
# ---------------------------------------------------------------------------

def _deep_freeze(value: Any) -> Any:
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
    """Broker-neutral canonical synchronization event."""

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
        for name in ("tenant_id", "broker", "event_type", "event_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")

        # Coerce enum values to plain strings so canonical_id is deterministic
        if isinstance(self.event_type, Enum):
            object.__setattr__(self, "event_type", self.event_type.value)

        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if self.event_timestamp is not None and self.event_timestamp.tzinfo is None:
            raise ValueError("event_timestamp must be timezone-aware")

        if self.provider_sequence is not None:
            if not isinstance(self.provider_sequence, int) or isinstance(self.provider_sequence, bool) or self.provider_sequence < 1:
                raise ValueError("provider_sequence must be a positive integer")

        if self.canonical_sequence is not None:
            if not isinstance(self.canonical_sequence, int) or isinstance(self.canonical_sequence, bool) or self.canonical_sequence < 1:
                raise ValueError("canonical_sequence must be a positive integer")

        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping or None")

        if self.metadata is not None:
            object.__setattr__(self, "metadata", _deep_freeze(self.metadata))

        # Fail closed: insufficient deterministic identity
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

    @property
    def canonical_id(self) -> str:
        """Deterministic tenant-scoped event identity."""
        if self.provider_event_id:
            parts = (self.tenant_id, self.broker, self.provider_event_id, self.event_type)
        else:
            parts = [self.tenant_id, self.broker, self.event_type, self.broker_order_id]

            if self.canonical_sequence is not None:
                parts.append(str(self.canonical_sequence))

            if self.fill_facts is not None:
                if self.fill_facts.fill_id:
                    parts.append(self.fill_facts.fill_id)
                else:
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
        return self.canonical_id

    def belongs_to_tenant(self, tenant_id: str) -> bool:
        return self.tenant_id == tenant_id


# ---------------------------------------------------------------------------
# Factory
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
    """Factory with sensible defaults for tests and adapters."""
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


# ---------------------------------------------------------------------------
# Task 2 — Durable ingestion (re-exports)
# ---------------------------------------------------------------------------

from app.broker_sync.ingestion import (  # noqa: E402
    IngestionError,
    ingest_canonical_event,
)

__all__ = [
    # Task 1 — canonical contract
    "BrokerSyncEvent",
    "BrokerEventType",
    "BrokerEventSourceMode",
    "CanonicalOrderState",
    "OrderFacts",
    "FillFacts",
    "make_broker_sync_event",
    # Task 2 — durable ingestion
    "ingest_canonical_event",
    "IngestionError",
]
