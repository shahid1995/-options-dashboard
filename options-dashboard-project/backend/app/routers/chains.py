from fastapi import APIRouter, HTTPException, Query
from app.services import upstox, token_store

router = APIRouter()

INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}


def require_token() -> str:
    token = token_store.get_token()
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return token


def resolve_instrument(symbol: str) -> tuple[str, str]:
    """Normalizes a symbol and returns (symbol, instrument_key), or raises 404."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")
    return symbol, INSTRUMENT_KEYS[symbol]


@router.get("/{symbol}/expiries")
async def list_expiries(symbol: str):
    symbol, instrument_key = resolve_instrument(symbol)
    token = require_token()
    data = await upstox.get_option_contracts(token, instrument_key)
    expiries = sorted({c["expiry"] for c in data.get("data", []) if "expiry" in c})
    return {"symbol": symbol, "expiries": expiries}


@router.get("/{symbol}")
async def get_chain(symbol: str, expiry_date: str = Query(..., description="YYYY-MM-DD")):
    symbol, instrument_key = resolve_instrument(symbol)
    token = require_token()
    raw = await upstox.get_option_chain(token, instrument_key, expiry_date)

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
