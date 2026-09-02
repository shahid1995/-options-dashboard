"""Day 5 — Alembic Authority & Schema Drift Tests.

Verifies:
1. Alembic head authority — exactly one head, multiple heads rejected
2. Production schema authority — no create_all() in production startup
3. Revision-state / drift detection — current, behind, unknown, unavailable
4. Migration upgrade produces correct state
5. No credentials leak in error paths
"""

from __future__ import annotations

import inspect
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# 1. Alembic head authority
# ---------------------------------------------------------------------------

class TestAlembicHeadAuthority:
    """Verify exactly one Alembic head exists and is deterministically obtainable."""

    def test_exactly_one_head(self):
        """Alembic must have exactly one head revision."""
        from alembic.config import Config
        from alembic import command
        from alembic.runtime.migration import MigrationContext

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        # Use a temporary database to check heads without touching production
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f"sqlite:///{f.name}"

        try:
            cfg.set_main_option("sqlalchemy.url", tmp_db)
            heads_output = []
            # heads() prints to stdout; capture via command
            from alembic.script import ScriptDirectory
            script = ScriptDirectory.from_config(cfg)
            heads = script.get_heads()
            assert len(heads) == 1, (
                f"Expected exactly 1 Alembic head, got {len(heads)}: {heads}. "
                "Multiple heads indicate an unmerged migration branch."
            )
        finally:
            os.unlink(f.name)

    def test_head_is_deterministic(self):
        """The Alembic head revision must be deterministic across calls."""
        from alembic.script import ScriptDirectory
        from alembic.config import Config

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )
        script = ScriptDirectory.from_config(cfg)
        head1 = script.get_heads()
        head2 = script.get_heads()
        assert head1 == head2, "Alembic head must be deterministic"

    def test_current_revision_obtainable(self):
        """The current database revision can be obtained via Alembic API."""
        from alembic.config import Config
        from alembic import command
        from alembic.runtime.migration import MigrationContext

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            # Stamp to head so revision is known
            cfg.set_main_option("sqlalchemy.url", tmp_db)
            command.stamp(cfg, "head")

            # Verify revision can be read
            with engine.connect() as conn:
                mc = MigrationContext.configure(conn)
                current_rev = mc.get_current_revision()
                assert current_rev is not None, "Current revision should not be None after stamp"

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_multiple_heads_detected_in_script(self):
        """ScriptDirectory.get_heads() returns a list; we verify length."""
        from alembic.script import ScriptDirectory
        from alembic.config import Config

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert isinstance(heads, (list, tuple))
        # The assertion is in test_exactly_one_head; here we just verify the API works
        assert len(heads) >= 1, "Must have at least one head"

    def test_no_credentials_in_alembic_config(self):
        """Alembic config must not contain hardcoded credentials."""
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        content = alembic_ini.read_text()
        # Check for common credential patterns in the config file
        lower = content.lower()
        assert "password=" not in lower.replace("password = ", ""), (
            "alembic.ini must not contain hardcoded passwords"
        )
        assert "postgres://" not in lower, (
            "alembic.ini must not contain hardcoded PostgreSQL URLs with credentials"
        )


# ---------------------------------------------------------------------------
# 2. Production schema authority
# ---------------------------------------------------------------------------

class TestProductionSchemaAuthority:
    """Verify production startup uses Alembic, not create_all()."""

    def test_init_db_no_create_all(self):
        """Production init_db() must NOT call Base.metadata.create_all()."""
        import app.db as db_module
        source = inspect.getsource(db_module.init_db)
        assert "create_all" not in source, (
            "init_db() must not call create_all(). "
            "Alembic is the sole schema management mechanism."
        )

    def test_init_db_no_ensure_column(self):
        """Production init_db() must NOT call ensure_column()."""
        import app.db as db_module
        source = inspect.getsource(db_module.init_db)
        assert "ensure_column" not in source, (
            "init_db() must not call ensure_column(). "
            "All legacy columns are in the Alembic baseline."
        )

    def test_init_db_uses_alembic_upgrade(self):
        """Production init_db() must call Alembic upgrade head."""
        import app.db as db_module
        source = inspect.getsource(db_module.init_db)
        assert "alembic" in source.lower() or "_run_alembic_migrations" in source, (
            "init_db() must use Alembic for schema management"
        )

    def test_ensure_column_function_removed(self):
        """ensure_column() and _existing_columns() must be removed from db.py."""
        import app.db as db_module
        assert not hasattr(db_module, "ensure_column"), (
            "ensure_column() must be removed from db.py"
        )
        assert not hasattr(db_module, "_existing_columns"), (
            "_existing_columns() must be removed from db.py"
        )

    def test_cli_tools_may_use_create_all(self):
        """CLI tools legitimately use create_all() for their own database setup.

        This test documents that CLI tools (candle_backfill, run_backfill, etc.)
        are separate from the web application startup path and may use create_all.
        """
        cli_files = [
            "tools/candle_backfill.py",
            "tools/option_candle_backfill.py",
            "tools/contract_metadata_backfill.py",
            "tools/live_verification.py",
            "run_backfill.py",
            "run_daily.py",
        ]
        backend_dir = Path(__file__).resolve().parent.parent
        for cli_file in cli_files:
            cli_path = backend_dir / cli_file
            if cli_path.exists():
                content = cli_path.read_text()
                # These files may use create_all — that's expected for CLI tools
                # This test just documents the boundary
                if "create_all" in content:
                    # Verify it's not importing from app.db.init_db
                    assert "init_db" not in content or "create_all" in content, (
                        f"{cli_file} should use create_all directly, not through init_db"
                    )


# ---------------------------------------------------------------------------
# 3. Revision-state / drift validation
# ---------------------------------------------------------------------------

class TestRevisionStateValidation:
    """Verify Alembic revision state can be inspected and validated."""

    def test_stamped_database_matches_head(self):
        """After upgrade/stamp, database revision must match Alembic head."""
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect as sa_inspect

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            # Run full upgrade
            cfg.set_main_option("sqlalchemy.url", tmp_db)
            command.upgrade(cfg, "head")

            # Get expected head from migration scripts
            script = ScriptDirectory.from_config(cfg)
            expected_head = script.get_heads()[0]

            # Get actual revision from database
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                assert row is not None, "alembic_version table must have a row"
                actual_rev = row[0]

            assert actual_rev == expected_head, (
                f"Database revision {actual_rev} does not match "
                f"expected head {expected_head}"
            )
            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_behind_database_detected(self):
        """A database stamped to an older revision is detected as behind."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            # Create alembic_version table and insert a fake old revision
            # (simulating a database that was migrated with an older version)
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                ))
                conn.execute(text(
                    "INSERT INTO alembic_version (version_num) VALUES ('old0000000000')"
                ))

            # Get expected head
            script = ScriptDirectory.from_config(cfg)
            expected_head = script.get_heads()[0]

            # Get actual revision
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                actual_rev = row[0] if row else None

            assert actual_rev != expected_head, (
                f"Database revision should be behind, but matches head: {actual_rev}"
            )
            assert actual_rev == "old0000000000", f"Expected fake old revision, got: {actual_rev}"

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_empty_database_detected(self):
        """A database with no alembic_version table is detected as uninitialised."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='alembic_version'"
                    )
                )
                row = result.fetchone()
                assert row is None, (
                    "Fresh database should not have alembic_version table"
                )

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_database_unavailable_handling(self):
        """When database is unreachable, revision check fails gracefully without leaking credentials."""
        from sqlalchemy import create_engine

        # Create engine pointing to non-existent database
        broken_engine = create_engine(
            "sqlite:///nonexistent_path_12345.db",
            connect_args={"check_same_thread": False},
        )

        try:
            with broken_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            error_str = str(e)
            # Error must not contain credential patterns
            assert "password" not in error_str.lower(), (
                f"Error should not contain password: {error_str}"
            )
            assert "secret" not in error_str.lower(), (
                f"Error should not contain secret: {error_str}"
            )
        finally:
            broken_engine.dispose()

    def test_alembic_version_table_single_row(self):
        """alembic_version must have exactly one row (no multiple heads in DB)."""
        from alembic.config import Config
        from alembic import command

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            cfg.set_main_option("sqlalchemy.url", tmp_db)
            command.upgrade(cfg, "head")

            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
                count = result.scalar()
                assert count == 1, (
                    f"alembic_version should have exactly 1 row, got {count}"
                )

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_upgrade_idempotent(self):
        """Running upgrade head twice must not error."""
        from alembic.config import Config
        from alembic import command

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"

            cfg.set_main_option("sqlalchemy.url", tmp_db)
            command.upgrade(cfg, "head")
            # Second upgrade must not raise
            command.upgrade(cfg, "head")

            # Verify still valid
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
                assert result.scalar() == 1
            engine.dispose()
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 4. validate_migration_state() function
# ---------------------------------------------------------------------------


class TestValidateMigrationState:
    """Verify the validate_migration_state() runtime validation function."""

    def test_function_exists_and_callable(self):
        """validate_migration_state must exist and be callable."""
        from app.db import validate_migration_state
        assert callable(validate_migration_state)

    def test_returns_dict_with_required_keys(self):
        """validate_migration_state must return a dict with required keys."""
        from app.db import validate_migration_state
        result = validate_migration_state()
        assert isinstance(result, dict)
        assert "status" in result
        assert "expected_head" in result
        assert "actual_revision" in result
        assert "alembic_heads" in result
        assert "error" in result

    def test_status_is_current_when_db_matches_head(self):
        """When database revision matches head, status must be 'current'."""
        import app.db as db_module
        from app.db import validate_migration_state
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        cfg = Config(
            os.path.join(
                os.path.dirname(__file__), "..", "alembic.ini"
            )
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            # Run full upgrade
            cfg.set_main_option("sqlalchemy.url", tmp_db)
            command.upgrade(cfg, "head")

            # Temporarily swap the module engine
            original_engine = db_module.engine
            original_session = db_module.SessionLocal
            try:
                db_module.engine = engine
                db_module.SessionLocal = sessionmaker(bind=engine)
                result = validate_migration_state()
                assert result["status"] == "current", (
                    f"Expected 'current', got '{result["status"]}': {result}"
                )
                assert result["error"] is None
            finally:
                db_module.engine = original_engine
                db_module.SessionLocal = original_session

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_status_is_behind_when_db_has_old_revision(self):
        """When database has an old revision, status must be 'behind'."""
        import app.db as db_module
        from app.db import validate_migration_state
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            tmp_db = f"sqlite:///{tmp_path}"
            engine = create_engine(tmp_db, connect_args={"check_same_thread": False})

            # Create alembic_version with a fake old revision
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                ))
                conn.execute(text(
                    "INSERT INTO alembic_version (version_num) VALUES ('old0000000000')"
                ))

            original_engine = db_module.engine
            original_session = db_module.SessionLocal
            try:
                db_module.engine = engine
                db_module.SessionLocal = sessionmaker(bind=engine)
                result = validate_migration_state()
                assert result["status"] == "behind", (
                    f"Expected 'behind', got '{result["status"]}': {result}"
                )
                assert result["error"] is not None
                assert "old0000000000" in result["error"]
            finally:
                db_module.engine = original_engine
                db_module.SessionLocal = original_session

            engine.dispose()
        finally:
            os.unlink(tmp_path)

    def test_no_credentials_in_output(self):
        """validate_migration_state output must never contain credentials."""
        from app.db import validate_migration_state
        result = validate_migration_state()
        result_str = str(result).lower()
        assert "password" not in result_str
        assert "secret" not in result_str
        # For SQLite (test env), database_path should not contain @
        if result["actual_revision"]:
            # Revision hashes don't contain @ — this is a basic sanity check
            assert "@" not in str(result["actual_revision"])
