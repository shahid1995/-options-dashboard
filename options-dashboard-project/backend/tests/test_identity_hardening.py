"""Tests for feat/identity-capability-hardening.

Covers:
1. Data-only → broker login lifecycle
2. Per-user market-data authorization (no cross-user token leakage)
3. Capability state machine
4. Durable session persistence (survives in-memory loss)
5. Default connection concurrency safety
"""

import time
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.identity import (
    BrokerConnection,
    BrokerToken,
    User,
    UserSession,
    create_session_record,
    get_analytics_token,
    get_or_create_connection,
    revoke_session,
    store_analytics_token,
    store_credentials,
    hash_session_id,
)
from app.services.token_store import set_token, get_token, clear_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def db_session():
    """In-memory SQLite for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def user_a(db_session):
    u = User(id="user-a", email="a@test.com", display_name="A")
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def user_b(db_session):
    u = User(id="user-b", email="b@test.com", display_name="B")
    db_session.add(u)
    db_session.flush()
    return u


# ---------------------------------------------------------------------------
# 1. DATA-ONLY → BROKER LOGIN LIFECYCLE
# ---------------------------------------------------------------------------

class TestDataOnlyLifecycle:
    """Verify the data-only → broker credentials → OAuth lifecycle."""

    def test_brand_new_user_gets_data_only_connection(self, db_session, user_a):
        """Storing an analytics token creates a data-only connection."""
        conn = store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_abc")
        assert conn.broker_account_id == "data-only"
        assert conn.status == "connected"
        assert conn.data_status == "active"
        assert conn.data_source == "analytics_token"
        assert conn.is_default is True

    def test_data_only_to_broker_credentials_transitions(self, db_session, user_a):
        """store_credentials must find and upgrade a data-only connection."""
        # Create data-only connection
        data_conn = store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_data")
        assert data_conn.broker_account_id == "data-only"

        # Store broker credentials — should find the data-only connection
        cred_conn = store_credentials(
            db_session, user_a.id, "UPSTOX", "api_key_123", "api_secret_456"
        )
        # The connection should be the same row (updated, not duplicated)
        assert cred_conn.id == data_conn.id
        # Analytics token must be preserved
        assert cred_conn.broker_analytics_token_encrypted is not None

    def test_data_only_to_oauth_preserves_analytics_token(self, db_session, user_a):
        """After OAuth completion, the analytics token must still be usable."""
        # Create data-only connection with analytics token
        data_conn = store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_analytics")

        # Simulate OAuth completion — get_or_create_connection
        oauth_conn = get_or_create_connection(
            db_session, user_a.id, "UPSTOX", "real_account_123"
        )
        assert oauth_conn.status == "connected"
        assert oauth_conn.broker_account_id == "real_account_123"

        # The connection should be the same row or should have preserved the analytics token
        # Check if analytics token is still accessible
        token = get_analytics_token(db_session, user_a.id, "UPSTOX")
        assert token == "tok_analytics"

    def test_trading_remains_inactive_after_broker_oauth(self, db_session, user_a):
        """OAuth completion does NOT automatically enable trading."""
        store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_data")
        conn = get_or_create_connection(db_session, user_a.id, "UPSTOX", "acct_123")
        # trading_status should remain inactive
        assert conn.trading_status == "inactive"

    def test_only_one_default_per_user_broker(self, db_session, user_a):
        """Partial unique index enforces one default per (user, broker)."""
        store_analytics_token(db_session, user_a.id, "UPSTOX", "tok1")
        # Second connection for same user/broker should not create another default
        conn2 = BrokerConnection(
            id=str(secrets.token_urlsafe(16)),
            user_id=user_a.id,
            broker="UPSTOX",
            broker_account_id="second_account",
            is_default=False,
        )
        db_session.add(conn2)
        db_session.flush()
        # Verify only one default exists
        defaults = (
            db_session.query(BrokerConnection)
            .filter(
                BrokerConnection.user_id == user_a.id,
                BrokerConnection.broker == "UPSTOX",
                BrokerConnection.is_default == True,
            )
            .all()
        )
        assert len(defaults) == 1

    def test_repeated_credential_storage_is_idempotent(self, db_session, user_a):
        """Storing credentials twice on same connection doesn't duplicate."""
        conn1 = store_credentials(db_session, user_a.id, "UPSTOX", "key1", "sec1")
        conn2 = store_credentials(db_session, user_a.id, "UPSTOX", "key1", "sec1")
        assert conn1.id == conn2.id

    def test_data_only_cannot_trade(self, db_session, user_a):
        """A data-only connection must not enable trading."""
        conn = store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_data")
        assert conn.trading_status == "inactive"
        assert conn.broker_account_id == "data-only"


# ---------------------------------------------------------------------------
# 2. PER-USER MARKET-DATA AUTHORIZATION
# ---------------------------------------------------------------------------

class TestPerUserAuthorization:
    """Verify no cross-user token leakage."""

    def test_user_a_token_not_returned_for_user_b(self, db_session, user_a, user_b):
        """Analytics Token for User A must not resolve for User B."""
        store_analytics_token(db_session, user_a.id, "UPSTOX", "secret_token_a")
        token_b = get_analytics_token(db_session, user_b.id, "UPSTOX")
        assert token_b is None

    def test_user_a_cannot_resolve_user_b_credentials(self, db_session, user_a, user_b):
        """User A cannot access User B's broker credentials via resolve_user_credentials."""
        store_credentials(db_session, user_b.id, "UPSTOX", "key_b", "secret_b")
        from app.identity import resolve_user_credentials
        with pytest.raises(ValueError, match="No UPSTOX credentials found for user user-a"):
            resolve_user_credentials(user_a.id, "UPSTOX", db_session)

    def test_inactive_data_status_blocks_data_authorization(self, db_session, user_a):
        """data_status != active blocks analytics token retrieval."""
        conn = store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_abc")
        conn.data_status = "inactive"
        db_session.flush()
        token = get_analytics_token(db_session, user_a.id, "UPSTOX")
        assert token is None

    def test_removed_analytics_token_cannot_be_used(self, db_session, user_a):
        """After removing analytics token, get returns None."""
        store_analytics_token(db_session, user_a.id, "UPSTOX", "tok_abc")
        from app.identity import remove_analytics_token
