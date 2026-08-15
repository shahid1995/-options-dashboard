from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_session_id
from app.schemas import LegCloseIn, OrderFillIn, TradeOut
from app.services import token_store
from app.services.journal import (
    LegNotFoundError,
    TradeClosedError,
    TradeNotFoundError,
    close_leg,
    get_journal,
    handlePaperOrderFill,
)

router = APIRouter()


def require_session(session_id: str | None) -> str:
    """Validates the Upstox session and returns it as the journal user key."""
    if not session_id or not token_store.get_token(session_id):
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return session_id


@router.post("/fills", status_code=201, response_model=TradeOut)
def submit_fill(
    order: OrderFillIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Auto-logs an executed paper order into the trades + legs tables."""
    user_id = require_session(session_id)
    trade = handlePaperOrderFill(user_id, order, db)
    return trade


@router.post("/trades/{trade_id}/legs/{leg_id}/close", response_model=TradeOut)
def submit_leg_close(
    trade_id: int,
    leg_id: int,
    body: LegCloseIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """Records a leg's exit; closes the trade once every leg has exited."""
    user_id = require_session(session_id)
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
    """Account, performance stats, and the full trade log for the journal UI."""
    user_id = require_session(session_id)
    return get_journal(user_id, db)
