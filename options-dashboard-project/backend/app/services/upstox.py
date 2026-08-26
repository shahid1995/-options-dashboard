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


async def get_market_status(access_token: str, exchange: str = "NSE_FO") -> dict:
    """Market status for one exchange from Upstox's authoritative feed.

    ``exchange`` is the segment's feed (NSE_FO for index/stock derivatives,
    NSE_CASH for the equity cash segment, NSE_CD for currency, MCX_COMM for
    commodities). Returns the full response body; the ``data`` object
    carries ``exchange``, ``status`` (e.g. ``NORMAL_OPEN`` /
    ``NORMAL_CLOSE`` / ``CLOSING``) and ``last_updated``. Raises
    :class:`UpstoxError` when the exchange is unreachable or the request
    fails.
    """
    return await _request(
        "GET",
        f"/market/status/{exchange}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_broker_profile(access_token: str) -> dict:
    """Read-only Upstox user profile (Phase 6.4.1).

    ``GET /v2/user/profile`` returns the authenticated customer's profile:
    ``data.user_name``, ``data.email``, ``data.user_id``, ``data.user_type``,
    ``data.is_active``, ``data.exchanges``, ``data.products``,
    ``data.order_types``, ``data.poa``, ``data.ddpi``. Raises
    :class:`UpstoxError` on failure. The raw payload is normalized by
    ``app.services.broker_profile`` — credentials are never exposed.
    """
    return await _request(
        "GET",
        "/user/profile",
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


# ---------------------------------------------------------------------------
# Phase 7.8A — Historical Candle Data (V3)
# ---------------------------------------------------------------------------


async def get_historical_candles(
    access_token: str,
    instrument_key: str,
    to_date: str,
    from_date: str | None = None,
    unit: str = "minutes",
    interval: int = 3,
) -> dict:
    """Fetch historical candle data from Upstox V3.

    ``GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}[/{from_date}]``

    Returns the raw response dict with ``data.candles`` array.
    Each candle: ``[timestamp, open, high, low, close, volume, open_interest]``
    Timestamps are IST (UTC+5:30).

    For 3-minute candles the maximum retrieval window is 1 month.
    Raises :class:`UpstoxError` on failure.
    """
    path = f"/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}"
    if from_date:
        path += f"/{from_date}"

    return await _request(
        "GET",
        path,
        base_url=V3_BASE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_intraday_candles(
    access_token: str,
    instrument_key: str,
    unit: str = "minutes",
    interval: int = 3,
) -> dict:
    """Fetch current trading day's intraday candle data from Upstox V3.

    ``GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}``

    Returns the raw response dict with ``data.candles`` array.
    Raises :class:`UpstoxError` on failure.
    """
    path = f"/historical-candle/intraday/{instrument_key}/{unit}/{interval}"

    return await _request(
        "GET",
        path,
        base_url=V3_BASE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


# ---------------------------------------------------------------------------
# Phase 7.8A — Expired Instruments (V2)
# ---------------------------------------------------------------------------


async def get_expired_expiries(
    access_token: str,
    instrument_key: str,
) -> dict:
    """Fetch all available expiry dates for expired instruments.

    ``GET /v2/expired-instruments/expiries?instrument_key={instrument_key}``

    Returns the raw response dict with ``data``: list of YYYY-MM-DD strings.
    Covers up to ~6 months of historical expiries.
    Requires Upstox Plus plan subscription.
    Raises :class:`UpstoxError` on failure.
    """
    return await _request(
        "GET",
        "/expired-instruments/expiries",
        params={"instrument_key": instrument_key},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


async def get_expired_option_contracts(
    access_token: str,
    instrument_key: str,
    expiry_date: str,
) -> dict:
    """Fetch expired option contract metadata for a given expiry date.

    ``GET /v2/expired-instruments/option/contract?instrument_key={instrument_key}&expiry_date={expiry_date}``

    Returns the raw response dict with ``data``: list of contract objects.
    Each contract includes authoritative per-instrument metadata:
    ``instrument_key``, ``trading_symbol``, ``lot_size``, ``minimum_lot``,
    ``freeze_quantity``, ``tick_size``, ``strike_price``, ``instrument_type``,
    ``expiry``, ``underlying_key``, ``underlying_type``,
    ``underlying_symbol``, ``segment``, ``exchange``, ``weekly``.

    Historical ``lot_size`` is the authoritative value for that specific
    instrument — it must be stored exactly as returned and never inferred
    from the current lot size or from an effective-date table.

    Requires Upstox Plus plan subscription (error UDAPI1149 if not subscribed).
    Raises :class:`UpstoxError` on failure.
    """
    return await _request(
        "GET",
        "/expired-instruments/option/contract",
        params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )


# ---------------------------------------------------------------------------
# Phase 7.11 -- Expired Historical Candle Data (V2)
# ---------------------------------------------------------------------------


async def get_expired_historical_candles(
    access_token: str,
    expired_instrument_key: str,
    interval: str,
    to_date: str,
    from_date: str,
) -> dict:
    """Fetch historical candle data for an expired option/future contract.

    ``GET /v2/expired-instruments/historical-candle/{expired_key}/{interval}/{to_date}/{from_date}``

    Returns the raw response dict with ``data.candles`` array.
    Each candle: ``[timestamp, open, high, low, close, volume, open_interest]``
    Timestamps are IST (UTC+5:30).

    ``expired_instrument_key`` is the instrument_key from the expired contracts
    API (e.g. ``NSE_FO|47983|17-04-2025``).

    ``interval`` is one of: 1minute, 3minute, 5minute, 15minute, 30minute, day.

    Requires Upstox Plus plan subscription.
    Raises :class:`UpstoxError` on failure.
    """
    path = (
        f"/expired-instruments/historical-candle/{expired_instrument_key}"
        f"/{interval}/{to_date}/{from_date}"
    )

    return await _request(
        "GET",
        path,
        base_url=BASE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
