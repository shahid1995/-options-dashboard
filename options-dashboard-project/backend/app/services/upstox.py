from urllib.parse import urlencode

import httpx
from app.config import settings

BASE_URL = "https://api.upstox.com/v2"


def get_login_url(state: str) -> str:
    params = urlencode({
        "response_type": "code",
        "client_id": settings.UPSTOX_API_KEY,
        "redirect_uri": settings.UPSTOX_REDIRECT_URI,
        "state": state,
    })
    return f"{BASE_URL}/login/authorization/dialog?{params}"


async def exchange_code_for_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/login/authorization/token",
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
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"]


async def get_option_chain(access_token: str, instrument_key: str, expiry_date: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/option/chain",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_option_contracts(access_token: str, instrument_key: str) -> dict:
    """Returns available strikes/expiries for an instrument (used to list expiry dates)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/option/contract",
            params={"instrument_key": instrument_key},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        resp.raise_for_status()
        return resp.json()
