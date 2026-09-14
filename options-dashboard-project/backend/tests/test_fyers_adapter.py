"""FYERS adapter tests — auth, identity, account, market data, capabilities,
errors and security (Phase 3/4/5/6/7/9/10 contract).

Identity rule under test (critical):

    broker_user_id = broker_account_id = FYERS customer **Login ID**
    NEVER the API App ID / OAuth client_id / secret / email / PAN.

The exact profile field is UNCONFIRMED until the first live staging
profile response; fixtures here use the audit-expected candidate shape
(``data.fy_id``) and the fail-closed contract is asserted explicitly.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.brokers.adapters.fyers.adapter import FyersAdapter
from app.brokers.adapters.fyers import mapper
from app.brokers.adapters.fyers.profile import (
    IDENTITY_FIELD_CANDIDATES,
    diagnose_profile_identity,
    extract_account_id,
    extract_customer_identity,
    mask_identity,
)
from app.brokers.domain.capabilities import CapabilityState
from app.brokers.domain.enums import OptionType, OrderType, Side
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import InstrumentIdentity
from app.services.fyers import FyersError, build_app_id_hash

APP_ID = "SPABC123XY-200"      # API App ID — never an ownership identity
LOGIN_ID = "XT00001"           # customer Login ID — the ownership identity
SECRET = "super-secret-secret"


def make_fetcher(body):
    async def fetcher(*args, **kwargs):
        return body
    return fetcher


def fyers_error(status, message):
    return FyersError(status, message)


def identity(**kwargs) -> InstrumentIdentity:
    base = dict(
        exchange="NSE",
        segment="INDEX_DERIVATIVES",
        underlying="NIFTY",
        symbol="NIFTY",
        instrument_type="INDEX",
    )
    base.update(kwargs)
    return InstrumentIdentity(**base)


def profile_payload(login_id: str = LOGIN_ID) -> dict:
    """Official/expected FYERS profile payload shape (fixture).

    The inner ``data`` object shape follows the v3 profile contract; the
    Login-ID field is the to-be-confirmed candidate. Extra fields
    (email, PAN-style identity) exist to prove they are never selected.
    """
    return {
        "s": "ok",
        "data": {
            IDENTITY_FIELD_CANDIDATES[0]: login_id,
            "name": "Test Human",
            "email_id": f"{login_id.lower()}@example.com",
            "mobile_number": "9000000000",
            "pan": "ABCPX1234F",
            "appattribution": "200",
        },
    }


# ---------------------------------------------------------------------------
# Test B — appIdHash is exactly sha256("<app_id>:<secret_id>")
# ---------------------------------------------------------------------------


def test_app_id_hash_exact_formula():
    expected = hashlib.sha256(f"{APP_ID}:{SECRET}".encode()).hexdigest()
    assert build_app_id_hash(APP_ID, SECRET) == expected


def test_app_id_hash_is_not_login_id_derived():
    # The hash inputs are the App ID + secret — never the Login ID.
    assert build_app_id_hash(LOGIN_ID, SECRET) != build_app_id_hash(APP_ID, SECRET)


# ---------------------------------------------------------------------------
# Test A — authorization URL (client_id = App ID; no secret leak)
# ---------------------------------------------------------------------------


def test_authorization_url_contains_app_id_and_state():
    adapter = FyersAdapter(api_key=APP_ID, redirect_uri="https://app.example/cb")
    url = adapter.get_authorization_url("state-xyz")
    assert url.startswith("https://api-t1.fyers.in/api/v3/generate-authcode")
    assert f"client_id={APP_ID}" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example%2Fcb" in url
    assert "response_type=code" in url
    assert "state=state-xyz" in url


def test_authorization_url_never_leaks_the_secret():
    adapter = FyersAdapter(api_key=APP_ID, api_secret=SECRET, redirect_uri="https://app.example/cb")
    url = adapter.get_authorization_url("state-xyz")
    assert SECRET not in url


# ---------------------------------------------------------------------------
# Test C — authorization-code exchange (validate-authcode)
# ---------------------------------------------------------------------------


async def test_exchange_authorization_code_posts_validate_authcode():
    captured = {}

    async def exchanger(code: str) -> dict:
        captured["code"] = code
        return {
            "s": "ok",
            "access_token": "fy-access-token-value",
            "refresh_token": "fy-refresh-token-value",
        }

    adapter = FyersAdapter(api_key=APP_ID, api_secret=SECRET, token_exchanger=exchanger)
    token = await adapter.exchange_authorization_code("single-use-code")

    assert token == "fy-access-token-value"
    assert captured["code"] == "single-use-code"
    # The payload builder (what the raw client sends) is the contract:
    body = __import__(
        "app.services.fyers", fromlist=["validate_authcode_payload"]
    ).validate_authcode_payload(APP_ID, SECRET, "single-use-code")
    assert body == {
        "grant_type": "authorization_code",
        "appIdHash": build_app_id_hash(APP_ID, SECRET),
        "code": "single-use-code",
    }


async def test_exchange_preserves_refresh_token_without_logging_it(caplog):
    async def exchanger(code: str) -> dict:
        return {"s": "ok", "access_token": "at", "refresh_token": "rt-value"}

    adapter = FyersAdapter(api_key=APP_ID, api_secret=SECRET, token_exchanger=exchanger)
    await adapter.exchange_authorization_code("code")
    # The refresh token must not be silently discarded.
    assert getattr(adapter, "_refresh_token", None) == "rt-value"
    # ...and never logged.
    assert "rt-value" not in caplog.text


async def test_exchange_bad_code_maps_to_canonical_error():
    async def exchanger(code: str) -> dict:
        raise fyers_error(401, "Invalid appIdHash or code")

    adapter = FyersAdapter(api_key=APP_ID, api_secret=SECRET, token_exchanger=exchanger)
    with pytest.raises(BrokerError) as exc:
        await adapter.exchange_authorization_code("bad-code")
    assert exc.value.code is BrokerErrorCode.TOKEN_EXPIRED


def test_exchange_without_app_credentials_fails_closed():
    adapter = FyersAdapter()  # no app id/secret
    with pytest.raises(BrokerError) as exc:
        __import__("asyncio").run(adapter.exchange_authorization_code("code"))
    assert exc.value.code is BrokerErrorCode.AUTH_REQUIRED


# ---------------------------------------------------------------------------
# Test E — profile request (GET /api/v3/profile, app_id:token header)
# ---------------------------------------------------------------------------


async def test_profile_request_uses_app_id_token_header():
    captured = {}

    async def fetcher(access_token: str, app_id: str) -> dict:
        captured["access_token"] = access_token
        captured["app_id"] = app_id
        return profile_payload()

    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, profile_fetcher=fetcher)
    body = await adapter.get_profile()

    assert captured["access_token"] == "tok"
    assert captured["app_id"] == APP_ID  # header is <app_id>:<token>
    assert body["s"] == "ok"


async def test_profile_payload_error_maps_canonical():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, profile_fetcher=make_fetcher({"s": "error", "code": 401, "message": "Invalid token"}))
    with pytest.raises(BrokerError) as exc:
        await adapter.get_profile()
    assert exc.value.code is BrokerErrorCode.TOKEN_EXPIRED


# ---------------------------------------------------------------------------
# Test F — customer identity extraction (fail-closed, never App ID)
# ---------------------------------------------------------------------------


def test_extract_login_id_from_profile_fixture():
    identity_value = extract_account_id(profile_payload())
    assert identity_value == LOGIN_ID


def test_extract_customer_identity_fail_closed_on_missing():
    with pytest.raises(ValueError):
        extract_customer_identity({"s": "ok", "data": {"name": "No Identity Here"}})


def test_extract_customer_identity_fail_closed_on_empty():
    with pytest.raises(ValueError):
        extract_customer_identity({"s": "ok", "data": {IDENTITY_FIELD_CANDIDATES[0]: "   "}})


def test_extract_never_returns_email_pan_or_app_id():
    data = {
        "email_id": "someone@example.com",
        "email": "someone@example.com",
        "pan": "ABCPX1234F",
        "app_id": APP_ID,
        "client_id": APP_ID,
    }
    assert extract_account_id({"s": "ok", "data": data}) is None


def test_adapter_extract_matches_module():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID)
    assert adapter.extract_account_id(profile_payload()) == LOGIN_ID
    assert adapter.extract_customer_identity(profile_payload()) == LOGIN_ID


def test_identity_candidates_never_include_credential_fields():
    lowered = {c.lower() for c in IDENTITY_FIELD_CANDIDATES}
    for forbidden in ("app_id", "client_id", "secret_id", "appidhash", "redirect_uri", "email", "pan", "pin"):
        assert forbidden not in lowered


# ---------------------------------------------------------------------------
# Test G — account identity: Login ID for broker_user_id/broker_account_id
# ---------------------------------------------------------------------------


def test_broker_account_id_is_login_id_not_app_id():
    profile = profile_payload()
    # The App ID is NOT the extracted identity even though both are present.
    broker_account_id = extract_account_id(profile)
    assert broker_account_id == LOGIN_ID
    assert broker_account_id != APP_ID
    # broker_user_id mirrors broker_account_id (intended mapping).
    broker_user_id = broker_account_id
    assert broker_user_id == LOGIN_ID


# ---------------------------------------------------------------------------
# Phase 18 — safe diagnostic
# ---------------------------------------------------------------------------


def test_diagnostic_reports_keys_and_masked_identity_only():
    report = diagnose_profile_identity(profile_payload())
    assert report["ok"] is True
    assert report["selected_field"] == IDENTITY_FIELD_CANDIDATES[0]
    assert report["identity_masked"] != LOGIN_ID
    assert LOGIN_ID not in str(report["identity_masked"])
    assert "email" in report["profile_keys"] or "email_id" in report["profile_keys"]
    # No secret-class values anywhere in the report.
    flattened = str(report)
    for secret in ("tok", APP_ID, SECRET, "ABCPX1234F", f"{LOGIN_ID.lower()}@example.com"):
        assert secret not in flattened


def test_mask_identity_masks_short_values():
    assert mask_identity("ab") == "**"
    assert mask_identity(None) == "<missing>"


# ---------------------------------------------------------------------------
# Phase 6 — funds / positions / holdings
# ---------------------------------------------------------------------------


async def test_get_funds_normalizes_fund_limit_rows():
    raw = {
        "s": "ok",
        "fund_limit": [
            {"id": "total_balance", "title": "Total Balance", "equityAmount": 100000.5},
            {"id": "utilized_amount", "title": "Utilized", "equityAmount": 25000.0},
        ],
    }
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, funds_fetcher=make_fetcher(raw))
    funds = await adapter.get_funds()
    assert funds["available_to_trade"] == 100000.5
    assert funds["margin_used"] == 25000.0
    assert "fund_limit" not in str(funds["rows"] is None)
    # No raw FYERS short-field names leak into the canonical mapping keys.
    assert set(funds) >= {"available_to_trade", "margin_used", "raw"}


async def test_get_positions_normalizes_rows():
    raw = {
        "s": "ok",
        "netPositions": [
            {"symbol": "NSE:NIFTY25OCT24500CE", "netQty": 65, "avgPrice": 120.5, "ltp": 132.0, "pl": 750.0, "productType": "M"},
            {"not_a_dict": True},
        ],
    }
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, positions_fetcher=make_fetcher(raw))
    positions = await adapter.get_positions()
    assert len(positions) == 1
    assert positions[0]["broker_id"] == "FYERS"
    assert positions[0]["quantity"] == 65  # broker contract units
    assert positions[0]["average_price"] == 120.5


async def test_get_holdings_normalizes_rows():
    raw = {
        "s": "ok",
        "holdings": [
            {"symbol": "EQ-SBINE", "quantity": 10, "costPrice": 2500.0, "ltp": 2700.0, "holdingType": "HOLD"},
        ],
    }
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, holdings_fetcher=make_fetcher(raw))
    holdings = await adapter.get_holdings()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == 10
    assert holdings[0]["average_price"] == 2500.0


# ---------------------------------------------------------------------------
# Phase 7 — quotes and option chain
# ---------------------------------------------------------------------------


async def test_get_quote_maps_fyers_short_fields():
    raw = {"s": "ok", "data": {"d": {mapper.FYERS_INSTRUMENTS["NIFTY"]["broker_instrument_id"]: {"lp": 25150.5, "v": 12345, "bid": 25149.0, "ask": 25151.0}}}}
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, quotes_fetcher=make_fetcher(raw))
    observation = await adapter.get_quote(identity())
    assert observation.quote.ltp == 25150.5
    assert observation.quote.bid == 25149.0
    assert observation.source == "FYERS"
    assert observation.data_mode.value == "BROKER_SNAPSHOT"


async def test_get_quotes_empty_response_is_canonical_error():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, quotes_fetcher=make_fetcher({"s": "ok", "data": {"d": {}}}))
    with pytest.raises(BrokerError) as exc:
        await adapter.get_quotes([identity()])
    assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA


async def test_get_quote_malformed_payload_is_canonical_error():
    raw = {"s": "ok", "data": {"d": {mapper.FYERS_INSTRUMENTS["NIFTY"]["broker_instrument_id"]: {"v": 1}}}}  # no lp
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, quotes_fetcher=make_fetcher(raw))
    with pytest.raises(BrokerError) as exc:
        await adapter.get_quote(identity())
    assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA


async def test_get_quote_provider_error_maps_canonical():
    async def fetcher(*args, **kwargs):
        raise fyers_error(429, "Too many requests")

    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, quotes_fetcher=fetcher)
    with pytest.raises(BrokerError) as exc:
        await adapter.get_quote(identity())
    assert exc.value.code is BrokerErrorCode.RATE_LIMITED


async def test_get_quote_concrete_contract_is_invalid_instrument():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID)
    option = identity(
        instrument_type="OPTION", expiry="2026-10-29", strike=24500.0, option_type=OptionType.CALL
    )
    with pytest.raises(BrokerError) as exc:
        await adapter.get_quote(option)
    assert exc.value.code is BrokerErrorCode.INVALID_INSTRUMENT


async def test_get_option_chain_normalizes_rows():
    raw = {
        "s": "ok",
        "data": {
            "callputltp": [
                {"strike_price": 24500.0, "callLtp": 160.0, "putLtp": 90.0, "callOICoynt": 1200, "putOICoynt": 900, "callVolume": 500, "putVolume": 300},
                {"strike_price": 24400.0, "callLtp": 220.0, "putLtp": 55.0},
                {"no_strike": True},
            ],
            "underlying": 25120.0,
        },
    }
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, chain_fetcher=make_fetcher(raw))
    chain = await adapter.get_option_chain("NIFTY", "2026-10-29")
    assert chain["symbol"] == "NIFTY"
    assert chain["underlying_spot_price"] == 25120.0
    strikes = [row["strike"] for row in chain["chain"]]
    assert strikes == [24400.0, 24500.0]  # sorted, malformed row skipped
    assert chain["chain"][1]["call"]["ltp"] == 160.0
    # No FYERS chain keys leak into the canonical chain.
    assert "callLtp" not in str(chain)


async def test_get_option_chain_empty_response_is_empty_chain():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, chain_fetcher=make_fetcher({"s": "ok", "data": {"callputltp": []}}))
    chain = await adapter.get_option_chain("NIFTY", "2026-10-29")
    assert chain["chain"] == []


# ---------------------------------------------------------------------------
# Phase 8 — instrument mapping
# ---------------------------------------------------------------------------


def test_resolve_instrument_and_fyers_symbol():
    adapter = FyersAdapter()
    identity_value = adapter.resolve_instrument("NIFTY")
    assert mapper.fyers_symbol_for(identity_value) == "NSE:NIFTY50-INDEX"


def test_option_symbol_grammar():
    option = identity(
        instrument_type="OPTION", expiry="2026-10-29", strike=24500.0, option_type=OptionType.CALL
    )
    assert mapper.fyers_symbol_for(option) == "NSE:NIFTY26OCT24500CE"
    put = identity(
        instrument_type="OPTION", expiry="2026-10-29", strike=24300.5, option_type=OptionType.PUT
    )
    assert mapper.fyers_symbol_for(put) == "NSE:NIFTY26OCT24300.5PE"


def test_unknown_symbol_is_invalid_instrument():
    adapter = FyersAdapter()
    with pytest.raises(BrokerError) as exc:
        adapter.resolve_instrument("NOPE")
    assert exc.value.code is BrokerErrorCode.INVALID_INSTRUMENT


def test_search_instruments_returns_mappings():
    adapter = FyersAdapter()
    results = adapter.search_instruments("bankn")
    assert len(results) == 1
    assert results[0].broker == "FYERS"
    assert results[0].broker_instrument_id == "NSE:NIFTYBANK-INDEX"


async def test_get_option_contracts_returns_expiries():
    raw = {"s": "ok", "data": {"callputltp": [{"expiry": "2026-10-29T14:20:00"}, {"expiry": "2026-11-26"}, {"expiry": "garbage"}]}}
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, chain_fetcher=make_fetcher(raw))
    result = await adapter.get_option_contracts("NIFTY")
    assert result["symbol"] == "NIFTY"
    assert result["expiries"] == ["2026-10-29", "2026-11-26"]


# ---------------------------------------------------------------------------
# Phase 9 — capability model
# ---------------------------------------------------------------------------


def test_capabilities_data_only_app_never_reports_orders_supported():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, app_type="-100")
    caps = adapter.get_capabilities()
    assert caps.state("orders") is CapabilityState.UNSUPPORTED
    assert caps.get("profile").state in (CapabilityState.SUPPORTED, CapabilityState.AVAILABLE)
    assert caps.state("option_chain") in (CapabilityState.SUPPORTED, CapabilityState.AVAILABLE)
    assert caps.state("websocket_market_data") in (CapabilityState.SUPPORTED, CapabilityState.AVAILABLE)


def test_capabilities_unknown_app_type_is_not_trading_capable():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID)
    caps = adapter.get_capabilities()
    assert caps.state("orders") is CapabilityState.UNSUPPORTED


def test_capabilities_compliant_app_reports_supported_with_gate_detail():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, app_type="-200")
    caps = adapter.get_capabilities()
    # Session-active view: the shared model promotes SUPPORTED → AVAILABLE
    # (same semantics as Upstox); UNSUPPORTED is never promoted.
    assert caps.state("orders") in (CapabilityState.SUPPORTED, CapabilityState.AVAILABLE)
    assert "static IP" in caps.get("orders").detail
    # ...but the session-unaware view still gates data capabilities.
    no_session = FyersAdapter(api_key=APP_ID, app_type="-200").get_capabilities()
    assert no_session.state("option_chain") is CapabilityState.AUTH_REQUIRED


def test_trading_available_requires_200_app():
    assert FyersAdapter(app_type="-200").trading_available() is True
    assert FyersAdapter(app_type="-100").trading_available() is False
    assert FyersAdapter(app_type="200").trading_available() is True
    assert FyersAdapter().trading_available() is False


def test_capability_names_cover_mission_set():
    adapter = FyersAdapter(app_type="-200")
    names = set(adapter.get_capabilities().names())
    for required in (
        "profile", "funds", "positions", "holdings", "quotes",
        "option_chain", "websocket_market_data", "trades", "orders",
        "websocket_order_events",
    ):
        assert required in names


# ---------------------------------------------------------------------------
# Phase 10 — error normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"s": "error", "code": 401, "message": "Invalid token"}, BrokerErrorCode.TOKEN_EXPIRED),
        ({"s": "error", "code": 400, "message": "Authentication failed"}, BrokerErrorCode.AUTH_REQUIRED),
        ({"s": "error", "code": 403, "message": "Access denied for this app"}, BrokerErrorCode.ACCOUNT_RESTRICTED),
        ({"s": "error", "code": 400, "message": "Static IP restriction violation"}, BrokerErrorCode.STATIC_IP_REQUIRED),
        ({"s": "error", "code": 400, "message": "This API is not supported for your app"}, BrokerErrorCode.CAPABILITY_UNSUPPORTED),
        ({"s": "error", "code": 400, "message": "Invalid symbol provided"}, BrokerErrorCode.INVALID_INSTRUMENT),
        ({"s": "error", "code": 400, "message": "Invalid qty"}, BrokerErrorCode.INVALID_QUANTITY),
        ({"s": "error", "code": 400, "message": "Invalid price"}, BrokerErrorCode.INVALID_PRICE),
        ({"s": "error", "code": 400, "message": "Insufficient margin"}, BrokerErrorCode.ORDER_REJECTED),
        ({"s": "error", "code": 400, "message": "Order not found"}, BrokerErrorCode.ORDER_NOT_FOUND),
        ({"s": "error", "code": 400, "message": "Order is already final"}, BrokerErrorCode.ORDER_ALREADY_FINAL),
        ({"s": "error", "code": -99, "message": "Mysterious upstream"}, BrokerErrorCode.UPSTREAM_ERROR),
    ],
)
def test_payload_error_map(payload, expected):
    error = FyersAdapter._error_from_payload(payload, "test")
    assert error.code is expected


def test_http_error_map():
    assert FyersAdapter._map_error(fyers_error(401, "Unauthorized")).code is BrokerErrorCode.TOKEN_EXPIRED
    assert FyersAdapter._map_error(fyers_error(403, "Forbidden")).code is BrokerErrorCode.TOKEN_EXPIRED
    assert FyersAdapter._map_error(fyers_error(429, "Rate limit")).code is BrokerErrorCode.RATE_LIMITED
    assert FyersAdapter._map_error(fyers_error(502, "Could not reach FYERS: x")).code is BrokerErrorCode.NETWORK_ERROR
    assert FyersAdapter._map_error(fyers_error(500, "boom")).code is BrokerErrorCode.UPSTREAM_ERROR


def test_order_status_map():
    from app.brokers.domain.enums import OrderStatus

    assert mapper.fyers_status_to_domain("6") is OrderStatus.FILLED
    assert mapper.fyers_status_to_domain("7") is OrderStatus.REJECTED
    assert mapper.fyers_status_to_domain("1") is OrderStatus.CANCELLED
    assert mapper.fyers_status_to_domain("2") is OrderStatus.PENDING
    assert mapper.fyers_status_to_domain("part_filled") is OrderStatus.PARTIALLY_FILLED
    assert mapper.fyers_status_to_domain(None) is OrderStatus.UNKNOWN
    assert mapper.fyers_status_to_domain("bizarre") is OrderStatus.UNKNOWN


def test_order_result_rows_mapping():
    from app.brokers.domain.enums import OrderStatus

    body = {"orderBook": [{"id": "ord-1", "status": "6"}, {"id": "ord-2", "status": "7"}]}
    results = mapper.map_order_result_rows(body)
    assert [r.broker_order_ids for r in results] == [("ord-1",), ("ord-2",)]
    assert results[0].status is OrderStatus.FILLED
    assert results[1].status is OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# Phase 11 — orders: mandatory capability gate
# ---------------------------------------------------------------------------


def _order_request():
    return __import__("app.brokers.domain.models", fromlist=["BrokerOrderRequest"]).BrokerOrderRequest(
        instrument=identity(lot_size=75),
        side=Side.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )


def test_order_gate_data_only_app_raises_before_any_http():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, app_type="-100")
    request = _order_request()
    for call in (
        lambda: adapter.place_order(request),
        lambda: adapter.place_orders([request]),
        lambda: adapter.modify_order("o1", request),
        lambda: adapter.cancel_order("o1"),
    ):
        with pytest.raises(BrokerError) as exc:
            call()
        assert exc.value.code is BrokerErrorCode.CAPABILITY_UNSUPPORTED


def test_order_gate_compliant_app_reaches_not_wired():
    """A compliant -200 app passes the gate and then hits the prepared-
    not-wired boundary (same posture as Upstox orders this phase)."""
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, app_type="-200")
    request = _order_request()
    with pytest.raises(BrokerError) as exc:
        adapter.place_order(request)
    assert exc.value.code is BrokerErrorCode.CAPABILITY_UNSUPPORTED
    assert "NOT wired" in exc.value.message


def test_order_gate_unknown_app_requires_static_ip_error():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID)
    request = _order_request()
    with pytest.raises(BrokerError) as exc:
        adapter.place_order(request)
    assert exc.value.code is BrokerErrorCode.STATIC_IP_REQUIRED


def test_build_order_payload_maps_fyers_fields():
    adapter = FyersAdapter(app_type="-200")
    from app.brokers.domain.enums import OrderType as OT

    request = __import__("app.brokers.domain.models", fromlist=["BrokerOrderRequest"]).BrokerOrderRequest(
        instrument=identity(lot_size=75),
        side=Side.BUY,
        quantity=1,
        order_type=OT.LIMIT,
        price=160.5,
    )
    payload = adapter.build_order_request_payload(request)
    assert payload["symbol"] == "NSE:NIFTY50-INDEX"  # index identity — not an order though
    assert payload["qty"] == 75
    assert payload["side"] == 1
    assert payload["limitPrice"] == 160.5


def test_build_order_payload_requires_lot_size():
    adapter = FyersAdapter(app_type="-200")
    request = __import__("app.brokers.domain.models", fromlist=["BrokerOrderRequest"]).BrokerOrderRequest(
        instrument=identity(),  # no lot size
        side=Side.BUY,
        quantity=1,
    )
    with pytest.raises(BrokerError) as exc:
        adapter.build_order_request_payload(request)
    assert exc.value.code is BrokerErrorCode.INVALID_QUANTITY


# ---------------------------------------------------------------------------
# Phase 13 — streaming bridge (transport boundary, no FYERS codes out)
# ---------------------------------------------------------------------------


class FakeTransport:
    def __init__(self):
        self.state = "connected"
        self.subscribed: list[str] = []
        self.tick_handler = None
        self.closed = False

    async def connect(self):
        self.state = "connected"

    async def subscribe(self, symbols):
        self.subscribed = list(symbols)

    async def unsubscribe(self, symbols):
        self.subscribed = [s for s in self.subscribed if s not in set(symbols)]

    async def close(self):
        self.closed = True
        self.state = "disconnected"

    def on_tick(self, handler):
        self.tick_handler = handler

    def classify_error(self, exc):
        return BrokerErrorCode.UPSTREAM_ERROR


def test_streaming_bridge_emits_canonical_observations_only():
    from app.brokers.adapters.fyers.streaming_source import FyersStreamingSource
    from app.market_data.contracts import QuoteObservation

    transport = FakeTransport()
    bridge = FyersStreamingSource(transport)
    received: list = []
    bridge.register_observation_handler(received.append)

    bridge.ingest_tick(
        "NSE:NIFTY50-INDEX",
        {"lp": 25100.25, "v": 999, "bid": 25099.0, "ask": 25101.0, "last_traded_timestamp": 1760000000},
    )

    assert len(received) == 1
    obs = received[0]
    assert isinstance(obs, QuoteObservation)
    assert obs.quote.ltp == 25100.25
    assert obs.source == "FYERS"
    assert obs.data_mode.value == "BROKER_LIVE"
    # FYERS message codes never appear in observations.
    assert not ({"cn", "sub", "sf", "dp"} & set(vars(obs)["quote"].__dict__.keys()))


def test_streaming_bridge_drops_ltpless_and_unknown_ticks():
    from app.brokers.adapters.fyers.streaming_source import FyersStreamingSource

    transport = FakeTransport()
    bridge = FyersStreamingSource(transport)
    received: list = []
    bridge.register_observation_handler(received.append)
    bridge.ingest_tick("NSE:NIFTY50-INDEX", {"v": 10})           # no LTP
    bridge.ingest_tick("NSE:UNKNOWN-TICKER-XYZ", {"lp": 100.0})  # unknown symbol
    assert received == []


async def test_streaming_bridge_subscribe_and_disconnect():
    from app.brokers.adapters.fyers.streaming_source import FyersStreamingSource

    transport = FakeTransport()
    bridge = FyersStreamingSource(transport)
    await bridge.connect()
    await bridge.subscribe(["NSE:NIFTY50-INDEX"])
    assert transport.subscribed == ["NSE:NIFTY50-INDEX"]
    assert bridge.is_connected() is True
    await bridge.disconnect()
    assert transport.closed is True
    assert bridge.is_connected() is False


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def test_repr_never_leaks_token_or_secret():
    adapter = FyersAdapter(access_token="fy-token-value", api_key=APP_ID, api_secret=SECRET)
    text = repr(adapter) + str(adapter)
    assert "fy-token-value" not in text
    assert SECRET not in text


def test_adapter_error_repr_never_leaks_metadata():
    error = BrokerError(BrokerErrorCode.UPSTREAM_ERROR, "boom", metadata={"fyers_code": "401"})
    assert "fyers_code" not in repr(error)


def test_disconnect_forgets_tokens():
    adapter = FyersAdapter(access_token="tok", api_key=APP_ID, api_secret=SECRET)
    adapter.disconnect()
    assert adapter._access_token is None
    assert getattr(adapter, "_refresh_token", None) is None


async def test_no_session_is_auth_required():
    adapter = FyersAdapter(api_key=APP_ID)
    with pytest.raises(BrokerError) as exc:
        await adapter.get_profile()
    assert exc.value.code is BrokerErrorCode.AUTH_REQUIRED
