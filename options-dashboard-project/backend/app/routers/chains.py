from fastapi import APIRouter, HTTPException, Query
from app.services import upstox, token_store
from app.services.upstox import UpstoxError

router = APIRouter()

INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}


def _upstox_http_error(e: UpstoxError) -> HTTPException:
    if e.status_code == 401:
        # The stored token is no longer valid (Upstox tokens expire daily),
        # so drop it and tell the frontend to log in again.
        token_store.clear_token()
        return HTTPException(status_code=401, detail="Upstox session expired. Please log in again.")
    return HTTPException(status_code=502, detail=f"Upstox API error: {e.message}")


def require_token() -> str:
    token = token_store.get_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return token


@router.get("/{symbol}/expiries")
async def list_expiries(symbol: str):
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")
    token = require_token()
    try:
        data = await upstox.get_option_contracts(token, INSTRUMENT_KEYS[symbol])
    except UpstoxError as e:
        raise _upstox_http_error(e) from e
    expiries = sorted({c["expiry"] for c in data.get("data", []) if "expiry" in c})
    return {"symbol": symbol, "expiries": expiries}


@router.get("/{symbol}")
async def get_chain(symbol: str, expiry_date: str = Query(..., description="YYYY-MM-DD")):
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")
    token = require_token()
    try:
        raw = await upstox.get_option_chain(token, INSTRUMENT_KEYS[symbol], expiry_date)
    except UpstoxError as e:
        raise _upstox_http_error(e) from e

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
