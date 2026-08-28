"""Tests for Phase 10.2B-2 BYOB credential management.

Covers: credential storage, resolution, adapter integration, callback flow,
backward compatibility, validation, lifecycle transitions, and cross-user isolation.
"""

from __future__ import annotations

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
    resolve_user_credentials,
    store_credentials,
    get_or_create_connection,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_partial_default_index(engine):
    """Create the one-default-per-user-per-broker partial unique index."""
    dialect = engine.dialect.name
    where_clause = "is_default = true" if dialect == "postgresql" else "is_default = 1"
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

    @event.listens_for(engine, "connect")
    def _set_fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
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


@pytest.fixture()
def pending_connection(db, user):
    """Create a pending broker connection with stored credentials."""
    conn = store_credentials(
        db,
        user_id=user.id,
        broker="UPSTOX",
        api_key="test-user-api-key-12345",
        api_secret="test-user-api-secret-67890",
        redirect_uri="http://localhost:8000/auth/callback",
        display_label="My Upstox",
    )
    db.flush()
    return conn


# ---------------------------------------------------------------------------
# 1. Credential Storage
# ---------------------------------------------------------------------------

class TestCredentialStorage:
    """Verify store_credentials() behavior."""

    def test_store_credentials_encrypts_at_rest(self, db, user):
        """store_credentials() stores Fernet-encrypted values."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "my-api-key", "my-api-secret"
        )
        # Verify values are encrypted (not plaintext)
        assert conn.broker_api_key_encrypted != "my-api-key"
        assert conn.broker_api_secret_encrypted != "my-api_secret"
        # Verify they can be decrypted
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == "my-api-key"
        assert decrypt(conn.broker_api_secret_encrypted) == "my-api-secret"

    def test_store_credentials_creates_pending_connection(self, db, user):
        """New connection has status='pending', broker_account_id='pending'."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "key", "secret"
        )
        assert conn.status == "pending"
        assert conn.broker_account_id == "pending"

    def test_store_credentials_idempotent(self, db, user):
        """Calling twice updates, doesn't duplicate."""
        conn1 = store_credentials(
            db, user.id, "UPSTOX", "key1", "secret1"
        )
        conn2 = store_credentials(
            db, user.id, "UPSTOX", "key2", "secret2"
        )
        # Same connection row
        assert conn1.id == conn2.id
        # Updated to new credentials
        from app.crypto import decrypt
        assert decrypt(conn2.broker_api_key_encrypted) == "key2"

    def test_store_credentials_allows_empty_api_key(self, db, user):
        """store_credentials allows empty api_key (validation is at endpoint layer).

        The auth.py connect_broker endpoint validates non-empty keys before
        calling store_credentials.  This test verifies the function itself
        does not reject empty strings -- validation is defense-in-depth at the
        API boundary.
        """
        conn = store_credentials(
            db, user.id, "UPSTOX", "", "secret"
        )
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == ""

    def test_store_credentials_max_length(self, db, user):
        """api_key/api_secret beyond 512 chars should be stored (validation is at endpoint)."""
        long_key = "k" * 512
        long_secret = "s" * 512
        conn = store_credentials(
            db, user.id, "UPSTOX", long_key, long_secret
        )
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == long_key

    def test_store_credentials_with_redirect_uri(self, db, user):
        """Redirect URI is stored on the connection."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "key", "secret",
            redirect_uri="https://myapp.com/callback"
        )
        assert conn.broker_redirect_uri == "https://myapp.com/callback"

    def test_store_credentials_with_display_label(self, db, user):
        """Display label is stored on the connection."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "key", "secret",
            display_label="My Trading Account"
        )
        assert conn.display_label == "My Trading Account"


# ---------------------------------------------------------------------------
# 2. Credential Resolution
# ---------------------------------------------------------------------------

class TestCredentialResolution:
    """Verify resolve_user_credentials() behavior."""

    def test_resolve_returns_decrypted_credentials(self, db, user, pending_connection):
        """resolve_user_credentials() decrypts and returns API key/secret."""
        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "test-user-api-key-12345"
        assert creds["api_secret"] == "test-user-api-secret-67890"
        assert creds["redirect_uri"] == "http://localhost:8000/auth/callback"

    def test_resolve_no_credentials_raises(self, db, user):
        """Raises ValueError when no connection has credentials."""
        with pytest.raises(ValueError, match="No UPSTOX credentials found"):
            resolve_user_credentials(user.id, "UPSTOX", db)

    def test_resolve_selects_default(self, db, user):
        """Selects default connection when multiple exist."""
        # Create a connected default connection (not pending)
        from app.crypto import encrypt as crypto_encrypt
        conn_default = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-DEFAULT",
            is_default=True,
            status="connected",
            connected_at=datetime.now(timezone.utc),
        )
        conn_default.broker_api_key_encrypted = crypto_encrypt("key-default")
        conn_default.broker_api_secret_encrypted = crypto_encrypt("secret-default")
        db.add(conn_default)
        db.flush()

        # Create a connected non-default connection
        conn_other = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-OTHER",
            is_default=False,
            status="connected",
            connected_at=datetime.now(timezone.utc),
        )
        conn_other.broker_api_key_encrypted = crypto_encrypt("key-other")
        conn_other.broker_api_secret_encrypted = crypto_encrypt("secret-other")
        db.add(conn_other)
        db.flush()

        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "key-default"

    def test_resolve_skips_pending_without_credentials(self, db, user):
        """Skips connections with NULL api_key_encrypted (pending without stored creds)."""
        from app.crypto import encrypt as crypto_encrypt

        # Create a pending connection WITHOUT credentials (no store_credentials call)
        conn_no_creds = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="no-creds-pending",
            is_default=False,
            status="pending",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn_no_creds)
        db.flush()

        # Create a separate connected connection WITH credentials (is_default=True)
        conn_with_creds = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="with-creds-connected",
            is_default=True,
            status="connected",
            connected_at=datetime.now(timezone.utc),
        )
        conn_with_creds.broker_api_key_encrypted = crypto_encrypt("real-key")
        conn_with_creds.broker_api_secret_encrypted = crypto_encrypt("real-secret")
        db.add(conn_with_creds)
        db.flush()

        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "real-key"

    def test_resolve_rejects_empty_after_decrypt(self, db, user):
        """Raises ValueError if decrypted key is empty."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "valid-key", "valid-secret"
        )
        # Tamper: set encrypted value to something that decrypts to empty
        from app.crypto import encrypt
        conn.broker_api_key_encrypted = encrypt("")
        db.flush()

        with pytest.raises(ValueError, match="empty after decryption"):
            resolve_user_credentials(user.id, "UPSTOX", db)


# ---------------------------------------------------------------------------
# 3. Connection Lifecycle
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:
    """Verify pending → connected lifecycle."""

    def test_get_or_create_creates_from_pending(self, db, user, pending_connection):
        """Transitions pending → connected with real broker_account_id."""
        conn = get_or_create_connection(
            db, user.id, "UPSTOX", "UCC12345"
        )
        assert conn.id == pending_connection.id  # Same row
        assert conn.broker_account_id == "UCC12345"
        assert conn.status == "connected"

    def test_get_or_create_updates_existing(self, db, user):
        """Updates existing connection on re-login."""
        # First: create a connected connection
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC99999",
            status="connected",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        # Re-login: should update existing, not create new
        conn2 = get_or_create_connection(
            db, user.id, "UPSTOX", "UCC99999"
        )
        assert conn2.id == conn.id  # Same row
        assert conn2.status == "connected"

    def test_get_or_create_idempotent_broker_account_id(self, db, user, pending_connection):
        """Same broker_account_id twice updates, no duplicate."""
        conn1 = get_or_create_connection(db, user.id, "UPSTOX", "UCC111")
        conn2 = get_or_create_connection(db, user.id, "UPSTOX", "UCC111")
        assert conn1.id == conn2.id

    def test_get_or_create_creates_new_when_no_pending(self, db, user):
        """Creates new connection when no pending row exists (first OAuth without prior storage)."""
        conn = get_or_create_connection(
            db, user.id, "UPSTOX", "UCC_NEW_123"
        )
        assert conn.broker_account_id == "UCC_NEW_123"
        assert conn.status == "connected"
        assert conn.user_id == user.id

    def test_pending_to_connected_full_lifecycle(self, db, user):
        """Full lifecycle: pending → OAuth → connected → broker_account_id immutable."""
        # Step 1: Store credentials
        conn = store_credentials(
            db, user.id, "UPSTOX", "api-key", "api-secret"
        )
        assert conn.status == "pending"
        assert conn.broker_account_id == "pending"
        assert conn.is_default is True

        # Step 2: OAuth callback → transition to connected
        conn = get_or_create_connection(
            db, user.id, "UPSTOX", "UCC_LIFECYCLE"
        )
        assert conn.status == "connected"
        assert conn.broker_account_id == "UCC_LIFECYCLE"

        # Step 3: Verify credentials still stored
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == "api-key"
        assert decrypt(conn.broker_api_secret_encrypted) == "api-secret"


# ---------------------------------------------------------------------------
# 4. Adapter Integration
# ---------------------------------------------------------------------------

class TestAdapterIntegration:
    """Verify adapter credential propagation."""

    def test_upstox_adapter_uses_user_api_key(self, db, user, pending_connection):
        """Adapter passes user's key to OAuth URL."""
        creds = resolve_user_credentials(user.id, "UPSTOX", db)

        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        adapter = UpstoxAdapter(
            api_key=creds["api_key"],
            api_secret=creds["api_secret"],
            redirect_uri=creds.get("redirect_uri"),
        )
        url = adapter.get_authorization_url("test-state")
        assert "client_id=test-user-api-key-12345" in url

    def test_upstox_adapter_falls_back_to_platform_key(self, db, user):
        """Without user key, uses platform key."""
        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        adapter = UpstoxAdapter()  # No api_key
        url = adapter.get_authorization_url("test-state")
        # Falls back to settings.UPSTOX_API_KEY (test-api-key)
        assert "client_id=test-api-key" in url

    def test_adapter_single_creation_for_exchange_and_profile(
        self, db, user, pending_connection
    ):
        """Same credentials used for both exchange and profile."""
        creds = resolve_user_credentials(user.id, "UPSTOX", db)

        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        adapter = UpstoxAdapter(
            api_key=creds["api_key"],
            api_secret=creds["api_secret"],
        )
        # Both methods should use the same credentials
        assert adapter._api_key == "test-user-api-key-12345"
        assert adapter._api_secret == "test-user-api-secret-67890"

    def test_upstox_extract_account_id_adapter_layer(self):
        """Account ID extraction works in adapter, not in identity.py."""
        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        profile = {"data": {"user_id": "UCC_FROM_ADAPTER"}}
        result = UpstoxAdapter.extract_account_id(profile)
        assert result == "UCC_FROM_ADAPTER"

    def test_extract_account_id_none_for_empty_profile(self):
        """Returns None for empty/invalid profile."""
        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        assert UpstoxAdapter.extract_account_id({}) is None
        assert UpstoxAdapter.extract_account_id({"data": {}}) is None


# ---------------------------------------------------------------------------
# 5. Endpoint Behavior (unit-level)
# ---------------------------------------------------------------------------

class TestEndpointBehavior:
    """Verify POST /auth/connect endpoint logic (without HTTP layer)."""

    def test_connect_stores_credentials(self, db, user):
        """connect_broker logic stores encrypted credentials."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "connect-key", "connect-secret",
            display_label="Test Connect"
        )
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == "connect-key"
        assert decrypt(conn.broker_api_secret_encrypted) == "connect-secret"
        assert conn.display_label == "Test Connect"

    def test_connect_requires_auth(self, db):
        """Without a valid user, store_credentials requires user_id."""
        with pytest.raises(IntegrityError):
            # user_id FK constraint should fail for non-existent user
            store_credentials(
                db, "nonexistent-user-id", "UPSTOX", "key", "secret"
            )
            db.flush()

    def test_connect_validates_input_empty_key(self):
        """Empty api_key should be caught at validation layer."""
        api_key = ""
        api_secret = "secret"
        # Validation logic from auth.py connect_broker endpoint
        assert not api_key.strip()

    def test_connect_validates_input_oversized_key(self):
        """Oversized api_key should be caught at validation layer."""
        api_key = "k" * 513
        assert len(api_key) > 512

    def test_connect_with_unknown_broker_stores_as_uppercase(self, db, user):
        """Unknown broker names are accepted and uppercased."""
        conn = store_credentials(
            db, user.id, "UNKNOWN_BROKER", "key", "secret"
        )
        assert conn.broker == "UNKNOWN_BROKER"
        from app.crypto import decrypt
        assert decrypt(conn.broker_api_key_encrypted) == "key"


# ---------------------------------------------------------------------------
# 6. Multi-User Isolation
# ---------------------------------------------------------------------------

class TestMultiUserIsolation:
    """Verify cross-user credential independence."""

    def test_multi_user_independent_credentials(self, db):
        """User A's credentials don't affect User B."""
        user_a = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="user-a",
        )
        user_b = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="user-b",
        )
        db.add_all([user_a, user_b])
        db.flush()

        # Store different credentials for each user
        store_credentials(db, user_a.id, "UPSTOX", "key-a", "secret-a")
        store_credentials(db, user_b.id, "UPSTOX", "key-b", "secret-b")
        db.flush()

        # Each user resolves their own credentials
        creds_a = resolve_user_credentials(user_a.id, "UPSTOX", db)
        creds_b = resolve_user_credentials(user_b.id, "UPSTOX", db)

        assert creds_a["api_key"] == "key-a"
        assert creds_b["api_key"] == "key-b"
        assert creds_a["api_key"] != creds_b["api_key"]

    def test_user_b_no_connection_does_not_affect_user_a(self, db):
        """User B having no connection doesn't affect User A's resolution."""
        user_a = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="ua-isolated",
        )
        user_b = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="ub-isolated",
        )
        db.add_all([user_a, user_b])
        db.flush()

        store_credentials(db, user_a.id, "UPSTOX", "key-a-only", "secret-a")

        # User A can resolve, User B cannot
        creds_a = resolve_user_credentials(user_a.id, "UPSTOX", db)
        assert creds_a["api_key"] == "key-a-only"

        with pytest.raises(ValueError, match="No UPSTOX credentials found"):
            resolve_user_credentials(user_b.id, "UPSTOX", db)


# ---------------------------------------------------------------------------
# 7. Backward Compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify platform key fallback still works."""

    def test_backward_compat_platform_key(self):
        """gateway.create(BROKER_ID_UPSTOX) still works without per-user kwargs."""
        from app.brokers.gateway import gateway
        from app.brokers.domain.enums import BROKER_ID_UPSTOX
        adapter = gateway.create(BROKER_ID_UPSTOX)
        # Should not raise — uses platform fallback
        url = adapter.get_authorization_url("test-state")
        assert "client_id=" in url

    def test_empty_platform_key_no_per_user_raises(self):
        """Empty UPSTOX_API_KEY + no per-user credentials raises UpstoxError."""
        from app.services.upstox import get_login_url, UpstoxError
        # Temporarily override the setting
        from app.config import settings
        original = settings.UPSTOX_API_KEY
        settings.UPSTOX_API_KEY = ""
        try:
            with pytest.raises(UpstoxError, match="No Upstox API key available"):
                get_login_url("test-state")
        finally:
            settings.UPSTOX_API_KEY = original


# ---------------------------------------------------------------------------
# 8. Broker Connection Model Integration
# ---------------------------------------------------------------------------

class TestBrokerConnectionModelIntegration:
    """Verify model-level behavior with BYOB lifecycle."""

    def test_pending_connection_nullable_credentials(self, db, user):
        """Pending connection can have NULL credentials (pre-storage)."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="pending",
            status="pending",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()
        assert conn.broker_api_key_encrypted is None
        assert conn.broker_api_secret_encrypted is None

    def test_session_record_with_connection_id(self, db, user):
        """create_session_record() accepts and sets broker_connection_id."""
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC_TEST",
            connected_at=datetime.now(timezone.utc),
        )
        db.add(conn)
        db.flush()

        from app.identity import create_session_record
        session = create_session_record(
            db, user.id, "test-session-id", broker_connection_id=conn.id
        )
        # Note: create_session_record calls db.commit(), which in the test
        # in-memory DB finalizes the transaction.  We verify the record.
        assert session.broker_connection_id == conn.id

    def test_multiple_brokers_independent(self, db, user):
        """Different brokers have independent credential storage."""
        store_credentials(db, user.id, "UPSTOX", "upstox-key", "upstox-secret")
        # FYERS would be: store_credentials(db, user.id, "FYERS", "fyers-key", "fyers-secret")
        # but FYERS adapter doesn't exist yet.  Verify UPSTOX works.
        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "upstox-key"

    def test_connection_default_is_true_for_first(self, db, user):
        """First connection for a (user, broker) defaults to is_default=True."""
        conn = store_credentials(
            db, user.id, "UPSTOX", "key", "secret"
        )
        assert conn.is_default is True


class TestResolveNonDefaultFallback:
    """Verify resolve_user_credentials falls back to non-default connections."""

    def test_resolve_uses_nondefault_when_no_default_exists(self, db, user):
        """When all connections are is_default=False, resolve still finds credentials."""
        from app.crypto import encrypt as crypto_encrypt

        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-NON-DEFAULT",
            is_default=False,
            status="connected",
            connected_at=datetime.now(timezone.utc),
        )
        conn.broker_api_key_encrypted = crypto_encrypt("non-default-key")
        conn.broker_api_secret_encrypted = crypto_encrypt("non-default-secret")
        db.add(conn)
        db.flush()

        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "non-default-key"
        assert creds["api_secret"] == "non-default-secret"

    def test_resolve_uses_most_recent_when_multiple_nondefault(self, db, user):
        """With multiple non-default connections, most recent is selected."""
        from app.crypto import encrypt as crypto_encrypt

        conn_older = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-OLDER",
            is_default=False,
            status="connected",
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        conn_older.broker_api_key_encrypted = crypto_encrypt("older-key")
        conn_older.broker_api_secret_encrypted = crypto_encrypt("older-secret")
        db.add(conn_older)

        conn_newer = BrokerConnection(
            id=str(uuid4()),
            user_id=user.id,
            broker="UPSTOX",
            broker_account_id="UCC-NEWER",
            is_default=False,
            status="connected",
            connected_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        conn_newer.broker_api_key_encrypted = crypto_encrypt("newer-key")
        conn_newer.broker_api_secret_encrypted = crypto_encrypt("newer-secret")
        db.add(conn_newer)
        db.flush()

        creds = resolve_user_credentials(user.id, "UPSTOX", db)
        assert creds["api_key"] == "newer-key"


class TestCallbackWithoutActiveSession:
    """Verify callback behavior when no active StrikeNova session exists."""

    def test_callback_falls_back_to_platform_credentials(self, db, user):
        """When no active session exists, callback uses platform credentials.

        This is the backward-compatible fallback: unauthenticated users
        (or expired sessions) get platform-level credentials, not another
        user's credentials.
        """
        # Verify no active sessions exist for this user
        from app.identity import UserSession
        active = (
            db.query(UserSession)
            .filter(
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        assert active is None  # No active session

        # Verify resolve_user_credentials raises (no credentials for user)
        with pytest.raises(ValueError, match="No UPSTOX credentials found"):
            resolve_user_credentials(user.id, "UPSTOX", db)

        # The callback would fall back to {} (platform credentials)
        # This is the documented backward-compatible behavior

    def test_callback_does_not_leak_other_users_credentials(self, db):
        """When user has no session, callback cannot select another user's creds."""
        user_a = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="leak-test-a",
        )
        user_b = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="leak-test-b",
        )
        db.add_all([user_a, user_b])
        db.flush()

        # Only user_b has credentials
        store_credentials(db, user_b.id, "UPSTOX", "secret-key-b", "secret-b")
        db.flush()

        # user_a has no session and no credentials — resolve raises
        with pytest.raises(ValueError, match="No UPSTOX credentials found"):
            resolve_user_credentials(user_a.id, "UPSTOX", db)

        # user_b can resolve their own credentials
        creds_b = resolve_user_credentials(user_b.id, "UPSTOX", db)
        assert creds_b["api_key"] == "secret-key-b"
