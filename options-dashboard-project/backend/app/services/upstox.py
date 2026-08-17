import logging
from urllib.parse import urlencode

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com/v2"
# Upstox API version 3 host (used by the read-only Fund & Margin endpoint).
V3_BASE_URL = "https://api.upstox.com/v3"


class UpstoxError(Exception):
    """An Upstox API call failed. Carries the upstream HTTP status and message."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"Upstox API error ({status_code}): {message}")
        self.status_code = status_code
        self.message = message


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:300] or f"HTTP {resp.status_code}"
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        message = errors[0].get("message")
        if message:
            return message
    return str(body)[:300]


async def _request(method: str, path: str, base_url: str = BASE_URL, **kwargs) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{base_url}{path}", **kwargs)
    except httpx.RequestError as e:
        logger.error("Could not reach Upstox at %s: %s", path, e)
        raise UpstoxError(502, f"Could not reach Upstox: {e}") from e

    if resp.status_code >= 400:
        message = _error_message(resp)
        logger.error("Upstox %s %s failed with %s: %s", method, path, resp.status_code, message)
        raise UpstoxError(resp.status_code, message)

    try:
        return resp.json()
    except ValueError as e:
        logger.error("Upstox %s %s returned non-JSON response", method, path)
        raise UpstoxError(502, "Upstox returned an unreadable (non-JSON) response") from e


def get_login_url(state: str) -> str:
    params = urlencode({
        "response_type": "code",
        "client_id": settings.UPSTOX_API_KEY,
        "redirect_uri": settings.UPSTOX_REDIRECT_URI,
        "state": state,
    })
    return f"{BASE_URL}/login/authorization/dialog?{params}"


async def exchange_code_for_token(code: str) -> str:
    data = await _request(
        "POST",
        "/login/authorization/token",
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "code": code,
            "client_id": settings.UPSTOX_API_KEY,
            "client_secret": settings.UPSTOX_API_SECRET,
            "redirect_uri": settings.UPSTOX_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    access_token = data.get("access_token")
    if not access_token:
        logger.error("Upstox token response had no access_token (keys: %s)", list(data.keys()))
        raise UpstoxError(502, "Upstox token response did not include an access token")
    return access_token


async def get_option_chain(access_token: str, instrument_key: str, expiry_date: str) -> dict:
    return await _request(
        "GET",
        "/option/chain",
        params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_option_contracts(access_token: str, instrument_key: str) -> dict:
    """Returns available strikes/expiries for an instrument (used to list expiry dates)."""
    return await _request(
        "GET",
        "/option/contract",
        params={"instrument_key": instrument_key},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_market_status(access_token: str) -> dict:
    """NSE F&O market status from Upstox's authoritative feed.

    Returns the full response body; the ``data`` object carries
    ``exchange``, ``status`` (e.g. ``NORMAL_OPEN`` / ``NORMAL_CLOSE``) and
    ``last_updated``. Raises :class:`UpstoxError` when the exchange is
    unreachable or the request fails.
    """
    return await _request(
        "GET",
        "/market/status/NSE_FO",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_funds_and_margin(access_token: str) -> dict:
    """Read-only account funds & margin (Phase 6.1).

    ``GET /v3/user/get-funds-and-margin`` with ``Api-Version: 3.0`` returns
    the V3 breakdown: ``available_to_trade`` (cash + pledge) and
    ``unavailable_to_trade`` (unsettled profit / unavailable pledge). Raises
    :class:`UpstoxError` on failure — note the documented daily maintenance
    window (12:00 AM – 5:30 AM IST) returns HTTP 423 Locked, which callers
    must surface as an UNAVAILABLE broker status, never as a crash or a 0.
    """
    return await _request(
        "GET",
        "/user/get-funds-and-margin",
        base_url=V3_BASE_URL,
        headers={
            "Accept": "application/json",
            "Api-Version": "3.0",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_margin_details(access_token: str, instruments: list[dict]) -> dict:
    """Read-only broker margin for a basket of instruments (Phase 6.1).

    ``POST /v2/charges/margin`` accepts up to 20 instruments and returns the
    broker-computed margin for the WHOLE request (``data.required_margin``,
    ``data.final_margin``) plus per-instrument rows in ``data.margins``. The
    broker receives the complete multi-leg strategy set so its margin engine
    applies spread/combination logic — the platform never sums per-leg
    margins itself. Each instrument needs ``instrument_key``, ``quantity``
    (broker contract units), ``transaction_type`` (BUY/SELL) and
    ``product`` (I | D | CO | MTF). Raises :class:`UpstoxError` on failure.
    """
    return await _request(
        "POST",
        "/charges/margin",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"instruments": instruments},
    )
