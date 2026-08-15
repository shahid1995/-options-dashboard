from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaperAccount(Base):
    """Per-user simulated account (starting capital) backing the journal."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=500000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Trade(Base):
    """A paper trade: one strategy execution, made up of one or more legs."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    strategy_tag: Mapped[str] = mapped_column(String(64), default="Custom")
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    # Net entry money flow in rupees (negative = net credit received, e.g. a
    # short vertical spread; positive = net debit paid, e.g. a long spread).
    entry_net: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    legs: Mapped[list["Leg"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", order_by="Leg.id"
    )


class Leg(Base):
    """One option leg of a paper trade."""

    __tablename__ = "legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    expiration_date: Mapped[str] = mapped_column(String(10))
    strike_price: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    action: Mapped[str] = mapped_column(String(8))  # buy | sell
    premium: Mapped[float] = mapped_column(Float)  # simulated premium per unit
    quantity: Mapped[int] = mapped_column(Integer)  # number of lots
    lot_size: Mapped[int] = mapped_column(Integer)  # contracts per lot
    entry_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade: Mapped[Trade] = relationship(back_populates="legs")
