import httpx
import pytest
import respx

from app.config import settings
from app.services import upstox


def test_get_login_url_contains_client_id_redirect_and_state():
    url = upstox.get_login_url("state-123")
    assert url.startswith(f"{upstox.BASE_URL}/login/authorization/dialog")
    assert "response_type=code" in url
    assert f"client_id={settings.UPSTOX_API_KEY}" in url
    params = dict(httpx.QueryParams(url.split("?", 1)[1]))
    assert params["redirect_uri"] == settings.UPSTOX_REDIRECT_URI
    assert params["state"] == "state-123"


@respx.mock
async def test_exchange_code_for_token_returns_access_token():
    route = respx.post(f"{upstox.BASE_URL}/login/authorization/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-123"})
    )

    token = await upstox.exchange_code_for_token("auth-code")

    assert token == "tok-123"
    assert route.called
    body = route.calls.last.request.content.decode()
    assert "code=auth-code" in body
    assert "grant_type=authorization_code" in body


@respx.mock
async def test_exchange_code_for_token_raises_on_http_error():
    respx.post(f"{upstox.BASE_URL}/login/authorization/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await upstox.exchange_code_for_token("bad-code")


@respx.mock
async def test_get_option_chain_sends_auth_header_and_params():
    route = respx.get(f"{upstox.BASE_URL}/option/chain").mock(
        return_value=httpx.Response(200, json={"data": [{"strike_price": 25000}]})
    )

    data = await upstox.get_option_chain("tok-123", "NSE_INDEX|Nifty 50", "2026-08-28")

    assert data == {"data": [{"strike_price": 25000}]}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok-123"
    params = dict(httpx.QueryParams(request.url.query))
    assert params == {"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": "2026-08-28"}


@respx.mock
async def test_get_option_chain_raises_on_http_error():
    respx.get(f"{upstox.BASE_URL}/option/chain").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await upstox.get_option_chain("bad-token", "NSE_INDEX|Nifty 50", "2026-08-28")


@respx.mock
async def test_get_option_contracts_sends_auth_header_and_params():
    route = respx.get(f"{upstox.BASE_URL}/option/contract").mock(
        return_value=httpx.Response(200, json={"data": [{"expiry": "2026-08-28"}]})
    )

    data = await upstox.get_option_contracts("tok-123", "NSE_INDEX|Nifty 50")

    assert data == {"data": [{"expiry": "2026-08-28"}]}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok-123"
    params = dict(httpx.QueryParams(request.url.query))
    assert params == {"instrument_key": "NSE_INDEX|Nifty 50"}
