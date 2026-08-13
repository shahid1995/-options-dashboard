from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import token_store, upstox


@pytest.fixture
def client():
    return TestClient(app)


def test_login_redirects_to_upstox(client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == upstox.get_login_url()


def test_callback_with_error_redirects_to_frontend(client):
    resp = client.get("/auth/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == f"{settings.FRONTEND_URL}?login_error=access_denied"
    assert token_store.get_token() is None


def test_callback_without_code_returns_400(client):
    resp = client.get("/auth/callback", follow_redirects=False)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Missing authorization code"


def test_callback_with_code_stores_token_and_redirects(client, monkeypatch):
    monkeypatch.setattr(upstox, "exchange_code_for_token", AsyncMock(return_value="tok-xyz"))

    resp = client.get("/auth/callback", params={"code": "auth-code"}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == f"{settings.FRONTEND_URL}/dashboard"
    assert token_store.get_token() == "tok-xyz"


def test_status_logged_out(client):
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": False}


def test_status_logged_in(client):
    token_store.set_token("tok-xyz")
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"logged_in": True}


def test_logout_clears_token(client):
    token_store.set_token("tok-xyz")
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert token_store.get_token() is None


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
