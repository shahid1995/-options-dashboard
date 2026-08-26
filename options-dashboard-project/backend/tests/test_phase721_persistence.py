"""Phase 7.21 — Persistent database foundation tests.

Proves that:
  - the database path is deterministic and CWD-independent
  - two sessions see the same data
  - two independent engines see the same data
  - data survives engine recreation
  - the backfill tools use the centralized path
  - the database health check works
  - the temporary Phase 7.18 endpoint was removed
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import (
    Base,
    engine,
    _DEFAULT_DB_PATH,
    _BACKEND_DIR,
    get_database_path,
    check_database_health,
)
from app.models import NiftyCandle, ContractSpec, OptionCandle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database at an absolute path."""
    db_file = str(tmp_path / "test_phase721.db")
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine, db_file
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def temp_session(temp_db):
    """Provide a session bound to the temporary database."""
    engine, _ = temp_db
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# 1. Database path determinism
# ---------------------------------------------------------------------------

class TestDatabasePathDeterminism:
    """Verify the database path is always the same regardless of CWD."""

    def test_default_path_is_absolute(self):
        """The default database path must be an absolute filesystem path."""
        assert os.path.isabs(_DEFAULT_DB_PATH)

    def test_default_path_resolves_to_backend_dir(self):
        """The database lives in the backend/ directory."""
        assert _DEFAULT_DB_PATH.startswith(_BACKEND_DIR)

    def test_default_path_ends_with_db_filename(self):
        """The filename is paper_journal.db."""
        assert _DEFAULT_DB_PATH.endswith("paper_journal.db")

    def test_get_database_path_matches_default(self):
        """get_database_path() returns the same path as _DEFAULT_DB_PATH."""
        assert get_database_path() == _DEFAULT_DB_PATH

    def test_path_independent_of_cwd(self, monkeypatch):
        """Changing CWD does not change the database path."""
        original = get_database_path()

        # Change CWD to a completely different directory
        monkeypatch.chdir(tempfile.gettempdir())
        after_cwd_change = get_database_path()

        assert original == after_cwd_change

    def test_path_from_project_root(self, monkeypatch):
        """Even when launched from the project root, the DB path is the same."""
        original = get_database_path()

        monkeypatch.chdir(os.path.dirname(_BACKEND_DIR))
        from_project_root = get_database_path()

        assert original == from_project_root

    def test_engine_url_is_absolute(self):
        """The production engine URL contains an absolute path."""
        from app.db import engine
        url_str = str(engine.url)
        # SQLite URL with absolute path: sqlite:///C:/... or sqlite:///home/...
        assert "paper_journal.db" in url_str
        # Must not be the old relative form
        assert "./paper_journal.db" not in url_str


# ---------------------------------------------------------------------------
# 2. Two sessions see the same data
# ---------------------------------------------------------------------------

class TestTwoSessionsSameData:
    """Verify concurrent sessions on the same engine see the same data."""

    def test_write_session_1_visible_in_session_2(self, temp_db):
        """A record written by session 1 is visible to session 2."""
        engine, _ = temp_db
        Session = sessionmaker(bind=engine)

        s1 = Session()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 6, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=25000.0, high=25020.0, low=24980.0, close=25010.0, volume=1000.0,
        ))
        s1.commit()
        s1.close()

        # New session
        s2 = Session()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()

        assert count == 1


# ---------------------------------------------------------------------------
# 3. Two independent engines see the same data
# ---------------------------------------------------------------------------

class TestTwoEnginesSameData:
    """Verify two separately created engines on the same file see the same data."""

    def test_independent_engines_same_file(self, tmp_path):
        """Two engines opened on the same absolute path see the same data."""
        db_file = str(tmp_path / "shared.db")
        url = f"sqlite:///{db_file}"

        # Engine 1 — write
        e1 = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=e1)
        s1 = sessionmaker(bind=e1)()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 7, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=26000.0, high=26020.0, low=25980.0, close=26010.0, volume=2000.0,
        ))
        s1.commit()
        s1.close()
        e1.dispose()

        # Engine 2 — read (simulating a new process)
        e2 = create_engine(url, connect_args={"check_same_thread": False})
        s2 = sessionmaker(bind=e2)()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()
        e2.dispose()

        assert count == 1


# ---------------------------------------------------------------------------
# 4. Data survives engine recreation
# ---------------------------------------------------------------------------

class TestEngineRecreation:
    """Verify data persists when the engine is disposed and recreated."""

    def test_dispose_recreate_read(self, tmp_path):
        """Dispose engine, create new engine, data should survive."""
        db_file = str(tmp_path / "recreate.db")
        url = f"sqlite:///{db_file}"

        # Write
        e1 = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=e1)
        s1 = sessionmaker(bind=e1)()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 8, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=27000.0, high=27020.0, low=26980.0, close=27010.0, volume=3000.0,
        ))
        s1.commit()
        s1.close()
        e1.dispose()

        # Recreate
        e2 = create_engine(url, connect_args={"check_same_thread": False})
        s2 = sessionmaker(bind=e2)()
        candle = s2.execute(
            select(NiftyCandle).where(NiftyCandle.symbol == "NIFTY")
        ).scalar_one()
        s2.close()
        e2.dispose()

        assert candle.open == 27000.0
        assert candle.close == 27010.0
        assert candle.volume == 3000.0

    def test_cwd_change_engine_recreation(self, tmp_path, monkeypatch):
        """Change CWD, then recreate engine — data should survive."""
        db_file = str(tmp_path / "cwd_test.db")
        url = f"sqlite:///{db_file}"

        # Write from one CWD
        e1 = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=e1)
        s1 = sessionmaker(bind=e1)()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 9, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=28000.0, high=28020.0, low=27980.0, close=28010.0, volume=4000.0,
        ))
        s1.commit()
        s1.close()
        e1.dispose()

        # Change CWD
        monkeypatch.chdir(tempfile.gettempdir())

        # Read from different CWD (using absolute URL)
        e2 = create_engine(url, connect_args={"check_same_thread": False})
        s2 = sessionmaker(bind=e2)()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()
        e2.dispose()

        assert count == 1


# ---------------------------------------------------------------------------
# 5. Backfill tools use centralized path
# ---------------------------------------------------------------------------

class TestBackfillToolsPath:
    """Verify backfill tools import the centralized path from db.py."""

    def test_candle_backfill_imports_default_db_path(self):
        """candle_backfill._make_db_session should use _DEFAULT_DB_PATH."""
        import inspect
        from app.tools.candle_backfill import _make_db_session
        source = inspect.getsource(_make_db_session)
        assert "_DEFAULT_DB_PATH" in source
        assert "./paper_journal.db" not in source

    def test_option_candle_backfill_imports_default_db_path(self):
        """option_candle_backfill._make_db_session should use _DEFAULT_DB_PATH."""
        import inspect
        from app.tools.option_candle_backfill import _make_db_session
        source = inspect.getsource(_make_db_session)
        assert "_DEFAULT_DB_PATH" in source
        assert "./paper_journal.db" not in source

    def test_contract_metadata_backfill_imports_default_db_path(self):
        """contract_metadata_backfill._get_session should use _DEFAULT_DB_PATH."""
        import inspect
        from app.tools.contract_metadata_backfill import _get_session
        source = inspect.getsource(_get_session)
        assert "_DEFAULT_DB_PATH" in source
        assert "./paper_journal.db" not in source
        assert "options_candles.db" not in source

    def test_backfill_tools_all_use_same_path(self, tmp_path):
        """All backfill tools should resolve to the same database path."""
        from app.tools.candle_backfill import _make_db_session as cb_session
        from app.tools.option_candle_backfill import _make_db_session as ocb_session
        from app.tools.contract_metadata_backfill import _get_session as cm_session

        # Create sessions from each tool
        s1 = cb_session()
        s2 = ocb_session()
        s3 = cm_session()

        # All should be pointing to the same database
        url1 = str(s1.get_bind().url)
        url2 = str(s2.get_bind().url)
        url3 = str(s3.get_bind().url)

        assert url1 == url2 == url3

        s1.close()
        s2.close()
        s3.close()


# ---------------------------------------------------------------------------
# 6. Database health check
# ---------------------------------------------------------------------------

class TestDatabaseHealthCheck:
    """Verify the health check function works correctly."""

    @pytest.fixture(autouse=True)
    def _ensure_tables(self):
        """Ensure tables exist before health check tests."""
        # Import models to register them on Base.metadata
        from app import models  # noqa: F401
        Base.metadata.create_all(bind=engine)

    def test_health_check_returns_dict(self):
        """Health check should return a dict with expected keys."""
        health = check_database_health()
        assert isinstance(health, dict)
        assert "database_path" in health
        assert "file_exists" in health
        assert "accessible" in health
        assert "tables_present" in health
        assert "row_counts" in health

    def test_health_check_path_matches_config(self):
        """Health check path should match get_database_path()."""
        health = check_database_health()
        assert health["database_path"] == get_database_path()

    def test_health_check_file_exists(self):
        """Health check should detect the database file."""
        health = check_database_health()
        assert health["file_exists"] is True

    def test_health_check_accessible(self):
        """Health check should confirm database accessibility."""
        health = check_database_health()
        assert health["accessible"] is True

    def test_health_check_tables_present(self):
        """Health check should detect the historical tables."""
        health = check_database_health()
        present = set(health["tables_present"])
        assert "nifty_candles" in present
        assert "contract_specs" in present
        assert "option_candles" in present
        assert "option_greeks" in present

    def test_health_check_row_counts_are_integers(self):
        """Row counts should be non-negative integers."""
        health = check_database_health()
        for table, count in health["row_counts"].items():
            assert isinstance(count, int)
            assert count >= 0


# ---------------------------------------------------------------------------
# 7. Temporary endpoint removed
# ---------------------------------------------------------------------------

class TestTemporaryEndpointRemoved:
    """Verify the Phase 7.18 temporary endpoint was removed."""

    def test_phase718_router_file_deleted(self):
        """phase718_audit.py should no longer exist."""
        path = os.path.join(_BACKEND_DIR, "app", "routers", "phase718_audit.py")
        assert not os.path.exists(path)

    def test_phase718_not_in_main_routes(self):
        """The /dev/phase718-audit route should not exist."""
        from app.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/dev/phase718-audit" not in routes

    def test_phase718_not_importable(self):
        """Importing phase718_audit should fail."""
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import app.routers.phase718_audit  # noqa: F401


# ---------------------------------------------------------------------------
# 8. Absolute path file exists for production
# ---------------------------------------------------------------------------

class TestProductionDatabaseFile:
    """Verify the production database file exists at the expected location."""

    def test_production_db_exists(self):
        """The production database file should exist on disk."""
        assert os.path.isfile(_DEFAULT_DB_PATH)

    def test_production_db_has_tables(self):
        """The production database should have the expected tables."""
        from sqlalchemy import inspect as sa_inspect
        from app import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        insp = sa_inspect(engine)
        tables = set(insp.get_table_names())
        assert "nifty_candles" in tables
        assert "contract_specs" in tables
        assert "option_candles" in tables
        assert "option_greeks" in tables

    def test_production_db_file_size(self):
        """The production DB should have a reasonable file size (>100KB for schema)."""
        size = os.path.getsize(_DEFAULT_DB_PATH)
        assert size > 100_000  # at least 100KB for schema + indexes
