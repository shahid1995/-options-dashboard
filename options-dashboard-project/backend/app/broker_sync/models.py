"""Day 39 Task 2 — Durable broker-sync persistence models.

Durable idempotency record and normalized broker-order projection.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BrokerSyncIdempotency(Base):
    """Durable idempotency record for canonical broker events.

    Survives process/worker/application restart.  The database enforces
    uniqueness on ``canonical_id`` so concurrent duplicate delivery cannot
    produce two semantic applications.
    """

    __tablename__ = "broker_sync_idempotency"

    canonical_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    canonical_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_version: Mapped[str] = mapped_column(String(16), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="APPLIED")
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BrokerOrderProjection(Base):
    """Durable normalized broker-order state.

    One row per canonical broker event.  The normalized status, fill
    quantities, and terminal state are durably persisted so that the
    projection survives restart and can be used for duplicate detection
    and terminal-state enforcement.
    """

    __tablename__ = "broker_order_projection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker_order_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    canonical_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cumulative_filled: Mapped[int] = mapped_column(Integer, default=0)
    remaining_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_fill_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    fill_count: Mapped[int] = mapped_column(Integer, default=0)
    last_fill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "broker",
            "broker_order_id",
            "canonical_id",
            name="uq_broker_projection_tenant_broker_order_canonical",
        ),
    )
