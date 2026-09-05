"""Day 37 — Domain Event Foundation contracts.

Immutable typed event envelope for in-process domain events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class DomainEvent:
    """Immutable typed domain event envelope.

    Required fields:
    - event_id: Unique identifier for this event (caller-supplied)
    - event_type: Type of event (e.g., "TradeCreated")
    - aggregate_type: Type of aggregate this event pertains to
    - aggregate_id: Identifier of the aggregate
    - occurred_at: When the event occurred (timezone-aware, caller-supplied)
    - tenant_id: Tenant identifier for multi-tenancy
    - event_version: Version of the event schema
    - payload: Structured event data
    - metadata: Optional structured metadata

    The event is immutable after creation to ensure consistency
    and prevent accidental mutation during handling.
    """

    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime
    tenant_id: str
    event_version: str
    payload: Mapping[str, Any]
    metadata: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        """Validate required fields and timestamp timezone awareness."""
        # Validate that required string fields are not empty
        if not self.event_id:
            raise ValueError("event_id must not be empty")
        if not self.event_type:
            raise ValueError("event_type must not be empty")
        if not self.aggregate_type:
            raise ValueError("aggregate_type must not be empty")
        if not self.aggregate_id:
            raise ValueError("aggregate_id must not be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not self.event_version:
            raise ValueError("event_version must not be empty")

        # Validate timestamp is timezone-aware
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        # Validate payload is mapping-like
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")

        # Validate metadata if provided
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping or None")

    def to_dict(self) -> dict[str, Any]:
        """Convert event to deterministic dictionary representation.

        Returns a dictionary suitable for serialization that preserves
        all event fields in a consistent order.
        """
        result: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": self.tenant_id,
            "event_version": self.event_version,
            "payload": dict(self.payload),
        }
        if self.metadata is not None:
            result["metadata"] = dict(self.metadata)
        return result