#!/usr/bin/env python
"""Daily Incremental Ingestion CLI — Phase 7.24.6.

Fetches only missing data after market close.  Designed for cron,
task scheduler, or manual invocation.

Usage::

    # Run daily ingestion for the last trading day
    python run_daily.py

    # Ingest for a specific date
    python run_daily.py --date 2026-08-22

    # Dry run — see plan without API calls
    python run_daily.py --dry-run

    # Skip specific stages
    python run_daily.py --skip-nifty
    python run_daily.py --skip-options
    python run_daily.py --skip-contracts

    # Show current status
    python run_daily.py --status

CRITICAL: This script must NEVER be called automatically by the server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, _DEFAULT_DB_PATH
from app.models import (
    ContractSpec,
    IngestionLog,
    NiftyCandle,
    OptionCandle,
)
from app.services.backfill_orchestrator import TokenBridge
from app.services.daily_ingestion import (
    DailyIngestionPipeline,
    _get_previous_trading_day,
    _is_after_market_close,
    _get_ist_date,
    _get_ist_now,
)
from app.services.upstox_client import UpstoxClient


def _get_db_session():
    url = settings.DATABASE_URL or f"sqlite:///{_DEFAULT_DB_PATH}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _print_status(db):
    """Print current data status."""
    total_specs = db.scalar(select(func.count(ContractSpec.id))) or 0
    nifty_candles = db.scalar(select(func.count(NiftyCandle.id))) or 0
    option_candles = db.scalar(select(func.count(OptionCandle.id))) or 0
    instruments = len(
        db.execute(select(OptionCandle.instrument_key).distinct()).scalars().all()
    )
    daily_logs = db.execute(
        select(IngestionLog)
        .where(IngestionLog.operation == "daily_ingestion")
        .order_by(IngestionLog.id.desc())
        .limit(5)
    ).scalars().all()

    now = _get_ist_now()
    target = _get_previous_trading_day()

    print("=" * 60)
    print("DAILY INGESTION STATUS")
    print("=" * 60)
    print(f"  Current IST time:   {now.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"  Last trading day:   {target.isoformat()}")
    print(f"  After market close: {'Yes' if _is_after_market_close() else 'No'}")
    print()
    print(f"  Contract specs:     {total_specs}")
    print(f"  NIFTY candles:      {nifty_candles}")
    print(f"  Option candles:     {option_candles}")
    print(f"  Instruments:        {instruments}")
    print()
    print("  Recent daily ingestion runs:")
    for log in daily_logs:
        print(f"    {log.started_at[:16]}  {log.status:8s}  {log.error_message or 'ok'}")
    print("=" * 60)


def _print_result(result):
    print("-" * 60)
    print(f"  Status:              {result.status}")
    print(f"  Target date:         {result.metadata.get('target_date', '?')}")
    print(f"  NIFTY candles:       {result.nifty_candles_inserted}")
    print(f"  Contracts refreshed: {result.contracts_refreshed}")
    print(f"  Option instruments:  {result.option_instruments_processed}")
    print(f"  Option candles:      {result.option_candles_inserted}")
    print(f"  API calls:           {result.api_calls}")
    print(f"  Elapsed:             {result.elapsed_seconds}s")
    if result.errors:
        print(f"  Errors ({len(result.errors)}):")
        for e in result.errors[:5]:
            print(f"    - {e[:120]}")
    print("-" * 60)


async def _run(args):
    db = _get_db_session()

    if args.status:
        _print_status(db)
        db.close()
        return

    token_bridge = TokenBridge(args.session_id)
    client = UpstoxClient(token_provider=token_bridge)

    target = None
    if args.date:
        target = date.fromisoformat(args.date)

    pipeline = DailyIngestionPipeline(
        db, client,
        target_date=target,
        skip_nifty=args.skip_nifty,
        skip_contracts=args.skip_contracts,
        skip_options=args.skip_options,
    )

    if args.dry_run:
        from app.services.daily_ingestion import (
            _get_previous_trading_day as gptd,
            _is_weekday,
        )
        effective_target = target or gptd()
        print("DRY RUN — no API calls, no database changes")
        print(f"  Target date:   {effective_target.isoformat()}")
        print(f"  Is weekday:    {_is_weekday(effective_target)}")
        print(f"  Skip nifty:    {args.skip_nifty}")
        print(f"  Skip contracts:{args.skip_contracts}")
        print(f"  Skip options:  {args.skip_options}")
        db.close()
        return

    # Warn if market is still open
    if not _is_after_market_close() and target is None:
        now = _get_ist_now()
        print(f"WARNING: Current IST time is {now.strftime('%H:%M')}.")
        print("         Market may not be closed yet. Data may be incomplete.")
        print("         Consider running after 16:00 IST.")
        print()

    print(f"Starting daily ingestion for {target or 'last trading day'}...")
    print()

    result = await pipeline.run()
    _print_result(result)

    print()
    _print_status(db)
    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Daily Incremental Ingestion — Phase 7.24.6",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_daily.py                  # Ingest last trading day
  python run_daily.py --date 2026-08-22
  python run_daily.py --dry-run        # See plan
  python run_daily.py --status         # Check current data
  python run_daily.py --skip-nifty     # Skip NIFTY candles
  python run_daily.py --skip-options   # Skip option candles
  python run_daily.py --skip-contracts # Skip contract refresh

CRITICAL: This script must NEVER be called automatically by the server.
        """,
    )
    parser.add_argument("--date", type=str, help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without fetching")
    parser.add_argument("--skip-nifty", action="store_true", help="Skip NIFTY candle ingestion")
    parser.add_argument("--skip-contracts", action="store_true", help="Skip contract metadata refresh")
    parser.add_argument("--skip-options", action="store_true", help="Skip option candle ingestion")
    parser.add_argument("--session-id", type=str, help="Session ID for in-memory token")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
