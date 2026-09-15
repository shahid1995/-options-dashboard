"""Day 12 — Data Quality Engine: deterministic quality boundary tests.

Proves the reusable quality engine over Day-9 canonical observations:

    Gateway
        → Canonical Observation (QuoteObservation / OptionChainObservation /
                                 MarketObservation)
        → Data Quality Engine
            freshness / completeness / validity / consistency / continuity /
            anomaly / provenance          (source reliability: NOT_EVALUATED —
                                           no justified statistics exist)
        → QualityResult (score 0-100, state, structured issues)
        → Quant / Intelligence

Determinism rules under test:
* ``evaluate(observation, reference_time=...)`` never reads the wall clock;
  the same input + reference time yields the identical result.
* Missing evidence yields ``NOT_EVALUATED`` dimensions, never fabricated
  scores; quality issues never carry credentials or broker payloads.

RED-phase expectations drive ``app/market_data/quality.py``.

Documented engine defaults (locked by tests below):
* dimension weights: freshness .30, completeness .25, validity .20,
  consistency .05, provenance .15, anomaly .05 (continuity .05 only when a
  prior observation is supplied) — evaluated-dimension weighted mean.
* freshness: fresh <= 60s (score 1.0); stale > 300s (score 0.0 +
  STALE_OBSERVATION); linear decay between; future timestamps score 0.0.
* classification: EXCELLENT >= 90, GOOD >= 75, DEGRADED >= 60, else
  INSUFFICIENT; any CRITICAL issue forces INSUFFICIENT; any ERROR issue
  prevents EXCELLENT.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    MarketObservation,
    NormalizedInstrument,
    OptionChainObservation,
    OptionChainRow,
    PriceQuote,
    Provenance,
    QualityState,
    QuoteObservation,
)

# ---------------------------------------------------------------------------
# Deterministic fixtures
# ---------------------------------------------------------------------------

T0 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)          # received
MARKET = datetime(2026, 9, 3, 9, 59, 30, tzinfo=timezone.utc)     # market
REF = datetime(2026, 9, 3, 10, 0, 5, tzinfo=timezone.utc)         # reference


def instrument(symbol: str = "NIFTY") -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="INDEX_DERIVATIVES",
        underlying=symbol,
        symbol=symbol,
        instrument_type="INDEX",
    )


def provenance(**overrides) -> Provenance:
    base = dict(
        source="UPSTOX",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=T0,
        normalization_version="1.0.0",
        contract_version=ContractVersion.v1_0_0.value,
        transformation_id="upstox_market_quote_v1",
    )
    base.update(overrides)
    return Provenance(**base)


def quote(
    *,
    ltp: float = 24500.0,
    symbol: str = "NIFTY",
    received: datetime = T0,
    market: datetime | None = MARKET,
    source: str = "UPSTOX",
    mode: DataMode = DataMode.BROKER_SNAPSHOT,
    prov: Provenance | None = None,
    include_provenance: bool = True,
    price_quote: PriceQuote | None = None,
) -> QuoteObservation:
    if prov is None and include_provenance:
        prov = provenance()
    return QuoteObservation(
        instrument=instrument(symbol),
        quote=price_quote or PriceQuote(ltp=ltp, source="UPSTOX"),
        market_timestamp=market,
        received_timestamp=received,
        source=source,
        data_mode=mode,
        provenance=prov,
        contract_version=ContractVersion.v1_0_0,
    )


def leg(ltp: float | None, *, bid=None, ask=None, low=None, high=None,
        volume: float | None = None, oi: float | None = None,
        source: str = "UPSTOX") -> PriceQuote | None:
    if ltp is None:
        return None
    return PriceQuote(ltp=ltp, bid=bid, ask=ask, low=low, high=high,
                      volume=volume, oi=oi, source=source)


def chain_observation(
    *,
    symbol: str = "NIFTY",
    expiry: str = "2026-09-11",
    spot: float | None = 24490.0,
    rows: list[OptionChainRow] | None = None,
    received: datetime | None = T0,
    source: str = "UPSTOX",
    mode: DataMode | None = DataMode.BROKER_SNAPSHOT,
) -> OptionChainObservation:
    if rows is None:
        rows = [
            OptionChainRow(strike=24500.0,
                           call=leg(150.0, oi=100000.0),
                           put=leg(80.0, oi=75000.0)),
            OptionChainRow(strike=24550.0,
                           call=leg(110.0, oi=90000.0),
                           put=leg(120.0, oi=60000.0)),
        ]
    return OptionChainObservation(
        symbol=symbol,
        expiry_date=expiry,
        underlying_spot_price=spot,
        chain=rows,
        market_timestamp=None,
        received_timestamp=received,
        source=source,
        data_mode=mode,
        contract_version=ContractVersion.v1_0_0,
    )


def market_observation() -> MarketObservation:
    return MarketObservation(
        instrument=instrument("NIFTY"),
        market_timestamp=MARKET,
        received_timestamp=T0,
        source="UPSTOX",
        data_mode=DataMode.BROKER_SNAPSHOT,
        provenance=provenance(),
        contract_version=ContractVersion.v1_0_0,
    )


# ===========================================================================
# Section 1 — Engine basics, determinism, no wall clock
# ===========================================================================


class TestEngineBasics:
    def test_perfect_quote_scores_100_excellent(self):
        from app.market_data.quality import MarketDataQualityEngine

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        assert result.quality_score == 100
        assert result.quality_state is QualityState.EXCELLENT
        assert result.issues == ()
        assert result.critical_failure is False

    def test_same_input_same_reference_is_identical(self):
        from app.market_data.quality import MarketDataQualityEngine

        engine = MarketDataQualityEngine()
        obs = quote()
        first = engine.evaluate(obs, reference_time=REF)
        second = engine.evaluate(obs, reference_time=REF)
        assert first == second  # frozen result — deterministic

    def test_evaluate_never_reads_wall_clock_without_reference(self):
        """reference_time=None → freshness is NOT_EVALUATED (no fabricated
        age) and the result is still identical across calls — no hidden
        datetime.now()."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityDimension,
        )

        engine = MarketDataQualityEngine()
        obs = quote()
        first = engine.evaluate(obs)
        second = engine.evaluate(obs)
        assert first == second
        assert first.evaluated_at is None
        fresh_dim = next(d for d in first.dimensions
                         if d.dimension is QualityDimension.FRESHNESS)
        assert fresh_dim.status == "NOT_EVALUATED"

    def test_result_metadata(self):
        from app.market_data.quality import MarketDataQualityEngine

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        assert result.evaluated_at == REF
        assert result.observation_type == "QuoteObservation"
        assert result.contract_version == ContractVersion.v1_0_0.value
        assert result.observation_time == MARKET  # market preferred

    def test_unsupported_observation_type_raises(self):
        from app.market_data.quality import MarketDataQualityEngine

        with pytest.raises(ValueError):
            MarketDataQualityEngine().evaluate({"not": "canonical"},
                                               reference_time=REF)

    def test_naive_reference_time_rejected(self):
        from app.market_data.quality import MarketDataQualityEngine

        with pytest.raises(ValueError):
            MarketDataQualityEngine().evaluate(
                quote(), reference_time=datetime(2026, 9, 3, 10, 0, 5)
            )


# ===========================================================================
# Section 2 — Freshness
# ===========================================================================


class TestFreshness:
    def test_fresh_observation_full_score(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityDimension,
        )

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        dim = next(d for d in result.dimensions
                   if d.dimension is QualityDimension.FRESHNESS)
        assert dim.score == 1.0
        assert dim.status == "EVALUATED"

    def test_boundary_age_equal_to_fresh_limit_is_fresh(self):
        """age == 60s (fresh limit) → still score 1.0 (inclusive)."""
        from app.market_data.quality import MarketDataQualityEngine

        market = REF - timedelta(seconds=60)
        obs = quote(market=market, received=REF)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 100

    def test_partial_decay_between_fresh_and_stale(self):
        """age 180s of (60, 300) → freshness 0.5 → composite 85 (GOOD)."""
        from app.market_data.quality import MarketDataQualityEngine

        market = REF - timedelta(seconds=180)
        obs = quote(market=market, received=REF)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 85
        assert result.quality_state is QualityState.GOOD

    def test_stale_observation_is_degraded_with_issue(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        market = REF - timedelta(seconds=600)
        obs = quote(market=market, received=REF)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 70
        assert result.quality_state is QualityState.DEGRADED
        assert any(i.code is QualityIssueCode.STALE_OBSERVATION
                   for i in result.issues)

    def test_future_timestamp_never_silently_valid(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        market = REF + timedelta(seconds=600)
        obs = quote(market=market, received=REF)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 70
        assert result.quality_state is QualityState.DEGRADED
        assert any(i.code is QualityIssueCode.FUTURE_TIMESTAMP
                   for i in result.issues)

    def test_market_timestamp_preferred_over_received(self):
        """Freshness uses the market/event timestamp when present; the
        received timestamp only when the market timestamp is absent."""
        from app.market_data.quality import MarketDataQualityEngine

        # Market 2s old (fresh); received 20 minutes old.
        market = REF - timedelta(seconds=2)
        received = REF - timedelta(seconds=1200)
        obs = quote(market=market, received=received)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 100

    def test_received_fallback_when_no_market_timestamp(self):
        """No market timestamp → freshness uses the received timestamp:
        age 120s → freshness 0.75 → composite 92.5 → 92 (EXCELLENT)."""
        from app.market_data.quality import MarketDataQualityEngine

        received = REF - timedelta(seconds=120)
        obs = quote(market=None, received=received)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 92
        assert result.quality_state is QualityState.EXCELLENT

    def test_no_timestamp_at_all_freshness_not_evaluated(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityDimension,
        )

        obs = quote(received=None, market=None)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        dim = next(d for d in result.dimensions
                   if d.dimension is QualityDimension.FRESHNESS)
        assert dim.status == "NOT_EVALUATED"


# ===========================================================================
# Section 3 — Completeness
# ===========================================================================


class TestCompleteness:
    def test_missing_source_is_error_not_excellent(self):
        """A quote without its source: completeness 3/4 → composite 94, but
        the ERROR issue prevents EXCELLENT (GOOD)."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(source=None)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 94
        assert result.quality_state is QualityState.GOOD
        assert any(i.code is QualityIssueCode.MISSING_REQUIRED_FIELD
                   and i.field == "source" for i in result.issues)

    def test_optional_missing_fields_do_not_fail_completeness(self):
        """OHLC/bid/ask/volume/OI are optional — a quote without them stays
        complete (no missing-required issue)."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(ltp=24500.0, source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 100
        assert not any(i.code is QualityIssueCode.MISSING_REQUIRED_FIELD
                       for i in result.issues)

    def test_empty_chain_is_critical_insufficient(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = chain_observation(rows=[])
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.critical_failure is True
        assert result.quality_state is QualityState.INSUFFICIENT
        assert any(i.code is QualityIssueCode.CHAIN_INCOMPLETE
                   and i.severity == "CRITICAL" for i in result.issues)

    def test_chain_without_spot_is_incomplete_but_not_critical(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = chain_observation(spot=None)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.critical_failure is False
        assert any(i.code is QualityIssueCode.MISSING_REQUIRED_FIELD
                   and i.field == "underlying_spot_price" for i in result.issues)

    def test_chain_row_without_legs_is_warning(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        rows = [
            OptionChainRow(strike=24500.0, call=leg(150.0), put=None),
            OptionChainRow(strike=24550.0, call=None, put=None),
        ]
        obs = chain_observation(rows=rows)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.CHAIN_INCOMPLETE
                   and i.severity == "WARNING" for i in result.issues)
        # Warnings do not prevent EXCELLENT.
        assert result.quality_state is QualityState.EXCELLENT


# ===========================================================================
# Section 4 — Validity
# ===========================================================================


class TestValidity:
    def test_negative_ltp_is_critical_invalid(self):
        """Invalid market data (negative price) forces INSUFFICIENT via the
        critical-failure rule regardless of the composite score."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(ltp=-24500.0)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.critical_failure is True
        assert result.quality_state is QualityState.INSUFFICIENT
        assert result.quality_score < 100
        assert any(i.code is QualityIssueCode.INVALID_PRICE
                   and i.severity == "CRITICAL" for i in result.issues)

    def test_negative_volume_and_oi_are_errors(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(
            ltp=100.0, volume=-5.0, oi=-10.0, source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_VOLUME
                   for i in result.issues)
        assert any(i.code is QualityIssueCode.INVALID_OI
                   for i in result.issues)
        assert result.critical_failure is False

    def test_invalid_chain_expiry_is_error(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = chain_observation(expiry="not-a-date")
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_EXPIRY
                   for i in result.issues)

    def test_invalid_chain_strike_is_error(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        rows = [
            OptionChainRow(strike=0.0, call=leg(150.0), put=leg(80.0)),
            OptionChainRow(strike=24550.0, call=leg(110.0), put=leg(120.0)),
        ]
        obs = chain_observation(rows=rows)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_STRIKE
                   for i in result.issues)

    def test_naive_timestamp_is_invalid(self):
        """A naive (timezone-less) timestamp cannot be compared — flagged as
        INVALID_TIMESTAMP rather than silently treated as UTC."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(received=datetime(2026, 9, 3, 10, 0, 0))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_TIMESTAMP
                   for i in result.issues)


# ===========================================================================
# Section 5 — Consistency
# ===========================================================================


class TestConsistency:
    def test_bid_above_ask_is_inconsistent(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(ltp=100.0, bid=105.0, ask=99.0,
                                           source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.BID_ASK_INCONSISTENT
                   for i in result.issues)

    def test_valid_bid_ask_no_issue(self):
        from app.market_data.quality import MarketDataQualityEngine

        obs = quote(price_quote=PriceQuote(ltp=100.0, bid=99.5, ask=100.5,
                                           source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.quality_score == 100

    def test_high_below_low_is_inconsistent(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(ltp=100.0, low=105.0, high=99.0,
                                           source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.OHLC_INCONSISTENT
                   for i in result.issues)

    def test_ltp_outside_ohlc_range_is_inconsistent(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(ltp=150.0, low=100.0, high=120.0,
                                           source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.OHLC_INCONSISTENT
                   for i in result.issues)

    def test_market_after_received_is_timestamp_order_warning(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        market = T0 + timedelta(seconds=30)
        obs = quote(market=market, received=T0)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.TIMESTAMP_ORDER
                   for i in result.issues)

    def test_chain_leg_consistency_checked(self):
        """Leg-level price quotes get the same bid/ask/OHLC consistency
        checks as single quotes."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        rows = [
            OptionChainRow(
                strike=24500.0,
                call=PriceQuote(ltp=150.0, bid=160.0, ask=140.0,
                                source="UPSTOX"),
                put=leg(80.0),
            ),
        ]
        obs = chain_observation(rows=rows)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.BID_ASK_INCONSISTENT
                   for i in result.issues)


# ===========================================================================
# Section 6 — Provenance
# ===========================================================================


class TestProvenance:
    def test_valid_provenance_full_score(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityDimension,
        )

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        dim = next(d for d in result.dimensions
                   if d.dimension is QualityDimension.PROVENANCE)
        assert dim.score == 1.0

    def test_missing_provenance_is_critical(self):
        """Day-9 rule: provenance is mandatory. A quote without provenance
        is INSUFFICIENT regardless of otherwise-perfect fields."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(include_provenance=False)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.critical_failure is True
        assert result.quality_state is QualityState.INSUFFICIENT
        assert any(i.code is QualityIssueCode.INVALID_PROVENANCE
                   and i.severity == "CRITICAL" for i in result.issues)

    def test_partial_provenance_reports_each_missing_part(self):
        """Source present but normalization/collection parts missing →
        one ERROR per missing part; provenance score is the satisfied
        fraction (3/5)."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(prov=provenance(collection_mode="", normalization_version="",
                                    received_at=None))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        codes = [i.code for i in result.issues
                 if i.code is QualityIssueCode.INVALID_PROVENANCE]
        assert len(codes) >= 3
        assert result.critical_failure is False

    def test_missing_transformation_id_is_not_an_issue(self):
        """transformation_id is optional in the Day-9 Provenance contract —
        its absence is not a quality issue (required vs optional)."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(prov=provenance(transformation_id=None))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert not any(i.code is QualityIssueCode.INVALID_PROVENANCE
                       for i in result.issues)
        assert result.quality_score == 100

    def test_provenance_mode_mismatch_is_error(self):
        """Provenance collection_mode contradicting the observation data_mode
        is incoherent provenance."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(prov=provenance(collection_mode=DataMode.BROKER_LIVE.value))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_PROVENANCE
                   for i in result.issues)

    def test_chain_flattened_provenance_missing_source_is_error(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = chain_observation(source=None)
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.INVALID_PROVENANCE
                   for i in result.issues)


# ===========================================================================
# Section 7 — Anomaly & continuity
# ===========================================================================


class TestAnomaly:
    def test_extreme_price_is_anomalous(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(ltp=1_000_000_000.0)  # default max_abs_price 10_000_000
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert any(i.code is QualityIssueCode.ANOMALOUS_VALUE
                   for i in result.issues)
        assert result.quality_score == 95  # anomaly weight .05
        assert result.quality_state is QualityState.GOOD  # ERROR blocks EXCELLENT

    def test_sane_values_no_anomaly(self):
        from app.market_data.quality import MarketDataQualityEngine

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        assert result.quality_score == 100


class TestContinuity:
    def test_continuity_not_evaluated_without_previous(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityDimension,
        )

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        dim = next(d for d in result.dimensions
                   if d.dimension is QualityDimension.CONTINUITY)
        assert dim.status == "NOT_EVALUATED"

    def test_sudden_jump_vs_previous_is_continuity_break(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        engine = MarketDataQualityEngine()
        previous = quote(ltp=100.0, market=MARKET - timedelta(minutes=5))
        current = quote(ltp=300.0)  # 200% jump > default 100% max
        result = engine.evaluate(current, reference_time=REF, previous=previous)
        assert any(i.code is QualityIssueCode.CONTINUITY_BREAK
                   for i in result.issues)
        assert result.quality_score == 95  # continuity weight .05 over 1.05

    def test_small_move_vs_previous_passes(self):
        from app.market_data.quality import MarketDataQualityEngine

        engine = MarketDataQualityEngine()
        previous = quote(ltp=100.0)
        current = quote(ltp=105.0)
        result = engine.evaluate(current, reference_time=REF, previous=previous)
        assert not any(True for i in result.issues
                       if i.code.value == "CONTINUITY_BREAK")
        assert result.quality_score == 100

    def test_previous_must_match_instrument(self):
        from app.market_data.quality import MarketDataQualityEngine

        engine = MarketDataQualityEngine()
        previous = quote(ltp=100.0, symbol="BANKNIFTY")
        current = quote(ltp=105.0, symbol="NIFTY")
        with pytest.raises(ValueError):
            engine.evaluate(current, reference_time=REF, previous=previous)


# ===========================================================================
# Section 8 — Classification
# ===========================================================================


class TestClassification:
    def test_classify_boundaries(self):
        from app.market_data.quality import classify

        assert classify(100, critical=False) is QualityState.EXCELLENT
        assert classify(90, critical=False) is QualityState.EXCELLENT
        assert classify(89, critical=False) is QualityState.GOOD
        assert classify(75, critical=False) is QualityState.GOOD
        assert classify(74, critical=False) is QualityState.DEGRADED
        assert classify(60, critical=False) is QualityState.DEGRADED
        assert classify(59, critical=False) is QualityState.INSUFFICIENT
        # Critical failure forces INSUFFICIENT regardless of score.
        assert classify(100, critical=True) is QualityState.INSUFFICIENT
        assert classify(90, critical=True) is QualityState.INSUFFICIENT

    def test_engine_state_follows_classify_plus_error_rule(self):
        """The engine state equals classify(score, critical), except that an
        ERROR-severity issue additionally prevents EXCELLENT (→ GOOD)."""
        from app.market_data.quality import (
            MarketDataQualityEngine,
            classify,
        )

        for obs in (
            quote(),
            quote(source=None),
            quote(market=REF - timedelta(seconds=600)),
            quote(ltp=-1.0),
            quote(include_provenance=False),
        ):
            result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
            base = classify(result.quality_score, result.critical_failure)
            has_error = any(i.severity == "ERROR" for i in result.issues)
            expected = QualityState.GOOD if (base is QualityState.EXCELLENT and has_error) else base
            assert result.quality_state is expected


# ===========================================================================
# Section 9 — Property / boundary invariants
# ===========================================================================


class TestInvariants:
    @pytest.mark.parametrize(
        "obs",
        [
            quote(),
            quote(ltp=-5.0),
            quote(source=None),
            quote(prov=None),
            quote(ltp=1e9),
            quote(market=REF + timedelta(minutes=5)),
            quote(market=REF - timedelta(hours=2)),
            chain_observation(),
            chain_observation(rows=[]),
            chain_observation(spot=None, expiry="bad"),
            market_observation(),
        ],
    )
    def test_score_always_bounded(self, obs):
        from app.market_data.quality import MarketDataQualityEngine

        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert 0 <= result.quality_score <= 100
        assert isinstance(result.quality_state, QualityState)

    def test_critical_invalidities_never_excellent(self):
        from app.market_data.quality import MarketDataQualityEngine

        for obs in (
            quote(ltp=-1.0),               # invalid market data
            quote(include_provenance=False),  # missing provenance
            chain_observation(rows=[]),    # empty chain
        ):
            result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
            assert result.quality_state is QualityState.INSUFFICIENT

    def test_error_issues_never_excellent(self):
        """An ERROR-severity issue (e.g. stale, missing source) must not sit
        inside an EXCELLENT result."""
        from app.market_data.quality import MarketDataQualityEngine

        for obs in (
            quote(source=None),
            quote(market=REF - timedelta(seconds=600)),
        ):
            result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
            assert result.quality_state is not QualityState.EXCELLENT


# ===========================================================================
# Section 10 — No leakage
# ===========================================================================


class TestNoLeakage:
    def test_result_never_leaks_credentials_or_broker_payloads(self):
        from app.market_data.quality import MarketDataQualityEngine

        result = MarketDataQualityEngine().evaluate(quote(), reference_time=REF)
        text = str(result) + str(asdict(result))
        for forbidden in (
            "access_token", "api_secret", "client_secret", "Authorization",
            "bearer", "last_price", "instrument_token", "depth", "ohlc",
            "call_options", "strike_price",
        ):
            assert forbidden not in text, f"'{forbidden}' leaked from quality result"

    def test_issues_are_structured(self):
        from app.market_data.quality import (
            MarketDataQualityEngine,
            QualityIssueCode,
        )

        obs = quote(price_quote=PriceQuote(ltp=-5.0, bid=10.0, ask=9.0,
                                           source="UPSTOX"))
        result = MarketDataQualityEngine().evaluate(obs, reference_time=REF)
        assert result.issues
        for issue in result.issues:
            assert issue.dimension
            assert issue.code in QualityIssueCode
            assert issue.severity in ("CRITICAL", "ERROR", "WARNING")
            assert issue.message


# ===========================================================================
# Section 11 — Configuration
# ===========================================================================


class TestConfiguration:
    def test_custom_thresholds_change_freshness(self):
        from app.market_data.quality import (
            MarketDataQualityConfig,
            MarketDataQualityEngine,
        )

        config = MarketDataQualityConfig(fresh_seconds=5.0, stale_seconds=30.0)
        # age 35s: fresh in the default config, stale under the custom one.
        market = REF - timedelta(seconds=35)
        obs = quote(market=market, received=REF)
        result = MarketDataQualityEngine(config).evaluate(obs,
                                                          reference_time=REF)
        assert any(i.code.value == "STALE_OBSERVATION" for i in result.issues)

    def test_invalid_config_rejected(self):
        from app.market_data.quality import MarketDataQualityConfig

        with pytest.raises(ValueError):
            MarketDataQualityConfig(fresh_seconds=-1.0)
        with pytest.raises(ValueError):
            MarketDataQualityConfig(fresh_seconds=100.0, stale_seconds=50.0)
