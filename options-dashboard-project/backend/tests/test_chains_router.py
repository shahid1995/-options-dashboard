from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.routers.chains import INSTRUMENT_KEYS
from app.services import token_store, upstox


def http_status_error(status_code):
    request = httpx.Request("GET", "https://api.upstox.com/v2/option/chain")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def logged_in():
    token_store.set_token("tok-xyz")


def make_chain_item(strike, call_market=None, put_market=None, call_greeks=None, spot=25010.5):
    return {
        "strike_price": strike,
        "underlying_spot_price": spot,
        "call_options": {
            "market_data": call_market or {},
            "option_greeks": call_greeks or {},
        },
        "put_options": {
            "market_data": put_market or {},
        },
    }


def test_expiries_unknown_symbol_returns_404(client, logged_in):
    resp = client.get("/chains/UNKNOWN/expiries")
    assert resp.status_code == 404
    assert "Unknown symbol" in resp.json()["detail"]


def test_expiries_requires_login(client):
    resp = client.get("/chains/NIFTY/expiries")
    assert resp.status_code == 401
    assert "Not logged in" in resp.json()["detail"]


def test_expiries_sorted_and_deduplicated(client, logged_in, monkeypatch):
    mock = AsyncMock(return_value={
        "data": [
            {"expiry": "2026-09-24"},
            {"expiry": "2026-08-28"},
            {"expiry": "2026-08-28"},
            {"no_expiry_key": True},
        ]
    })
    monkeypatch.setattr(upstox, "get_option_contracts", mock)

    resp = client.get("/chains/nifty/expiries")

    assert resp.status_code == 200
    assert resp.json() == {"symbol": "NIFTY", "expiries": ["2026-08-28", "2026-09-24"]}
    mock.assert_awaited_once_with("tok-xyz", INSTRUMENT_KEYS["NIFTY"])


def test_expiries_empty_data(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_contracts", AsyncMock(return_value={}))
    resp = client.get("/chains/BANKNIFTY/expiries")
    assert resp.status_code == 200
    assert resp.json() == {"symbol": "BANKNIFTY", "expiries": []}


def test_chain_unknown_symbol_returns_404(client, logged_in):
    resp = client.get("/chains/UNKNOWN", params={"expiry_date": "2026-08-28"})
    assert resp.status_code == 404


def test_chain_requires_expiry_date(client, logged_in):
    resp = client.get("/chains/NIFTY")
    assert resp.status_code == 422


def test_chain_requires_login(client):
    resp = client.get("/chains/NIFTY", params={"expiry_date": "2026-08-28"})
    assert resp.status_code == 401


def test_chain_transforms_and_sorts_rows(client, logged_in, monkeypatch):
    raw = {
        "data": [
            make_chain_item(
                25100,
                call_market={"ltp": 120.5, "oi": 500, "prev_oi": 400, "volume": 1000},
                call_greeks={"iv": 14.2, "delta": 0.55, "theta": -3.1, "gamma": 0.002, "vega": 8.5, "pop": 52.0},
                put_market={"ltp": 95.0, "oi": 300, "prev_oi": 350},
            ),
            make_chain_item(25000, call_market={"ltp": 160.0}),
        ]
    }
    mock = AsyncMock(return_value=raw)
    monkeypatch.setattr(upstox, "get_option_chain", mock)

    resp = client.get("/chains/nifty", params={"expiry_date": "2026-08-28"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NIFTY"
    assert body["expiry_date"] == "2026-08-28"
    assert body["underlying_spot_price"] == 25010.5
    mock.assert_awaited_once_with("tok-xyz", INSTRUMENT_KEYS["NIFTY"], "2026-08-28")

    strikes = [row["strike"] for row in body["chain"]]
    assert strikes == [25000, 25100]

    row = body["chain"][1]
    assert row["call"]["ltp"] == 120.5
    assert row["call"]["chg_oi"] == 100
    assert row["call"]["iv"] == 14.2
    assert row["call"]["pop"] == 52.0
    assert row["put"]["ltp"] == 95.0
    assert row["put"]["chg_oi"] == -50
    assert row["put"]["iv"] is None


def test_chain_handles_missing_oi_and_sides(client, logged_in, monkeypatch):
    raw = {
        "data": [
            {
                "strike_price": 25000,
                "underlying_spot_price": 25010.5,
                "call_options": {"market_data": {"oi": 500}},
                # put_options entirely missing
            }
        ]
    }
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(return_value=raw))

    resp = client.get("/chains/NIFTY", params={"expiry_date": "2026-08-28"})

    assert resp.status_code == 200
    row = resp.json()["chain"][0]
    assert row["call"]["oi"] == 500
    assert row["call"]["chg_oi"] is None  # prev_oi missing
    assert row["put"] == {
        "ltp": None,
        "oi": None,
        "chg_oi": None,
        "volume": None,
        "iv": None,
        "delta": None,
        "theta": None,
        "gamma": None,
        "vega": None,
        "pop": None,
    }


def test_chain_empty_data(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(return_value={}))
    resp = client.get("/chains/NIFTY", params={"expiry_date": "2026-08-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["chain"] == []
    assert body["underlying_spot_price"] is None


def test_chain_banknifty_uses_bank_instrument_key(client, logged_in, monkeypatch):
    mock = AsyncMock(return_value={})
    monkeypatch.setattr(upstox, "get_option_chain", mock)

    resp = client.get("/chains/banknifty", params={"expiry_date": "2026-08-28"})

    assert resp.status_code == 200
    assert resp.json()["symbol"] == "BANKNIFTY"
    mock.assert_awaited_once_with("tok-xyz", INSTRUMENT_KEYS["BANKNIFTY"], "2026-08-28")


@pytest.mark.parametrize("status", [401, 403])
def test_chain_upstox_auth_error_clears_token_and_returns_401(client, logged_in, monkeypatch, status):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(side_effect=http_status_error(status)))

    resp = client.get("/chains/NIFTY", params={"expiry_date": "2026-08-28"})

    assert resp.status_code == 401
    assert "session expired" in resp.json()["detail"].lower()
    assert token_store.get_token() is None


def test_chain_upstox_server_error_returns_502(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(side_effect=http_status_error(500)))

    resp = client.get("/chains/NIFTY", params={"expiry_date": "2026-08-28"})

    assert resp.status_code == 502
    assert "Upstox API error (500)" in resp.json()["detail"]
    assert token_store.get_token() == "tok-xyz"


def test_expiries_upstox_auth_error_clears_token_and_returns_401(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_contracts", AsyncMock(side_effect=http_status_error(401)))

    resp = client.get("/chains/NIFTY/expiries")

    assert resp.status_code == 401
    assert token_store.get_token() is None


def ws_close_code(client, path):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(path) as ws:
            ws.receive_json()
    return exc_info.value.code


def test_ws_unknown_symbol_closes_4404(client, logged_in):
    assert ws_close_code(client, "/chains/ws/UNKNOWN?expiry_date=2026-08-28") == 4404


def test_ws_without_login_closes_4401(client):
    assert ws_close_code(client, "/chains/ws/NIFTY?expiry_date=2026-08-28") == 4401


def test_ws_upstox_auth_error_clears_token_and_closes_4401(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(side_effect=http_status_error(403)))
    assert ws_close_code(client, "/chains/ws/NIFTY?expiry_date=2026-08-28") == 4401
    assert token_store.get_token() is None


def test_ws_upstox_server_error_closes_4502(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(side_effect=http_status_error(500)))
    assert ws_close_code(client, "/chains/ws/NIFTY?expiry_date=2026-08-28") == 4502


def test_ws_network_error_closes_4502(client, logged_in, monkeypatch):
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(side_effect=httpx.ConnectError("boom")))
    assert ws_close_code(client, "/chains/ws/NIFTY?expiry_date=2026-08-28") == 4502


def test_ws_streams_transformed_chain(client, logged_in, monkeypatch):
    raw = {"data": [make_chain_item(25000, call_market={"ltp": 160.0})]}
    monkeypatch.setattr(upstox, "get_option_chain", AsyncMock(return_value=raw))

    with client.websocket_connect("/chains/ws/nifty?expiry_date=2026-08-28") as ws:
        body = ws.receive_json()

    assert body["symbol"] == "NIFTY"
    assert body["expiry_date"] == "2026-08-28"
    assert body["chain"][0]["strike"] == 25000
    assert body["chain"][0]["call"]["ltp"] == 160.0
