"""Day 20 — Positioning Intelligence + Flow/Divergence Intelligence tests
(RED-phase contract).

Proves the first two Day-19-contract engines:

    Raw strike-level observations (OI / ΔOI / volume / price context)
        -> derived metrics (totals, ratios, asymmetry, concentration)
        -> deterministic classification (long/short buildup, covering,
           unwinding)  [positioning]
        -> flow/divergence derived series (CE-PE net flow, imbalance,
           delta/vega divergence flags)                  [flow]
        -> Day-19 IntelligenceResult (direction / signal_strength /
           confidence / evidence / quality / provenance / versions)

Rules locked by these tests
---------------------------
1. The Day-19 IntelligenceResult is the authoritative output envelope; the
   Day-19 contract module is NOT modified by this day.
2. Missing values stay None — never coerced to zero; a measured zero stays a
   legitimate zero; missing OI/price/delta/vega yield structured
   PARTIAL/UNAVAILABLE results, never fabricated reads.
3. signal_strength != confidence != data quality; the exact supplied Day-12
   QualityResult instance and Day-9 Provenance are preserved verbatim.
4. Evidence supports every directional interpretation; conflicting evidence is
   MIXED with the Day-19 CONFLICTING_DIRECTION issue — never forced into
   bullish/bearish; no static-level rules (no "high CE OI = resistance").
5. Chain classification is change-based only: LONG_BUILDUP (net ΔOI>0,
   price↑), SHORT_BUILDUP (net ΔOI>0, price↓), SHORT_COVERING (net ΔOI<0,
   price↑), LONG_UNWINDING (net ΔOI<0, price↓); balanced/no-price-change ⇒
   neutral; missing ⇒ unknown.
6. Deterministic, repeatable, pure: no wall clock, no randomness, no
   DB/network/filesystem/broker imports in either engine module (AST-guarded
   here because the Day-14 guard globs only app/quant).
7. Golden expectations are independent hand arithmetic — never produced by
   calling the engine under test.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    IntelligenceDirection,
    IntelligenceResult,
    IntelligenceStatus,
    IntelligenceIssueCode,
)
from app.intelligence.positioning import (
    CALCULATION_ID as POSITIONING_CALCULATION_ID,
    MODEL_VERSION as POSITIONING_MODEL_VERSION,
    CALCULATION_VERSION as POSITIONING_CALCULATION_VERSION,
    STRENGTH_REFERENCE_OI,
    PositioningClassification,
    PositioningInput,
    StrikePositioning,
    classify_chain,
    compute_metrics,
    evaluate_positioning,
)
from app.intelligence.flow import (
    CALCULATION_ID as FLOW_CALCULATION_ID,
    MODEL_VERSION as FLOW_MODEL_VERSION,
    CALCULATION_VERSION as FLOW_CALCULATION_VERSION,
    FLOW_REFERENCE,
    FlowInput,
    PriceFlowRelation,
    VegaPattern,
    compute_flow_metrics,
    evaluate_flow,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()

# ---------------------------------------------------------------------------
# Golden NIFTY-like chain (independent hand arithmetic)
#   strike | call_oi | put_oi | call_d | put_d | call_vol | put_vol
# ---------------------------------------------------------------------------
# 24000: 50_000 18_000  +1_200   +300    2_400     900
# 24100: 62_000 22_000  +900     -400    1_800     1_100
# 24200: 71_000 26_000  -600     +700    2_200     2_000
# 24300: 45_000 34_000  +400     -250    1_500     1_600
# 24400: 30_000 41_000  -200     +150      900     2_300
#
# totals:  call_oi 258_000 | put_oi 141_000 | pcr_oi 141/258 = 0.5465116...
#          call_d 1_700    | put_d 500       | net 2_200 | asym +1_200
#          call_vol 8_800  | put_vol 7_900   | pcr_vol 7_900/8_800 = 0.8977272..
#          max_call_oi strike 24200 | max_put_oi strike 24400 |
#          max |dOI| strike 24000 (1_200)
GOLDEN_CALL_OI = 258_000.0
GOLDEN_PUT_OI = 141_000.0
GOLDEN_PCR_OI = 141_000.0 / 258_000.0
GOLDEN_CALL_D = 1_700.0
GOLDEN_PUT_D = 500.0
GOLDEN_NET_D = 2_200.0
GOLDEN_ASYM = 1_200.0
GOLDEN_CALL_VOL = 8_800.0
GOLDEN_PUT_VOL = 7_900.0
GOLDEN_PCR_VOL = 7_900.0 / 8_800.0


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX_SNAPSHOT_NORMALIZED",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=_REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quality(state: QualityState = QualityState.EXCELLENT) -> QualityResult:
    return QualityResult(
        quality_score=95 if state is QualityState.EXCELLENT else 70,
        quality_state=state,
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=_REF,
        observation_time=_REF,
        observation_type="QUOTE",
        contract_version="1.0.0",
        reference_time=_REF,
    )


def _row(strike: float, call_oi=0.0, put_oi=0.0, call_d=None, put_d=None,
         call_vol=None, put_vol=None) -> StrikePositioning:
    return StrikePositioning(
        strike=strike,
        call_oi=call_oi,
        put_oi=put_oi,
        call_oi_change=call_d,
        put_oi_change=put_d,
        call_volume=call_vol,
        put_volume=put_vol,
    )


def _golden_rows():
    return (
        _row(24000.0, 50_000, 18_000, 1_200, 300, 2_400, 900),
        _row(24100.0, 62_000, 22_000, 900, -400, 1_800, 1_100),
        _row(24200.0, 71_000, 26_000, -600, 700, 2_200, 2_000),
        _row(24300.0, 45_000, 34_000, 400, -250, 1_500, 1_600),
        _row(24400.0, 30_000, 41_000, -200, 150, 900, 2_300),
    )


def _pos_input(*, rows=None, spot=24300.0, spot_change=100.0,
               quality=_UNSET, prov=_UNSET, expiry="2026-09-24") -> PositioningInput:
    return PositioningInput(
        underlying="NIFTY",
        expiry=expiry,
        spot=spot,
        spot_change=spot_change,
        rows=rows if rows is not None else _golden_rows(),
        reference_timestamp=_REF,
        window_seconds=86400.0,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


def _flow_input(*, spot_change=100.0, ce_d=1_700.0, pe_d=500.0,
                ce_vol=8_800.0, pe_vol=7_900.0, call_delta=420.0,
                put_delta=-120.0, vega=55.0, quality=_UNSET,
                prov=_UNSET) -> FlowInput:
    return FlowInput(
        underlying="NIFTY",
        expiry="2026-09-24",
        spot=24300.0,
        spot_change=spot_change,
        net_ce_oi_change=ce_d,
        net_pe_oi_change=pe_d,
        ce_volume=ce_vol,
        pe_volume=pe_vol,
        call_delta_shift=call_delta,
        put_delta_shift=put_delta,
        vega_shift_net=vega,
        reference_timestamp=_REF,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


# ---------------------------------------------------------------------------
# 1. Input contract validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_positioning_input(self):
        inp = _pos_input()
        assert inp.underlying == "NIFTY"
        assert len(inp.rows) == 5

    def test_negative_oi_rejected(self):
        with pytest.raises(ValueError):
            _row(100.0, call_oi=-1.0)
        with pytest.raises(ValueError):
            _row(100.0, put_vol=-5.0)

    def test_non_finite_oi_rejected(self):
        with pytest.raises(ValueError):
            _row(100.0, call_oi=float("nan"))

    def test_non_finite_delta_oi_rejected(self):
        with pytest.raises(ValueError):
            _row(100.0, call_d=float("inf"))

    def test_non_positive_strike_rejected(self):
        with pytest.raises(ValueError):
            _row(0.0)
        with pytest.raises(ValueError):
            _row(-10.0)

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        rows = (_row(100.0),)
        with pytest.raises(ValueError):
            PositioningInput(underlying="NIFTY", expiry="2026-09-24", spot=100.0,
                             spot_change=1.0, rows=rows,
                             reference_timestamp=naive, window_seconds=1.0,
                             provenance=_prov(), quality=_quality())
        with pytest.raises(ValueError):
            FlowInput(underlying="NIFTY", expiry="2026-09-24", spot=100.0,
                      spot_change=1.0, net_ce_oi_change=1.0, net_pe_oi_change=1.0,
                      ce_volume=None, pe_volume=None, call_delta_shift=None,
                      put_delta_shift=None, vega_shift_net=None,
                      reference_timestamp=naive, provenance=_prov(),
                      quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            _pos_input(quality=QualityState.EXCELLENT)
        with pytest.raises(ValueError):
            _flow_input(quality=QualityState.EXCELLENT)

    def test_provenance_required_and_type_checked(self):
        with pytest.raises(ValueError):
            PositioningInput(underlying="NIFTY", expiry="2026-09-24",
                             spot=24300.0, spot_change=100.0, rows=_golden_rows(),
                             reference_timestamp=_REF, window_seconds=1.0,
                             provenance=None, quality=_quality())
        with pytest.raises(ValueError):
            FlowInput(underlying="NIFTY", expiry="2026-09-24", spot=24300.0,
                      spot_change=100.0, net_ce_oi_change=1.0, net_pe_oi_change=1.0,
                      ce_volume=None, pe_volume=None, call_delta_shift=None,
                      put_delta_shift=None, vega_shift_net=None,
                      reference_timestamp=_REF, provenance=None, quality=_quality())
        with pytest.raises(ValueError):
            _pos_input(prov="not-a-provenance")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            _flow_input(prov="not-a-provenance")  # type: ignore[arg-type]

    def test_engine_constants_explicit(self):
        assert POSITIONING_CALCULATION_ID == "intelligence.positioning.v1"
        assert POSITIONING_MODEL_VERSION == "1.0.0"
        assert POSITIONING_CALCULATION_VERSION == "1.0.0"
        assert FLOW_CALCULATION_ID == "intelligence.flow_divergence.v1"
        assert FLOW_MODEL_VERSION == "1.0.0"
        assert FLOW_CALCULATION_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# 2. Positioning metrics (golden arithmetic)
# ---------------------------------------------------------------------------


class TestPositioningMetrics:
    def test_golden_totals(self):
        m = compute_metrics(_pos_input())
        assert m.total_call_oi == pytest.approx(GOLDEN_CALL_OI, rel=1e-9)
        assert m.total_put_oi == pytest.approx(GOLDEN_PUT_OI, rel=1e-9)

    def test_golden_oi_ratio(self):
        m = compute_metrics(_pos_input())
        assert m.put_call_oi_ratio == pytest.approx(GOLDEN_PCR_OI, rel=1e-9)

    def test_golden_oi_changes(self):
        m = compute_metrics(_pos_input())
        assert m.total_call_oi_change == pytest.approx(GOLDEN_CALL_D, rel=1e-9)
        assert m.total_put_oi_change == pytest.approx(GOLDEN_PUT_D, rel=1e-9)
        assert m.net_chain_oi_change == pytest.approx(GOLDEN_NET_D, rel=1e-9)
        assert m.ce_pe_oi_change_asymmetry == pytest.approx(GOLDEN_ASYM, rel=1e-9)

    def test_golden_volumes_and_ratio(self):
        m = compute_metrics(_pos_input())
        assert m.total_call_volume == pytest.approx(GOLDEN_CALL_VOL, rel=1e-9)
        assert m.total_put_volume == pytest.approx(GOLDEN_PUT_VOL, rel=1e-9)
        assert m.put_call_volume_ratio == pytest.approx(GOLDEN_PCR_VOL, rel=1e-9)

    def test_golden_concentration_facts(self):
        m = compute_metrics(_pos_input())
        assert m.max_call_oi_strike == 24200.0
        assert m.max_put_oi_strike == 24400.0
        assert m.max_abs_oi_change_strike == 24000.0

    def test_zero_oi_is_measured_not_missing(self):
        rows = (_row(24000.0, call_oi=0.0, put_oi=0.0),)
        m = compute_metrics(_pos_input(rows=rows))
        assert m.total_call_oi == 0.0
        assert m.total_put_oi == 0.0
        assert m.call_oi_side_present is True

    def test_missing_side_stays_none(self):
        # rows carry levels for call only on the put side
        rows = (_row(24000.0, call_oi=100.0, put_oi=None,
                     call_d=10.0, put_d=None),)
        m = compute_metrics(_pos_input(rows=rows))
        assert m.total_call_oi == 100.0
        assert m.total_put_oi is None
        assert m.put_call_oi_ratio is None
        assert m.net_chain_oi_change is None   # put ΔOI missing
        assert m.ce_pe_oi_change_asymmetry is None

    def test_no_rows_metrics_all_none(self):
        m = compute_metrics(_pos_input(rows=()))
        assert m.total_call_oi is None
        assert m.total_put_oi is None
        assert m.net_chain_oi_change is None

    def test_put_call_ratio_zero_denominator_is_none(self):
        rows = (_row(24000.0, call_oi=0.0, put_oi=50.0),)
        m = compute_metrics(_pos_input(rows=rows))
        assert m.put_call_oi_ratio is None  # measured zero denominator

    def test_volume_imbalance_zero_denominator_is_none(self):
        rows = (_row(24000.0, call_vol=0.0, put_vol=0.0),)
        m = compute_metrics(_pos_input(rows=rows))
        assert m.put_call_volume_ratio is None

    def test_extreme_finite_oi_finite(self):
        rows = (_row(24000.0, call_oi=1e15, put_oi=1e15, call_d=1e12,
                     put_d=1e12, call_vol=1e13, put_vol=1e13),)
        m = compute_metrics(_pos_input(rows=rows))
        assert m.total_call_oi == 1e15
        assert m.net_chain_oi_change == 2e12
        assert m.put_call_oi_ratio == 1.0


# ---------------------------------------------------------------------------
# 3. Chain classification (change-based only)
# ---------------------------------------------------------------------------


class TestChainClassification:
    @pytest.mark.parametrize("net,price,expected", [
        (100.0, 10.0, PositioningClassification.LONG_BUILDUP),
        (100.0, -10.0, PositioningClassification.SHORT_BUILDUP),
        (-100.0, 10.0, PositioningClassification.SHORT_COVERING),
        (-100.0, -10.0, PositioningClassification.LONG_UNWINDING),
    ])
    def test_sign_table(self, net, price, expected):
        assert classify_chain(net, price) is expected

    def test_balanced_net_is_unclassified(self):
        assert classify_chain(0.0, 10.0) is PositioningClassification.UNCLASSIFIED

    def test_zero_price_change_is_unclassified(self):
        assert classify_chain(100.0, 0.0) is PositioningClassification.UNCLASSIFIED

    def test_missing_inputs_are_unclassified(self):
        assert classify_chain(None, 10.0) is PositioningClassification.UNCLASSIFIED
        assert classify_chain(100.0, None) is PositioningClassification.UNCLASSIFIED
        assert classify_chain(None, None) is PositioningClassification.UNCLASSIFIED


# ---------------------------------------------------------------------------
# 4. Positioning interpretation
# ---------------------------------------------------------------------------


class TestEvaluatePositioning:
    def test_golden_chain_is_long_buildup_success(self):
        r = evaluate_positioning(_pos_input())
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.calculation_id == POSITIONING_CALCULATION_ID
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(2_200.0 / STRENGTH_REFERENCE_OI)
        assert r.confidence == pytest.approx(0.9)
        assert r.observation.metric_name == "net_chain_oi_change"
        assert r.observation.value == pytest.approx(GOLDEN_NET_D)
        assert r.issues == ()
        assert r.model_version == POSITIONING_MODEL_VERSION
        assert r.calculation_version == POSITIONING_CALCULATION_VERSION

    def test_evidence_supports_interpretation(self):
        r = evaluate_positioning(_pos_input())
        ev = {e.source_reference_id: e for e in r.evidence}
        # every evidence value is finite (SUCCESS rule)
        assert all(e.value is not None for e in r.evidence)
        # chain aggregates + classification inputs are cited
        assert "pos:NIFTY:2026-09-24:total_call_oi" in ev
        assert "pos:NIFTY:2026-09-24:total_put_oi" in ev
        assert "pos:NIFTY:2026-09-24:net_chain_oi_change" in ev
        assert "pos:NIFTY:2026-09-24:spot_change" in ev
        assert ev["pos:NIFTY:2026-09-24:total_call_oi"].value == pytest.approx(258_000.0)

    def test_short_buildup_maps_bearish(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=50.0, put_d=50.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=-100.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BEARISH

    def test_short_covering_maps_bullish(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=-50.0, put_d=-50.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=100.0))
        assert r.direction is IntelligenceDirection.BULLISH

    def test_long_unwinding_maps_bearish(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=-50.0, put_d=-50.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=-100.0))
        assert r.direction is IntelligenceDirection.BEARISH

    def test_balanced_net_is_neutral_success(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=0.0, put_d=0.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=100.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.signal_strength == 0.0

    def test_no_price_change_is_neutral(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=50.0, put_d=50.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=0.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.NEUTRAL

    def test_missing_price_context_is_partial_unknown(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=50.0, put_d=50.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is None
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   for i in r.issues)

    def test_missing_oi_change_leg_is_partial(self):
        rows = (_row(24200.0, call_oi=100.0, put_oi=100.0, call_d=50.0, put_d=None),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=100.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   for i in r.issues)

    def test_empty_rows_unavailable(self):
        r = evaluate_positioning(_pos_input(rows=()))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert r.direction is None
        assert r.observation is None

    def test_conflicting_legs_mixed_not_forced(self):
        # call ΔOI +500 (bullish flow) vs put ΔOI -400; price UP:
        # net = +100 (small) — the net is bullish but legs oppose; we assert
        # the engine refuses to claim a confident side when legs conflict.
        rows = (_row(24200.0, call_oi=1_000.0, put_oi=1_000.0,
                     call_d=500.0, put_d=-400.0),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=100.0))
        assert r.direction is IntelligenceDirection.MIXED
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_missing_quality_prevents_success(self):
        r = evaluate_positioning(_pos_input(quality=None))
        assert r.status is not IntelligenceStatus.SUCCESS
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY for i in r.issues)
        assert r.quality is None

    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_positioning(_pos_input(quality=q))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        r = evaluate_positioning(_pos_input(prov=prov))
        assert r.provenance == prov
        assert r.provenance.source == "UPSTOX_SNAPSHOT_NORMALIZED"

    def test_repeatable(self):
        a = evaluate_positioning(_pos_input())
        b = evaluate_positioning(_pos_input())
        assert a == b

    def test_serialization_round_trip(self):
        r = evaluate_positioning(_pos_input())
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_strength_clamps_at_one(self):
        rows = (_row(24200.0, call_oi=1e9, put_oi=1e9, call_d=5e6, put_d=5e6),)
        r = evaluate_positioning(_pos_input(rows=rows, spot_change=100.0))
        assert r.signal_strength == 1.0


# ---------------------------------------------------------------------------
# 5. Flow / divergence derived series
# ---------------------------------------------------------------------------


class TestFlowDerived:
    def test_golden_net_ce_pe_flow(self):
        m = compute_flow_metrics(_flow_input())
        assert m.net_ce_pe_flow == pytest.approx(1_200.0, rel=1e-9)

    def test_golden_directional_imbalance(self):
        m = compute_flow_metrics(_flow_input())
        assert m.directional_imbalance == pytest.approx(900.0 / 16_700.0, rel=1e-9)

    def test_golden_net_delta_shift(self):
        m = compute_flow_metrics(_flow_input())
        assert m.net_delta_shift == pytest.approx(300.0, rel=1e-9)

    def test_balanced_flows(self):
        m = compute_flow_metrics(_flow_input(ce_d=100.0, pe_d=100.0,
                                             ce_vol=5_000.0, pe_vol=5_000.0))
        assert m.net_ce_pe_flow == 0.0
        assert m.directional_imbalance == 0.0

    def test_zero_volume_measured(self):
        m = compute_flow_metrics(_flow_input(ce_vol=0.0, pe_vol=7_900.0))
        assert m.directional_imbalance == pytest.approx(-1.0, rel=1e-9)

    def test_missing_series_are_none(self):
        m = compute_flow_metrics(_flow_input(pe_d=None))
        assert m.net_ce_pe_flow is None
        m2 = compute_flow_metrics(_flow_input(ce_vol=None, pe_vol=None))
        assert m2.directional_imbalance is None
        m3 = compute_flow_metrics(_flow_input(call_delta=None, put_delta=None))
        assert m3.net_delta_shift is None

    def test_missing_flow_none_not_zero(self):
        m = compute_flow_metrics(_flow_input(pe_d=None))
        assert m.net_ce_pe_flow is None
        assert m.net_ce_pe_flow != 0.0

    @pytest.mark.parametrize("price,flow,expected", [
        (100.0, 100.0, PriceFlowRelation.CONFIRM),
        (100.0, -100.0, PriceFlowRelation.DIVERGE),
        (-100.0, -100.0, PriceFlowRelation.CONFIRM),
        (0.0, 100.0, PriceFlowRelation.NO_SIGNAL),
        (100.0, 0.0, PriceFlowRelation.NO_SIGNAL),
    ])
    def test_price_flow_relation(self, price, flow, expected):
        m = compute_flow_metrics(_flow_input(spot_change=price, ce_d=flow, pe_d=0.0))
        assert m.price_flow_relation is expected

    @pytest.mark.parametrize("price,delta,expected", [
        (100.0, 50.0, PriceFlowRelation.CONFIRM),
        (100.0, -50.0, PriceFlowRelation.DIVERGE),
        (-100.0, -50.0, PriceFlowRelation.CONFIRM),
        (0.0, 50.0, PriceFlowRelation.NO_SIGNAL),
    ])
    def test_delta_divergence(self, price, delta, expected):
        m = compute_flow_metrics(_flow_input(spot_change=price,
                                             call_delta=delta, put_delta=0.0))
        assert m.delta_divergence is expected

    @pytest.mark.parametrize("price,vega,expected", [
        (100.0, 50.0, VegaPattern.VOL_DEMAND_WITH_PRICE),
        (-100.0, 50.0, VegaPattern.VOL_DEMAND_AGAINST_PRICE),
        (-100.0, -50.0, VegaPattern.VOL_DEMAND_WITH_PRICE),
        (0.0, 50.0, VegaPattern.NO_SIGNAL),
        (100.0, 0.0, VegaPattern.NO_SIGNAL),
    ])
    def test_vega_patterns(self, price, vega, expected):
        m = compute_flow_metrics(_flow_input(spot_change=price, vega=vega))
        assert m.vega_pattern is expected

    def test_delta_divergence_missing_is_none(self):
        m = compute_flow_metrics(_flow_input(call_delta=None, put_delta=None))
        assert m.delta_divergence is None


# ---------------------------------------------------------------------------
# 6. Flow interpretation
# ---------------------------------------------------------------------------


class TestEvaluateFlow:
    def test_golden_confirm_bullish_success(self):
        r = evaluate_flow(_flow_input())
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.calculation_id == FLOW_CALCULATION_ID
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(300.0 / FLOW_REFERENCE)
        assert r.confidence == pytest.approx(0.9)
        assert r.observation.metric_name == "net_delta_shift"
        assert r.observation.value == pytest.approx(300.0)
        assert r.issues == ()
        assert r.model_version == FLOW_MODEL_VERSION
        assert r.calculation_version == FLOW_CALCULATION_VERSION

    def test_bearish_confirm(self):
        r = evaluate_flow(_flow_input(spot_change=-100.0, call_delta=-200.0,
                                      put_delta=-80.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BEARISH

    def test_divergence_is_mixed_not_forced(self):
        # price up but net delta shift negative -> conflicting evidence
        r = evaluate_flow(_flow_input(spot_change=100.0, call_delta=-200.0,
                                      put_delta=-80.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_flow_fallback_when_delta_missing(self):
        # no greek shift inputs -> primary series falls back to CE-PE net flow
        r = evaluate_flow(_flow_input(call_delta=None, put_delta=None))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BULLISH  # flow +1200, price up
        assert r.observation.metric_name == "net_ce_pe_flow"

    def test_delta_and_flow_missing_partial(self):
        r = evaluate_flow(_flow_input(ce_d=None, pe_d=None,
                                      call_delta=None, put_delta=None))
        assert r.status is not IntelligenceStatus.SUCCESS
        assert r.direction is None

    def test_evidence_cites_series(self):
        r = evaluate_flow(_flow_input())
        ev = {e.source_reference_id: e for e in r.evidence}
        assert "flow:NIFTY:2026-09-24:net_ce_pe_flow" in ev
        assert "flow:NIFTY:2026-09-24:net_delta_shift" in ev
        assert "flow:NIFTY:2026-09-24:spot_change" in ev
        assert ev["flow:NIFTY:2026-09-24:net_ce_pe_flow"].value == pytest.approx(1_200.0)

    def test_missing_quality_prevents_success(self):
        r = evaluate_flow(_flow_input(quality=None))
        assert r.status is not IntelligenceStatus.SUCCESS
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY for i in r.issues)

    def test_exact_quality_and_provenance_preserved(self):
        q = _quality(QualityState.DEGRADED)
        prov = _prov()
        r = evaluate_flow(_flow_input(quality=q, prov=prov))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.quality is q
        assert r.provenance == prov

    def test_repeatable_and_round_trip(self):
        a = evaluate_flow(_flow_input())
        b = evaluate_flow(_flow_input())
        assert a == b
        assert IntelligenceResult.from_dict(a.to_dict()) == a

    def test_extreme_finite_values_finite(self):
        r = evaluate_flow(_flow_input(ce_d=1e12, pe_d=-1e12, ce_vol=1e13,
                                      pe_vol=1e13, call_delta=5e11,
                                      put_delta=-1e11))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.signal_strength == 1.0  # clamped


# ---------------------------------------------------------------------------
# 7. Separation & purity (module-level static)
# ---------------------------------------------------------------------------


class TestSeparationAndPurity:
    _MODULES = [
        pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "positioning.py",
        pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "flow.py",
    ]

    def test_no_clock_io_or_broker_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi"}
        for path in self._MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"now", "utcnow", "today", "time", "sleep"}
                if isinstance(node, ast.Import):
                    for a in node.names:
                        assert a.name.split(".")[0] not in forbidden
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert not module.startswith("app.brokers")
                    assert not module.startswith("app.services")
                    assert not module.startswith("app.routers")

    def test_strength_confidence_quality_separate_fields(self):
        r = evaluate_positioning(_pos_input())
        assert isinstance(r.signal_strength, float)
        assert isinstance(r.confidence, float)
        assert isinstance(r.quality, QualityResult)
        assert r.signal_strength != r.confidence
        assert r.confidence == pytest.approx(0.9)

    def test_no_secret_strings_in_outputs(self):
        for r in (evaluate_positioning(_pos_input()), evaluate_flow(_flow_input())):
            s = str(r)
            assert "sk_live" not in s
            assert "access_token" not in s
            assert "authorization" not in s

    def test_evidence_supports_every_direction(self):
        # bullish read must carry its evidence; no unconditional static claim
        r = evaluate_positioning(_pos_input())
        assert r.evidence
        labels = {e.source_reference_id.split(":")[-1] for e in r.evidence}
        assert "classification_inputs" in labels or "net_chain_oi_change" in labels
