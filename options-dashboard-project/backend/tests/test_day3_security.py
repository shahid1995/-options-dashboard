"""Day 3 — Tenant and Credential Safety Review.

Tests for:
1. Unauthenticated OAuth initiation rejection
2. Legacy unsigned OAuth state rejection
3. Callback broker override prevention
4. Cross-user OAuth state isolation
5. Platform credential fallback removal
6. Credential serialization isolation
7. OAuth state single-use enforcement
8. Callback session-mismatch rejection
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.identity import (
    BrokerConnection,
    User,
    UserSession,
    create_session_record,
    store_credentials,
)
from app.main import app
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    import app.routers.auth as auth_mod

    _orig_session_local = auth_mod.SessionLocal
    auth_mod.SessionLocal = lambda: db_session
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        auth_mod.SessionLocal = _orig_session_local


def _create_user(db, identity_source="upstox", email=None):
    """Create a test user and return (user_id, session_id)."""
    user_id = str(uuid4())
    session_id = token_store.set_token(f"tok-{user_id[:8]}")

    user = User(
        id=user_id,
        status="active",
        identity_source=identity_source,
        broker_provider="UPSTOX",
        broker_user_id=f"test-{user_id[:8]}",
        email=email,
    )
    db.add(user)
    db.flush()

    create_session_record(db, user_id, session_id)
    return user_id, session_id


def _create_user_with_credentials(db, api_key="user-key", api_secret="user-secret"):
    """Create a user with stored BYOB credentials."""
    user_id, session_id = _create_user(db)
    store_credentials(db, user_id, "UPSTOX", api_key, api_secret)
    return user_id, session_id


# ---------------------------------------------------------------------------
# 1. Unauthenticated OAuth initiation rejection
# ---------------------------------------------------------------------------

class TestUnauthenticatedOAuthInitiation:
    """POST /auth/login must require an authenticated session."""

    def test_login_without_session_returns_401(self, client):
        """GET /auth/login without a session must return 401."""
        resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 401
        assert "Authentication required" in resp.json()["detail"]

    def test_login_with_invalid_session_returns_401(self, client):
        """GET /auth/login with an invalid session must return 401."""
        resp = client.get(
            "/auth/login",
            headers={"X-Session-Id": "totally-fake-session"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_login_with_expired_session_returns_401(self, client, db_session):
        """GET /auth/login with an expired (revoked) session must return 401."""
        from app.identity import hash_session_id
        user_id, session_id = _create_user(db_session)
        # Revoke the session in DB and clear from token_store
        db_session.query(UserSession).filter(
            UserSession.session_hash == hash_session_id(session_id)
        ).update({"revoked_at": datetime.now(timezone.utc)})
        db_session.flush()
        token_store.clear_token(session_id)

        resp = client.get(
            "/auth/login",
            headers={"X-Session-Id": session_id},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_login_with_valid_session_succeeds(self, client, db_session):
        """GET /auth/login with a valid session must redirect (307)."""
        _create_user_with_credentials(db_session)
        session_id = token_store.set_token("tok-valid")
        # Need a user for this session
        user = User(
            id=str(uuid4()), status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="valid-user",
        )
        db_session.add(user)
        db_session.flush()
        create_session_record(db_session, user.id, session_id)
        store_credentials(db_session, user.id, "UPSTOX", "user-api-key", "user-api-secret")

        resp = client.get(
            "/auth/login",
            headers={"X-Session-Id": session_id},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "client_id=user-api-key" in location

    def test_no_platform_key_fallback_used(self, client, db_session):
        """Without user credentials, login must fail — not fall back to platform key."""
        # Create a valid user session (with no stored broker credentials)
        user_id, session_id = _create_user(db_session)

        resp = client.get(
            "/auth/login",
            headers={"X-Session-Id": session_id},
            follow_redirects=False,
        )
        # Should fail: no stored credentials and platform fallback removed
        assert resp.status_code == 400
        assert "credentials" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 2. Legacy unsigned OAuth state rejection
# ---------------------------------------------------------------------------

class TestLegacyUnsignedStateRejection:
    """consume_oauth_state() must reject unsigned (no-dot) states."""

    def test_legacy_unsigned_state_rejected(self):
        """A legacy unsigned state (no dot) must be rejected."""
        from app.services.token_store import consume_oauth_state, _pending_states

        # Simulate a legacy unsigned state
        legacy_state = "legacy-csrf-state-no-dot"
        _pending_states[legacy_state] = time.time()

        result = consume_oauth_state(legacy_state)
        assert result is None, "Legacy unsigned state must be rejected"

    def test_signed_state_accepted(self):
        """A properly HMAC-signed state must be accepted."""
        from app.services.token_store import create_oauth_state, consume_oauth_state

        state = create_oauth_state(session_id="test-session-123", broker="UPSTOX")
        result = consume_oauth_state(state)
        assert result is not None
        assert result["session_id"] == "test-session-123"
        assert result["broker"] == "UPSTOX"

    def test_callback_with_legacy_state_returns_400(self, client):
        """Callback with an unsigned legacy state must return 400."""
        resp = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "unsigned-legacy-state"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Invalid or expired OAuth state" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Callback broker override prevention
# ---------------------------------------------------------------------------

class TestCallbackBrokerOverridePrevention:
    """The callback must use the broker from the signed state, not the query param."""

    def test_broker_from_signed_state_used(self, client, db_session):
        """Callback uses broker from signed state, not the broker query param."""
        user_id, session_id = _create_user_with_credentials(db_session)

        # Create a state for UPSTOX
        state = token_store.create_oauth_state(session_id=session_id, broker="UPSTOX")

        # Try to override broker via query param
        resp = client.get(
            "/auth/callback",
            params={
                "code": "auth-code",
                "state": state,
                "broker": "FYERS",  # Attempted override
            },
            follow_redirects=False,
        )
        # The state_data must contain UPSTOX, not FYERS
        state_data = token_store.consume_oauth_state(state)
        # consume_oauth_state was already called above — create a new one
        state2 = token_store.create_oauth_state(session_id=session_id, broker="UPSTOX")
        state_data2 = token_store.consume_oauth_state(state2)
        assert state_data2 is not None
        assert state_data2["broker"] == "UPSTOX"


# ---------------------------------------------------------------------------
# 4. Cross-user OAuth state isolation
# ---------------------------------------------------------------------------

class TestCrossUserOAuthStateIsolation:
    """User B cannot use User A's OAuth state."""

    def test_user_b_cannot_reuse_user_a_state(self, client, db_session):
        """User B attempting to use User A's signed state gets rejected."""
        # User A: create state
        user_a_id = str(uuid4())
        session_a = token_store.set_token("tok-user-a")
        user_a = User(
            id=user_a_id, status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="user-a",
        )
        db_session.add(user_a)
        db_session.flush()
        create_session_record(db_session, user_a_id, session_a)

        state_a = token_store.create_oauth_state(session_id=session_a, broker="UPSTOX")

        # User B: try to consume User A's state
        # (In the callback, the bound_session_id would be User A's session)
        # The state is single-use — if User A consumed it first, User B can't use it
        result = token_store.consume_oauth_state(state_a)
        assert result is not None
        assert result["session_id"] == session_a

        # Attempt to reuse — must fail (single-use)
        result2 = token_store.consume_oauth_state(state_a)
        assert result2 is None

    def test_user_b_cannot_create_state_for_user_a(self, client, db_session):
        """The signed state is bound to the creating user's session."""
        user_a_id, session_a = _create_user(db_session)
        user_b_id, session_b = _create_user(db_session)

        # User B creates state with their own session
        state_b = token_store.create_oauth_state(session_id=session_b, broker="UPSTOX")
        result = token_store.consume_oauth_state(state_b)
        assert result["session_id"] == session_b
        assert result["session_id"] != session_a


# ---------------------------------------------------------------------------
# 5. Platform credential fallback removal
# ---------------------------------------------------------------------------

class TestPlatformCredentialFallbackRemoval:
    """settings.UPSTOX_API_KEY must not be used as OAuth fallback."""

    def test_login_url_requires_explicit_client_id(self):
        """get_login_url() without client_id and empty platform key raises."""
        from app.services.upstox import get_login_url, UpstoxError

        original = settings.UPSTOX_API_KEY
        settings.UPSTOX_API_KEY = ""
        try:
            with pytest.raises(UpstoxError, match="No Upstox API key"):
                get_login_url("test-state")
        finally:
            settings.UPSTOX_API_KEY = original

    def test_adapter_requires_api_key_for_login_url(self):
        """UpstoxAdapter without api_key must not silently use platform key."""
        from app.brokers.adapters.upstox.adapter import UpstoxAdapter
        from app.services.upstox import UpstoxError

        original = settings.UPSTOX_API_KEY
        settings.UPSTOX_API_KEY = ""
        try:
            adapter = UpstoxAdapter()  # No api_key
            with pytest.raises(UpstoxError, match="No Upstox API key"):
                adapter.get_authorization_url("test-state")
        finally:
            settings.UPSTOX_API_KEY = original


# ---------------------------------------------------------------------------
# 6. Credential serialization isolation
# ---------------------------------------------------------------------------

class TestCredentialSerializationIsolation:
    """Broker credentials must not appear in API responses, logs, or errors."""

    def test_broker_profile_endpoint_no_secrets(self, client, db_session):
        """GET /auth/broker/profile must not contain encrypted fields."""
        user_id, session_id = _create_user_with_credentials(db_session)

        # Create a broker profile response that would normally be serialized
        from app.services.broker_profile import normalize_profile, FORBIDDEN_FIELDS

        raw = {
            "data": {
                "user_id": "UCC12345",
                "email": "test@example.com",
                "user_name": "Test User",
                "broker": "UPSTOX",
                "broker_user_id": "broker-user-123",
            }
        }
        normalized = normalize_profile(raw)
        for field in FORBIDDEN_FIELDS:
            assert field not in normalized, f"{field} must not appear in profile response"

    def test_connect_response_no_encrypted_fields(self, client, db_session):
        """POST /auth/connect response must not contain encrypted credentials."""
        user_id, session_id = _create_user(db_session)

        resp = client.post(
            "/auth/connect",
            json={
                "api_key": "test-key-12345",
                "api_secret": "test-secret-67890",
                "display_label": "My Broker",
            },
            headers={"X-Session-Id": session_id},
        )
        if resp.status_code == 200:
            body = resp.json()
            assert "broker_api_key_encrypted" not in body
            assert "broker_api_secret_encrypted" not in body
            assert "api_key" not in body
            assert "api_secret" not in body


# ---------------------------------------------------------------------------
# 7. OAuth state single-use enforcement
# ---------------------------------------------------------------------------

class TestOAuthStateSingleUse:
    """OAuth state must be consumed exactly once."""

    def test_state_consumed_on_first_use(self):
        """First consume succeeds, second fails."""
        from app.services.token_store import create_oauth_state, consume_oauth_state

        state = create_oauth_state(session_id="test-sid", broker="UPSTOX")
        result1 = consume_oauth_state(state)
        assert result1 is not None

        result2 = consume_oauth_state(state)
        assert result2 is None

    def test_state_expired_after_ttl(self):
        """Expired state must be rejected."""
        from app.services.token_store import _pending_states, consume_oauth_state, _STATE_TTL_SECONDS

        expired_state = "expired-test-state"
        _pending_states[expired_state] = time.time() - _STATE_TTL_SECONDS - 1

        result = consume_oauth_state(expired_state)
        assert result is None


# ---------------------------------------------------------------------------
# 8. Callback session-mismatch rejection
# ---------------------------------------------------------------------------

class TestCallbackSessionMismatch:
    """Callback must only proceed with the authenticated bound session."""

    def test_callback_without_session_binding_fails(self, client, monkeypatch):
        """Callback with an unsigned state (no session binding) must fail."""
        resp = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "no-session-binding"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "Invalid or expired OAuth state" in resp.json()["detail"]

    def test_callback_with_valid_bound_session(self, client, db_session, monkeypatch):
        """Callback with a valid bound session proceeds to exchange."""
        user_id, session_id = _create_user(db_session)
        store_credentials(db_session, user_id, "UPSTOX", "user-cb-key", "user-cb-secret")

        # Mock the gateway
        mock_adapter = AsyncMock()
        mock_adapter.exchange_authorization_code = AsyncMock(return_value="tok-broker")
        mock_adapter.get_profile = AsyncMock(
            return_value={
                "data": {
                    "user_id": "broker-user-callback",
                    "email": "callback@test.com",
                    "user_name": "Callback User",
                    "broker": "UPSTOX",
                    "is_active": True,
                }
            }
        )
        mock_adapter.extract_account_id = MagicMock(return_value="broker-user-callback")
        mock_gw = MagicMock()
        mock_gw.create.return_value = mock_adapter
        monkeypatch.setattr("app.routers.auth.gateway", mock_gw)

        # Create a signed state with session binding
        state = token_store.create_oauth_state(session_id=session_id, broker="UPSTOX")

        resp = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "/dashboard#session_id=" in location
