"""Phase 7.0 — Trade Annotations Router.

Provides PUT /paper/analytics/trades/{execution_id}/annotations for updating
trade tags and notes. This is a separate router to avoid modifying the
protected paper.py file.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import StrategyExecution
from app.routers.deps import get_session_id
from app.schemas import TradeAnnotationsIn, TradeAnnotationsOut, TradeDetailOut, StrategyDetailOut
from app.services.performance import _parse_tags, serialize_tags, get_trade_detail, get_strategy_detail
from app.services.token_store import get_token

router = APIRouter(prefix="/paper", tags=["annotations"])


def require_session(session_id: str | None) -> tuple[str, str]:
    """Validate the session and return (user_id, access_token)."""
    token = get_token(session_id) if session_id else None
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return session_id, token


@router.put(
    "/analytics/trades/{execution_id}/annotations",
    response_model=TradeAnnotationsOut,
)
def update_trade_annotations(
    execution_id: str,
    body: TradeAnnotationsIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """PUT /paper/analytics/trades/:id/annotations — update trade tags and notes.

    Partial update: only provided fields are changed. Tags are validated as
    a list of non-empty strings (max 10 tags, max 50 chars each). Notes are
    validated as a string (max 2000 chars). The execution must belong to the
    authenticated user.
    """
    user_id, _access_token = require_session(session_id)
    exec_record = db.scalar(
        select(StrategyExecution).where(
            StrategyExecution.execution_id == execution_id,
            StrategyExecution.user_id == user_id,
        )
    )
    if exec_record is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if body.tags is not None:
        cleaned = [str(t).strip() for t in body.tags if t and str(t).strip()]
        if len(cleaned) > 10:
            raise HTTPException(status_code=422, detail="Maximum 10 tags allowed")
        if any(len(t) > 50 for t in cleaned):
            raise HTTPException(status_code=422, detail="Each tag must be 50 characters or fewer")
        exec_record.tags = serialize_tags(cleaned)

    if body.notes is not None:
        notes = body.notes.strip() if body.notes else None
        if notes and len(notes) > 2000:
            raise HTTPException(status_code=422, detail="Notes must be 2000 characters or fewer")
        exec_record.notes = notes or None

    db.commit()
    db.refresh(exec_record)

    return TradeAnnotationsOut(
        execution_id=exec_record.execution_id,
        tags=_parse_tags(exec_record.tags),
        notes=exec_record.notes,
    )


@router.get(
    "/analytics/trades/{execution_id}",
    response_model=TradeDetailOut,
)
def trade_detail(
    execution_id: str,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /paper/analytics/trades/:id — complete trade detail drill-down."""
    user_id, _access_token = require_session(session_id)
    detail = get_trade_detail(user_id, execution_id, db)
    if detail is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return detail


@router.get(
    "/analytics/strategies/{strategy_name}",
    response_model=StrategyDetailOut,
)
def strategy_detail(
    strategy_name: str,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /paper/analytics/strategies/:name — strategy detail with aggregate metrics."""
    user_id, _access_token = require_session(session_id)
    detail = get_strategy_detail(user_id, strategy_name, db)
    if detail is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return detail
