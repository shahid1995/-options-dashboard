import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from app.brokers.adapters.upstox.mapper import (
    UPSTOX_INSTRUMENT_KEYS as INSTRUMENT_KEYS,  # compat re-export (adapter mapping)
)
from app.brokers.adapters.upstox.mapper import transform_chain  # compat re-export
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.gateway import gateway
from app.routers.deps import get_session_id
from app.services import token_store

router = APIRouter()

# Index option chains available via Upstox (NSE + BSE). The instrument keys
# are the canonical mapping table living in the Upstox adapter
# (app/brokers/adapters/upstox/mapper.py); this re-export keeps the
# pre-existing import path working.

WS_PUSH_INTERVAL_SECONDS = 3

WS_SESSION_PROTOCOL = "options-dashboard-session"


def ws_session(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Extracts the session ID from the websocket handshake.

    Browsers can't set custom headers on websockets, so the frontend sends the
    session ID as the second entry of the Sec-WebSocket-Protocol list (falling
    back to the session cookie). Returns (session_id, subprotocol_to_accept)."""
    requested = websocket.headers.get("sec-websocket-protocol")
    if requested:
        parts = [p.strip() for p in requested.split(",")]
        if len(parts) == 2 and parts[0] == WS_SESSION_PROTOCOL:
            return parts[1], WS_SESSION_PROTOCOL
    return websocket.cookies.get("session_id"), None


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
    """Awaits a broker-gateway call, translating session failures into a 401
    that also clears the stored token (broker tokens expire daily at 3:30 AM).

    The coroutine comes from a broker ADAPTER, so failures arrive as
    canonical BrokerError — never a provider exception.
    """
    try:
        return await coro
    except BrokerError as e:
        if e.code in BrokerErrorCode.SESSION_CODES:
            token_store.clear_token()
            raise HTTPException(status_code=401, detail="Upstox session expired. Please log in again.") from e
        raise HTTPException(status_code=502, detail=f"Upstox API error ({e.status_code}): {e.message}") from e


@router.get("/{symbol}/expiries")
async def list_expiries(symbol: str, session_id: str | None = Depends(get_session_id)):
    symbol = resolve_symbol(symbol)
    token = require_token(session_id)
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=token)
    return await call_upstox(adapter.get_option_contracts(symbol))


@router.get("/{symbol}")
async def get_chain(
    symbol: str,
    expiry_date: str = Query(..., description="YYYY-MM-DD"),
    session_id: str | None = Depends(get_session_id),
):
    symbol = resolve_symbol(symbol)
    expiry_date = validate_expiry_date(expiry_date)
    token = require_token(session_id)
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=token)
    return await call_upstox(adapter.get_option_chain(symbol, expiry_date))


@router.websocket("/ws/{symbol}")
async def chain_ws(websocket: WebSocket, symbol: str, expiry_date: str = Query(...)):
    """Pushes the canonical option chain to the client every few seconds.
    Closes with 4401 on auth issues, 4404 for unknown symbols, and 4422 for
    malformed expiry dates so the frontend can fall back to HTTP polling or
    prompt a re-login."""
    session_id, subprotocol = ws_session(websocket)
    await websocket.accept(subprotocol=subprotocol)

    symbol = symbol.upper()
    if symbol not in INSTRUMENT_KEYS:
        await websocket.close(code=4404)
        return

    try:
        date.fromisoformat(expiry_date)
    except ValueError:
        await websocket.close(code=4422)
        return

    try:
        while True:
            token = token_store.get_token(session_id)
            if not token:
                await websocket.close(code=4401)
                return
            try:
                adapter = gateway.create(BROKER_ID_UPSTOX, access_token=token)
                chain = await adapter.get_option_chain(symbol, expiry_date)
            except BrokerError as e:
                if e.code in BrokerErrorCode.SESSION_CODES:
                    token_store.clear_token()
                    await websocket.close(code=4401)
                else:
                    await websocket.close(code=4502)
                return
            await websocket.send_json(chain)
            await asyncio.sleep(WS_PUSH_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
