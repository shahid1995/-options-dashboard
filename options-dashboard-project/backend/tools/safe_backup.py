#!/usr/bin/env python3
"""Safe database backup utility — never deletes source, never overwrites existing backups.

Usage:
    python tools/safe_backup.py                    # backup paper_journal.db
    python tools/safe_backup.py paper_journal.db   # backup specific file
    python tools/safe_backup.py /path/to/file.db   # backup arbitrary file
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


BACKUP_DIR = Path(__file__).parent.parent / "backups"

# Tables to verify row counts for
VERIFY_TABLES = [
    "option_candles",
    "option_greeks",
    "nifty_candles",
    "contract_specs",
    "historical_gex",
    "greeks_checkpoint",
]


def safe_backup(source_path: str, prefix: str = "backup") -> dict:
    """Create a timestamped backup of a SQLite database.
    
    Rules:
    - Never deletes the source
    - Never overwrites an existing backup
    - Includes timestamp in filename
    - Verifies the copied database has expected tables
    - Reports important row counts
    - Runs SQLite integrity check on the backup
    
    Returns a dict with backup results.
    """
    source = Path(source_path).resolve()
    if not source.exists():
        return {"success": False, "error": f"Source not found: {source}"}

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{source.stem}_{prefix}_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name

    # Never overwrite an existing backup
    if backup_path.exists():
        return {"success": False, "error": f"Backup already exists: {backup_path}"}

    # Copy
    shutil.copy2(str(source), str(backup_path))

    # Verify backup exists and is non-zero
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        return {"success": False, "error": "Backup is empty or missing"}

    # Open backup read-only and verify
    conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    c = conn.cursor()

    # Integrity check
    integrity = c.execute("PRAGMA integrity_check").fetchone()[0]

    # Row counts
    row_counts = {}
    for table in VERIFY_TABLES:
        try:
            count = c.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            row_counts[table] = count
        except Exception:
            row_counts[table] = "table not found"

    conn.close()

    return {
        "success": True,
        "source": str(source),
        "source_size": source.stat().st_size,
        "backup": str(backup_path),
        "backup_size": backup_path.stat().st_size,
        "integrity": integrity,
        "row_counts": row_counts,
    }


def main():
    if len(sys.argv) > 1:
        source = sys.argv[1]
    else:
        source = str(Path(__file__).parent.parent / "paper_journal.db")

    result = safe_backup(source)

    if not result["success"]:
        print(f"FAILED: {result['error']}")
        sys.exit(1)

    print(f"Source:    {result['source']} ({result['source_size']:,} bytes)")
    print(f"Backup:    {result['backup']} ({result['backup_size']:,} bytes)")
    print(f"Integrity: {result['integrity']}")
    print(f"Row counts:")
    for table, count in result["row_counts"].items():
        print(f"  {table}: {count}")
    print("OK")


if __name__ == "__main__":
    main()
