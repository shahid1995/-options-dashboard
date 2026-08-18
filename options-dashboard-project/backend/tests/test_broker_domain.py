"""Phase 6.5.0.2 — broker-neutral domain contract tests.

Covers the phase's contract-test matrix:

A. Canonical model tests — no Upstox-specific field names in canonical
   models; optional/missing values stay explicit (None); nothing fabricated
   to zero.
B. Registry/gateway tests — Upstox resolves correctly; unknown broker fails
   safely; selection is deterministic.
C. Error taxonomy tests — canonical codes exist and are stable; session
   codes are recognized.
D. Instrument mapping tests — canonical identity is broker-neutral; the
   Upstox key stays in the broker mapping; option type maps correctly.
E. Order mapping tests — BUY/SELL, MARKET/LIMIT/SL/SL-M, quantity/price/
   trigger/validity/AMO/market-protection mappings are isolated to the
   Upstox mapper; slicing is represented without leaking Upstox fields.
F. Response mapping tests — single/multiple order ids, status mapping,
   rejected/partial/filled orders.
G. Security tests — canonical models and order results never carry
   credentials; broker keys stay in the mapping, never in the identity.
"""

import pytest

from app.brokers.domain.capabilities import BrokerCapabilities, BrokerCapability, CapabilityState
from app.brokers.domain.enums import (
    BROKER_ID_UPSTOX,
    BrokerId,
    ExecutionPolicy,
    OptionType,
    OrderStatus,
    OrderType,
    Product,
    Side,
    Validity,
)
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import (
    BrokerConnectionContext,
    BrokerInstrumentMapping,
    BrokerOrderRequest,
    BrokerOrderResult,
    InstrumentIdentity,
)
from app.brokers.gateway import BrokerGateway, gateway
from app.brokers.registry import BrokerRegistry


# ---- A. Canonical model tests ------------------------------------------------


def test_canonical_models_have_no_broker_specific_field_names():
    """Upstox field names must never appear as canonical model attributes."""
    forbidden = {"instrument_key", "instrument_token", "transaction_type", "is_amo", "slice"}
    request_fields = set(BrokerOrderRequest.__dataclass_fields__)
    result_fields = set(BrokerOrderResult.__dataclass_fields__)
    identity_fields = set(InstrumentIdentity.__dataclass_fields__)
    assert not (request_fields & forbidden)
    assert not (result_fields & forbidden)
    assert not (identity_fields & forbidden)
    assert "broker_order_ids" in result_fields  # list, not a single id
    assert "execution_policy" in request_fields  # neutral slicing policy


def test_canonical_models_keep_optional_values_explicit_none():
    identity = InstrumentIdentity(exchange="NSE", segment="INDEX_DERIVATIVES", underlying="NIFTY", symbol="NIFTY")
    assert identity.expiry is None
    assert identity.strike is None
    assert identity.option_type is None
    assert identity.lot_size is None
    assert identity.tick_size is None
    assert identity.is_concrete_contract is False

    order = BrokerOrderRequest(
        instrument=identity,
        side=Side.BUY,
        quantity=1,
    )
    assert order.price is None
    assert order.trigger_price is None
    assert order.disclosed_quantity is None
    assert order.broker_account_id is None
    assert order.client_order_tag is None
    assert order.product is None  # never fabricated to a default in the model


def test_broker_order_result_supports_multiple_broker_order_ids():
    single = BrokerOrderResult(broker="UPSTOX", broker_order_ids=("ord-1",), status=OrderStatus.FILLED)
    assert single.broker_order_ids == ("ord-1",)

    sliced = BrokerOrderResult(broker="UPSTOX", broker_order_ids=("ord-1", "ord-2", "ord-3"))
    assert len(sliced.broker_order_ids) == 3
    assert sliced.status is OrderStatus.UNKNOWN  # unknown until mapped


def test_canonical_order_status_lifecycle_has_required_states():
    required = {
        "CREATED", "PENDING", "OPEN", "PARTIALLY_FILLED",
        "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN",
    }
    assert {s.value for s in OrderStatus} == required


def test_canonical_enums_are_broker_neutral():
    assert {s.value for s in Side} == {"BUY", "SELL"}
    assert {t.value for t in OrderType} == {"MARKET", "LIMIT", "SL", "SL-M"}
    assert {p.value for p in Product} == {"DELIVERY", "INTRADAY", "CO", "MTF"}
    assert {v.value for v in Validity} == {"DAY", "IOC"}
    assert {e.value for e in ExecutionPolicy} == {
        "AUTO", "BROKER_NATIVE", "PLATFORM_MANAGED", "DISABLED",
    }


def test_broker_connection_context_scopes_user_and_broker():
    ctx = BrokerConnectionContext(user_id="user-1", broker="UPSTOX")
    assert ctx.user_id == "user-1"
    assert ctx.broker == "UPSTOX"
    assert ctx.account_id is None


# ---- B. Registry / gateway tests --------------------------------------------


def test_registry_resolves_upstox_deterministically():
    registry = BrokerRegistry()
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter

    registry.register(BROKER_ID_UPSTOX, UpstoxAdapter)
    first = registry.create(BROKER_ID_UPSTOX, access_token="tok-1")
    second = registry.create(BROKER_ID_UPSTOX, access_token="tok-2")
    assert type(first) is UpstoxAdapter
    assert type(second) is UpstoxAdapter
    assert first is not second  # adapters are per-call objects, never shared
    assert registry.known_brokers() == ("UPSTOX",)


def test_registry_unknown_broker_fails_safely():
    registry = BrokerRegistry()
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter

    registry.register(BROKER_ID_UPSTOX, UpstoxAdapter)
    with pytest.raises(BrokerError) as exc:
        registry.create("ZERODHA")
    assert exc.value.code is BrokerErrorCode.BROKER_UNKNOWN
    assert "ZERODHA" in exc.value.message


def test_registry_register_is_idempotent():
    registry = BrokerRegistry()

    class FakeAdapter:
        pass

    registry.register("X", FakeAdapter)
    registry.register("x", FakeAdapter)  # case-insensitive, no clobber
    assert registry.create("X") is not None


def test_gateway_default_requires_exactly_one_broker():
    single = BrokerGateway()
    assert len(single.registry.known_brokers()) == 1
    adapter = single.default(access_token="tok")
    assert adapter.broker_name == "UPSTOX"

    empty = BrokerGateway(BrokerRegistry())
    with pytest.raises(BrokerError) as exc:
        empty.default()
    assert exc.value.code is BrokerErrorCode.BROKER_UNKNOWN


def test_gateway_for_connection_attaches_context():
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter

    ctx = BrokerConnectionContext(user_id="user-7", broker="UPSTOX", account_id="ACC-7")
    adapter = gateway.for_connection(ctx, access_token="tok")
    assert isinstance(adapter, UpstoxAdapter)
    assert adapter.get_connection_context() == ctx


def test_known_broker_ids_include_future_brokers_but_only_upstox_registered():
    assert BrokerId.ZERODHA.value == "ZERODHA"
    assert BrokerId.DHAN.value == "DHAN"
    assert BrokerId.ANGEL_ONE.value == "ANGEL_ONE"
    assert BrokerId.FYERS.value == "FYERS"
    # Only UPSTOX is registered in this phase — the others must fail safely.
    with pytest.raises(BrokerError) as exc:
        gateway.create(BrokerId.ZERODHA)
    assert exc.value.code is BrokerErrorCode.BROKER_UNKNOWN


# ---- C. Error taxonomy tests -------------------------------------------------


def test_error_taxonomy_has_required_codes():
    required = {
        "AUTH_REQUIRED", "TOKEN_EXPIRED", "RATE_LIMITED", "NETWORK_ERROR",
        "MAINTENANCE", "INVALID_INSTRUMENT", "INVALID_QUANTITY", "INVALID_PRICE",
        "ORDER_REJECTED", "ORDER_NOT_FOUND", "ORDER_ALREADY_FINAL",
        "ACCOUNT_RESTRICTED", "SEGMENT_DISABLED", "STATIC_IP_REQUIRED",
        "CAPABILITY_UNSUPPORTED", "BROKER_UNKNOWN",
    }
    assert required <= {c.value for c in BrokerErrorCode}


def test_session_codes_recognized():
    assert BrokerErrorCode.AUTH_REQUIRED in BrokerErrorCode.SESSION_CODES
    assert BrokerErrorCode.TOKEN_EXPIRED in BrokerErrorCode.SESSION_CODES
    assert BrokerErrorCode.RATE_LIMITED not in BrokerErrorCode.SESSION_CODES


def test_broker_error_repr_never_leaks_metadata():
    err = BrokerError(
        BrokerErrorCode.TOKEN_EXPIRED,
        "session gone",
        status_code=401,
        metadata={"secret": "do-not-leak"},
    )
    assert "do-not-leak" not in repr(err)
    assert "session gone" in str(err)
    assert err.code is BrokerErrorCode.TOKEN_EXPIRED
    assert err.status_code == 401


# ---- D. Instrument mapping tests ---------------------------------------------

from app.brokers.adapters.upstox import mapper as upstox_mapper  # noqa: E402


def test_instrument_identity_is_broker_neutral():
    identity = upstox_mapper.resolve_instrument_identity("nifty")
    assert identity.symbol == "NIFTY"
    assert identity.exchange == "NSE"
    assert identity.segment == "INDEX_DERIVATIVES"
    assert identity.underlying == "NIFTY"
    assert identity.instrument_type == "INDEX"
    assert identity.lot_size is None  # unknown → explicit None, never fabricated
    # The Upstox key is NOT on the canonical identity.
    assert not hasattr(identity, "instrument_key")
    assert not hasattr(identity, "instrument_token")


def test_broker_key_stays_in_the_broker_mapping():
    mapping = BrokerInstrumentMapping(
        broker="UPSTOX",
        broker_instrument_id="NSE_INDEX|Nifty 50",
        identity=upstox_mapper.resolve_instrument_identity("NIFTY"),
    )
    assert mapping.broker_instrument_id == "NSE_INDEX|Nifty 50"
    assert mapping.identity.symbol == "NIFTY"
    # The broker key is reachable ONLY through the mapping, never the identity.
    assert "NSE_INDEX|Nifty 50" not in str(mapping.identity)


def test_unknown_symbol_raises_invalid_instrument():
    with pytest.raises(BrokerError) as exc:
        upstox_mapper.resolve_instrument_identity("UNKNOWN")
    assert exc.value.code is BrokerErrorCode.INVALID_INSTRUMENT


def test_option_type_maps_both_ways():
    assert upstox_mapper.option_type_to_domain("call") is OptionType.CALL
    assert upstox_mapper.option_type_to_domain("PUT") is OptionType.PUT
    assert upstox_mapper.option_type_to_domain("CE") is OptionType.CALL
    assert upstox_mapper.option_type_to_domain("PE") is OptionType.PUT
    assert upstox_mapper.option_type_to_domain("weird") is None  # never guessed
    assert upstox_mapper.option_type_to_upstox(OptionType.CALL) == "call"
    assert upstox_mapper.option_type_to_upstox("PUT") == "put"


def test_search_instruments_returns_mappings():
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter

    adapter = UpstoxAdapter()
    results = adapter.search_instruments("bank")
    symbols = {r.identity.symbol for r in results}
    assert "BANKNIFTY" in symbols  # BANKNIFTY and BANKEX both match "bank"
    assert all(isinstance(r, BrokerInstrumentMapping) for r in results)
    assert all(r.broker == "UPSTOX" for r in results)
    assert all("BANK" in r.identity.symbol for r in results)


# ---- E. Order mapping tests --------------------------------------------------


def _order_request(**overrides):
    identity = InstrumentIdentity(
        exchange="NSE", segment="INDEX_DERIVATIVES", underlying="NIFTY",
        symbol="NIFTY", instrument_type="INDEX", lot_size=65,
    )
    base = dict(
        instrument=identity,
        side=Side.BUY,
        quantity=2,
        order_type=OrderType.LIMIT,
        price=150.0,
    )
    base.update(overrides)
    return BrokerOrderRequest(**base)


def test_order_request_maps_buy_and_sell():
    payload = upstox_mapper.build_order_request_payload(_order_request(side=Side.BUY))
    assert payload["transaction_type"] == "BUY"
    payload = upstox_mapper.build_order_request_payload(_order_request(side=Side.SELL))
    assert payload["transaction_type"] == "SELL"
    # transaction_type exists ONLY inside the Upstox payload, never canonical.
    assert "transaction_type" not in BrokerOrderRequest.__dataclass_fields__


def test_order_type_mappings_are_isolated_to_the_mapper():
    for canonical, expected in [
        (OrderType.MARKET, "MARKET"),
        (OrderType.LIMIT, "LIMIT"),
        (OrderType.STOP_LOSS, "SL"),
        (OrderType.STOP_LOSS_MARKET, "SL-M"),
    ]:
        payload = upstox_mapper.build_order_request_payload(
            _order_request(order_type=canonical)
        )
        assert payload["order_type"] == expected


def test_quantity_price_trigger_remain_canonical():
    payload = upstox_mapper.build_order_request_payload(
        _order_request(
            quantity=2,
            order_type=OrderType.STOP_LOSS,
            price=100.0,
            trigger_price=95.0,
        )
    )
    assert payload["quantity"] == 2 * 65  # lots → contracts at the boundary
    assert payload["price"] == 100.0
    assert payload["trigger_price"] == 95.0
    assert payload["instrument_token"] == "NSE_INDEX|Nifty 50"  # broker key, boundary-only


def test_validity_and_after_market_map_to_upstox_fields():
    day = upstox_mapper.build_order_request_payload(_order_request(validity=Validity.DAY))
    assert day["validity"] == "DAY"
    assert day["is_amo"] is False
    amo = upstox_mapper.build_order_request_payload(
        _order_request(validity=Validity.DAY, after_market=True)
    )
    assert amo["is_amo"] is True  # is_amo exists ONLY in the Upstox payload
    assert "after_market" in BrokerOrderRequest.__dataclass_fields__
    assert "is_amo" not in BrokerOrderRequest.__dataclass_fields__


def test_market_protection_and_tag_map_at_the_boundary():
    payload = upstox_mapper.build_order_request_payload(
        _order_request(market_protection=True, client_order_tag="tag-1")
    )
    assert payload["market_protection"] == 1
    assert payload["tag"] == "tag-1"


def test_native_slicing_is_represented_without_leaking_upstox_fields():
    # Canonical: execution policy + multi-id result — no "slice" field.
    req = _order_request(execution_policy=ExecutionPolicy.BROKER_NATIVE)
    assert req.execution_policy is ExecutionPolicy.BROKER_NATIVE
    assert "slice" not in BrokerOrderRequest.__dataclass_fields__
    # The Upstox payload never receives a slicing directive.
    payload = upstox_mapper.build_order_request_payload(req)
    assert "slice" not in payload


def test_order_payload_requires_lot_size_for_conversion():
    identity = InstrumentIdentity(
        exchange="NSE", segment="INDEX_DERIVATIVES", underlying="NIFTY",
        symbol="NIFTY", instrument_type="INDEX", lot_size=None,
    )
    with pytest.raises(BrokerError) as exc:
        upstox_mapper.build_order_request_payload(
            BrokerOrderRequest(instrument=identity, side=Side.BUY, quantity=1)
        )
    assert exc.value.code is BrokerErrorCode.INVALID_QUANTITY


# ---- F. Response mapping tests -----------------------------------------------


def test_order_result_maps_single_order_id():
    result = upstox_mapper.map_order_result(
        {"status": "success", "data": {"order_id": "ord-1", "status": "complete"}}
    )
    assert result.broker_order_ids == ("ord-1",)
    assert result.status is OrderStatus.FILLED


def test_order_result_maps_multiple_order_ids():
    result = upstox_mapper.map_order_result(
        {
            "status": "success",
            "data": [
                {"order_id": "ord-1"},
                {"order_id": "ord-2"},
                {"order_id": "ord-3"},
            ],
        }
    )
    assert result.broker_order_ids == ("ord-1", "ord-2", "ord-3")


def test_order_status_mapping():
    cases = {
        "complete": OrderStatus.FILLED,
        "pending": OrderStatus.PENDING,
        "open": OrderStatus.OPEN,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "cancelled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "expired": OrderStatus.EXPIRED,
    }
    for raw, expected in cases.items():
        assert upstox_mapper.upstox_status_to_domain(raw) is expected
    assert upstox_mapper.upstox_status_to_domain("mystery_state") is OrderStatus.UNKNOWN
    assert upstox_mapper.upstox_status_to_domain(None) is OrderStatus.UNKNOWN


def test_order_result_maps_rejected_order():
    result = upstox_mapper.map_order_result(
        {"status": "error", "data": {"order_id": "ord-x", "status": "rejected"}}
    )
    assert result.status is OrderStatus.REJECTED
    assert result.broker_order_ids == ("ord-x",)


def test_order_result_maps_partial_fill():
    result = upstox_mapper.map_order_result(
        {"status": "success", "data": {"order_id": "ord-p", "status": "partially_filled"}}
    )
    assert result.status is OrderStatus.PARTIALLY_FILLED


def test_order_result_empty_is_unknown_not_fabricated():
    result = upstox_mapper.map_order_result({})
    assert result.broker_order_ids == ()
    assert result.status is OrderStatus.UNKNOWN
    assert result.broker == "UPSTOX"


# ---- G. Security tests -------------------------------------------------------


def test_canonical_order_result_never_carries_credentials():
    result = BrokerOrderResult(broker="UPSTOX", broker_order_ids=("ord-1",))
    serialized = str(result)
    for forbidden in ("access_token", "refresh_token", "api_secret", "client_secret"):
        assert forbidden not in serialized
    assert "access_token" not in BrokerOrderResult.__dataclass_fields__
    assert "token" not in BrokerOrderRequest.__dataclass_fields__


def test_capabilities_distinguish_supported_from_disabled():
    from app.brokers.adapters.upstox.adapter import upstox_capability_matrix

    capabilities = BrokerCapabilities(
        [BrokerCapability(name, state, wired, detail) for name, state, wired, detail in upstox_capability_matrix()]
    )
    # F&O order placement: SUPPORTED by the API (never UNSUPPORTED) but not
    # wired in this phase.
    assert capabilities.state("orders") is CapabilityState.SUPPORTED
    assert capabilities.get("orders").wired is False
    assert capabilities.state("option_chain") is CapabilityState.SUPPORTED
    assert capabilities.get("option_chain").wired is True

    # Account-level: an account without the NFO segment is ACCOUNT_DISABLED —
    # NOT UNSUPPORTED.
    disabled = capabilities.with_session_state(
        session_active=True, profile={"exchanges": ["NSE", "BSE"]}
    )
    assert disabled.state("orders") is CapabilityState.ACCOUNT_DISABLED
    assert disabled.state("option_chain") is CapabilityState.ACCOUNT_DISABLED
    assert disabled.state("funds") is CapabilityState.AVAILABLE or disabled.state("funds") is CapabilityState.SUPPORTED

    # No session → data capabilities require auth.
    unauth = capabilities.with_session_state(session_active=False, profile=None)
    assert unauth.state("funds") is CapabilityState.AUTH_REQUIRED
    assert unauth.state("orders") is CapabilityState.AUTH_REQUIRED
    assert unauth.state("websocket_market_data") is CapabilityState.SUPPORTED  # not session-gated


def test_capability_states_are_never_booleans():
    from app.brokers.adapters.upstox.adapter import upstox_capability_matrix

    for name, state, wired, detail in upstox_capability_matrix():
        assert isinstance(state, CapabilityState)
        assert isinstance(wired, bool)
