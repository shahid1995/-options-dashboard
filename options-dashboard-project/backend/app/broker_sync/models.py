"""Broker-sync idempotency model.

Durable idempotency record for canonical broker events.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BrokerSyncIdempotency(Base):
    """Durable idempotency record for canonical broker events.

    Persisted alongside the normalized projection and Day38 lifecycle
    event within a single caller-owned transaction.  The ``canonical_id``
    primary key enforces durability: a duplicate identity cannot be
    inserted twice, so even after process restart the idempotency state
    survives.
    """

    __tablename__ = "broker_sync_idempotency"

    canonical_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    canonical_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_version: Mapped[str] = mapped_column(String(16), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("canonical_id", name="uq_broker_sync_idempotency_canonical_id"),
    )


class BrokerOrderProjection(Base):
    """Normalized broker-order state (current-state representation).

    One row per canonical event, but the *current* state is reconstructed
    deterministically via the ``canonical_sequence`` ordering (not insertion
    time).  The row with the highest ``canonical_sequence`` for a given
    tenant+broker+broker_order_id is the current state.
    """

    __tablename__ = "broker_order_projection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cumulative_filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_fill_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    fill_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fill_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    canonical_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class BrokerSyncSequenceAnchor(Base):
    """Durable monotonic sequence for broker-order event ordering.

    Uses an upsert-based counter so the sequence allocation is atomic
    at the database level.  The anchor stores the last applied
    ``canonical_sequence`` for a given tenant+broker+broker_order_id,
    enabling gap/stale detection.
    """

    __tablename__ = "broker_sync_sequence_anchor"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    broker: Mapped[str] = mapped_column(String(64), primary_key=True)
    broker_order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "broker", "broker_order_id",
            name="uq_broker_sync_sequence_anchor_identity",
        ),
    )
