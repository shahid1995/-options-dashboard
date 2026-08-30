from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, normalize_database_url
from app.identity import BrokerConnection, User
from app.models import GexSnapshot

ROOT = Path(__file__).resolve().parents[1]


def _postgres_test_url() -> str:
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not configured")
    url = normalize_database_url(raw)
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("TEST_DATABASE_URL must resolve to the psycopg 3 SQLAlchemy dialect")
    return url


@pytest.fixture(scope="session")
def postgres_engine():
    url = _postgres_test_url()
    engine = create_engine(url, pool_pre_ping=True)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    alembic_cfg.attributes["connectable"] = engine
    command.upgrade(alembic_cfg, "head")

    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_url_normalization():
    assert (
        normalize_database_url("postgres://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )
    explicit = "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url(explicit) == explicit
    sqlite = "sqlite:////tmp/test.db"
    assert normalize_database_url(sqlite) == sqlite


def test_full_alembic_schema_exists_on_postgres(postgres_engine):
    tables = set(inspect(postgres_engine).get_table_names())
    expected = set(Base.metadata.tables.keys())
    missing = sorted(expected - tables)
    assert not missing, f"PostgreSQL is missing ORM tables: {missing}"


def test_postgres_schema_supports_identity_and_gex_provenance(postgres_engine):
    session = sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)()
    user_id = "postgres-compat-user"
    connection_id = "postgres-compat-connection"

    try:
        # Flush the parent first so PostgreSQL's FK constraint is satisfied.
        session.add(
            User(
                id=user_id,
                email="postgres-compat@example.com",
                identity_source="email",
            )
        )
        session.flush()

        session.add(
            BrokerConnection(
                id=connection_id,
                user_id=user_id,
                broker="UPSTOX",
                broker_account_id="pending",
                is_default=True,
                status="pending",
                capability_mode="data",
                data_status="active",
                trading_status="inactive",
            )
        )
        session.flush()

        snapshot = GexSnapshot(
            owner_id=user_id,
            connection_id=connection_id,
            data_source="analytics_token",
            symbol="NIFTY",
            expiry="2026-12-31",
            spot=25000.0,
            methodology="GEX_STANDARD_V1",
            sign_convention="NAIVE_DEALER_CONVENTION",
            availability_status="available",
            valid_strike_count=2,
            total_strike_count=2,
            captured_at=datetime.now(timezone.utc),
            strike_data="[]",
            expiry_data="[]",
            methodology_metadata="{}",
        )
        session.add(snapshot)
        session.commit()

        loaded = session.get(GexSnapshot, snapshot.id)
        assert loaded is not None
        assert loaded.owner_id == user_id
        assert loaded.connection_id == connection_id
        assert loaded.data_source == "analytics_token"
        assert loaded.symbol == "NIFTY"
    finally:
        session.rollback()
        session.close()


def test_postgres_partial_unique_default_connection_is_enforced(postgres_engine):
    session: Session = sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)()
    user_id = "postgres-default-index-user"

    try:
        session.add(
            User(
                id=user_id,
                email="postgres-default@example.com",
                identity_source="email",
            )
        )
        session.flush()
        session.add(
            BrokerConnection(
                id="default-connection-1",
                user_id=user_id,
                broker="UPSTOX",
                broker_account_id="account-1",
                is_default=True,
                status="connected",
                capability_mode="trading",
            )
        )
        session.commit()

        session.add(
            BrokerConnection(
                id="default-connection-2",
                user_id=user_id,
                broker="UPSTOX",
                broker_account_id="account-2",
                is_default=True,
                status="connected",
                capability_mode="trading",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_postgres_unique_constraint_allows_multiple_non_default_connections(postgres_engine):
    session: Session = sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)()
    user_id = "postgres-multi-connection-user"

    try:
        session.add(
            User(
                id=user_id,
                email="postgres-multi@example.com",
                identity_source="email",
            )
        )
        session.flush()
        session.add_all(
            [
                BrokerConnection(
                    id="non-default-1",
                    user_id=user_id,
                    broker="UPSTOX",
                    broker_account_id="account-nd-1",
                    is_default=False,
                    status="connected",
                    capability_mode="trading",
                ),
                BrokerConnection(
                    id="non-default-2",
                    user_id=user_id,
                    broker="UPSTOX",
                    broker_account_id="account-nd-2",
                    is_default=False,
                    status="connected",
                    capability_mode="trading",
                ),
            ]
        )
        session.commit()
        count = (
            session.query(BrokerConnection)
            .filter(BrokerConnection.user_id == user_id)
            .count()
        )
        assert count == 2
    finally:
        session.rollback()
        session.close()
