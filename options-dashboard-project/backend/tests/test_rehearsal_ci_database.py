from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, text

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from migrate_sqlite_to_postgres import (  # noqa: E402
    SKIP_TABLES,
    get_table_order,
    migrate_database,
    normalize_url,
    verify_databases,
)


def _load_synthetic_builder():
    path = Path(__file__).with_name("test_rehearsal_synthetic.py")
    spec = importlib.util.spec_from_file_location("synthetic_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_synthetic_dataset


def _prepare_postgres_schema(engine) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.attributes["connectable"] = engine
    command.upgrade(cfg, "head")


def _clear_postgres_target(engine) -> None:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    tables = [name for name in get_table_order(metadata) if name not in SKIP_TABLES]
    with engine.begin() as conn:
        for table_name in reversed(tables):
            conn.execute(text(f'DELETE FROM "{table_name}"'))


def _align_synthetic_fixture_schema(sqlite_path: Path) -> None:
    """Keep the legacy synthetic fixture compatible with the current Alembic schema."""
    engine = create_engine(f"sqlite:///{sqlite_path}")
    try:
        with engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.exec_driver_sql('PRAGMA table_info("broker_tokens")').fetchall()
            }
            if "broker" not in columns:
                conn.exec_driver_sql(
                    'ALTER TABLE "broker_tokens" ADD COLUMN "broker" VARCHAR DEFAULT \'UPSTOX\''
                )
            if "broker_analytics_token_encrypted" not in columns:
                conn.exec_driver_sql(
                    'ALTER TABLE "broker_tokens" ADD COLUMN "broker_analytics_token_encrypted" VARCHAR'
                )
            if "has_analytics_token" not in columns:
                conn.exec_driver_sql(
                    'ALTER TABLE "broker_tokens" ADD COLUMN "has_analytics_token" BOOLEAN DEFAULT 0'
                )
            if "updated_at" not in columns:
                conn.exec_driver_sql(
                    'ALTER TABLE "broker_tokens" ADD COLUMN "updated_at" DATETIME'
                )
    finally:
        engine.dispose()


def test_synthetic_rehearsal_uses_ci_postgres_and_verifies_full_report(tmp_path):
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    sqlite_path = tmp_path / "synthetic-ci.db"
    _load_synthetic_builder()(str(sqlite_path))
    _align_synthetic_fixture_schema(sqlite_path)

    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    postgres_engine = create_engine(normalize_url(raw_url), pool_pre_ping=True)
    try:
        _prepare_postgres_schema(postgres_engine)
        _clear_postgres_target(postgres_engine)

        report = migrate_database(
            sqlite_engine,
            postgres_engine,
            batch_size=1000,
        )

        assert report["ok"] is True, {
            "failed_tables": {
                name: details["errors"]
                for name, details in report["tables"].items()
                if not details["passed"]
            },
            "failed_sequences": {
                name: details
                for name, details in report["sequences"].items()
                if not details.get("ok")
            },
            "security": report["security"],
            "isolation": report["isolation"],
        }

        verified = verify_databases(sqlite_engine, postgres_engine)
        assert verified["ok"] is True
    finally:
        sqlite_engine.dispose()
        postgres_engine.dispose()
