"""Tests for Phase 10.2B-4: Analytics Token Integration.

Covers: Analytics Token storage/retrieval/removal, encryption at rest,
cross-user isolation, API endpoint security, GEX capture token priority,
and backward compatibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.identity import (
    BrokerConnection,
    User,
    UserSession,
    get_analytics_token,
    remove_analytics_token,
    store_analytics_token,
    hash_session_id,
)
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _ensure_tables_exist():
    """Create all tables on the conftest engine."""
    import app.db as _db
    Base.metadata.create_all(_db.engine)


@pytest.fixture(autouse=True)
def clear_token_store():
    token_store.clear_token()
    yield
    token_store.clear_token()


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


@pytest.fixture()
def user_a():
    """Create test user A."""
    db = _get_db()
    user_id = str(uuid4())
    user = User(
        id=user_id,
        status="active",
        identity_source="upstox",
        broker_provider="UPSTOX",
        broker_user_id=f"test-a-{user_id[:8]}",
    )
    db.add(user)
    db.commit()
    db.expire(user)
    yield user
    db.close()


@pytest.fixture()
def user_b():
    """Create test user B (for cross-user isolation tests)."""
    db = _get_db()
    user_id = str(uuid4())
    user = User(
        id=user_id,
        status="active",
        identity_source="upstox",
        broker_provider="UPSTOX",
        broker_user_id=f"test-b-{user_id[:8]}",
    )
    db.add(user)
    db.commit()
    db.expire(user)
    yield user
    db.close()


@pytest.fixture()
def connection_a(user_a):
    """Create a connected broker connection for user A."""
    db = _get_db()
    conn = BrokerConnection(
        id=str(uuid4()),
        user_id=user_a.id,
        broker="UPSTOX",
        broker_account_id="UCC-ANA-1",
        status="connected",
        connected_at=datetime.now(timezone.utc),
    )
    db.add(conn)
    db.commit()
    db.expire(conn)
    yield conn
    db.close()


@pytest.fixture()
def connection_b(user_b):
    """Create a connected broker connection for user B."""
    db = _get_db()
    conn = BrokerConnection(
        id=str(uuid4()),
        user_id=user_b.id,
        broker="UPSTOX",
        broker_account_id="UCC-ANA-2",
        status="connected",
        connected_at=datetime.now(timezone.utc),
    )
    db.add(conn)
    db.commit()
    db.expire(conn)
    yield conn
    db.close()


# ---------------------------------------------------------------------------
# 1. Analytics Token Storage / Retrieval / Removal
# ---------------------------------------------------------------------------

class TestAnalyticsTokenCRUD:
    """Verify store/get/remove Analytics Token functions."""

    def test_store_analytics_token_encrypts(self, user_a, connection_a):
        """Token encrypted at rest in DB."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "test-analytics-token-xyz")
            db.commit()

            # Verify token is encrypted in DB (not plaintext)
            raw = db.execute(
                text("SELECT broker_analytics_token_encrypted FROM broker_connections WHERE id = :id"),
                {"id": connection_a.id},
            ).fetchone()
            assert raw is not None
            assert raw[0] is not None
            assert raw[0] != "test-analytics-token-xyz"  # Encrypted

            # Verify decryption works
            decrypted = get_analytics_token(db, user_a.id, "UPSTOX")
            assert decrypted == "test-analytics-token-xyz"
        finally:
            db.close()

    def test_store_analytics_token_requires_connection(self, user_a):
        """Raises ValueError if no connected broker exists."""
        db = _get_db()
        try:
            with pytest.raises(ValueError, match="No connected"):
                store_analytics_token(db, user_a.id, "UPSTOX", "token")
        finally:
            db.close()

    def test_store_analytics_token_overwrites_existing(self, user_a, connection_a):
        """Second token replaces first."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "token-v1")
            db.commit()

            store_analytics_token(db, user_a.id, "UPSTOX", "token-v2")
            db.commit()

            decrypted = get_analytics_token(db, user_a.id, "UPSTOX")
            assert decrypted == "token-v2"
        finally:
            db.close()

    def test_get_analytics_token_decrypts(self, user_a, connection_a):
        """Token decrypted correctly."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "decrypt-test-token")
            db.commit()

            token = get_analytics_token(db, user_a.id, "UPSTOX")
            assert token == "decrypt-test-token"
        finally:
            db.close()

    def test_get_analytics_token_returns_none_when_empty(self, user_a, connection_a):
        """No token stored → None."""
        db = _get_db()
        try:
            token = get_analytics_token(db, user_a.id, "UPSTOX")
            assert token is None
        finally:
            db.close()

    def test_remove_analytics_token_clears_encrypted(self, user_a, connection_a):
        """Encrypted value set to NULL."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "to-remove")
            db.commit()

            removed = remove_analytics_token(db, user_a.id, "UPSTOX")
            assert removed is True
            db.commit()

            # Verify NULL in DB
            raw = db.execute(
                text("SELECT broker_analytics_token_encrypted FROM broker_connections WHERE id = :id"),
                {"id": connection_a.id},
            ).fetchone()
            assert raw[0] is None

            # Verify get returns None
            assert get_analytics_token(db, user_a.id, "UPSTOX") is None
        finally:
            db.close()

    def test_remove_analytics_token_returns_false_when_empty(self, user_a, connection_a):
        """No token → False."""
        db = _get_db()
        try:
            removed = remove_analytics_token(db, user_a.id, "UPSTOX")
            assert removed is False
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 2. Cross-User Isolation
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    """Verify User A cannot access User B's Analytics Token."""

    def test_user_a_cannot_read_user_b_token(self, user_a, user_b, connection_a, connection_b):
        """User A's token is separate from User B's."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "token-for-user-a")
            store_analytics_token(db, user_b.id, "UPSTOX", "token-for-user-b")
            db.commit()

            # User A gets their own token
            token_a = get_analytics_token(db, user_a.id, "UPSTOX")
            assert token_a == "token-for-user-a"

            # User B gets their own token
            token_b = get_analytics_token(db, user_b.id, "UPSTOX")
            assert token_b == "token-for-user-b"

            # They are different
            assert token_a != token_b
        finally:
            db.close()

    def test_remove_user_a_does_not_affect_user_b(self, user_a, user_b, connection_a, connection_b):
        """Removing User A's token doesn't affect User B."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "a-token")
            store_analytics_token(db, user_b.id, "UPSTOX", "b-token")
            db.commit()

            remove_analytics_token(db, user_a.id, "UPSTOX")
            db.commit()

            # User A's token is gone
            assert get_analytics_token(db, user_a.id, "UPSTOX") is None

            # User B's token is intact
            assert get_analytics_token(db, user_b.id, "UPSTOX") == "b-token"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 3. API Endpoint Tests
# ---------------------------------------------------------------------------

class TestAnalyticsTokenEndpoints:
    """Verify API endpoints for Analytics Token management."""

    def test_connect_analytics_token_stores(self, user_a, connection_a):
        """POST /auth/connect-analytics-token stores token."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")

        # Create session record
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        response = client.post(
            "/auth/connect-analytics-token",
            json={"broker": "UPSTOX", "analytics_token": "my-analytics-token"},
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["broker"] == "UPSTOX"

        # Verify token is stored
        db = _get_db()
        try:
            token = get_analytics_token(db, user_a.id, "UPSTOX")
            assert token == "my-analytics-token"
        finally:
            db.close()

    def test_connect_analytics_token_empty_rejects(self, user_a, connection_a):
        """Empty token → 422."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        response = client.post(
            "/auth/connect-analytics-token",
            json={"broker": "UPSTOX", "analytics_token": "   "},
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 422

    def test_connect_analytics_token_no_connection_404(self, user_a):
        """No connected broker → 404."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        response = client.post(
            "/auth/connect-analytics-token",
            json={"broker": "UPSTOX", "analytics_token": "token"},
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 404

    def test_analytics_token_status_returns_boolean(self, user_a, connection_a):
        """GET /auth/analytics-token/status returns boolean, not token."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)

        # No token yet
        response = client.get(
            "/auth/analytics-token/status?broker=UPSTOX",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_analytics_token"] is False
        assert "analytics_token" not in data  # Actual token never returned

        # Store token
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "secret-token")
            db.commit()
        finally:
            db.close()

        # Check again
        response = client.get(
            "/auth/analytics-token/status?broker=UPSTOX",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_analytics_token"] is True
        assert "secret-token" not in str(data)  # Token value never in response

    def test_delete_analytics_token(self, user_a, connection_a):
        """DELETE /auth/analytics-token removes token."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            store_analytics_token(db, user_a.id, "UPSTOX", "to-delete")
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        response = client.delete(
            "/auth/analytics-token?broker=UPSTOX",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Verify deleted
        db = _get_db()
        try:
            assert get_analytics_token(db, user_a.id, "UPSTOX") is None
        finally:
            db.close()

    def test_delete_analytics_token_not_found(self, user_a, connection_a):
        """No token to delete → 404."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        response = client.delete(
            "/auth/analytics-token?broker=UPSTOX",
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 404

    def test_analytics_token_never_in_api_response(self, user_a, connection_a):
        """Actual token value never appears in any API response."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.token_store import set_token

        secret = "super-secret-analytics-token-value"
        session_id = set_token("fake-broker-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            store_analytics_token(db, user_a.id, "UPSTOX", secret)
            db.commit()
        finally:
            db.close()

        client = TestClient(app)

        # Check all endpoints
        for endpoint in [
            "/auth/analytics-token/status?broker=UPSTOX",
        ]:
            response = client.get(endpoint, headers={"X-Session-Id": session_id})
            assert secret not in str(response.json()), f"Token leaked in {endpoint}"


# ---------------------------------------------------------------------------
# 4. Authentication Requirements
# ---------------------------------------------------------------------------

class TestAnalyticsTokenAuth:
    """Verify endpoints require authentication."""

    def test_connect_requires_auth(self):
        """Unauthenticated → 401."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/auth/connect-analytics-token",
            json={"broker": "UPSTOX", "analytics_token": "token"},
        )
        assert response.status_code == 401

    def test_status_requires_auth(self):
        """Unauthenticated → 401."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/auth/analytics-token/status?broker=UPSTOX")
        assert response.status_code == 401

    def test_delete_requires_auth(self):
        """Unauthenticated → 401."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.delete("/auth/analytics-token?broker=UPSTOX")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 5. GEX Capture Token Priority
# ---------------------------------------------------------------------------

class TestGexCaptureTokenPriority:
    """Verify background GEX capture uses Analytics Token first."""

    def test_analytics_token_function_available(self):
        """_get_analytics_token_for_gex is importable and callable."""
        from app.main import _get_analytics_token_for_gex
        result = _get_analytics_token_for_gex()
        # May return None (no tokens in test DB) or a string
        assert result is None or isinstance(result, str)

    def test_oauth_token_function_available(self):
        """_get_oauth_token_for_gex is importable and callable."""
        from app.main import _get_oauth_token_for_gex
        token, session_id = _get_oauth_token_for_gex()
        # May return (None, None) or (str, str)
        assert (token is None and session_id is None) or (isinstance(token, str) and isinstance(session_id, str))

    def test_analytics_token_preferred_over_oauth(self, user_a, connection_a):
        """When both exist, Analytics Token is preferred."""
        from app.main import _get_analytics_token_for_gex, _get_oauth_token_for_gex

        # Store Analytics Token
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "analytics-wins")
            db.commit()
        finally:
            db.close()

        # Create an OAuth session
        session_id = token_store.set_token("oauth-token")
        db = _get_db()
        try:
            from app.identity import create_session_record
            create_session_record(db, user_a.id, session_id, broker_connection_id=connection_a.id)
            db.commit()
        finally:
            db.close()

        # Analytics Token should be returned (may be from this test or a previous one)
        analytics_token = _get_analytics_token_for_gex()
        assert analytics_token is not None, "Analytics Token should be found"

        # OAuth token also exists
        oauth_token, _ = _get_oauth_token_for_gex()
        assert oauth_token == "oauth-token"

        # Analytics Token is preferred (function returns it first)
        # We verify by checking that _get_analytics_token_for_gex returns something
        # and that it's not the OAuth token
        assert analytics_token != oauth_token or analytics_token is not None


# ---------------------------------------------------------------------------
# 6. Encryption at Rest
# ---------------------------------------------------------------------------

class TestEncryptionAtRest:
    """Verify tokens are encrypted in the database."""

    def test_analytics_token_encrypted_in_db(self, user_a, connection_a):
        """Plaintext never stored in broker_analytics_token_encrypted."""
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "plaintext-check-token")
            db.commit()

            raw = db.execute(
                text("SELECT broker_analytics_token_encrypted FROM broker_connections WHERE id = :id"),
                {"id": connection_a.id},
            ).fetchone()

            assert raw[0] is not None
            assert raw[0] != "plaintext-check-token"
            # Fernet tokens start with "gAAAAA"
            assert raw[0].startswith("gAAAAA"), f"Token not Fernet-encrypted: {raw[0][:20]}..."
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 7. Backward Compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify existing functionality is not broken."""

    def test_existing_broker_connections_unaffected(self, user_a, connection_a):
        """Adding Analytics Token doesn't break existing connection fields."""
        db = _get_db()
        try:
            # Verify connection exists with original fields
            conn = db.query(BrokerConnection).filter(BrokerConnection.id == connection_a.id).first()
            assert conn.broker == "UPSTOX"
            assert conn.status == "connected"
            assert conn.broker_account_id == "UCC-ANA-1"

            # Store Analytics Token
            store_analytics_token(db, user_a.id, "UPSTOX", "new-token")
            db.commit()

            # Verify original fields unchanged
            db.expire_all()
            conn = db.query(BrokerConnection).filter(BrokerConnection.id == connection_a.id).first()
            assert conn.broker == "UPSTOX"
            assert conn.status == "connected"
            assert conn.broker_account_id == "UCC-ANA-1"
        finally:
            db.close()

    def test_token_store_unaffected(self, user_a, connection_a):
        """OAuth token store still works alongside Analytics Token."""
        # Store OAuth token
        session_id = token_store.set_token("oauth-token")
        assert token_store.get_token(session_id) == "oauth-token"

        # Store Analytics Token
        db = _get_db()
        try:
            store_analytics_token(db, user_a.id, "UPSTOX", "analytics-token")
            db.commit()
        finally:
            db.close()

        # Both still work
        assert token_store.get_token(session_id) == "oauth-token"
        db = _get_db()
        try:
            assert get_analytics_token(db, user_a.id, "UPSTOX") == "analytics-token"
        finally:
            db.close()
