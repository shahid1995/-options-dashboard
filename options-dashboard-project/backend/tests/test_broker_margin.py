"""Phase 6.1 tests — Upstox broker margin integration.

Covers the phase's §31 matrix:

- Account funds (1–10): success mapping, available funds, margin used, SPAN/
  exposure, timestamp, missing field, API error, maintenance/423, token error.
- Strategy margin (11–20): single leg, bull call spread, multi-leg, instrument
  key, lots→contracts, quantity conversion, product mapping, missing key,
  >20 instruments, response mapping.
- Source/status (21–25): BROKER_REPORTED available/unavailable, never falls
  back to ESTIMATED or paper cash, null vs zero.
- Caching (26–29): same fingerprint reuses, different strategy misses, expired
  refreshes, user isolation.
- Router integration: broker margin + funds flow through GET /paper/capital
  with the real provider wired in.

Pure helpers are tested directly; the provider is exercised with injected
fetchers/resolver/cache (no HTTP); router tests use the same FastAPI TestClient
+ in-memory SQLite pattern as test_capital.py with canned broker responses.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.services import token_store
from tests.test_helpers import create_test_identity
from app.services.broker_margin import (
    BROKER_BAD_RESPONSE,
    BROKER_FUNDS_UNAVAILABLE,
    BROKER_MAINTENANCE,
    BROKER_MARGIN_UNAVAILABLE,
    BROKER_PRODUCT_DEFAULT,
    BROKER_RATE_LIMITED,
    BROKER_TOKEN_EXPIRED,
    MARGIN_REQUEST_TOO_LARGE,
    MISSING_INSTRUMENT_KEY,
    BrokerMarginCache,
    BrokerMarginError,
    UpstoxMarginProvider,
    build_margin_request_instruments,
    classify_upstox_error,
    default_instrument_key_resolver,
    lots_to_contracts,
    map_funds_payload,
    map_margin_payload,
    net_strategy_instruments,
    strategy_fingerprint,
)
from app.services.capital import SOURCE_BROKER_REPORTED, STATUS_AVAILABLE, STATUS_PARTIAL, STATUS_UNAVAILABLE
from app.services.upstox import UpstoxError

LOT = 65
EXPIRY = "2026-08-27"
NOW = datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc)

# ---- canned broker payloads -------------------------------------------------

FUNDS_OK = {
    "status": "success",
    "data": {
        "available_to_trade": {
            "total": 40034.0,
            "cash_available_to_trade": {
                "total": 39900.0,
                "cash": {"opening_balance": 50000.0},
                "margin_used": {
                    "total": 134.0,
                    "mtf": 0.0,
                    "span_exposure": 100.0,
                    "cash_margin_var_elm": 30.0,
                    "premium_present": 4.0,
                    "delivery_margin": {"total": 0.0, "equity": 0.0, "fo_settlement": 0.0},
                },
            },
            "pledge_available_to_trade": {
                "total": 134.0,
                "margin_from_pledge": {"total": 200.0, "equity": 200.0, "mutual_funds": 0.0},
                "margin_used": {"total": 66.0, "span_exposure": 66.0},
            },
        },
        "unavailable_to_trade": {
            "cash_unavailable_to_trade": {"unsettled_profit": {"todays_profit": 12.5, "previous_days": 0.0}},
            "pledge_unavailable_to_trade": {"equity": 0.0, "mutual_funds": 0.0},
        },
    },
}

MARGIN_OK = {
    "status": "success",
    "data": {
        "required_margin": 37503.0,
        "final_margin": 37000.0,
        "margins": [
            {
                "span_margin": 30000.0,
                "exposure_margin": 7503.0,
                "equity_margin": 0.0,
                "net_buy_premium": 0.0,
                "additional_margin": 0.0,
                "total_margin": 37503.0,
                "tender_margin": 0.0,
            }
        ],
    },
}


# ---- builders ----------------------------------------------------------------

def order(symbol="NIFTY", expiry=EXPIRY, strike=24350.0, option_type="call", action="buy",
          quantity=1, lot_size=LOT, status="FILLED"):
    return {
        "symbol": symbol, "expiry": expiry, "strike": strike, "option_type": option_type,
        "action": action, "quantity": quantity, "lot_size": lot_size, "status": status,
    }


def strategy(execution_id="exec-1", tag="Bull Call Spread", orders=None):
    return {
        "execution_id": execution_id,
        "strategy_tag": tag,
        "symbol": "NIFTY",
        "entry_net": 5827.25,
        "premium_outlay": 8141.25,
        "estimated_capital": 5827.25,
        "estimated_capital_basis": "premium",
        "orders": orders or [],
    }


def context(user="user-a", strategies=None):
    return {"user_id": user, "broker": "upstox", "strategies": strategies or [], "account": {}}


def build_provider(funds_result=FUNDS_OK, margin_result=MARGIN_OK, funds_error=None, margin_error=None,
                   resolver_result=None, cache=None, now=None):
    """Provider with injected fetchers; every callable is inspectable."""
    funds_fetcher = AsyncMock()
    if funds_error is not None:
        funds_fetcher.side_effect = funds_error
    else:
        funds_fetcher.return_value = funds_result
    margin_fetcher = AsyncMock()
    if margin_error is not None:
        margin_fetcher.side_effect = margin_error
    else:
        margin_fetcher.return_value = margin_result
    resolver = AsyncMock(return_value=resolver_result)
    provider = UpstoxMarginProvider(
        "tok-phase61",
        funds_fetcher=funds_fetcher,
        margin_fetcher=margin_fetcher,
        instrument_resolver=resolver,
        cache=cache or BrokerMarginCache(now=now or (lambda: NOW)),
        now=now or (lambda: NOW),
    )
    return provider, funds_fetcher, margin_fetcher, resolver


def two_leg_orders():
    return [
        order(strike=24350.0, option_type="call", action="buy"),
        order(strike=24550.0, option_type="call", action="sell"),
    ]


def two_keys():
    return [
        {**order(strike=24350.0, action="buy"), "instrument_key": "NSE_FO|NIFTY 24350 CE 270826"},
        {**order(strike=24550.0, action="sell"), "instrument_key": "NSE_FO|NIFTY 24550 CE 270826"},
    ]


# =============================================================================
# Pure helpers
# =============================================================================


def test_lots_to_contracts_conversion():
    assert lots_to_contracts(1, 65) == 65
    assert lots_to_contracts(2, 65) == 130
    assert lots_to_contracts(1, 25) == 25


def test_net_strategy_instruments_nets_same_instrument():
    orders = [order(strike=24350.0, action="buy"), order(strike=24350.0, action="sell")]
    assert net_strategy_instruments(orders) == []  # fully netted → no margin


def test_net_strategy_instruments_bull_call_spread():
    instruments = net_strategy_instruments(two_leg_orders())
    assert len(instruments) == 2
    by_strike = {i["strike"]: i for i in instruments}
    assert by_strike[24350.0]["action"] == "buy"
    assert by_strike[24350.0]["quantity"] == 1
    assert by_strike[24550.0]["action"] == "sell"
    assert by_strike[24550.0]["quantity"] == 1


def test_strategy_fingerprint_deterministic_and_normalized():
    orders_a = two_leg_orders()
    orders_b = [orders_a[1], orders_a[0]]  # reversed leg order
    fp_a = strategy_fingerprint(net_strategy_instruments(orders_a))
    fp_b = strategy_fingerprint(net_strategy_instruments(orders_b))
    assert fp_a == fp_b and len(fp_a) == 64


def test_strategy_fingerprint_sensitive_to_inputs():
    base = net_strategy_instruments(two_leg_orders())
    different_qty = net_strategy_instruments([order(strike=24350.0, action="buy", quantity=2),
                                             order(strike=24550.0, action="sell")])
    different_strike = net_strategy_instruments([order(strike=25000.0, action="buy"),
                                                 order(strike=24550.0, action="sell")])
    different_action = net_strategy_instruments([order(strike=24350.0, action="buy"),
                                                 order(strike=24550.0, action="buy")])
    fp = strategy_fingerprint(base)
    assert strategy_fingerprint(different_qty) != fp
    assert strategy_fingerprint(different_strike) != fp
    assert strategy_fingerprint(different_action) != fp


def test_build_margin_request_instruments_converts_lots_and_maps_product():
    resolved = two_keys()
    payload = build_margin_request_instruments(resolved)
    assert payload == [
        {"instrument_key": "NSE_FO|NIFTY 24350 CE 270826", "quantity": 65,
         "transaction_type": "BUY", "product": BROKER_PRODUCT_DEFAULT},
        {"instrument_key": "NSE_FO|NIFTY 24550 CE 270826", "quantity": 65,
         "transaction_type": "SELL", "product": BROKER_PRODUCT_DEFAULT},
    ]
    assert BROKER_PRODUCT_DEFAULT == "D"  # documented delivery default (§12)


def test_map_funds_payload_keeps_broker_terminology():
    mapped = map_funds_payload(FUNDS_OK["data"])
    assert mapped["available_to_trade"] == 40034.0
    assert mapped["cash_available_to_trade"] == 39900.0
    assert mapped["margin_used"] == 134.0
    assert mapped["span_exposure"] == 100.0
    assert mapped["cash_margin_var_elm"] == 30.0
    assert mapped["premium_present"] == 4.0
    assert mapped["delivery_margin"] == 0.0
    assert mapped["pledge_available_to_trade"] == 134.0
    assert mapped["margin_from_pledge"] == 200.0
    assert mapped["pledge_margin_used"] == 66.0
    assert mapped["unsettled_profit"] == 12.5
    assert mapped["raw"] == FUNDS_OK["data"]


def test_map_funds_payload_missing_fields_are_none():
    mapped = map_funds_payload({})
    assert mapped["available_to_trade"] is None
    assert mapped["margin_used"] is None
    assert mapped["span_exposure"] is None


def test_map_margin_payload_preserves_required_and_rows():
    mapped = map_margin_payload(MARGIN_OK)
    assert mapped["required_margin"] == 37503.0
    assert mapped["final_margin"] == 37000.0
    assert mapped["rows"][0]["span_margin"] == 30000.0
    assert mapped["rows"][0]["exposure_margin"] == 7503.0
    assert mapped["raw"] == MARGIN_OK


def test_classify_upstox_error_codes():
    assert classify_upstox_error(UpstoxError(401, "x"), "funds").code == BROKER_TOKEN_EXPIRED
    assert classify_upstox_error(UpstoxError(403, "x"), "margin").code == BROKER_TOKEN_EXPIRED
    assert classify_upstox_error(UpstoxError(423, "x"), "funds").code == BROKER_MAINTENANCE
    assert classify_upstox_error(UpstoxError(429, "x"), "funds").code == BROKER_RATE_LIMITED
    assert classify_upstox_error(UpstoxError(502, "x"), "funds").code == BROKER_FUNDS_UNAVAILABLE
    assert classify_upstox_error(UpstoxError(502, "x"), "margin").code == BROKER_MARGIN_UNAVAILABLE


# =============================================================================
# Account funds (§31-1..10)
# =============================================================================


async def test_funds_success_maps_available_funds():
    provider, *_ = build_provider()
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_available_funds"] == 40034.0
    assert snapshot["source"] == SOURCE_BROKER_REPORTED
    # No open strategies → no strategy margin computed → broker overall partial
    # (funds available, margin N/A). Never a fabricated margin number.
    assert snapshot["status"] == STATUS_PARTIAL
    assert snapshot["broker_funds_timestamp"] is not None
    assert snapshot["broker_funds_detail"]["cash_available_to_trade"] == 39900.0
    assert snapshot["errors"]["funds"] is None


async def test_funds_margin_used_and_cash_mapping():
    provider, *_ = build_provider()
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_margin_used"] == 134.0  # keep broker term: margin USED
    assert snapshot["broker_cash_available"] == 39900.0
    assert snapshot["broker_pledge_available"] == 134.0


async def test_funds_span_exposure_mapping():
    provider, *_ = build_provider()
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_funds_detail"]["span_exposure"] == 100.0  # SPAN + exposure combined (V3)


async def test_funds_timestamp_captured():
    provider, *_ = build_provider()
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_funds_detail"]["generated_at"] == NOW.isoformat()
    assert snapshot["broker_funds_detail"]["expires_at"] is not None


async def test_funds_missing_field_is_null_not_zero():
    funds = {"status": "success", "data": {"available_to_trade": {"total": 40034.0}}}
    provider, *_ = build_provider(funds_result=funds)
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_available_funds"] == 40034.0
    assert snapshot["broker_margin_used"] is None  # missing stays null, never 0
    assert snapshot["broker_cash_available"] is None
    assert snapshot["status"] == STATUS_PARTIAL  # funds OK, no strategy margin (no strategies)


async def test_funds_api_error_unavailable():
    provider, *_ = build_provider(funds_error=UpstoxError(502, "boom"))
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_available_funds"] is None
    assert snapshot["broker_funds_timestamp"] is None
    assert snapshot["errors"]["funds"] == BROKER_FUNDS_UNAVAILABLE


async def test_funds_maintenance_423():
    provider, *_ = build_provider(funds_error=UpstoxError(423, "maintenance"))
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_available_funds"] is None
    assert snapshot["errors"]["funds"] == BROKER_MAINTENANCE
    assert "maintenance window" in (snapshot["broker_funds_detail"].get("message") or "")


async def test_funds_token_expired():
    provider, *_ = build_provider(funds_error=UpstoxError(401, "unauthorized"))
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["errors"]["funds"] == BROKER_TOKEN_EXPIRED
    assert snapshot["broker_available_funds"] is None


async def test_funds_rate_limited():
    provider, *_ = build_provider(funds_error=UpstoxError(429, "rate limited"))
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["errors"]["funds"] == BROKER_RATE_LIMITED


# =============================================================================
# Strategy margin (§31-11..20)
# =============================================================================


async def test_single_leg_margin():
    provider, _, margin_fetcher, resolver = build_provider(resolver_result=two_keys()[:1])
    snapshot = await provider.get_capital_snapshot(
        context(strategies=[strategy(orders=[order(strike=24350.0, action="buy")])])
    )
    assert snapshot["broker_margin"] == 37503.0
    assert snapshot["broker_margin_status"] == STATUS_AVAILABLE
    row = snapshot["broker_margin_detail"]["per_strategy"][0]
    assert row["required_margin"] == 37503.0
    assert row["final_margin"] == 37000.0
    assert row["instrument_count"] == 1
    assert row["status"] == STATUS_AVAILABLE
    assert margin_fetcher.await_count == 1
    assert resolver.await_count == 1


async def test_bull_call_spread_sent_as_one_request():
    provider, _, margin_fetcher, resolver = build_provider(resolver_result=two_keys())
    await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    assert margin_fetcher.await_count == 1  # ONE whole-strategy request
    payload = margin_fetcher.await_args.args[1]
    assert len(payload) == 2
    assert {p["instrument_key"] for p in payload} == {"NSE_FO|NIFTY 24350 CE 270826",
                                                      "NSE_FO|NIFTY 24550 CE 270826"}
    by_key = {p["instrument_key"]: p for p in payload}
    assert by_key["NSE_FO|NIFTY 24350 CE 270826"]["transaction_type"] == "BUY"
    assert by_key["NSE_FO|NIFTY 24550 CE 270826"]["transaction_type"] == "SELL"
    assert all(p["quantity"] == 65 for p in payload)  # 1 lot × 65
    assert all(p["product"] == "D" for p in payload)


async def test_multi_leg_strategy_one_request():
    orders = [
        order(strike=24000.0, action="buy"),
        order(strike=24350.0, action="sell"),
        order(strike=24550.0, action="buy"),
        order(strike=25000.0, action="sell"),
    ]
    keys = [
        {**o, "instrument_key": f"NSE_FO|KEY{i}"}
        for i, o in enumerate(orders)
    ]
    provider, _, margin_fetcher, _ = build_provider(resolver_result=keys)
    await provider.get_capital_snapshot(context(strategies=[strategy(orders=orders)]))
    assert margin_fetcher.await_count == 1
    assert len(margin_fetcher.await_args.args[1]) == 4


async def test_instrument_key_resolution_inputs():
    provider, _, _, resolver = build_provider(resolver_result=two_keys())
    await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    args = resolver.await_args
    assert args.args[0] == "tok-phase61"
    strikes = {i["strike"]: i for i in args.args[1]}
    assert strikes[24350.0]["option_type"] == "call"
    assert strikes[24550.0]["option_type"] == "call"
    assert strikes[24350.0]["action"] == "buy"


async def test_quantity_conversion_two_lots():
    orders = [order(strike=24350.0, action="buy", quantity=2)]
    keys = [{**orders[0], "instrument_key": "NSE_FO|K"}]
    provider, _, margin_fetcher, _ = build_provider(resolver_result=keys)
    await provider.get_capital_snapshot(context(strategies=[strategy(orders=orders)]))
    payload = margin_fetcher.await_args.args[1]
    assert payload[0]["quantity"] == 130  # 2 lots × 65 contracts


async def test_missing_instrument_key_no_request():
    keys = [{**two_keys()[0], "instrument_key": None}]
    provider, _, margin_fetcher, _ = build_provider(resolver_result=keys)
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    row = snapshot["broker_margin_detail"]["per_strategy"][0]
    assert row["status"] == STATUS_UNAVAILABLE
    assert row["error"] == MISSING_INSTRUMENT_KEY
    assert row["required_margin"] is None
    assert snapshot["broker_margin"] is None
    assert margin_fetcher.await_count == 0  # never submit an invalid request


async def test_more_than_20_instruments():
    orders = [order(strike=20000.0 + i * 50.0, action="buy" if i % 2 == 0 else "sell") for i in range(21)]
    provider, _, margin_fetcher, resolver = build_provider(resolver_result=None)
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=orders)]))
    row = snapshot["broker_margin_detail"]["per_strategy"][0]
    assert row["status"] == STATUS_UNAVAILABLE
    assert row["error"] == MARGIN_REQUEST_TOO_LARGE
    assert margin_fetcher.await_count == 0
    assert resolver.await_count == 0  # no point resolving keys for an oversized request


async def test_margin_response_mapping_preserves_rows():
    provider, _, _, _ = build_provider(resolver_result=two_keys()[:1])
    snapshot = await provider.get_capital_snapshot(
        context(strategies=[strategy(orders=[order(strike=24350.0, action="buy")])])
    )
    row = snapshot["broker_margin_detail"]["per_strategy"][0]
    assert row["rows"][0]["span_margin"] == 30000.0
    assert row["rows"][0]["exposure_margin"] == 7503.0
    # broker-reported total is authoritative — never re-derived by the platform
    assert row["required_margin"] == 37503.0


# =============================================================================
# Source / status (§31-21..25)
# =============================================================================


async def test_broker_reported_available_status():
    provider, *_ = build_provider(resolver_result=two_keys())
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    assert snapshot["source"] == SOURCE_BROKER_REPORTED
    assert snapshot["status"] == STATUS_AVAILABLE
    assert snapshot["broker_margin"] == 37503.0
    assert snapshot["broker_available_funds"] == 40034.0


async def test_broker_reported_unavailable_status():
    provider, *_ = build_provider(
        funds_error=UpstoxError(502, "f"), margin_error=UpstoxError(502, "m"), resolver_result=two_keys()
    )
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    assert snapshot["status"] == STATUS_UNAVAILABLE
    assert snapshot["broker_margin"] is None
    assert snapshot["broker_available_funds"] is None
    assert snapshot["errors"]["margin"] == [BROKER_MARGIN_UNAVAILABLE]


async def test_partial_when_one_source_available():
    provider, *_ = build_provider(funds_error=UpstoxError(502, "f"), resolver_result=two_keys())
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    assert snapshot["status"] == STATUS_PARTIAL
    assert snapshot["broker_margin"] == 37503.0  # margin OK
    assert snapshot["broker_available_funds"] is None  # funds down


async def test_no_fallback_to_estimated_or_paper_cash():
    # The provider knows NOTHING about estimated capital or paper cash — it
    # cannot fall back to them. Router-level tests assert the same contract.
    provider, *_ = build_provider(
        funds_error=UpstoxError(502, "f"), margin_error=UpstoxError(502, "m"), resolver_result=two_keys()
    )
    snapshot = await provider.get_capital_snapshot(context(strategies=[strategy(orders=two_leg_orders())]))
    assert snapshot["broker_margin"] is None
    assert snapshot["broker_available_funds"] is None
    assert "broker_margin" in snapshot and "broker_available_funds" in snapshot
    assert not any(k.startswith("paper") for k in snapshot)


async def test_null_vs_zero_broker_figures():
    funds = {"status": "success", "data": {"available_to_trade": {"total": 0.0}}}  # real zero
    provider, *_ = build_provider(funds_result=funds)
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["broker_available_funds"] == 0.0  # genuine 0 is a valid figure
    assert snapshot["broker_margin_used"] is None  # missing → null, never 0


# =============================================================================
# Caching (§31-26..29)
# =============================================================================


async def test_same_strategy_fingerprint_reuses_cache():
    cache = BrokerMarginCache(now=lambda: NOW)
    provider, _, margin_fetcher, _ = build_provider(resolver_result=two_keys(), cache=cache)
    ctx = context(strategies=[strategy(orders=two_leg_orders())])
    await provider.get_capital_snapshot(ctx)
    await provider.get_capital_snapshot(ctx)
    assert margin_fetcher.await_count == 1  # second call served from cache


async def test_different_strategy_does_not_reuse_cache():
    cache = BrokerMarginCache(now=lambda: NOW)
    provider, _, margin_fetcher, _ = build_provider(resolver_result=two_keys(), cache=cache)
    ctx_a = context(strategies=[strategy("exec-1", orders=two_leg_orders())])
    ctx_b = context(strategies=[strategy("exec-2", orders=[
        order(strike=25000.0, action="buy"), order(strike=24550.0, action="sell"),
    ])])
    await provider.get_capital_snapshot(ctx_a)
    await provider.get_capital_snapshot(ctx_b)
    assert margin_fetcher.await_count == 2  # changed strike → different fingerprint


async def test_expired_cache_refreshes():
    class Clock:
        def __init__(self):
            self.t = NOW

        def __call__(self):
            return self.t

    clock = Clock()
    cache = BrokerMarginCache(now=clock)
    provider, _, margin_fetcher, _ = build_provider(resolver_result=two_keys(), cache=cache, now=clock)
    ctx = context(strategies=[strategy(orders=two_leg_orders())])
    await provider.get_capital_snapshot(ctx)
    clock.t = NOW + timedelta(seconds=301)  # beyond MARGIN_TTL_SECONDS
    await provider.get_capital_snapshot(ctx)
    assert margin_fetcher.await_count == 2  # expired → refreshed


async def test_user_cache_isolation():
    cache = BrokerMarginCache(now=lambda: NOW)
    provider, _, margin_fetcher, _ = build_provider(resolver_result=two_keys(), cache=cache)
    ctx_a = context("user-a", strategies=[strategy(orders=two_leg_orders())])
    ctx_b = context("user-b", strategies=[strategy(orders=two_leg_orders())])
    await provider.get_capital_snapshot(ctx_a)
    await provider.get_capital_snapshot(ctx_b)
    assert margin_fetcher.await_count == 2  # identical strategy, different users → no sharing


async def test_cache_keys_include_user_and_fingerprint():
    cache = BrokerMarginCache(now=lambda: NOW)
    provider, _, _, _ = build_provider(resolver_result=two_keys(), cache=cache)
    await provider.get_capital_snapshot(context("user-a", strategies=[strategy(orders=two_leg_orders())]))
    await provider.get_capital_snapshot(context("user-b", strategies=[strategy(orders=two_leg_orders())]))
    keys = list(cache._store.keys())
    assert any(k.startswith("funds:user-a") for k in keys)
    assert any(k.startswith("funds:user-b") for k in keys)
    margin_keys = [k for k in keys if k.startswith("margin:")]
    assert len(margin_keys) == 2
    assert any(k.startswith("margin:user-a:") for k in margin_keys)
    assert any(k.startswith("margin:user-b:") for k in margin_keys)


async def test_bad_broker_response_structured():
    provider, *_ = build_provider(funds_result=[1, 2, 3])  # not a dict
    snapshot = await provider.get_capital_snapshot(context())
    assert snapshot["errors"]["funds"] == BROKER_BAD_RESPONSE
    assert snapshot["broker_available_funds"] is None


async def test_default_resolver_uses_chain_instrument_keys():
    raw = {
        "data": [
            {
                "strike_price": 24350.0,
                "underlying_spot_price": 24000.0,
                "call_options": {"instrument_key": "NSE_FO|NIFTY 24350 CE 270826", "market_data": {}, "option_greeks": {}},
                "put_options": {"instrument_key": "NSE_FO|NIFTY 24350 PE 270826", "market_data": {}, "option_greeks": {}},
            }
        ]
    }
    with patch("app.services.upstox.get_option_chain", new=AsyncMock(return_value=raw)):
        resolved = await default_instrument_key_resolver("tok", [order(strike=24350.0, option_type="call")])
    assert resolved[0]["instrument_key"] == "NSE_FO|NIFTY 24350 CE 270826"


# =============================================================================
# Router integration (GET /paper/capital with the real provider wired in)
# =============================================================================

DEFAULT_CHAIN = {
    EXPIRY: {
        24350: {"call": 125.25, "put": 90.0},
        24550: {"call": 35.60, "put": 200.0},
        25000: {"call": 200.0, "put": 80.0},
    },
}


def chain_payload_with_keys(expiry, quotes):
    data = []
    for strike, sides in quotes.items():
        item = {"strike_price": strike, "underlying_spot_price": 24000.0}
        for side_key, label in (("call_options", "CE"), ("put_options", "PE")):
            item[side_key] = {
                "instrument_key": f"NSE_FO|NIFTY {strike:g} {label} {expiry.replace('-', '')[-4:]}",
                "market_data": {"ltp": sides[side_key.startswith("call") and "call" or "put"]},
                "option_greeks": {},
            }
        data.append(item)
    return {"data": data}


@pytest.fixture(autouse=True)
def market_open_gate():
    from types import SimpleNamespace

    status = SimpleNamespace(
        status="open", source="test", trade_date="2026-08-14",
        checked_at="2026-08-14T10:00:00+05:30", message="open", error=None,
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=status)):
        yield


@pytest.fixture(autouse=True)
def chain_mock_with_keys():
    async def fake(token, instrument_key, expiry):
        return chain_payload_with_keys(expiry, DEFAULT_CHAIN.get(expiry, {}))

    with patch("app.services.upstox.get_option_chain", new=AsyncMock(side_effect=fake)):
        yield


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client, db_session):
    session_id, _ = create_test_identity(db_session, "tok-broker61")
    return session_id


def headers(session_id):
    return {"X-Session-Id": session_id}


_counter = {"n": 0}


def next_id(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:06d}"


def leg(expiry, strike, option_type, action):
    return {
        "symbol": "NIFTY", "expiration_date": expiry, "strike_price": strike,
        "option_type": option_type, "action": action, "quantity": 1, "lot_size": LOT,
    }


def bull_call_spread_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Bull Call Spread",
        "starting_capital": 500000,
        "legs": [leg(EXPIRY, 24350, "call", "buy"), leg(EXPIRY, 24550, "call", "sell")],
    }
    payload.update(overrides)
    return payload


def execute(client, session_id, payload):
    return client.post("/paper/executions", headers=headers(session_id), json=payload)


def get_capital(client, session_id):
    return client.get("/paper/capital", headers=headers(session_id))


@pytest.fixture
def broker_ok():
    with (
        patch("app.services.upstox.get_funds_and_margin", new=AsyncMock(return_value=FUNDS_OK)),
        patch("app.services.upstox.get_margin_details", new=AsyncMock(return_value=MARGIN_OK)),
    ):
        yield


@pytest.fixture
def broker_down():
    async def _raise(*args, **kwargs):
        raise UpstoxError(502, "mock down")

    with (
        patch("app.services.upstox.get_funds_and_margin", new=AsyncMock(side_effect=_raise)),
        patch("app.services.upstox.get_margin_details", new=AsyncMock(side_effect=_raise)),
    ):
        yield


def test_router_broker_margin_and_funds_available(client, logged_in, broker_ok):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    # Strategy margin (aggregate whole-strategy, broker-reported)
    assert body["broker_margin"]["value"] == 37503.0
    assert body["broker_margin"]["source"] == SOURCE_BROKER_REPORTED
    assert body["broker_margin"]["status"] == STATUS_AVAILABLE
    assert body["broker_margin"]["timestamp"]
    # Account funds
    assert body["broker_available_funds"]["value"] == 40034.0
    assert body["broker_available_funds"]["source"] == SOURCE_BROKER_REPORTED
    assert body["broker_margin_used"]["value"] == 134.0
    assert body["broker_cash_available"]["value"] == 39900.0
    assert body["broker_pledge_available"]["value"] == 134.0
    # Paper capital stays separate and unchanged
    assert body["paper_available_cash"]["value"] == pytest.approx(500000 - 125.25 * LOT + 35.60 * LOT, abs=0.01)
    assert body["paper_available_cash"]["source"] == "CALCULATED"
    # Per-strategy broker margin
    row = body["strategies"][0]
    assert row["broker_margin"] == 37503.0
    assert row["broker_margin_status"] == STATUS_AVAILABLE
    assert row["broker_margin_error"] is None
    # Raw broker detail preserved with capture timestamps
    assert body["broker_margin_detail"]["aggregate_required_margin"] == 37503.0
    assert body["broker_funds_detail"]["span_exposure"] == 100.0
    assert body["broker_generated_at"]
    assert body["expires_at"]


def test_router_broker_unavailable_never_falls_back(client, logged_in, broker_down):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200
    body = get_capital(client, logged_in).json()

    # Broker figures are null + UNAVAILABLE — never ESTIMATED, never paper cash.
    assert body["broker_margin"]["value"] is None
    assert body["broker_margin"]["status"] == STATUS_UNAVAILABLE
    assert body["broker_available_funds"]["value"] is None
    assert body["broker_margin_used"]["value"] is None
    assert body["broker_errors"]["funds"] == BROKER_FUNDS_UNAVAILABLE
    assert BROKER_MARGIN_UNAVAILABLE in body["broker_errors"]["margin"]
    # Estimated capital remains ESTIMATED (Phase 6.0 behavior unchanged)
    assert body["estimated_capital"]["value"] == pytest.approx(89.65 * LOT, abs=0.01)
    assert body["estimated_capital"]["source"] == "ESTIMATED"
    # Paper cash remains paper cash
    assert body["paper_available_cash"]["value"] == pytest.approx(
        500000 - 125.25 * LOT + 35.60 * LOT, abs=0.01
    )
    row = body["strategies"][0]
    assert row["broker_margin"] is None
    assert row["broker_margin_status"] == STATUS_UNAVAILABLE
    assert row["broker_margin_error"] == BROKER_MARGIN_UNAVAILABLE
    # Overall status: estimated available + broker unavailable → partial
    assert body["status"] == STATUS_PARTIAL


def test_router_funds_maintenance_window(client, logged_in):
    assert execute(client, logged_in, bull_call_spread_payload()).status_code == 200

    async def maintenance(*args, **kwargs):
        raise UpstoxError(423, "Funds service maintenance")

    with (
        patch("app.services.upstox.get_funds_and_margin", new=AsyncMock(side_effect=maintenance)),
        patch("app.services.upstox.get_margin_details", new=AsyncMock(return_value=MARGIN_OK)),
    ):
        body = get_capital(client, logged_in).json()

    assert body["broker_available_funds"]["value"] is None
    assert body["broker_available_funds"]["status"] == STATUS_UNAVAILABLE
    assert body["broker_errors"]["funds"] == BROKER_MAINTENANCE
    assert "maintenance window" in body["broker_funds_detail"]["message"]
    # The margin side still works — maintenance is funds-only, not an app crash
    assert body["broker_margin"]["value"] == 37503.0
    # Overall summary status follows the Phase 6.0 rule (broker margin +
    # estimated capital): broker margin IS available here, so overall is
    # available — the funds outage is visible via broker_available_funds.
    assert body["status"] == STATUS_AVAILABLE


def test_router_broker_auth_required(client):
    # No session → 401 before any broker work
    assert get_capital(client, "nope").status_code == 401
