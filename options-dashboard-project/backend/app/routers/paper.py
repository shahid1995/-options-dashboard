from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.routers.deps import get_session_id
from app.schemas import (
    AnalyticsOut,
    BrokerProfileOut,
    BulkExitOut,
    BulkExitRequestIn,
    CapitalOut,
    ExecutionOut,
    ExecutionRequestIn,
    ExitOut,
    ExitRequestIn,
    LegCloseIn,
    MarketStatusOut,
    OrderFillIn,
    PortfolioOut,
    PositionOut,
    ReconcileOut,
    TradeOut,
)
from app.services import token_store
from app.services.journal import (
    LegNotFoundError,
    TradeClosedError,
    TradeNotFoundError,
    close_leg,
    get_journal,
    handlePaperOrderFill,
)
from app.services.capital import get_capital_summary
from app.services.market_status import get_market_status
from app.services.performance import get_analytics
from app.services.paper_execution import (
    PaperExecutionError,
    bulk_exit,
    execute_strategy,
    exit_position,
    find_exit_replay,
    get_open_positions,
    get_order_history,
    get_portfolio,
    reconcile,
    reset_portfolio,
    round_option_price,
)
router = APIRouter()

MARKET_CLOSED_MSG = "Market is closed. Paper order was not executed."
MARKET_UNKNOWN_MSG = "Unable to verify market status. Order was not executed."


def require_session(session_id: str | None) -> tuple[str, str]:
    """Validates the Upstox session and returns (journal user key, access token)."""
    token = token_store.get_token(session_id) if session_id else None
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return session_id, token


async def require_market_open(access_token: str) -> None:
    """Centralized market-hours execution gate.

    Every paper order — manual BUY/SELL, strategy-generated, or automated —
    must pass through here before anything is executed, and the check runs at
    the exact moment of execution. A closed or unverifiable market rejects the
    order; an unknown status is never treated as open.
    """
    status = await get_market_status(access_token)
    if status.status == "open":
        return
    detail = MARKET_UNKNOWN_MSG if status.status == "unknown" else MARKET_CLOSED_MSG
    raise HTTPException(status_code=409, detail=detail)


@router.get("/broker/profile", response_model=BrokerProfileOut)
async def broker_profile(
    session_id: str | None = Depends(get_session_id),
    refresh: bool = False,
):
    """GET /paper/broker/profile — broker connection diagnostics (Phase 6.4.1).

    Read-only: verifies the authenticated customer's Upstox connection via
    the broker's profile endpoint (server-side, reusing the existing session
    and Upstox HTTP client) and returns the NORMALIZED safe profile. No
    mutation; user-scoped; never returns credentials or raw broker payloads.
    ``refresh=true`` bypasses the short user-scoped TTL cache (manual
    refresh). Profile is NOT tick data — the page never polls it.

    Always available regardless of market status: connection diagnostics
    must work even while the market is closed.
    """
    from app.services.broker_profile import get_broker_profile_summary

    user_id, access_token = require_session(session_id)
    return await get_broker_profile_summary(user_id, access_token, refresh=refresh)


@router.get("/market-status", response_model=MarketStatusOut)
async def market_status(
    session_id: str | None = Depends(get_session_id),
    segment: str = "INDEX_DERIVATIVES",
):
    """Current market status for the paper-trading UI badge (segment-aware).

    Phase 5.2.1: the status is resolved for ONE segment (default
    INDEX_DERIVATIVES — the product's NIFTY index-options segment), so a
    cash-segment closing auction can never be mistaken for index-options
    trading. The badge is informational; the execution gate re-resolves the
    same segment at the exact moment of execution.
    """
    _, access_token = require_session(session_id)
    status = await get_market_status(access_token, segment=segment)
    return MarketStatusOut(
        status=status.status,
        source=status.source,
        trade_date=status.trade_date,
        checked_at=status.checked_at,
        message=status.message,
        open=status.status == "open",
        segment=status.segment,
        session_state=status.session_state,
        timezone=status.timezone,
        trading_allowed=status.trading_allowed,
    )


@router.post("/fills", status_code=201, response_model=TradeOut)
async def submit_fill(
    order: OrderFillIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """LEGACY journal path: auto-logs an executed paper order into trades+legs.

    Phase 5.0 supersedes this with ``POST /paper/executions`` (the
    server-authoritative execution layer). This endpoint is retained for
    backward compatibility with existing clients and tests; it writes only
    the journal tables, never the authoritative orders/positions/ledger.
    """
    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    trade = handlePaperOrderFill(user_id, order, db)
    return trade


@router.post("/trades/{trade_id}/legs/{leg_id}/close", response_model=TradeOut)
async def submit_leg_close(
    trade_id: int,
    leg_id: int,
    body: LegCloseIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """LEGACY journal path: records a leg's exit; closes the trade once every
    leg has exited. Phase 5.0 positions exit via ``POST /paper/positions/{id}/exit``.
    """
    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    try:
        trade = close_leg(user_id, trade_id, leg_id, body.exit_price, db)
    except TradeNotFoundError:
        raise HTTPException(status_code=404, detail="Trade not found")
    except LegNotFoundError:
        raise HTTPException(status_code=404, detail="Leg not found")
    except TradeClosedError:
        raise HTTPException(status_code=400, detail="Trade already closed")
    return trade


# ---- Phase 5.0: server-authoritative paper trading -------------------------


async def resolve_market_prices(access_token: str, symbol: str, legs) -> dict:
    """Resolve the authoritative fill price for every leg from market data.

    Fetches each required expiry's chain ONCE and maps each leg to the LTP of
    its own strike/side (Phase 2.1 rule: every expiry uses its own chain; a
    missing chain, strike or quote blocks execution — no fallback pricing
    from another expiry, no stale client values).

    Returns ``{(expiry, strike, option_type): ltp}``.
    """
    symbol = symbol.upper()
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
    by_expiry: dict[str, list] = {}
    for leg in legs:
        by_expiry.setdefault(leg.expiration_date, []).append(leg)

    prices: dict[tuple, float] = {}
    try:
        for expiry, leg_list in by_expiry.items():
            chain = (await adapter.get_option_chain(symbol, expiry))["chain"]
            by_strike = {row["strike"]: row for row in chain}
            for leg in leg_list:
                row = by_strike.get(leg.strike_price)
                side = row.get(leg.option_type) if row else None
                ltp = side.get("ltp") if side else None
                if ltp is None or ltp <= 0:
                    raise PaperExecutionError(
                        "CHAIN_DATA_MISSING",
                        f"Market data unavailable for {symbol} {leg.strike_price:g} "
                        f"{leg.option_type.upper()} ({expiry}). Paper order was not executed.",
                    )
                # Phase 5.2.1: the authoritative FILL price is normalized to
                # the option's tick size (NIFTY index options: ₹0.05). The raw
                # broker LTP is kept for analytics; only the tradable price
                # crosses the fill boundary tick-aligned.
                prices[(expiry, leg.strike_price, leg.option_type)] = round_option_price(ltp)
    except BrokerError as exc:
        raise PaperExecutionError(
            "EXECUTION_FAILED", f"Could not load market data for {symbol}: {exc.message}"
        ) from exc
    return prices


async def resolve_bulk_market_prices(access_token: str, positions) -> dict:
    """Resolve the authoritative fill price for every open position (bulk).

    Fetches each required (symbol, expiry) chain ONCE and maps every position
    to the LTP of its OWN strike/side (Phase 2.1 rule: every expiry uses its
    own chain; no fallback from another expiry, no stale client values). A
    missing chain, strike or quote raises ``BULK_EXIT_CHAIN_DATA_MISSING``
    BEFORE any mutation — the whole bulk request is rejected, never a
    partial closure.

    Returns ``{(symbol, expiry, strike, option_type): ltp}``.
    """
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
    by_chain: dict[tuple[str, str], list] = {}
    for p in positions:
        by_chain.setdefault((p.symbol.upper(), p.expiry), []).append(p)

    prices: dict[tuple, float] = {}
    try:
        for (symbol, expiry), leg_list in by_chain.items():
            chain = (await adapter.get_option_chain(symbol, expiry))["chain"]
            by_strike = {row["strike"]: row for row in chain}
            for p in leg_list:
                row = by_strike.get(p.strike)
                side = row.get(p.option_type) if row else None
                ltp = side.get("ltp") if side else None
                if ltp is None or ltp <= 0:
                    raise PaperExecutionError(
                        "BULK_EXIT_CHAIN_DATA_MISSING",
                        f"Market data unavailable for {symbol} {p.strike:g} "
                        f"{p.option_type.upper()} ({expiry}). No position was closed.",
                    )
                # Phase 5.2.1: authoritative bulk-exit fill prices are
                # normalized to the option tick size (NIFTY: ₹0.05), matching
                # the single-position exit boundary exactly.
                prices[(symbol, p.expiry, p.strike, p.option_type)] = round_option_price(ltp)
    except BrokerError as exc:
        raise PaperExecutionError(
            "EXECUTION_FAILED", f"Could not load market data: {exc.message}"
        ) from exc
    return prices


def _paper_error(exc: PaperExecutionError) -> HTTPException:
    """Map a structured execution error to an HTTP response.

    The detail string carries the error CODE plus a human-readable message
    (e.g. ``CHAIN_DATA_MISSING: ...``) so the UI can show a useful message
    without exposing internal stack traces.
    """
    status = {
        "CHAIN_DATA_MISSING": 409,
        "BULK_EXIT_CHAIN_DATA_MISSING": 409,
        "INVALID_QUANTITY": 400,
        "POSITION_NOT_FOUND": 404,
        "INSUFFICIENT_POSITION": 400,
        "INVALID_STATE_TRANSITION": 400,
        "EXECUTION_FAILED": 502,
    }.get(exc.code, 409)
    return HTTPException(status_code=status, detail=f"{exc.code}: {exc.message}")


@router.post("/executions", response_model=ExecutionOut)
async def submit_execution(
    request: ExecutionRequestIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Execute a strategy as a group of paper orders (idempotent).

    Guards, in order: session, market OPEN re-checked at execution time,
    required chain data for every leg, then an atomic write of execution +
    orders + positions + ledger + journal record. Replays of the same
    ``client_order_id`` return the original execution without new writes.
    """
    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    try:
        prices = await resolve_market_prices(access_token, request.symbol, request.legs)
        return execute_strategy(user_id, request, db, prices)
    except PaperExecutionError as exc:
        raise _paper_error(exc) from exc


@router.post("/positions/{position_id}/exit", response_model=ExitOut)
async def submit_position_exit(
    position_id: int,
    request: ExitRequestIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Exit a paper position (full or partial) at the authoritative market price.

    Order of guards: session, market OPEN re-checked at execution time,
    idempotent replay (a retried ``client_order_id`` returns the ORIGINAL
    result even after the position closed, without needing market data),
    open-position check, required chain data, current market price, then an
    atomic position/order/ledger/journal update.
    """
    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    try:
        from app.models import Position as PositionModel

        position = db.get(PositionModel, position_id)
        if position is None or position.user_id != user_id:
            raise PaperExecutionError("POSITION_NOT_FOUND", "Position not found.")
        replay = find_exit_replay(user_id, position, request.client_order_id, db)
        if replay is not None:
            return replay
        if position.status != "open" or position.net_quantity == 0:
            raise PaperExecutionError(
                "INSUFFICIENT_POSITION", "Position is closed — no quantity available to exit."
            )
        pseudo_leg = type(
            "ExitLeg",
            (),
            {
                "expiration_date": position.expiry,
                "strike_price": position.strike,
                "option_type": position.option_type,
            },
        )
        prices = await resolve_market_prices(access_token, position.symbol, [pseudo_leg])
        fill_price = prices[(position.expiry, position.strike, position.option_type)]
        return exit_position(user_id, position_id, request, db, fill_price)
    except PaperExecutionError as exc:
        raise _paper_error(exc) from exc


@router.post("/executions/{strategy_execution_id}/exit-all", response_model=BulkExitOut)
async def submit_execution_exit_all(
    strategy_execution_id: str,
    request: BulkExitRequestIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """EXIT STRATEGY — close every open position of ONE strategy execution.

    Guards, in order: session, market OPEN re-checked at execution time,
    the strategy execution exists + belongs to the user, then all required
    chain data is resolved BEFORE any mutation. Every position exits through
    the same trusted position-exit path in ONE transaction; the whole
    operation is idempotent via ``client_order_id``.
    """
    from app.models import Position as PositionModel
    from app.models import StrategyExecution as StrategyExecutionModel

    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    execution = db.scalar(
        select(StrategyExecutionModel).where(
            StrategyExecutionModel.user_id == user_id,
            StrategyExecutionModel.execution_id == strategy_execution_id,
        )
    )
    if execution is None:
        raise HTTPException(status_code=404, detail="Strategy execution not found.")
    positions = db.scalars(
        select(PositionModel)
        .where(
            PositionModel.user_id == user_id,
            PositionModel.strategy_execution_id == strategy_execution_id,
            PositionModel.status == "open",
        )
        .order_by(PositionModel.id.asc())
    ).all()
    try:
        prices = await resolve_bulk_market_prices(access_token, positions)
        return bulk_exit(user_id, "STRATEGY", strategy_execution_id, request, db, prices)
    except PaperExecutionError as exc:
        raise _paper_error(exc) from exc


@router.post("/positions/exit-all", response_model=BulkExitOut)
async def submit_exit_all(
    request: BulkExitRequestIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """EXIT ALL — close every open paper position of the authenticated user.

    The backend owns the bulk operation (the frontend never loops over
    positions): session, market OPEN re-checked at execution time, then all
    required chain data is resolved BEFORE any mutation, then every position
    exits through the same trusted position-exit path in ONE transaction.
    The whole operation is idempotent via ``client_order_id``.
    """
    from app.models import Position as PositionModel

    user_id, access_token = require_session(session_id)
    await require_market_open(access_token)
    positions = db.scalars(
        select(PositionModel)
        .where(PositionModel.user_id == user_id, PositionModel.status == "open")
        .order_by(PositionModel.id.asc())
    ).all()
    try:
        prices = await resolve_bulk_market_prices(access_token, positions)
        return bulk_exit(user_id, "ACCOUNT", None, request, db, prices)
    except PaperExecutionError as exc:
        raise _paper_error(exc) from exc


@router.get("/positions", response_model=list[PositionOut])
def positions(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """The user's OPEN paper positions (server-authoritative)."""
    user_id, _access_token = require_session(session_id)
    return get_open_positions(user_id, db)


@router.get("/orders")
def orders(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """The user's paper order history (fills, exits, status, timestamps)."""
    user_id, _access_token = require_session(session_id)
    return get_order_history(user_id, db)


@router.get("/portfolio", response_model=PortfolioOut)
def portfolio(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Portfolio summary + strategy-grouped view (server-authoritative)."""
    user_id, _access_token = require_session(session_id)
    return get_portfolio(user_id, db)


@router.post("/portfolio/reset", response_model=PortfolioOut)
def portfolio_reset(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Clear the user's paper portfolio (executions, orders, positions, ledger)."""
    user_id, _access_token = require_session(session_id)
    return reset_portfolio(user_id, db)


@router.get("/reconcile", response_model=ReconcileOut)
def portfolio_reconcile(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Verify orders, positions, cash and executions agree; report discrepancies."""
    user_id, _access_token = require_session(session_id)
    return reconcile(user_id, db)


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    strategy: str | None = None,
):
    """ONE authoritative analytics response: summary + performance + equity
    curve + drawdown + strategy performance + positions + journal.

    Read-only (never mutates trading state) and always available regardless
    of market status. ``date_from`` / ``date_to`` (YYYY-MM-DD) and
    ``strategy`` filter the completed-trade set used for performance, equity
    curve, drawdown, strategy groups and journal; the canonical summary
    always reflects the full portfolio.
    """
    user_id, _access_token = require_session(session_id)
    return get_analytics(
        user_id, db, date_from=date_from, date_to=date_to, strategy=strategy
    )


@router.get("/journal")
def journal(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Account, performance stats, and the full trade log for the journal UI.

    Read-only: always available, regardless of market status, so users can
    review positions, P&L and history after the market closes.
    """
    user_id, _access_token = require_session(session_id)
    return get_journal(user_id, db)


@router.get("/capital", response_model=CapitalOut)
async def capital(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /paper/capital — server-authoritative capital summary (Phase 6.0/6.1).

    Read-only and always available regardless of market status. Every figure
    carries its source (BROKER_REPORTED | ESTIMATED | CALCULATED) and
    availability status; missing values are null, never 0. Phase 6.1: with an
    authenticated Upstox session the broker's read-only funds + whole-strategy
    margin APIs back the broker figures; on any broker failure (including the
    daily funds maintenance window) they stay UNAVAILABLE with a structured
    code — never estimated, never paper cash, never 0. Paper capital is
    exposed as paper values, never renamed as broker funds. No Return-on-
    Capital metric is computed; only its future inputs are returned.
    """
    user_id, access_token = require_session(session_id)
    return await get_capital_summary(user_id, db, access_token=access_token)
