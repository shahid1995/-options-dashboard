"""Day 9 — Canonical Market-Data Contracts: Tests.

Establishes the test-first specification for every canonical contract
the market-data domain must satisfy. These tests verify:

- Instrument identity completeness and immutability
- Market observation structure and timestamp separation
- Price field semantics (units, nullable, source)
- Option chain row contract (OI in contracts, not lots)
- Greeks separation (broker vs model-calculated)
- Provenance metadata
- Data mode semantics
- Sequence/freshness fields
- Contract versioning
- Normalization boundary (no broker payloads leaking)
- Invalid payload rejection
- Deterministic normalization
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Import contracts under test (will fail until GREEN phase)
# ---------------------------------------------------------------------------

from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    GreeksObservation,
    MarketObservation,
    NormalizedInstrument,
    OptionChainObservation,
    OptionChainRow,
    PriceQuote,
    Provenance,
    QualityState,
    Side,
)


# ===========================================================================
# SECTION 1 — Instrument Identity
# ===========================================================================


class TestInstrumentIdentity:
    """Canonical instrument identity must be unambiguous, immutable,
    and clearly separate instrument identity from market observation."""

    def test_normalized_instrument_is_frozen(self):
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="INDEX",
        )
        with pytest.raises(AttributeError):
            inst.symbol = "BANKNIFTY"

    def test_option_contract_has_all_identity_fields(self):
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="OPTION",
            expiry="2026-09-11",
            strike=24500.0,
            option_type=Side.CALL,
            lot_size=65,
            tick_size=0.05,
        )
        assert inst.is_concrete_contract is True
        assert inst.expiry == "2026-09-11"
        assert inst.strike == 24500.0
        assert inst.option_type == Side.CALL
        assert inst.lot_size == 65

    def test_underlying_index_has_none_for_contract_fields(self):
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="INDEX",
        )
        assert inst.is_concrete_contract is False
        assert inst.expiry is None
        assert inst.strike is None
        assert inst.option_type is None

    def test_lot_size_and_tick_size_nullable(self):
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="INDEX",
            lot_size=None,
            tick_size=None,
        )
        assert inst.lot_size is None
        assert inst.tick_size is None

    def test_option_type_is_side_enum(self):
        inst_call = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="OPTION",
            expiry="2026-09-11",
            strike=24500.0,
            option_type=Side.CALL,
        )
        inst_put = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="OPTION",
            expiry="2026-09-11",
            strike=24500.0,
            option_type=Side.PUT,
        )
        assert inst_call.option_type == Side.CALL
        assert inst_put.option_type == Side.PUT

    def test_instrument_identity_distinguishes_from_observation(self):
        """Instrument identity contains no price/volume/timestamp data."""
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="INDEX",
        )
        d = asdict(inst)
        # No price fields in identity
        for field in ("ltp", "open", "high", "low", "close", "volume", "oi",
                       "bid", "ask", "timestamp", "captured_at"):
            assert field not in d, f"Field '{field}' should not be in instrument identity"


# ===========================================================================
# SECTION 2 — Market Observation
# ===========================================================================


class TestMarketObservation:
    """Market observation must separate instrument identity from market data,
    and maintain distinct timestamps for exchange event time vs receive time."""

    def test_observation_has_identity_and_timestamps(self):
        inst = NormalizedInstrument(
            exchange="NSE",
            segment="INDEX_DERIVATIVES",
            underlying="NIFTY",
            symbol="NIFTY",
            instrument_type="INDEX",
        )
        now = datetime.now(timezone.utc)
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=now,
            received_timestamp=now,
            source="BROKER_LIVE",
            data_mode=DataMode.BROKER_LIVE,
            sequence_id=1,
        )
        assert obs.instrument is inst
        assert obs.market_timestamp == now
        assert obs.received_timestamp == now

    def test_market_timestamp_and_received_timestamp_are_distinct(self):
        """Exchange event time and application receive time must never be
        conflated into a single field."""
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        market_ts = datetime(2026, 9, 3, 9, 15, 0, tzinfo=timezone.utc)
        received_ts = datetime(2026, 9, 3, 9, 15, 0, 150000, tzinfo=timezone.utc)
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=market_ts,
            received_timestamp=received_ts,
            source="BROKER_LIVE",
            data_mode=DataMode.BROKER_LIVE,
        )
        assert obs.market_timestamp != obs.received_timestamp
        assert obs.received_timestamp > obs.market_timestamp

    def test_observation_has_source_and_data_mode(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="STRIKENOVA_DATASET",
            data_mode=DataMode.HISTORICAL,
        )
        assert obs.source == "STRIKENOVA_DATASET"
        assert obs.data_mode == DataMode.HISTORICAL

    def test_sequence_id_optional(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER_LIVE",
            data_mode=DataMode.BROKER_LIVE,
        )
        assert obs.sequence_id is None

    def test_observation_has_quality_state(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER_LIVE",
            data_mode=DataMode.BROKER_LIVE,
            quality=QualityState.EXCELLENT,
        )
        assert obs.quality == QualityState.EXCELLENT

    def test_observation_has_contract_version(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER_LIVE",
            data_mode=DataMode.BROKER_LIVE,
            contract_version=ContractVersion.v1_0_0,
        )
        assert obs.contract_version == ContractVersion.v1_0_0


# ===========================================================================
# SECTION 3 — Price Fields
# ===========================================================================


class TestPriceQuote:
    """Canonical price semantics: units, nullable fields, source authority,
    and the distinction between event-time and snapshot-time values."""

    def test_price_fields_present(self):
        q = PriceQuote(
            ltp=24500.50,
            open=24480.0,
            high=24510.0,
            low=24470.0,
            close=24500.50,
            bid=24500.00,
            ask=24501.00,
            bid_quantity=150,
            ask_quantity=200,
            volume=1500000,
        )
        assert q.ltp == 24500.50
        assert q.volume == 1500000

    def test_nullable_fields_are_optional(self):
        q = PriceQuote(ltp=100.0)
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.close is None
        assert q.bid is None
        assert q.ask is None
        assert q.bid_quantity is None
        assert q.ask_quantity is None
        assert q.volume is None

    def test_price_fields_never_fabricate_zero(self):
        """Missing price fields must stay None, never be silently set to 0."""
        q = PriceQuote(ltp=100.0)
        assert q.open is None  # not 0
        assert q.volume is None  # not 0

    def test_price_source_authority(self):
        """PriceQuote records who provided the data."""
        q = PriceQuote(ltp=100.0, source="BROKER")
        assert q.source == "BROKER"


# ===========================================================================
# SECTION 4 — Options Chain Fields
# ===========================================================================


class TestOptionChainRow:
    """Option chain row contract: strike, CE/PE, OI semantics (contracts
    not lots), and all required chain fields."""

    def test_chain_row_has_required_fields(self):
        row = OptionChainRow(
            strike=24500.0,
            call=PriceQuote(ltp=150.0, volume=5000, oi=100000),
            put=PriceQuote(ltp=80.0, volume=3000, oi=75000),
        )
        assert row.strike == 24500.0
        assert row.call.ltp == 150.0
        assert row.put.ltp == 80.0

    def test_oi_is_contracts_not_lots(self):
        """OI is contracts, not lots, unless the source explicitly defines
        another unit. The contract documents this semantic."""
        row = OptionChainRow(
            strike=24500.0,
            call=PriceQuote(ltp=150.0, oi=100000),
            put=PriceQuote(ltp=80.0, oi=75000),
        )
        # OI values represent contracts
        assert row.call.oi == 100000
        assert row.put.oi == 75000

    def test_chain_observation_has_underlying_spot(self):
        obs = OptionChainObservation(
            symbol="NIFTY",
            expiry_date="2026-09-11",
            underlying_spot_price=24490.0,
            chain=[
                OptionChainRow(strike=24500.0, call=PriceQuote(ltp=150.0), put=PriceQuote(ltp=80.0)),
            ],
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
        )
        assert obs.underlying_spot_price == 24490.0
        assert len(obs.chain) == 1

    def test_chain_observation_preserves_timestamps(self):
        mt = datetime(2026, 9, 3, 9, 15, 0, tzinfo=timezone.utc)
        rt = datetime(2026, 9, 3, 9, 15, 0, 200000, tzinfo=timezone.utc)
        obs = OptionChainObservation(
            symbol="NIFTY",
            expiry_date="2026-09-11",
            underlying_spot_price=24490.0,
            chain=[],
            market_timestamp=mt,
            received_timestamp=rt,
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
        )
        assert obs.market_timestamp == mt
        assert obs.received_timestamp == rt

    def test_call_put_independence(self):
        """CE and PE legs are independently optional — a chain row can have
        only one side populated (e.g. partial chain data)."""
        call_only = OptionChainRow(
            strike=24500.0,
            call=PriceQuote(ltp=150.0),
            put=None,
        )
        assert call_only.call is not None
        assert call_only.put is None

        put_only = OptionChainRow(
            strike=24500.0,
            call=None,
            put=PriceQuote(ltp=80.0),
        )
        assert put_only.call is None
        assert put_only.put is not None


# ===========================================================================
# SECTION 5 — Greeks / IV Boundary
# ===========================================================================


class TestGreeksObservation:
    """Greeks boundary: broker-provided vs model-calculated must be
    distinguishable. The contract does not implement the Greek engine
    but establishes the data boundary."""

    def test_greeks_observation_has_source_field(self):
        g = GreeksObservation(
            iv=0.1824,
            delta=0.45,
            gamma=0.0003,
            theta=-0.05,
            vega=0.12,
            source="BROKER",
            calc_model=None,
            calc_version=None,
        )
        assert g.source == "BROKER"

    def test_broker_greeks_and_model_greeks_are_separate(self):
        broker_g = GreeksObservation(
            iv=0.18, delta=0.45, gamma=0.0003,
            theta=-0.05, vega=0.12,
            source="BROKER",
            calc_model=None, calc_version=None,
        )
        model_g = GreeksObservation(
            iv=0.1824, delta=0.452, gamma=0.00031,
            theta=-0.049, vega=0.121,
            source="MODEL",
            calc_model="BLACK_SCHOLES_EUROPEAN",
            calc_version="1.0.0",
        )
        # Same instrument, different sources — values may differ
        assert broker_g.source != model_g.source
        assert broker_g.calc_model is None
        assert model_g.calc_model == "BLACK_SCHOLES_EUROPEAN"

    def test_greek_fields_nullable(self):
        """Greeks may be partially available from broker."""
        g = GreeksObservation(
            iv=0.18,
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
            source="BROKER",
            calc_model=None,
            calc_version=None,
        )
        assert g.iv == 0.18
        assert g.delta is None

    def test_iv_stored_as_canonical_decimal(self):
        """IV is a canonical decimal fraction (0.1824 = 18.24%)."""
        g = GreeksObservation(
            iv=0.1824,
            delta=0.45, gamma=0.0003, theta=-0.05, vega=0.12,
            source="MODEL",
            calc_model="BLACK_SCHOLES_EUROPEAN",
            calc_version="1.0.0",
        )
        assert 0.0 < g.iv < 1.0  # decimal, not percent


# ===========================================================================
# SECTION 6 — Provenance
# ===========================================================================


class TestProvenance:
    """Every canonical observation must carry enough metadata to answer:
    Where did this data come from, when was it received, and which
    normalization/version produced it?"""

    def test_provenance_has_required_fields(self):
        p = Provenance(
            source="UPSTOX",
            collection_mode="BROKER_LIVE",
            received_at=datetime.now(timezone.utc),
            normalization_version="1.0.0",
            contract_version="1.0.0",
        )
        assert p.source == "UPSTOX"
        assert p.collection_mode == "BROKER_LIVE"
        assert p.normalization_version == "1.0.0"

    def test_provenance_tracks_transformation(self):
        """Provenance records which normalization pipeline produced the
        observation."""
        p = Provenance(
            source="UPSTOX",
            collection_mode="BROKER_LIVE",
            received_at=datetime.now(timezone.utc),
            normalization_version="2.0.0",
            contract_version="1.0.0",
            transformation_id="chain_v2_normalize",
        )
        assert p.transformation_id == "chain_v2_normalize"

    def test_provenance_on_observation(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        p = Provenance(
            source="UPSTOX",
            collection_mode="BROKER_LIVE",
            received_at=datetime.now(timezone.utc),
            normalization_version="1.0.0",
            contract_version="1.0.0",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="UPSTOX",
            data_mode=DataMode.BROKER_LIVE,
            provenance=p,
        )
        assert obs.provenance is p


# ===========================================================================
# SECTION 7 — Data Mode
# ===========================================================================


class TestDataMode:
    """Canonical data mode semantics."""

    def test_data_modes_exist(self):
        assert DataMode.BROKER_LIVE.value == "BROKER_LIVE"
        assert DataMode.BROKER_SNAPSHOT.value == "BROKER_SNAPSHOT"
        assert DataMode.HISTORICAL.value == "HISTORICAL"
        assert DataMode.IMPORTED.value == "IMPORTED"
        assert DataMode.REPLAY.value == "REPLAY"
        assert DataMode.TEST.value == "TEST"

    def test_delayed_data_not_labeled_realtime(self):
        """DataMode enforces that delayed data is never represented as
        real-time. A TEST or HISTORICAL mode must not masquerade as
        BROKER_LIVE."""
        # If you have historical data, use HISTORICAL mode
        assert DataMode.HISTORICAL != DataMode.BROKER_LIVE
        assert DataMode.BROKER_SNAPSHOT != DataMode.BROKER_LIVE


# ===========================================================================
# SECTION 8 — Quality State
# ===========================================================================


class TestQualityState:
    """Quality states as specified by the Blueprint."""

    def test_quality_states_exist(self):
        assert QualityState.EXCELLENT.value == "EXCELLENT"
        assert QualityState.GOOD.value == "GOOD"
        assert QualityState.DEGRADED.value == "DEGRADED"
        assert QualityState.INSUFFICIENT.value == "INSUFFICIENT"


# ===========================================================================
# SECTION 9 — Contract Versioning
# ===========================================================================


class TestContractVersioning:
    """The canonical market-data contract must be explicitly versioned."""

    def test_contract_version_exists(self):
        assert ContractVersion.v1_0_0.value == "1.0.0"

    def test_version_is_semver_string(self):
        v = ContractVersion.v1_0_0
        parts = v.value.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_observations_carry_version(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="TEST",
            data_mode=DataMode.TEST,
            contract_version=ContractVersion.v1_0_0,
        )
        assert obs.contract_version.value.startswith("1.")


# ===========================================================================
# SECTION 10 — Normalization Boundary
# ===========================================================================


class TestNormalizationBoundary:
    """External broker payloads must not leak directly into downstream
    domain logic. The contract boundary must be verifiable."""

    def test_observation_does_not_carry_raw_payload(self):
        """MarketObservation is the normalized contract — it does not
        contain broker-specific raw payloads."""
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
        )
        d = asdict(obs)
        # No broker-specific keys
        for key in ("instrument_key", "transaction_type", "is_amo",
                     "raw_payload", "broker_response", "upstox_data"):
            assert key not in d, f"Broker key '{key}' leaked into canonical contract"

    def test_option_chain_observation_no_broker_keys(self):
        obs = OptionChainObservation(
            symbol="NIFTY",
            expiry_date="2026-09-11",
            underlying_spot_price=24490.0,
            chain=[],
            market_timestamp=datetime.now(timezone.utc),
            received_timestamp=datetime.now(timezone.utc),
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
        )
        d = asdict(obs)
        for key in ("call_options", "put_options", "market_data",
                     "option_greeks", "raw_data", "instrument_key"):
            assert key not in d, f"Broker key '{key}' leaked into chain contract"


# ===========================================================================
# SECTION 11 — Deterministic Normalization
# ===========================================================================


class TestDeterministicNormalization:
    """Normalization must be deterministic: same input produces same output."""

    def test_same_input_same_output(self):
        """Two PriceQuote instances with the same values are equal."""
        q1 = PriceQuote(ltp=100.0, open=99.0, high=101.0, low=98.0, close=100.0)
        q2 = PriceQuote(ltp=100.0, open=99.0, high=101.0, low=98.0, close=100.0)
        assert asdict(q1) == asdict(q2)

    def test_instrument_equality(self):
        i1 = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        i2 = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        assert asdict(i1) == asdict(i2)


# ===========================================================================
# SECTION 12 — Side Enum
# ===========================================================================


class TestSideEnum:
    """Side enum for CE/PE representation."""

    def test_call_and_put(self):
        assert Side.CALL.value == "CALL"
        assert Side.PUT.value == "PUT"

    def test_side_is_string_enum(self):
        assert isinstance(Side.CALL.value, str)
        assert isinstance(Side.PUT.value, str)


# ===========================================================================
# SECTION 13 — Contract Serialization
# ===========================================================================


class TestContractSerialization:
    """Contracts must be serializable for API responses and persistence."""

    def test_observation_to_dict(self):
        inst = NormalizedInstrument(
            exchange="NSE", segment="INDEX_DERIVATIVES",
            underlying="NIFTY", symbol="NIFTY", instrument_type="INDEX",
        )
        obs = MarketObservation(
            instrument=inst,
            market_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc),
            received_timestamp=datetime(2026, 9, 3, 0, 0, 10, tzinfo=timezone.utc),
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
            contract_version=ContractVersion.v1_0_0,
        )
        d = asdict(obs)
        assert d["instrument"]["symbol"] == "NIFTY"
        assert d["data_mode"] == "BROKER_LIVE"
        assert d["contract_version"] == "1.0.0"

    def test_chain_observation_to_dict(self):
        obs = OptionChainObservation(
            symbol="NIFTY",
            expiry_date="2026-09-11",
            underlying_spot_price=24490.0,
            chain=[
                OptionChainRow(
                    strike=24500.0,
                    call=PriceQuote(ltp=150.0, oi=100000),
                    put=PriceQuote(ltp=80.0, oi=75000),
                ),
            ],
            market_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc),
            received_timestamp=datetime(2026, 9, 3, 0, 0, 10, tzinfo=timezone.utc),
            source="BROKER",
            data_mode=DataMode.BROKER_LIVE,
        )
        d = asdict(obs)
        assert d["symbol"] == "NIFTY"
        assert len(d["chain"]) == 1
        assert d["chain"][0]["call"]["oi"] == 100000
