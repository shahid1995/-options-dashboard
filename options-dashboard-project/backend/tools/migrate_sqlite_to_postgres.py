#!/usr/bin/env python3
"""Safe SQLite -> PostgreSQL migration utility for StrikeNova."""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

BATCH_SIZE = 1000
SKIP_TABLES = {"alembic_version", "sqlite_sequence"}
GEX_DATA_SOURCES = {"analytics_token", "broker_oauth", "api_upload"}
ENCRYPTED_COLUMNS = {
    "broker_api_key_encrypted",
    "broker_api_secret_encrypted",
    "broker_analytics_token_encrypted",
    "broker_token_encrypted",
    "broker_refresh_token_encrypted",
}
ALL_TABLES = [
    "users", "user_sessions", "broker_connections", "broker_tokens",
    "paper_accounts", "strategy_templates", "strategy_template_legs",
    "trades", "legs", "strategy_executions", "paper_orders", "positions",
    "paper_transactions", "strategy_leg_exposures", "exit_exposure_allocations",
    "bulk_exit_records", "gex_snapshots", "historical_gex", "contract_specs",
    "nifty_candles", "option_candles", "option_greeks", "data_completeness",
    "ingestion_checkpoint", "ingestion_log", "iv_observations",
]


@dataclass
class MigrationResult:
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


def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.password is None:
            return url
        netloc = f"{parsed.username or ''}:***@{parsed.hostname or ''}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "<redacted database url>"


def storage_safety_ok(source_size: int, target_capacity: int) -> bool:
    return source_size >= 0 and target_capacity > 0 and source_size <= int(target_capacity * 0.8)


def canonical_value(value: Any) -> list[str]:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", "1" if value else "0"]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, Decimal):
        return ["decimal", format(value, "f")]
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, dtime):
        return ["time", value.isoformat()]
    if isinstance(value, bytes):
        return ["bytes", base64.b64encode(value).decode("ascii")]
    return ["str", str(value)]


def _fingerprint_token(value: Any) -> tuple[str, ...]:
    if isinstance(value, bool):
        return ("bool", "1" if value else "0")
    if isinstance(value, int) and value in (0, 1):
        return ("bool", str(value))
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return ("datetime", value.isoformat())
    if isinstance(value, str):
        timestamp_like = len(value) >= 19 and value[4] == "-" and value[7] == "-" and value[10] in {" ", "T"} and value[13] == ":" and value[16] == ":"
        if timestamp_like:
            try:
                parsed = datetime.fromisoformat(value.replace(" ", "T", 1))
            except ValueError:
                pass
            else:
                parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
                return ("datetime", parsed.isoformat())
    return tuple(canonical_value(value))


def _canonical_row(row: Sequence[Any]) -> tuple[tuple[str, ...], ...]:
    return tuple(_fingerprint_token(value) for value in row)


def sha256_rows(rows: Iterable[Sequence[Any]]) -> str:
    ordered = sorted(_canonical_row(row) for row in rows)
    payload = "\n".join("|".join(":".join(part) for part in row) for row in ordered)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_reset_sql(table: str, column: str) -> str:
    return f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), COALESCE((SELECT MAX(\"{column}\") FROM \"{table}\"), 1), true)"


def get_alembic_heads(alembic_dir: str | Path) -> list[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    directory = Path(alembic_dir).resolve()
    config = Config(str(directory.parent / "alembic.ini"))
    config.set_main_option("script_location", str(directory))
    return list(ScriptDirectory.from_config(config).get_heads())


def backup_sqlite(source_path: str, destination_path: str) -> None:
    """Create a transaction-consistent SQLite backup from a writable handle."""
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source), timeout=30) as src:
        integrity = src.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        src.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(str(destination), timeout=30) as dst:
            src.backup(dst)
            dst.commit()
            backup_integrity = dst.execute("PRAGMA quick_check").fetchone()[0]
            if backup_integrity != "ok":
                raise RuntimeError(f"Backup integrity check failed: {backup_integrity}")
    os.chmod(destination, 0o600)


class SQLiteReader:
    """Strictly read-only SQLite access."""
    def __init__(self, db_path: str):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(self.db_path)
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30)
        self.conn.row_factory = sqlite3.Row
    def close(self) -> None:
        self.conn.close()
    def integrity_check(self) -> str:
        return self.conn.execute("PRAGMA quick_check").fetchone()[0]
    def wal_checkpoint(self) -> None:
        raise RuntimeError("WAL checkpoint requires a read-write SQLite connection; use backup_sqlite()")
    def get_tables(self) -> list[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [row[0] for row in rows]
    def get_columns(self, table: str) -> list[str]:
        return [row[1] for row in self.conn.execute(f"PRAGMA table_info([{table}])").fetchall()]
    def get_pk_columns(self, table: str) -> list[str]:
        rows = self.conn.execute(f"PRAGMA table_info([{table}])").fetchall()
        return [row[1] for row in sorted(rows, key=lambda row: row[5]) if row[5] > 0]
    def count(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
    def fetch_all(self, table: str, columns: list[str]) -> list[tuple]:
        cols = ", ".join(f"[{column}]" for column in columns)
        return [tuple(row) for row in self.conn.execute(f"SELECT {cols} FROM [{table}]")]
    def fetch_batch(self, table: str, columns: list[str], offset: int, limit: int) -> list[tuple]:
        cols = ", ".join(f"[{column}]" for column in columns)
        return [tuple(row) for row in self.conn.execute(f"SELECT {cols} FROM [{table}] LIMIT ? OFFSET ?", (limit, offset))]
    def compute_fingerprint(self, table: str, columns: list[str]) -> str:
        return sha256_rows(self.fetch_all(table, columns))
    def file_sha256(self) -> str:
        return sha256_file(str(self.db_path))
    def file_size(self) -> int:
        return self.db_path.stat().st_size


class PgWriter:
    """PostgreSQL writer using psycopg 3; transaction ownership is explicit."""
    def __init__(self, pg_url: str | None = None, connection: Any | None = None, owns_connection: bool = True):
        if connection is None:
            import psycopg
            if pg_url is None:
                raise ValueError("pg_url or connection is required")
            self.conn = psycopg.connect(normalize_url(pg_url), connect_timeout=15)
            self.conn.autocommit = False
            self._owns_connection = True
        else:
            self.conn = connection
            self._owns_connection = owns_connection
    @classmethod
    def from_sqlalchemy_engine(cls, engine):
        return cls(connection=engine.raw_connection(), owns_connection=True)
    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()
    def commit(self) -> None:
        self.conn.commit()
    def rollback(self) -> None:
        self.conn.rollback()
    def table_exists(self, table: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (table,))
            return bool(cur.fetchone()[0])
    def get_columns(self, table: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
            return [row[0] for row in cur.fetchall()]
    def count(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            return int(cur.fetchone()[0])
    def fetch_all(self, table: str, columns: list[str]) -> list[tuple]:
        cols = ", ".join(f'"{column}"' for column in columns)
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT {cols} FROM "{table}"')
            return [tuple(row) for row in cur.fetchall()]
    def get_pk_columns(self, table: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT a.attname, k.ordinality FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ordinality) ON k.attnum=a.attnum WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY k.ordinality", (table,))
            return [row[0] for row in cur.fetchall()]
    def get_fk_constraints(self, table: str) -> list[tuple[str, str, str]]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT kcu.column_name, ccu.table_name, ccu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public' AND tc.table_name=%s", (table,))
            return list(cur.fetchall())
    def get_not_null_columns(self, table: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND is_nullable='NO'", (table,))
            return [row[0] for row in cur.fetchall()]
    def insert_batch(self, table: str, columns: list[str], rows: list[tuple]) -> int:
        if not rows:
            return 0
        cols = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        with self.conn.cursor() as cur:
            cur.executemany(f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})', rows)
        return len(rows)
    def compute_fingerprint(self, table: str, columns: list[str]) -> str:
        return sha256_rows(self.fetch_all(table, columns))
    def check_pk_uniqueness(self, table: str, pk_cols: list[str]) -> tuple[bool, int, int]:
        total = self.count(table)
        if not pk_cols:
            return True, total, total
        cols = ", ".join(f'"{column}"' for column in pk_cols)
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM "{table}") t')
            unique = int(cur.fetchone()[0])
        return total == unique, total, unique
    def check_fk_integrity(self, table: str) -> list[str]:
        errors: list[str] = []
        for column, ref_table, ref_column in self.get_fk_constraints(table):
            with self.conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{table}" t LEFT JOIN "{ref_table}" r ON t."{column}"=r."{ref_column}" WHERE t."{column}" IS NOT NULL AND r."{ref_column}" IS NULL')
                count = int(cur.fetchone()[0])
            if count:
                errors.append(f"{table}.{column} -> {ref_table}.{ref_column}: {count} orphaned rows")
        return errors
    def check_not_null(self, table: str) -> list[str]:
        errors: list[str] = []
        for column in self.get_not_null_columns(table):
            with self.conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL')
                count = int(cur.fetchone()[0])
            if count:
                errors.append(f"{table}.{column}: {count} NULL values")
        return errors
    def get_sequence_info(self) -> list[tuple[str, str, str]]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name, column_name, pg_get_serial_sequence('public.' || table_name, column_name) FROM information_schema.columns WHERE table_schema='public' AND (is_identity='YES' OR column_default LIKE 'nextval(%') ORDER BY table_name, column_name")
            return [(row[0], row[1], row[2]) for row in cur.fetchall() if row[2]]
    def check_sequences(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        with self.conn.cursor() as cur:
            for table, column, sequence_name in self.get_sequence_info():
                cur.execute(f'SELECT COALESCE(MAX("{column}"), 0) FROM "{table}"')
                max_value = int(cur.fetchone()[0] or 0)
                cur.execute("SELECT last_value FROM pg_sequences WHERE schemaname='public' AND sequencename=%s", (sequence_name.split(".")[-1],))
                row = cur.fetchone()
                sequence_value = int(row[0]) if row and row[0] is not None else 0
                results[sequence_name] = {"table": table, "column": column, "value": sequence_value, "max": max_value, "ok": sequence_value >= max_value}
        return results
    def verify_security_invariants(self) -> dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users"); users = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM user_sessions"); sessions = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM broker_connections"); connections = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM broker_tokens"); broker_tokens = int(cur.fetchone()[0])
            cur.execute("SELECT DISTINCT data_source FROM gex_snapshots WHERE data_source IS NOT NULL ORDER BY data_source")
            sources = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT COUNT(*) FROM gex_snapshots WHERE data_source IN ('analytics_token','broker_oauth') AND connection_id IS NULL")
            missing_connection = int(cur.fetchone()[0])
            cur.execute("SELECT trading_status, COUNT(*) FROM broker_connections GROUP BY trading_status")
            trading = {row[0]: int(row[1]) for row in cur.fetchall()}
        return {"users_count": users, "user_sessions_count": sessions, "broker_connections_count": connections, "broker_tokens_count": broker_tokens, "gex_data_sources": sources, "invalid_gex_sources": [source for source in sources if source not in GEX_DATA_SOURCES], "gex_missing_connection_provenance": missing_connection, "trading_status": trading}
    def verify_multi_user_isolation(self, user_ids: list[str]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        with self.conn.cursor() as cur:
            for user_id in user_ids:
                cur.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id=%s", (user_id,)); sessions = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM broker_connections WHERE user_id=%s", (user_id,)); connections = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM gex_snapshots WHERE owner_id=%s", (user_id,)); gex = int(cur.fetchone()[0])
                results[user_id] = {"sessions": sessions, "connections": connections, "gex_snapshots": gex}
            # Cross-owner checks are intentionally independent of the supplied user list.
            cur.execute("SELECT COUNT(*) FROM user_sessions s JOIN broker_connections b ON s.broker_connection_id=b.id WHERE s.broker_connection_id IS NOT NULL AND s.user_id <> b.user_id")
            session_owner_mismatch = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM gex_snapshots g JOIN broker_connections b ON g.connection_id=b.id WHERE g.connection_id IS NOT NULL AND g.owner_id IS NOT NULL AND g.owner_id <> b.user_id")
            gex_owner_mismatch = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM broker_connections b LEFT JOIN users u ON b.user_id=u.id WHERE u.id IS NULL")
            connection_owner_missing = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM gex_snapshots g LEFT JOIN users u ON g.owner_id=u.id WHERE g.owner_id IS NOT NULL AND u.id IS NULL")
            gex_owner_missing = int(cur.fetchone()[0])
        violations = session_owner_mismatch + gex_owner_mismatch + connection_owner_missing + gex_owner_missing
        results["cross_user_violation"] = violations
        results["cross_user_violation_details"] = {"session_broker_owner_mismatch": session_owner_mismatch, "gex_connection_owner_mismatch": gex_owner_mismatch, "broker_connection_missing_user": connection_owner_missing, "gex_snapshot_missing_owner": gex_owner_missing}
        return results


def _order_table_names(metadata, names: set[str] | None = None) -> list[str]:
    selected = {table_name: table for table_name, table in metadata.tables.items() if table_name not in SKIP_TABLES and (names is None or table_name in names)}
    dependencies: dict[str, set[str]] = {table_name: set() for table_name in selected}
    for table_name, table in selected.items():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in selected and parent != table_name:
                dependencies[table_name].add(parent)
    order: list[str] = []
    while dependencies:
        ready = sorted(table_name for table_name, parents in dependencies.items() if not parents)
        if not ready:
            raise RuntimeError("dependency cycle detected in migration tables")
        order.extend(ready)
        for table_name in ready: dependencies.pop(table_name, None)
        for parents in dependencies.values(): parents.difference_update(ready)
    return order


def get_table_order(metadata) -> list[str]:
    return _order_table_names(metadata)


def assert_schema_compatible(source_metadata, target_metadata) -> None:
    source_tables = {name for name in source_metadata.tables if name not in SKIP_TABLES}
    target_tables = {name for name in target_metadata.tables if name not in SKIP_TABLES}
    missing = sorted(source_tables - target_tables)
    if missing:
        raise ValueError("tables missing from target: " + ", ".join(missing))
    for table_name in sorted(source_tables):
        source_columns = set(source_metadata.tables[table_name].columns.keys())
        target_columns = set(target_metadata.tables[table_name].columns.keys())
        missing_columns = sorted(source_columns - target_columns)
        if missing_columns:
            raise ValueError(f"columns missing from target for {table_name}: " + ", ".join(missing_columns))


def assert_target_empty(writer: PgWriter, tables: Sequence[str]) -> None:
    non_empty = [(table, writer.count(table)) for table in tables if writer.count(table)]
    if non_empty:
        raise RuntimeError("PostgreSQL target is not empty: " + ", ".join(f"{table}={count}" for table, count in non_empty))


def migrate_table(reader: SQLiteReader, writer: PgWriter, table: str, dry_run: bool = False) -> MigrationResult:
    result = MigrationResult(table=table); started = time.monotonic(); result.source_count = reader.count(table)
    if result.source_count == 0:
        result.skipped = True; result.skip_reason = "empty source table"; return result
    if not writer.table_exists(table):
        result.error = f"Table {table} does not exist in PostgreSQL"; return result
    source_columns = reader.get_columns(table); target_columns = writer.get_columns(table)
    common_columns = [column for column in source_columns if column in target_columns]
    if not common_columns:
        result.error = f"No common columns for {table}"; return result
    if dry_run:
        result.skipped = True; result.skip_reason = "dry run"; return result
    offset = 0
    while offset < result.source_count:
        batch = reader.fetch_batch(table, common_columns, offset, BATCH_SIZE)
        if not batch: break
        result.rows_written += writer.insert_batch(table, common_columns, batch); offset += len(batch)
    result.target_count = writer.count(table); result.duration_seconds = time.monotonic() - started; return result


def _repair_sequences_with_sqlalchemy(connection) -> None:
    from sqlalchemy import text
    sequence_rows = connection.execute(text("SELECT table_name, column_name, pg_get_serial_sequence('public.' || table_name, column_name) FROM information_schema.columns WHERE table_schema='public' AND (is_identity='YES' OR column_default LIKE 'nextval(%')")).fetchall()
    for table, column, sequence_name in sequence_rows:
        if not sequence_name: continue
        max_value = connection.execute(text(f'SELECT MAX("{column}") FROM "{table}"')).scalar()
        if max_value is None: continue
        current = connection.execute(text("SELECT last_value FROM pg_sequences WHERE schemaname='public' AND sequencename=:name"), {"name": sequence_name.split(".")[-1]}).scalar()
        if current is None or int(current) < int(max_value):
            connection.execute(text("SELECT setval(:sequence_name, :max_value, true)"), {"sequence_name": sequence_name, "max_value": int(max_value)})


def migrate_database(sqlite_engine, postgres_engine, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    from sqlalchemy import MetaData, select
    source_metadata = MetaData(); target_metadata = MetaData()
    source_metadata.reflect(bind=sqlite_engine); target_metadata.reflect(bind=postgres_engine)
    assert_schema_compatible(source_metadata, target_metadata)
    source_names = {name for name in source_metadata.tables if name not in SKIP_TABLES}
    table_order = _order_table_names(target_metadata, source_names)
    source_conn = sqlite_engine.connect(); target_conn = postgres_engine.connect(); transaction = target_conn.begin()
    try:
        for table_name in table_order:
            source_table = source_metadata.tables[table_name]; target_table = target_metadata.tables[table_name]
            common_columns = [column.name for column in source_table.columns if column.name in target_table.columns]
            if not common_columns: continue
            result = source_conn.execute(select(*[source_table.c[column] for column in common_columns]))
            while True:
                rows = result.fetchmany(batch_size)
                if not rows: break
                target_conn.execute(target_table.insert(), [dict(zip(common_columns, row)) for row in rows])
        _repair_sequences_with_sqlalchemy(target_conn); transaction.commit()
    except Exception:
        transaction.rollback(); raise
    finally:
        source_conn.close(); target_conn.close()
    return verify_databases(sqlite_engine, postgres_engine)


def verify_table(reader: SQLiteReader, writer: PgWriter, table: str) -> VerificationResult:
    result = VerificationResult(table=table); result.source_count = reader.count(table); result.target_count = writer.count(table); result.row_count_match = result.source_count == result.target_count
    common = [column for column in reader.get_columns(table) if column in writer.get_columns(table)]
    if not common:
        result.errors.append("no common columns"); return result
    result.source_fingerprint = reader.compute_fingerprint(table, common); result.target_fingerprint = writer.compute_fingerprint(table, common); result.fingerprint_match = result.source_fingerprint == result.target_fingerprint
    result.pk_unique = writer.check_pk_uniqueness(table, writer.get_pk_columns(table))[0]
    fk_errors = writer.check_fk_integrity(table); result.fk_clean = not fk_errors; result.errors.extend(fk_errors)
    not_null_errors = writer.check_not_null(table); result.not_null_clean = not not_null_errors; result.errors.extend(not_null_errors)
    if not result.row_count_match: result.errors.append(f"row count mismatch: source={result.source_count}, target={result.target_count}")
    if not result.fingerprint_match: result.errors.append("SHA-256 fingerprint mismatch")
    if not result.pk_unique: result.errors.append("primary key uniqueness check failed")
    result.passed = result.row_count_match and result.fingerprint_match and result.pk_unique and result.fk_clean and result.not_null_clean
    return result


def _missing_target_verifications(writer: PgWriter, tables: Sequence[str]) -> list[VerificationResult]:
    missing: list[VerificationResult] = []
    for table in tables:
        if not writer.table_exists(table):
            missing.append(VerificationResult(table=table, errors=["table missing from PostgreSQL target"], passed=False))
    return missing


def verify_databases(sqlite_engine, postgres_engine) -> dict[str, Any]:
    source_path = sqlite_engine.url.database
    if not source_path or source_path == ":memory:":
        raise ValueError("verify_databases requires a file-backed SQLite database")
    reader = SQLiteReader(str(source_path)); writer = PgWriter.from_sqlalchemy_engine(postgres_engine)
    try:
        tables = [table for table in reader.get_tables() if table not in SKIP_TABLES]
        missing_verifications = _missing_target_verifications(writer, tables)
        existing_tables = [table for table in tables if writer.table_exists(table)]
        verifications = [verify_table(reader, writer, table) for table in existing_tables] + missing_verifications
        sequences = writer.check_sequences(); security = writer.verify_security_invariants()
        user_ids: list[str] = []
        if writer.table_exists("users"):
            with writer.conn.cursor() as cur:
                cur.execute("SELECT id FROM users ORDER BY id"); user_ids = [row[0] for row in cur.fetchall()]
        isolation = writer.verify_multi_user_isolation(user_ids)
        return {
            "ok": all(item.passed for item in verifications) and all(item.get("ok", False) for item in sequences.values()) and not security.get("invalid_gex_sources") and int(security.get("gex_missing_connection_provenance", 0)) == 0 and isolation.get("cross_user_violation", 0) == 0,
            "tables": {item.table: {"row_count": item.target_count, "source_count": item.source_count, "fingerprint_match": item.fingerprint_match, "source_fingerprint": item.source_fingerprint, "target_fingerprint": item.target_fingerprint, "pk_unique": item.pk_unique, "fk_clean": item.fk_clean, "not_null_clean": item.not_null_clean, "errors": item.errors, "passed": item.passed} for item in verifications},
            "sequences": sequences, "security": security, "isolation": isolation,
        }
    finally:
        reader.close(); writer.close()


def check_ready_for_cutover(reader: SQLiteReader, writer: PgWriter, results: list[MigrationResult], verifications: list[VerificationResult], security: dict[str, Any], user_isolation: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if reader.integrity_check() != "ok": reasons.append("SQLite integrity check failed")
    heads = get_alembic_heads(Path(__file__).resolve().parents[1] / "alembic")
    if len(heads) != 1: reasons.append(f"Alembic has {len(heads)} heads")
    else:
        try:
            with writer.conn.cursor() as cur:
                cur.execute("SELECT version_num FROM alembic_version"); row = cur.fetchone()
            if not row or row[0] != heads[0]: reasons.append("Alembic database head does not match repository head")
        except Exception: reasons.append("Alembic head could not be verified")
    for result in results:
        if result.error: reasons.append(f"Migration error in {result.table}")
    for verification in verifications:
        if not verification.passed: reasons.append(f"Verification failed for {verification.table}")
    if security.get("invalid_gex_sources"): reasons.append("Invalid GEX data_source values")
    if security.get("gex_missing_connection_provenance"): reasons.append("User-owned GEX snapshot is missing connection provenance")
    if user_isolation.get("cross_user_violation", 0): reasons.append("Cross-user ownership violation")
    if not all(item.get("ok", False) for item in writer.check_sequences().values()): reasons.append("PostgreSQL sequences are behind imported IDs")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe SQLite -> PostgreSQL migration for StrikeNova")
    parser.add_argument("--sqlite", required=True, help="Path to a verified SQLite backup")
    parser.add_argument("--pg-url", help="PostgreSQL URL; defaults to DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without database writes")
    parser.add_argument("--validate-only", action="store_true", help="Verify an already migrated target")
    parser.add_argument("--ready-for-cutover", action="store_true", help="Run readiness checks only")
    args = parser.parse_args()
    pg_url = normalize_url(args.pg_url or os.getenv("DATABASE_URL") or "")
    if not pg_url.startswith("postgresql+psycopg://"):
        print("ERROR: PostgreSQL URL must use the supported psycopg dialect"); return 1
    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite backup not found: {sqlite_path}"); return 1
    reader = SQLiteReader(str(sqlite_path)); writer = PgWriter(pg_url)
    try:
        integrity = reader.integrity_check()
        if integrity != "ok": print(f"ERROR: SQLite integrity: {integrity}"); return 1
        print("SQLite integrity: ok"); print(f"Backup SHA-256: {reader.file_sha256()}"); print(f"Backup size: {reader.file_size():,} bytes")
        if args.dry_run:
            print("DRY RUN: source validated; no PostgreSQL writes performed"); return 0
        tables = [table for table in reader.get_tables() if table not in SKIP_TABLES]
        if args.validate_only or args.ready_for_cutover:
            missing_verifications = _missing_target_verifications(writer, tables)
            existing_tables = [table for table in tables if writer.table_exists(table)]
            verifications = [verify_table(reader, writer, table) for table in existing_tables] + missing_verifications
            security = writer.verify_security_invariants()
            with writer.conn.cursor() as cur:
                cur.execute("SELECT id FROM users ORDER BY id"); user_ids = [row[0] for row in cur.fetchall()]
            isolation = writer.verify_multi_user_isolation(user_ids)
            ready, reasons = check_ready_for_cutover(reader, writer, [], verifications, security, isolation)
            if args.ready_for_cutover:
                print("READY FOR CUTOVER" if ready else "NOT READY FOR CUTOVER")
                for reason in reasons: print(f"- {reason}")
            return 0 if ready else 1
        assert_target_empty(writer, tables)
        from sqlalchemy import create_engine
        source_engine = create_engine(f"sqlite:///{sqlite_path}"); target_engine = create_engine(pg_url)
        try: report = migrate_database(source_engine, target_engine, batch_size=BATCH_SIZE)
        finally: source_engine.dispose(); target_engine.dispose()
        print(f"Migration verification: {'PASS' if report['ok'] else 'FAIL'}")
        return 0 if report["ok"] else 1
    finally:
        reader.close(); writer.close()


if __name__ == "__main__":
    raise SystemExit(main())
