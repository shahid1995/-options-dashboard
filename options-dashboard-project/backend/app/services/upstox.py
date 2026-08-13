import httpx
from app.config import settings

BASE_URL = "https://api.upstox.com/v2"


def get_login_url() -> str:
    return (
        f"{BASE_URL}/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={settings.UPSTOX_API_KEY}"
        f"&redirect_uri={settings.UPSTOX_REDIRECT_URI}"
    )


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


async def _get(path: str, access_token: str, params: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_option_chain(access_token: str, instrument_key: str, expiry_date: str) -> dict:
    return await _get("/option/chain", access_token, {"instrument_key": instrument_key, "expiry_date": expiry_date})


async def get_option_contracts(access_token: str, instrument_key: str) -> dict:
    """Returns available strikes/expiries for an instrument (used to list expiry dates)."""
    return await _get("/option/contract", access_token, {"instrument_key": instrument_key})
