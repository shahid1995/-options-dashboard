"""Contract metadata backfill CLI — Phase 7.8F.

Populates the ``contract_specs`` table with historical option contract
metadata from the Upstox Get Expired Option Contracts API.

Key properties:
  - **Idempotent**: re-running the same expiry range does not create
    duplicates (upsert via ``upsert_contract_spec()``).
  - **Resumable**: already-stored instrument_keys are skipped via
    idempotent upsert (conflict detection).
  - **Lot-size immutable**: once a valid lot_size is stored for an
    instrument_key, it is NEVER overwritten.
  - **Safe degradation**: if the Expired Option Contracts API is
    unavailable (401/403/Plus-plan), the backfill reports the error
    and continues with other expiries.

Usage::

    # Populate all available expired expiries
    python -m app.tools.contract_metadata_backfill

    # Populate specific expiry range
    python -m app.tools.contract_metadata_backfill --start 2025-01 --end 2025-06

    # Check current progress
    python -m app.tools.contract_metadata_backfill --status

    # Dry-run (show what would be fetched)
    python -m app.tools.contract_metadata_backfill --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, _DEFAULT_DB_PATH
from app.models import ContractSpec
from app.services.contract_metadata import (
    SOURCE_UPSTOX_EXPIRED,
    upsert_contract_spec,
)
from app.services.token_store import get_token
from app.services.upstox import get_expired_expiries, get_expired_option_contracts
from app.services.candle_retry import fetch_with_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB session helper
# ---------------------------------------------------------------------------

def _get_session():
    """Create a database session.

    Uses the centralized path resolution from ``app.db`` so the same
    database file is used regardless of process working directory.
    """
    db_url = settings.DATABASE_URL or f"sqlite:///{_DEFAULT_DB_PATH}"
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def report_status(session=None) -> None:
    """Print current registry status."""
    close = False
    if session is None:
        session = _get_session()
        close = True

    try:
        total = session.scalar(select(func.count(ContractSpec.id))) or 0
        nifty_count = session.scalar(
            select(func.count(ContractSpec.id))
            .where(ContractSpec.underlying == "NIFTY")
        ) or 0
        with_lot_size = session.scalar(
            select(func.count(ContractSpec.id))
            .where(ContractSpec.lot_size.isnot(None))
        ) or 0
        without_lot_size = total - with_lot_size

        expiry_dates = session.execute(
            select(ContractSpec.expiry)
            .where(ContractSpec.underlying == "NIFTY")
            .distinct()
            .order_by(ContractSpec.expiry.asc())
        ).scalars().all()

        print(f"Contract metadata registry status:")
        print(f"  Total contracts:    {total}")
        print(f"  NIFTY contracts:    {nifty_count}")
        print(f"  With lot_size:      {with_lot_size}")
        print(f"  Without lot_size:   {without_lot_size}")
        print(f"  Expiry dates:       {len(expiry_dates)}")
        if expiry_dates:
            print(f"  Earliest expiry:    {expiry_dates[0]}")
            print(f"  Latest expiry:      {expiry_dates[-1]}")
    finally:
        if close:
            session.close()


# ---------------------------------------------------------------------------
# Backfill core
# ---------------------------------------------------------------------------

async def run_backfill(
    underlying: str = "NIFTY",
    start_expiry: str | None = None,
    end_expiry: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Populate the contract metadata registry from Upstox expired instruments API.

    Parameters
    ----------
    underlying : str
        Underlying symbol (default "NIFTY").
    start_expiry : str | None
        If provided, only process expiries >= this date (YYYY-MM or YYYY-MM-DD).
    end_expiry : str | None
        If provided, only process expiries <= this date.
    dry_run : bool
        If True, fetch data but do not persist.

    Returns
    -------
    dict
        Summary of what was done.
    """
    session = _get_session()
    token = get_token()

    if not token:
        print("ERROR: No active Upstox session. Visit /auth/login first.")
        return {"error": "no_session"}

    stats = {
        "expiries_discovered": 0,
        "expiries_fetched": 0,
        "expiries_failed": 0,
        "contracts_inserted": 0,
        "contracts_idempotent": 0,
        "contracts_conflict": 0,
        "contracts_filled": 0,
    }

    try:
        # 1. Discover available expired expiries
        print(f"Fetching expired expiries for {underlying}...")
        raw_expiries = await get_expired_expiries(
            token, underlying=underlying
        )

        expiries = _filter_expiries(raw_expiries, start_expiry, end_expiry)
        stats["expiries_discovered"] = len(expiries)

        if not expiries:
            print("No expired expiries found in the specified range.")
            return stats

        print(f"Found {len(expiries)} expiry dates to process.")

        if dry_run:
            print("\n[DRY RUN] Would fetch contracts for:")
            for exp in expiries:
                print(f"  {exp}")
            return stats

        # 2. Fetch and store contracts for each expiry
        for i, expiry_date in enumerate(expiries, 1):
            print(f"\n[{i}/{len(expiries)}] Fetching contracts for expiry {expiry_date}...")

            try:
                raw_contracts = await get_expired_option_contracts(
                    token,
                    underlying=underlying,
                    expiry_date=expiry_date,
                )

                if not raw_contracts:
                    print(f"  No contracts returned for {expiry_date}.")
                    stats["expiries_fetched"] += 1
                    continue

                print(f"  Received {len(raw_contracts)} contracts.")

                # 3. Upsert each contract
                from app.services.contract_metadata import upsert_contract_specs
                source_ref = f"EXPIRED_INSTRUMENTS/{underlying}/{expiry_date}"
                results = upsert_contract_specs(
                    session,
                    raw_contracts,
                    source=SOURCE_UPSTOX_EXPIRED,
                    source_reference=source_ref,
                )

                for r in results:
                    if r.action == "inserted":
                        stats["contracts_inserted"] += 1
                    elif r.action == "idempotent":
                        stats["contracts_idempotent"] += 1
                    elif r.action == "conflict":
                        stats["contracts_conflict"] += 1
                        print(f"  CONFLICT {r.instrument_key}: {r.message}")
                    elif r.action == "filled_lot_size":
                        stats["contracts_filled"] += 1

                stats["expiries_fetched"] += 1
                inserted = sum(1 for r in results if r.action == "inserted")
                idempotent = sum(1 for r in results if r.action == "idempotent")
                print(f"  Stored: {inserted} new, {idempotent} idempotent.")

            except Exception as e:
                error_msg = str(e)
                stats["expiries_failed"] += 1

                # Detect Upstox plan/permission errors
                if "401" in error_msg or "403" in error_msg:
                    print(f"  SKIP: API access denied (401/403) — likely Upstox Plus plan required.")
                    print(f"  Error: {error_msg}")
                elif "429" in error_msg:
                    print(f"  RATE LIMITED: {error_msg}")
                    print(f"  Waiting 5s before retrying...")
                    await asyncio.sleep(5)
                    # Retry once
                    try:
                        raw_contracts = await get_expired_option_contracts(
                            token,
                            underlying=underlying,
                            expiry_date=expiry_date,
                        )
                        if raw_contracts:
                            from app.services.contract_metadata import upsert_contract_specs
                            source_ref = f"EXPIRED_INSTRUMENTS/{underlying}/{expiry_date}"
                            results = upsert_contract_specs(
                                session,
                                raw_contracts,
                                source=SOURCE_UPSTOX_EXPIRED,
                                source_reference=source_ref,
                            )
                            for r in results:
                                if r.action == "inserted":
                                    stats["contracts_inserted"] += 1
                                elif r.action == "idempotent":
                                    stats["contracts_idempotent"] += 1
                            stats["expiries_fetched"] += 1
                            stats["expiries_failed"] -= 1  # undo the failure count
                            print(f"  Retry succeeded: {len(raw_contracts)} contracts.")
                    except Exception as retry_err:
                        print(f"  Retry also failed: {retry_err}")
                else:
                    print(f"  ERROR: {error_msg}")

        # 4. Final summary
        print(f"\n{'='*60}")
        print(f"Backfill complete.")
        print(f"  Expiries discovered:  {stats['expiries_discovered']}")
        print(f"  Expiries fetched:     {stats['expiries_fetched']}")
        print(f"  Expiries failed:      {stats['expiries_failed']}")
        print(f"  Contracts inserted:   {stats['contracts_inserted']}")
        print(f"  Contracts idempotent: {stats['contracts_idempotent']}")
        print(f"  Contracts conflict:   {stats['contracts_conflict']}")
        print(f"  Contracts filled:     {stats['contracts_filled']}")
        print(f"{'='*60}")

        return stats

    finally:
        session.close()


def _filter_expiries(
    expiries: list[str],
    start: str | None,
    end: str | None,
) -> list[str]:
    """Filter expiry dates to the requested range.

    Accepts YYYY-MM or YYYY-MM-DD format for start/end.
    """
    if not expiries:
        return []

    result = list(expiries)

    if start:
        # Normalize to YYYY-MM-DD for comparison
        start_norm = _normalize_expiry(start)
        result = [e for e in result if e >= start_norm]

    if end:
        end_norm = _normalize_expiry(end)
        result = [e for e in result if e <= end_norm]

    return sorted(result)


def _normalize_expiry(value: str) -> str:
    """Normalize YYYY-MM or YYYY-MM-DD to YYYY-MM-DD for comparison."""
    value = value.strip()
    if len(value) == 7:  # YYYY-MM
        return value + "-01"
    return value


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Populate contract metadata registry from Upstox Expired Option Contracts API."
    )
    parser.add_argument(
        "--underlying", default="NIFTY",
        help="Underlying symbol (default: NIFTY)",
    )
    parser.add_argument(
        "--start", default=None,
        help="Start expiry date (YYYY-MM or YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", default=None,
        help="End expiry date (YYYY-MM or YYYY-MM-DD)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current registry status and exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be fetched without persisting",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.status:
        report_status()
        return

    asyncio.run(run_backfill(
        underlying=args.underlying,
        start_expiry=args.start,
        end_expiry=args.end,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
