"""Regression tests for Stage 5 blockers: CLI contract, target-empty, storage safety."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, text

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
MODULE_PATH = TOOLS_DIR / "migrate_sqlite_to_postgres.py"
ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    spec = importlib.util.spec_from_file_location("migration_tool", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(spec.name, None)
        raise


def postgres_url():
    import os
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return raw


def _prepare_schema(engine):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.attributes["connectable"] = engine
    command.upgrade(cfg, "head")


def _make_source_db(tmp_path):
    """Create a minimal SQLite source with one user."""
    db_path = tmp_path / "stage5_source.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    _prepare_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, identity_source) "
                "VALUES ('blocker-test-user', 'blocker@test.com', 'email')"
            )
        )
    return engine


# ──────────────────────────────────────────────────────────────────
# BLOCKER 1 — CLI/runbook contract
# ──────────────────────────────────────────────────────────────────

class TestCLIRunbookContract:
    """The runbook documents subcommands: backup, preflight, migrate, verify.
    The CLI must expose these as actual subcommands."""

    def test_runbook_backup_subcommand_exists(self):
        """Runbook documents 'backup' subcommand — it must be parseable."""
        tool = load_tool()
        import argparse

        parser = tool._build_parser()
        # The 'backup' subcommand should be recognized
        args = parser.parse_args(
            ["backup", "--source", "/tmp/src.db", "--backup", "/tmp/dst.db"]
        )
        assert args.subcommand == "backup"

    def test_runbook_preflight_subcommand_exists(self):
        """Runbook documents 'preflight' subcommand."""
        tool = load_tool()
        parser = tool._build_parser()
        args = parser.parse_args(
            ["preflight", "--source", "/tmp/src.db", "--target", "postgresql+psycopg://u:p@h/db"]
        )
        assert args.subcommand == "preflight"

    def test_runbook_migrate_subcommand_exists(self):
        """Runbook documents 'migrate' subcommand."""
        tool = load_tool()
        parser = tool._build_parser()
        args = parser.parse_args(
            ["migrate", "--source", "/tmp/src.db", "--target", "postgresql+psycopg://u:p@h/db"]
        )
        assert args.subcommand == "migrate"

    def test_runbook_verify_subcommand_exists(self):
        """Runbook documents 'verify' subcommand."""
        tool = load_tool()
        parser = tool._build_parser()
        args = parser.parse_args(
            ["verify", "--source", "/tmp/src.db", "--target", "postgresql+psycopg://u:p@h/db"]
        )
        assert args.subcommand == "verify"

    def test_legacy_flag_interface_still_works(self):
        """Backward compatibility: --sqlite --pg-url flags should still parse."""
        tool = load_tool()
        parser = tool._build_parser()
        args = parser.parse_args(
            ["--sqlite", "/tmp/src.db", "--pg-url", "postgresql+psycopg://u:p@h/db"]
        )
        assert getattr(args, "subcommand", None) is None or args.subcommand == "migrate"
        assert args.sqlite == "/tmp/src.db"

    def test_runbook_documented_flags_match_parser(self):
        """Runbook --target-budget-mib and --batch-size must be accepted by migrate subcommand."""
        tool = load_tool()
        parser = tool._build_parser()
        args = parser.parse_args(
            [
                "migrate",
                "--source", "/tmp/src.db",
                "--target", "postgresql+psycopg://u:p@h/db",
                "--batch-size", "500",
                "--target-budget-mib", "1024",
            ]
        )
        assert args.batch_size == 500
        assert args.target_budget_mib == 1024


# ──────────────────────────────────────────────────────────────────
# BLOCKER 2 — Target-empty enforcement in migrate_database()
# ──────────────────────────────────────────────────────────────────

class TestTargetEmptyEnforcement:
    """migrate_database() must refuse to start if PostgreSQL target already has data."""

    def test_migrate_database_refuses_non_empty_target(self, tmp_path):
        """Calling migrate_database() against a non-empty PostgreSQL must fail
        before writing any rows. No rows should be added."""
        tool = load_tool()
        url = postgres_url()
        pg_url = tool.normalize_url(url)
        source_engine = _make_source_db(tmp_path)
        target_engine = create_engine(pg_url, pool_pre_ping=True)
        try:
            _prepare_schema(target_engine)
            # Pre-populate target with a user that does NOT exist in source
            with target_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (id, email, identity_source) "
                        "VALUES ('existing-pg-user', 'existing@pg.com', 'email')"
                    )
                )
            initial_count = target_engine.connect().execute(
                text('SELECT COUNT(*) FROM "users"')
            ).scalar()

            with pytest.raises(RuntimeError, match="not empty"):
                tool.migrate_database(source_engine, target_engine, batch_size=1000)

            # Verify NO source rows were written
            final_count = target_engine.connect().execute(
                text('SELECT COUNT(*) FROM "users"')
            ).scalar()
            assert final_count == initial_count, (
                f"migrate_database wrote {final_count - initial_count} rows "
                f"into a non-empty target — target-empty gate failed"
            )

            # Verify existing target data is untouched
            with target_engine.connect() as conn:
                existing = conn.execute(
                    text("SELECT id FROM users WHERE id = 'existing-pg-user'")
                ).fetchone()
                assert existing is not None, "Existing target row was lost"
        finally:
            source_engine.dispose()
            target_engine.dispose()

    def test_target_empty_check_not_only_in_main(self):
        """The target-empty check must appear in migrate_database, not only in main()."""
        tool = load_tool()
        import inspect

        source = inspect.getsource(tool.migrate_database)
        assert "target_empty" in source.lower() or "not empty" in source.lower() or "assert_target_empty" in source, (
            "migrate_database() does not enforce target-empty invariant"
        )


# ──────────────────────────────────────────────────────────────────
# BLOCKER 3 — Storage safety gate enforcement
# ──────────────────────────────────────────────────────────────────

class TestStorageSafetyGate:
    """migration must check storage capacity before writing any rows."""

    def test_migrate_database_checks_storage_safety(self, tmp_path):
        """migrate_database() must verify storage budget before writing rows.
        If source is larger than the budget allows, migration must refuse."""
        tool = load_tool()
        url = postgres_url()
        pg_url = tool.normalize_url(url)
        source_engine = _make_source_db(tmp_path)
        target_engine = create_engine(pg_url, pool_pre_ping=True)
        try:
            _prepare_schema(target_engine)
            with target_engine.begin() as conn:
                # Clear target to empty
                metadata = MetaData()
                metadata.reflect(bind=target_engine)
                for t in reversed(list(metadata.tables)):
                    conn.execute(text(f'DELETE FROM "{t}"'))

            # Pass an absurdly small budget (1 byte) to force rejection
            with pytest.raises((RuntimeError, ValueError), match="storage|budget|capacity"):
                tool.migrate_database(
                    source_engine, target_engine,
                    batch_size=1000,
                    target_budget_bytes=1,
                )

            # Verify no rows were written
            with target_engine.connect() as conn:
                count = conn.execute(text('SELECT COUNT(*) FROM "users"')).scalar()
                assert count == 0, (
                    f"Migration wrote {count} rows despite failing the storage safety gate"
                )
        finally:
            source_engine.dispose()
            target_engine.dispose()

    def test_storage_safety_gate_before_any_writes(self):
        """The storage check must appear as an actual function CALL in migrate_database, not just a definition."""
        tool = load_tool()
        import inspect

        source = inspect.getsource(tool.migrate_database)
        # There must be an actual CALL to storage_safety_ok (not just the function definition elsewhere)
        has_call = ("storage_safety_ok(" in source) or ("_check_storage" in source)
        assert has_call, (
            "migrate_database() does not call storage_safety_ok — "
            "the storage safety gate is not enforced in the migration operation"
        )

    def test_storage_safety_ok_function_exists(self):
        """The storage_safety_ok helper must exist and enforce the 80% budget."""
        tool = load_tool()
        assert hasattr(tool, "storage_safety_ok")
        # Must reject over-budget
        assert not tool.storage_safety_ok(801 * 1024 * 1024, 1000 * 1024 * 1024)
        # Must accept under-budget
        assert tool.storage_safety_ok(799 * 1024 * 1024, 1000 * 1024 * 1024)
        # Must reject negative source
        assert not tool.storage_safety_ok(-1, 1000 * 1024 * 1024)
        # Must reject zero capacity
        assert not tool.storage_safety_ok(100, 0)
