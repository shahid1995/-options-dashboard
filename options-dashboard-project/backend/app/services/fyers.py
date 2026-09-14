"""Raw FYERS API client (broker-specific layer — AD-6 boundary).

Mirrors the role of ``app.services.upstox`` for the FYERS broker: base
URLs, OAuth, tokens, endpoint paths, request/response transport and
``FyersError`` all stay HERE and in the FYERS adapter package
(``app.brokers.adapters.fyers``). Nothing in this module is imported by
domain/application code except through the adapter boundary.

Authoritative FYERS contract facts implemented here:

- ``appIdHash = SHA256("<app_id>:<secret_id>")`` — the API **App ID**,
  never the customer's Login ID.
- The OAuth ``client_id`` parameter on the authorization URL is the API
  App ID (NOT the customer Login ID).
- Auth-code exchange: ``POST /api/v3/validate-authcode``.
- REST auth header: ``Authorization: <app_id>:<access_token>`` (AD-9) —
  NOT Bearer. WebSocket uses Bearer, but that lives in the adapter's
  streaming transport, not here.
- Data endpoints (quotes / option chain / history) live under the
  ``/data`` path on the same v3 host.
- Access tokens are DAILY (expire at the end of the trading day); the
  refresh token (15 days, PIN-gated) may be discontinued — daily
  re-authentication remains the baseline (AD-11).
- Order execution is capability-dependent in 2026: only a compliant
  ``-200`` app with activated trading, a static IP and order-placement
  permission may place orders. The adapter owns that capability gate.

Secrets are never logged in this module: token/appIdHash values are never
passed to ``logger``.
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api-t1.fyers.in"
API_BASE = f"{BASE_URL}/api/v3"
DATA_BASE = f"{API_BASE}/data"

AUTH_GENERATE_PATH = "/api/v3/generate-authcode"
AUTH_VALIDATE_PATH = "/api/v3/validate-authcode"
PROFILE_PATH = "/api/v3/profile"
FUNDS_PATH = "/api/v3/funds"
POSITIONS_PATH = "/api/v3/positions"
HOLDINGS_PATH = "/api/v3/holdings"
ORDERS_PATH = "/api/v3/orders"
ORDERS_SWEEP_PATH = "/api/v3/orders-simplified"
TRADEBOOK_PATH = "/api/v3/tradebook"
QUOTES_PATH = "/data/quotes"
OPTION_CHAIN_PATH = "/data/options-chain-v3"


class FyersError(Exception):
    """A FYERS API call failed. Carries the upstream HTTP status and message."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"Fyers API error ({status_code}): {message}")
        self.status_code = status_code
        self.message = message


def build_app_id_hash(app_id: str, secret_id: str) -> str:
    """``appIdHash`` — exactly SHA256("<app_id>:<secret_id>") hex digest.

    The App ID is the API application identifier (e.g. ``SPXXXX-200``),
    never the customer's Login ID. The hash is a credential-equivalent:
    callers must never log it.
    """
    return hashlib.sha256(f"{app_id}:{secret_id}".encode()).hexdigest()


def get_login_url(
    state: str,
    *,
    app_id: str,
    redirect_uri: str,
) -> str:
    """Build the FYERS OAuth authorization (generate-authcode) URL.

    ``client_id`` here is the API **App ID** — never the customer's
    Login ID (that identity is resolved from the profile after OAuth).
    The secret is never part of this URL.
    """
    if not app_id:
        raise FyersError(500, "No FYERS app id available for authorization.")
    if not redirect_uri:
        raise FyersError(500, "No FYERS redirect URI available for authorization.")
    params = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return f"{BASE_URL}{AUTH_GENERATE_PATH}?{params}"


def rest_auth_header(app_id: str, access_token: str) -> str:
    """REST authorization header — ``Authorization: <app_id>:<access_token>``.

    AD-9: FYERS REST is NOT Bearer (WebSocket is). One function so both
    the adapter and any future transport share the exact format.
    """
    return f"{app_id}:{access_token}"


async def _request(
    method: str,
    path: str,
    *,
    base_url: str = API_BASE,
    headers: dict | None = None,
    json: dict | None = None,
    params: dict | None = None,
) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method, f"{base_url}{path}", headers=headers or {}, json=json, params=params
            )
    except httpx.RequestError as e:
        logger.error("Could not reach FYERS at %s: %s", path, type(e).__name__)
        raise FyersError(502, f"Could not reach FYERS: {type(e).__name__}") from e

    if resp.status_code >= 400:
        message = _error_message(resp)
        logger.error(
            "FYERS %s %s failed with %s", method, path, resp.status_code
        )  # message text only — never the request headers (they carry the token)
        raise FyersError(resp.status_code, message)

    try:
        return resp.json()
    except ValueError as e:
        logger.error("FYERS %s %s returned non-JSON response", method, path)
        raise FyersError(502, "FYERS returned an unreadable (non-JSON) response") from e


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:300] or f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message[:300]
        return str(body)[:300]
    return str(body)[:300]


def validate_authcode_payload(app_id: str, secret_id: str, code: str) -> dict:
    """Build the ``POST /api/v3/validate-authcode`` request body."""
    return {
        "grant_type": "authorization_code",
        "appIdHash": build_app_id_hash(app_id, secret_id),
        "code": code,
    }


async def exchange_code_for_token(app_id: str, secret_id: str, code: str) -> dict:
    """Exchange an authorization code for tokens (auth-code flow).

    Returns the FULL response body so the adapter can carry both the
    access token AND the refresh token (the FYERS refresh token must not
    be silently discarded — see ``app.identity.BrokerToken``'s encrypted
    refresh column). The body also carries the FYERS ``s`` status field.
    """
    return await _request(
        "POST",
        AUTH_VALIDATE_PATH,
        json=validate_authcode_payload(app_id, secret_id, code),
    )


async def get_profile(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/profile`` — authenticated customer profile.

    The payload's identity-field shape is the FYERS adapter's identity
    extraction concern (see
    ``app.brokers.adapters.fyers.profile``); this function returns the
    raw body.
    """
    return await _request(
        "GET", PROFILE_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_funds(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/funds`` — funds & margin limit breakdown."""
    return await _request(
        "GET", FUNDS_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_positions(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/positions`` — current-day trading positions."""
    return await _request(
        "GET", POSITIONS_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_holdings(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/holdings`` — long-term portfolio holdings."""
    return await _request(
        "GET", HOLDINGS_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_orders(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/orders`` — order book."""
    return await _request(
        "GET", ORDERS_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_tradebook(access_token: str, app_id: str) -> dict:
    """``GET /api/v3/tradebook`` — executed trades."""
    return await _request(
        "GET", TRADEBOOK_PATH, headers={"Authorization": rest_auth_header(app_id, access_token)}
    )


async def get_quotes(access_token: str, app_id: str, symbols: list[str]) -> dict:
    """``POST /data/quotes`` — full market quotes for FYERS symbols.

    ``symbols`` are FYERS instrument symbols (``NSE:NIFTY50-INDEX``,
    ``NSE:NIFTY25OCT24500CE``, ...). The FYERS symbol grammar stays
    inside the adapter boundary.
    """
    if not symbols:
        raise FyersError(400, "No symbols requested for FYERS quotes.")
    return await _request(
        "POST",
        QUOTES_PATH,
        base_url=DATA_BASE,
        headers={
            "Authorization": rest_auth_header(app_id, access_token),
            "Content-Type": "application/json",
        },
        json={"symbols": ",".join(symbols)},
    )


async def get_option_chain(access_token: str, app_id: str, symbol: str, expiry_date: str) -> dict:
    """``POST /data/options-chain-v3`` — option chain for one FYERS symbol.

    ``symbol`` is the FYERS underlying symbol (``NSE:NIFTY50-INDEX``),
    ``expiry_date`` is ``YYYY-MM-DD``. Raw body returned; canonical
    normalization happens in the adapter mapper.
    """
    return await _request(
        "POST",
        OPTION_CHAIN_PATH,
        base_url=DATA_BASE,
        headers={
            "Authorization": rest_auth_header(app_id, access_token),
            "Content-Type": "application/json",
        },
        json={"symbol": symbol, "expiry": expiry_date, "strikecount": 200},
    )
