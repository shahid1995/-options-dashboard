"""Option candle persistence -- Phase 7.13.

Stores historical OHLCV candles for expired option and future contracts.
Follows the same persistence pattern as ``nifty_candles.py``.

Key properties:
  - **Idempotent**: re-running the same data does not create duplicates
    (SQLite upsert via ``record_option_candles()``).
  - **Transactional**: each batch is persisted in a single transaction.
  - **Raw data immutable**: OHLCV/OI values are stored exactly as provided.
    Derived analytics (IV, Greeks) are computed separately.

This module is completely independent of:
  - ``nifty_candles.py`` (index candle pipeline)
  - ``contract_metadata.py`` (contract specs lookup)
  - lot_size / minimum_lot / freeze_quantity
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.utils.db_dialect import dialect_insert

from app.models import OptionCandle


VALID_INTERVALS = {"1min", "3min", "5min", "15min", "30min", "1hour", "1day"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_option_candle(
    raw_candle: list | tuple,
    instrument_key: str,
    interval: str = "3min",
) -> dict | None:
    """Convert a single Upstox raw candle array into the ``record_option_candles()`` format.

    Parameters
    ----------
    raw_candle:
        A list/tuple of at least 7 elements:
        ``[timestamp, open, high, low, close, volume, open_interest]``
    instrument_key:
        The Upstox expired instrument key (e.g. ``NSE_FO|48891|31-10-2024``).
    interval:
        Candle interval (default ``"3min"``).

    Returns
    -------
    dict or None
        A dict with keys ``instrument_key``, ``interval``, ``openTime``
        (ISO 8601 UTC with ``Z`` suffix), ``open``, ``high``, ``low``,
        ``close``, ``volume``, ``open_interest``.  Returns ``None`` when
        the raw candle is structurally invalid.

    Notes
    -----
    * Unlike ``candle_ingestion.normalize_candle()``, this function
      PRESERVES open_interest (index 6) -- it is critical for option
      analytics and must never be discarded.
    * Timestamps are normalized to naive IST (Phase 7.24.4 convention).
      Both NIFTY and option candles use the same canonical representation.
    """
    if not isinstance(raw_candle, (list, tuple)) or len(raw_candle) < 7:
        return None

    ist_timestamp = raw_candle[0]
    open_price = raw_candle[1]
    high = raw_candle[2]
    low = raw_candle[3]
    close = raw_candle[4]
    volume = raw_candle[5]
    open_interest = raw_candle[6]

    # Validate numeric OHLC fields
    for _name, val in (("open", open_price), ("high", high), ("low", low), ("close", close)):
        if val is None or not isinstance(val, (int, float)):
            return None

    # Volume and OI -- coerce to float, default 0.0 for non-numeric
    if not isinstance(volume, (int, float)):
        volume = 0.0
    if not isinstance(open_interest, (int, float)):
        open_interest = 0.0

    # Normalize timestamp (IST -> naive IST, Phase 7.24.4 convention)
    from app.services.candle_ingestion import normalize_candle_timestamp
    try:
        open_time_ist = normalize_candle_timestamp(ist_timestamp)
    except (ValueError, TypeError):
        return None

    return {
        "instrument_key": instrument_key,
        "interval": interval.strip(),
        "openTime": open_time_ist.isoformat(),  # naive IST, no Z suffix
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "open_interest": float(open_interest),
    }


def normalize_option_candles(
    raw_candles: list[list] | list[tuple],
    instrument_key: str,
    interval: str = "3min",
) -> list[dict]:
    """Normalize a batch of raw Upstox option candle arrays.

    Invalid candles are silently dropped (returns a shorter list).
    """
    out: list[dict] = []
    for raw in (raw_candles or []):
        normalized = normalize_option_candle(raw, instrument_key, interval)
        if normalized is not None:
            out.append(normalized)
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def record_option_candles(db: Session, candles: list[dict]) -> int:
    """Persist option candles idempotently; return the number actually inserted/updated.

    Each candle is::

        {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00Z",  # ISO 8601 UTC
            "open": 897.05,
            "high": 897.05,
            "low": 894.2,
            "close": 896.3,
            "volume": 2075.0,
            "open_interest": 325300.0,
        }

    Duplicate (instrument_key, interval, open_time) -> upsert (update OHLCV/OI).
    Invalid/incomplete candles are skipped.

    Timestamps must be naive IST (Phase 7.24.4 convention).
    """
    stored = 0
    for c in candles or []:
        instrument_key = str(c.get("instrument_key", "")).strip()
        interval = str(c.get("interval", "3min")).strip()
        open_time = c.get("openTime") or c.get("open_time")

        if not instrument_key or not open_time:
            continue
        if interval not in VALID_INTERVALS:
            continue

        # Parse timestamp
        if isinstance(open_time, str):
            try:
                open_time = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
        elif not isinstance(open_time, datetime):
            continue

        # Convert to naive IST for SQLite storage (Phase 7.24.4 convention)
        if open_time.tzinfo is not None:
            from app.utils.market_time import to_ist_naive
            open_time = to_ist_naive(open_time)

        ohlcv = {}
        for field in ("open", "high", "low", "close"):
            v = c.get(field)
            if v is None or not isinstance(v, (int, float)):
                break
            ohlcv[field] = float(v)
        else:
            # All OHLC fields valid
            ohlcv["volume"] = float(c.get("volume", 0) or 0)
            ohlcv["open_interest"] = float(c.get("open_interest", 0) or 0)

            # Idempotent upsert
            try:
                db.execute(
                    dialect_insert(db.get_bind(), OptionCandle)
                    .values(
                        instrument_key=instrument_key,
                        interval=interval,
                        open_time=open_time,
                        open=ohlcv["open"],
                        high=ohlcv["high"],
                        low=ohlcv["low"],
                        close=ohlcv["close"],
                        volume=ohlcv["volume"],
                        open_interest=ohlcv["open_interest"],
                        source="UPSTOX_EXPIRED_CANDLE",
                        fetched_at=_utcnow(),
                    )
                    .on_conflict_do_update(
                        index_elements=["instrument_key", "interval", "open_time"],
                        set_={
                            "open": ohlcv["open"],
                            "high": ohlcv["high"],
                            "low": ohlcv["low"],
                            "close": ohlcv["close"],
                            "volume": ohlcv["volume"],
                            "open_interest": ohlcv["open_interest"],
                            "fetched_at": _utcnow(),
                        },
                    )
                )
                stored += 1
            except Exception:
                # Silently skip malformed records
                pass

    db.commit()
    return stored


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def count_option_candles(
    db: Session,
    instrument_key: str | None = None,
) -> int:
    """Count option candles, optionally filtered by instrument_key."""
    stmt = select(func.count(OptionCandle.id))
    if instrument_key:
        stmt = stmt.where(OptionCandle.instrument_key == instrument_key)
    return db.scalar(stmt) or 0


def get_option_candles(
    db: Session,
    instrument_key: str,
    interval: str = "3min",
    limit: int = 10000,
) -> list[dict]:
    """Retrieve option candles for one instrument, ordered ascending by time."""
    rows = (
        db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == instrument_key)
            .where(OptionCandle.interval == interval)
            .order_by(OptionCandle.open_time.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "instrument_key": r.instrument_key,
            "interval": r.interval,
            "openTime": r.open_time.isoformat() if r.open_time else None,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "open_interest": r.open_interest,
        }
        for r in rows
    ]


def get_distinct_instruments(db: Session) -> list[str]:
    """Return all instrument_keys that have candle data."""
    return list(
        db.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all()
    )
