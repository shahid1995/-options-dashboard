"""Option candle backfill engine -- Phase 7.14.

Populates the ``option_candles`` table with historical OHLCV data for
expired option and future contracts from the Upstox Expired Historical
Candle Data API.

Key properties:
  - **Idempotent**: re-running skips already-fetched contracts.
  - **Resumable**: interrupted backfills can be restarted safely.
  - **Rate-limited**: respects Upstox API limits (50 req/sec, 500/min).
  - **Checkpointed**: progress tracked per contract (instrument_key).
  - **Transactional**: each contract's candles are committed atomically.

Architecture:
  1. Discover expired expiries (from contract_specs or API)
  2. For each expiry, discover contracts (from contract_specs)
  3. For each contract, fetch historical candles
  4. Normalize, validate, persist
  5. Record progress for resume

Usage::

    # Backfill all available contracts
    python -m app.tools.option_candle_backfill --all

    # Backfill specific expiry
    python -m app.tools.option_candle_backfill --expiry 2024-10-31

    # Check progress
    python -m app.tools.option_candle_backfill --status

    # Dry-run
    python -m app.tools.option_candle_backfill --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, _DEFAULT_DB_PATH
from app.models import ContractSpec, OptionCandle
from app.services.candle_retry import fetch_with_retry
from app.services.candle_validation import validate_candle
from app.services.option_candles import (
    normalize_option_candles,
    record_option_candles,
    count_option_candles,
)
from app.services.upstox import (
    get_expired_option_contracts,
    get_expired_historical_candles,
    UpstoxError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"
DEFAULT_INTERVAL = "3minute"
DEFAULT_BACKFILL_INTERVAL = "3min"  # for record_option_candles

# Rate limiting: 200ms between requests (5 req/sec, well under 50/sec)
REQUEST_DELAY_SECONDS = 0.2

# Progress tracking table name (stored in contract_specs via backfill_status)
STATUS_FETCHED = "fetched"
STATUS_PENDING = "pending"
STATUS_ERROR = "error"


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


# ---------------------------------------------------------------------------
# Contract discovery
# ---------------------------------------------------------------------------

def discover_contracts(
    db,
    expiry: str | None = None,
    underlying: str = "NIFTY",
) -> list[dict]:
    """Discover contracts that need candle backfill.

    Returns a list of dicts with instrument_key, expiry, and metadata.
    """
    stmt = select(ContractSpec).where(ContractSpec.underlying == underlying)
    if expiry:
        stmt = stmt.where(ContractSpec.expiry == expiry)

    specs = db.execute(stmt).scalars().all()
    return [
        {
            "instrument_key": s.instrument_key,
            "expiry": s.expiry,
            "strike_price": s.strike_price,
            "instrument_type": s.instrument_type,
            "lot_size": s.lot_size,
            "trading_symbol": s.trading_symbol,
        }
        for s in specs
    ]


# ---------------------------------------------------------------------------
# Checkpoint / resume
# ---------------------------------------------------------------------------

def get_completed_instruments(db) -> set[str]:
    """Return instrument_keys that already have candle data."""
    return set(
        db.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all()
    )


# ---------------------------------------------------------------------------
# Core backfill
# ---------------------------------------------------------------------------

async def backfill_contract(
    db,
    token: str,
    contract: dict,
    interval: str = DEFAULT_INTERVAL,
    backfill_interval: str = DEFAULT_BACKFILL_INTERVAL,
    dry_run: bool = False,
) -> dict:
    """Fetch and persist candles for a single contract.

    Returns a summary dict with status, counts, and any errors.
    """
    ik = contract["instrument_key"]
    expiry = contract["expiry"]

    result: dict[str, Any] = {
        "instrument_key": ik,
        "expiry": expiry,
        "status": "pending",
        "candles_fetched": 0,
        "candles_persisted": 0,
        "error": None,
    }

    if dry_run:
        result["status"] = "dry_run"
        return result

    try:
        # Fetch candles for the expiry date
        candle_resp = await fetch_with_retry(
            get_expired_historical_candles,
            token,
            expired_instrument_key=ik,
            interval=interval,
            to_date=expiry,
            from_date=expiry,
        )

        # Extract raw candles
        raw_candles = candle_resp.get("data", {}).get("candles", [])
        if not isinstance(raw_candles, list):
            raw_candles = []
        result["candles_fetched"] = len(raw_candles)

        if not raw_candles:
            result["status"] = "empty"
            return result

        # Normalize
        normalized = normalize_option_candles(
            raw_candles, instrument_key=ik, interval=backfill_interval,
        )

        # Validate (filter invalid)
        valid = [
            c for c in normalized
            if validate_candle(c, 0).is_valid
        ]

        # Persist
        saved = record_option_candles(db, valid) if valid else 0
        result["candles_persisted"] = saved
        result["status"] = "ok"

    except UpstoxError as e:
        result["status"] = "error"
        result["error"] = f"UpstoxError({e.status_code}): {e.message}"
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"

    return result


async def run_backfill(
    token: str,
    expiry: str | None = None,
    underlying: str = "NIFTY",
    interval: str = DEFAULT_INTERVAL,
    dry_run: bool = False,
    skip_existing: bool = True,
    max_contracts: int | None = None,
) -> dict:
    """Run the option candle backfill.

    Parameters
    ----------
    token : str
        Upstox access token.
    expiry : str | None
        If provided, only backfill this specific expiry.
    underlying : str
        Underlying symbol (default "NIFTY").
    interval : str
        Upstox API interval (default "3minute").
    dry_run : bool
        If True, show what would be fetched without fetching.
    skip_existing : bool
        If True, skip contracts that already have candle data.
    max_contracts : int | None
        If provided, limit the number of contracts to process.

    Returns
    -------
    dict
        Summary of the backfill run.
    """
    db = _make_db_session()

    stats = {
        "contracts_discovered": 0,
        "contracts_skipped": 0,
        "contracts_fetched": 0,
        "contracts_empty": 0,
        "contracts_error": 0,
        "total_candles_persisted": 0,
        "elapsed_seconds": 0,
        "errors": [],
    }

    start_time = time.time()

    try:
        # 1. Discover contracts
        contracts = discover_contracts(db, expiry=expiry, underlying=underlying)
        stats["contracts_discovered"] = len(contracts)

        if not contracts:
            logger.info("No contracts found for backfill.")
            return stats

        # 2. Filter already-completed contracts
        if skip_existing:
            completed = get_completed_instruments(db)
            remaining = [c for c in contracts if c["instrument_key"] not in completed]
            stats["contracts_skipped"] = len(contracts) - len(remaining)
            contracts = remaining

        if max_contracts:
            contracts = contracts[:max_contracts]

        logger.info(
            "Backfill: %d contracts to process (skipped %d existing)",
            len(contracts), stats["contracts_skipped"],
        )

        if dry_run:
            for c in contracts:
                logger.info("  [DRY RUN] %s (%s %s)", c["instrument_key"], c["strike_price"], c["instrument_type"])
            stats["elapsed_seconds"] = round(time.time() - start_time, 2)
            return stats

        # 3. Process each contract
        for i, contract in enumerate(contracts, 1):
            ik = contract["instrument_key"]
            logger.info(
                "[%d/%d] %s (strike=%s, type=%s, lot=%s)",
                i, len(contracts), ik, contract["strike_price"],
                contract["instrument_type"], contract["lot_size"],
            )

            result = await backfill_contract(
                db, token, contract,
                interval=interval,
            )

            if result["status"] == "ok":
                stats["contracts_fetched"] += 1
                stats["total_candles_persisted"] += result["candles_persisted"]
                logger.info(
                    "  -> %d candles fetched, %d persisted",
                    result["candles_fetched"], result["candles_persisted"],
                )
            elif result["status"] == "empty":
                stats["contracts_empty"] += 1
                logger.info("  -> no candle data available")
            elif result["status"] == "error":
                stats["contracts_error"] += 1
                stats["errors"].append(result["error"])
                logger.warning("  -> ERROR: %s", result["error"])

            # Rate limiting: delay between requests
            if i < len(contracts):
                time.sleep(REQUEST_DELAY_SECONDS)

    finally:
        db.close()

    stats["elapsed_seconds"] = round(time.time() - start_time, 2)
    return stats


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def report_status():
    """Print current backfill progress."""
    db = _make_db_session()
    try:
        total_contracts = db.scalar(
            select(func.count(ContractSpec.id))
            .where(ContractSpec.underlying == "NIFTY")
        ) or 0

        completed_instruments = db.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all()
        completed_count = len(completed_instruments)

        total_candles = db.scalar(select(func.count(OptionCandle.id))) or 0

        earliest = db.scalar(
            select(OptionCandle.open_time)
            .order_by(OptionCandle.open_time.asc())
            .limit(1)
        )
        latest = db.scalar(
            select(OptionCandle.open_time)
            .order_by(OptionCandle.open_time.desc())
            .limit(1)
        )

        print(f"Option candle backfill status:")
        print(f"  Total contracts in registry: {total_contracts}")
        print(f"  Contracts with candle data:  {completed_count}")
        print(f"  Contracts missing data:      {total_contracts - completed_count}")
        print(f"  Total candles stored:        {total_candles}")
        if earliest:
            print(f"  Earliest candle:             {earliest.isoformat()}")
        if latest:
            print(f"  Latest candle:               {latest.isoformat()}")
        if earliest and latest:
            span = (latest - earliest).days
            print(f"  Time span:                   {span} days")
        print(f"  Completion:                  {completed_count}/{total_contracts} ({100 * completed_count // max(total_contracts, 1)}%)")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical option candles from Upstox Expired Historical Candle API",
    )
    parser.add_argument("--all", action="store_true", help="Backfill all available contracts")
    parser.add_argument("--expiry", type=str, help="Backfill a specific expiry (YYYY-MM-DD)")
    parser.add_argument("--status", action="store_true", help="Show current progress")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched")
    parser.add_argument("--max", type=int, dest="max_contracts", help="Max contracts to process")
    parser.add_argument("--no-skip", action="store_true", help="Re-fetch even existing contracts")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.status:
        report_status()
        return

    if not args.all and not args.expiry:
        parser.print_help()
        print("\nERROR: Specify --all or --expiry")
        sys.exit(1)

    # Get token
    from app.services.token_store import get_token
    token = get_token()
    if not token:
        print("Error: No active Upstox session. Please log in first.", file=sys.stderr)
        sys.exit(1)

    # Run backfill
    stats = asyncio.run(run_backfill(
        token,
        expiry=args.expiry if args.expiry else None,
        dry_run=args.dry_run,
        skip_existing=not args.no_skip,
        max_contracts=args.max_contracts,
    ))

    # Summary
    print(f"\nBackfill complete:")
    print(f"  Contracts discovered: {stats['contracts_discovered']}")
    print(f"  Contracts skipped:    {stats['contracts_skipped']}")
    print(f"  Contracts fetched:    {stats['contracts_fetched']}")
    print(f"  Contracts empty:      {stats['contracts_empty']}")
    print(f"  Contracts error:      {stats['contracts_error']}")
    print(f"  Candles persisted:    {stats['total_candles_persisted']}")
    print(f"  Elapsed:              {stats['elapsed_seconds']}s")
    if stats["errors"]:
        print(f"  Errors:")
        for e in stats["errors"][:5]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
