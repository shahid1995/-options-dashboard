"""Day 25 — Trap Detection Intelligence tests (RED-phase contract).

Proves the deterministic, broker-neutral trap-candidate engine on the
Day-19 Intelligence Contract, consuming only typed evidence available
through the existing Days 20-24 engines:

    price attempt + family directional reads (Days 20-23)
        -> opposing / agreeing evidence-family evaluation
        -> trap-candidate classification (BULL/BEAR_TRAP_CANDIDATE,
           FAILED_BREAKOUT/BREAKDOWN, FLOW_PRICE_TRAP, NO_TRAP)
        -> Day-19 IntelligenceResult

Rules locked by these tests
---------------------------
1. A trap is a CANDIDATE, never certainty: multi-factor conflict
   (price attempt + >=1 independent opposing family) is required; a
   single observation (high OI / volume / divergence / level) is never
   a trap.
2. Evidence is evaluated at the family level (PRICE / POSITIONING /
   FLOW / LEVEL / INSTITUTIONAL_LIKE / REGIME) — correlated raw fields
   derived from the same measurement are never independent
   confirmations.
3. Day-21 semantics: APPROACHING != CONFIRMED_INTERACTION (approach
   never creates a trap); only kind-aware CONFLICTED_INTERACTION
   opposes (conflicted SUPPORT opposes rising price, conflicted
   RESISTANCE opposes falling price — Day-23 corrections preserved).
4. MIXED / UNKNOWN / NO_SIGNAL carry NO directional implication —
   never opposing, never agreeing (Day-22/23 corrections).
5. Missing != zero: spot_change None = missing (PARTIAL), 0.0 =
   measured flat (NO_TRAP); missing family input = no read.
6. Day-12 quality preserved (identity) and gated; Day-9 provenance
   preserved verbatim; never recomputed.
7. signal_strength != confidence != quality; horizon EXPIRY.
8. Deterministic, repeatable, pure: no wall clock / random / DB /
   network / filesystem / broker imports (AST-guarded).
9. Golden expectations are independent hand arithmetic.

Hand arithmetic
---------------
Family strengths (documented constants): POSITIONING 0.5, FLOW 0.5,
LEVEL = conflicted level strength (Day-21 measured), INSTITUTIONAL =
caller-supplied Day-22 strength (else 0.5), REGIME 0.5.
strength = min(opposing_sum, 1.0); confidence table 0.80 / 0.70 / 0.90.

Examples:
  spot_change +5, positioning SHORT_BUILDUP (bearish opposing 0.5)
      => BULL_TRAP_CANDIDATE, strength 0.5, conf 0.70, dir BEARISH
  spot_change +5, flow DIVERGE
      => FLOW_PRICE_TRAP, strength 0.5, conf 0.70, dir BEARISH
  spot_change +5, conflicted SUPPORT strength 0.8 (proximate)
      => FAILED_BREAKOUT, strength 0.8, conf 0.70, dir BEARISH
  spot_change +5, positioning SHORT_BUILDUP (0.5) + flow DIVERGE (0.5)
      => BULL_TRAP_CANDIDATE, strength min(1.0, 1.0) = 1.0, conf 0.70
  same + flow CONFIRM (agreeing) => conf 0.80 (both sides observed)
  spot_change +5, positioning LONG_BUILDUP (agreeing) => NO_TRAP,
      strength 0.0, conf 0.90, dir NEUTRAL
  spot_change 0.0 (measured flat) => NO_TRAP, strength 0.0, conf 0.90
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    IntelligenceDirection,
    IntelligenceIssueCode,
    IntelligenceResult,
    IntelligenceStatus,
    RegimeLabel,
    TimeHorizon,
)
from app.intelligence.flow import PriceFlowRelation
from app.intelligence.levels import LevelClassification, LevelKind, LevelState
from app.intelligence.positioning import PositioningClassification
from app.intelligence.traps import (
    CALCULATION_ID,
    CONFIDENCE_FLAT,
    CONFIDENCE_NO_TRAP,
    CONFIDENCE_TRAP_FULL,
    CONFIDENCE_TRAP_OPPOSING_ONLY,
    FAMILY_STRENGTH_FLOW,
    FAMILY_STRENGTH_LABEL_LEVEL,
    FAMILY_STRENGTH_POSITIONING,
    FAMILY_STRENGTH_REGIME,
    TrapClassification,
    TrapInput,
    evaluate_traps,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"


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
        quality_score=95 if state is QualityState.EXCELLENT else 55,
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


def _level(strike: float, kind: LevelKind, state: LevelState,
           strength: float | None = None) -> LevelClassification:
    return LevelClassification(strike=strike, kind=kind, state=state,
                               strength=strength)


def _inp(*, spot_change=5.0, spot=250.0, positioning=None,
         price_flow_relation=None, levels=(), institutional_direction=None,
         institutional_strength=None, regime_label=None,
         regime_direction=None, quality=_UNSET, prov=_UNSET,
         expiry="2026-09-24") -> TrapInput:
    return TrapInput(
        underlying=NIFTY,
        expiry=expiry,
        spot=spot,
        spot_change=spot_change,
        positioning=positioning,
        price_flow_relation=price_flow_relation,
        level_classifications=tuple(levels),
        institutional_direction=institutional_direction,
        institutional_strength=institutional_strength,
        regime_label=regime_label,
        regime_direction=regime_direction,
        reference_timestamp=_REF,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


# ---------------------------------------------------------------------------
# 1. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_input(self):
        inp = _inp()
        assert inp.underlying == NIFTY
        assert inp.spot_change == pytest.approx(5.0)

    def test_naive_reference_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            TrapInput(underlying=NIFTY, reference_timestamp=naive,
                      provenance=_prov(), quality=_quality())

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            TrapInput(underlying=NIFTY, reference_timestamp=_REF,
                      provenance=None, quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            TrapInput(underlying=NIFTY, reference_timestamp=_REF,
                      provenance=_prov(), quality=QualityState.EXCELLENT)

    def test_spot_must_be_positive_when_present(self):
        with pytest.raises(ValueError):
            _inp(spot=0.0)

    def test_institutional_strength_bounds(self):
        with pytest.raises(ValueError):
            _inp(institutional_direction=IntelligenceDirection.BEARISH,
                 institutional_strength=1.5)
        with pytest.raises(ValueError):
            _inp(institutional_direction=IntelligenceDirection.BEARISH,
                 institutional_strength=-0.1)

    def test_positioning_type_checked(self):
        with pytest.raises(ValueError):
            _inp(positioning="SHORT_BUILDUP")

    def test_flow_relation_type_checked(self):
        with pytest.raises(ValueError):
            _inp(price_flow_relation="DIVERGE")

    def test_levels_type_checked(self):
        with pytest.raises(ValueError):
            _inp(levels=(("not", "a", "level"),))

    def test_constants_documented(self):
        assert FAMILY_STRENGTH_POSITIONING == 0.5
        assert FAMILY_STRENGTH_FLOW == 0.5
        assert FAMILY_STRENGTH_LABEL_LEVEL == 0.5
        assert FAMILY_STRENGTH_REGIME == 0.5
        assert CONFIDENCE_TRAP_FULL == 0.80
        assert CONFIDENCE_TRAP_OPPOSING_ONLY == 0.70
        assert CONFIDENCE_NO_TRAP == 0.90
        assert CONFIDENCE_FLAT == 0.90
        assert CALCULATION_ID == "intelligence.trap_detection.v1"


# ---------------------------------------------------------------------------
# 2. Basic classification
# ---------------------------------------------------------------------------


class TestBasicClassification:
    def test_bullish_price_bearish_positioning_is_bull_trap(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(0.70, rel=1e-9)
        assert r.time_horizon is TimeHorizon.EXPIRY

    def test_bearish_price_bullish_positioning_is_bear_trap(self):
        r = evaluate_traps(_inp(spot_change=-5.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        assert r.observation.metric_name == TrapClassification.BEAR_TRAP_CANDIDATE.value
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_bullish_price_supportive_positioning_is_no_trap(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.signal_strength == 0.0
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_bearish_price_supportive_positioning_is_no_trap(self):
        r = evaluate_traps(_inp(spot_change=-5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.direction is IntelligenceDirection.NEUTRAL

    def test_unclassified_positioning_is_no_read(self):
        # UNCLASSIFIED carries no directional implication: neither opposing
        # nor agreeing => insufficient directional evidence => PARTIAL
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.UNCLASSIFIED))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "directional_evidence" for i in r.issues)


# ---------------------------------------------------------------------------
# 3. Flow family
# ---------------------------------------------------------------------------


class TestFlow:
    def test_bullish_price_bearish_flow_is_flow_price_trap(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.FLOW_PRICE_TRAP.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(0.70, rel=1e-9)

    def test_bearish_price_bullish_flow_is_flow_price_trap(self):
        r = evaluate_traps(_inp(spot_change=-5.0,
                                price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.observation.metric_name == TrapClassification.FLOW_PRICE_TRAP.value
        assert r.direction is IntelligenceDirection.BULLISH

    def test_flow_confirm_agrees(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_flow_no_signal_is_no_read(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                price_flow_relation=PriceFlowRelation.NO_SIGNAL))
        assert r.status is IntelligenceStatus.PARTIAL

    def test_missing_flow_is_no_read(self):
        r = evaluate_traps(_inp(spot_change=5.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any("flow" not in (i.field or "") for i in r.issues)


# ---------------------------------------------------------------------------
# 4. Positioning family
# ---------------------------------------------------------------------------


class TestPositioning:
    def test_bullish_price_bearish_positioning_opposes(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value

    def test_bearish_price_bullish_positioning_opposes(self):
        r = evaluate_traps(_inp(spot_change=-5.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        assert r.observation.metric_name == TrapClassification.BEAR_TRAP_CANDIDATE.value

    def test_bullish_price_bullish_positioning_agrees(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value

    def test_bearish_price_bearish_positioning_agrees(self):
        r = evaluate_traps(_inp(spot_change=-5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value

    def test_missing_positioning_no_read(self):
        r = evaluate_traps(_inp(spot_change=5.0))
        assert r.status is IntelligenceStatus.PARTIAL


# ---------------------------------------------------------------------------
# 5. Level family (Day-21/23 semantics authoritative)
# ---------------------------------------------------------------------------


class TestLevels:
    def test_conflicted_support_opposes_bullish_price_failed_breakout(self):
        # conflicted SUPPORT = bearish implication (support broke down);
        # proximate to spot => opposing the bullish attempt
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            levels=(_level(245.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, strength=0.8),)))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.FAILED_BREAKOUT.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.8, rel=1e-9)
        assert r.confidence == pytest.approx(0.70, rel=1e-9)

    def test_conflicted_resistance_opposes_bearish_price_failed_breakdown(self):
        r = evaluate_traps(_inp(
            spot_change=-5.0, spot=250.0,
            levels=(_level(255.0, LevelKind.RESISTANCE,
                           LevelState.CONFLICTED_INTERACTION, strength=0.7),)))
        assert r.observation.metric_name == TrapClassification.FAILED_BREAKDOWN.value
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.7, rel=1e-9)

    def test_conflicted_resistance_with_bullish_price_is_consistent_not_trap(self):
        # resistance broke up = bullish implication => agrees with the
        # bullish attempt; never a trap.  Consistent conflicts form no trap
        # read => PARTIAL (no observation, never a trap label).
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            levels=(_level(255.0, LevelKind.RESISTANCE,
                           LevelState.CONFLICTED_INTERACTION, strength=0.8),)))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.observation is None

    def test_conflicted_support_with_bearish_price_is_consistent_not_trap(self):
        r = evaluate_traps(_inp(
            spot_change=-5.0, spot=250.0,
            levels=(_level(245.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, strength=0.8),)))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.observation is None

    def test_approaching_level_is_never_a_trap(self):
        # Day-21 remediation: APPROACHING proves movement, not interaction
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            levels=(_level(255.0, LevelKind.RESISTANCE,
                           LevelState.APPROACHING, strength=0.8),)))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.observation is None

    def test_level_existence_alone_never_creates_trap(self):
        # constructive STATIC level: measured concentration, no conflict
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            levels=(_level(245.0, LevelKind.SUPPORT, LevelState.STATIC,
                           strength=0.9),)))
        assert r.status is IntelligenceStatus.PARTIAL

    def test_non_proximate_conflicted_level_is_not_used(self):
        # conflicted level far from spot: not relevant to the current move
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            levels=(_level(150.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, strength=0.8),)))
        assert r.status is IntelligenceStatus.PARTIAL

    def test_kind_aware_conflict_multi_factor(self):
        # conflicted SUPPORT (bearish) + bullish move + bearish positioning:
        # two opposing families => BULL_TRAP_CANDIDATE strength 1.0 (capped)
        r = evaluate_traps(_inp(
            spot_change=5.0, spot=250.0,
            positioning=PositioningClassification.SHORT_BUILDUP,
            levels=(_level(245.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, strength=0.9),)))
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)


# ---------------------------------------------------------------------------
# 6. Institutional-like family (Day-22 semantics)
# ---------------------------------------------------------------------------


class TestInstitutionalLike:
    def test_opposing_direction_is_trap_evidence(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                institutional_direction=IntelligenceDirection.BEARISH,
                                institutional_strength=0.6))
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.6, rel=1e-9)

    def test_consistent_direction_is_no_trap(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                institutional_direction=IntelligenceDirection.BULLISH,
                                institutional_strength=0.6))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_mixed_institutional_is_never_opposing(self):
        # Day-23 correction: MIXED carries no directional implication
        r = evaluate_traps(_inp(spot_change=5.0,
                                institutional_direction=IntelligenceDirection.MIXED,
                                institutional_strength=0.6))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.observation is None

    def test_missing_institutional_is_no_read(self):
        r = evaluate_traps(_inp(spot_change=5.0))
        assert r.status is IntelligenceStatus.PARTIAL

    def test_label_level_fallback_strength(self):
        # direction opposing without a supplied strength => label-level 0.5
        r = evaluate_traps(_inp(spot_change=5.0,
                                institutional_direction=IntelligenceDirection.BEARISH))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 7. Regime family (Day-23 semantics)
# ---------------------------------------------------------------------------


class TestRegime:
    def test_opposing_regime_direction_is_trap_evidence(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                regime_label=RegimeLabel.RISK_OFF,
                                regime_direction=IntelligenceDirection.BEARISH))
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_agreeing_regime_direction_is_no_trap(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                regime_label=RegimeLabel.RISK_ON,
                                regime_direction=IntelligenceDirection.BULLISH))
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value

    def test_mixed_regime_is_never_opposing(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                regime_label=RegimeLabel.TRENDING,
                                regime_direction=IntelligenceDirection.MIXED))
        assert r.status is IntelligenceStatus.PARTIAL

    def test_missing_regime_no_read(self):
        r = evaluate_traps(_inp(spot_change=5.0))
        assert r.status is IntelligenceStatus.PARTIAL


# ---------------------------------------------------------------------------
# 8. Evidence independence
# ---------------------------------------------------------------------------


class TestEvidenceIndependence:
    def test_one_opposing_family_is_0_5(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_two_independent_opposing_families_cap_at_1_0(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.observation.metric_name == TrapClassification.BULL_TRAP_CANDIDATE.value

    def test_three_opposing_families_stay_capped(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.DIVERGE,
                                institutional_direction=IntelligenceDirection.BEARISH,
                                institutional_strength=0.6))
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)

    def test_conflict_fully_characterized_confidence(self):
        # opposing + agreeing both observed => 0.80
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(0.80, rel=1e-9)

    def test_agreeing_families_never_reduce_strength_of_opposing(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_evidence_rows_record_families(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.DIVERGE))
        refs = [e.source_reference_id for e in r.evidence]
        assert any("opposing:positioning" in x for x in refs)
        assert any("opposing:flow" in x for x in refs)
        assert any("price_attempt" in x for x in refs)
        assert any("opposing_family_count" in x for x in refs)


# ---------------------------------------------------------------------------
# 9. Missing vs zero
# ---------------------------------------------------------------------------


class TestMissingVsZero:
    def test_missing_price_is_partial_not_no_trap(self):
        r = evaluate_traps(_inp(spot_change=None,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "spot_change" for i in r.issues)
        assert r.observation is None  # never a NO_TRAP label from missing data

    def test_measured_flat_price_is_no_trap(self):
        # 0.0 is a legitimate measured zero, distinct from missing
        r = evaluate_traps(_inp(spot_change=0.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.signal_strength == 0.0
        assert r.confidence == pytest.approx(0.90, rel=1e-9)
        assert r.direction is IntelligenceDirection.NEUTRAL

    def test_no_evidence_is_unavailable(self):
        r = evaluate_traps(_inp(spot_change=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert any(i.code is IntelligenceIssueCode.MISSING_EVIDENCE
                   for i in r.issues)
        assert not r.evidence

    def test_insufficient_directional_families_is_partial(self):
        # price present but every family read is missing/non-directional
        r = evaluate_traps(_inp(spot_change=5.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "directional_evidence" for i in r.issues)

    def test_zero_strength_measured_is_distinct_from_missing(self):
        # measured-zero institutional strength with opposing direction: the read
        # is present (0.0) — never treated as missing.  The Day-19 contract
        # requires positive strength for a directional claim, so a zero-
        # magnitude contradiction yields NO_TRAP (NEUTRAL, 0.0) with the
        # measured-zero opposing row proving the read was present.
        r = evaluate_traps(_inp(spot_change=5.0,
                                institutional_direction=IntelligenceDirection.BEARISH,
                                institutional_strength=0.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == TrapClassification.NO_TRAP.value
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.signal_strength == pytest.approx(0.0, rel=1e-9)
        assert any("opposing:institutional" in e.source_reference_id
                   and e.value == 0.0 for e in r.evidence)


# ---------------------------------------------------------------------------
# 10. Quality / provenance / contract
# ---------------------------------------------------------------------------


class TestQualityProvenance:
    def test_missing_quality_partial(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                quality=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY
                   for i in r.issues)

    def test_insufficient_quality_partial(self):
        q = _quality(QualityState.INSUFFICIENT)
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                quality=q))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.INSUFFICIENT_QUALITY
                   for i in r.issues)
        assert r.quality is q

    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                quality=q))
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                prov=prov))
        assert r.provenance == prov
        assert all(e.provenance == prov for e in r.evidence)

    def test_signal_strength_confidence_quality_separate(self):
        q = _quality()
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                quality=q))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(0.70, rel=1e-9)
        assert r.quality is q
        assert r.signal_strength != r.confidence
        assert r.confidence != q.quality_score

    def test_result_contract_fields(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.calculation_id == CALCULATION_ID
        assert r.contract_version == INTELLIGENCE_CONTRACT_VERSION
        assert r.reference_timestamp == _REF
        assert r.observation.value == pytest.approx(0.5, rel=1e-9)
        assert r.observation.unit == "score_0_1"
        assert r.evidence
        assert not r.issues

    def test_serialization_round_trip(self):
        r = evaluate_traps(_inp(spot_change=5.0,
                                positioning=PositioningClassification.SHORT_BUILDUP,
                                price_flow_relation=PriceFlowRelation.DIVERGE,
                                levels=(_level(245.0, LevelKind.SUPPORT,
                                               LevelState.CONFLICTED_INTERACTION,
                                               strength=0.8),)))
        assert IntelligenceResult.from_dict(r.to_dict()) == r


# ---------------------------------------------------------------------------
# 11. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_evaluation_identical(self):
        inp = _inp(spot_change=5.0,
                   positioning=PositioningClassification.SHORT_BUILDUP,
                   price_flow_relation=PriceFlowRelation.DIVERGE,
                   institutional_direction=IntelligenceDirection.BEARISH,
                   institutional_strength=0.6,
                   levels=(_level(245.0, LevelKind.SUPPORT,
                                  LevelState.CONFLICTED_INTERACTION,
                                  strength=0.8),))
        a = evaluate_traps(inp)
        b = evaluate_traps(inp)
        assert a == b
        assert a.to_dict() == b.to_dict()

    def test_family_reads_deterministic_with_same_inputs(self):
        a = evaluate_traps(_inp(spot_change=-3.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        b = evaluate_traps(_inp(spot_change=-3.0,
                                positioning=PositioningClassification.LONG_BUILDUP))
        assert a.observation == b.observation
        assert [e.source_reference_id for e in a.evidence] \
            == [e.source_reference_id for e in b.evidence]


# ---------------------------------------------------------------------------
# 12. Purity (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "traps.py"

    def test_no_clock_io_or_broker_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi"}
        tree = ast.parse(self._MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today", "time",
                                              "sleep"}
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("app.brokers")
                assert not module.startswith("app.services")
                assert not module.startswith("app.routers")

    def test_no_wall_clock_tokens_in_module(self):
        text = self._MODULE.read_text(encoding="utf-8")
        for token in ("datetime.now", "datetime.utcnow", "time.time()",
                      "uuid", "random."):
            assert token not in text

    def test_no_certainty_or_identity_vocabulary(self):
        text = self._MODULE.read_text(encoding="utf-8")
        for token in ("manipulation", "market_maker", "smart_money",
                      "FII", "DII", "confirmed trap", "will pin"):
            assert token not in text