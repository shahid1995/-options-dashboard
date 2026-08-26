"""Candle data API (Phase 7.8).

Endpoints:
  GET /candles              — query stored candles (oldest-first)
  GET /candles/count        — count stored candles
  GET /candles/coverage     — coverage report

All endpoints require session authentication (X-Session-Id header or
session_id cookie).  Candle data is market-data only — no broker
credentials, no trading logic, no BUY/SELL signals.

Lot-size rule:
  Candle data is pure OHLCV.  No lot_size, minimum_lot, freeze_quantity,
  or tick_size fields.  Historical contract metadata remains a separate
  pipeline (contract_metadata.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_session_id
from app.services import token_store
from app.services.candle_coverage import generate_coverage_report
from app.services.nifty_candles import (
    count_candles,
    get_candles,
    get_candle_at_or_before,
)

router = APIRouter()

# Valid intervals matching nifty_candles.VALID_INTERVALS
VALID_INTERVALS = {"1min", "3min", "5min", "15min", "30min", "1hour", "1day"}

# Maximum query range in days
MAX_QUERY_RANGE_DAYS = 365


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_session(session_id: str | None) -> str:
    """Validate the session and return the session_id."""
    token = token_store.get_token(session_id) if session_id else None
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return session_id


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CandleOut(BaseModel):
    """Single candle returned to the frontend."""
    id: int
    symbol: str
    interval: str
    openTime: str | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleListOut(BaseModel):
    """List of candles returned to the frontend."""
    candles: list[CandleOut]
    count: int
    symbol: str
    interval: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=CandleListOut)
def list_candles(
    symbol: str = Query("NIFTY", description="Underlying symbol"),
    interval: str = Query("3min", description="Candle interval"),
    limit: int = Query(500, ge=1, le=10000, description="Max candles"),
    since: str | None = Query(None, description="Start time (ISO-8601)"),
    until: str | None = Query(None, description="End time (ISO-8601)"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles — Query stored candles (oldest-first)."""
    _require_session(session_id)

    # Validate interval
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'. Valid: {sorted(VALID_INTERVALS)}")

    # Parse optional timestamps
    since_dt = _parse_timestamp(since, "since")
    until_dt = _parse_timestamp(until, "until")

    candles = get_candles(
        db,
        symbol=symbol.upper(),
        interval=interval,
        limit=limit,
        since=since_dt,
        until=until_dt,
    )

    return CandleListOut(
        candles=[CandleOut(**c) for c in candles],
        count=len(candles),
        symbol=symbol.upper(),
        interval=interval,
    )


@router.get("/count")
def candle_count(
    symbol: str = Query("NIFTY", description="Underlying symbol"),
    interval: str = Query("3min", description="Candle interval"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles/count — Count stored candles."""
    _require_session(session_id)

    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'. Valid: {sorted(VALID_INTERVALS)}")

    return {"count": count_candles(db, symbol=symbol.upper(), interval=interval)}


@router.get("/coverage")
def candle_coverage(
    symbol: str = Query("NIFTY", description="Underlying symbol"),
    interval: str = Query("3min", description="Candle interval"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles/coverage — Data coverage report."""
    _require_session(session_id)

    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'. Valid: {sorted(VALID_INTERVALS)}")

    return generate_coverage_report(db, symbol=symbol.upper(), interval=interval)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(value: str | None, name: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string, raising 400 on invalid input."""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Strip timezone for SQLite comparison (SQLite stores naive UTC)
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid '{name}' timestamp")
