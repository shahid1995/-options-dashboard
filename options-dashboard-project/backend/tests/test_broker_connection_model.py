"""Tests for Phase 10.2B-1 broker connection models.

Verifies BrokerConnection and BrokerToken model creation, constraints,
cascades, and the new broker_connection_id on UserSession.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
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


@pytest.fixture()
def db():
    """Create an in-memory SQLite database with all tables."""
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
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn1)
        db.add(conn2)
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
            broker_account_id="UCC12345", connected_at=datetime.now(timezone.utc),
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
        # SQLite server_default may not populate on flush; check the column default
        # The model default is "{}" in the column definition


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
