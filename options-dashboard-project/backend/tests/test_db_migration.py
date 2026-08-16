"""Tests for the ``init_db`` / ``ensure_column`` startup migration path.

Regression guard for the Railway startup crash: ``db.py`` used the
SQLAlchemy 1.4 ``engine.execute()`` API (removed in 2.0) and the
``ensure_column`` ALTER statement omitted the column name
(``ADD COLUMN VARCHAR(40) NULL``). Both only fire when a *pre-existing*
``trades`` table lacks the Phase 5.0 columns — exactly what a production
database upgrade hits, and what fresh-DB unit tests never exercised.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.db import _existing_columns, ensure_column, init_db


@pytest.fixture
def engine():
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def _create_legacy_trades(engine):
    """A pre-Phase 5.0 ``trades`` table without the new columns."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE trades ("
                "id INTEGER PRIMARY KEY, "
                "user_id VARCHAR(64), "
                "status VARCHAR(20))"
            )
        )


def test_existing_columns_uses_2_0_connection_api(engine):
    """engine.execute() was removed in SQLAlchemy 2.0; this must not crash."""
    _create_legacy_trades(engine)
    cols = _existing_columns(engine, "trades")
    assert cols == {"id", "user_id", "status"}


def test_ensure_column_adds_named_column(engine):
    _create_legacy_trades(engine)
    ensure_column(engine, "trades", "strategy_execution_id", "VARCHAR(40) NULL")
    cols = _existing_columns(engine, "trades")
    assert "strategy_execution_id" in cols


def test_ensure_column_is_idempotent(engine):
    _create_legacy_trades(engine)
    ensure_column(engine, "trades", "client_order_id", "VARCHAR(64) NULL")
    first = _existing_columns(engine, "trades")
    ensure_column(engine, "trades", "client_order_id", "VARCHAR(64) NULL")
    assert _existing_columns(engine, "trades") == first


def test_ensure_column_skips_missing_tables(engine):
    # Table absent: create_all owns it; ensure_column must not crash.
    ensure_column(engine, "trades", "strategy_execution_id", "VARCHAR(40) NULL")
    assert _existing_columns(engine, "trades") == set()


def test_init_db_migrates_preexisting_trades_table(monkeypatch, engine):
    """The Railway production path: old schema on disk, then startup."""
    _create_legacy_trades(engine)
    monkeypatch.setattr("app.db.engine", engine)

    init_db()

    cols = _existing_columns(engine, "trades")
    assert "strategy_execution_id" in cols
    assert "client_order_id" in cols
    # Every other model table was created alongside the migration.
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert "positions" in tables
    assert "paper_orders" in tables


def test_init_db_is_idempotent_on_migrated_schema(monkeypatch, engine):
    _create_legacy_trades(engine)
    monkeypatch.setattr("app.db.engine", engine)
    init_db()
    init_db()  # must not raise or duplicate columns
    cols = _existing_columns(engine, "trades")
    assert "strategy_execution_id" in cols
    assert "client_order_id" in cols
