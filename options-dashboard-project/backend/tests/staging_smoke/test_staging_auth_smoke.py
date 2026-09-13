"""Live staging auth/session/CRDB-path smoke tests (Staging Tasks 1-10, 12).

Every request goes to the deployed Render staging service. Synthetic
credentials are generated at runtime and live only in this module's memory.
Session IDs are masked in all output.
"""

import secrets

import httpx
import pytest

from tests.staging_smoke.conftest import (
    BASE_URL,
    FRONTEND_URL,
    HTTP_TIMEOUT,
    UNRELATED_ORIGIN,
    generate_test_email,
    generate_test_password,
    mask,
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=HTTP_TIMEOUT)


# ---------------------------------------------------------------------------
# Tests 1-2: health / readiness
# ---------------------------------------------------------------------------
def test_01_health():
    with _client() as c:
        r = c.get("/health")
    assert r.status_code == 200, f"/health -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("status") == "ok", f"/health body: {body}"


def test_02_readiness():
    with _client() as c:
        r = c.get("/readiness")
    assert r.status_code == 200, f"/readiness -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    checks = body.get("checks") or {}
    assert checks.get("database") == "ok", f"readiness checks: {checks}"
    assert checks.get("token_store") == "ok", f"readiness checks: {checks}"


# ---------------------------------------------------------------------------
# Tests 3-9: full auth lifecycle against the live stack
# ---------------------------------------------------------------------------
@pytest.fixture()
def account():
    """One synthetic account per test (runtime-generated, memory only)."""
    return {"email": generate_test_email(), "password": generate_test_password()}


def _register(c: httpx.Client, account: dict) -> httpx.Response:
    return c.post(
        "/auth/register",
        json={
            "email": account["email"],
            "password": account["password"],
            "name": "Staging Smoke",
        },
    )


def _login(c: httpx.Client, account: dict) -> str:
    r = c.post(
        "/auth/login-email",
        json={"email": account["email"], "password": account["password"]},
    )
    assert r.status_code == 200, f"login-email -> {r.status_code}: {r.text[:200]}"
    session_id = r.json().get("session_id")
    assert session_id, "login-email returned no session_id"
    return session_id


def _me(c: httpx.Client, session_id: str) -> httpx.Response:
    return c.get("/auth/me", headers={"X-Session-Id": session_id})


def test_03_register(account):
    with _client() as c:
        r = _register(c, account)
    assert r.status_code == 200, f"register -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("ok") is True, f"register body: {body}"


def test_04_login_returns_masked_session(account):
    with _client() as c:
        assert _register(c, account).status_code == 200
        session_id = _login(c, account)
        # Session id stays in memory only; output is masked.
        print(f"login session: {mask(session_id)}")
        # Session is immediately usable (sanity for Test 5's precondition).
        assert _me(c, session_id).status_code == 200
        c.post("/auth/logout", headers={"X-Session-Id": session_id})


def test_05_me_identity_matches(account):
    with _client() as c:
        _register(c, account)
        session_id = _login(c, account)
        r = _me(c, session_id)
        assert r.status_code == 200, f"/auth/me -> {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("email") == account["email"], "identity email mismatch"
        assert body.get("status") == "active", f"identity status: {body}"
        assert body.get("identity_source") == "email", f"identity source: {body}"
        c.post("/auth/logout", headers={"X-Session-Id": session_id})


def test_06_status_logged_in(account):
    with _client() as c:
        _register(c, account)
        session_id = _login(c, account)
        r = c.get("/auth/status", headers={"X-Session-Id": session_id})
        assert r.status_code == 200, f"/auth/status -> {r.status_code}"
        body = r.json()
        assert body.get("logged_in") is True, f"status body: {body}"
        c.post("/auth/logout", headers={"X-Session-Id": session_id})


def test_07_paper_capital_crdb_path(account):
    """Authenticated request that must reach CockroachDB to answer."""
    with _client() as c:
        _register(c, account)
        session_id = _login(c, account)
        r = c.get("/paper/capital", headers={"X-Session-Id": session_id})
        assert r.status_code == 200, f"/paper/capital -> {r.status_code}: {r.text[:200]}"
        c.post("/auth/logout", headers={"X-Session-Id": session_id})


def test_08_logout(account):
    with _client() as c:
        _register(c, account)
        session_id = _login(c, account)
        r = c.post("/auth/logout", headers={"X-Session-Id": session_id})
        assert r.status_code == 200, f"logout -> {r.status_code}: {r.text[:200]}"


def test_09_post_logout_me_401(account):
    with _client() as c:
        _register(c, account)
        session_id = _login(c, account)
        assert c.post("/auth/logout", headers={"X-Session-Id": session_id}).status_code == 200
        r = _me(c, session_id)
        assert r.status_code == 401, f"post-logout /auth/me -> {r.status_code} (want 401)"


# ---------------------------------------------------------------------------
# Test 10: Google OAuth state endpoint
# ---------------------------------------------------------------------------
def test_10_google_state_present():
    origin = FRONTEND_URL
    with _client() as c:
        r = c.post("/auth/google/state", headers={"Origin": origin})
    assert r.status_code == 200, f"/auth/google/state -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    state, nonce = body.get("state"), body.get("nonce")
    assert state, "state missing from /auth/google/state response"
    assert nonce, "nonce missing from /auth/google/state response"
    # Values are never printed; only shape and lengths.
    print(f"google state shape ok (state len={len(state)}, nonce len={len(nonce)})")


# ---------------------------------------------------------------------------
# Test 12: CORS behavior from the staging frontend origin + an unrelated origin
# ---------------------------------------------------------------------------
def test_12_cors_preflight_and_rejection():
    # (a) Unauthenticated preflight from the staging origin must be allowed.
    with _client() as c:
        pre = c.options(
            "/auth/login-email",
            headers={
                "Origin": FRONTEND_URL,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert pre.status_code == 200, f"preflight -> {pre.status_code}"
    acao = pre.headers.get("access-control-allow-origin", "")
    assert acao == FRONTEND_URL, f"allow-origin = {acao!r} (want exact staging origin)"
    assert pre.headers.get("access-control-allow-credentials") == "true", (
        "credentials must remain allowed for the staging origin"
    )
    wild = pre.headers.get("access-control-allow-origin") == "*"
    assert not wild, "wildcard origin must never be returned"

    # (b) The same preflight from an unrelated origin must NOT be allowed.
    with _client() as c:
        rej = c.options(
            "/auth/login-email",
            headers={
                "Origin": UNRELATED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    acao_rej = rej.headers.get("access-control-allow-origin", "")
    assert acao_rej == "", (
        f"unrelated origin must get no allow-origin header (got {acao_rej!r})"
    )


# ---------------------------------------------------------------------------
# Shared-hygiene guard: every request in this module targets staging only.
# ---------------------------------------------------------------------------
def test_00_targets_are_staging():
    assert BASE_URL.startswith("https://strikenova-api-staging.onrender.com")
    assert FRONTEND_URL.startswith("https://strikenova-frontend-staging.vercel.app")
    assert "localhost" not in BASE_URL and "localhost" not in FRONTEND_URL
    assert secrets.token_hex(1)  # import sanity; no behavioral meaning
