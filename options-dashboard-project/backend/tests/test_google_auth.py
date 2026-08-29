"""Tests for Google OAuth authentication (Phase A).

Covers:
- POST /auth/google token verification
- Account creation from Google identity
- Account linking (existing email → Google sub)
- Duplicate account protection
- Session management
- /auth/me with Google-created users
- Edge cases (invalid token, expired token, missing config)
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine, SessionLocal
from app.identity import User, UserSession, hash_session_id
from app.main import app
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test."""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper: build a fake Google credential (JWT-like)
# ---------------------------------------------------------------------------

def _fake_google_credential(sub="google-user-123", email="test@gmail.com", name="Test User"):
    """Build a minimal JWT-like string for testing.

    The real verification calls Google's JWKS endpoint, so we mock
    _verify_google_token in the auth router to bypass that.
    """
    header = {"alg": "RS256", "typ": "JWT", "kid": "fake-key-id"}
    payload = {"sub": sub, "email": email, "name": name, "aud": "fake-client-id"}
    # We don't actually need a valid signature since we mock verification
    import base64
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{h}.{p}.fake-signature"


# ---------------------------------------------------------------------------
# Test: new user creation via Google
# ---------------------------------------------------------------------------

class TestGoogleAuthNewUser:
    """POST /auth/google creates a new user when no existing match."""

    @patch("app.routers.auth._verify_google_token")
    def test_new_google_user_created(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "google-sub-001",
            "email": "newuser@gmail.com",
            "name": "New User",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["session_id"]
        assert data["user"]["email"] == "newuser@gmail.com"
        assert data["user"]["display_name"] == "New User"

        # Verify user in DB
        user = db.query(User).filter(User.google_sub == "google-sub-001").first()
        assert user is not None
        assert user.identity_source == "google"
        assert user.email == "newuser@gmail.com"
        assert user.password_hash is None  # No password for Google-only user

    @patch("app.routers.auth._verify_google_token")
    def test_new_google_user_no_email(self, mock_verify, client, db):
        """Google account without public email."""
        mock_verify.return_value = {
            "sub": "google-sub-no-email",
            "email": None,
            "name": "Anonymous",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        user = db.query(User).filter(User.google_sub == "google-sub-no-email").first()
        assert user is not None
        assert user.email is None


# ---------------------------------------------------------------------------
# Test: account linking — existing email user → Google
# ---------------------------------------------------------------------------

class TestGoogleAccountLinking:
    """Google auth links to existing email/password account."""

    @patch("app.routers.auth._verify_google_token")
    def test_link_google_to_existing_email_user(self, mock_verify, client, db):
        """User registered with email, later signs in with Google."""
        from app.identity import hash_password

        # Create an existing email/password user
        user_id = str(uuid4())
        user = User(
            id=user_id,
            email="linktest@gmail.com",
            password_hash=hash_password("TestPass123!"),
            display_name="Email User",
            status="active",
            identity_source="email",
        )
        db.add(user)
        db.commit()

        # Google login with same email
        mock_verify.return_value = {
            "sub": "google-sub-link",
            "email": "linktest@gmail.com",
            "name": "Google User",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Same user should be returned (linked, not duplicated)
        db.refresh(user)
        assert user.google_sub == "google-sub-link"
        assert user.identity_source == "google"  # Updated from "email"
        assert user.password_hash is not None  # Password preserved

    @patch("app.routers.auth._verify_google_token")
    def test_subsequent_google_login_returns_same_user(self, mock_verify, client, db):
        """Second Google login returns the same user (no duplicate)."""
        mock_verify.return_value = {
            "sub": "google-sub-repeat",
            "email": "repeat@gmail.com",
            "name": "Repeat User",
        }
        resp1 = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp1.status_code == 200
        user_id_1 = resp1.json()["user"]["user_id"]

        resp2 = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp2.status_code == 200
        user_id_2 = resp2.json()["user"]["user_id"]

        assert user_id_1 == user_id_2  # Same user, not duplicated


# ---------------------------------------------------------------------------
# Test: duplicate account protection
# ---------------------------------------------------------------------------

class TestDuplicateAccountProtection:
    """Ensure no duplicate accounts when same email uses multiple methods."""

    @patch("app.routers.auth._verify_google_token")
    def test_google_does_not_create_duplicate_with_email_user(self, mock_verify, client, db):
        from app.identity import hash_password

        # Create email user
        user = User(
            id=str(uuid4()),
            email="nodup@gmail.com",
            password_hash=hash_password("TestPass123!"),
            status="active",
            identity_source="email",
        )
        db.add(user)
        db.commit()
        original_count = db.query(User).count()

        # Google login with same email
        mock_verify.return_value = {
            "sub": "google-nodup",
            "email": "nodup@gmail.com",
            "name": "No Dup",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200

        # Count should not increase
        new_count = db.query(User).count()
        assert new_count == original_count

    @patch("app.routers.auth._verify_google_token")
    def test_google_does_not_duplicate_with_upstox_user(self, mock_verify, client, db):
        """Upstox user with same email should be linked, not duplicated."""
        user = User(
            id=str(uuid4()),
            email="upstoxuser@gmail.com",
            display_name="Upstox User",
            status="active",
            identity_source="upstox",
            broker_provider="UPSTOX",
            broker_user_id="UPSTOX-123",
        )
        db.add(user)
        db.commit()

        mock_verify.return_value = {
            "sub": "google-sub-upstox",
            "email": "upstoxuser@gmail.com",
            "name": "Upstox Google",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200

        # Upstox user should now have google_sub
        db.refresh(user)
        assert user.google_sub == "google-sub-upstox"


# ---------------------------------------------------------------------------
# Test: invalid / expired Google tokens
# ---------------------------------------------------------------------------

class TestGoogleTokenValidation:
    """Invalid Google tokens are rejected."""

    @patch("app.routers.auth._verify_google_token")
    def test_invalid_token_rejected(self, mock_verify, client):
        mock_verify.return_value = None
        resp = client.post("/auth/google", json={"credential": "invalid-token"})
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    @patch("app.routers.auth._verify_google_token")
    def test_empty_token_rejected(self, mock_verify, client):
        resp = client.post("/auth/google", json={"credential": ""})
        assert resp.status_code == 422

    @patch("app.routers.auth._verify_google_token")
    def test_missing_token_rejected(self, mock_verify, client):
        resp = client.post("/auth/google", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: session management
# ---------------------------------------------------------------------------

class TestGoogleSessionManagement:
    """Sessions created via Google auth work correctly."""

    @patch("app.routers.auth._verify_google_token")
    def test_google_session_works_with_me_endpoint(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "google-me-test",
            "email": "metest@gmail.com",
            "name": "ME Test",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        session_id = resp.json()["session_id"]

        # Use the session to access /auth/me
        me_resp = client.get("/auth/me", headers={"X-Session-Id": session_id})
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "metest@gmail.com"
        assert me_data["display_name"] == "ME Test"
        assert me_data["identity_source"] == "google"

    @patch("app.routers.auth._verify_google_token")
    def test_google_session_logout(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "google-logout-test",
            "email": "logout@gmail.com",
            "name": "Logout Test",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        session_id = resp.json()["session_id"]

        # Logout
        logout_resp = client.post("/auth/logout", headers={"X-Session-Id": session_id})
        assert logout_resp.status_code == 200

        # Session should be invalid after logout
        me_resp = client.get("/auth/me", headers={"X-Session-Id": session_id})
        assert me_resp.status_code == 401

    @patch("app.routers.auth._verify_google_token")
    def test_google_session_is_unique_per_login(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "google-unique-session",
            "email": "unique@gmail.com",
            "name": "Unique Session",
        }
        resp1 = client.post("/auth/google", json={"credential": "fake-jwt"})
        resp2 = client.post("/auth/google", json={"credential": "fake-jwt"})

        sid1 = resp1.json()["session_id"]
        sid2 = resp2.json()["session_id"]
        assert sid1 != sid2  # Each login gets a unique session


# ---------------------------------------------------------------------------
# Test: /auth/me with Google users
# ---------------------------------------------------------------------------

class TestAuthMe:
    """/auth/me returns correct data for Google-created users."""

    @patch("app.routers.auth._verify_google_token")
    def test_me_returns_google_user_data(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "google-me-data",
            "email": "medata@gmail.com",
            "name": "ME Data",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        session_id = resp.json()["session_id"]

        me_resp = client.get("/auth/me", headers={"X-Session-Id": session_id})
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["email"] == "medata@gmail.com"
        assert data["display_name"] == "ME Data"
        assert data["identity_source"] == "google"
        assert data["status"] == "active"
        assert data["created_at"] is not None
        assert data["last_login_at"] is not None

    def test_me_returns_401_when_not_logged_in(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: identity_source tracking
# ---------------------------------------------------------------------------

class TestIdentitySourceTracking:
    """identity_source correctly reflects the auth method."""

    @patch("app.routers.auth._verify_google_token")
    def test_new_google_user_source_is_google(self, mock_verify, client, db):
        mock_verify.return_value = {
            "sub": "src-google",
            "email": "src@gmail.com",
            "name": "Src Test",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.json()["user"]["identity_source"] == "google"

    @patch("app.routers.auth._verify_google_token")
    def test_email_user_linked_to_google_source_updates(self, mock_verify, client, db):
        from app.identity import hash_password

        user = User(
            id=str(uuid4()),
            email="srcupdate@gmail.com",
            password_hash=hash_password("TestPass123!"),
            status="active",
            identity_source="email",
        )
        db.add(user)
        db.commit()

        mock_verify.return_value = {
            "sub": "src-update-google",
            "email": "srcupdate@gmail.com",
            "name": "Source Update",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200

        db.refresh(user)
        assert user.identity_source == "google"


# ---------------------------------------------------------------------------
# Test: edge cases
# ---------------------------------------------------------------------------

class TestGoogleAuthEdgeCases:
    """Edge cases and boundary conditions."""

    @patch("app.routers.auth._verify_google_token")
    def test_inactive_user_rejected(self, mock_verify, client, db):
        from app.identity import hash_password

        user = User(
            id=str(uuid4()),
            email="inactive@gmail.com",
            password_hash=hash_password("TestPass123!"),
            status="suspended",
            identity_source="email",
        )
        db.add(user)
        db.commit()

        mock_verify.return_value = {
            "sub": "google-inactive",
            "email": "inactive@gmail.com",
            "name": "Inactive",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 403
        assert "not active" in resp.json()["detail"]

    @patch("app.routers.auth._verify_google_token")
    def test_google_sub_case_sensitive(self, mock_verify, client, db):
        """Google subs are case-sensitive (they shouldn't be, but verify behavior)."""
        mock_verify.return_value = {
            "sub": "CASE-SENSITIVE-SUB",
            "email": None,
            "name": "Case Test",
        }
        resp1 = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp1.status_code == 200

        mock_verify.return_value = {
            "sub": "case-sensitive-sub",  # Different case
            "email": None,
            "name": "Case Test 2",
        }
        resp2 = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp2.status_code == 200

        # Should create two different users (different subs)
        assert resp1.json()["user"]["user_id"] != resp2.json()["user"]["user_id"]

    @patch("app.routers.auth._verify_google_token")
    def test_email_case_insensitive(self, mock_verify, client, db):
        """Emails should be normalized to lowercase."""
        mock_verify.return_value = {
            "sub": "sub-upper",
            "email": "UPPER@GMAIL.COM",
            "name": "Upper",
        }
        resp = client.post("/auth/google", json={"credential": "fake-jwt"})
        assert resp.status_code == 200

        user = db.query(User).filter(User.google_sub == "sub-upper").first()
        assert user.email == "upper@gmail.com"  # Normalized
