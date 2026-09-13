"""Opt-in broker-path smoke tests for live staging (Upstox audit Phase 20).

Run with BOTH flags:

    STAGING_SMOKE=1 STAGING_BROKER_SMOKE=1 \
        python -m pytest tests/staging_smoke/test_staging_broker_smoke.py -v

Scope decision (Upstox sandbox audit, 2026-09-13): Upstox sandbox apps are
portal-token based (no OAuth) and their tokens are sandbox-orders-only, so
StrikeNova's BYOB OAuth flow CANNOT be exercised against the sandbox.
These tests therefore validate the deterministic, broker-independent parts of
the broker path against live staging:

* authorization gates (no anonymous OAuth, no credential store for
  unauthenticated callers)
* the graceful "no broker connection" contract
* the app-sanctioned direct-token mechanism lifecycle
  (POST /auth/connect-analytics-token -> status -> DELETE -> status)
  using an obviously-fake opaque token value that is never printed

No real or sandbox Upstox credentials are used; nothing is injected into the
OAuth/token-store path; each run creates one synthetic data-only connection
row for its synthetic user, which the DELETE step deactivates.
"""

import secrets

import httpx
import pytest

from tests.staging_smoke.conftest import (
    BASE_URL,
    HTTP_TIMEOUT,
    generate_test_email,
    generate_test_password,
    mask,
)


@pytest.fixture(scope="module")
def broker_client():
    with httpx.Client(base_url=BASE_URL, timeout=HTTP_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def broker_account(broker_client):
    """One synthetic user shared by the module; cleaned up at teardown."""
    account = {
        "email": generate_test_email(),
        "password": generate_test_password(),
    }
    r = broker_client.post(
        "/auth/register",
        json={
            "email": account["email"],
            "password": account["password"],
            "name": "Broker Smoke",
        },
    )
    assert r.status_code == 200, f"register -> {r.status_code}: {r.text[:200]}"
    login = broker_client.post(
        "/auth/login-email",
        json={"email": account["email"], "password": account["password"]},
    )
    assert login.status_code == 200, f"login -> {login.status_code}"
    session_id = login.json().get("session_id")
    assert session_id, "no session id"
    account["session_id"] = session_id
    yield account
    broker_client.post("/auth/logout", headers={"X-Session-Id": session_id})


def _auth(account) -> dict:
    return {"X-Session-Id": account["session_id"]}


# ---------------------------------------------------------------------------
# Broker authorization gates (live, negative path)
# ---------------------------------------------------------------------------
def test_b01_oauth_login_requires_session(broker_client):
    r = broker_client.get("/auth/login?broker=UPSTOX")
    assert r.status_code == 401, f"anonymous /auth/login -> {r.status_code} (want 401)"
    assert "accounts.upstox.com" not in r.text, "must never leak an Upstox URL"


def test_b02_connect_requires_session(broker_client):
    r = broker_client.post(
        "/auth/connect",
        json={"broker": "UPSTOX", "api_key": "k", "api_secret": "s"},
    )
    assert r.status_code == 401, f"anonymous /auth/connect -> {r.status_code} (want 401)"


def test_b03_login_without_byob_credentials(broker_account, broker_client):
    """Authenticated user with no stored BYOB creds gets a clean 400."""
    r = broker_client.get(
        "/auth/login?broker=UPSTOX", headers=_auth(broker_account)
    )
    assert r.status_code == 400, f"/auth/login (no creds) -> {r.status_code}"
    assert "credentials" in r.json().get("detail", "").lower()
    assert "accounts.upstox.com" not in r.text


def test_b04_profile_graceful_without_broker(broker_account, broker_client):
    r = broker_client.get("/paper/broker/profile", headers=_auth(broker_account))
    assert r.status_code == 200, f"/paper/broker/profile -> {r.status_code}"
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["profile"] is None
    assert body["error"] == "BROKER_AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# App-sanctioned direct-token mechanism lifecycle (synthetic value)
# ---------------------------------------------------------------------------
def test_b05_analytics_token_lifecycle(broker_account, broker_client):
    """Store -> status -> remove -> status for the data-only token path.

    The token value is a runtime-generated fake; it is never printed and
    never used against any Upstox endpoint.
    """
    fake_token = f"smoke-fake-analytics-{secrets.token_hex(16)}"

    # store
    r = broker_client.post(
        "/auth/connect-analytics-token",
        headers=_auth(broker_account),
        json={"broker": "UPSTOX", "analytics_token": fake_token},
    )
    assert r.status_code == 200, f"connect-analytics-token -> {r.status_code}: {r.text[:200]}"
    assert r.json().get("ok") is True

    # status reports presence (never the value)
    r = broker_client.get(
        "/auth/analytics-token/status",
        headers=_auth(broker_account),
        params={"broker": "UPSTOX"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["has_analytics_token"] is True, f"status body: {body}"
    assert "token" not in {k.lower() for k in body if "value" in k.lower()}

    # remove
    r = broker_client.delete(
        "/auth/analytics-token",
        headers=_auth(broker_account),
        params={"broker": "UPSTOX"},
    )
    assert r.status_code == 200, f"DELETE analytics-token -> {r.status_code}"

    # status back to absent
    r = broker_client.get(
        "/auth/analytics-token/status",
        headers=_auth(broker_account),
        params={"broker": "UPSTOX"},
    )
    assert r.status_code == 200
    assert r.json()["has_analytics_token"] is False


def test_b06_delete_without_token_is_404(broker_account, broker_client):
    r = broker_client.delete(
        "/auth/analytics-token",
        headers=_auth(broker_account),
        params={"broker": "UPSTOX"},
    )
    assert r.status_code == 404, f"DELETE without token -> {r.status_code}"


def test_b07_token_value_never_in_any_response(broker_account, broker_client):
    """Paranoia check: the fake token value must not echo in responses.

    Stores a distinctive fake token and asserts that the status, profile,
    and me endpoints never contain it (by value or any recognizable prefix).
    """
    marker = secrets.token_hex(12)
    r = broker_client.post(
        "/auth/connect-analytics-token",
        headers=_auth(broker_account),
        json={"broker": "UPSTOX", "analytics_token": f"smoke-{marker}"},
    )
    assert r.status_code == 200

    leaked = []
    for path, method in (
        ("/auth/analytics-token/status?broker=UPSTOX", "GET"),
        ("/paper/broker/profile", "GET"),
        ("/auth/me", "GET"),
    ):
        resp = broker_client.request(method, path, headers=_auth(broker_account))
        if marker in resp.text:
            leaked.append(path)
    print(f"session used: {mask(broker_account['session_id'])}")
    assert not leaked, f"token value echoed by: {leaked}"

    # cleanup for this test's row
    broker_client.delete(
        "/auth/analytics-token",
        headers=_auth(broker_account),
        params={"broker": "UPSTOX"},
    )


def test_b08_two_user_isolation(broker_account, broker_client):
    """User A's broker connection must be invisible to synthetic user B.

    Runs entirely through the public API with two synthetic users:
    A stores a data-only token; B must see no token, must NOT be able to
    remove A's token (404), and A's state must be untouched afterwards.
    """
    # second synthetic user (B)
    b_account = {
        "email": generate_test_email(),
        "password": generate_test_password(),
    }
    assert broker_client.post(
        "/auth/register",
        json={
            "email": b_account["email"],
            "password": b_account["password"],
            "name": "Broker Smoke B",
        },
    ).status_code == 200
    b_session = broker_client.post(
        "/auth/login-email",
        json={"email": b_account["email"], "password": b_account["password"]},
    ).json()["session_id"]
    try:
        # A stores a token
        r = broker_client.post(
            "/auth/connect-analytics-token",
            headers=_auth(broker_account),
            json={"broker": "UPSTOX", "analytics_token": f"smoke-iso-{secrets.token_hex(8)}"},
        )
        assert r.status_code == 200

        # B sees no token for themselves
        r = broker_client.get(
            "/auth/analytics-token/status",
            headers={"X-Session-Id": b_session},
            params={"broker": "UPSTOX"},
        )
        assert r.status_code == 200
        assert r.json()["has_analytics_token"] is False, "B must not see A's token"

        # B cannot remove A's token
        r = broker_client.delete(
            "/auth/analytics-token",
            headers={"X-Session-Id": b_session},
            params={"broker": "UPSTOX"},
        )
        assert r.status_code == 404, f"B removing A's token -> {r.status_code} (want 404)"

        # A's token is untouched
        r = broker_client.get(
            "/auth/analytics-token/status",
            headers=_auth(broker_account),
            params={"broker": "UPSTOX"},
        )
        assert r.json()["has_analytics_token"] is True, "A's token must survive B's attempt"
    finally:
        # A cleanup
        broker_client.delete(
            "/auth/analytics-token",
            headers=_auth(broker_account),
            params={"broker": "UPSTOX"},
        )
        broker_client.post("/auth/logout", headers={"X-Session-Id": b_session})
