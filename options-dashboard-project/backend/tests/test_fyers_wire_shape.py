"""Wire-shape regression tests for the FYERS raw client URL assembly.

Background (staging incident, 2026-09-15): the first live auth-code
exchange returned FYERS' router 404 because the path constants carried the
full ``/api/v3`` prefix while ``_request`` already prefixed ``API_BASE`` —
producing ``/api/v3/api/v3/validate-authcode``. Mocked adapter tests
(mocker replaces these functions) never exercised the URL assembly.

These tests pin the EXACT outgoing URL of every ``_request`` call site:

* REST endpoints → ``https://api-t1.fyers.in/api/v3/<relative-path>``
* ``/data/*`` endpoints → ``https://api-t1.fyers.in/data/*`` (host ROOT —
  FYERS does not serve them under ``/api/v3``; verified live against the
  router: ``/api/v3/data/*`` and ``/api/v3/quotes`` 404, root ``/data/*``
  exists behind the WAF).

The adapter functions are exercised through the real raw client (respx
mocks HTTP), so a future path/URL regression fails here first.
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.services import fyers

APP_ID = "SYNTHAPP-100"
SECRET = "synthetic-secret"
TOKEN = "synthetic-access-token"


def _ok() -> Response:
    return Response(200, json={"s": "ok", "code": 200, "message": "", "data": {}})


@respx.mock
@pytest.mark.asyncio
async def test_exchange_url_is_single_prefixed():
    route = respx.post("https://api-t1.fyers.in/api/v3/validate-authcode").mock(
        return_value=_ok()
    )
    body = await fyers.exchange_code_for_token(APP_ID, SECRET, "some-code")
    assert body["s"] == "ok"
    assert route.called
    sent = route.calls.last.request.read()
    assert b"appIdHash" in sent and b"grant_type" in sent


@respx.mock
@pytest.mark.asyncio
async def test_rest_endpoints_are_single_prefixed_under_api_v3():
    for fn, path in (
        (lambda: fyers.get_profile(TOKEN, APP_ID), "/api/v3/profile"),
        (lambda: fyers.get_funds(TOKEN, APP_ID), "/api/v3/funds"),
        (lambda: fyers.get_positions(TOKEN, APP_ID), "/api/v3/positions"),
        (lambda: fyers.get_holdings(TOKEN, APP_ID), "/api/v3/holdings"),
        (lambda: fyers.get_orders(TOKEN, APP_ID), "/api/v3/orders"),
        (lambda: fyers.get_tradebook(TOKEN, APP_ID), "/api/v3/tradebook"),
    ):
        respx.routes.clear()
        route = respx.get(f"https://api-t1.fyers.in{path}").mock(return_value=_ok())
        await fn()
        assert route.called, f"{path} never called"


@respx.mock
@pytest.mark.asyncio
async def test_data_endpoints_live_at_host_root_not_under_api_v3():
    quotes_route = respx.post("https://api-t1.fyers.in/data/quotes").mock(
        return_value=_ok()
    )
    chain_route = respx.post("https://api-t1.fyers.in/data/options-chain-v3").mock(
        return_value=_ok()
    )
    await fyers.get_quotes(TOKEN, APP_ID, ["NSE:SBIN-EQ"])
    await fyers.get_option_chain(TOKEN, APP_ID, "NSE:NIFTY50-INDEX", "2026-10-29")
    assert quotes_route.called and chain_route.called
    # The double-prefixed variants must NEVER be requested.
    assert not respx.post("https://api-t1.fyers.in/api/v3/data/quotes").called


@respx.mock
@pytest.mark.asyncio
async def test_auth_header_is_app_id_colon_token_not_bearer():
    route = respx.get("https://api-t1.fyers.in/api/v3/profile").mock(return_value=_ok())
    await fyers.get_profile(TOKEN, APP_ID)
    auth = route.calls.last.request.headers.get("Authorization")
    assert auth == f"{APP_ID}:{TOKEN}", "REST header must be '<app_id>:<token>'"
    assert not auth.lower().startswith("bearer ")


def test_app_id_hash_is_sha256_of_app_colon_secret():
    import hashlib

    assert fyers.build_app_id_hash(APP_ID, SECRET) == hashlib.sha256(
        f"{APP_ID}:{SECRET}".encode()
    ).hexdigest()


def test_login_url_uses_base_url_once_and_contains_no_secret():
    url = fyers.get_login_url(
        "some-state", app_id=APP_ID, redirect_uri="https://example.test/cb"
    )
    assert url.startswith("https://api-t1.fyers.in/api/v3/generate-authcode?")
    assert url.count("/api/v3") == 1
    assert "client_id=SYNTHAPP-100" in url
    assert "response_type=code" in url
    assert "state=some-state" in url
    assert SECRET not in url
