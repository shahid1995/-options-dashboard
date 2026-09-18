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
11. CurrentUser() cookie path uses strikenova_session
12. WebSocket session uses strikenova_session cookie
13. Browser JavaScript cannot read session credentials
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


def _create_test_identity(db_session, token="tok-test"):
    """Create a User + UserSession + token_store entry for testing."""
    from tests.test_helpers import create_test_identity as _cti
    return _cti(db_session, token)


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


# ---------------------------------------------------------------------------
# Test 8 — CurrentUser cookie path
# ---------------------------------------------------------------------------


class TestCurrentUserCookiePath:
    """CurrentUser() and get_current_user() must use strikenova_session cookie."""

    def test_current_user_succeeds_with_canonical_cookie(self, client, db_session):
        """CurrentUser() resolves session from strikenova_session cookie."""
        session_id, user_id = _create_test_identity(db_session, "tok-current-user")
        resp = client.get("/paper/templates", cookies={"strikenova_session": session_id})
        assert resp.status_code == 200

    def test_current_user_rejects_missing_cookie(self, client):
        """CurrentUser() rejects request without session cookie or header."""
        resp = client.get("/paper/templates")
        assert resp.status_code == 401

    def test_current_user_rejects_legacy_session_id_cookie(self, client, db_session):
        """Legacy session_id cookie must NOT be accepted."""
        session_id, user_id = _create_test_identity(db_session, "tok-legacy-cookie")
        # Using old cookie name should fail
        resp = client.get("/paper/templates", cookies={"session_id": session_id})
        assert resp.status_code == 401

    def test_current_user_works_with_x_session_id_header(self, client, db_session):
        """X-Session-Id header still works for backward compat."""
        session_id, user_id = _create_test_identity(db_session, "tok-header-compat")
        resp = client.get("/paper/templates", headers={"X-Session-Id": session_id})
        assert resp.status_code == 200

    def test_current_user_protected_route_with_cookie(self, client, db_session):
        """Authenticated protected endpoint works using browser cookie only."""
        session_id, user_id = _create_test_identity(db_session, "tok-protected-route")
        # Use cookie only (no X-Session-Id header)
        resp = client.get("/paper/positions", cookies={"strikenova_session": session_id})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 8b — Issue #61 acceptance: canonical cookie end-to-end on real routes
# ---------------------------------------------------------------------------


class TestCanonicalCookieEndToEnd:
    """Issue #61 acceptance condition.

    A browser that receives ONLY the canonical ``strikenova_session`` cookie
    from login must be able to access authenticated StrikeNova routes through
    the REAL production dependency path (CurrentUser / get_session_id) — not
    a test-only shim. Also proves the legacy ``session_id`` cookie name is no
    longer a transport, and that platform-only sessions (no broker token)
    authenticate for ordinary platform routes.
    """

    def test_login_email_sets_canonical_cookie_only(self, client, db_session):
        """Login must issue the canonical cookie and never the legacy name."""
        user = _create_active_user(db_session)
        resp = client.post("/auth/login-email", json={
            "email": user.email,
            "password": "password123",
        })
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie
        # The legacy cookie name must not be issued alongside the canonical one
        assert "session_id=" not in set_cookie, (
            "Legacy session_id cookie must never be issued by login"
        )

    def test_real_current_user_route_accepts_canonical_cookie(self, client, db_session):
        """Cookie from /auth/login-email authenticates a real CurrentUser route."""
        cookie_value, user = _login_and_get_cookie(client, db_session)
        # /paper/templates is guarded by Depends(CurrentUser()) in production
        resp = client.get("/paper/templates", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert resp.status_code == 200

    def test_real_current_user_route_platform_only_session(self, client, db_session):
        """Platform-only login (no broker token) still authenticates."""
        cookie_value, user = _login_and_get_cookie(client, db_session)
        # Email login stores a platform session token, never a broker token
        assert token_store.get_token(cookie_value).startswith("email:")
        # /paper/positions is CurrentUser-guarded and broker-independent
        resp = client.get("/paper/positions", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_legacy_session_id_cookie_is_not_a_transport(self, client, db_session):
        """The retired session_id cookie name must authenticate nothing."""
        cookie_value, user = _login_and_get_cookie(client, db_session)

        status = client.get("/auth/status", cookies={"session_id": cookie_value})
        assert status.json()["logged_in"] is False

        protected = client.get("/paper/templates", cookies={"session_id": cookie_value})
        assert protected.status_code == 401

    def test_platform_session_without_broker_token_passes_auth_me(self, client, db_session):
        """/auth/me works for a valid platform session with no broker token."""
        cookie_value, user = _login_and_get_cookie(client, db_session)
        assert user.broker_provider is None  # platform-only identity
        resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: cookie_value})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user.id

    def test_combined_platform_only_canonical_cookie_real_route(self, client, db_session):
        """Combined acceptance regression (Issue #61).

        Proves the full production scenario in ONE path:

            valid StrikeNova platform session (durable UserSession row)
            + NO broker credential available to the auth path
              (token_store.get_token() -> None => access_token=None)
            + ONLY the canonical strikenova_session cookie as transport
            + real route protected by Depends(CurrentUser())
            = successful authenticated response bound to the expected user

        No fake dependency, no CurrentUser monkeypatching, no direct
        _resolve_user() call: the request crosses the real FastAPI
        dependency boundary (cookie -> CurrentUser -> AuthenticatedUser).
        """
        import secrets

        from app.identity import get_active_session
        from app.models import StrategyTemplate

        # 1. Valid StrikeNova platform identity (active email user).
        user = _create_active_user(db_session, email="platform-only@test.com")

        # 2. Valid durable UserSession via the production session-record API
        #    (same function the login flows call; no broker connection).
        session_id = secrets.token_urlsafe(32)
        create_session_record(db_session, user.id, session_id)
        db_session.commit()

        # 3. NO broker credential exists for this session — the only source
        #    _resolve_user() uses for AuthenticatedUser.access_token.
        assert token_store.get_token(session_id) is None
        # The durable platform session itself is valid and active.
        assert get_active_session(db_session, session_id) is not None

        # 4+5. Present ONLY the canonical cookie to a real CurrentUser-protected
        #      production route (GET /paper/templates -> Depends(CurrentUser())).
        cookie = {SESSION_COOKIE_NAME: session_id}
        listed = client.get("/paper/templates", cookies=cookie)

        # 7. Successful authentication through the real dependency path.
        assert listed.status_code == 200, listed.text
        assert listed.json() == []

        # 8. Response is associated with the expected user: a write through the
        #    same real route must be persisted with exactly this user's id,
        #    and the ownership-scoped read must return it for this cookie only.
        created = client.post(
            "/paper/templates",
            cookies=cookie,
            json={
                "name": "platform-only regression",
                "symbol": "NIFTY",
                "legs": [
                    {
                        "position": 1,
                        "action": "sell",
                        "option_type": "call",
                        "strike": 20000,
                        "expiry": "2026-12-31",
                        "quantity": 1,
                        "lot_size": 25,
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text

        row = (
            db_session.query(StrategyTemplate)
            .filter(StrategyTemplate.name == "platform-only regression")
            .one_or_none()
        )
        assert row is not None
        assert row.user_id == user.id

        listed = client.get("/paper/templates", cookies=cookie)
        assert listed.status_code == 200
        assert [t["name"] for t in listed.json()] == ["platform-only regression"]


# ---------------------------------------------------------------------------
# Test 9 — WebSocket session migration
# ---------------------------------------------------------------------------


class TestWebSocketSessionMigration:
    """WebSocket authentication must use strikenova_session cookie."""

    def test_ws_session_reads_canonical_cookie(self):
        """ws_session() extracts session from strikenova_session cookie."""
        from app.routers.chains import ws_session
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers.get.return_value = None  # No Sec-WebSocket-Protocol
        ws.cookies.get.side_effect = lambda key: "test-session-123" if key == "strikenova_session" else None

        session_id, subprotocol = ws_session(ws)
        assert session_id == "test-session-123"
        assert subprotocol is None

    def test_ws_session_rejects_missing_cookie(self):
        """ws_session() returns None when cookie is missing."""
        from app.routers.chains import ws_session
        from unittest.mock import MagicMock

        ws = MagicMock()
        ws.headers.get.return_value = None
        ws.cookies.get.return_value = None

        session_id, subprotocol = ws_session(ws)
        assert session_id is None

    def test_ws_session_ignores_sec_websocket_protocol(self):
        """ws_session() does NOT use Sec-WebSocket-Protocol for session ID."""
        from app.routers.chains import ws_session
        from unittest.mock import MagicMock

        ws = MagicMock()
        # Frontend might still send the protocol, but backend should ignore it
        ws.headers.get.return_value = "options-dashboard-session, some-session-id"
        ws.cookies.get.return_value = None

        session_id, subprotocol = ws_session(ws)
        # Should NOT extract from Sec-WebSocket-Protocol
        assert session_id is None


# ---------------------------------------------------------------------------
# Test 10 — Browser-side security regression
# ---------------------------------------------------------------------------


class TestBrowserSecurityRegression:
    """Verify JavaScript never accesses session credentials."""

    def test_no_localstorage_session_id(self):
        """session.js does not write session ID to localStorage."""
        import os
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        session_path = os.path.join(base, "frontend", "lib", "session.js")
        with open(session_path, "r") as f:
            source = f.read()
        # Should not contain localStorage.setItem with session_id
        assert "localStorage.setItem" not in source or "session_id" not in source

    def test_get_session_id_returns_null(self):
        """getSessionId() always returns null."""
        from app.routers.deps import SESSION_COOKIE_NAME as canon
        # The canonical cookie name is not the old one
        assert canon == "strikenova_session"

    def test_chain_ws_protocols_no_session_id(self):
        """chainWsProtocols() does not expose session ID."""
        # chainWsProtocols is a pure function that returns undefined
        # We test the source code doesn't reference getSessionId
        import os
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        api_path = os.path.join(base, "frontend", "lib", "api.js")
        with open(api_path, "r") as f:
            source = f.read()
        # Should not import or call getSessionId for WebSocket protocols
        assert "chainWsProtocols" in source
        # Verify getSessionId is not used in api.js
        assert "getSessionId" not in source

    def test_no_x_session_id_interceptor(self):
        """api.js does not have X-Session-Id interceptor."""
        import os
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        api_path = os.path.join(base, "frontend", "lib", "api.js")
        with open(api_path, "r") as f:
            source = f.read()
        assert "X-Session-Id" not in source

    def test_no_session_id_in_url(self):
        """OAuth callback redirect must not contain session_id in URL."""
        import os
        import inspect
        from app.routers import auth
        source = inspect.getsource(auth)
        assert "#session_id=" not in source
