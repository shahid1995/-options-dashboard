"""Candle backfill CLI — Phase 7.8D.

Populates the ``nifty_candles`` table with historical 3-minute NIFTY
candles from the Upstox V3 Historical Candle API.

Key properties:
  - **Idempotent**: re-running the same date range does not create
    duplicates (SQLite upsert via ``record_candles()``).
  - **Resumable**: if the process is interrupted, re-running it skips
    already-persisted chunks by checking the DB for existing data.
  - **28-day chunks**: Upstox limits 3-min candle retrieval to 1 month;
    28-day chunks are conservative and uniform.
  - **Never requests future dates**: ``to_date`` is clamped to today.
  - **Lot-size-independent**: this module never reads or writes lot_size,
    minimum_lot, freeze_quantity, or tick_size.  Candle data is pure
    OHLCV.  Historical lot_size remains exclusively in
    ``contract_metadata.py``.

Usage::

    # Backfill last 6 months
    python -m app.tools.candle_backfill --months 6

    # Backfill specific date range
    python -m app.tools.candle_backfill --from 2025-08-01 --to 2026-02-01

    # Check current progress
    python -m app.tools.candle_backfill --status

    # Dry-run (show chunks without fetching)
    python -m app.tools.candle_backfill --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, _DEFAULT_DB_PATH
from app.models import NiftyCandle
from app.services.candle_config import (
    CANDLE_INTERVAL,
    CANDLE_UNIT,
    MAX_CHUNK_DAYS,
    NIFTY_INSTRUMENT_KEY,
)
from app.services.candle_ingestion import (
    extract_candles_from_response,
    normalize_candles,
)
from app.services.candle_retry import fetch_with_retry
from app.services.candle_validation import validate_candle_batch, validate_candle
from app.services.nifty_candles import record_candles
from app.services.upstox import get_historical_candles, UpstoxError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunk generation (§7.1)
# ---------------------------------------------------------------------------


def generate_monthly_chunks(
    start_date: date,
    end_date: date,
    max_chunk_days: int = MAX_CHUNK_DAYS,
) -> list[tuple[date, date]]:
    """Generate (from_date, to_date) pairs covering *start_date* to *end_date*.

    Each chunk is at most *max_chunk_days* apart.
    Chunks are contiguous — no gaps between them.

    Examples
    --------
    >>> generate_monthly_chunks(date(2026, 1, 1), date(2026, 1, 28))
    [(date(2026, 1, 1), date(2026, 1, 28))]
    >>> generate_monthly_chunks(date(2026, 1, 1), date(2026, 2, 15))
    [(date(2026, 1, 1), date(2026, 1, 28)), (date(2026, 1, 29), date(2026, 2, 15))]
    """
    if start_date > end_date:
        return []

    chunks: list[tuple[date, date]] = []
    current = start_date

    while current <= end_date:
        chunk_end = min(current + timedelta(days=max_chunk_days - 1), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)

    return chunks


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _today() -> date:
    """Return today's date (UTC).  Overridable in tests."""
    return datetime.now(timezone.utc).date()


def _clamp_end_date(end_date: date) -> date:
    """Never request future dates (§7.8D requirement)."""
    return min(end_date, _today())


def _date_to_str(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _make_db_session():
    """Create a DB session for the backfill CLI.

    Uses the centralized path resolution from ``app.db`` so the same
    database file is used regardless of process working directory.
    """
    url = settings.DATABASE_URL or f"sqlite:///{_DEFAULT_DB_PATH}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


def _has_candles_for_date_range(
    db, symbol: str, start: date, end: date,
) -> bool:
    """Check if any candles already exist for the given date range.

    Used for resume: if a chunk's date range overlaps with existing data,
    we can skip the API call for that chunk.
    """
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
    count = db.scalar(
        select(func.count(NiftyCandle.id)).where(
            NiftyCandle.symbol == symbol.upper(),
            NiftyCandle.open_time >= start_dt,
            NiftyCandle.open_time < end_dt,
        )
    ) or 0
    return count > 0


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


async def _fetch_and_persist_chunk(
    db,
    token: str,
    instrument_key: str,
    chunk_start: date,
    chunk_end: date,
    symbol: str = "NIFTY",
    interval: str = CANDLE_INTERVAL,
) -> dict:
    """Fetch one chunk, normalize, validate, persist.

    Returns a summary dict:
    ``{"fetched": int, "valid": int, "persisted": int, "errors": list}``
    """
    to_str = _date_to_str(chunk_end)
    from_str = _date_to_str(chunk_start)

    # Fetch from Upstox with retry
    interval_val = int(interval.split("min")[0]) if isinstance(interval, str) and "min" in interval else (int(interval) if interval else 3)
    response = await fetch_with_retry(
        get_historical_candles,
        token, instrument_key, to_str, from_str,
        unit=CANDLE_UNIT,
        interval=interval_val,
    )

    # Extract raw candle arrays
    raw_candles = extract_candles_from_response(response)
    if not raw_candles:
        return {"fetched": 0, "valid": 0, "persisted": 0, "errors": []}

    # Normalize (IST → UTC, array → dict)
    # interval may be int (3) or str ("3min") — normalize_candles expects str
    interval_str = f"{interval}min" if isinstance(interval, int) else interval
    normalized = normalize_candles(raw_candles, symbol=symbol, interval=interval_str)

    # Validate
    report = validate_candle_batch(normalized)

    # Filter: only valid candles (hard errors rejected)
    valid_candles = [
        c for c in normalized
        if validate_candle(c, 0).is_valid
    ]

    # Persist valid candles (idempotent upsert)
    persisted = record_candles(db, valid_candles) if valid_candles else 0

    return {
        "fetched": len(raw_candles),
        "valid": report["valid"],
        "persisted": persisted,
        "errors": [e.errors for e in report["errors"]],
    }


# ---------------------------------------------------------------------------
# Backfill orchestration
# ---------------------------------------------------------------------------


async def run_backfill(
    token: str,
    start_date: date,
    end_date: date,
    instrument_key: str = NIFTY_INSTRUMENT_KEY,
    symbol: str = "NIFTY",
    dry_run: bool = False,
    skip_existing_chunks: bool = True,
) -> list[dict]:
    """Run the full backfill for a date range.

    Parameters
    ----------
    token:
        Upstox access token.
    start_date:
        First date to backfill (inclusive).
    end_date:
        Last date to backfill (inclusive).  Clamped to today.
    instrument_key:
        Upstox instrument key (default NIFTY 50).
    symbol:
        Symbol for candle storage (default NIFTY).
    dry_run:
        If True, show chunks without fetching.
    skip_existing_chunks:
        If True, skip chunks that already have data in the DB.

    Returns
    -------
    list[dict]
        Per-chunk results.
    """
    end_date = _clamp_end_date(end_date)
    chunks = generate_monthly_chunks(start_date, end_date)

    logger.info(
        "Backfill: %s to %s → %d chunks (28-day)",
        _date_to_str(start_date), _date_to_str(end_date), len(chunks),
    )

    if dry_run:
        for i, (cs, ce) in enumerate(chunks):
            logger.info("  Chunk %d: %s → %s", i + 1, _date_to_str(cs), _date_to_str(ce))
        return []

    db = _make_db_session()
    results: list[dict] = []

    try:
        for i, (cs, ce) in enumerate(chunks):
            chunk_label = f"[{i + 1}/{len(chunks)}] {_date_to_str(cs)} → {_date_to_str(ce)}"

            # Resume: skip chunks with existing data
            if skip_existing_chunks and _has_candles_for_date_range(db, symbol, cs, ce):
                logger.info("  %s — skipping (data exists)", chunk_label)
                results.append({"chunk": chunk_label, "status": "skipped"})
                continue

            logger.info("  %s — fetching…", chunk_label)
            try:
                result = await _fetch_and_persist_chunk(
                    db, token, instrument_key, cs, ce, symbol=symbol,
                )
                results.append({"chunk": chunk_label, "status": "ok", **result})
                logger.info(
                    "    fetched=%d valid=%d persisted=%d",
                    result["fetched"], result["valid"], result["persisted"],
                )
            except UpstoxError as exc:
                logger.error("  %s — FAILED: %s", chunk_label, exc.message)
                results.append({"chunk": chunk_label, "status": "error", "message": exc.message})
    finally:
        db.close()

    return results


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------


def report_status():
    """Print current backfill progress."""
    db = _make_db_session()
    try:
        count = db.scalar(
            select(func.count(NiftyCandle.id)).where(NiftyCandle.symbol == "NIFTY")
        ) or 0
        earliest = db.scalar(
            select(NiftyCandle.open_time)
            .where(NiftyCandle.symbol == "NIFTY")
            .order_by(NiftyCandle.open_time.asc())
            .limit(1)
        )
        latest = db.scalar(
            select(NiftyCandle.open_time)
            .where(NiftyCandle.symbol == "NIFTY")
            .order_by(NiftyCandle.open_time.desc())
            .limit(1)
        )

        print(f"NIFTY candles: {count}")
        if earliest:
            print(f"  Earliest: {earliest.isoformat()}")
        if latest:
            print(f"  Latest:   {latest.isoformat()}")
        if earliest and latest:
            span = (latest - earliest).days
            print(f"  Span:     {span} days")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Backfill NIFTY candles from Upstox V3 Historical Candle API",
    )
    parser.add_argument("--months", type=int, help="Backfill the last N months")
    parser.add_argument("--from", dest="from_date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--status", action="store_true", help="Show current progress")
    parser.add_argument("--dry-run", action="store_true", help="Show chunks without fetching")
    parser.add_argument("--no-skip", action="store_true", help="Re-fetch even existing chunks")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.status:
        report_status()
        return

    # Determine date range
    today = _today()
    if args.months:
        end_date = today
        start_date = today - timedelta(days=args.months * 30)
    elif args.from_date and args.to_date:
        start_date = date.fromisoformat(args.from_date)
        end_date = date.fromisoformat(args.to_date)
    elif args.from_date:
        start_date = date.fromisoformat(args.from_date)
        end_date = today
    else:
        # Default: last 6 months
        end_date = today
        start_date = today - timedelta(days=180)

    # Get token
    from app.services.token_store import get_token
    # For CLI, the session_id must be passed or the token must be set
    token = get_token(None)
    if not token:
        print("Error: No active Upstox session. Please log in first.", file=sys.stderr)
        sys.exit(1)

    # Run backfill
    results = asyncio.run(run_backfill(
        token,
        start_date,
        end_date,
        dry_run=args.dry_run,
        skip_existing_chunks=not args.no_skip,
    ))

    # Summary
    if results:
        ok = sum(1 for r in results if r.get("status") == "ok")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        errors = sum(1 for r in results if r.get("status") == "error")
        total_candles = sum(r.get("persisted", 0) for r in results if r.get("status") == "ok")
        print(f"\nDone: {ok} chunks fetched, {skipped} skipped, {errors} errors")
        print(f"Total candles persisted: {total_candles}")


if __name__ == "__main__":
    main()
