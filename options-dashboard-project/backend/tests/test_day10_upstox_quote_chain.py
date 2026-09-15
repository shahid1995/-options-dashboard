"""Day 10 — Upstox quote/option-chain adapter completion: contract tests.

Proves the Upstox adapter boundary normalizes raw Upstox payloads into the
Day 9 canonical market-data contracts:

    Upstox API payload
        → Upstox adapter / mapper
        → Day 9 canonical contracts
          (NormalizedInstrument, PriceQuote, QuoteObservation,
           OptionChainObservation, GreeksObservation)
        → normalized observation

RED-phase expectations drive the implementation in ``mapper.py`` and
``adapter.py``; no real Upstox credentials are used — deterministic fixtures.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.brokers.adapters.upstox import mapper
from app.brokers.adapters.upstox.adapter import UpstoxAdapter
from app.brokers.domain.enums import OptionType
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import InstrumentIdentity
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    GreeksObservation,
    NormalizedInstrument,
    OptionChainObservation,
    PriceQuote,
    Provenance,
    QualityState,
    QuoteObservation,
    Side,
)

# ---------------------------------------------------------------------------
# Deterministic fixtures (sanitized, non-production test data)
# ---------------------------------------------------------------------------

ISO_MARKET_TS = "2023-10-19T05:21:51.099+05:30"  # Upstox ISO feed timestamp
EPOCH_MS_TS = "1697624972130"  # Upstox last_trade_time (epoch milliseconds)

RECEIVED_AT = datetime(2023, 10, 19, 0, 0, 0, tzinfo=timezone.utc)


def make_fetcher(body):
    async def _f(*args, **kwargs):
        if isinstance(body, Exception):
            raise body
        return body

    return _f


def index_identity(symbol: str = "NIFTY") -> InstrumentIdentity:
    return mapper.resolve_instrument_identity(symbol)


# A realistic Upstox V2 /market-quote/quotes single-item payload (documented
# shape: ohlc, depth.buy/sell top-5, timestamp, last_price, volume, oi,
# last_trade_time). Field names are deliberately the Upstox names — the
# mapper must strip them at the boundary.
def quote_payload(**overrides) -> dict:
    base = {
        "ohlc": {"open": 52.4, "high": 53.8, "low": 51.75, "close": 52.05},
        "depth": {
            "buy": [
                {"quantity": 6917, "price": 52.05, "orders": 20},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
            ],
            "sell": [
                {"quantity": 4150, "price": 52.1, "orders": 15},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
                {"quantity": 0, "price": 0.0, "orders": 0},
            ],
        },
        "timestamp": ISO_MARKET_TS,
        "instrument_token": "NSE_INDEX|Nifty 50",
        "symbol": "NIFTY",
        "last_price": 52.05,
        "volume": 24123697,
        "average_price": 52.56,
        "oi": 0,
        "net_change": -1.05,
        "total_buy_quantity": 6917,
        "total_sell_quantity": 0,
        "lower_circuit_limit": 42.5,
        "upper_circuit_limit": 63.7,
        "last_trade_time": EPOCH_MS_TS,
        "oi_day_high": 0,
        "oi_day_low": 0,
    }
    base.update(overrides)
    return base


def quotes_response(payloads_by_key: dict[str, dict]) -> dict:
    return {"status": "success", "data": payloads_by_key}


# Realistic raw option-chain payload in the shape the Upstox chain endpoint
# returns (strike_price + call_options/put_options with market_data and
# option_greeks). Used to test OptionChainObservation normalization.
def chain_row(
    strike: float,
    *,
    call_ltp=None,
    call_oi=None,
    put_ltp=None,
    put_oi=None,
    call_iv=None,
    put_iv=None,
    spot: float = 24500.0,
) -> dict:
    call_market = {}
    put_market = {}
    if call_ltp is not None:
        call_market["ltp"] = call_ltp
    if call_oi is not None:
        call_market["oi"] = call_oi
    if put_ltp is not None:
        put_market["ltp"] = put_ltp
    if put_oi is not None:
        put_market["oi"] = put_oi

    call_greeks = {"iv": call_iv} if call_iv is not None else {}
    put_greeks = {"iv": put_iv} if put_iv is not None else {}

    return {
        "strike_price": strike,
        "underlying_spot_price": spot,
        "call_options": {"market_data": call_market, "option_greeks": call_greeks},
        "put_options": {"market_data": put_market, "option_greeks": put_greeks},
    }


def chain_payload(rows: list[dict]) -> dict:
    return {"status": "success", "data": rows}


# ===========================================================================
# Section 1 — REST market-quote HTTP client (services/upstox.py)
# ===========================================================================


class TestUpstoxQuoteHttpClient:
    async def test_get_market_quotes_hits_quotes_endpoint(self):
        """The raw Upstox client must expose a market-quote fetch that maps to
        GET /v2/market-quote/quotes with a comma-joined instrument_key."""
        from app.services import upstox as raw_upstox

        payload = quotes_response({"NSE_INDEX|Nifty 50": quote_payload()})
        with pytest.MonkeyPatch.context() as mp:
            request_mock = AsyncMock(return_value=payload)
            mp.setattr(raw_upstox, "_request", request_mock)
            result = await raw_upstox.get_market_quotes(
                "token", ["NSE_INDEX|Nifty 50"]
            )
        assert result["status"] == "success"
        call = request_mock.await_args
        assert call.kwargs["params"]["instrument_key"] == "NSE_INDEX|Nifty 50"

    async def test_get_market_quotes_joins_multiple_keys(self):
        from app.services import upstox as raw_upstox

        with pytest.MonkeyPatch.context() as mp:
            request_mock = AsyncMock(return_value=quotes_response({}))
            mp.setattr(raw_upstox, "_request", request_mock)
            await raw_upstox.get_market_quotes("token", ["K1", "K2", "K3"])
        call = request_mock.await_args
        assert call.kwargs["params"]["instrument_key"] == "K1,K2,K3"

    async def test_get_market_quote_single_delegates(self):
        from app.services import upstox as raw_upstox

        payload = quotes_response({"K1": quote_payload()})
        with pytest.MonkeyPatch.context() as mp:
            request_mock = AsyncMock(return_value=payload)
            mp.setattr(raw_upstox, "_request", request_mock)
            result = await raw_upstox.get_market_quote("token", "K1")
        assert result == payload
        call = request_mock.await_args
        assert call.kwargs["params"]["instrument_key"] == "K1"


# ===========================================================================
# Section 2 — Instrument identity bridge
# ===========================================================================


class TestInstrumentBridge:
    def test_broker_identity_to_normalized_index(self):
        """Broker-layer InstrumentIdentity (NIFTY index) → market-data
        NormalizedInstrument without broker keys and without inventing a
        third identity model."""
        identity = index_identity("NIFTY")
        inst = mapper.instrument_identity_to_normalized(identity)
        assert isinstance(inst, NormalizedInstrument)
        assert inst.symbol == "NIFTY"
        assert inst.exchange == "NSE"
        assert inst.segment == "INDEX_DERIVATIVES"
        assert inst.underlying == "NIFTY"
        assert inst.instrument_type == "INDEX"
        assert inst.expiry is None
        assert inst.strike is None
        assert inst.option_type is None
        # No broker key on the canonical contract.
        assert "instrument_key" not in str(inst)
        assert "instrument_token" not in str(inst)

    def test_broker_identity_to_normalized_option(self):
        """A concrete option identity maps option_type CALL/PUT to the
        market-data Side enum."""
        identity = InstrumentIdentity(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="OPTION",
            expiry="2026-09-11",
            strike=24500.0,
            option_type=OptionType.CALL,
            lot_size=65,
        )
        inst = mapper.instrument_identity_to_normalized(identity)
        assert inst.is_concrete_contract is True
        assert inst.expiry == "2026-09-11"
        assert inst.strike == 24500.0
        assert inst.option_type is Side.CALL
        assert inst.lot_size == 65


# ===========================================================================
# Section 3 — Quote normalization
# ===========================================================================


class TestQuoteNormalization:
    def test_quote_payload_maps_ohlc_ltp_volume_oi(self):
        """Raw Upstox quote payload → canonical PriceQuote; LTP comes from
        last_price, OHLC from ohlc, volume/OI are preserved as-is."""
        price = mapper.upstox_quote_to_price_quote(quote_payload())
        assert isinstance(price, PriceQuote)
        assert price.ltp == 52.05
        assert price.open == 52.4
        assert price.high == 53.8
        assert price.low == 51.75
        assert price.close == 52.05
        assert price.volume == 24123697
        assert price.oi == 0  # oi of 0 is an observed value, not fabricated

    def test_quote_payload_maps_best_bid_ask_from_depth(self):
        """Top of book: depth.buy[0] is bid, depth.sell[0] is ask."""
        price = mapper.upstox_quote_to_price_quote(quote_payload())
        assert price.bid == 52.05
        assert price.ask == 52.1
        assert price.bid_quantity == 6917
        assert price.ask_quantity == 4150

    def test_quote_missing_fields_stay_none(self):
        """Absent Upstox fields → None, never fabricated zeros."""
        raw = quote_payload()
        raw.pop("volume", None)
        raw.pop("oi", None)
        del raw["depth"]
        price = mapper.upstox_quote_to_price_quote(raw)
        assert price.volume is None
        assert price.oi is None
        assert price.bid is None
        assert price.ask is None
        assert price.ltp is not None  # still carries the core price

    def test_quote_source_marks_upstox(self):
        price = mapper.upstox_quote_to_price_quote(quote_payload())
        assert price.source == "UPSTOX"


# ===========================================================================
# Section 4 — Timestamps
# ===========================================================================


class TestTimestampNormalization:
    def test_epoch_millis_parsed_to_utc_datetime(self):
        """Upstox last_trade_time (epoch ms string) → UTC datetime."""
        dt = mapper.upstox_timestamp_to_datetime(EPOCH_MS_TS)
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.tzinfo.utcoffset(dt).total_seconds() == 0.0  # UTC

    def test_iso_timestamp_normalized_to_utc(self):
        """ISO-8601 with +05:30 → UTC (offset applied, not kept)."""
        dt = mapper.upstox_timestamp_to_datetime(ISO_MARKET_TS)
        assert dt is not None
        expected = datetime.fromisoformat(ISO_MARKET_TS).astimezone(timezone.utc)
        assert dt == expected
        assert dt.tzinfo.utcoffset(dt).total_seconds() == 0.0
        assert dt.hour == 23  # 05:21 IST = 23:21 UTC the prior day
        assert dt.minute == 51

    def test_none_and_unparseable_return_none(self):
        assert mapper.upstox_timestamp_to_datetime(None) is None
        assert mapper.upstox_timestamp_to_datetime("not-a-timestamp") is None
        assert mapper.upstox_timestamp_to_datetime("") is None

    def test_quote_observation_keeps_market_and_received_separate(self):
        """The normalized quote must carry the Upstox market timestamp AND the
        distinct receive timestamp, never conflated."""
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        assert obs.market_timestamp is not None
        assert obs.market_timestamp != obs.received_timestamp
        expected_market = datetime.fromtimestamp(
            int(EPOCH_MS_TS) / 1000, tz=timezone.utc
        )
        assert obs.market_timestamp == expected_market
        assert obs.received_timestamp == RECEIVED_AT


# ===========================================================================
# Section 5 — QuoteObservation composite
# ===========================================================================


class TestQuoteObservation:
    def test_observation_has_identity_price_and_mode(self):
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        assert isinstance(obs, QuoteObservation)
        assert obs.instrument.symbol == "NIFTY"
        assert isinstance(obs.quote, PriceQuote)
        assert obs.quote.ltp == 52.05
        # REST market-quote is a snapshot — never labelled live.
        assert obs.data_mode is DataMode.BROKER_SNAPSHOT

    def test_observation_carries_version(self):
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        assert obs.contract_version == ContractVersion.v1_0_0

    def test_observation_serialization_has_no_upstox_keys(self):
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        serialized = str(asdict(obs))
        for key in (
            "ohlc", "depth", "last_price", "instrument_token",
            "last_trade_time", "total_buy_quantity", "lower_circuit_limit",
        ):
            assert key not in serialized, f"Upstox key '{key}' leaked into canonical quote"

    def test_observation_never_carries_credentials(self):
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        serialized = str(asdict(obs))
        for forbidden in ("access_token", "api_secret", "client_secret", "Authorization"):
            assert forbidden not in serialized


# ===========================================================================
# Section 6 — Provenance & DataMode
# ===========================================================================


class TestQuoteProvenance:
    def test_observation_builds_provenance(self):
        obs = mapper.upstox_quote_to_observation(
            quote_payload(),
            mapper.instrument_identity_to_normalized(index_identity()),
            received_at=RECEIVED_AT,
        )
        assert obs.provenance is not None
        assert obs.provenance.source == "UPSTOX"
        assert obs.provenance.collection_mode == DataMode.BROKER_SNAPSHOT.value
        assert obs.provenance.received_at == RECEIVED_AT
        assert obs.provenance.normalization_version == mapper.NORMALIZATION_VERSION
        assert obs.provenance.contract_version == ContractVersion.v1_0_0.value
        assert obs.provenance.transformation_id == "upstox_market_quote_v1"


# ===========================================================================
# Section 7 — Adapter wiring (get_quote / get_quotes)
# ===========================================================================


class TestAdapterQuotes:
    async def test_get_quote_returns_canonical_observation(self):
        adapter = UpstoxAdapter(
            "tok",
            quote_fetcher=make_fetcher(
                quotes_response({"NSE_INDEX|Nifty 50": quote_payload()})
            ),
        )
        obs = await adapter.get_quote(index_identity("NIFTY"))
        assert isinstance(obs, QuoteObservation)
        assert obs.instrument.symbol == "NIFTY"
        assert obs.quote.ltp == 52.05
        assert obs.data_mode is DataMode.BROKER_SNAPSHOT

    async def test_get_quote_requires_broker_key(self):
        """A concrete option identity with no broker key mapping fails with a
        canonical error — never a fabricated quote."""
        identity = InstrumentIdentity(
            exchange="NSE", segment="INDEX_DERIVATIVES", underlying="NIFTY",
            symbol="NIFTY", instrument_type="OPTION", expiry="2026-09-11",
            strike=24500.0, option_type=OptionType.CALL,
        )
        adapter = UpstoxAdapter("tok")
        with pytest.raises(BrokerError) as exc:
            await adapter.get_quote(identity)
        assert exc.value.code in (
            BrokerErrorCode.INVALID_INSTRUMENT,
            BrokerErrorCode.CAPABILITY_UNSUPPORTED,
        )

    async def test_get_quote_maps_upstox_http_error(self):
        from app.services.upstox import UpstoxError

        adapter = UpstoxAdapter(
            "tok",
            quote_fetcher=make_fetcher(UpstoxError(429, "rate limited")),
        )
        with pytest.raises(BrokerError) as exc:
            await adapter.get_quote(index_identity("NIFTY"))
        assert exc.value.code is BrokerErrorCode.RATE_LIMITED

    async def test_get_quotes_returns_observations_per_instrument(self):
        adapter = UpstoxAdapter(
            "tok",
            quote_fetcher=make_fetcher(
                quotes_response(
                    {
                        "NSE_INDEX|Nifty 50": quote_payload(symbol="NIFTY"),
                        "NSE_INDEX|Nifty Bank": quote_payload(
                            symbol="BANKNIFTY", last_price=48000.0,
                        ),
                    }
                )
            ),
        )
        obs_list = await adapter.get_quotes(
            [index_identity("NIFTY"), index_identity("BANKNIFTY")]
        )
        assert len(obs_list) == 2
        symbols = {o.instrument.symbol for o in obs_list}
        assert symbols == {"NIFTY", "BANKNIFTY"}

    async def test_get_quotes_requires_token(self):
        adapter = UpstoxAdapter()
        with pytest.raises(BrokerError) as exc:
            await adapter.get_quotes([index_identity("NIFTY")])
        assert exc.value.code is BrokerErrorCode.AUTH_REQUIRED


# ===========================================================================
# Section 8 — Option chain normalization
# ===========================================================================


class TestChainNormalization:
    def test_chain_payload_maps_to_option_chain_observation(self):
        raw = chain_payload(
            [
                chain_row(24500.0, call_ltp=150.0, call_oi=100000,
                          put_ltp=80.0, put_oi=75000, spot=24490.0),
                chain_row(24550.0, call_ltp=110.0, put_ltp=120.0, spot=24490.0),
            ]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        assert isinstance(obs, OptionChainObservation)
        assert obs.symbol == "NIFTY"
        assert obs.expiry_date == "2026-09-11"
        assert obs.underlying_spot_price == 24490.0
        assert len(obs.chain) == 2
        # Chain rows sorted by strike ascending.
        assert [r.strike for r in obs.chain] == [24500.0, 24550.0]

    def test_chain_row_legs_are_price_quotes(self):
        raw = chain_payload(
            [chain_row(24500.0, call_ltp=150.0, call_oi=100000,
                       put_ltp=80.0, put_oi=75000, spot=24490.0)]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        row = obs.chain[0]
        assert isinstance(row.call, PriceQuote)
        assert isinstance(row.put, PriceQuote)
        assert row.call.ltp == 150.0
        # OI preserved as broker units (contracts, not lots — never converted).
        assert row.call.oi == 100000
        assert row.put.oi == 75000

    def test_chain_row_missing_leg_stays_none(self):
        """CE/PE legs are independent: a row with only a call keeps put=None."""
        raw = chain_payload(
            [chain_row(24500.0, call_ltp=150.0, spot=24490.0)]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        row = obs.chain[0]
        assert row.call is not None
        assert row.put is None

    def test_chain_observation_serialization_has_no_broker_keys(self):
        raw = chain_payload(
            [
                chain_row(24500.0, call_ltp=150.0, call_oi=100000,
                          put_ltp=80.0, put_oi=75000, spot=24490.0),
            ]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        serialized = str(asdict(obs))
        for key in (
            "call_options", "put_options", "market_data", "option_greeks",
            "strike_price", "instrument_key",
        ):
            assert key not in serialized, f"Upstox key '{key}' leaked into canonical chain"

    def test_chain_observation_carries_timestamps(self):
        raw = chain_payload(
            [
                chain_row(24500.0, call_ltp=150.0, put_ltp=80.0, spot=24490.0),
            ]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        assert obs.received_timestamp == RECEIVED_AT
        assert obs.data_mode is DataMode.BROKER_SNAPSHOT
        assert obs.source == "UPSTOX"
        assert obs.contract_version == ContractVersion.v1_0_0


# ===========================================================================
# Section 9 — Broker Greeks preserved as broker values
# ===========================================================================


class TestBrokerGreeks:
    def test_chain_iv_maps_to_broker_source_greeks(self):
        """Upstox option_greeks iv must map to a canonical GreeksObservation
        with source=BROKER — never silently dropped or relabelled as model."""
        raw = chain_payload(
            [
                chain_row(24500.0, call_ltp=150.0, call_iv=0.1824,
                          put_ltp=80.0, put_iv=0.20, spot=24490.0),
            ]
        )
        greeks = mapper.upstox_chain_to_broker_greeks(raw)
        assert greeks  # not empty — broker Greeks preserved
        # One GreeksObservation per (strike, side) with iv from the payload.
        key_call = (24500.0, "CALL")
        key_put = (24500.0, "PUT")
        assert key_call in greeks
        assert key_put in greeks
        call_g = greeks[key_call]
        assert isinstance(call_g, GreeksObservation)
        assert call_g.source == "BROKER"
        assert call_g.iv == 0.1824
        assert call_g.delta is None  # only iv supplied
        put_g = greeks[key_put]
        assert put_g.iv == 0.20

    def test_broker_greeks_never_confused_with_model(self):
        """A model-calculated GreeksObservation (source=MODEL) is a separate
        object — broker values are not overwritten by model values."""
        raw = chain_payload(
            [chain_row(24500.0, call_ltp=150.0, call_iv=0.1824, spot=24490.0)]
        )
        broker = mapper.upstox_chain_to_broker_greeks(raw)[(24500.0, "CALL")]
        assert broker.source == "BROKER"
        assert broker.calc_model is None  # broker values carry no model claim
        model = GreeksObservation(
            iv=0.1901, delta=0.45, gamma=0.0003, theta=-0.05, vega=0.12,
            source="MODEL", calc_model="BLACK_SCHOLES_EUROPEAN",
            calc_version="1.0.0",
        )
        assert model.source == "MODEL"
        assert broker.iv != model.iv  # distinct — never merged


# ===========================================================================
# Section 10 — Malformed payload handling
# ===========================================================================


class TestMalformedPayload:
    def test_quote_without_price_raises_canonical_error(self):
        """A malformed Upstox quote with no last_price is rejected — never
        silently fabricated to zero."""
        raw = quote_payload()
        raw.pop("last_price", None)
        with pytest.raises(BrokerError) as exc:
            mapper.upstox_quote_to_observation(
                raw,
                mapper.instrument_identity_to_normalized(index_identity()),
                received_at=RECEIVED_AT,
            )
        assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA

    def test_chain_without_rows_returns_empty_observation(self):
        raw = chain_payload([])
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        assert obs.chain == []
        assert obs.underlying_spot_price is None

    def test_chain_row_without_strike_is_skipped(self):
        raw = chain_payload(
            [
                chain_row(24500.0, call_ltp=150.0, spot=24490.0),
                {"underlying_spot_price": 24490.0,
                 "call_options": {"market_data": {"ltp": 1.0}}},
            ]
        )
        obs = mapper.upstox_chain_to_observation(
            "NIFTY", "2026-09-11", raw, received_at=RECEIVED_AT
        )
        assert len(obs.chain) == 1
        assert obs.chain[0].strike == 24500.0
