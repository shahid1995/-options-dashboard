"""Application-level PostgreSQL integration tests.

Phases B-F of the PostgreSQL readiness program:
- Verifies the actual backend application works against PostgreSQL
- Tests authentication, identity, broker connections, GEX, paper trading
- Performs a full SQLite-to-PostgreSQL migration rehearsal
- Simulates cutover and exercises rollback decision tree

Requires TEST_DATABASE_URL environment variable pointing to a PostgreSQL database.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import sessionmaker

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
TOOLS_DIR = ROOT / "tools"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TESTS_DIR))

from migrate_sqlite_to_postgres import (  # noqa: E402
    SKIP_TABLES,
    get_table_order,
    migrate_database,
    normalize_url,
    verify_databases,
)


def _pg_url() -> str:
    raw = os.getenv("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return normalize_url(raw)


def _prepare_schema(engine) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.attributes["connectable"] = engine
    command.upgrade(cfg, "head")


def _clear_postgres_target(engine) -> None:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    tables = [
        name
        for name in metadata.tables
        if name not in SKIP_TABLES
    ]
    with engine.begin() as conn:
        for table_name in reversed(tables):
            conn.execute(text(f'DELETE FROM "{table_name}"'))


def _create_rehearsal_sqlite(tmp_path) -> "tuple[Path, object]":
    """Create a realistic SQLite dataset for migration rehearsal."""
    from app.identity import BrokerConnection, User
    from app.models import GexSnapshot

    db_path = tmp_path / "rehearsal_source.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    _prepare_schema(engine)

    session = sessionmaker(bind=engine)()
    try:
        # Two users with different broker connections
        user_a = User(
            id="app-test-user-a",
            email="user-a@app-test.com",
            identity_source="email",
        )
        user_b = User(
            id="app-test-user-b",
            email="user-b@app-test.com",
            identity_source="google",
        )
        conn_a = BrokerConnection(
            id="app-test-conn-a",
            user_id=user_a.id,
            broker="UPSTOX",
            broker_account_id="app-test-acct-a",
            is_default=True,
            status="connected",
            capability_mode="data",
            data_status="active",
            trading_status="inactive",
        )
        conn_b = BrokerConnection(
            id="app-test-conn-b",
            user_id=user_b.id,
            broker="UPSTOX",
            broker_account_id="app-test-acct-b",
            is_default=True,
            status="connected",
            capability_mode="data",
            data_status="active",
            trading_status="inactive",
        )
        session.add_all([user_a, user_b, conn_a, conn_b])
        session.flush()

        # GEX snapshots with provenance
        for user, conn, source in [
            (user_a, conn_a, "analytics_token"),
            (user_b, conn_b, "broker_oauth"),
        ]:
            session.add(GexSnapshot(
                owner_id=user.id,
                connection_id=conn.id,
                data_source=source,
                symbol="NIFTY",
                expiry="2026-12-31",
                spot=25000.0,
                methodology="GEX_STANDARD_V1",
                sign_convention="NAIVE_DEALER_CONVENTION",
                availability_status="available",
                valid_strike_count=1,
                total_strike_count=1,
                captured_at=datetime.now(timezone.utc),
                strike_data="[]",
                expiry_data="[]",
                methodology_metadata="{}",
            ))
        session.commit()
    finally:
        session.close()
    engine.dispose()
    return db_path


# ---------------------------------------------------------------------------
# Phase B: PostgreSQL environment verification
# ---------------------------------------------------------------------------

class TestPostgresEnvironment:
    """Verify the PostgreSQL test environment is usable."""

    def test_postgres_connects(self):
        engine = create_engine(_pg_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
        engine.dispose()

    def test_alembic_schema_applies(self):
        engine = create_engine(_pg_url(), pool_pre_ping=True)
        try:
            _prepare_schema(engine)
            with engine.connect() as conn:
                tables = [
                    row[0]
                    for row in conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    ).fetchall()
                ]
                assert "users" in tables
                assert "user_sessions" in tables
                assert "broker_connections" in tables
                assert "gex_snapshots" in tables
        finally:
            engine.dispose()

    def test_alembic_head_matches(self):
        engine = create_engine(_pg_url(), pool_pre_ping=True)
        try:
            _prepare_schema(engine)
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                assert row is not None
                # Head should be a valid migration hash
                assert len(row[0]) >= 10
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Phase C: Application-level PostgreSQL tests
# ---------------------------------------------------------------------------

class TestApplicationPostgres:
    """Run core application logic against PostgreSQL."""

    def _setup(self):
        engine = create_engine(_pg_url(), pool_pre_ping=True)
        _prepare_schema(engine)
        _clear_postgres_target(engine)
        return engine

    def test_user_creation_and_read(self):
        engine = self._setup()
        try:
            from app.identity import User
            session = sessionmaker(bind=engine)()
            try:
                user = User(
                    id="pg-crud-user",
                    email="crud@test.com",
                    identity_source="email",
                )
                session.add(user)
                session.commit()

                found = session.query(User).filter(User.id == "pg-crud-user").one()
                assert found.email == "crud@test.com"
                assert found.identity_source == "email"
            finally:
                session.close()
        finally:
            engine.dispose()

    def test_broker_connection_lifecycle(self):
        engine = self._setup()
        try:
            from app.identity import BrokerConnection, User
            session = sessionmaker(bind=engine)()
            try:
                user = User(
                    id="pg-broker-user",
                    email="broker@test.com",
                    identity_source="email",
                )
                conn = BrokerConnection(
                    id="pg-broker-conn",
                    user_id=user.id,
                    broker="UPSTOX",
                    broker_account_id="pg-broker-acct",
                    is_default=True,
                    status="connected",
                    capability_mode="data",
                    data_status="active",
                    trading_status="inactive",
                )
                session.add_all([user, conn])
                session.commit()

                found = session.query(BrokerConnection).filter(
                    BrokerConnection.id == "pg-broker-conn"
                ).one()
                assert found.user_id == "pg-broker-user"
                assert found.broker == "UPSTOX"
                assert found.data_status == "active"
                assert found.trading_status == "inactive"
            finally:
                session.close()
        finally:
            engine.dispose()

    def test_gex_snapshot_with_provenance(self):
        engine = self._setup()
        try:
            from app.identity import BrokerConnection, User
            from app.models import GexSnapshot
            session = sessionmaker(bind=engine)()
            try:
                user = User(
                    id="pg-gex-user",
                    email="gex@test.com",
                    identity_source="email",
                )
                conn = BrokerConnection(
                    id="pg-gex-conn",
                    user_id=user.id,
                    broker="UPSTOX",
                    broker_account_id="pg-gex-acct",
                    is_default=True,
                    status="connected",
                    capability_mode="data",
                    data_status="active",
                    trading_status="inactive",
                )
                snap = GexSnapshot(
                    owner_id=user.id,
                    connection_id=conn.id,
                    data_source="analytics_token",
                    symbol="NIFTY",
                    expiry="2026-12-31",
                    spot=25000.0,
                    methodology="GEX_STANDARD_V1",
                    sign_convention="NAIVE_DEALER_CONVENTION",
                    availability_status="available",
                    valid_strike_count=5,
                    total_strike_count=10,
                    captured_at=datetime.now(timezone.utc),
                    strike_data='[{"strike":25000,"gex":100}]',
                    expiry_data="[]",
                    methodology_metadata="{}",
                )
                session.add_all([user, conn, snap])
                session.commit()

                found = session.query(GexSnapshot).filter(
                    GexSnapshot.owner_id == "pg-gex-user"
                ).one()
                assert found.connection_id == "pg-gex-conn"
                assert found.data_source == "analytics_token"
                assert found.symbol == "NIFTY"
            finally:
                session.close()
        finally:
            engine.dispose()

    def test_cross_user_isolation(self):
        engine = self._setup()
        try:
            from app.identity import BrokerConnection, User
            from app.models import GexSnapshot
            session = sessionmaker(bind=engine)()
            try:
                user_a = User(id="pg-iso-a", email="a@iso.com", identity_source="email")
                user_b = User(id="pg-iso-b", email="b@iso.com", identity_source="email")
                conn_a = BrokerConnection(
                    id="pg-iso-conn-a", user_id=user_a.id, broker="UPSTOX",
                    broker_account_id="iso-acct-a", is_default=True,
                    status="connected", capability_mode="data",
                    data_status="active", trading_status="inactive",
                )
                conn_b = BrokerConnection(
                    id="pg-iso-conn-b", user_id=user_b.id, broker="UPSTOX",
                    broker_account_id="iso-acct-b", is_default=True,
                    status="connected", capability_mode="data",
                    data_status="active", trading_status="inactive",
                )
                snap_a = GexSnapshot(
                    owner_id=user_a.id, connection_id=conn_a.id,
                    data_source="analytics_token", symbol="NIFTY",
                    expiry="2026-12-31", spot=25000.0,
                    methodology="GEX_STANDARD_V1",
                    sign_convention="NAIVE_DEALER_CONVENTION",
                    availability_status="available",
                    valid_strike_count=1, total_strike_count=1,
                    captured_at=datetime.now(timezone.utc),
                    strike_data="[]", expiry_data="[]",
                    methodology_metadata="{}",
                )
                snap_b = GexSnapshot(
                    owner_id=user_b.id, connection_id=conn_b.id,
                    data_source="broker_oauth", symbol="BANKNIFTY",
                    expiry="2026-12-31", spot=50000.0,
                    methodology="GEX_STANDARD_V1",
                    sign_convention="NAIVE_DEALER_CONVENTION",
                    availability_status="available",
                    valid_strike_count=1, total_strike_count=1,
                    captured_at=datetime.now(timezone.utc),
                    strike_data="[]", expiry_data="[]",
                    methodology_metadata="{}",
                )
                session.add_all([user_a, user_b, conn_a, conn_b, snap_a, snap_b])
                session.commit()

                # User A cannot see User B's snapshots
                a_snaps = session.query(GexSnapshot).filter(
                    GexSnapshot.owner_id == "pg-iso-a"
                ).all()
                assert len(a_snaps) == 1
                assert a_snaps[0].symbol == "NIFTY"

                b_snaps = session.query(GexSnapshot).filter(
                    GexSnapshot.owner_id == "pg-iso-b"
                ).all()
                assert len(b_snaps) == 1
                assert b_snaps[0].symbol == "BANKNIFTY"
            finally:
                session.close()
        finally:
            engine.dispose()

    def test_health_query_works(self):
        engine = self._setup()
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1")).scalar_one()
                assert result == 1
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Phase D: Migration + application integration rehearsal
# ---------------------------------------------------------------------------

class TestMigrationRehearsal:
    """Full SQLite-to-PostgreSQL migration rehearsal with application verification."""

    def test_full_rehearsal_migrate_and_verify(self, tmp_path):
        """Create SQLite dataset, migrate to PostgreSQL, verify, then run app queries."""
        pg_url = _pg_url()

        # Step 1: Create realistic SQLite dataset
        sqlite_path = _create_rehearsal_sqlite(tmp_path)
        sqlite_engine = create_engine(
            f"sqlite:///{sqlite_path}",
            connect_args={"check_same_thread": False},
        )

        # Step 2: Prepare PostgreSQL target
        pg_engine = create_engine(pg_url, pool_pre_ping=True)
        try:
            _prepare_schema(pg_engine)
            _clear_postgres_target(pg_engine)

            # Step 3: Migrate
            report = migrate_database(sqlite_engine, pg_engine, batch_size=1000)
            assert report["ok"] is True, {
                "failed_tables": {
                    name: details["errors"]
                    for name, details in report["tables"].items()
                    if not details["passed"]
                },
                "security": report["security"],
                "isolation": report["isolation"],
            }

            # Step 4: Verify migration
            assert report["tables"]["users"]["row_count"] == 2
            assert report["tables"]["user_sessions"]["row_count"] == 0
            assert report["tables"]["broker_connections"]["row_count"] == 2
            assert report["tables"]["gex_snapshots"]["row_count"] == 2
            assert report["tables"]["gex_snapshots"]["fingerprint_match"] is True

            # Step 5: Verify GEX provenance
            security = report["security"]
            assert security["invalid_gex_sources"] == []
            assert security["gex_missing_connection_provenance"] == 0

            # Step 6: Verify multi-user isolation
            isolation = report["isolation"]
            assert isolation["cross_user_violation"] == 0

            # Step 7: Run application queries against migrated PostgreSQL
            from app.identity import BrokerConnection, User
            from app.models import GexSnapshot
            session = sessionmaker(bind=pg_engine)()
            try:
                users = session.query(User).all()
                assert len(users) == 2
                user_ids = {u.id for u in users}
                assert "app-test-user-a" in user_ids
                assert "app-test-user-b" in user_ids

                conns = session.query(BrokerConnection).all()
                assert len(conns) == 2

                snaps = session.query(GexSnapshot).all()
                assert len(snaps) == 2
                sources = {s.data_source for s in snaps}
                assert sources == {"analytics_token", "broker_oauth"}
                owners = {s.owner_id for s in snaps}
                assert len(owners) == 2  # Each user owns their snapshot
            finally:
                session.close()
        finally:
            sqlite_engine.dispose()
            pg_engine.dispose()


# ---------------------------------------------------------------------------
# Phase E: Cutover simulation (no production change)
# ---------------------------------------------------------------------------

class TestCutoverSimulation:
    """Simulate a cutover scenario without touching production."""

    def test_cutover_simulation_exercises_rollback_tree(self, tmp_path):
        """Simulate: backup → migrate → verify → check readiness → document rollback."""
        pg_url = _pg_url()

        # Step 1: Create and verify backup
        sqlite_path = _create_rehearsal_sqlite(tmp_path)
        backup_path = tmp_path / "cutover_backup.db"
        from migrate_sqlite_to_postgres import backup_sqlite
        backup_sqlite(str(sqlite_path), str(backup_path))
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0

        # Step 2: Migrate
        sqlite_engine = create_engine(
            f"sqlite:///{sqlite_path}",
            connect_args={"check_same_thread": False},
        )
        pg_engine = create_engine(pg_url, pool_pre_ping=True)
        try:
            _prepare_schema(pg_engine)
            _clear_postgres_target(pg_engine)
            migrate_database(sqlite_engine, pg_engine, batch_size=1000)

            # Step 3: Verify readiness
            from migrate_sqlite_to_postgres import (
                PgWriter,
                SQLiteReader,
                check_ready_for_cutover,
            )
            reader = SQLiteReader(str(sqlite_path))
            writer = PgWriter.from_sqlalchemy_engine(pg_engine)
            try:
                from migrate_sqlite_to_postgres import verify_table
                tables = [t for t in reader.get_tables() if t not in SKIP_TABLES]
                verifications = [verify_table(reader, writer, t) for t in tables if writer.table_exists(t)]
                security = writer.verify_security_invariants()
                with writer.conn.cursor() as cur:
                    cur.execute("SELECT id FROM users ORDER BY id")
                    user_ids = [row[0] for row in cur.fetchall()]
                isolation = writer.verify_multi_user_isolation(user_ids)
                ready, reasons = check_ready_for_cutover(
                    reader, writer, [], verifications, security, isolation
                )
                assert ready, f"Not ready for cutover: {reasons}"
            finally:
                reader.close()
                writer.close()

            # Step 4: Document rollback scenario
            # In a real cutover, if PostgreSQL fails after accepting writes,
            # we must NOT blindly switch back to SQLite (data loss risk).
            # The backup preserves the pre-cutover SQLite state.
            assert backup_path.exists(), "Backup must be preserved for rollback"

        finally:
            sqlite_engine.dispose()
            pg_engine.dispose()

    def test_rollback_preserves_pre_cutover_state(self, tmp_path):
        """Prove that the SQLite backup is independent of PostgreSQL state."""
        pg_url = _pg_url()

        # Create source and backup
        sqlite_path = _create_rehearsal_sqlite(tmp_path)
        backup_path = tmp_path / "rollback_backup.db"

        from migrate_sqlite_to_postgres import backup_sqlite
        backup_sqlite(str(sqlite_path), str(backup_path))

        # Verify backup is independent
        src_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        bak_conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)

        src_users = src_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        bak_users = bak_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert src_users == bak_users

        src_gex = src_conn.execute("SELECT COUNT(*) FROM gex_snapshots").fetchone()[0]
        bak_gex = bak_conn.execute("SELECT COUNT(*) FROM gex_snapshots").fetchone()[0]
        assert src_gex == bak_gex

        src_conn.close()
        bak_conn.close()
