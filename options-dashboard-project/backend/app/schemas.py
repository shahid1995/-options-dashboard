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


# ---- Phase 5.0: server-authoritative paper trading schemas ------------------


class ExecutionLegIn(BaseModel):
    """One leg of a strategy execution request.

    Fill prices are NOT taken from the client: the backend resolves the
    authoritative market price from the required expiry chain at execution
    time. ``quantity`` is LOTS.
    """

    symbol: str = Field(..., min_length=1)
    expiration_date: str = Field(..., min_length=1)
    strike_price: float = Field(..., gt=0)
    option_type: Literal["call", "put"]
    action: Literal["buy", "sell"]
    quantity: int = Field(..., ge=1)  # lots
    lot_size: int = Field(..., ge=1)  # contracts per lot


class ExecutionRequestIn(BaseModel):
    """Strategy execution request (idempotent via ``client_order_id``)."""

    client_order_id: str = Field(..., min_length=8, max_length=64)
    symbol: str = Field(..., min_length=1)
    strategy_tag: str = "Custom"
    strategy_id: str | None = None
    starting_capital: float | None = Field(default=None, gt=0)
    legs: list[ExecutionLegIn] = Field(..., min_length=1)


class ExitRequestIn(BaseModel):
    """Position exit request (idempotent via ``client_order_id``).

    ``quantity`` defaults to the full position. ``exit_price`` is optional;
    when omitted (or when the backend has a fresher chain quote) the
    authoritative market price is used.
    """

    client_order_id: str = Field(..., min_length=8, max_length=64)
    quantity: int | None = Field(default=None, ge=1)  # lots
    exit_price: float | None = Field(default=None, ge=0)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_order_id: str
    execution_id: str | None
    position_id: int | None
    kind: str
    symbol: str
    expiry: str
    strike: float
    option_type: str
    action: str
    quantity: int
    lot_size: int
    status: str
    filled_quantity: int
    fill_price: float | None
    price_source: str
    realized_pnl: float | None
    rejected_reason: str | None
    created_at: datetime


class ExecutionOut(BaseModel):
    """Result of a strategy execution (a group of orders)."""

    execution_id: str
    status: str
    symbol: str
    strategy_tag: str
    entry_net: float
    orders: list[OrderOut]
    filled_count: int
    failed_count: int
    errors: list[str]
    duplicated: bool = False  # true when this is an idempotent replay


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    expiry: str
    strike: float
    option_type: str
    net_quantity: int
    average_entry_price: float
    lot_size: int
    realized_pnl: float
    status: str
    strategy_execution_id: str | None
    opened_at: datetime
    closed_at: datetime | None
    # Unrealized P&L requires a market mark. The backend never fabricates it:
    # it stays null here and the UI applies the existing chain-cache mark.
    unrealized_pnl: float | None = None
    current_price: float | None = None


class PortfolioSummaryOut(BaseModel):
    starting_cash: float
    available_cash: float
    invested_value: float
    realized_pnl: float
    unrealized_pnl: float | None = None  # requires market marks (UI applies them)
    total_pnl: float
    open_position_count: int
    open_strategy_count: int


class PortfolioGroupOut(BaseModel):
    """Strategy-grouped portfolio view (one row per strategy execution)."""

    execution_id: str
    strategy_tag: str
    symbol: str
    status: str
    entry_net: float
    realized_pnl: float
    legs: list[OrderOut]
    entry_at: datetime


class ExitOut(BaseModel):
    """Result of a position exit (one exit order + the updated position)."""

    order: OrderOut
    position: PositionOut
    duplicated: bool = False  # true when this is an idempotent replay


class PortfolioOut(BaseModel):
    """Portfolio: summary numbers + strategy-grouped view."""

    summary: PortfolioSummaryOut
    groups: list[PortfolioGroupOut]


class ReconcileOut(BaseModel):
    valid: bool
    discrepancies: list[dict]


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


# ---- Phase 5.1: portfolio & journal analytics schemas -----------------------


class PortfolioSummaryAnalyticsOut(BaseModel):
    """Canonical portfolio summary. ``unrealized_pnl`` stays ``None`` until a
    market mark exists (the frontend chain cache supplies it)."""

    starting_capital: float
    available_cash: float
    invested_value: float
    realized_pnl: float
    unrealized_pnl: float | None = None
    total_pnl: float
    return_pct: float | None = None  # totalPnl / startingCapital × 100 (not ROI/margin)
    open_position_count: int
    open_strategy_count: int


class PerformanceOut(BaseModel):
    """Performance metrics over COMPLETED strategy trades. Every statistic
    that needs data returns ``None`` (never 0/Infinity) when data is missing."""

    total_completed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float | None = None
    average_winner: float | None = None
    average_loser: float | None = None
    profit_factor: float | None = None
    expectancy: float | None = None
    largest_winner: float | None = None
    largest_loser: float | None = None
    current_win_streak: int = 0
    current_loss_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    average_holding_duration: float | None = None  # seconds
    median_holding_duration: float | None = None
    shortest_holding_duration: float | None = None
    longest_holding_duration: float | None = None


class EquityPointOut(BaseModel):
    """One point of the REALIZED equity curve."""

    date: str  # YYYY-MM-DD of the realization
    pnl: float
    cumulative_pnl: float
    equity: float


class DrawdownOut(BaseModel):
    current_drawdown: float | None = None
    current_drawdown_pct: float | None = None
    max_drawdown: float | None = None
    max_drawdown_pct: float | None = None


class DailyPnlOut(BaseModel):
    """Daily realized P&L. Historical unrealized marks are never stored, so
    ``unrealized_pnl`` is always ``None`` (unavailable), never fabricated."""

    date: str
    realized_pnl: float
    unrealized_pnl: float | None = None
    total_pnl: float


class StrategyPerformanceOut(BaseModel):
    """One strategy's completed-trade performance (grouped by tag)."""

    strategy: str
    trades: int
    wins: int
    losses: int
    win_rate: float | None = None
    total_pnl: float
    average_pnl: float
    profit_factor: float | None = None
    expectancy: float | None = None


class PositionAnalyticsItemOut(BaseModel):
    """One OPEN position. Current-price fields stay ``None`` until the
    frontend overlays a market mark (backend has no live marks)."""

    symbol: str
    expiry: str
    strike: float
    option_type: str
    net_quantity: int
    average_entry: float
    current_price: float | None = None
    unrealized_pnl: float | None = None
    market_value: float | None = None
    strategy_execution_id: str | None = None


class PositionAnalyticsOut(BaseModel):
    """Open-position exposure. Entry-value exposure, NOT margin required."""

    long_exposure: float
    short_exposure: float
    total_exposure: float
    items: list[PositionAnalyticsItemOut]


class JournalRowOut(BaseModel):
    """ONE completed strategy trade for the grouped journal view (multi-leg
    strategies appear as a single row; individual legs ride underneath)."""

    execution_id: str
    strategy: str
    symbol: str
    entry_at: datetime
    exit_at: datetime
    duration_seconds: float | None = None
    duration_label: str | None = None
    realized_pnl: float
    result: str  # WIN | LOSS | BREAKEVEN
    legs: list[dict]


class AnalyticsWarningOut(BaseModel):
    code: str
    discrepancies: list[dict] = []


class DataQualityOut(BaseModel):
    """Every analytics block reports availability: available | partial |
    unavailable. Values are never fabricated to complete a chart."""

    historical_unrealized: str = "unavailable"
    current_marks: str = "unavailable"
    completed_trades: str = "available"  # available | none
    warnings: list[AnalyticsWarningOut] = []


class AnalyticsOut(BaseModel):
    """GET /paper/analytics — ONE authoritative analytics response."""

    summary: PortfolioSummaryAnalyticsOut
    performance: PerformanceOut
    equity_curve: list[EquityPointOut]
    drawdown: DrawdownOut
    daily_pnl: list[DailyPnlOut]
    strategies: list[StrategyPerformanceOut]
    positions: PositionAnalyticsOut
    journal: list[JournalRowOut]
    data_quality: DataQualityOut
    filters: dict
