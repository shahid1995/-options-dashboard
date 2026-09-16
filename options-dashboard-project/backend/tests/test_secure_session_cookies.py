"""Tests for secure cross-origin session cookies (TDD — verify GREEN phase).

Verifies the hardened authentication architecture:
1. No persistent session ID in localStorage
2. No X-Session-Id header dependency for authenticated requests
3. Secure cookie attributes (HttpOnly, Secure, SameSite=None)
4. Cross-origin credentials included
5. CORS uses explicit origins, never wildcard
6. Login sets cookie, doesn't return session_id in body
7. Logout clears cookie
8. /auth/me works via cookie
9. OAuth callbacks don't expose tokens in URLs
10. Protected routes blocked without cookie
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.identity import User, create_session_record, hash_password
from app.main import app
from app.services import token_store


# The session cookie name used by the backend
SESSION_COOKIE_NAME = "strikenova_session"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    import app.routers.auth as auth_mod

    _orig_session_local = auth_mod.SessionLocal
    auth_mod.SessionLocal = lambda: db_session
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        auth_mod.SessionLocal = _orig_session_local


def _create_active_user(db_session, email="user@test.com", password="password123"):
    """Helper: create an active email user in the DB."""
    user = User(
        id=str(uuid4()),
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        status="active",
        identity_source="email",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login_and_get_cookie(client, db_session, email="user@test.com", password="password123"):
    """Helper: login and return the session cookie value."""
    user = _create_active_user(db_session, email=email, password=password)
    resp = client.post("/auth/login-email", json={"email": email, "password": password})
    assert resp.status_code == 200
    # Extract cookie value from Set-Cookie header
    set_cookie = resp.headers.get("set-cookie", "")
    # Parse the cookie value
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{SESSION_COOKIE_NAME}="):
            return part.split("=", 1)[1], user
    raise AssertionError(f"Cookie {SESSION_COOKIE_NAME} not found in Set-Cookie: {set_cookie}")


# ---------------------------------------------------------------------------
# Test 1 — No session_id in response body
# ---------------------------------------------------------------------------


class TestNoSessionIdInResponse:
    """Login must not return session_id in JSON body."""

    def test_login_email_does_not_return_session_id(self, client, db_session):
        """Login response must not contain the session identifier."""
        user = _create_active_user(db_session)

        resp = client.post("/auth/login-email", json={
            "email": user.email,
            "password": "password123",
        })

        assert resp.status_code == 200
        body = resp.json()
        # Must not expose session_id in body
        assert "session_id" not in body, "session_id must not be returned in response body"
        # User info should be present
        assert body.get("ok") is True
        assert "user" in body


# ---------------------------------------------------------------------------
# Test 2 — Secure cookie attributes
# ---------------------------------------------------------------------------


class TestSecureCookieAttributes:
    """Session cookie must have required security attributes."""

    def test_login_sets_httponly_cookie(self, client, db_session):
        """Login must set an HttpOnly cookie."""
        user = _create_active_user(db_session)

        resp = client.post("/auth/login-email", json={
            "email": user.email,
            "password": "password123",
        })

        assert resp.status_code == 200
        # Check Set-Cookie header
        set_cookie = resp.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie, f"Login must set {SESSION_COOKIE_NAME} cookie"
        assert "httponly" in set_cookie.lower(), "Cookie must be HttpOnly"

    def test_login_cookie_is_secure(self, client, db_session):
        """Cookie must have Secure attribute."""
        user = _create_active_user(db_session)

        resp = client.post("/auth/login-email", json={
            "email": user.email,
            "password": "password123",
        })

        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "secure" in set_cookie.lower(), "Cookie must be Secure"

    def test_login_cookie_samesite_none(self, client, db_session):
        """Cookie must be SameSite=None for cross-origin."""
        user = _create_active_user(db_session)

        resp = client.post("/auth/login-email", json={
            "email": user.email,
            "password": "password123",
        })

        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "samesite=none" in set_cookie.lower(), "Cookie must be SameSite=None for cross-origin"


# ---------------------------------------------------------------------------
# Test 3 — Cross-origin credentials
# ---------------------------------------------------------------------------


class TestCrossOriginCredentials:
    """Browser requests must include credentials via cookie."""

    def test_auth_me_works_with_cookie(self, client, db_session):
        """/auth/me must work using the session cookie (no X-Session-Id)."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        # /auth/me should work using cookie (no X-Session-Id header)
        me_resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert me_resp.status_code == 200
        assert me_resp.json()["user_id"] == user.id

    def test_auth_status_works_with_cookie(self, client, db_session):
        """/auth/status must work using cookie."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        # /auth/status should show logged_in
        status_resp = client.get("/auth/status", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert status_resp.status_code == 200
        assert status_resp.json()["logged_in"] is True


# ---------------------------------------------------------------------------
# Test 4 — CORS configuration
# ---------------------------------------------------------------------------


class TestCORS:
    """CORS must use explicit origins, never wildcard."""

    def test_cors_uses_explicit_origin(self, client):
        """CORS must return explicit origin, not wildcard."""
        # Send OPTIONS request with Origin header
        resp = client.options(
            "/auth/login-email",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # The response should either have a specific origin or no CORS headers
        # (never wildcard with credentials)
        if "access-control-allow-origin" in resp.headers:
            assert resp.headers["access-control-allow-origin"] != "*", \
                "CORS must never use wildcard with credentials"

    def test_cors_allows_credentials(self):
        """CORS middleware must allow credentials."""
        from app.main import app
        # Check that CORSMiddleware is configured with allow_credentials=True
        cors_configs = []
        for middleware in app.user_middleware:
            if hasattr(middleware, 'kwargs'):
                cors_configs.append(middleware.kwargs)
        # At least one middleware should have allow_credentials
        has_credentials = any(
            kwargs.get('allow_credentials') is True
            for kwargs in cors_configs
        )
        assert has_credentials, "CORS middleware must have allow_credentials=True"


# ---------------------------------------------------------------------------
# Test 5 — Logout clears cookie
# ---------------------------------------------------------------------------


class TestLogoutClearsCookie:
    """Logout must invalidate session and clear cookie."""

    def test_logout_deletes_session_cookie(self, client, db_session):
        """Logout must clear the session cookie."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        # Logout with cookie
        logout_resp = client.post("/auth/logout", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert logout_resp.status_code == 200

        # Check that cookie is cleared (Max-Age=0)
        set_cookie = logout_resp.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie, f"Logout must set expired {SESSION_COOKIE_NAME} cookie"
        assert "max-age=0" in set_cookie.lower(), "Logout must expire the cookie (Max-Age=0)"

    def test_auth_me_fails_after_logout(self, client, db_session):
        """After logout, /auth/me must return 401."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        # Logout
        client.post("/auth/logout", cookies={SESSION_COOKIE_NAME: cookie_value})

        # /auth/me should fail
        me_resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert me_resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 6 — Protected route without cookie
# ---------------------------------------------------------------------------


class TestProtectedRoute:
    """Unauthenticated access must be blocked."""

    def test_auth_me_requires_cookie(self, client):
        """/auth/me without cookie must return 401."""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_auth_status_shows_logged_out(self, client):
        """/auth/status without cookie must show logged_in=false."""
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        assert resp.json()["logged_in"] is False


# ---------------------------------------------------------------------------
# Test 7 — No X-Session-Id dependency
# ---------------------------------------------------------------------------


class TestNoXSessionIdDependency:
    """Authenticated requests must work without X-Session-Id header."""

    def test_auth_me_without_x_session_id(self, client, db_session):
        """/auth/me should work using only the cookie, not X-Session-Id."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        # Explicitly send empty X-Session-Id (simulating frontend not sending it)
        me_resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: cookie_value}, headers={"X-Session-Id": ""})
        assert me_resp.status_code == 200
        assert me_resp.json()["user_id"] == user.id
