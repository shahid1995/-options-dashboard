import logging

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upstox.com/v2"


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


async def _request(method: str, path: str, **kwargs) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{BASE_URL}{path}", **kwargs)
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


def get_login_url() -> str:
    return (
        f"{BASE_URL}/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={settings.UPSTOX_API_KEY}"
        f"&redirect_uri={settings.UPSTOX_REDIRECT_URI}"
    )


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
