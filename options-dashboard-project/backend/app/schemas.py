from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LegOrderIn(BaseModel):
    """One executed option leg, as filled by the paper trading engine."""

    symbol: str = Field(..., min_length=1)
    expiration_date: str = Field(..., min_length=1)
    strike_price: float = Field(..., gt=0)
    option_type: Literal["call", "put"]
    action: Literal["buy", "sell"]
    premium: float = Field(..., ge=0)  # simulated premium per unit
    quantity: int = Field(..., ge=1)  # number of lots
    lot_size: int = Field(..., ge=1)  # contracts per lot


class OrderFillIn(BaseModel):
    """An executed paper order (one strategy, one or more legs)."""

    symbol: str = Field(..., min_length=1)
    strategy_tag: str = "Custom"
    starting_capital: float | None = Field(default=None, gt=0)
    legs: list[LegOrderIn] = Field(..., min_length=1)


class LegCloseIn(BaseModel):
    exit_price: float = Field(..., ge=0)


class LegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    expiration_date: str
    strike_price: float
    option_type: str
    action: str
    premium: float
    quantity: int
    lot_size: int
    entry_at: datetime
    exit_at: datetime | None
    exit_price: float | None
    realized_pnl: float | None


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    strategy_tag: str
    status: str
    entry_net: float
    realized_pnl: float | None
    entry_at: datetime
    exit_at: datetime | None
    legs: list[LegOut]


class AccountOut(BaseModel):
    starting_capital: float
    balance: float
    net_pnl: float


class JournalStatsOut(BaseModel):
    total_trades: int
    open_trades: int
    closed_trades: int
    wins: int
    win_rate: float | None
    profit_factor: float | None
    gross_profit: float
    gross_loss: float


class JournalOut(BaseModel):
    account: AccountOut
    stats: JournalStatsOut
    trades: list[TradeOut]


class MarketStatusOut(BaseModel):
    """Current NSE market status for the paper-trading UI badge."""

    status: Literal["open", "closed", "unknown"]
    source: str
    trade_date: str | None = None
    checked_at: str
    message: str
    open: bool
