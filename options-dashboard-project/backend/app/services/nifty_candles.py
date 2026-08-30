"""Historical NIFTY candle persistence (Phase 7.7 research foundation).

Stores intraday OHLCV candles for constructing research observations,
forward outcomes, and baseline price features.  Follows the same
persistence pattern as ``gex_history.py`` and ``iv_history.py``.

Candles are user-scoped implicitly (the user's Upstox token is required
to fetch them).  The table itself stores only market data — no credentials,
no broker tokens, no trading logic.

Phase 7.24.4: All timestamps are stored as naive IST (Asia/Kolkata).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session
from app.utils.db_dialect import dialect_insert

from app.models import NiftyCandle
from app.utils.market_time import to_ist_naive


VALID_INTERVALS = {"1min", "3min", "5min", "15min", "30min", "1hour", "1day"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_candles(db: Session, candles: list[dict]) -> int:
    """Persist candles idempotently; return the number actually inserted/updated.

    Each candle is::

        {
            "symbol": "NIFTY",
            "interval": "3min",
            "openTime": "2026-08-22T09:15:00Z",  # ISO 8601
            "open": 25500.0,
            "high": 25520.0,
            "low": 25480.0,
            "close": 25510.0,
            "volume": 15000.0,
        }

    Duplicate (symbol, interval, openTime) → upsert (update OHLCV).
    Invalid/incomplete candles are skipped.
    """
    stored = 0
    for c in candles or []:
        symbol = str(c.get("symbol", "")).upper().strip()
        interval = str(c.get("interval", "3min")).strip()
        open_time = c.get("openTime") or c.get("open_time")

        if not symbol or not open_time:
            continue
        if interval not in VALID_INTERVALS:
            continue

        # Parse timestamp → naive IST (Phase 7.24.4 convention)
        if isinstance(open_time, str):
            parsed = to_ist_naive(open_time)
            if parsed is None:
                continue
            open_time = parsed
        elif isinstance(open_time, datetime):
            # Convert aware to naive IST; keep naive as-is (assumed IST)
            if open_time.tzinfo is not None:
                from app.utils.market_time import IST
                open_time = open_time.astimezone(IST).replace(tzinfo=None)
        else:
            continue

        ohlcv = {}
        for field in ("open", "high", "low", "close"):
            v = c.get(field)
            if v is None or not isinstance(v, (int, float)):
                break
            ohlcv[field] = float(v)
        else:
            # All OHLCV fields valid
            ohlcv["volume"] = float(c.get("volume", 0) or 0)

            # Idempotent upsert
            try:
                db.execute(
                    dialect_insert(db.get_bind(), NiftyCandle)
                    .values(
                        symbol=symbol,
                        interval=interval,
                        open_time=open_time,
                        open=ohlcv["open"],
                        high=ohlcv["high"],
                        low=ohlcv["low"],
                        close=ohlcv["close"],
                        volume=ohlcv["volume"],
                    )
                    .on_conflict_do_update(
                        index_elements=["symbol", "interval", "open_time"],
                        set_={
                            "open": ohlcv["open"],
                            "high": ohlcv["high"],
                            "low": ohlcv["low"],
                            "close": ohlcv["close"],
                            "volume": ohlcv["volume"],
                        },
                    )
                )
                stored += 1
            except Exception:
                # Fallback for non-SQLite: try insert, ignore duplicates
                try:
                    existing = db.execute(
                        select(NiftyCandle).where(
                            NiftyCandle.symbol == symbol,
                            NiftyCandle.interval == interval,
                            NiftyCandle.open_time == open_time,
                        )
                    ).first()
                    if existing is None:
                        db.add(
                            NiftyCandle(
                                symbol=symbol,
                                interval=interval,
                                open_time=open_time,
                                **ohlcv,
                            )
                        )
                        stored += 1
                except Exception:
                    pass

    if stored > 0:
        db.commit()
    return stored


def get_candles(
    db: Session,
    symbol: str,
    interval: str = "3min",
    limit: int = 500,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    """Query stored candles, oldest-first.

    Used by the frontend research module to build observations and
    forward outcomes.
    """
    stmt = (
        select(NiftyCandle)
        .where(NiftyCandle.symbol == symbol.upper())
        .where(NiftyCandle.interval == interval)
    )
    if since:
        stmt = stmt.where(NiftyCandle.open_time >= since)
    if until:
        stmt = stmt.where(NiftyCandle.open_time <= until)
    stmt = stmt.order_by(NiftyCandle.open_time.asc()).limit(max(1, limit))
    return [_row_to_dict(row) for row in db.scalars(stmt)]


def get_candle_at_or_before(
    db: Session,
    symbol: str,
    timestamp: datetime,
    interval: str = "3min",
) -> dict | None:
    """Get the candle that was open at or just before the given timestamp.

    This is the reference candle for forward-outcome computation.
    """
    stmt = (
        select(NiftyCandle)
        .where(NiftyCandle.symbol == symbol.upper())
        .where(NiftyCandle.interval == interval)
        .where(NiftyCandle.open_time <= timestamp)
        .order_by(NiftyCandle.open_time.desc())
        .limit(1)
    )
    row = db.scalars(stmt).first()
    return _row_to_dict(row) if row else None


def count_candles(db: Session, symbol: str | None = None, interval: str | None = None) -> int:
    """Count stored candles."""
    stmt = select(func.count(NiftyCandle.id))
    if symbol:
        stmt = stmt.where(NiftyCandle.symbol == symbol.upper())
    if interval:
        stmt = stmt.where(NiftyCandle.interval == interval)
    return db.scalar(stmt) or 0


def prune_candles(db: Session, retention_days: int = 365) -> int:
    """Delete candles older than retention_days; return rows deleted."""
    cutoff = _utcnow() - timedelta(days=max(1, retention_days))
    result = db.execute(delete(NiftyCandle).where(NiftyCandle.open_time < cutoff))
    db.commit()
    return result.rowcount or 0


def _row_to_dict(row: NiftyCandle) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "interval": row.interval,
        "openTime": row.open_time.isoformat() if row.open_time else None,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
    }
