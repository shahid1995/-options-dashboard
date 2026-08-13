import asyncio
from datetime import date

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Query, WebSocket, WebSocketDisconnect
from app.services import upstox, token_store

router = APIRouter()

INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}

WS_PUSH_INTERVAL_SECONDS = 3


def require_token(session_id: str | None) -> str:
    token = token_store.get_token(session_id)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return token


def resolve_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")
    return symbol


def validate_expiry_date(expiry_date: str) -> str:
    try:
        date.fromisoformat(expiry_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="expiry_date must be YYYY-MM-DD")
    return expiry_date


async def call_upstox(coro):
    """Awaits an upstox call, translating auth failures into a 401 that also
    clears the stored token (Upstox tokens expire daily at 3:30 AM)."""
    try:
        return await coro
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            token_store.clear_token()
            raise HTTPException(status_code=401, detail="Upstox session expired. Please log in again.")
        raise HTTPException(status_code=502, detail=f"Upstox API error ({e.response.status_code})")


def transform_chain(symbol: str, expiry_date: str, raw: dict) -> dict:
    rows = []
    underlying_spot = None

    for item in raw.get("data", []):
        strike = item.get("strike_price")
        if underlying_spot is None:
            underlying_spot = item.get("underlying_spot_price")

        def leg(side_key):
            side = item.get(side_key) or {}
            market = side.get("market_data") or {}
            greeks = side.get("option_greeks") or {}

            oi = market.get("oi")
            prev_oi = market.get("prev_oi")
            chg_oi = (oi - prev_oi) if (oi is not None and prev_oi is not None) else None

            return {
                "ltp": market.get("ltp"),
                "oi": oi,
                "chg_oi": chg_oi,
                "volume": market.get("volume"),
                "iv": greeks.get("iv"),
                "delta": greeks.get("delta"),
                "theta": greeks.get("theta"),
                "gamma": greeks.get("gamma"),
                "vega": greeks.get("vega"),
                "pop": greeks.get("pop"),
            }

        rows.append({
            "strike": strike,
            "call": leg("call_options"),
            "put": leg("put_options"),
        })

    rows.sort(key=lambda r: r["strike"])

    return {
        "symbol": symbol,
        "expiry_date": expiry_date,
        "underlying_spot_price": underlying_spot,
        "chain": rows,
    }


@router.get("/{symbol}/expiries")
async def list_expiries(symbol: str, session_id: str | None = Cookie(default=None)):
    symbol = resolve_symbol(symbol)
    token = require_token(session_id)
    data = await call_upstox(upstox.get_option_contracts(token, INSTRUMENT_KEYS[symbol]))
    expiries = sorted({c["expiry"] for c in data.get("data", []) if "expiry" in c})
    return {"symbol": symbol, "expiries": expiries}


@router.get("/{symbol}")
async def get_chain(
    symbol: str,
    expiry_date: str = Query(..., description="YYYY-MM-DD"),
    session_id: str | None = Cookie(default=None),
):
    symbol = resolve_symbol(symbol)
    expiry_date = validate_expiry_date(expiry_date)
    token = require_token(session_id)
    raw = await call_upstox(upstox.get_option_chain(token, INSTRUMENT_KEYS[symbol], expiry_date))
    return transform_chain(symbol, expiry_date, raw)


@router.websocket("/ws/{symbol}")
async def chain_ws(websocket: WebSocket, symbol: str, expiry_date: str = Query(...)):
    """Pushes the transformed option chain to the client every few seconds.
    Closes with 4401 on auth issues, 4404 for unknown symbols, and 4422 for
    malformed expiry dates so the frontend can fall back to HTTP polling or
    prompt a re-login."""
    await websocket.accept()

    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        await websocket.close(code=4404)
        return

    try:
        date.fromisoformat(expiry_date)
    except ValueError:
        await websocket.close(code=4422)
        return

    session_id = websocket.cookies.get("session_id")

    try:
        while True:
            token = token_store.get_token(session_id)
            if not token:
                await websocket.close(code=4401)
                return
            try:
                raw = await upstox.get_option_chain(token, INSTRUMENT_KEYS[symbol], expiry_date)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    token_store.clear_token()
                    await websocket.close(code=4401)
                else:
                    await websocket.close(code=4502)
                return
            except httpx.HTTPError:
                await websocket.close(code=4502)
                return
            await websocket.send_json(transform_chain(symbol, expiry_date, raw))
            await asyncio.sleep(WS_PUSH_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
