"""Regression tests for PostgreSQL migration safety hardening."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
MODULE_PATH = TOOLS_DIR / "migrate_sqlite_to_postgres.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("migration_tool", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_tool_uses_psycopg3_not_psycopg2() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "import psycopg2" not in source
    assert "psycopg2.extras" not in source
    assert "import psycopg" in source or "from psycopg" in source


def test_read_only_sqlite_reader_does_not_checkpoint_wal(tmp_path: Path) -> None:
    tool = load_tool()
    db_path = tmp_path / "wal.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('one')")
        conn.commit()

    reader = tool.SQLiteReader(str(db_path))
    try:
        with pytest.raises(RuntimeError, match="read-only"):
            reader.wal_checkpoint()
    finally:
        reader.close()


def test_sqlite_fingerprint_is_independent_of_row_storage_order(tmp_path: Path) -> None:
    tool = load_tool()
    db_path = tmp_path / "order.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO demo(id, value) VALUES (?, ?)",
            [(1, "one"), (2, "two"), (3, "three")],
        )
        conn.commit()

    reader = tool.SQLiteReader(str(db_path))
    fp_before = reader.compute_fingerprint("demo", ["id", "value"])
    reader.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM demo")
        conn.executemany(
            "INSERT INTO demo(id, value) VALUES (?, ?)",
            [(3, "three"), (1, "one"), (2, "two")],
        )
        conn.commit()

    reader = tool.SQLiteReader(str(db_path))
    fp_after = reader.compute_fingerprint("demo", ["id", "value"])
    reader.close()
    assert fp_before == fp_after


def test_alembic_head_is_discovered_dynamically() -> None:
    tool = load_tool()
    assert hasattr(tool, "get_alembic_heads")
    heads = tool.get_alembic_heads(Path(__file__).resolve().parent.parent / "alembic")
    assert isinstance(heads, list)
    assert len(heads) == 1


def test_no_hardcoded_alembic_head_constant() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "EXPECTED_ALEMBIC_HEAD =" not in source


def test_insert_batch_does_not_commit_each_batch() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    start = source.index("def insert_batch")
    end = source.index("def compute_fingerprint", start)
    insert_batch_source = source[start:end]
    assert ".commit()" not in insert_batch_source


def test_migration_has_explicit_commit_and_rollback_boundary() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    start = source.index("def migrate_database")
    end = source.index("# Verification", start)
    migration_source = source[start:end]
    assert "commit()" in migration_source
    assert "rollback()" in migration_source


def test_sequence_reset_sql_is_present() -> None:
    tool = load_tool()
    sql = tool.sequence_reset_sql("users", "id")
    assert "pg_get_serial_sequence" in sql
    assert "setval" in sql


def test_redaction_never_returns_password() -> None:
    tool = load_tool()
    redacted = tool.redact_url("postgresql+psycopg://user:super-secret@host:5432/db")
    assert "super-secret" not in redacted


def test_canonical_gex_sources_remain_frozen() -> None:
    tool = load_tool()
    assert tool.GEX_DATA_SOURCES == {
        "analytics_token",
        "broker_oauth",
        "api_upload",
    }
