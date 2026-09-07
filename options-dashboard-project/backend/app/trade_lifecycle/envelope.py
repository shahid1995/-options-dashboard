"""Day 38 Task 2 — Immutable lifecycle event envelope + canonical identity.

Pure-domain module: no SQLAlchemy, no DB access. Hosts the deterministic
identity and canonical-content primitives consumed by
``app.trade_lifecycle.persistence`` (Task 1) so that the envelope and the
persisted representation cannot drift apart.

Semantics are exactly the verified Task 1 semantics:

- ``event_id`` is SHA-256 over ``\\x1f``-joined UTF-8 of
  ``(tenant_id, aggregate_type, aggregate_id, event_type, sequence)``
  — tenant-scoped, lowercase hex, byte-for-byte identical to
  ``persistence.event_id``.
- ``event_id`` identifies *aggregate + event type + lifecycle sequence*,
  NOT the payload. Content integrity is validated separately by canonical
  content comparison (design §8a/§11).
- Canonical content covers every semantically relevant persisted field,
  serialized as sorted-key, ensure-ASCII JSON; ``occurred_at`` is
  normalized to UTC before serialization.
- ``metadata=None`` and ``metadata={}`` are distinct (DD-3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

# ---------------------------------------------------------------------------
# Deterministic event identity (tenant-scoped) — moved verbatim from Task 1
# ---------------------------------------------------------------------------

_CANONICAL_SEP = "\x1f"


def _canonical_str(*parts: object) -> str:
    """Join parts with the ASCII Unit Separator (\\x1f)."""
    return _CANONICAL_SEP.join(str(p) for p in parts)


def event_id(
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    sequence: int,
) -> str:
    """Deterministic SHA256 event identity — tenant-scoped.

    The identity includes tenant_id so that identical lifecycle
    coordinates in two tenants produce different event IDs.

    Identity is deliberately computed ONLY from the finalized identity
    coordinates above. Payload, metadata, occurred_at, quantity_delta,
    position_sequence, position_identity and event_version do NOT
    participate in identity (they participate in canonical content).
    """
    canonical = _canonical_str(tenant_id, aggregate_type, aggregate_id, event_type, sequence)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Canonical persisted-event content — moved verbatim from Task 1
# ---------------------------------------------------------------------------

def canonical_persisted_content(
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    sequence: int,
    event_type: str,
    event_version: str,
    position_sequence: Optional[int],
    quantity_delta: Optional[int],
    position_identity_user_id: Optional[str],
    position_identity_symbol: Optional[str],
    position_identity_expiry: Optional[str],
    position_identity_strike: Optional[float],
    position_identity_option_type: Optional[str],
    occurred_at: datetime,
    payload_json: str,
    metadata_json: Optional[str],
) -> str:
    """Canonical byte-level representation of every semantically relevant
    persisted lifecycle field.

    Used for idempotent-vs-conflict duplicate detection.  The string is
    deterministic: sorted field names, no date/DB-server values.

    occurred_at is normalized to UTC naive for canonical representation
    because SQLite does not preserve timezone info and we store in UTC.
    """
    # Normalize occurred_at to UTC naive for canonical representation
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    fields = {
        "tenant_id": tenant_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "sequence": sequence,
        "event_type": event_type,
        "event_version": event_version,
        "position_sequence": position_sequence,
        "quantity_delta": quantity_delta,
        "position_identity_user_id": position_identity_user_id,
        "position_identity_symbol": position_identity_symbol,
        "position_identity_expiry": position_identity_expiry,
        "position_identity_strike": position_identity_strike,
        "position_identity_option_type": position_identity_option_type,
        "occurred_at": occurred_at.isoformat(),
        "payload_json": payload_json,
        "metadata_json": metadata_json,
    }
    return json.dumps(fields, sort_keys=True, ensure_ascii=True)


# ---------------------------------------------------------------------------
# Deep-freeze helpers (Task2 Finding #3)
# ---------------------------------------------------------------------------

def _deep_freeze(value: Any) -> Any:
    """Recursively freeze a JSON-like value into an immutable, serializable form.

    Mappings become ``MappingProxyType`` and lists become tuples.  Because an
    entirely fresh structure is built, mutating the caller's ORIGINAL nested
    structures after construction cannot change the envelope; and because the
    stored structure is immutable, a caller cannot mutate it through the
    envelope either.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _deep_unfreeze(value: Any) -> Any:
    """Convert the frozen form back to plain dict/list for deterministic JSON."""
    if isinstance(value, Mapping):
        return {k: _deep_unfreeze(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_deep_unfreeze(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Immutable value objects
# ---------------------------------------------------------------------------

def _require_non_empty(value: object, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_mapping(value: object, name: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")


def _require_positive(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1")


def _utc_naive_isoformat(occurred_at: datetime) -> str:
    if occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    return (
        occurred_at.astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat()
    )


@dataclass(frozen=True)
class PositionIdentity:
    """Approved Day 38 position identity.

    ``(user_id, symbol, expiry, strike, option_type)`` — instrument-netted
    identity used by position reconstruction. This is NOT the lifecycle
    aggregate identity (``aggregate_id``); executions own aggregates,
    positions are identified per instrument.
    """

    user_id: str
    symbol: str
    expiry: str
    strike: float
    option_type: str

    def __post_init__(self) -> None:
        for name in ("user_id", "symbol", "expiry", "option_type"):
            _require_non_empty(getattr(self, name), f"position_identity.{name}")
        if not isinstance(self.strike, (int, float)) or isinstance(self.strike, bool):
            raise TypeError("position_identity.strike must be a number")
        # DD-4: strike is float (matches the Task 1 Float column). No Decimal.
        object.__setattr__(self, "strike", float(self.strike))


@dataclass(frozen=True)
class TradeLifecycleEventEnvelope:
    """Immutable lifecycle event envelope (Day 38).

    Follows the Day 37 ``DomainEvent`` frozen-dataclass convention and is
    ``DomainEvent``-compatible via :meth:`to_domain_event`. Day 37 code is
    NOT modified (design §18).

    Immutability: the dataclass is frozen AND ``payload``/``metadata``
    mappings are defensively copied at construction, so canonical output
    can never silently change because a caller mutated its original dict.

    ``event_id`` is a derived property computed from the finalized identity
    coordinates (tenant, aggregate, event type, sequence) — it is never an
    independently mutable constructor value (design §8a ordering).
    """

    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    event_version: str
    sequence: int
    occurred_at: datetime
    payload: Mapping[str, Any]
    position_sequence: Optional[int] = None
    position_identity: Optional[PositionIdentity] = None
    quantity_delta: Optional[int] = None
    metadata: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        # Required non-empty strings
        for name in (
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            "event_type",
            "event_version",
        ):
            _require_non_empty(getattr(self, name), name)

        # Sequence invariants
        _require_positive(self.sequence, "sequence")
        if self.position_sequence is not None:
            _require_positive(self.position_sequence, "position_sequence")

        # Quantity delta: signed integer or None
        if self.quantity_delta is not None:
            if not isinstance(self.quantity_delta, int) or isinstance(self.quantity_delta, bool):
                raise TypeError("quantity_delta must be an integer or None")

        # Timestamp must be timezone-aware (Day 37 DomainEvent parity)
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        # Payload must be a mapping; metadata None or mapping (None != {})
        _require_mapping(self.payload, "payload")
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping or None")

        # DD-3 + Task2 Finding #3: deep-freeze payload/metadata so that BOTH
        # mutation of the caller's original nested structures AND mutation
        # through the envelope cannot change canonical content after
        # construction.
        object.__setattr__(self, "payload", _deep_freeze(self.payload))
        object.__setattr__(
            self,
            "metadata",
            None if self.metadata is None else _deep_freeze(self.metadata),
        )

    # ------------------------------------------------------------------
    # Derived deterministic identity
    # ------------------------------------------------------------------

    @property
    def event_id(self) -> str:
        """Deterministic tenant-scoped event identity (design §8a)."""
        return event_id(
            self.tenant_id,
            self.aggregate_type,
            self.aggregate_id,
            self.event_type,
            self.sequence,
        )

    # ------------------------------------------------------------------
    # Canonical content
    # ------------------------------------------------------------------

    def canonical_content(self) -> str:
        """Deterministic canonical representation of the full event.

        Includes ALL semantically relevant fields (design §11): identity
        coordinates, sequences, position identity, event type/version,
        UTC-normalized occurred_at, quantity_delta, payload and metadata.
        """
        identity = self.position_identity
        return canonical_persisted_content(
            tenant_id=self.tenant_id,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            sequence=self.sequence,
            event_type=self.event_type,
            event_version=self.event_version,
            position_sequence=self.position_sequence,
            quantity_delta=self.quantity_delta,
            position_identity_user_id=identity.user_id if identity else None,
            position_identity_symbol=identity.symbol if identity else None,
            position_identity_expiry=identity.expiry if identity else None,
            position_identity_strike=identity.strike if identity else None,
            position_identity_option_type=identity.option_type if identity else None,
            occurred_at=self.occurred_at,
            payload_json=json.dumps(_deep_unfreeze(self.payload), sort_keys=True),
            metadata_json=(
                None
                if self.metadata is None
                else json.dumps(_deep_unfreeze(self.metadata), sort_keys=True)
            ),
        )

    # ------------------------------------------------------------------
    # Day 37 compatibility (design §18 — DomainEvent is NOT modified)
    # ------------------------------------------------------------------

    def to_domain_event(self):
        """Build a Day 37 ``DomainEvent`` from this envelope."""
        from app.domain_events.contracts import DomainEvent

        # Hand DomainEvent plain (deep-copied) mappings — the same JSON-able
        # structures Day 37 expects — while this envelope keeps its immutable
        # frozen copies internally.
        return DomainEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            occurred_at=self.occurred_at,
            tenant_id=self.tenant_id,
            event_version=self.event_version,
            payload=_deep_unfreeze(self.payload),
            metadata=(
                None if self.metadata is None else _deep_unfreeze(self.metadata)
            ),
        )


def canonical_event_content(envelope: TradeLifecycleEventEnvelope) -> str:
    """Module-level canonical content function (Task 2 contract)."""
    return envelope.canonical_content()


__all__ = [
    "PositionIdentity",
    "TradeLifecycleEventEnvelope",
    "canonical_event_content",
    "canonical_persisted_content",
    "event_id",
]
