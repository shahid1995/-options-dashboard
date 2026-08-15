from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_session_id
from app.schemas import LegCloseIn, MarketStatusOut, OrderFillIn, TradeOut
from app.services import token_store
from app.services.journal import (
    LegNotFoundError,
    TradeClosedError,
    TradeNotFoundError,
    close_leg,
    get_journal,
    handlePaperOrderFill,
)
from app.services.market_status import get_market_status

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
    """Auto-logs an executed paper order into the trades + legs tables.

    Guarded by the market-hours gate: an order is never recorded as executed
    unless the market is verified open at the moment of submission.
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
    """Records a leg's exit; closes the trade once every leg has exited.

    Exits are sell orders and go through the same market-hours gate.
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
