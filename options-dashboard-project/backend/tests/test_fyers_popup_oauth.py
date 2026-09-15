"""FYERS seamless OAuth popup UX — backend security tests (Phase 10).

Tests verify that the popup callback endpoint:
- Returns minimal HTML (no tokens, no secrets, no auth_codes)
- Sends postMessage with correct source, broker, status
- Validates origin strictly
- Works with existing OAuth state and BrokerConnection/BrokerToken architecture
- Never exposes credentials
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
import app.routers.auth as auth_mod
from app.identity import BrokerConnection, BrokerToken, User, create_session_record, store_credentials
from app.services import token_store
from app.main import app


FYERS_APP_ID = "FYERS-TEST-APP-200"
FYERS_LOGIN_ID = "FYERSLOGIN-TEST-001"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    session._linking_engine = engine
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


from app.db import SessionLocal as _real_session_local


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    engine = db_session._linking_engine
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    auth_mod.SessionLocal = factory
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        auth_mod.SessionLocal = _real_session_local


def make_platform_user(db: object, email: str | None = None) -> User:
    user = User(
        id=str(uuid4()),
        email=email,
        display_name="Platform User",
        status="active",
        identity_source="email",
        password_hash="seed-not-a-real-hash",
    )
    db.add(user)
    db.commit()
    return user


def login_initiator(db: object, user: User) -> str:
    session_id = token_store.set_token(f"initiator-session-{uuid4()}", persist_to_db=False)
    create_session_record(db, user.id, session_id)
    db.commit()
    return session_id


def store_byob(db: object, user: User, broker: str) -> None:
    store_credentials(db, user.id, broker, f"{broker.lower()}-key", f"{broker.lower()}-secret")
    db.commit()


def fyers_profile() -> dict:
    return {
        "s": "ok",
        "data": {
            "fy_id": FYERS_LOGIN_ID,
            "name": "Test User",
            "email_id": "test@example.com",
            "appattribution": "200",
        },
    }


def mock_fyers_adapter(monkeypatch: object, profile: dict) -> None:
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value="fyers-access-token-value")
    adapter.get_profile = AsyncMock(return_value=profile)
    adapter.extract_account_id = MagicMock(return_value=profile["data"]["fy_id"])
    adapter._refresh_token = "fyers-refresh-token-value"

    monkeypatch.setattr("app.routers.auth.gateway.create", lambda *a, **kw: adapter)
    return adapter


# ---------------------------------------------------------------------------
# Test A: Only the configured frontend origin receives success messages
# ---------------------------------------------------------------------------
def test_popup_callback_returns_html_with_exact_origin(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup callback must include the exact configured frontend origin in postMessage."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act - popup flag is embedded in signed state, not query param
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    # Must contain the configured origin (not wildcard)
    assert settings.FRONTEND_ORIGIN in body


# ---------------------------------------------------------------------------
# Test C: targetOrigin is never '*'
# ---------------------------------------------------------------------------
def test_popup_callback_never_uses_wildcard_target_origin(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup callback must NEVER use '*' as the postMessage targetOrigin."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    body = resp.text
    # The targetOrigin parameter in postMessage must be a URL, not '*'
    assert '"*"' not in body  # No wildcard string literal
    assert "postMessage(" in body
    # postMessage signature: postMessage(payload, targetOrigin)
    # targetOrigin must be a string URL
    import re
    # Find postMessage call and check targetOrigin
    match = re.search(r'postMessage\([^,]+,\s*["\']([^"\']+)["\']\)', body)
    assert match is not None, "postMessage call must have targetOrigin"
    assert match.group(1) != "*", "targetOrigin must not be '*'"


# ---------------------------------------------------------------------------
# Test D: No token appears in the callback HTML
# ---------------------------------------------------------------------------
def test_popup_callback_no_access_token_exposure(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup HTML must never contain the access token value."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    body = resp.text
    # Must not contain the access token value
    assert "fyers-access-token-value" not in body
    assert "access_token" not in body.lower() or body.lower().count("access_token") == 0


# ---------------------------------------------------------------------------
# Test E: No auth_code appears in the callback HTML
# ---------------------------------------------------------------------------
def test_popup_callback_no_auth_code_exposure(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup HTML must never contain the authorization code."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    auth_code_used = "super-secret-auth-code-xyz"
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": auth_code_used, "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    body = resp.text
    assert auth_code_used not in body
    # The generic term "auth_code" as a JS variable name is fine, but not the value
    assert "auth-code-value" not in body


# ---------------------------------------------------------------------------
# Test F: No secret appears in the callback HTML
# ---------------------------------------------------------------------------
def test_popup_callback_no_app_secret_exposure(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup HTML must never contain the FYERS app secret."""
    # Arrange
    secret_value = "my-super-secret-app-secret"
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_credentials(db_session, user.id, "FYERS", "fyers-app-key", secret_value)
    db_session.commit()
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    body = resp.text
    assert secret_value not in body
    assert "api_secret" not in body.lower()


# ---------------------------------------------------------------------------
# Test G: Successful callback creates normal BrokerConnection/BrokerToken state
# ---------------------------------------------------------------------------
def test_popup_callback_creates_broker_connection_and_token(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The popup callback must create the same BrokerConnection/BrokerToken as the dashboard flow."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    # Verify BrokerConnection exists
    conn = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS")
        .first()
    )
    assert conn is not None, "BrokerConnection must be created"
    assert conn.status == "connected"
    # Verify broker identity is the customer Login ID, not App ID
    assert FYERS_LOGIN_ID in conn.provider_metadata_json or FYERS_LOGIN_ID in str(conn.__dict__)
    # Verify BrokerToken exists (encrypted)
    token_row = (
        db_session.query(BrokerToken)
        .filter(BrokerToken.connection_id == conn.id)
        .first()
    )
    assert token_row is not None, "BrokerToken must be created"
    assert token_row.broker_token_encrypted is not None
    # The token must be encrypted (not plaintext)
    assert token_row.broker_token_encrypted != "fyers-access-token-value"


# ---------------------------------------------------------------------------
# Test H: Failed callback does not create partial ownership state
# ---------------------------------------------------------------------------
def test_popup_callback_failure_no_partial_state(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """If OAuth fails, the popup must NOT create any BrokerConnection with 'connected' status or partial token state."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")

    # Count existing connections (store_byob creates one with status 'pending')
    initial_connected_count = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS", BrokerConnection.status == "connected")
        .count()
    )

    # Make ALL adapter methods fail with BrokerError
    from app.brokers.domain.errors import BrokerError, BrokerErrorCode
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(
        side_effect=BrokerError(BrokerErrorCode.UPSTREAM_ERROR, "Token exchange failed")
    )
    adapter.get_profile = AsyncMock(
        side_effect=BrokerError(BrokerErrorCode.UPSTREAM_ERROR, "Profile fetch failed")
    )
    adapter.extract_account_id = MagicMock(return_value=None)
    monkeypatch.setattr("app.routers.auth.gateway.create", lambda *a, **kw: adapter)

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "invalid-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    # Must return an error popup (not crash)
    assert resp.status_code == 200
    body = resp.text
    assert "error" in body.lower() or "unable to connect" in body.lower()
    # No NEW connected BrokerConnection should be created
    final_connected_count = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS", BrokerConnection.status == "connected")
        .count()
    )
    assert final_connected_count == initial_connected_count, "Failed callback must not create a connected BrokerConnection"


# ---------------------------------------------------------------------------
# Test I: User cannot be switched based on postMessage contents
# ---------------------------------------------------------------------------
def test_popup_callback_does_not_switch_user_based_on_message(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The callback must only use the session_id from signed OAuth state, never from postMessage."""
    # Arrange
    user_a = make_platform_user(db_session, email="usera@example.com")
    user_b = make_platform_user(db_session, email="userb@example.com")
    session_a = login_initiator(db_session, user_a)
    session_b = login_initiator(db_session, user_b)
    store_byob(db_session, user_a, "FYERS")
    store_byob(db_session, user_b, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act - user_b initiates OAuth but uses user_a's state (forgery attempt)
    # In real scenario, the state is signed so forgery would be detected
    # But we test that even if state is valid, the broker connection goes to the
    # session owner, not someone claiming to be a different user
    state_a = token_store.create_oauth_state(session_id=session_a, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state_a},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    # Connection must belong to user_a, not user_b
    conn = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.broker == "FYERS")
        .first()
    )
    assert conn is not None
    assert conn.user_id == user_a.id, "Connection must belong to the session owner"
    assert conn.user_id != user_b.id, "Connection must NOT belong to another user"


# ---------------------------------------------------------------------------
# Test J: Existing signed OAuth state remains mandatory
# ---------------------------------------------------------------------------
def test_popup_callback_requires_signed_oauth_state(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """Popup mode must still require a valid signed OAuth state (same as dashboard mode)."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act - try with forged state
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": "forged-state"},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 400
    body = resp.text
    # Must reject the request
    assert "Invalid or expired OAuth state" in body or resp.status_code == 400


# ---------------------------------------------------------------------------
# Test: Error callback returns safe HTML
# ---------------------------------------------------------------------------
def test_popup_callback_error_returns_safe_html(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """OAuth error (user denies consent) must return safe error popup HTML."""
    # Arrange - need valid state with popup flag to trigger popup mode
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Create state with popup flag embedded
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)

    # Act
    resp = client.get(
        "/auth/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    body = resp.text
    assert "text/html" in resp.headers.get("content-type", "")
    # Must contain error indicator
    assert "error" in body.lower() or "unable to connect" in body.lower()
    # Must not contain raw OAuth error details that could be confusing
    # The raw "access_denied" code should not appear - it should be mapped to a user-friendly message
    assert "access_denied" not in body  # Raw OAuth error code not exposed
    # Should contain user-friendly message instead
    assert "denied" in body.lower() or "try again" in body.lower()


# ---------------------------------------------------------------------------
# Test: Successful popup sends correct broker in postMessage
# ---------------------------------------------------------------------------
def test_popup_callback_sends_correct_broker_in_postmessage(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """The postMessage payload must identify the correct broker."""
    # Arrange
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    mock_fyers_adapter(monkeypatch, fyers_profile())

    # Act
    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "test-auth-code", "state": state},
        follow_redirects=False,
    )

    # Assert
    assert resp.status_code == 200
    body = resp.text
    # Must contain the broker identifier
    assert '"FYERS"' in body or "'FYERS'" in body
    # Must contain status
    assert '"connected"' in body or "'connected'" in body
    # Must contain source marker
    assert "strikenova-broker-oauth" in body


# ---------------------------------------------------------------------------
# Seamless popup kickoff (2026-09-15 staging finding): the popup is a
# TOP-LEVEL navigation to the API origin — no X-Session-Id header and, for
# first-time email/google users, no session cookie either. POST
# /auth/oauth/popup-kick mints a single-use kick cookie that /auth/login
# accepts as session evidence for the popup's navigation only.
# ---------------------------------------------------------------------------

def test_popup_kick_requires_authentication(client: TestClient):
    """Unauthenticated callers cannot mint a kick cookie."""
    resp = client.post("/auth/oauth/popup-kick", json={"broker": "FYERS"})
    assert resp.status_code == 401


def test_popup_kick_mints_single_use_cookie_for_valid_session(
    client: TestClient,
    db_session: object,
):
    """Authenticated opener gets an HttpOnly kick cookie scoped to /auth."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    resp = client.post(
        "/auth/oauth/popup-kick",
        json={"broker": "FYERS"},
        headers={"X-Session-Id": session_id},
    )
    assert resp.status_code == 200
    cookie = resp.headers.get("set-cookie", "")
    assert "sn_oauth_kick=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "samesite=none" in cookie.lower()
    assert "Path=/auth" in cookie


def test_popup_kick_lets_popup_login_pass_then_replay_fails(
    client: TestClient,
    db_session: object,
):
    """Popup /auth/login succeeds with ONLY the kick cookie; replay is rejected."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_credentials(
        db_session, user.id, "FYERS", "fyers-key", "fyers-secret",
        redirect_uri="https://frontend.example.com/auth/callback",
    )
    db_session.commit()

    mint = client.post(
        "/auth/oauth/popup-kick",
        json={"broker": "FYERS"},
        headers={"X-Session-Id": session_id},
    )
    cookie_value = mint.headers["set-cookie"].split(";")[0]  # name=value

    # Popup navigation: kick cookie only, no session header/cookie.
    first = client.get(
        "/auth/login",
        params={"broker": "FYERS", "popup": "true"},
        headers={"Cookie": cookie_value},
        follow_redirects=False,
    )
    assert first.status_code == 307
    assert first.headers["location"].startswith("https://api-t1.fyers.in/")

    # Single use: the same cookie can never authorize a second navigation.
    replay = client.get(
        "/auth/login",
        params={"broker": "FYERS", "popup": "true"},
        headers={"Cookie": cookie_value},
        follow_redirects=False,
    )
    assert replay.status_code == 401


def test_popup_kick_is_broker_bound(client: TestClient, db_session: object):
    """A kick minted for one broker cannot authorize another broker's popup."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")

    mint = client.post(
        "/auth/oauth/popup-kick",
        json={"broker": "UPSTOX"},
        headers={"X-Session-Id": session_id},
    )
    cookie_value = mint.headers["set-cookie"].split(";")[0]
    resp = client.get(
        "/auth/login",
        params={"broker": "FYERS", "popup": "true"},
        headers={"Cookie": cookie_value},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test L: REAL FYERS redirect shape — code (status) AND auth_code (JWT) together
#
# Staging incident (2026-09-15, live consent): FYERS v3 redirects back with
# `s=ok&code=200&auth_code=<JWT>&state=...` — `code` is a NUMERIC STATUS, not
# the authorization code. The old `code = code or auth_code` alias bound
# code="200" (truthy) and exchanged the literal string "200", which FYERS
# rejected (UPSTREAM_ERROR: invalid auth code). Regression: with the REAL
# shape, the JWT must reach validate-authcode and "200" must NEVER be sent.
# ---------------------------------------------------------------------------
def test_callback_fyers_real_redirect_shape_exchanges_auth_code_jwt(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """FYERS callback with BOTH code=200 and auth_code=<JWT> exchanges the JWT."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    adapter = mock_fyers_adapter(monkeypatch, fyers_profile())

    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={
            "s": "ok",
            "code": "200",  # FYERS status code, NOT the authorization code
            "auth_code": "real-fyers-auth-code-jwt",  # the actual JWT
            "state": state,
        },
        follow_redirects=False,
    )

    # The exchange succeeded (popup success HTML, not the error page).
    assert resp.status_code == 200
    assert "Unable to connect" not in resp.text
    exchanged = adapter.exchange_authorization_code.call_args[0][0]
    assert exchanged == "real-fyers-auth-code-jwt"
    assert exchanged != "200"


def test_callback_fyers_auth_code_absent_falls_back_to_code(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """Without auth_code, FYERS still exchanges the `code` param (compat fallback)."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "FYERS")
    adapter = mock_fyers_adapter(monkeypatch, fyers_profile())

    state = token_store.create_oauth_state(session_id=session_id, broker="FYERS", popup=True)
    resp = client.get(
        "/auth/callback",
        params={"code": "legacy-code-value", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert "Unable to connect" not in resp.text
    assert adapter.exchange_authorization_code.call_args[0][0] == "legacy-code-value"


def test_callback_upstox_preserves_code_parameter_behavior(
    client: TestClient,
    db_session: object,
    monkeypatch: object,
):
    """Upstox flow is untouched: `code` is the authorization code as before."""
    user = make_platform_user(db_session)
    session_id = login_initiator(db_session, user)
    store_byob(db_session, user, "UPSTOX")

    upstox_adapter = AsyncMock()
    upstox_adapter.exchange_authorization_code = AsyncMock(return_value="upstox-token")
    upstox_adapter.get_profile = AsyncMock(
        return_value={
            "data": {
                "user_id": "upstox-user-1",
                "email": "test@example.com",
                "user_name": "Test User",
                "broker": "UPSTOX",
                "is_active": True,
            }
        }
    )
    upstox_adapter.extract_account_id = MagicMock(return_value="upstox-user-1")
    monkeypatch.setattr(
        "app.routers.auth.gateway.create", lambda *a, **kw: upstox_adapter
    )

    state = token_store.create_oauth_state(session_id=session_id, broker="UPSTOX")
    resp = client.get(
        "/auth/callback",
        params={"code": "upstox-auth-code", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 307  # non-popup success redirect
    assert upstox_adapter.exchange_authorization_code.call_args[0][0] == "upstox-auth-code"
