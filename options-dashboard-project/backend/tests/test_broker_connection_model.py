"""Tests for Phase 10.2B-1 broker connection models.

Verifies BrokerConnection and BrokerToken model creation, constraints,
cascades, the new broker_connection_id on UserSession, broker_account_id
lifecycle, the one-default-per-user-per-broker invariant, and
migration-vs-ORM default parity.
"""

import pathlib
import textwrap
import pytest
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.identity import (
    User,
    UserSession,
    BrokerConnection,
    BrokerToken,
    hash_session_id,
)


def _create_partial_default_index(engine):
    """Create the one-default-per-user-per-broker partial unique index.

    The partial index is ONLY defined in the Alembic migration (not in ORM
    metadata) because cross-dialect WHERE clauses (PostgreSQL: true,
    SQLite: 1) cannot be expressed portably in SQLAlchemy metadata.
    Tests that need this invariant enforced must call this helper after
    Base.metadata.create_all().
    """
    dialect = engine.dialect.name
    if dialect == "postgresql":
        where_clause = "is_default = true"
    else:
        where_clause = "is_default = 1"
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE UNIQUE INDEX uq_one_default_per_user_broker "
            f"ON broker_connections (user_id, broker) "
            f"WHERE {where_clause}"
        ))


@pytest.fixture()
def db():
    """Create an in-memory SQLite database with all tables + partial index."""
    from sqlalchemy import event

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Enable foreign key enforcement for SQLite (off by default)
    @event.listens_for(engine, "connect")
    def _set_fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")
    Base.metadata.create_all(engine)
    # Create the partial unique index that Alembic migration creates in prod
    _create_partial_default_index(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def user(db):
    """Create a test user."""
    user_id = str(uuid4())
    user = User(
        id=user_id,
        status="active",
        identity_source="upstox",
        broker_provider="UPSTOX",
        broker_user_id=f"test-{user_id[:8]}",
    )
    db.add(user)
    db.flush()
    return user


class TestBrokerConnectionModel:
    """Verify BrokerConnection table structure and constraints."""

    def test_table_exists(self, db):
        """broker_connections table must exist."""
        insp = inspect(db.get_bind())
        assert "broker_connections" in insp.get_table_names()

    def test_create_connection(self, db, user):
        """Can create a BrokerConnection with all required fields."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            display_label="My Upstox Account",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.id is not None
        assert conn.is_default is True
        assert conn.status == "connected"
        assert conn.capability_mode == "trading"

    def test_nullable_credentials(self, db, user):
        """Credential columns must be nullable (added after connection creation)."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.broker_api_key_encrypted is None
        assert conn.broker_api_secret_encrypted is None
        assert conn.broker_analytics_token_encrypted is None
        assert conn.broker_redirect_uri is None
        assert conn.broker_static_ip is None

    def test_unique_constraint(self, db, user):
        """Duplicate (user_id, broker, broker_account_id) must raise IntegrityError."""
        conn1 = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",  # Same
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn1)
        db.flush()
        db.add(conn2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_different_broker_same_account_allowed(self, db, user):
        """Same account_id with different broker is allowed."""
        conn1 = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="FYERS",
            broker_account_id="UCC12345",  # Same account_id, different broker
            is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise

    def test_different_users_same_account_allowed(self, db):
        """Different users can have connections to the same broker account."""
        user1 = User(id=str(uuid4()), status="active", identity_source="upstox",
                      broker_provider="UPSTOX", broker_user_id="u1")
        user2 = User(id=str(uuid4()), status="active", identity_source="upstox",
                      broker_provider="UPSTOX", broker_user_id="u2")
        db.add_all([user1, user2])
        db.flush()

        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user1.id, broker="UPSTOX",
            broker_account_id="UCC12345", connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user2.id, broker="UPSTOX",
            broker_account_id="UCC12345", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise

    def test_provider_metadata_json_default(self, db, user):
        """provider_metadata_json must default to '{}'."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()


class TestBrokerAccountIdLifecycle:
    """Verify broker_account_id creation lifecycle and immutability.

    broker_account_id is the upstream broker's account identifier
    (e.g. Upstox user_id, FYERS app_id).  It is:
      - Required (NOT NULL) at connection creation
      - Populated from the broker OAuth profile
      - Immutable after creation (part of unique constraint)
    """

    def test_required_not_null(self, db, user):
        """broker_account_id must be required (NOT NULL)."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.broker_account_id == "UCC12345"

    def test_not_nullable_at_database_level(self, db):
        """Attempting to insert NULL broker_account_id must raise IntegrityError."""
        bare_user = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="bare-user",
        )
        db.add(bare_user)
        db.flush()

        # Use raw SQL to bypass ORM defaults and attempt NULL insert.
        # IntegrityError is raised immediately by SQLite, not at flush.
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO broker_connections "
                    "(id, user_id, broker, broker_account_id, "
                    " is_default, status, capability_mode, provider_metadata_json,"
                    " created_at, updated_at, connected_at) "
                    "VALUES (:id, :user_id, :broker, NULL, "
                    " 1, 'connected', 'trading', '{}', :now, :now, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": bare_user.id,
                    "broker": "UPSTOX",
                    "now": datetime.now(timezone.utc),
                },
            )

    def test_unique_per_user_broker(self, db, user):
        """Same (user_id, broker, broker_account_id) must not be creatable twice."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC99999", connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC99999", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn1)
        db.flush()
        db.add(conn2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_different_account_ids_allowed(self, db, user):
        """Different account_ids for the same (user, broker) must be allowed."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC11111", connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC22222", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise

    def test_account_id_set_from_oauth_profile(self, db, user):
        """Lifecycle: connection created with account_id from broker profile, then
        credentials are added in a subsequent step (two-phase creation)."""
        # Phase 1: Create connection with just the account_id (no credentials yet)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC_FROM_OAUTH",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.broker_account_id == "UCC_FROM_OAUTH"
        assert conn.broker_api_key_encrypted is None

        # Phase 2: Add encrypted credentials (simulating store_credentials)
        from app.crypto import encrypt
        conn.broker_api_key_encrypted = encrypt("user-api-key")
        conn.broker_api_secret_encrypted = encrypt("user-api-secret")
        db.flush()

        assert conn.broker_api_key_encrypted is not None
        assert conn.broker_api_secret_encrypted is not None


class TestBrokerTokenModel:
    """Verify BrokerToken table structure and constraints."""

    def test_table_exists(self, db):
        """broker_tokens table must exist."""
        insp = inspect(db.get_bind())
        assert "broker_tokens" in insp.get_table_names()

    def test_create_token(self, db, user):
        """Can create a BrokerToken linked to a BrokerConnection."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        token = BrokerToken(
            connection_id=conn.id,
            session_hash="abc123",
            broker_token_encrypted="encrypted-token-value",
            broker_token_expires_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(token)
        db.flush()
        assert token.id is not None

    def test_unique_constraint(self, db, user):
        """Duplicate (connection_id, session_hash) must raise IntegrityError."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        t1 = BrokerToken(
            connection_id=conn.id, session_hash="abc123",
            created_at=datetime.now(timezone.utc),
        )
        t2 = BrokerToken(
            connection_id=conn.id, session_hash="abc123",  # Same
            created_at=datetime.now(timezone.utc),
        )
        db.add(t1)
        db.flush()
        db.add(t2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_cascade_delete(self, db, user):
        """Deleting BrokerConnection must cascade to BrokerTokens."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        token = BrokerToken(
            connection_id=conn.id, session_hash="abc123",
            created_at=datetime.now(timezone.utc),
        )
        db.add(token)
        db.flush()

        # Delete the connection
        db.delete(conn)
        db.flush()

        # Token must be gone
        remaining = db.query(BrokerToken).filter_by(connection_id=conn.id).count()
        assert remaining == 0

    def test_nullable_token_fields(self, db, user):
        """Token fields must be nullable (populated after OAuth)."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="FYERS",
            broker_account_id="FYERS-123",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        token = BrokerToken(
            connection_id=conn.id, session_hash="def456",
            created_at=datetime.now(timezone.utc),
        )
        db.add(token)
        db.flush()
        assert token.broker_token_encrypted is None
        assert token.broker_token_expires_at is None
        assert token.broker_refresh_token_encrypted is None
        assert token.broker_refresh_token_expires_at is None


class TestUserSessionBrokerConnection:
    """Verify the new broker_connection_id column on user_sessions."""

    def test_column_exists(self, db):
        """user_sessions must have broker_connection_id column."""
        insp = inspect(db.get_bind())
        cols = [c["name"] for c in insp.get_columns("user_sessions")]
        assert "broker_connection_id" in cols

    def test_nullable_by_default(self, db, user):
        """Existing sessions can have NULL broker_connection_id."""
        session = UserSession(
            user_id=user.id,
            session_hash=hash_session_id("test-session-123"),
            expires_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()
        assert session.broker_connection_id is None

    def test_can_set_connection(self, db, user):
        """broker_connection_id can reference a BrokerConnection."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC12345",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        session = UserSession(
            user_id=user.id,
            session_hash=hash_session_id("test-session-456"),
            expires_at=datetime.now(timezone.utc),
            broker_connection_id=conn.id,
        )
        db.add(session)
        db.flush()
        assert session.broker_connection_id == conn.id

    def test_invalid_connection_id_raises(self, db, user):
        """Setting broker_connection_id to non-existent ID raises IntegrityError."""
        session = UserSession(
            user_id=user.id,
            session_hash=hash_session_id("test-session-789"),
            expires_at=datetime.now(timezone.utc),
            broker_connection_id="non-existent-uuid",
        )
        db.add(session)
        with pytest.raises(IntegrityError):
            db.flush()


class TestOneDefaultPerUserBroker:
    """Verify the one-default-per-user-per-broker invariant.

    At most one BrokerConnection per (user_id, broker) may have
    is_default=True.  Enforced by partial unique index
    uq_one_default_per_user_broker (created in the Alembic migration
    and replicated in the db fixture via _create_partial_default_index).
    """

    def test_partial_index_exists(self, db):
        """The partial unique index uq_one_default_per_user_broker must exist in DB."""
        insp = inspect(db.get_bind())
        indexes = insp.get_indexes("broker_connections")
        index_names = [idx["name"] for idx in indexes]
        assert "uq_one_default_per_user_broker" in index_names

    def test_multiple_defaults_violates_invariant(self, db, user):
        """Two connections with is_default=True for same (user, broker) must fail."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-DEF-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-DEF-2", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn1)
        db.flush()
        db.add(conn2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_one_default_one_nondefault_allowed(self, db, user):
        """One default + one non-default for same (user, broker) must be allowed."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-MIX-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-MIX-2", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise

    def test_multiple_nondefaults_allowed(self, db, user):
        """Multiple non-default connections for same (user, broker) must be allowed."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-NON-1", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-NON-2", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise

    def test_defaults_independent_across_brokers(self, db, user):
        """Each broker can have its own default — UPSTOX default != FYERS default."""
        conn_upstox = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-IND-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        conn_fyers = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="FYERS",
            broker_account_id="FYERS-IND-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn_upstox, conn_fyers])
        db.flush()  # Should not raise — different brokers

    def test_defaults_independent_across_users(self, db):
        """Each user can have their own default — user A default != user B default."""
        user1 = User(id=str(uuid4()), status="active", identity_source="upstox",
                      broker_provider="UPSTOX", broker_user_id="u-default-1")
        user2 = User(id=str(uuid4()), status="active", identity_source="upstox",
                      broker_provider="UPSTOX", broker_user_id="u-default-2")
        db.add_all([user1, user2])
        db.flush()

        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user1.id, broker="UPSTOX",
            broker_account_id="UCC-USER-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user2.id, broker="UPSTOX",
            broker_account_id="UCC-USER-2", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()  # Should not raise — different users

    def test_switching_default_is_valid(self, db, user):
        """Switching default from conn1 to conn2 is a valid operation."""
        conn1 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-SW-1", is_default=True,
            connected_at=datetime.now(timezone.utc),
        )
        conn2 = BrokerConnection(
            id=str(uuid4()), user_id=user.id, broker="UPSTOX",
            broker_account_id="UCC-SW-2", is_default=False,
            connected_at=datetime.now(timezone.utc),
        )
        db.add_all([conn1, conn2])
        db.flush()

        # Switch default in two steps: clear old first, then set new.
        # SQLite evaluates partial unique indexes per-statement; flushing
        # both changes atomically would momentarily satisfy the invariant
        # violation (both rows is_default=1) before the DELETE side takes
        # effect.  Two separate flushes avoid this.
        conn1.is_default = False
        db.flush()  # Step 1: no defaults exist — clean state

        conn2.is_default = True
        db.flush()  # Step 2: exactly one default — invariant holds


class TestMigrationVsORMDefaultParity:
    """Verify that migration server_defaults match ORM column defaults.

    Audit finding: migration and ORM defaults must agree. If they diverge,
    INSERT without explicit values would silently produce different data
    depending on the code path (ORM vs raw SQL / migration backfill).

    The migration uses server_default (DDL-level), while the ORM uses
    default (Python-level).  Both must agree on the value.
    """

    def test_is_default_parity(self, db, user):
        """ORM default for is_default must match migration server_default (True/1)."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-PARITY-1",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.is_default is True

    def test_status_parity(self, db, user):
        """ORM default for status must match migration server_default ('connected')."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-PARITY-2",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.status == "connected"

    def test_capability_mode_parity(self, db, user):
        """ORM default for capability_mode must match migration server_default ('trading')."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-PARITY-3",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.capability_mode == "trading"

    def test_provider_metadata_json_parity(self, db, user):
        """ORM default for provider_metadata_json must match migration server_default ('{}')."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-PARITY-4",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.provider_metadata_json == "{}"

    def test_migration_server_defaults_in_source(self):
        """Source-level contract: migration file must declare matching server_defaults.

        This test reads the migration source and verifies that the expected
        server_default values appear.  If someone changes a server_default in
        the migration without updating the ORM model (or vice versa), this
        test catches the drift at the source level.
        """
        migration_path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "alembic" / "versions"
            / "125e1807df8d_add_broker_connection_foundation.py"
        )
        source = migration_path.read_text()

        # Verify the migration server_default values
        assert "server_default='1'" in source, (
            "is_default server_default='1' missing from migration"
        )
        assert "server_default='connected'" in source, (
            "status server_default='connected' missing from migration"
        )
        assert "server_default='trading'" in source, (
            "capability_mode server_default='trading' missing from migration"
        )
        assert "server_default='{}'" in source, (
            "provider_metadata_json server_default='{}' missing from migration"
        )

    def test_orm_defaults_match_migration(self):
        """Source-level contract: ORM model defaults must match migration server_defaults.

        Reads the ORM model source to verify that the Python-side default
        values agree with the database-side server_default values in the
        migration.  This catches drift between ORM and migration.
        """
        identity_path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app" / "identity.py"
        )
        source = identity_path.read_text(encoding="utf-8")

        # Verify ORM defaults match migration server_defaults
        # is_default: ORM default=True matches migration server_default='1'
        assert "is_default: Mapped[bool] = mapped_column(default=True)" in source, (
            "ORM is_default must have default=True"
        )
        # status: ORM default='connected' matches migration server_default='connected'
        assert 'default="connected"' in source, (
            'ORM status must have default="connected"'
        )
        # capability_mode: ORM default='trading' matches migration server_default='trading'
        assert 'default="trading"' in source, (
            'ORM capability_mode must have default="trading"'
        )
        # provider_metadata_json: ORM default='{}' matches migration server_default='{}'
        assert 'default="{}"' in source, (
            'ORM provider_metadata_json must have default="{}"'
        )
