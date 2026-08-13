from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import token_store, upstox


@pytest.fixture
def client():
    return TestClient(app)


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
    monkeypatch.setattr(upstox, "exchange_code_for_token", AsyncMock(return_value="tok-xyz"))

    state = token_store.create_oauth_state()
    resp = client.get(
        "/auth/callback", params={"code": "auth-code", "state": state}, follow_redirects=False
    )

    assert resp.status_code == 307
    assert resp.headers["location"] == f"{settings.FRONTEND_URL}/dashboard"
    session_id = resp.cookies.get("session_id")
    assert session_id
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


def test_status_logged_out_with_wrong_session(client):
    token_store.set_token("tok-xyz")
    resp = client.get("/auth/status", cookies={"session_id": "wrong"})
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": False}


def test_logout_clears_token(client):
    session_id = token_store.set_token("tok-xyz")
    resp = client.post("/auth/logout", cookies={"session_id": session_id})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert token_store.get_token(session_id) is None


def test_logout_requires_valid_session(client):
    token_store.set_token("tok-xyz")
    resp = client.post("/auth/logout")
    assert resp.status_code == 401


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
