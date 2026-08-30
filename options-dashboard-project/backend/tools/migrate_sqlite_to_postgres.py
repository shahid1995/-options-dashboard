from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.db import normalize_database_url as _normalize_database_url

DEFAULT_BATCH_SIZE = 1000
DEFAULT_TARGET_BUDGET_BYTES = 500 * 1024 * 1024
DEFAULT_SAFETY_THRESHOLD = 0.80
EXCLUDED_TABLES = frozenset({"alembic_version"})


def normalize_url(url: str) -> str:
    return _normalize_database_url(url)


def redact_url(url: str) -> str:
    parsed = make_url(normalize_url(url))
    if parsed.password is None:
        return str(parsed)
    return str(parsed.set(password="***"))


def canonical_value(value: object) -> list[str]:
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
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ["bytes", bytes(value).hex()]
    return [type(value).__name__, str(value)]


def storage_safety_ok(
    estimated_bytes: int,
    budget_bytes: int,
    threshold: float = DEFAULT_SAFETY_THRESHOLD,
) -> bool:
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be > 0 and <= 1")
    return estimated_bytes <= int(budget_bytes * threshold)


def _application_tables(metadata: MetaData) -> dict[str, Table]:
    return {
        name: table
        for name, table in metadata.tables.items()
        if name not in EXCLUDED_TABLES
    }


def get_table_order(metadata: MetaData) -> list[str]:
    tables = _application_tables(metadata)
    dependencies: dict[str, set[str]] = {name: set() for name in tables}

    for name, table in tables.items():
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent in tables and parent != name:
                dependencies[name].add(parent)

    order: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise RuntimeError(f"foreign-key dependency cycle detected: {cycle}")
        order.extend(ready)
        remaining.difference_update(ready)
    return order


def assert_schema_compatible(source: MetaData, target: MetaData) -> None:
    source_tables = _application_tables(source)
    target_tables = _application_tables(target)

    missing_tables = sorted(set(source_tables) - set(target_tables))
    if missing_tables:
        raise ValueError(f"tables missing from target: {missing_tables}")

    for table_name in sorted(source_tables):
        source_columns = set(source_tables[table_name].columns.keys())
        target_columns = set(target_tables[table_name].columns.keys())
        missing_columns = sorted(source_columns - target_columns)
        if missing_columns:
            raise ValueError(
                f"columns missing from target table {table_name}: {missing_columns}"
            )


def backup_sqlite(source_path: str, backup_path: str) -> None:
    source = Path(source_path)
    backup = Path(backup_path)

    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    if backup.exists():
        raise FileExistsError(f"Backup already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)

    source_conn = sqlite3.connect(str(source))
    backup_conn = sqlite3.connect(str(backup))
    try:
        source_conn.backup(backup_conn)
        integrity = backup_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed: {integrity}")
        backup_conn.commit()
    finally:
        backup_conn.close()
        source_conn.close()


def estimate_sqlite_size_bytes(source_path: str) -> int:
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {path}")
    return path.stat().st_size


def _sqlite_path_from_url(source_url: str) -> str:
    parsed = make_url(normalize_url(source_url))
    if parsed.get_backend_name() != "sqlite":
        raise ValueError("source database must use SQLite")
    if parsed.database in (None, "", ":memory:"):
        raise ValueError("source database must be a file-backed SQLite database")
    return parsed.database


def _make_engine(url: str) -> Engine:
    return create_engine(normalize_url(url), pool_pre_ping=True)


def preflight_databases(
    source_url: str,
    target_url: str,
    target_budget_bytes: int = DEFAULT_TARGET_BUDGET_BYTES,
) -> dict:
    source_url = normalize_url(source_url)
    target_url = normalize_url(target_url)

    source_path = _sqlite_path_from_url(source_url)
    target_backend = make_url(target_url).get_backend_name()
    if target_backend != "postgresql":
        raise ValueError("target database must use PostgreSQL")

    estimated_bytes = estimate_sqlite_size_bytes(source_path)
    report: dict = {
        "ok": True,
        "source": redact_url(source_url),
        "target": redact_url(target_url),
        "sqlite_size_bytes": estimated_bytes,
        "target_budget_bytes": target_budget_bytes,
        "safety_threshold": DEFAULT_SAFETY_THRESHOLD,
        "schema_compatible": False,
        "target_accessible": False,
    }

    if not storage_safety_ok(estimated_bytes, target_budget_bytes):
        report["ok"] = False
        report["safety_failure"] = "estimated SQLite size exceeds the 80% target storage safety threshold"
        return report

    source_engine = _make_engine(source_url)
    target_engine = _make_engine(target_url)
    try:
        with source_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        with target_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            report["target_accessible"] = True

        source_metadata = MetaData()
        target_metadata = MetaData()
        source_metadata.reflect(bind=source_engine)
        target_metadata.reflect(bind=target_engine)
        assert_schema_compatible(source_metadata, target_metadata)
        report["schema_compatible"] = True

        source_counts = table_counts(source_engine, source_metadata)
        report["source_row_counts"] = source_counts
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    finally:
        source_engine.dispose()
        target_engine.dispose()

    return report


def sequence_reset_sql(table_name: str, column_name: str) -> str:
    for identifier in (table_name, column_name):
        if not identifier.replace("_", "").isalnum():
            raise ValueError("unsafe SQL identifier")
    return (
        "SELECT setval(pg_get_serial_sequence('"
        + table_name
        + "', '"
        + column_name
        + "'), GREATEST(COALESCE((SELECT MAX("
        + column_name
        + ") FROM "
        + table_name
        + "), 1), 1), true)"
    )


def _integer_pk_columns(table: Table) -> Iterable:
    for column in table.primary_key.columns:
        type_name = str(column.type).upper()
        if "INTEGER" in type_name or "BIGINT" in type_name:
            yield column


def reset_postgres_sequences(engine: Engine, metadata: MetaData) -> None:
    tables = _application_tables(metadata)
    with engine.begin() as connection:
        for table_name in sorted(tables):
            table = tables[table_name]
            for column in _integer_pk_columns(table):
                sequence = connection.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                    {"table_name": table_name, "column_name": column.name},
                ).scalar_one_or_none()
                if not sequence:
                    continue
                max_value = connection.execute(
                    text(f'SELECT MAX("{column.name}") FROM "{table_name}"')
                ).scalar_one_or_none()
                if max_value is None:
                    continue
                connection.execute(
                    text("SELECT setval(CAST(:sequence_name AS regclass), :value, true)"),
                    {"sequence_name": sequence, "value": int(max_value)},
                )


def migrate_database(
    source_engine: Engine,
    target_engine: Engine,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if source_engine.dialect.name != "sqlite":
        raise ValueError("source engine must be SQLite")
    if target_engine.dialect.name != "postgresql":
        raise ValueError("target engine must be PostgreSQL")

    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)
    assert_schema_compatible(source_metadata, target_metadata)
    table_order = get_table_order(source_metadata)

    with target_engine.connect() as connection:
        for table_name in table_order:
            count = connection.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            ).scalar_one()
            if count:
                raise RuntimeError(
                    f"target table {table_name} is not empty; refusing to merge into existing data"
                )

    source_tables = _application_tables(source_metadata)
    target_tables = _application_tables(target_metadata)

    with target_engine.begin() as target_connection:
        with source_engine.connect().execution_options(stream_results=True) as source_connection:
            for table_name in table_order:
                source_table = source_tables[table_name]
                target_table = target_tables[table_name]
                result = source_connection.execute(source_table.select())
                while True:
                    rows = result.fetchmany(batch_size)
                    if not rows:
                        break
                    payload = [dict(row._mapping) for row in rows]
                    target_connection.execute(target_table.insert(), payload)

    reset_postgres_sequences(target_engine, target_metadata)


def table_counts(engine: Engine, metadata: MetaData) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name, table in sorted(_application_tables(metadata).items()):
        with engine.connect() as connection:
            counts[table_name] = int(
                connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
            )
    return counts


def table_fingerprint(engine: Engine, table: Table) -> tuple[int, str]:
    primary_key = list(table.primary_key.columns)
    order_columns = primary_key or list(table.columns)
    digest = hashlib.sha256()
    count = 0

    with engine.connect().execution_options(stream_results=True) as connection:
        result = connection.execute(table.select().order_by(*order_columns))
        for row in result:
            values = [
                [column.name, *canonical_value(row._mapping[column.name])]
                for column in table.columns
            ]
            digest.update(
                (
                    json.dumps(values, separators=(",", ":"), ensure_ascii=False)
                    + "\n"
                ).encode("utf-8")
            )
            count += 1

    return count, digest.hexdigest()


def verify_databases(source_engine: Engine, target_engine: Engine) -> dict:
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)
    assert_schema_compatible(source_metadata, target_metadata)

    source_tables = _application_tables(source_metadata)
    target_tables = _application_tables(target_metadata)
    report: dict = {"ok": True, "tables": {}}

    for table_name in sorted(source_tables):
        source_count, source_hash = table_fingerprint(source_engine, source_tables[table_name])
        target_count, target_hash = table_fingerprint(target_engine, target_tables[table_name])
        match = source_count == target_count and source_hash == target_hash
        report["tables"][table_name] = {
            "source_row_count": source_count,
            "row_count": target_count,
            "source_fingerprint": source_hash,
            "target_fingerprint": target_hash,
            "match": match,
        }
        report["ok"] = bool(report["ok"] and match)

    return report


def _alembic_upgrade_head(target_engine: Engine) -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", str(target_engine.url))
    config.attributes["connectable"] = target_engine
    command.upgrade(config, "head")


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe SQLite→PostgreSQL migration utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--source", required=True)
    backup_parser.add_argument("--backup", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--source", required=True)
    preflight_parser.add_argument("--target", required=True)
    preflight_parser.add_argument("--target-budget-mib", type=int, default=500)

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--source", required=True)
    migrate_parser.add_argument("--target", required=True)
    migrate_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    migrate_parser.add_argument("--target-budget-mib", type=int, default=500)
    migrate_parser.add_argument("--skip-verify", action="store_true")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--source", required=True)
    verify_parser.add_argument("--target", required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            backup_sqlite(args.source, args.backup)
            print(f"Backup created: {args.backup}")
            return 0

        if args.command == "preflight":
            report = preflight_databases(
                args.source,
                args.target,
                args.target_budget_mib * 1024 * 1024,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["ok"] else 1

        if args.command == "migrate":
            source_url = normalize_url(args.source)
            target_url = normalize_url(args.target)
            source_path = _sqlite_path_from_url(source_url)
            if not storage_safety_ok(
                estimate_sqlite_size_bytes(source_path),
                args.target_budget_mib * 1024 * 1024,
            ):
                raise RuntimeError(
                    "Migration blocked: estimated source size exceeds the 80% target storage safety threshold"
                )

            source_engine = _make_engine(source_url)
            target_engine = _make_engine(target_url)
            try:
                _alembic_upgrade_head(target_engine)
                preflight = preflight_databases(
                    source_url,
                    target_url,
                    args.target_budget_mib * 1024 * 1024,
                )
                if not preflight["ok"]:
                    raise RuntimeError("Migration blocked by preflight safety checks")
                migrate_database(source_engine, target_engine, batch_size=args.batch_size)
                if not args.skip_verify:
                    report = verify_databases(source_engine, target_engine)
                    print(json.dumps(report, indent=2, sort_keys=True))
                    if not report["ok"]:
                        raise RuntimeError("Verification mismatch detected")
                print("Migration completed; production DATABASE_URL was not modified.")
                return 0
            finally:
                source_engine.dispose()
                target_engine.dispose()

        if args.command == "verify":
            source_engine = _make_engine(args.source)
            target_engine = _make_engine(args.target)
            try:
                report = verify_databases(source_engine, target_engine)
                print(json.dumps(report, indent=2, sort_keys=True))
                return 0 if report["ok"] else 1
            finally:
                source_engine.dispose()
                target_engine.dispose()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
