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
# Deterministic event identity
# ---------------------------------------------------------------------------

def event_id(
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    sequence: int,
) -> str:
    """Deterministic SHA256 event identity.

    Uses ASCII Unit Separator (\\x1f) as an unambiguous delimiter so that
    no valid identifier can ever collide with the separator.
    """
    canonical = f"{aggregate_type}\x1f{aggregate_id}\x1f{event_type}\x1f{sequence}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
            "aggregate_id",
            "sequence",
            name="uq_lifecycle_aggregate_sequence",
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

def next_event_sequence(db: SessionLocal, aggregate_id: str) -> int:
    """Allocate the next execution-scoped sequence for a lifecycle aggregate.

    Returns ``MAX(sequence) + 1`` for the given ``aggregate_id``.  The
    caller is responsible for holding the ``StrategyExecution`` row lock
    (``SELECT ... FOR UPDATE``) before calling this function so that
    concurrent writers to the same aggregate are serialized.
    """
    max_seq = db.execute(
        select(func.max(TradeLifecycleEvent.sequence)).where(
            TradeLifecycleEvent.aggregate_id == aggregate_id
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
                (tenant_id, user_id, symbol, expiry, strike, option_type, last_position_sequence, created_at, updated_at)
            VALUES
                (:tenant_id, :user_id, :symbol, :expiry, :strike, :option_type, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
        # Defensive fallback: should never happen with the upsert above.
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
      - same (aggregate_id, sequence) + identical → idempotent
      - same (aggregate_id, sequence) + different → conflict (raises)
    """
    computed_id = event_id(aggregate_type, aggregate_id, event_type, sequence)

    payload_json = __import__("json").dumps(payload, sort_keys=True)
    metadata_json = (
        __import__("json").dumps(metadata, sort_keys=True) if metadata else None
    )

    # Canonical content for duplicate/conflict detection
    canonical_payload = payload_json
    canonical_meta = metadata_json or ""

    existing = db.execute(
        select(TradeLifecycleEvent).where(TradeLifecycleEvent.event_id == computed_id)
    ).scalar_one_or_none()

    if existing is not None:
        # Same event_id: compare full canonical content
        same_content = (
            existing.aggregate_type == aggregate_type
            and existing.aggregate_id == aggregate_id
            and existing.event_type == event_type
            and existing.event_version == event_version
            and existing.tenant_id == tenant_id
            and existing.sequence == sequence
            and existing.position_sequence == position_sequence
            and existing.payload_json == canonical_payload
            and (existing.metadata_json or "") == canonical_meta
            and existing.quantity_delta == quantity_delta
        )
        if same_content:
            return existing  # idempotent — identical duplicate
        raise IntegrityError(
            f"event_id {computed_id} exists with different canonical content"
        )

    # Check aggregate+sequence conflict (independent of event_id)
    agg_seq_conflict = db.execute(
        select(TradeLifecycleEvent).where(
            TradeLifecycleEvent.aggregate_id == aggregate_id,
            TradeLifecycleEvent.sequence == sequence,
        )
    ).scalar_one_or_none()
    if agg_seq_conflict is not None:
        same_content = (
            agg_seq_conflict.aggregate_type == aggregate_type
            and agg_seq_conflict.event_type == event_type
            and agg_seq_conflict.payload_json == canonical_payload
            and agg_seq_conflict.quantity_delta == quantity_delta
        )
        if not same_content:
            raise IntegrityError(
                f"Aggregate {aggregate_id} sequence {sequence} already has different event"
            )
        return agg_seq_conflict  # idempotent

    pos_identity = position_identity or {}
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
        position_identity_user_id=pos_identity.get("user_id"),
        position_identity_symbol=pos_identity.get("symbol"),
        position_identity_expiry=pos_identity.get("expiry"),
        position_identity_strike=pos_identity.get("strike"),
        position_identity_option_type=pos_identity.get("option_type"),
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
