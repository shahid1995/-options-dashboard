#!/usr/bin/env python
"""Unified Backfill CLI — Phase 7.24.5.

CLI-first entry point for all historical data ingestion. Works without
FastAPI by using UpstoxTokenManager for persistent token storage.

Usage::

    # Show help
    python run_backfill.py --help

    # Dry run — shows what would be fetched, zero API calls
    python run_backfill.py --dry-run

    # Backfill contract metadata only
    python run_backfill.py --contracts

    # Backfill NIFTY index candles only
    python run_backfill.py --index

    # Backfill option candles only
    python run_backfill.py --options

    # Backfill everything
    python run_backfill.py --all

    # Check current database status
    python run_backfill.py --status

    # Resume interrupted backfill (default behavior)
    python run_backfill.py --all

    # Force re-download
    python run_backfill.py --all --force

    # Limit option candles to N instruments
    python run_backfill.py --options --limit 50

    # Backfill specific expiry
    python run_backfill.py --options --expiry 2024-10-31

CRITICAL: This script must NEVER be called automatically by server
startup, init_db(), or any other non-CLI pathway.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os
from datetime import datetime

# Ensure the backend directory is on the Python path so that app.* imports work
# when running this script directly (e.g. ``python run_backfill.py``).
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, _DEFAULT_DB_PATH
from app.models import (
    ContractSpec,
    IngestionCheckpoint,
    IngestionLog,
    NiftyCandle,
    OptionCandle,
)
from app.services.backfill_orchestrator import (
    BackfillOrchestrator,
    TokenBridge,
    NIFTY_INDEX_KEY,
)
from app.services.upstox_client import (
    UpstoxClient,
    UpstoxAuthenticationError,
)
from app.services.rate_limiter import GlobalRateLimiter, RateLimiterConfig



def _get_db_session():
    """Create a DB session for the CLI."""
    url = settings.DATABASE_URL or f"sqlite:///{_DEFAULT_DB_PATH}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _get_token_bridge(session_id: str | None = None) -> TokenBridge:
    """Create a token bridge for the CLI."""
    return TokenBridge(session_id=session_id)


def _print_status(db):
    """Print current database status."""
    total_specs = db.scalar(select(func.count(ContractSpec.id))) or 0
    nifty_specs = db.scalar(
        select(func.count(ContractSpec.id)).where(ContractSpec.underlying == "NIFTY")
    ) or 0
    nifty_candles = db.scalar(select(func.count(NiftyCandle.id))) or 0
    option_candles = db.scalar(select(func.count(OptionCandle.id))) or 0
    instruments_with_candles = len(
        db.execute(select(OptionCandle.instrument_key).distinct()).scalars().all()
    )
    checkpoints_completed = db.scalar(
        select(func.count(IngestionCheckpoint.id)).where(
            IngestionCheckpoint.status == "COMPLETED"
        )
    ) or 0
    logs_count = db.scalar(select(func.count(IngestionLog.id))) or 0

    print("=" * 60)
    print("HISTORICAL DATA BACKFILL STATUS")
    print("=" * 60)
    print(f"  Contract specs:         {total_specs}")
    print(f"    NIFTY contracts:      {nifty_specs}")
    print(f"  NIFTY candles:          {nifty_candles}")
    print(f"  Option candles:         {option_candles}")
    print(f"    Instruments with data:{instruments_with_candles}")
    print(f"  Checkpoints completed:  {checkpoints_completed}")
    print(f"  Ingestion log entries:  {logs_count}")
    print("=" * 60)

    if nifty_candles > 0:
        earliest = db.scalar(
            select(NiftyCandle.open_time).order_by(NiftyCandle.open_time.asc()).limit(1)
        )
        latest = db.scalar(
            select(NiftyCandle.open_time).order_by(NiftyCandle.open_time.desc()).limit(1)
        )
        if earliest and latest:
            print(f"  NIFTY range:            {earliest.date()} to {latest.date()}")
            print(f"  NIFTY span:             {(latest - earliest).days} days")

    if option_candles > 0:
        earliest = db.scalar(
            select(OptionCandle.open_time).order_by(OptionCandle.open_time.asc()).limit(1)
        )
        latest = db.scalar(
            select(OptionCandle.open_time).order_by(OptionCandle.open_time.desc()).limit(1)
        )
        if earliest and latest:
            print(f"  Option range:           {earliest.date()} to {latest.date()}")
            print(f"  Option span:            {(latest - earliest).days} days")


def _print_result(result):
    """Print a formatted backfill result."""
    print("-" * 60)
    print(f"  Operation:    {result.operation}")
    print(f"  Status:       {result.status}")
    print(f"  API calls:    {result.api_calls}")
    print(f"  Rows fetched: {result.rows_fetched}")
    print(f"  Rows inserted:{result.rows_inserted}")
    print(f"  Rows skipped: {result.rows_skipped}")
    print(f"  Elapsed:      {result.elapsed_seconds}s")
    if result.errors:
        print(f"  Errors ({len(result.errors)}):")
        for e in result.errors[:5]:
            print(f"    - {e[:120]}")
    print("-" * 60)


def _print_rate_limiter_status(limiter: GlobalRateLimiter) -> None:
    """Print the global rate limiter adaptive state."""
    m = limiter.snapshot()
    print("=" * 60)
    print("GLOBAL RATE LIMITER STATUS (Phase 7.24.8C)")
    print("=" * 60)
    print(f"  Concurrency:           {m.current_concurrency}")
    print(f"  Request interval:      {m.current_interval_s:.2f}s")
    print(f"  Cooldown remaining:    {m.cooldown_remaining_s:.1f}s")
    print(f"  Total requests:        {m.total_requests}")
    print(f"  Successful requests:   {m.successful_requests}")
    print(f"  429 responses:         {m.rate_limit_429s}")
    print(f"  Consecutive 429s:      {m.consecutive_429s}")
    print(f"  Client retries:        {m.retries_from_client}")
    print(f"  Total cooldown time:   {m.total_cooldown_time_s:.1f}s")
    print(f"  Instruments completed: {m.instruments_completed}")
    print(f"  Instruments remaining: {m.instruments_remaining}")
    print("=" * 60)


async def _run(args):
    """Main async entry point."""
    db = _get_db_session()
    token_bridge = _get_token_bridge(args.session_id)
    client = UpstoxClient(token_provider=token_bridge)

    # Phase 7.24.8C: Create global rate limiter shared by all workers
    rate_config = RateLimiterConfig(
        initial_concurrency=args.concurrency,
        max_concurrency=6,
    )
    rate_limiter = GlobalRateLimiter(config=rate_config)

    orchestrator = BackfillOrchestrator(
        db, client,
        dry_run=args.dry_run,
        force=args.force,
        rate_limiter=rate_limiter,
    )

    if args.status:
        _print_status(db)
        db.close()
        return

    if args.dry_run:
        print("DRY RUN — no API calls, no database changes")
        print()

        plan = await orchestrator.run_dry_run()
        print("BACKFILL PLAN:")
        print(f"  Contracts in registry:   {plan['contracts']['nifty_in_registry']}")
        print(f"  NIFTY candles:           {plan['nifty_candles']['total']}")
        print(f"  Option candles:          {plan['option_candles']['total']}")
        print(f"  Instruments with data:   {plan['option_candles']['instruments_with_data']}")
        print(f"  Instruments needing:     {plan['option_candles']['in_registry_missing_data']}")
        print(f"  Est. API calls:          {plan['estimated_work']['estimated_api_calls']}")
        if args.universe:
            print(f"  Universe filter:         {args.universe}")
        print(f"  Concurrency:             {args.concurrency}")
        print()

        # Also show specific stages
        if args.all or args.contracts:
            result = await orchestrator.run_contracts()
            print("CONTRACT METADATA PLAN:")
            for k, v in result.metadata.items():
                if isinstance(v, list):
                    print(f"  {k}: {len(v)} items")
                else:
                    print(f"  {k}: {v}")
            print()

        if args.all or args.index:
            start_dt = None
            if args.start_date:
                start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
            result = await orchestrator.run_nifty(start_date=start_dt)
            print("NIFTY CANDLES PLAN:")
            for k, v in result.metadata.items():
                if isinstance(v, list):
                    print(f"  {k}: {len(v)} chunks")
                else:
                    print(f"  {k}: {v}")
            print()

        if args.all or args.options:
            result = await orchestrator.run_options(
                expiry=args.expiry,
                max_instruments=args.limit,
                universe=args.universe,
                concurrency=args.concurrency,
            )
            print("OPTION CANDLES PLAN:")
            for k, v in result.metadata.items():
                print(f"  {k}: {v}")
            print()

        db.close()
        return

    # Determine stages
    stages = []
    if args.all:
        stages = ["contracts", "nifty", "options"]
    else:
        if args.contracts:
            stages.append("contracts")
        if args.index:
            stages.append("nifty")
        if args.options:
            stages.append("options")

    if not stages:
        print("ERROR: Specify --all, --contracts, --index, or --options")
        print("       Use --help for available commands.")
        db.close()
        sys.exit(1)

    print(f"Starting backfill: {', '.join(stages)}")
    if args.dry_run:
        print("(dry run mode)")
    print()

    if "options" in stages:
        result = await orchestrator.run_options(
            expiry=args.expiry,
            max_instruments=args.limit,
            universe=args.universe,
            concurrency=args.concurrency,
        )
    elif "contracts" in stages and "nifty" in stages:
        start_dt = None
        if args.start_date:
            start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        result = await orchestrator.run_all(stages=stages, nifty_start_date=start_dt)
    else:
        start_dt = None
        if args.start_date:
            start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        result = await orchestrator.run_all(stages=stages, nifty_start_date=start_dt)

    _print_result(result)

    # Phase 7.24.8C: Print rate limiter adaptive state
    if getattr(args, 'rate_status', False) or args.options:
        print()
        _print_rate_limiter_status(rate_limiter)

    # Final status
    print()
    _print_status(db)
    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Unified Historical Data Backfill — Phase 7.24.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_backfill.py --status          # Check current data
  python run_backfill.py --dry-run --all   # See full plan
  python run_backfill.py --contracts       # Fetch contract metadata
  python run_backfill.py --index           # Fetch NIFTY candles
  python run_backfill.py --options         # Fetch option candles
  python run_backfill.py --all             # Full backfill
  python run_backfill.py --options --expiry 2024-10-31
  python run_backfill.py --all --force     # Re-download everything
  python run_backfill.py --index --start-date 2024-10-01  # Backfill NIFTY from Oct 2024

CRITICAL: This script must NEVER be called automatically by the server.
        """,
    )

    # Modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--status", action="store_true", help="Show current database status")
    mode_group.add_argument("--dry-run", action="store_true", help="Show plan without fetching")
    mode_group.add_argument("--all", action="store_true", help="Run all backfill stages")

    # Stages
    parser.add_argument("--contracts", action="store_true", help="Backfill contract metadata only")
    parser.add_argument("--index", action="store_true", help="Backfill NIFTY index candles only")
    parser.add_argument("--options", action="store_true", help="Backfill option candles only")

    # Filters
    parser.add_argument("--expiry", type=str, help="Specific expiry date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, help="Max instruments for option candles")
    parser.add_argument("--force", action="store_true", help="Re-download even existing data")
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="NIFTY backfill start date (YYYY-MM-DD). Default: earliest expiry - 3 days.",
    )

    # Phase 7.24.8C: Universe, concurrency (rate-limiter managed)
    parser.add_argument(
        "--universe", type=str, default=None,
        choices=["ATM_5", "ATM_10", "ATM_20", "ATM_30"],
        help="Filter to ATM ±N strike universe (default: all contracts)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Initial concurrency (default: 1, max: 6). Rate limiter adapts.",
    )
    parser.add_argument(
        "--rate-status", action="store_true",
        help="Show global rate limiter adaptive state after run",
    )

    # Auth
    parser.add_argument("--session-id", type=str, help="Session ID for in-memory token (server)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
