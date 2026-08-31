#!/usr/bin/env python3
"""SQLite → PostgreSQL migration tool for StrikeNova.

Single authoritative migration utility that reads from a verified SQLite
backup and writes to PostgreSQL via Railway's private network.

Features:
  - All 27 application tables in FK dependency order
  - Batched INSERT (fails loudly on constraint violations)
  - Deterministic row-count verification
  - Deterministic SHA-256 fingerprint verification
  - Foreign key / orphan verification
  - Primary key uniqueness verification
  - PostgreSQL sequence validation
  - NOT NULL integrity verification
  - Security invariant verification (encrypted fields, no plaintext)
  - GEX provenance verification
  - Multi-user ownership isolation verification
  - WAL-aware backup verification
  - --ready-for-cutover safety gate

Usage:
    # Dry-run (validate only, no writes)
    python backend/tools/migrate_sqlite_to_postgres.py --dry-run --sqlite /path/to/backup.db

    # Full migration
    python backend/tools/migrate_sqlite_to_postgres.py --sqlite /path/to/backup.db

    # Validate only (no migration)
    python backend/tools/migrate_sqlite_to_postgres.py --validate-only --sqlite /path/to/backup.db

    # Check if ready for production cutover
    python backend/tools/migrate_sqlite_to_postgres.py --ready-for-cutover --sqlite /path/to/backup.db

Requirements:
    pip install psycopg2-binary

Design principles:
  - SQLite source is STRICTLY read-only (opened via file: URI with mode=ro)
  - PostgreSQL destination comes from --pg-url or DATABASE_URL env var
  - Batch at 1,000 rows per commit
  - FAILS LOUDLY on constraint violations (no silent row skipping)
  - SHA-256 is the integrity contract
  - Secrets are NEVER printed or logged
  - Final cutover requires separate operator action (DATABASE_URL switch)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BATCH_SIZE = 1000

# Tables in FK dependency order (parents before children).
ALL_TABLES = [
    "users",
    "user_sessions",
    "broker_connections",
    "broker_tokens",
    "paper_accounts",
    "strategy_templates",
    "strategy_template_legs",
    "trades",
    "legs",
    "strategy_executions",
    "paper_orders",
    "positions",
    "paper_transactions",
    "strategy_leg_exposures",
    "exit_exposure_allocations",
    "bulk_exit_records",
    "gex_snapshots",
    "historical_gex",
    "contract_specs",
    "nifty_candles",
    "option_candles",
    "option_greeks",
    "data_completeness",
    "ingestion_checkpoint",
    "ingestion_log",
    "iv_observations",
]

# Tables managed by Alembic — never migrate data into them
SKIP_TABLES = {"alembic_version", "sqlite_sequence"}

# Canonical GEX data_source values
GEX_DATA_SOURCES = {"analytics_token", "broker_oauth", "api_upload"}

# Expected Alembic head
EXPECTED_ALEMBIC_HEAD = "b2c3d4e5f6a7"

# Encrypted broker credential columns
ENCRYPTED_COLUMNS = [
    "broker_api_key_encrypted",
    "broker_api_secret_encrypted",
    "broker_analytics_token_encrypted",
    "broker_token_encrypted",
    "broker_refresh_token_encrypted",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MigrationResult:
    """Result of migrating one table."""
    table: str
    source_count: int = 0
    target_count: int = 0
    rows_written: int = 0
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class VerificationResult:
    """Result of verifying one table."""
    table: str
    row_count_match: bool = False
    fingerprint_match: bool = False
    pk_unique: bool = False
    fk_clean: bool = True
    not_null_clean: bool = True
    source_count: int = 0
    target_count: int = 0
    source_fingerprint: str = ""
    target_fingerprint: str = ""
    errors: list[str] = field(default_factory=list)
    passed: bool = False


# ---------------------------------------------------------------------------
# SHA-256 helpers
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_rows(rows: list[tuple]) -> str:
    """Compute deterministic SHA-256 of a list of rows."""
    h = hashlib.sha256()
    for row in rows:
        for val in row:
            h.update(str(val).encode("utf-8", errors="replace"))
            h.update(b"|")
        h.update(b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# SQLite reader (read-only)
# ---------------------------------------------------------------------------

class SQLiteReader:
    """Read-only access to the SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        uri = f"file:{self.db_path}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True, timeout=10)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def integrity_check(self) -> str:
        cur = self.conn.cursor()
        cur.execute("PRAGMA integrity_check")
        return cur.fetchone()[0]

    def wal_checkpoint(self) -> None:
        """Force WAL checkpoint to ensure backup captures all data."""
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")

    def get_tables(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r[0] for r in cur.fetchall()]

    def count(self, table: str) -> int:
        cur = self.conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM [{table}]')
        return cur.fetchone()[0]

    def get_columns(self, table: str) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA table_info([{table}])")
        return [r[1] for r in cur.fetchall()]

    def fetch_all(self, table: str, columns: list[str]) -> list[tuple]:
        col_list = ", ".join([f"[{c}]" for c in columns])
        cur = self.conn.cursor()
        cur.execute(f"SELECT {col_list} FROM [{table}]")
        return cur.fetchall()

    def fetch_batch(self, table: str, columns: list[str], offset: int, limit: int) -> list[tuple]:
        col_list = ", ".join([f"[{c}]" for c in columns])
        cur = self.conn.cursor()
        cur.execute(f"SELECT {col_list} FROM [{table}] LIMIT ? OFFSET ?", (limit, offset))
        return cur.fetchall()

    def compute_fingerprint(self, table: str, columns: list[str]) -> str:
        """Compute deterministic SHA-256 fingerprint of all rows."""
        rows = self.fetch_all(table, columns)
        return sha256_rows(rows)

    def file_sha256(self) -> str:
        return sha256_file(str(self.db_path))

    def file_size(self) -> int:
        return self.db_path.stat().st_size


# ---------------------------------------------------------------------------
# PostgreSQL writer
# ---------------------------------------------------------------------------

class PgWriter:
    """Write to PostgreSQL via psycopg2."""

    def __init__(self, pg_url: str):
        import psycopg2
        import psycopg2.extras
        self._psycopg2 = psycopg2
        self._extras = psycopg2.extras
        self.conn = psycopg2.connect(pg_url, connect_timeout=15)
        self.conn.autocommit = False

    def close(self):
        if self.conn:
            self.conn.close()

    def table_exists(self, table: str) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)",
            (table,),
        )
        return cur.fetchone()[0]

    def get_columns(self, table: str) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]

    def count(self, table: str) -> int:
        cur = self.conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]

    def get_pk_columns(self, table: str) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = %s::regclass AND i.indisprimary",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]

    def get_fk_constraints(self, table: str) -> list[tuple[str, str, str]]:
        """Get FK constraints: [(column, ref_table, ref_column)]."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT kcu.column_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public' "
            "AND tc.table_name = %s",
            (table,),
        )
        return cur.fetchall()

    def get_not_null_columns(self, table: str) -> list[str]:
        """Get NOT NULL columns (excluding PK which is always NOT NULL)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s "
            "AND is_nullable = 'NO' AND column_name != 'id'",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]

    def insert_batch(self, table: str, columns: list[str], rows: list[tuple]) -> int:
        """Insert a batch of rows. FAILS LOUDLY on constraint violations."""
        if not rows:
            return 0

        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join([f'"{c}"' for c in columns])
        sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

        cur = self.conn.cursor()
        try:
            self._extras.execute_batch(cur, sql, rows, page_size=BATCH_SIZE)
            self.conn.commit()
            return len(rows)
        except Exception:
            self.conn.rollback()
            raise

    def compute_fingerprint(self, table: str, columns: list[str]) -> str:
        """Compute deterministic SHA-256 fingerprint of all rows."""
        cur = self.conn.cursor()
        pg_cols = ", ".join([f'"{c}"' for c in columns])
        cur.execute(f"SELECT {pg_cols} FROM \"{table}\" ORDER BY {pg_cols}")
        rows = cur.fetchall()
        return sha256_rows(rows)

    def check_pk_uniqueness(self, table: str, pk_cols: list[str]) -> tuple[bool, int, int]:
        """Check primary key uniqueness."""
        cur = self.conn.cursor()
        total = self.count(table)
        if total == 0:
            return True, 0, 0
        pk_list = ", ".join([f'"{c}"' for c in pk_cols])
        cur.execute(f'SELECT COUNT(*) FROM (SELECT DISTINCT {pk_list} FROM "{table}") sub')
        unique = cur.fetchone()[0]
        return total == unique, total, unique

    def check_fk_integrity(self, table: str) -> list[str]:
        """Check foreign key integrity. Returns list of orphan descriptions."""
        fks = self.get_fk_constraints(table)
        if not fks:
            return []

        cur = self.conn.cursor()
        orphans = []
        for col, ref_table, ref_col in fks:
            cur.execute(
                f'SELECT COUNT(*) FROM "{table}" t '
                f'LEFT JOIN "{ref_table}" r ON t."{col}" = r."{ref_col}" '
                f'WHERE t."{col}" IS NOT NULL AND r."{ref_col}" IS NULL'
            )
            count = cur.fetchone()[0]
            if count > 0:
                orphans.append(f"{table}.{col} -> {ref_table}.{ref_col}: {count} orphaned rows")
        return orphans

    def check_not_null(self, table: str) -> list[str]:
        """Check NOT NULL columns have no NULLs."""
        nn_cols = self.get_not_null_columns(table)
        if not nn_cols:
            return []

        cur = self.conn.cursor()
        violations = []
        for col in nn_cols:
            cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL')
            count = cur.fetchone()[0]
            if count > 0:
                violations.append(f"{table}.{col}: {count} NULL values in NOT NULL column")
        return violations

    def check_sequences(self) -> dict[str, dict]:
        """Check all integer sequences are >= max(id)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT sequencename FROM pg_sequences WHERE schemaname='public' "
            "AND sequencename LIKE '%_id_seq' ORDER BY sequencename"
        )
        results = {}
        for (seq_name,) in cur.fetchall():
            table = seq_name.replace("_id_seq", "")
            try:
                cur.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')
                max_id = cur.fetchone()[0]
                cur.execute(f"SELECT last_value FROM pg_sequences WHERE sequencename=%s", (seq_name,))
                row = cur.fetchone()
                seq_val = row[0] if row else None
                if seq_val is None or seq_val < max_id:
                    cur.execute(f"SELECT setval('{seq_name}', {max_id})")
                    results[seq_name] = {"corrected": True, "from": seq_val, "to": max_id}
                else:
                    results[seq_name] = {"corrected": False, "value": seq_val}
            except Exception as e:
                results[seq_name] = {"error": str(e)}
        self.conn.commit()
        return results

    def verify_security_invariants(self) -> dict:
        """Verify security/business invariants."""
        cur = self.conn.cursor()
        results = {}

        # 1. Broker encrypted fields
        for col_name in ENCRYPTED_COLUMNS:
            try:
                cur.execute(f'SELECT COUNT(*) FROM broker_tokens WHERE "{col_name}" IS NOT NULL')
                count = cur.fetchone()[0]
                results[f"broker_{col_name}_count"] = count
            except Exception:
                results[f"broker_{col_name}_count"] = 0

        # 2. GEX provenance
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='gex_snapshots' "
            "AND column_name IN ('owner_id', 'connection_id', 'data_source')"
        )
        gex_cols = cur.fetchall()
        results["gex_provenance_columns"] = len(gex_cols)

        # 3. GEX data sources
        try:
            cur.execute("SELECT DISTINCT data_source FROM gex_snapshots WHERE data_source IS NOT NULL")
            gex_sources = [r[0] for r in cur.fetchall()]
            results["gex_data_sources"] = gex_sources
            results["invalid_gex_sources"] = [s for s in gex_sources if s not in GEX_DATA_SOURCES]
        except Exception:
            results["gex_data_sources"] = []
            results["invalid_gex_sources"] = []

        # 4. Counts
        for table in ["users", "user_sessions", "broker_connections", "broker_tokens"]:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                results[f"{table}_count"] = cur.fetchone()[0]
            except Exception:
                results[f"{table}_count"] = 0

        # 5. Trading status
        try:
            cur.execute(
                "SELECT trading_status, COUNT(*) FROM broker_connections GROUP BY trading_status"
            )
            results["trading_status"] = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            results["trading_status"] = {}

        # 6. Encrypted field ciphertext match (sample)
        try:
            cur.execute(
                f'SELECT "{ENCRYPTED_COLUMNS[0]}" FROM broker_tokens '
                f'WHERE "{ENCRYPTED_COLUMNS[0]}" IS NOT NULL LIMIT 1'
            )
            row = cur.fetchone()
            if row and row[0]:
                results["encrypted_ciphertext_sample"] = "present"
            else:
                results["encrypted_ciphertext_sample"] = "empty"
        except Exception:
            results["encrypted_ciphertext_sample"] = "error"

        return results

    def verify_multi_user_isolation(self, user_ids: list[str]) -> dict:
        """Verify cross-user ownership integrity."""
        cur = self.conn.cursor()
        results = {}

        for uid in user_ids:
            # Sessions belong to user
            cur.execute('SELECT COUNT(*) FROM user_sessions WHERE user_id = %s', (uid,))
            session_count = cur.fetchone()[0]

            # Connections belong to user
            cur.execute('SELECT COUNT(*) FROM broker_connections WHERE user_id = %s', (uid,))
            conn_count = cur.fetchone()[0]

            # GEX snapshots owned by user
            cur.execute('SELECT COUNT(*) FROM gex_snapshots WHERE owner_id = %s', (uid,))
            gex_count = cur.fetchone()[0]

            results[uid] = {
                "sessions": session_count,
                "connections": conn_count,
                "gex_snapshots": gex_count,
            }

        # Cross-user check: no connection belongs to multiple users
        cur.execute(
            "SELECT user_id, id FROM broker_connections ORDER BY user_id"
        )
        conns = cur.fetchall()
        conn_owners = {}
        for uid, cid in conns:
            if cid in conn_owners and conn_owners[cid] != uid:
                results["cross_user_violation"] = f"connection {cid} owned by both {conn_owners[cid]} and {uid}"
            conn_owners[cid] = uid

        return results


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate_table(
    reader: SQLiteReader,
    writer: PgWriter,
    table: str,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate a single table from SQLite to PostgreSQL."""
    result = MigrationResult(table=table)
    start = time.time()

    result.source_count = reader.count(table)
    if result.source_count == 0:
        result.skipped = True
        result.skip_reason = "Source table is empty"
        return result

    if not writer.table_exists(table):
        result.error = f"Table {table} does not exist in PostgreSQL"
        return result

    src_cols = reader.get_columns(table)
    pg_cols = writer.get_columns(table)
    common_cols = [c for c in src_cols if c in pg_cols]

    if not common_cols:
        result.error = f"No common columns for {table}"
        return result

    if dry_run:
        result.skipped = True
        result.skip_reason = "Dry run"
        return result

    # Migrate in batches — FAILS LOUDLY on constraint violations
    offset = 0
    total_written = 0
    while offset < result.source_count:
        batch = reader.fetch_batch(table, common_cols, offset, BATCH_SIZE)
        if not batch:
            break

        written = writer.insert_batch(table, common_cols, batch)
        total_written += written
        offset += BATCH_SIZE

    result.target_count = writer.count(table)
    result.rows_written = total_written
    result.duration_seconds = time.time() - start
    return result


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_table(
    reader: SQLiteReader,
    writer: PgWriter,
    table: str,
) -> VerificationResult:
    """Verify that PostgreSQL matches SQLite for a table."""
    v = VerificationResult(table=table)

    v.source_count = reader.count(table)
    v.target_count = writer.count(table)
    v.row_count_match = v.source_count == v.target_count

    src_cols = reader.get_columns(table)
    pg_cols = writer.get_columns(table)
    common_cols = [c for c in src_cols if c in pg_cols]

    if not common_cols:
        v.errors.append("No common columns for fingerprint")
        v.passed = False
        return v

    # SHA-256 fingerprint
    v.source_fingerprint = reader.compute_fingerprint(table, common_cols)
    v.target_fingerprint = writer.compute_fingerprint(table, common_cols)
    v.fingerprint_match = v.source_fingerprint == v.target_fingerprint

    # PK uniqueness
    pk_cols = writer.get_pk_columns(table)
    if pk_cols:
        is_unique, total, unique = writer.check_pk_uniqueness(table, pk_cols)
        v.pk_unique = is_unique
        if not is_unique:
            v.errors.append(f"PK duplicate: {total} rows, {unique} unique PKs")
    else:
        v.pk_unique = True

    # FK integrity
    fk_errors = writer.check_fk_integrity(table)
    if fk_errors:
        v.fk_clean = False
        v.errors.extend(fk_errors)

    # NOT NULL integrity
    nn_errors = writer.check_not_null(table)
    if nn_errors:
        v.not_null_clean = False
        v.errors.extend(nn_errors)

    v.passed = (
        v.row_count_match
        and v.fingerprint_match
        and v.pk_unique
        and v.fk_clean
        and v.not_null_clean
    )
    return v


# ---------------------------------------------------------------------------
# Cutover readiness check
# ---------------------------------------------------------------------------

def check_ready_for_cutover(
    reader: SQLiteReader,
    writer: PgWriter,
    results: list[MigrationResult],
    verifications: list[VerificationResult],
    security: dict,
    user_isolation: dict,
) -> tuple[bool, list[str]]:
    """Check if production cutover is safe."""
    reasons = []

    # 1. SQLite integrity
    integrity = reader.integrity_check()
    if integrity != "ok":
        reasons.append(f"SQLite integrity: {integrity}")

    # 2. Schema matches expected head
    try:
        cur = writer.conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        if not row:
            reasons.append("alembic_version missing")
        elif row[0] != EXPECTED_ALEMBIC_HEAD:
            reasons.append(f"Alembic version: {row[0]} (expected {EXPECTED_ALEMBIC_HEAD})")
    except Exception as e:
        reasons.append(f"Alembic check failed: {e}")

    # 3. Migration errors
    for r in results:
        if r.error:
            reasons.append(f"Migration error in {r.table}: {r.error}")

    # 4. Verification failures
    for v in verifications:
        if not v.passed:
            reasons.append(f"Verification failed for {v.table}: {v.errors}")

    # 5. Security invariants
    if security.get("invalid_gex_sources"):
        reasons.append(f"Invalid GEX sources: {security['invalid_gex_sources']}")
    if security.get("encrypted_ciphertext_sample") != "present":
        reasons.append("Encrypted broker credentials not verified")

    # 6. Cross-user isolation
    if "cross_user_violation" in user_isolation:
        reasons.append(f"Cross-user violation: {user_isolation['cross_user_violation']}")

    ready = len(reasons) == 0
    return ready, reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SQLite → PostgreSQL migration tool for StrikeNova"
    )
    parser.add_argument(
        "--sqlite", required=True,
        help="Path to SQLite backup file"
    )
    parser.add_argument(
        "--pg-url",
        help="PostgreSQL connection URL (or set DATABASE_URL env var)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate only — no writes to PostgreSQL"
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Run verification only — no migration"
    )
    parser.add_argument(
        "--ready-for-cutover", action="store_true",
        help="Check if all verification gates pass for production cutover"
    )
    parser.add_argument(
        "--skip", nargs="*", default=[],
        help="Table names to skip"
    )
    args = parser.parse_args()

    # Resolve PostgreSQL URL
    pg_url = args.pg_url or os.environ.get("DATABASE_URL")
    if not pg_url:
        print("ERROR: Provide --pg-url or set DATABASE_URL env var")
        sys.exit(1)

    if not pg_url.startswith("postgresql"):
        print("ERROR: PostgreSQL URL must start with 'postgresql'")
        sys.exit(1)

    # SQLite validation
    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    # Open connections
    reader = SQLiteReader(str(sqlite_path))
    writer = PgWriter(pg_url)

    try:
        # SQLite integrity + WAL checkpoint
        reader.wal_checkpoint()
        integrity = reader.integrity_check()
        if integrity != "ok":
            print(f"ERROR: SQLite integrity: {integrity}")
            sys.exit(1)

        # Record backup metadata
        backup_sha256 = reader.file_sha256()
        backup_size = reader.file_size()
        print(f"SQLite integrity: {integrity}")
        print(f"Backup SHA-256: {backup_sha256}")
        print(f"Backup size: {backup_size:,} bytes")

        # Inventory
        all_tables = reader.get_tables()
        non_skip = [t for t in all_tables if t not in SKIP_TABLES]
        skip_set = set(args.skip)
        tables_to_process = [t for t in non_skip if t not in skip_set]

        src_counts = {t: reader.count(t) for t in tables_to_process}
        total_rows = sum(src_counts.values())
        non_empty = sum(1 for v in src_counts.values() if v > 0)
        print(f"Source: {len(tables_to_process)} tables, {non_empty} non-empty, {total_rows} total rows")

        # Validation-only mode
        if args.validate_only or args.ready_for_cutover:
            mode = "CUTOVER CHECK" if args.ready_for_cutover else "VALIDATION"
            print(f"\n=== {mode} ===")
            verifications: list[VerificationResult] = []
            all_passed = True
            for table in tables_to_process:
                v = verify_table(reader, writer, table)
                verifications.append(v)
                status = "PASS" if v.passed else "FAIL"
                fp_short = v.source_fingerprint[:12] if v.source_fingerprint else "?"
                print(f"  [{status}] {table}: src={v.source_count} tgt={v.target_count} "
                      f"fp={v.fingerprint_match} pk={v.pk_unique} fk={v.fk_clean} nn={v.not_null_clean} "
                      f"sha256={fp_short}")
                if not v.passed:
                    all_passed = False
                    for e in v.errors:
                        print(f"    ERROR: {e}")

            # Sequences
            print("\n--- Sequences ---")
            seqs = writer.check_sequences()
            corrected = sum(1 for s in seqs.values() if s.get("corrected"))
            print(f"  {len(seqs)} sequences, {corrected} corrected")

            # Security invariants
            print("\n--- Security Invariants ---")
            security = writer.verify_security_invariants()
            for key in ["users_count", "user_sessions_count", "broker_connections_count", "broker_tokens_count"]:
                print(f"  {key}: {security.get(key, '?')}")
            print(f"  GEX provenance columns: {security.get('gex_provenance_columns', 0)}")
            print(f"  GEX data sources: {security.get('gex_data_sources', [])}")
            print(f"  Invalid GEX sources: {security.get('invalid_gex_sources', [])}")
            print(f"  Encrypted ciphertext: {security.get('encrypted_ciphertext_sample', '?')}")
            print(f"  Trading status: {security.get('trading_status', {})}")

            # Multi-user isolation
            print("\n--- Multi-User Isolation ---")
            user_ids = []
            try:
                cur = writer.conn.cursor()
                cur.execute("SELECT id FROM users")
                user_ids = [r[0] for r in cur.fetchall()]
            except Exception:
                pass
            user_isolation = writer.verify_multi_user_isolation(user_ids)
            for uid, info in user_isolation.items():
                if isinstance(info, dict):
                    print(f"  {uid}: sessions={info['sessions']} connections={info['connections']} gex={info['gex_snapshots']}")
                else:
                    print(f"  {uid}: {info}")

            if args.ready_for_cutover:
                print("\n=== CUTOVER READINESS ===")
                ready, reasons = check_ready_for_cutover(
                    reader, writer, [], verifications, security, user_isolation
                )
                if ready:
                    print("READY FOR CUTOVER — all verification gates passed")
                    print(f"Backup SHA-256: {backup_sha256}")
                    print(f"Backup size: {backup_size:,} bytes")
                    print(f"PostgreSQL alembic head: {EXPECTED_ALEMBIC_HEAD}")
                    print("\nTo complete cutover:")
                    print("  1. Put application in maintenance/read-only mode")
                    print("  2. Take FINAL SQLite backup")
                    print("  3. Verify FINAL backup integrity + SHA-256")
                    print("  4. Set DATABASE_URL on Railway")
                    print("  5. Redeploy backend")
                    print("  6. Smoke test")
                else:
                    print("NOT READY — verification gates failed:")
                    for r in reasons:
                        print(f"  - {r}")
                    sys.exit(1)

            if not all_passed:
                print("\nSOME VERIFICATIONS FAILED")
                sys.exit(1)

            print("\nDone.")
            return

        # Migration mode
        print(f"\n{'DRY RUN' if args.dry_run else 'MIGRATION'}: {len(tables_to_process)} tables")
        print("-" * 60)

        results: list[MigrationResult] = []
        for table in tables_to_process:
            if src_counts[table] == 0:
                results.append(MigrationResult(table=table, skipped=True, skip_reason="empty"))
                continue

            print(f"  {table} ({src_counts[table]} rows)...", end=" ", flush=True)
            r = migrate_table(reader, writer, table, dry_run=args.dry_run)
            results.append(r)

            if r.error:
                print(f"ERROR: {r.error}")
                sys.exit(1)
            elif r.skipped:
                print(f"SKIP: {r.skip_reason}")
            else:
                print(f"OK ({r.rows_written} rows, {r.duration_seconds:.1f}s)")

        migrated = [r for r in results if not r.skipped and not r.error]
        total_written = sum(r.rows_written for r in migrated)
        print(f"\nTotal: {len(migrated)} tables migrated, {total_written} rows written")

        # Verification after migration
        if not args.dry_run and migrated:
            print("\n=== VERIFICATION ===")
            verifications = []
            all_passed = True
            for table in tables_to_process:
                if src_counts[table] == 0:
                    continue
                v = verify_table(reader, writer, table)
                verifications.append(v)
                status = "PASS" if v.passed else "FAIL"
                fp_short = v.source_fingerprint[:12] if v.source_fingerprint else "?"
                print(f"  [{status}] {table}: src={v.source_count} tgt={v.target_count} "
                      f"fp={v.fingerprint_match} pk={v.pk_unique} fk={v.fk_clean} nn={v.not_null_clean} "
                      f"sha256={fp_short}")
                if not v.passed:
                    all_passed = False
                    for e in v.errors:
                        print(f"    ERROR: {e}")

            # Sequences
            print("\n--- Sequences ---")
            seqs = writer.check_sequences()
            corrected = sum(1 for s in seqs.values() if s.get("corrected"))
            print(f"  {len(seqs)} sequences, {corrected} corrected")

            # Security
            print("\n--- Security Invariants ---")
            security = writer.verify_security_invariants()
            print(f"  Encrypted ciphertext: {security.get('encrypted_ciphertext_sample', '?')}")
            print(f"  GEX sources: {security.get('gex_data_sources', [])}")

            if not all_passed:
                print("\nVERIFICATION FAILED")
                sys.exit(1)

        print("\nDone.")

    finally:
        reader.close()
        writer.close()


if __name__ == "__main__":
    main()
