from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.chains import INSTRUMENT_KEYS, transform_chain
from app.routers.deps import get_session_id
from app.schemas import (
    AnalyticsOut,
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
from app.services import token_store, upstox
from app.services.journal import (
    LegNotFoundError,
    TradeClosedError,
    TradeNotFoundError,
    close_leg,
    get_journal,
    handlePaperOrderFill,
)
from app.services.market_status import get_market_status
from app.services.performance import get_analytics
from app.services.paper_execution import (
    PaperExecutionError,
    execute_strategy,
    exit_position,
    find_exit_replay,
    get_open_positions,
    get_order_history,
    get_portfolio,
    reconcile,
    reset_portfolio,
)
from app.services.upstox import UpstoxError

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


@router.get("/market-status", response_model=MarketStatusOut)
async def market_status(session_id: str | None = Depends(get_session_id)):
    """Current NSE market status for the paper-trading UI badge."""
    _, access_token = require_session(session_id)
    status = await get_market_status(access_token)
    return MarketStatusOut(
        status=status.status,
        source=status.source,
        trade_date=status.trade_date,
        checked_at=status.checked_at,
        message=status.message,
        open=status.status == "open",
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
    by_expiry: dict[str, list] = {}
    for leg in legs:
        by_expiry.setdefault(leg.expiration_date, []).append(leg)

    prices: dict[tuple, float] = {}
    try:
        for expiry, leg_list in by_expiry.items():
            raw = await upstox.get_option_chain(access_token, INSTRUMENT_KEYS[symbol], expiry)
            chain = transform_chain(symbol, expiry, raw)["chain"]
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
                prices[(expiry, leg.strike_price, leg.option_type)] = ltp
    except UpstoxError as exc:
        raise PaperExecutionError(
            "EXECUTION_FAILED", f"Could not load market data for {symbol}: {exc.message}"
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
