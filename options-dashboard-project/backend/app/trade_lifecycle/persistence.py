"""Day 38 trade lifecycle persistence foundation.

Implements the append-only ``trade_lifecycle_events`` table and the
concurrency-safe ``position_sequence_anchor`` table described in the
approved Day 38 design.

Conventions:
- Existing authoritative paper-trading state (StrategyExecution, PaperOrder,
  Position, PaperTransaction) is NOT replaced.
- All writes happen within the caller's transaction; this module never
  commits or rolls back independently.
- SQLite-compatible types are used so the same model works for local
  deterministic tests; PostgreSQL-compatible types are used where
  required (e.g. Integer for quantity_delta, Float for strike).
"""

import hashlib
import json as _json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.db import Base, SessionLocal


# ---------------------------------------------------------------------------
# Deterministic event identity (tenant-scoped)
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
    """
    canonical = _canonical_str(tenant_id, aggregate_type, aggregate_id, event_type, sequence)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Canonical event content for duplicate / conflict detection
# ---------------------------------------------------------------------------

def _canonical_event_content(
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
    return _json.dumps(fields, sort_keys=True, ensure_ascii=True)


def _event_to_canonical(ev: "TradeLifecycleEvent") -> str:
    """Build canonical content from a persisted event row."""
    return _canonical_event_content(
        tenant_id=ev.tenant_id,
        aggregate_type=ev.aggregate_type,
        aggregate_id=ev.aggregate_id,
        sequence=ev.sequence,
        event_type=ev.event_type,
        event_version=ev.event_version,
        position_sequence=ev.position_sequence,
        quantity_delta=ev.quantity_delta,
        position_identity_user_id=ev.position_identity_user_id,
        position_identity_symbol=ev.position_identity_symbol,
        position_identity_expiry=ev.position_identity_expiry,
        position_identity_strike=ev.position_identity_strike,
        position_identity_option_type=ev.position_identity_option_type,
        occurred_at=ev.occurred_at,
        payload_json=ev.payload_json,
        metadata_json=ev.metadata_json,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TradeLifecycleEvent(Base):
    """Append-only trade lifecycle event record."""

    __tablename__ = "trade_lifecycle_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    position_sequence: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    quantity_delta: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    position_identity_user_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    position_identity_symbol: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    position_identity_expiry: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )
    position_identity_strike: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    position_identity_option_type: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            "sequence",
            name="uq_lifecycle_tenant_aggregate_sequence",
        ),
        UniqueConstraint(
            "tenant_id",
            "position_identity_user_id",
            "position_identity_symbol",
            "position_identity_expiry",
            "position_identity_strike",
            "position_identity_option_type",
            "position_sequence",
            name="uq_position_sequence",
        ),
    )


class PositionSequenceAnchor(Base):
    """Concurrency-safe anchor for position-scoped sequence allocation.

    One row per PositionIdentity: ``(tenant_id, user_id, symbol, expiry,
    strike, option_type)``.  The row is created on first use via an
    atomic upsert; concurrent writers are serialized by the database row
    lock.
    """

    __tablename__ = "position_sequence_anchor"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, primary_key=True)
    expiry: Mapped[str] = mapped_column(String(10), nullable=False, primary_key=True)
    strike: Mapped[float] = mapped_column(Float, nullable=False, primary_key=True)
    option_type: Mapped[str] = mapped_column(String(8), nullable=False, primary_key=True)
    last_position_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Sequence allocation helpers
# ---------------------------------------------------------------------------

def next_event_sequence(db: SessionLocal, tenant_id: str, aggregate_type: str, aggregate_id: str) -> int:
    """Allocate the next tenant-scoped sequence for a lifecycle aggregate.

    Returns ``MAX(sequence) + 1`` for the given
    ``(tenant_id, aggregate_type, aggregate_id)``.  The caller is
    responsible for holding the ``StrategyExecution`` row lock
    (``SELECT ... FOR UPDATE``) before calling this function so that
    concurrent writers to the same aggregate are serialized.
    """
    max_seq = db.execute(
        select(func.max(TradeLifecycleEvent.sequence)).where(
            TradeLifecycleEvent.tenant_id == tenant_id,
            TradeLifecycleEvent.aggregate_type == aggregate_type,
            TradeLifecycleEvent.aggregate_id == aggregate_id,
        )
    ).scalar()
    return (max_seq or 0) + 1


def allocate_position_sequence(
    db: SessionLocal,
    tenant_id: str,
    user_id: str,
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
) -> int:
    """Allocate the next position-scoped sequence for a PositionIdentity.

    Uses an atomic ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``
    upsert on ``position_sequence_anchor`` so that the first-event case
    (no existing row) is handled without a separate ``SELECT … FOR
    UPDATE`` + ``INSERT`` race window.

    If the transaction is rolled back, the anchor update and any
    associated event insert are also rolled back — no sequence number
    is "burned".
    """
    result = db.execute(
        text(
            """
            INSERT INTO position_sequence_anchor
                (tenant_id, user_id, symbol, expiry, strike, option_type,
                 last_position_sequence, created_at, updated_at)
            VALUES
                (:tenant_id, :user_id, :symbol, :expiry, :strike, :option_type,
                 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id, user_id, symbol, expiry, strike, option_type)
            DO UPDATE SET
                last_position_sequence = position_sequence_anchor.last_position_sequence + 1,
                updated_at = CURRENT_TIMESTAMP
            RETURNING last_position_sequence
            """
        ),
        dict(
            tenant_id=tenant_id,
            user_id=user_id,
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        ),
    ).scalar()
    if result is None:
        raise RuntimeError("Failed to allocate position_sequence")
    return int(result)


# ---------------------------------------------------------------------------
# Event persistence
# ---------------------------------------------------------------------------

def append_lifecycle_event(
    db: SessionLocal,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    event_version: str,
    tenant_id: str,
    sequence: int,
    position_sequence: Optional[int],
    quantity_delta: Optional[int],
    position_identity: Optional[dict],
    occurred_at: datetime,
    payload: dict,
    metadata: Optional[dict] = None,
) -> TradeLifecycleEvent:
    """Persist a single lifecycle event with deterministic identity.

    Implements the approved duplicate/conflict semantics:
      - same event_id + identical canonical content → idempotent (no insert)
      - same event_id + different content → integrity conflict (raises)
      - same (tenant_id, aggregate_type, aggregate_id, sequence) + identical → idempotent
      - same (tenant_id, aggregate_type, aggregate_id, sequence) + different → conflict (raises)
    """
    computed_id = event_id(tenant_id, aggregate_type, aggregate_id, event_type, sequence)

    payload_json = _json.dumps(payload, sort_keys=True)
    metadata_json = (
        _json.dumps(metadata, sort_keys=True) if metadata else None
    )

    pos_identity = position_identity or {}
    pi_user = pos_identity.get("user_id")
    pi_symbol = pos_identity.get("symbol")
    pi_expiry = pos_identity.get("expiry")
    pi_strike = pos_identity.get("strike")
    pi_option_type = pos_identity.get("option_type")

    incoming_canonical = _canonical_event_content(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        sequence=sequence,
        event_type=event_type,
        event_version=event_version,
        position_sequence=position_sequence,
        quantity_delta=quantity_delta,
        position_identity_user_id=pi_user,
        position_identity_symbol=pi_symbol,
        position_identity_expiry=pi_expiry,
        position_identity_strike=pi_strike,
        position_identity_option_type=pi_option_type,
        occurred_at=occurred_at,
        payload_json=payload_json,
        metadata_json=metadata_json,
    )

    # --- Check by event_id ---
    existing = db.execute(
        select(TradeLifecycleEvent).where(TradeLifecycleEvent.event_id == computed_id)
    ).scalar_one_or_none()

    if existing is not None:
        if _event_to_canonical(existing) == incoming_canonical:
            return existing  # idempotent — identical duplicate
        raise IntegrityError(
            f"event_id {computed_id} exists with different canonical content"
        )

    # --- Check by (tenant_id, aggregate_type, aggregate_id, sequence) ---
    agg_seq_conflict = db.execute(
        select(TradeLifecycleEvent).where(
            TradeLifecycleEvent.tenant_id == tenant_id,
            TradeLifecycleEvent.aggregate_type == aggregate_type,
            TradeLifecycleEvent.aggregate_id == aggregate_id,
            TradeLifecycleEvent.sequence == sequence,
        )
    ).scalar_one_or_none()
    if agg_seq_conflict is not None:
        if _event_to_canonical(agg_seq_conflict) == incoming_canonical:
            return agg_seq_conflict  # idempotent
        raise IntegrityError(
            f"(tenant={tenant_id}, agg_type={aggregate_type}, agg_id={aggregate_id}, "
            f"seq={sequence}) already has different event"
        )

    # --- Insert new event ---
    ev = TradeLifecycleEvent(
        event_id=computed_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        event_version=event_version,
        tenant_id=tenant_id,
        sequence=sequence,
        position_sequence=position_sequence,
        quantity_delta=quantity_delta,
        position_identity_user_id=pi_user,
        position_identity_symbol=pi_symbol,
        position_identity_expiry=pi_expiry,
        position_identity_strike=pi_strike,
        position_identity_option_type=pi_option_type,
        occurred_at=occurred_at,
        payload_json=payload_json,
        metadata_json=metadata_json,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ev)
    return ev


class IntegrityError(Exception):
    """Raised when a conflicting duplicate event is detected."""


__all__ = [
    "event_id",
    "TradeLifecycleEvent",
    "PositionSequenceAnchor",
    "next_event_sequence",
    "allocate_position_sequence",
    "append_lifecycle_event",
    "IntegrityError",
]
