from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from test_rehearsal_ci_database import (
    _clear_postgres_target,
    _populate_current_schema_synthetic_dataset,
    _prepare_schema,
)
from migrate_sqlite_to_postgres import migrate_database, normalize_url


ROOT = Path(__file__).resolve().parents[1]


def _make_source_engine(tmp_path):
    return create_engine(
        f"sqlite:///{tmp_path / 'failure-injection.db'}",
        connect_args={"check_same_thread": False},
    )


def test_migration_failure_rolls_back_all_imported_rows(tmp_path):
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    sqlite_engine = _make_source_engine(tmp_path)
    postgres_engine = create_engine(normalize_url(raw_url), pool_pre_ping=True)
    try:
        _prepare_schema(sqlite_engine)
        _populate_current_schema_synthetic_dataset(sqlite_engine)
        _prepare_schema(postgres_engine)
        _clear_postgres_target(postgres_engine)

        def fail_after_first_table(table_name: str, rows_written: int) -> None:
            if table_name == "users" and rows_written > 0:
                raise RuntimeError("injected migration failure")

        with pytest.raises(RuntimeError, match="injected migration failure"):
            migrate_database(
                sqlite_engine,
                postgres_engine,
                batch_size=1000,
                failure_hook=fail_after_first_table,
            )

        with postgres_engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM "users"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "broker_connections"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "gex_snapshots"')).scalar_one() == 0
    finally:
        sqlite_engine.dispose()
        postgres_engine.dispose()


def test_migration_failure_during_later_table_rolls_back_earlier_tables(tmp_path):
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    sqlite_engine = _make_source_engine(tmp_path)
    postgres_engine = create_engine(normalize_url(raw_url), pool_pre_ping=True)
    try:
        _prepare_schema(sqlite_engine)
        _populate_current_schema_synthetic_dataset(sqlite_engine)
        _prepare_schema(postgres_engine)
        _clear_postgres_target(postgres_engine)

        def fail_on_gex(table_name: str, rows_written: int) -> None:
            if table_name == "gex_snapshots" and rows_written > 0:
                raise RuntimeError("injected later-table failure")

        with pytest.raises(RuntimeError, match="injected later-table failure"):
            migrate_database(
                sqlite_engine,
                postgres_engine,
                batch_size=1000,
                failure_hook=fail_on_gex,
            )

        with postgres_engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM "users"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "broker_connections"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "gex_snapshots"')).scalar_one() == 0
    finally:
        sqlite_engine.dispose()
        postgres_engine.dispose()


def test_migration_failure_during_sequence_repair_rolls_back_data(tmp_path):
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    sqlite_engine = _make_source_engine(tmp_path)
    postgres_engine = create_engine(normalize_url(raw_url), pool_pre_ping=True)
    try:
        _prepare_schema(sqlite_engine)
        _populate_current_schema_synthetic_dataset(sqlite_engine)
        _prepare_schema(postgres_engine)
        _clear_postgres_target(postgres_engine)

        def fail_sequence_repair(connection) -> None:
            raise RuntimeError("injected sequence-repair failure")

        with pytest.raises(RuntimeError, match="injected sequence-repair failure"):
            migrate_database(
                sqlite_engine,
                postgres_engine,
                batch_size=1000,
                sequence_repair_hook=fail_sequence_repair,
            )

        with postgres_engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM "users"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "broker_connections"')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM "gex_snapshots"')).scalar_one() == 0
    finally:
        sqlite_engine.dispose()
        postgres_engine.dispose()
