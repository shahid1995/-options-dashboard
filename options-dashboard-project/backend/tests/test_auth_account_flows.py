"""StrikeNova account-security API flow tests.

Covers the /auth/account/* endpoints implemented task-by-task per
docs/superpowers/plans/2026-09-16-strikenova-auth-account-security-execution-plan.md:

- Task 1: account login / logout / logout-all / session + broker-OAuth boundary
- Task 3: registration, email verification, resend verification
- Task 4: forgot/reset password, change password/email, recent authentication
- Task 5: rate limiting, security events, secret-leak prevention

Architecture boundary (design spec §3/§9): these endpoints authenticate the
StrikeNova User and manage durable UserSessions. They NEVER invoke the broker
gateway. GET /auth/login remains the broker OAuth initiation route.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.identity import (
    User,
    UserSession,
    create_session_record,
    hash_password,
    hash_session_id,
    store_credentials,
)
from app.main import app
from app.routers.auth import SESSION_COOKIE as SESSION_COOKIE_NAME
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/test_auth_router.py — same in-memory DB pattern)
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


@pytest.fixture(autouse=True)
def _clear_auth_rate_limiter():
    """Clear rate limiter state before/after each test to prevent leakage."""
    from app.services.rate_limiter import rate_limiter

    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


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


def _local_user(
    db,
    email="trader@example.com",
    password="Sup3rSecret!",
    status="active",
):
    """Create a local (email/password) StrikeNova user."""
    user = User(
        id=str(uuid4()),
        email=email,
        password_hash=hash_password(password),
        display_name=email.split("@")[0],
        status=status,
        identity_source="email",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


ACCOUNT = "/auth/account"


# ---------------------------------------------------------------------------
# Task 1 — POST /auth/account/login
# ---------------------------------------------------------------------------


class TestAccountLogin:
    def test_account_login_valid_credentials_creates_durable_session(
        self, client, db_session
    ):
        """POST /auth/account/login authenticates a StrikeNova User and
        creates exactly one durable, non-revoked UserSession."""
        user = _local_user(db_session)

        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": user.email, "password": "Sup3rSecret!"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["user"]["user_id"] == user.id
        assert body["user"]["email"] == user.email
        assert body.get("session_id"), "login must return the session identifier"

        sessions = (
            db_session.query(UserSession).filter(UserSession.user_id == user.id).all()
        )
        assert len(sessions) == 1
        assert sessions[0].revoked_at is None
        assert sessions[0].expires_at > sessions[0].created_at

    def test_account_login_sets_secure_session_cookie(self, client, db_session):
        """Login must set the HttpOnly Secure SameSite=None session cookie
        (existing secure cookie policy) — never a readable document.cookie."""
        user = _local_user(db_session)

        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": user.email, "password": "Sup3rSecret!"},
        )

        set_cookie = resp.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie, f"Set-Cookie missing: {set_cookie}"
        assert "httponly" in set_cookie.lower()
        assert "secure" in set_cookie.lower()
        assert "samesite=none" in set_cookie.lower()

    def test_account_login_wrong_password_returns_generic_401(self, client, db_session):
        user = _local_user(db_session)
        resp = client.post(
            f"{ACCOUNT}/login", json={"email": user.email, "password": "wrong-password"}
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"

    def test_account_login_unknown_email_returns_identical_generic_401(
        self, client, db_session
    ):
        """Unknown email must fail with exactly the same public response as a
        wrong password (no account-existence oracle)."""
        resp_unknown = client.post(
            f"{ACCOUNT}/login",
            json={"email": "nobody@example.com", "password": "whatever123"},
        )
        assert resp_unknown.status_code == 401
        assert resp_unknown.json()["detail"] == "Invalid email or password"

    def test_account_login_normalizes_email(self, client, db_session):
        """Email matching is case/whitespace-insensitive at login."""
        user = _local_user(db_session, email="trader@example.com")
        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": "  TRADER@Example.COM  ", "password": "Sup3rSecret!"},
        )
        assert resp.status_code == 200

    def test_account_login_never_invokes_broker_gateway(self, client, db_session):
        """Account authentication is independent of broker authorization:
        the broker gateway must not be touched (design spec §3 boundary)."""
        _local_user(db_session)

        with patch(
            "app.brokers.gateway.gateway.create",
            side_effect=AssertionError("broker gateway must not be invoked by account login"),
        ) as gateway_create:
            resp = client.post(
                f"{ACCOUNT}/login",
                json={"email": "trader@example.com", "password": "Sup3rSecret!"},
            )

        assert resp.status_code == 200
        gateway_create.assert_not_called()

    def test_account_login_requires_no_broker_credentials(self, client, db_session):
        """Broker connectivity is NOT a prerequisite for account login: a user
        with no BrokerConnection / broker credentials can authenticate."""
        _local_user(db_session)  # no store_credentials() call
        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": "trader@example.com", "password": "Sup3rSecret!"},
        )
        assert resp.status_code == 200

    def test_account_login_missing_fields_422(self, client, db_session):
        resp = client.post(f"{ACCOUNT}/login", json={"email": "", "password": ""})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Task 1 — GET /auth/account/session
# ---------------------------------------------------------------------------


class TestAccountSession:
    def _login(self, client):
        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": "trader@example.com", "password": "Sup3rSecret!"},
        )
        assert resp.status_code == 200
        return resp.json()

    def test_session_endpoint_returns_authenticated_user(self, client, db_session):
        user = _local_user(db_session)
        body = self._login(client)

        resp = client.get(
            f"{ACCOUNT}/session", headers={"X-Session-Id": body["session_id"]}
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["user_id"] == user.id
        assert data["session"]["expires_at"] > data["session"]["created_at"]

    def test_session_rejects_invalid_session(self, client, db_session):
        _local_user(db_session)
        resp = client.get(f"{ACCOUNT}/session", headers={"X-Session-Id": "not-a-session"})
        assert resp.status_code == 401

    def test_session_rejects_revoked_session(self, client, db_session):
        """UserSession.revoked_at is the authority — a revoked session is
        rejected even if the client still presents its identifier."""
        _local_user(db_session)
        body = self._login(client)
        sid = body["session_id"]

        logout = client.post(f"{ACCOUNT}/logout", headers={"X-Session-Id": sid})
        assert logout.status_code == 200

        resp = client.get(f"{ACCOUNT}/session", headers={"X-Session-Id": sid})
        assert resp.status_code == 401

    def test_session_rejects_expired_session(self, client, db_session):
        """UserSession.expires_at is the authority — expired sessions fail."""
        _local_user(db_session)
        body = self._login(client)
        sid = body["session_id"]

        db_session.query(UserSession).filter(
            UserSession.session_hash == hash_session_id(sid)
        ).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db_session.commit()

        resp = client.get(f"{ACCOUNT}/session", headers={"X-Session-Id": sid})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task 1 — POST /auth/account/logout and /auth/account/logout-all
# ---------------------------------------------------------------------------


class TestAccountLogout:
    def test_logout_revokes_current_session_only(self, client, db_session):
        user = _local_user(db_session)
        r1 = client.post(
            f"{ACCOUNT}/login", json={"email": user.email, "password": "Sup3rSecret!"}
        ).json()
        r2 = client.post(
            f"{ACCOUNT}/login", json={"email": user.email, "password": "Sup3rSecret!"}
        ).json()

        resp = client.post(
            f"{ACCOUNT}/logout", headers={"X-Session-Id": r1["session_id"]}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Logged-out session is rejected; the other session still works.
        assert (
            client.get(
                f"{ACCOUNT}/session", headers={"X-Session-Id": r1["session_id"]}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{ACCOUNT}/session", headers={"X-Session-Id": r2["session_id"]}
            ).status_code
            == 200
        )

    def test_logout_is_idempotent(self, client, db_session):
        """Logout of an unknown/already-revoked session still returns ok."""
        resp = client.post(f"{ACCOUNT}/logout", headers={"X-Session-Id": "never-existed"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_logout_clears_session_cookie(self, client, db_session):
        _local_user(db_session)
        resp = client.post(f"{ACCOUNT}/logout")
        set_cookie = resp.headers.get("set-cookie", "")
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()

    def test_logout_all_revokes_every_session(self, client, db_session):
        user = _local_user(db_session)
        sessions = [
            client.post(
                f"{ACCOUNT}/login",
                json={"email": user.email, "password": "Sup3rSecret!"},
            ).json()["session_id"]
            for _ in range(3)
        ]

        resp = client.post(
            f"{ACCOUNT}/logout-all", headers={"X-Session-Id": sessions[0]}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        for sid in sessions:
            assert (
                client.get(f"{ACCOUNT}/session", headers={"X-Session-Id": sid}).status_code
                == 401
            )

    def test_logout_all_requires_authentication(self, client, db_session):
        resp = client.post(f"{ACCOUNT}/logout-all")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task 1 — Broker OAuth regression: GET /auth/login stays the broker route
# ---------------------------------------------------------------------------


class TestBrokerOAuthBoundary:
    def test_broker_oauth_route_unchanged(self, client, db_session):
        """GET /auth/login?broker=UPSTOX must remain the broker OAuth
        initiation route: authenticated session + BYOB credentials → 307
        redirect carrying the user's own client_id."""
        user = _local_user(db_session)
        session_id = token_store.set_token("tok-broker-route")
        create_session_record(db_session, user.id, session_id)
        store_credentials(db_session, user.id, "UPSTOX", "user-api-key", "user-api-secret")

        resp = client.get(
            "/auth/login?broker=UPSTOX",
            headers={"X-Session-Id": session_id},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "client_id=user-api-key" in location

    def test_broker_oauth_requires_authentication(self, client, db_session):
        """Day-3 security fix is preserved: anonymous /auth/login → 401."""
        resp = client.get("/auth/login?broker=UPSTOX", follow_redirects=False)
        assert resp.status_code == 401

    def test_account_login_is_not_the_broker_route(self, client, db_session):
        """POST /auth/account/login must exist separately from broker OAuth —
        it authenticates without any broker query parameter or redirect."""
        _local_user(db_session)
        resp = client.post(
            f"{ACCOUNT}/login",
            json={"email": "trader@example.com", "password": "Sup3rSecret!"},
        )
        assert resp.status_code == 200
        assert "location" not in resp.headers
        assert resp.json().get("session_id")
