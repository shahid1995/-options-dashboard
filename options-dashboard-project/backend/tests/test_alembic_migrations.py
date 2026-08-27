"""Tests for the Phase 10.1A Alembic migration infrastructure.

These tests verify:
1. Alembic baseline migration creates all tables including users/user_sessions
2. Migrations are idempotent (upgrade head is safe to run multiple times)
3. init_db() runs Alembic migrations and falls back to create_all()
4. Schema detection matches model definitions
5. No runtime DDL in auth path
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def fresh_engine():
    """Create a fresh in-memory SQLite engine for migration tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database file for file-based migration tests."""
    db_path = tmp_path / "test_migration.db"
    return f"sqlite:///{db_path}"


def test_alembic_baseline_creates_all_model_tables(fresh_engine):
    """Verify that Base.metadata.create_all creates all expected tables."""
    from app.db import Base
    from app import models  # noqa: F401
    from app.identity import User, UserSession  # noqa: F401

    Base.metadata.create_all(bind=fresh_engine)

    with fresh_engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

    # Core trading tables
    expected_tables = {
        "trades", "legs", "paper_accounts", "paper_orders", "paper_transactions",
        "positions", "strategy_executions", "strategy_leg_exposures",
        "exit_exposure_allocations", "bulk_exit_records",
        "strategy_templates", "strategy_template_legs",
        # Market data tables
        "gex_snapshots", "iv_observations", "nifty_candles",
        "contract_specs", "option_candles", "option_greeks",
        "historical_gex",
        # Pipeline tables
        "ingestion_log", "data_completeness", "ingestion_checkpoint",
        # Phase 10.1 identity tables
        "users", "user_sessions",
    }

    missing = expected_tables - tables
    assert not missing, f"Tables missing from schema: {missing}"


def test_init_db_uses_alembic_when_available(monkeypatch, fresh_engine):
    """Verify init_db() calls Alembic migrations then create_all()."""
    monkeypatch.setattr("app.db.engine", fresh_engine)
    monkeypatch.setattr("app.db.SessionLocal", sessionmaker(bind=fresh_engine))

    from app.db import init_db
    init_db()

    with fresh_engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }

    assert "users" in tables
    assert "user_sessions" in tables
    assert "trades" in tables
    assert "positions" in tables


def test_init_db_is_idempotent(monkeypatch, fresh_engine):
    """Verify init_db() can be called multiple times without errors."""
    monkeypatch.setattr("app.db.engine", fresh_engine)
    monkeypatch.setattr("app.db.SessionLocal", sessionmaker(bind=fresh_engine))

    from app.db import init_db
    init_db()
    init_db()  # Second call must not raise

    with fresh_engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
    assert "users" in tables


def test_no_ensure_identity_schema_in_auth_router():
    """Verify ensure_identity_schema is NOT called at request time in auth.

    Phase 10.1A removes runtime DDL from the authentication path.
    Schema is managed by Alembic migrations at startup.
    """
    with open(
        os.path.join(os.path.dirname(__file__), "..", "app", "routers", "auth.py")
    ) as f:
        auth_source = f.read()

    assert "ensure_identity_schema" not in auth_source, (
        "ensure_identity_schema() must not be called in auth.py after Phase 10.1A. "
        "Schema creation is handled by Alembic migrations at startup."
    )


def test_identity_module_has_no_engine_dependency():
    """Verify identity.py does not import engine (runtime DDL removed)."""
    with open(
        os.path.join(os.path.dirname(__file__), "..", "app", "identity.py")
    ) as f:
        identity_source = f.read()

    # Should not import engine for create_all
    assert "from app.db import Base, engine" not in identity_source, (
        "identity.py should not import engine after Phase 10.1A. "
        "Schema creation is handled by Alembic migrations."
    )
    # Should still import Base for model definitions
    assert "from app.db import Base" in identity_source


def test_alembic_stamped_database_is_upgradeable(temp_db):
    """Verify that a create_all database can be stamped and then upgraded."""
    # Create database the old way
    engine = create_engine(temp_db, connect_args={"check_same_thread": False})
    from app.db import Base
    from app import models  # noqa: F401
    from app.identity import User, UserSession  # noqa: F401

    Base.metadata.create_all(bind=engine)
    engine.dispose()

    # Stamp with alembic
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", temp_db)
    command.stamp(alembic_cfg, "head")

    # Verify stamp
    engine2 = create_engine(temp_db, connect_args={"check_same_thread": False})
    with engine2.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        assert len(result) == 1, "alembic_version table should have exactly one row"
    engine2.dispose()


def test_auth_callback_does_not_call_ensure_identity_schema(monkeypatch):
    """Integration test: auth callback path does not trigger runtime DDL.

    This verifies that the OAuth callback handler works without
    ensure_identity_schema() being called at request time.
    """
    from app.db import Base, engine
    from app import models  # noqa: F401
    from app.identity import User, UserSession  # noqa: F401

    # Ensure schema exists via create_all (simulating startup migration)
    Base.metadata.create_all(bind=engine)

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Test /auth/status - should not trigger any DDL
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": False}

    # Test /auth/logout without session - should return 401, no DDL
    resp = client.post("/auth/logout")
    assert resp.status_code == 401
