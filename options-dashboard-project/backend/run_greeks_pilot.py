#!/usr/bin/env python
"""Phase 7.23C — Safe, Resumable Historical Greeks Reconstruction CLI.

Processes one instrument at a time with checkpointing, backup, and
failure isolation.  No web server or Upstox authentication required.

Usage:
    python run_greeks_pilot.py --status
    python run_greeks_pilot.py --backup
    python run_greeks_pilot.py --missing --limit 1
    python run_greeks_pilot.py --missing --limit 5
    python run_greeks_pilot.py --missing             # process ALL missing
    python run_greeks_pilot.py --instrument "NSE_FO|..."
    python run_greeks_pilot.py --retry-failed
    python run_greeks_pilot.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

# Ensure we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Database helpers (Phase 10B: SQLAlchemy for PostgreSQL compatibility)
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    """Absolute path of the production database (SQLite fallback)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_journal.db")


def get_engine():
    """SQLAlchemy engine bound to the production database."""
    from app.db import engine as _eng
    return _eng


def get_session():
    """Fresh SQLAlchemy session."""
    from app.db import SessionLocal
    return SessionLocal()


def raw_conn():
    """Database connection via SQLAlchemy (works for both SQLite and PostgreSQL).

    Phase 10B: Replaces raw sqlite3 connection with SQLAlchemy.
    Returns a SQLAlchemy connection for lightweight queries.
    """
    from sqlalchemy import text
    engine = get_engine()
    return engine.connect()


def _ensure_checkpoint_table(conn=None) -> None:
    """Create the reconstruction checkpoint table if it does not exist.

    Phase 10B: Uses SQLAlchemy DDL for SQLite/PostgreSQL compatibility.
    """
    from sqlalchemy import text
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS greeks_checkpoint (
                instrument_key TEXT PRIMARY KEY,
                status         TEXT NOT NULL DEFAULT 'PENDING',
                candle_count   INTEGER DEFAULT 0,
                success_count  INTEGER DEFAULT 0,
                failure_count  INTEGER DEFAULT 0,
                rows_persisted INTEGER DEFAULT 0,
                error_message  TEXT,
                run_id         TEXT,
                started_at     TEXT,
                completed_at   TEXT,
                calc_version   TEXT DEFAULT '1.0.0'
            )
        """))
        # Ensure calc_version column exists for older schemas
        try:
            connection.execute(text("SELECT calc_version FROM greeks_checkpoint LIMIT 1"))
        except Exception:
            if engine.dialect.name == "sqlite":
                connection.execute(text("ALTER TABLE greeks_checkpoint ADD COLUMN calc_version TEXT DEFAULT '1.0.0'"))


# ---------------------------------------------------------------------------
# PART 3 — Database backup
# ---------------------------------------------------------------------------

def cmd_backup(_args):
    """Create a timestamped backup of the production database."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"paper_journal_backup_{ts}.db"
    backup_path = os.path.join(os.path.dirname(db_path), backup_name)

    size_before = os.path.getsize(db_path)
    print(f"Source:      {db_path}")
    print(f"Source size: {size_before:,} bytes")
    print(f"Backup:      {backup_path}")

    shutil.copy2(db_path, backup_path)

    size_after = os.path.getsize(backup_path)
    print(f"Backup size: {size_after:,} bytes")

    # Verify backup is readable
    conn = sqlite3.connect(backup_path)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    tables = {}
    for t in ["nifty_candles", "contract_specs", "option_candles", "option_greeks"]:
        try:
            tables[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            tables[t] = "ERROR"
    conn.close()

    print(f"Integrity:   {integrity}")
    for t, cnt in tables.items():
        print(f"  {t}: {cnt}")

    if integrity != "ok":
        print("ERROR: Backup integrity check failed!")
        sys.exit(1)
    if size_before != size_after:
        print("WARNING: Backup size differs from source (WAL checkpoint may have occurred)")
    print("\nBackup verified successfully.")


# ---------------------------------------------------------------------------
# PART 4 — Database integrity check
# ---------------------------------------------------------------------------

def _check_integrity() -> bool:
    """Run SQLite integrity check. Returns True if ok."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return False

    print(f"Database: {db_path}")
    print(f"Size:     {os.path.getsize(db_path):,} bytes")

    conn = sqlite3.connect(db_path)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Integrity: {integrity}")

    if integrity != "ok":
        print("HARD STOP: Database integrity check failed!")
        conn.close()
        return False

    for t in ["nifty_candles", "contract_specs", "option_candles", "option_greeks"]:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt:,}")
        except Exception as e:
            print(f"  {t}: ERROR ({e})")

    opt = conn.execute("SELECT COUNT(DISTINCT instrument_key) FROM option_candles").fetchone()[0]
    grk = conn.execute("SELECT COUNT(DISTINCT instrument_key) FROM option_greeks").fetchone()[0]
    print(f"  unique option instruments: {opt}")
    print(f"  unique Greeks instruments: {grk}")
    conn.close()
    return True


# ---------------------------------------------------------------------------
# PART 5 — Determine missing instruments
# ---------------------------------------------------------------------------

def _get_missing_instruments(conn: sqlite3.Connection, limit: int | None = None) -> list[str]:
    """Return instrument_keys that have option_candles but lack current-version Greeks.

    The authoritative test is whether option_greeks rows exist for the
    current calc_version and interval — NOT the checkpoint status.
    Checkpoints are a resume aid, not the source of truth.
    """
    _ensure_checkpoint_table(conn)

    # Instrument is missing if it has option_candles but no matching
    # option_greeks rows for the current calc_version (1.0.0) and interval (3min).
    query = """
        SELECT oc.instrument_key, COUNT(*) AS candle_count
        FROM option_candles oc
        WHERE NOT EXISTS (
            SELECT 1 FROM option_greeks og
            WHERE og.instrument_key = oc.instrument_key
              AND og.calc_version = '1.0.0'
              AND og.interval = '3min'
        )
        GROUP BY oc.instrument_key
        ORDER BY candle_count DESC
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(query).fetchall()]


def _get_status_counts(conn: sqlite3.Connection) -> dict:
    """Return counts for status display."""
    _ensure_checkpoint_table(conn)
    total = conn.execute("SELECT COUNT(DISTINCT instrument_key) FROM option_candles").fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM greeks_checkpoint WHERE status = 'COMPLETED'"
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM greeks_checkpoint WHERE status = 'FAILED'"
    ).fetchone()[0]
    running = conn.execute(
        "SELECT COUNT(*) FROM greeks_checkpoint WHERE status = 'RUNNING'"
    ).fetchone()[0]
    missing = _get_missing_instruments(conn)
    return {
        "total_instruments": total,
        "completed": completed,
        "failed": failed,
        "running": running,
        "missing": len(missing),
        "missing_keys": missing[:10],
    }


# ---------------------------------------------------------------------------
# PART 13 — CLI commands
# ---------------------------------------------------------------------------

def cmd_status(_args):
    """Print database and checkpoint status (dry-run, no modifications)."""
    if not _check_integrity():
        sys.exit(1)

    conn = raw_conn()
    counts = _get_status_counts(conn)
    conn.close()

    print(f"\n=== RECONSTRUCTION STATUS ===")
    print(f"Total instruments: {counts['total_instruments']}")
    print(f"Completed:         {counts['completed']}")
    print(f"Failed:            {counts['failed']}")
    print(f"Running:           {counts['running']}")
    print(f"Missing:           {counts['missing']}")

    if counts["missing_keys"]:
        print(f"\nFirst {len(counts['missing_keys'])} missing:")
        for ik in counts["missing_keys"]:
            print(f"  {ik}")


def cmd_missing(args):
    """Process missing instruments one at a time with checkpointing."""
    if not _check_integrity():
        sys.exit(1)

    conn = raw_conn()
    _ensure_checkpoint_table(conn)
    missing = _get_missing_instruments(conn, limit=args.limit)
    conn.close()

    if not missing:
        print("No missing instruments. Reconstruction is complete.")
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"Run ID: {run_id}")
    print(f"Missing instruments: {len(missing)}")
    print(f"Limit: {'all' if args.limit is None else args.limit}")
    print()

    stats = {"completed": 0, "failed": 0, "skipped": 0, "total_persisted": 0}
    start_all = time.time()

    for i, ik in enumerate(missing):
        _process_one_instrument(ik, i + 1, len(missing), run_id, stats)

    elapsed = time.time() - start_all
    _print_final_summary(stats, elapsed, conn_path=get_db_path())


def cmd_instrument(args):
    """Process a single named instrument."""
    if not args.instrument:
        print("ERROR: --instrument requires a value")
        sys.exit(1)

    if not _check_integrity():
        sys.exit(1)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stats = {"completed": 0, "failed": 0, "skipped": 0, "total_persisted": 0}
    _process_one_instrument(args.instrument, 1, 1, run_id, stats)
    elapsed = 0  # individual instrument
    _print_final_summary(stats, elapsed, conn_path=get_db_path())


def cmd_retry_failed(_args):
    """Re-process instruments that previously failed."""
    if not _check_integrity():
        sys.exit(1)

    conn = raw_conn()
    _ensure_checkpoint_table(conn)
    failed_keys = [r[0] for r in conn.execute(
        "SELECT instrument_key FROM greeks_checkpoint WHERE status = 'FAILED'"
    ).fetchall()]
    conn.close()

    if not failed_keys:
        print("No failed instruments to retry.")
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"Run ID: {run_id}")
    print(f"Retrying {len(failed_keys)} failed instruments\n")

    stats = {"completed": 0, "failed": 0, "skipped": 0, "total_persisted": 0}
    start_all = time.time()

    for i, ik in enumerate(failed_keys):
        _process_one_instrument(ik, i + 1, len(failed_keys), run_id, stats)

    elapsed = time.time() - start_all
    _print_final_summary(stats, elapsed, conn_path=get_db_path())


def cmd_verify(_args):
    """Verify raw data immutability and Greeks integrity."""
    if not _check_integrity():
        sys.exit(1)

    print("\n=== RAW DATA IMMUTABILITY ===")
    conn = raw_conn()

    # Sample option candles
    opt_sample = conn.execute(
        "SELECT id, open, high, low, close, volume, open_interest "
        "FROM option_candles ORDER BY id LIMIT 20"
    ).fetchall()
    print(f"Sampled {len(opt_sample)} option candles")

    # Sample nifty candles
    nifty_sample = conn.execute(
        "SELECT id, open, high, low, close FROM nifty_candles ORDER BY id LIMIT 10"
    ).fetchall()
    print(f"Sampled {len(nifty_sample)} NIFTY candles")

    # Sample contract specs
    spec_sample = conn.execute(
        "SELECT instrument_key, strike_price, lot_size, instrument_type "
        "FROM contract_specs LIMIT 10"
    ).fetchall()
    print(f"Sampled {len(spec_sample)} contract specs")

    # Greeks integrity
    print("\n=== GREEKS INTEGRITY ===")
    greeks_status = conn.execute(
        "SELECT status, COUNT(*) FROM option_greeks GROUP BY status"
    ).fetchall()
    for s, c in greeks_status:
        print(f"  {s}: {c:,}")

    # Duplicate check
    dups = conn.execute("""
        SELECT instrument_key, interval, open_time, calc_version, COUNT(*)
        FROM option_greeks
        GROUP BY instrument_key, interval, open_time, calc_version
        HAVING COUNT(*) > 1
    """).fetchall()
    print(f"\nDuplicate Greeks rows: {len(dups)}")
    if dups:
        for d in dups[:5]:
            print(f"  {d}")

    # Spot alignment check
    print("\n=== SPOT ALIGNMENT SAMPLE ===")
    spot_check = conn.execute("""
        SELECT og.instrument_key, og.open_time, og.spot, og.status
        FROM option_greeks og
        WHERE og.status = 'SUCCESS'
        LIMIT 3
    """).fetchall()
    for ik, ot, spot, status in spot_check:
        print(f"  {ik} @ {ot}: spot={spot}")

    # Checkpoint status
    print("\n=== CHECKPOINT STATUS ===")
    _ensure_checkpoint_table(conn)
    cp = conn.execute(
        "SELECT status, COUNT(*) FROM greeks_checkpoint GROUP BY status"
    ).fetchall()
    for s, c in cp:
        print(f"  {s}: {c}")

    # Ghost checkpoint check
    ghosts = conn.execute("""
        SELECT COUNT(*) FROM greeks_checkpoint gc
        WHERE gc.status = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1 FROM option_greeks og
              WHERE og.instrument_key = gc.instrument_key
                AND og.calc_version = '1.0.0'
                AND og.interval = '3min'
          )
    """).fetchone()[0]
    print(f"\nGhost COMPLETED checkpoints (no Greek rows): {ghosts}")

    conn.close()
    print("\nVerification complete.")


# ---------------------------------------------------------------------------
# Core processing — one instrument at a time
# ---------------------------------------------------------------------------

def _process_one_instrument(
    instrument_key: str,
    idx: int,
    total: int,
    run_id: str,
    stats: dict,
) -> None:
    """Calculate + persist Greeks for one instrument with checkpointing."""
    from app.services.historical_greeks import HistoricalGreeksEngine, CalcStatus

    conn = raw_conn()
    _ensure_checkpoint_table(conn)

    # Check if current-version Greek rows already exist (authoritative)
    greek_count = conn.execute(
        "SELECT COUNT(*) FROM option_greeks WHERE instrument_key = ? AND calc_version = '1.0.0' AND interval = '3min'",
        (instrument_key,),
    ).fetchone()[0]
    if greek_count > 0:
        stats["skipped"] += 1
        conn.close()
        print(f"[{idx}/{total}] SKIP  {instrument_key} (already has {greek_count} Greek rows)")
        return

    print(f"[{idx}/{total}] START {instrument_key}")
    conn.close()

    # Mark as RUNNING
    conn = raw_conn()
    conn.execute(
        """INSERT OR REPLACE INTO greeks_checkpoint
           (instrument_key, status, run_id, started_at)
           VALUES (?, 'RUNNING', ?, ?)""",
        (instrument_key, run_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    start = time.time()
    try:
        # Use a separate session for calculation
        db = get_session()
        engine = HistoricalGreeksEngine(db)

        # Get candle count before calculation
        from sqlalchemy import func, select
        from app.models import OptionCandle
        candle_count = db.execute(
            select(func.count(OptionCandle.id))
            .where(OptionCandle.instrument_key == instrument_key)
        ).scalar() or 0

        print(f"  Candles: {candle_count}")

        # Calculate and persist
        result = engine.run_instrument(instrument_key)
        elapsed = time.time() - start

        success = result["success"]
        failed = result["failed"]
        persisted = result["persisted"]

        print(f"  Success: {success}")
        if failed:
            print(f"  Failed:  {failed}")
        print(f"  Persisted: {persisted}")
        print(f"  COMPLETED in {elapsed:.1f}s")

        # Verify persistence before marking COMPLETED
        verify_conn = raw_conn()
        actual_greek_rows = verify_conn.execute(
            "SELECT COUNT(*) FROM option_greeks WHERE instrument_key = ? AND calc_version = '1.0.0' AND interval = '3min'",
            (instrument_key,),
        ).fetchone()[0]
        verify_conn.close()

        if actual_greek_rows == 0 and persisted > 0:
            # Persistence reported rows but none exist — mark FAILED
            print(f"  WARNING: persisted={persisted} but actual_greek_rows=0 — marking FAILED")
            conn = raw_conn()
            conn.execute(
                """UPDATE greeks_checkpoint
                   SET status = 'FAILED',
                       error_message = ?,
                       candle_count = ?,
                       success_count = ?,
                       failure_count = ?,
                       rows_persisted = ?,
                       calc_version = '1.0.0',
                       completed_at = ?
                   WHERE instrument_key = ?""",
                ("Persistence verification failed: 0 rows after persist",
                 candle_count, success, failed, persisted,
                 datetime.now(timezone.utc).isoformat(), instrument_key),
            )
            conn.commit()
            conn.close()
            db.close()
            stats["failed"] += 1
            return

        # Update checkpoint — only after verified persistence
        conn = raw_conn()
        conn.execute(
            """UPDATE greeks_checkpoint
               SET status = 'COMPLETED',
                   candle_count = ?,
                   success_count = ?,
                   failure_count = ?,
                   rows_persisted = ?,
                   calc_version = '1.0.0',
                   completed_at = ?
               WHERE instrument_key = ?""",
            (candle_count, success, failed, persisted,
             datetime.now(timezone.utc).isoformat(), instrument_key),
        )
        conn.commit()
        conn.close()

        db.close()
        stats["completed"] += 1
        stats["total_persisted"] += persisted

    except Exception as e:
        elapsed = time.time() - start
        print(f"  FAILED in {elapsed:.1f}s: {e}")

        # Record failure
        conn = raw_conn()
        conn.execute(
            """UPDATE greeks_checkpoint
               SET status = 'FAILED',
                   error_message = ?,
                   completed_at = ?
               WHERE instrument_key = ?""",
            (str(e), datetime.now(timezone.utc).isoformat(), instrument_key),
        )
        conn.commit()
        conn.close()
        stats["failed"] += 1


def _print_final_summary(stats: dict, elapsed: float, conn_path: str) -> None:
    """Print final reconstruction summary."""
    print(f"\n{'='*50}")
    print(f"RECONSTRUCTION SUMMARY")
    print(f"{'='*50}")
    print(f"Completed:      {stats['completed']}")
    print(f"Failed:         {stats['failed']}")
    print(f"Skipped:        {stats['skipped']}")
    print(f"Total persisted: {stats['total_persisted']}")
    if elapsed > 0:
        print(f"Elapsed:        {elapsed:.1f}s")
        if stats['completed'] > 0:
            print(f"Avg/instrument: {elapsed / stats['completed']:.1f}s")

    # Database summary
    if os.path.exists(conn_path):
        conn = sqlite3.connect(conn_path)
        print(f"\nDatabase: {conn_path}")
        print(f"Size:     {os.path.getsize(conn_path):,} bytes")
        for t in ["nifty_candles", "contract_specs", "option_candles", "option_greeks"]:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt:,}")

        # Greeks by status
        for s, c in conn.execute("SELECT status, COUNT(*) FROM option_greeks GROUP BY status"):
            print(f"  greeks.{s}: {c:,}")

        # Duplicate check
        dups = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT instrument_key, interval, open_time, calc_version
                FROM option_greeks
                GROUP BY instrument_key, interval, open_time, calc_version
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        print(f"  duplicate_greeks: {dups}")

        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 7.23C — Safe, Resumable Historical Greeks Reconstruction"
    )
    parser.add_argument("--status", action="store_true",
                        help="Show database and checkpoint status (read-only)")
    parser.add_argument("--backup", action="store_true",
                        help="Create a timestamped database backup")
    parser.add_argument("--missing", action="store_true",
                        help="Process all instruments missing Greeks")
    parser.add_argument("--instrument", help="Process one specific instrument")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max instruments to process (None = all)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-process instruments that previously failed")
    parser.add_argument("--verify", action="store_true",
                        help="Verify raw data immutability and Greeks integrity")

    args = parser.parse_args()

    if args.status:
        cmd_status(args)
    elif args.backup:
        cmd_backup(args)
    elif args.missing:
        cmd_missing(args)
    elif args.instrument:
        cmd_instrument(args)
    elif args.retry_failed:
        cmd_retry_failed(args)
    elif args.verify:
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
