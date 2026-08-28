from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.services import token_store, upstox


# The callback endpoint creates its own ``SessionLocal()`` outside of
# FastAPI dependency injection.  We must patch both ``get_db`` AND
# ``SessionLocal`` so the callback's DB session lands on the same
# in-memory database as the test fixtures.


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

    # Patch SessionLocal so the callback's direct ``SessionLocal()``
    # call uses the same in-memory DB as db_session.
    import app.routers.auth as auth_mod

    _orig_session_local = auth_mod.SessionLocal
    auth_mod.SessionLocal = lambda: db_session
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        auth_mod.SessionLocal = _orig_session_local


def test_login_redirects_to_upstox_with_state(client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith(f"{upstox.BASE_URL}/login/authorization/dialog")
    assert "state=" in location


def test_callback_with_error_redirects_to_frontend(client):
    resp = client.get("/auth/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == f"{settings.FRONTEND_URL}?login_error=access_denied"
    assert client.get("/auth/status").json() == {"logged_in": False}


def test_callback_without_state_returns_400(client):
    resp = client.get("/auth/callback", params={"code": "auth-code"}, follow_redirects=False)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired OAuth state"


def test_callback_with_forged_state_returns_400(client):
    resp = client.get(
        "/auth/callback", params={"code": "auth-code", "state": "forged"}, follow_redirects=False
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired OAuth state"


def test_callback_without_code_returns_400(client):
    state = token_store.create_oauth_state()
    resp = client.get("/auth/callback", params={"state": state}, follow_redirects=False)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Missing authorization code"


def test_callback_with_code_sets_session_cookie_and_redirects(client, monkeypatch):
    mock_adapter = AsyncMock()
    mock_adapter.exchange_authorization_code = AsyncMock(return_value="tok-xyz")
    mock_adapter.get_profile = AsyncMock(
        return_value={
            "data": {
                "user_id": "broker-user-1",
                "email": "test@example.com",
                "user_name": "Test User",
                "broker": "UPSTOX",
                "is_active": True,
            }
        }
    )
    # extract_account_id is a @staticmethod — must return str, not coroutine
    mock_adapter.extract_account_id = MagicMock(return_value="broker-user-1")
    mock_gw = MagicMock()
    mock_gw.create.return_value = mock_adapter
    monkeypatch.setattr("app.routers.auth.gateway", mock_gw)

    state = token_store.create_oauth_state()
    resp = client.get(
        "/auth/callback", params={"code": "auth-code", "state": state}, follow_redirects=False
    )

    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith(f"{settings.FRONTEND_URL}/dashboard#session_id=")
    session_id = resp.cookies.get("session_id")
    assert session_id
    assert location == f"{settings.FRONTEND_URL}/dashboard#session_id={session_id}"
    assert token_store.get_token(session_id) == "tok-xyz"


def test_status_logged_out(client):
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": False}


def test_status_logged_in(client):
    session_id = token_store.set_token("tok-xyz")
    resp = client.get("/auth/status", cookies={"session_id": session_id})
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": True}


def test_status_logged_in_via_header(client):
    session_id = token_store.set_token("tok-xyz")
    resp = client.get("/auth/status", headers={"X-Session-Id": session_id})
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": True}


def test_status_logged_out_with_wrong_session(client):
    token_store.set_token("tok-xyz")
    resp = client.get("/auth/status", cookies={"session_id": "wrong"})
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": False}


def test_logout_clears_token(client, db_session):
    from tests.test_helpers import create_test_identity
    session_id, _ = create_test_identity(db_session, "tok-xyz")
    resp = client.post("/auth/logout", cookies={"session_id": session_id})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert token_store.get_token(session_id) is None


def test_logout_via_header(client, db_session):
    from tests.test_helpers import create_test_identity
    session_id, _ = create_test_identity(db_session, "tok-xyz")
    resp = client.post("/auth/logout", headers={"X-Session-Id": session_id})
    assert resp.status_code == 200
    assert token_store.get_token(session_id) is None


def test_logout_requires_valid_session(client):
    token_store.set_token("tok-xyz")
    resp = client.post("/auth/logout")
    assert resp.status_code == 401


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
