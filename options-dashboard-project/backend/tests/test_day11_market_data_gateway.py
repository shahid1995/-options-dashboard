"""Day 11 — Market Data Gateway: broker-neutral routing boundary tests.

Proves the gateway boundary contracts:

    Source adapter (session-bound, broker-neutral protocol surface)
        → Market Data Gateway
            source selection      (per-request adapter / provider, never
                                   a global credential-holding source)
            capability pre-flight (quotes / option_chain wired?)
            data-mode semantics   (REST = BROKER_SNAPSHOT; live requests
                                   require a live-capable source; delayed
                                   data is never relabelled live)
            provenance            (adapter provenance preserved — never
                                   overwritten; mandatory on quotes)
            canonical guard       (raw broker payloads are refused at the
                                   gateway — never reach consumers)
        → Day 9 canonical contracts
            (QuoteObservation / OptionChainObservation)
        → downstream consumer

No production credentials, no Upstox payloads, no HTTP — deterministic fake
sources speak only the broker-neutral adapter surface.

RED-phase expectations drive the implementation in
``app/market_data/gateway.py``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import pytest

from app.brokers.domain.capabilities import (
    BrokerCapabilities,
    BrokerCapability,
    CapabilityState,
)
from app.brokers.domain.enums import OptionType
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import InstrumentIdentity
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    NormalizedInstrument,
    OptionChainObservation,
    PriceQuote,
    Provenance,
    QuoteObservation,
)

# ---------------------------------------------------------------------------
# Deterministic fixtures
# ---------------------------------------------------------------------------

RECEIVED_AT = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
MARKET_AT = datetime(2026, 9, 3, 9, 59, 30, tzinfo=timezone.utc)


def index_identity(symbol: str = "NIFTY") -> InstrumentIdentity:
    return InstrumentIdentity(
        exchange="NSE",
        segment="INDEX_DERIVATIVES",
        underlying=symbol,
        symbol=symbol,
        instrument_type="INDEX",
    )


def normalized_instrument(symbol: str = "NIFTY") -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="INDEX_DERIVATIVES",
        underlying=symbol,
        symbol=symbol,
        instrument_type="INDEX",
    )


def quote_observation(
    symbol: str = "NIFTY",
    *,
    ltp: float = 24500.0,
    mode: DataMode = DataMode.BROKER_SNAPSHOT,
    with_provenance: bool = True,
) -> QuoteObservation:
    provenance = None
    if with_provenance:
        provenance = Provenance(
            source="UPSTOX",
            collection_mode=mode.value,
            received_at=RECEIVED_AT,
            normalization_version="1.0.0",
            contract_version=ContractVersion.v1_0_0.value,
            transformation_id="upstox_market_quote_v1",
        )
    return QuoteObservation(
        instrument=normalized_instrument(symbol),
        quote=PriceQuote(ltp=ltp, source="UPSTOX"),
        market_timestamp=MARKET_AT,
        received_timestamp=RECEIVED_AT,
        source="UPSTOX",
        data_mode=mode,
        provenance=provenance,
        contract_version=ContractVersion.v1_0_0,
    )


def chain_leg(ltp: float | None, *, oi: float | None = None) -> dict:
    leg = {"ltp": ltp, "oi": oi, "chg_oi": None, "volume": None,
           "quote_timestamp": None, "iv": None, "delta": None,
           "theta": None, "gamma": None, "vega": None, "pop": None}
    return leg


def canonical_chain_dict(symbol: str = "NIFTY", expiry: str = "2026-09-11") -> dict:
    """The canonical transformed chain dict shape the adapter protocol
    returns (mapper.transform_chain contract)."""
    return {
        "symbol": symbol,
        "expiry_date": expiry,
        "underlying_spot_price": 24490.0,
        "chain": [
            {
                "strike": 24500.0,
                "call": chain_leg(150.0, oi=100000),
                "put": chain_leg(80.0, oi=75000),
            },
            {
                "strike": 24550.0,
                "call": chain_leg(110.0, oi=90000),
                "put": chain_leg(None, oi=0),
            },
        ],
    }


def capabilities(*wired_names: str, live_wired: bool = False) -> BrokerCapabilities:
    """A capability set where every ``wired_names`` capability is SUPPORTED
    and wired; everything else is UNSUPPORTED and unwired."""
    matrix = {
        "quotes": ("quotes", CapabilityState.SUPPORTED, "quotes" in wired_names),
        "option_chain": ("option_chain", CapabilityState.SUPPORTED, "option_chain" in wired_names),
        "websocket_market_data": (
            "websocket_market_data", CapabilityState.SUPPORTED, live_wired,
        ),
    }
    return BrokerCapabilities(
        [
            BrokerCapability(name, state, wired, f"GET {name}")
            for name, state, wired in matrix.values()
        ]
    )


class FakeSource:
    """A broker-neutral fake speaking ONLY the adapter protocol surface.

    Never holds tokens; raises/returns whatever the test configures so the
    gateway's orchestration (not Upstox specifics) is under test.
    """

    broker_id = "FAKESTOCK"
    broker_name = "Fake Stock Broker"

    def __init__(
        self,
        *,
        quote_result: QuoteObservation | dict | Exception = None,
        quotes_result: list | Exception = None,
        chain_result: dict | Exception = None,
        caps: BrokerCapabilities | None = None,
        track_calls: list | None = None,
    ):
        self._quote_result = quote_result
        self._quotes_result = quotes_result
        self._chain_result = chain_result
        self._caps = caps or capabilities("quotes", "option_chain")
        self._track = track_calls

    def get_capabilities(self, profile: dict | None = None) -> BrokerCapabilities:
        return self._caps

    async def get_quote(self, instrument: InstrumentIdentity):
        if self._track is not None:
            self._track.append(("quote", instrument.symbol))
        if isinstance(self._quote_result, Exception):
            raise self._quote_result
        return self._quote_result

    async def get_quotes(self, instruments: list[InstrumentIdentity]):
        if self._track is not None:
            self._track.append(("quotes", len(instruments)))
        if isinstance(self._quotes_result, Exception):
            raise self._quotes_result
        return self._quotes_result

    async def get_option_chain(self, symbol: str, expiry_date: str) -> dict:
        if self._track is not None:
            self._track.append(("chain", symbol, expiry_date))
        if isinstance(self._chain_result, Exception):
            raise self._chain_result
        return self._chain_result


def make_provider(source):
    return lambda: source


# ===========================================================================
# Section 1 — Gateway quote request (canonical boundary)
# ===========================================================================


class TestGatewayQuoteRequest:
    async def test_get_quote_returns_canonical_observation(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation())
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(index_identity(), source=source)
        assert isinstance(obs, QuoteObservation)
        assert obs.instrument.symbol == "NIFTY"
        assert obs.quote.ltp == 24500.0

    async def test_get_quote_request_is_canonical_not_broker_specific(self):
        """The consumer requests with a canonical identity — the gateway never
        asks the consumer for broker keys, tokens, or Upstox instrument keys."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation("BANKNIFTY"))
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(
            index_identity("BANKNIFTY"), source=source
        )
        assert obs.instrument.symbol == "BANKNIFTY"

    async def test_get_quotes_returns_observations_in_order(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(
            quotes_result=[quote_observation("NIFTY"), quote_observation("BANKNIFTY")]
        )
        gateway = MarketDataGateway()
        obs_list = await gateway.get_quotes(
            [index_identity("NIFTY"), index_identity("BANKNIFTY")], source=source
        )
        assert [o.instrument.symbol for o in obs_list] == ["NIFTY", "BANKNIFTY"]


# ===========================================================================
# Section 2 — Source selection
# ===========================================================================


class TestSourceSelection:
    async def test_no_source_raises_source_unavailable(self):
        from app.market_data.gateway import MarketDataGateway

        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity())
        assert exc.value.code is BrokerErrorCode.SOURCE_UNAVAILABLE

    async def test_provider_is_used_when_source_absent(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation())
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(
            index_identity(), source_provider=make_provider(source)
        )
        assert isinstance(obs, QuoteObservation)

    async def test_provider_returning_none_raises_source_unavailable(self):
        from app.market_data.gateway import MarketDataGateway

        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source_provider=lambda: None)
        assert exc.value.code is BrokerErrorCode.SOURCE_UNAVAILABLE

    async def test_explicit_source_wins_over_provider(self):
        from app.market_data.gateway import MarketDataGateway

        explicit = FakeSource(quote_result=quote_observation("NIFTY"))
        provider_source = FakeSource(quote_result=quote_observation("BANKNIFTY"))
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(
            index_identity(),
            source=explicit,
            source_provider=make_provider(provider_source),
        )
        assert obs.instrument.symbol == "NIFTY"

    async def test_provider_errors_propagate_unmasked(self):
        """An adapter failure (e.g. the session adapter cannot authenticate)
        must not be swallowed or relabelled by the gateway."""
        from app.market_data.gateway import MarketDataGateway

        def failing_provider():
            raise BrokerError(BrokerErrorCode.AUTH_REQUIRED, "session missing")

        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source_provider=failing_provider)
        assert exc.value.code is BrokerErrorCode.AUTH_REQUIRED

    async def test_adapter_failure_propagates_unmasked(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(
            quote_result=BrokerError(BrokerErrorCode.RATE_LIMITED, "slow down")
        )
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.RATE_LIMITED


# ===========================================================================
# Section 3 — Capability pre-flight
# ===========================================================================


class TestCapabilityGate:
    async def test_unwired_quote_capability_raises_unsupported(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(caps=capabilities())  # nothing wired
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.CAPABILITY_UNSUPPORTED

    async def test_unwired_chain_capability_raises_unsupported(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(caps=capabilities("quotes"))  # chain unwired
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        assert exc.value.code is BrokerErrorCode.CAPABILITY_UNSUPPORTED

    async def test_auth_required_capability_state_raises_auth_required(self):
        from app.market_data.gateway import MarketDataGateway

        caps = capabilities("quotes")
        caps = BrokerCapabilities(
            [
                BrokerCapability(
                    "quotes", CapabilityState.AUTH_REQUIRED, True, "auth needed"
                ),
                BrokerCapability(
                    "option_chain", CapabilityState.UNSUPPORTED, False, "unused"
                ),
                BrokerCapability(
                    "websocket_market_data", CapabilityState.UNSUPPORTED, False, "unused"
                ),
            ]
        )
        source = FakeSource(quote_result=quote_observation(), caps=caps)
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.AUTH_REQUIRED

    async def test_wired_capability_proceeds(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation())
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(index_identity(), source=source)
        assert isinstance(obs, QuoteObservation)


# ===========================================================================
# Section 4 — Data-mode semantics (delayed data is never labelled live)
# ===========================================================================


class TestDataModeSemantics:
    async def test_snapshot_is_the_default_request_mode(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation())
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(index_identity(), source=source)
        assert obs.data_mode is DataMode.BROKER_SNAPSHOT

    async def test_live_request_without_live_source_fails(self):
        """BROKER_LIVE semantics require a live-capable source; a REST
        snapshot source cannot satisfy a live request — no silent downgrade."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation())
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(
                index_identity(), source=source, data_mode=DataMode.BROKER_LIVE
            )
        assert exc.value.code is BrokerErrorCode.CAPABILITY_UNSUPPORTED

    async def test_live_request_with_live_capable_source_succeeds(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(
            quote_result=quote_observation(mode=DataMode.BROKER_LIVE),
            caps=capabilities("quotes", live_wired=True),
        )
        gateway = MarketDataGateway()
        obs = await gateway.get_quote(
            index_identity(), source=source, data_mode=DataMode.BROKER_LIVE
        )
        assert obs.data_mode is DataMode.BROKER_LIVE

    async def test_snapshot_request_rejects_live_mislabel(self):
        """A source returning a LIVE observation for a snapshot request is
        rejected — the gateway never lets delayed/snapshot semantics silently
        upgrade to real-time."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation(mode=DataMode.BROKER_LIVE))
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA


# ===========================================================================
# Section 5 — Provenance preservation
# ===========================================================================


class TestProvenancePreservation:
    async def test_quote_provenance_preserved_untouched(self):
        """The gateway must preserve — never overwrite — adapter provenance."""
        from app.market_data.gateway import MarketDataGateway

        obs = quote_observation()
        source = FakeSource(quote_result=obs)
        gateway = MarketDataGateway()
        result = await gateway.get_quote(index_identity(), source=source)
        assert result.provenance == obs.provenance
        assert result.provenance.source == "UPSTOX"
        assert result.provenance.transformation_id == "upstox_market_quote_v1"

    async def test_quote_without_provenance_rejected(self):
        """Provenance is mandatory on the canonical boundary (Day 9 rule) —
        a canonical quote with no provenance cannot answer where/when/how it
        was produced and must not flow downstream."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(quote_result=quote_observation(with_provenance=False))
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA

    async def test_gateway_does_not_attach_own_provenance(self):
        """Gateway metadata must stay separate from source provenance — it
        does not fabricate a transformation_id for data it did not produce."""
        from app.market_data.gateway import MarketDataGateway

        obs = quote_observation()
        source = FakeSource(quote_result=obs)
        gateway = MarketDataGateway()
        result = await gateway.get_quote(index_identity(), source=source)
        assert result.provenance.received_at == obs.provenance.received_at
        # The gateway never substitutes its own normalization version.
        assert result.provenance.normalization_version == "1.0.0"


# ===========================================================================
# Section 6 — Option-chain routing
# ===========================================================================


class TestOptionChainRouting:
    async def test_get_option_chain_returns_canonical_observation(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(chain_result=canonical_chain_dict())
        gateway = MarketDataGateway(now=lambda: RECEIVED_AT)
        obs = await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        assert isinstance(obs, OptionChainObservation)
        assert obs.symbol == "NIFTY"
        assert obs.expiry_date == "2026-09-11"
        assert obs.underlying_spot_price == 24490.0

    async def test_chain_rows_are_canonical_and_sorted(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(chain_result=canonical_chain_dict())
        gateway = MarketDataGateway(now=lambda: RECEIVED_AT)
        obs = await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        rows = obs.chain
        assert len(rows) == 2
        assert [r.strike for r in rows] == [24500.0, 24550.0]
        assert isinstance(rows[0].call, PriceQuote)
        assert rows[0].call.ltp == 150.0
        assert rows[0].call.oi == 100000  # OI in contracts, never converted
        assert isinstance(rows[0].put, PriceQuote)

    async def test_chain_row_without_ltp_leg_is_absent(self):
        """A leg with no LTP cannot be canonically priced — stays None rather
        than a fabricated zero."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(chain_result=canonical_chain_dict())
        gateway = MarketDataGateway(now=lambda: RECEIVED_AT)
        obs = await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        assert obs.chain[1].put is None  # put_ltp None → absent leg

    async def test_chain_observation_carries_gateway_metadata(self):
        """The observation the consumer receives carries the collection
        timestamp, source label and snapshot mode (never relabelled live)."""
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(chain_result=canonical_chain_dict())
        gateway = MarketDataGateway(now=lambda: RECEIVED_AT)
        obs = await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        assert obs.received_timestamp == RECEIVED_AT
        assert obs.source == source.broker_id
        assert obs.data_mode is DataMode.BROKER_SNAPSHOT
        assert obs.contract_version == ContractVersion.v1_0_0

    async def test_chain_observation_has_no_broker_payload_shape(self):
        from app.market_data.gateway import MarketDataGateway

        source = FakeSource(chain_result=canonical_chain_dict())
        gateway = MarketDataGateway(now=lambda: RECEIVED_AT)
        obs = await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        serialized = str(asdict(obs))
        for key in ("call_options", "put_options", "market_data", "last_price",
                    "instrument_token", "depth", "ohlc"):
            assert key not in serialized


# ===========================================================================
# Section 7 — Boundary integrity (raw payloads refused)
# ===========================================================================


class TestBoundaryIntegrity:
    async def test_source_returning_raw_payload_is_refused(self):
        """If an adapter ever returned a raw broker payload (a plain dict
        with Upstox fields) instead of a canonical observation, the gateway
        must refuse it — raw payloads never reach downstream consumers."""
        from app.market_data.gateway import MarketDataGateway

        raw_payload = {
            "status": "success",
            "data": {
                "NSE_INDEX|Nifty 50": {
                    "last_price": 52.05, "volume": 100, "instrument_token": "X",
                }
            },
        }
        source = FakeSource(quote_result=raw_payload)
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_quote(index_identity(), source=source)
        assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA

    async def test_source_returning_raw_chain_payload_is_refused(self):
        from app.market_data.gateway import MarketDataGateway

        raw_chain = {
            "status": "success",
            "data": [{"strike_price": 24500.0,
                      "call_options": {"market_data": {"ltp": 150.0}}}],
        }
        source = FakeSource(chain_result=raw_chain)
        gateway = MarketDataGateway()
        with pytest.raises(BrokerError) as exc:
            await gateway.get_option_chain("NIFTY", "2026-09-11", source=source)
        assert exc.value.code is BrokerErrorCode.INVALID_MARKET_DATA

    async def test_canonical_objects_never_carry_credentials(self):
        from app.market_data.gateway import MarketDataGateway

        obs = quote_observation()
        source = FakeSource(quote_result=obs)
        gateway = MarketDataGateway()
        result = await gateway.get_quote(index_identity(), source=source)
        serialized = str(asdict(result))
        for forbidden in ("access_token", "api_secret", "client_secret",
                          "Authorization", "bearer"):
            assert forbidden not in serialized


# ===========================================================================
# Section 8 — Tenant / session isolation
# ===========================================================================


class TestTenantIsolation:
    async def test_gateway_uses_per_request_source_not_a_global(self):
        """Two users' session-bound adapters never mix: each request routes
        through the source supplied for THAT request — the gateway holds no
        global adapter and no credentials."""
        from app.market_data.gateway import MarketDataGateway

        calls: list = []
        user_a = FakeSource(
            quote_result=quote_observation("NIFTY"), track_calls=calls
        )
        user_b = FakeSource(
            quote_result=quote_observation("BANKNIFTY"), track_calls=calls
        )
        gateway = MarketDataGateway()

        await gateway.get_quote(index_identity("NIFTY"), source=user_a)
        await gateway.get_quote(index_identity("BANKNIFTY"), source=user_b)

        # Exactly one quote call per request, on the matching session adapter.
        assert calls == [("quote", "NIFTY"), ("quote", "BANKNIFTY")]

    async def test_gateway_has_no_credential_state(self):
        from app.market_data.gateway import MarketDataGateway

        gateway = MarketDataGateway()
        assert not hasattr(gateway, "access_token")
        assert not hasattr(gateway, "_access_token")
        text = str(gateway)
        for forbidden in ("token", "secret", "api_key"):
            assert forbidden not in text.lower()


# ===========================================================================
# Section 9 — Timestamps / freshness (deterministic, no scoring)
# ===========================================================================


class TestFreshnessCalculation:
    def test_observation_ages_are_deterministic(self):
        from app.market_data.gateway import ObservationAges, observation_ages

        now = datetime(2026, 9, 3, 10, 0, 5, tzinfo=timezone.utc)
        obs = quote_observation()
        ages = observation_ages(obs, now=now)
        assert isinstance(ages, ObservationAges)
        # market 09:59:30 → 35s old; received 10:00:00 → 5s old
        assert ages.market_age_seconds == 35.0
        assert ages.received_age_seconds == 5.0

    def test_missing_market_timestamp_stays_none(self):
        """A quote without an exchange event time has no market age — None,
        never fabricated to zero."""
        from app.market_data.gateway import observation_ages

        obs = quote_observation()
        obs = QuoteObservation(
            instrument=obs.instrument,
            quote=obs.quote,
            market_timestamp=None,
            received_timestamp=RECEIVED_AT,
            source="UPSTOX",
            data_mode=DataMode.BROKER_SNAPSHOT,
            provenance=obs.provenance,
        )
        ages = observation_ages(obs, now=RECEIVED_AT + timedelta(seconds=60))
        assert ages.market_age_seconds is None
        assert ages.received_age_seconds == 60.0

    def test_ages_are_not_a_quality_score(self):
        """Freshness here is pure timestamp arithmetic — no scoring, no
        EXCELLENT/GOOD/DEGRADED classification (that is Day 12's engine)."""
        from app.market_data.gateway import observation_ages

        ages = observation_ages(quote_observation(), now=RECEIVED_AT)
        assert not hasattr(ages, "score")
        assert not hasattr(ages, "state")
        assert not hasattr(ages, "classification")
