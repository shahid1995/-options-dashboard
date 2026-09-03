"""Day 26 — Intelligence Synthesis & Conflict Resolution tests (RED-phase contract).

Proves the deterministic, broker-neutral synthesis engine on the Day-19
Intelligence Contract, consuming typed family evidence from Days 20-25:

    per-family directional reads (Days 20-24) + trap pattern read (Day 25)
        -> evidence-family synthesis (no majority vote, no double counting)
        -> agreement / conflict / no-direction outcome
        -> Day-19 IntelligenceResult

Rules locked by these tests
---------------------------
1. No majority-vote intelligence: one independent read per evidence family
   (POSITIONING / FLOW / LEVEL / INSTITUTIONAL_LIKE / REGIME / TRAP);
   correlated fields derived from the same measurement are never counted
   repeatedly.
2. Only BULLISH / BEARISH contribute directional votes.  NEUTRAL, MIXED,
   UNKNOWN, NO_SIGNAL and label-only reads never become votes (Days 22-23
   corrections preserved) and never act as opposing evidence.
3. Correlation rules:
   a. POSITIONING + aligned INSTITUTIONAL_LIKE (same-OI derivation, Day-22
      consumes Day-20) form ONE vote at max(a, b) -- never the sum.
   b. A TRAP read duplicating another vote of the same direction adds NO
      strength (recorded as context); a unique-direction trap votes.
   c. Material evidence on BOTH sides => MIXED (conflict exposed), never an
      arbitrary choice of the stronger side.
4. Day-21 semantics preserved: APPROACHING / STATIC / constructive levels
   never vote; only proximate CONFLICTED_INTERACTION rows carry a
   directional implication (conflicted SUPPORT => bearish breakdown,
   conflicted RESISTANCE => bullish breakout).
5. Day-23 regime semantics preserved: label alone never votes; only an
   actual directional Day-23 read (BULLISH / BEARISH) votes.
6. Day-25 trap semantics preserved: trap candidates are one pattern family
   (never certainty, never an automatic override); NO_TRAP never votes.
7. Missing != zero: missing family input = absent; a measured-zero strength
   read is present but carries no magnitude and can never support a
   directional claim (Day-19 requires positive strength for direction).
8. Day-12 quality preserved by identity and gated (None => PARTIAL
   MISSING_QUALITY; INSUFFICIENT => PARTIAL INSUFFICIENT_QUALITY); Day-9
   provenance preserved verbatim; never recomputed.
9. signal_strength != confidence != quality.  Confidence is a documented
   completeness/agreement table, never strength.
10. Deterministic, repeatable, pure: no wall clock / random / DB / network /
    filesystem / broker imports (AST-guarded).
11. Golden expectations are independent hand arithmetic.

Hand arithmetic
---------------
Label family strengths (documented constants): POSITIONING 0.5, FLOW 0.5,
REGIME 0.5, INSTITUTIONAL 0.5 fallback (caller strength when supplied),
TRAP 0.5 fallback (caller strength when supplied), LEVEL = measured
strength of the strongest proximate conflicted row.
bull_total = min(sum(bull votes), 1.0); bear_total likewise.
Outcome: one side only => that direction with strength = side total;
         both sides material (>= 1 vote each) => MIXED,
            strength = min(bull_total, bear_total) (contested mass);
         reads present, no votes => UNKNOWN, strength 0.0.
Confidence table: 0.85 (>=2 winning votes) / 0.75 (1 winning vote) /
0.60 (MIXED) / 0.70 (no directional read).

Examples:
  positioning LONG_BUILDUP                     => BULLISH, 0.5,  conf 0.75
  positioning LONG_BUILDUP + flow CONFIRM(+5)  => BULLISH, 1.0,  conf 0.85
  positioning LONG_BUILDUP + flow DIVERGE(+5)  => MIXED,   0.5,  conf 0.60
  positioning SHORT_BUILDUP + institutional
      BEARISH 0.6 (aligned same-source)        => BEARISH, 0.6 (max, never sum)
  positioning LONG_BUILDUP + institutional
      BEARISH 0.5 (opposing)                   => MIXED,   0.5,  conf 0.60
  conflicted SUPPORT 0.8 proximate             => BEARISH, 0.8
  positioning SHORT_BUILDUP + trap BEARISH 0.5 => BEARISH, 0.5 (trap duplicated,
                                                  no double count)
  trap BEARISH 0.7 alone                       => BEARISH, 0.7 (unique vote)
  institutional BEARISH strength 0.0           => UNKNOWN, 0.0 (measured zero,
                                                  never a vote, never missing)
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
from app.intelligence.synthesis import (
    CALCULATION_ID,
    CONFIDENCE_AGREEMENT_MULTI,
    CONFIDENCE_AGREEMENT_SINGLE,
    CONFIDENCE_CONFLICT,
    CONFIDENCE_NO_DIRECTION,
    FAMILY_STRENGTH_FLOW,
    FAMILY_STRENGTH_INSTITUTIONAL,
    FAMILY_STRENGTH_POSITIONING,
    FAMILY_STRENGTH_REGIME,
    FAMILY_STRENGTH_TRAP,
    LEVEL_PROXIMITY_FRACTION,
    SynthesisInput,
    SynthesisOutcome,
    evaluate_synthesis,
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


def _inp(*, spot=250.0, spot_change=5.0, positioning=None,
         price_flow_relation=None, levels=(), institutional_direction=None,
         institutional_strength=None, regime_label=None,
         regime_direction=None, trap_direction=None, trap_strength=None,
         quality=_UNSET, prov=_UNSET, expiry="2026-09-24") -> SynthesisInput:
    return SynthesisInput(
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
        trap_direction=trap_direction,
        trap_strength=trap_strength,
        reference_timestamp=_REF,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


def _evidence_map(r: IntelligenceResult) -> dict[str, float]:
    # canonical reference ids are synthesis:<underlying>:<scope>:<key> --
    # strip the fixed prefix so assertions address the evidence key
    return {e.source_reference_id.split(":", 3)[3]: e.value
            for e in r.evidence}


# ---------------------------------------------------------------------------
# 1. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_input(self):
        inp = _inp()
        assert inp.underlying == NIFTY

    def test_naive_reference_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            SynthesisInput(underlying=NIFTY, reference_timestamp=naive,
                           provenance=_prov(), quality=_quality())

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            SynthesisInput(underlying=NIFTY, reference_timestamp=_REF,
                           provenance=None, quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            SynthesisInput(underlying=NIFTY, reference_timestamp=_REF,
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

    def test_trap_strength_bounds(self):
        with pytest.raises(ValueError):
            _inp(trap_direction=IntelligenceDirection.BEARISH,
                 trap_strength=1.5)
        with pytest.raises(ValueError):
            _inp(trap_direction=IntelligenceDirection.BEARISH,
                 trap_strength=-0.1)

    def test_positioning_type_checked(self):
        with pytest.raises(ValueError):
            _inp(positioning="SHORT_BUILDUP")

    def test_flow_relation_type_checked(self):
        with pytest.raises(ValueError):
            _inp(price_flow_relation="DIVERGE")

    def test_levels_type_checked(self):
        with pytest.raises(ValueError):
            _inp(levels=(( "not", "a", "level"),))

    def test_constants_documented(self):
        assert FAMILY_STRENGTH_POSITIONING == 0.5
        assert FAMILY_STRENGTH_FLOW == 0.5
        assert FAMILY_STRENGTH_REGIME == 0.5
        assert FAMILY_STRENGTH_INSTITUTIONAL == 0.5
        assert FAMILY_STRENGTH_TRAP == 0.5
        assert LEVEL_PROXIMITY_FRACTION == 0.10
        assert CONFIDENCE_AGREEMENT_MULTI == 0.85
        assert CONFIDENCE_AGREEMENT_SINGLE == 0.75
        assert CONFIDENCE_CONFLICT == 0.60
        assert CONFIDENCE_NO_DIRECTION == 0.70
        assert CALCULATION_ID == "intelligence.synthesis.v1"


# ---------------------------------------------------------------------------
# 2. Status ladder: UNAVAILABLE / quality gates
# ---------------------------------------------------------------------------


class TestStatusLadder:
    def test_no_evidence_is_unavailable(self):
        r = evaluate_synthesis(_inp(positioning=None, price_flow_relation=None,
                                    levels=(), institutional_direction=None,
                                    regime_direction=None, trap_direction=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert r.direction is None
        assert r.observation is None
        assert r.evidence == ()
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_EVIDENCE in codes

    def test_no_evidence_without_quality_reports_both(self):
        r = evaluate_synthesis(_inp(quality=None, positioning=None,
                                    price_flow_relation=None, levels=(),
                                    institutional_direction=None,
                                    regime_direction=None, trap_direction=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_EVIDENCE in codes
        assert IntelligenceIssueCode.MISSING_QUALITY in codes

    def test_price_alone_is_not_evidence(self):
        # a raw signed move is context, never a family read -- it cannot
        # synthesize a direction by itself
        r = evaluate_synthesis(_inp(spot_change=5.0, positioning=None,
                                    price_flow_relation=None, levels=(),
                                    institutional_direction=None,
                                    regime_direction=None, trap_direction=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert IntelligenceIssueCode.MISSING_EVIDENCE in {i.code for i in r.issues}

    def test_expiry_alone_is_not_evidence(self):
        # Day-24/expiry context is never directional and never a vote
        r = evaluate_synthesis(_inp(expiry="2026-09-24", positioning=None,
                                    price_flow_relation=None, levels=(),
                                    institutional_direction=None,
                                    regime_direction=None, trap_direction=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE

    def test_missing_quality_is_partial_with_evidence(self):
        r = evaluate_synthesis(_inp(
            quality=None,
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is None
        assert r.observation is None
        assert r.evidence  # Day-19 PARTIAL requires >= 1 evidence row
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_QUALITY in codes

    def test_insufficient_quality_is_partial(self):
        r = evaluate_synthesis(_inp(
            quality=_quality(QualityState.INSUFFICIENT),
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is None
        assert r.evidence
        assert IntelligenceIssueCode.INSUFFICIENT_QUALITY in {
            i.code for i in r.issues}

    def test_quality_preserved_by_identity_on_success(self):
        q = _quality()
        r = evaluate_synthesis(_inp(
            quality=q, positioning=PositioningClassification.LONG_BUILDUP))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        p = _prov()
        r = evaluate_synthesis(_inp(prov=p,
                                    positioning=PositioningClassification.LONG_BUILDUP))
        assert r.provenance is p
        assert r.reference_timestamp == _REF
        assert all(e.provenance is p for e in r.evidence)


# ---------------------------------------------------------------------------
# 3. One-family directional reads
# ---------------------------------------------------------------------------


class TestSingleFamilyReads:
    def test_positioning_bullish(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == SynthesisOutcome.BULLISH_AGREEMENT.value
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_SINGLE, rel=1e-9)
        assert r.time_horizon is TimeHorizon.EXPIRY

    def test_positioning_bearish(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.observation.metric_name == SynthesisOutcome.BEARISH_AGREEMENT.value
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_positioning_unclassified_never_votes(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.UNCLASSIFIED))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == SynthesisOutcome.NO_DIRECTIONAL_EVIDENCE.value
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0

    def test_flow_confirm_rising_is_bullish(self):
        r = evaluate_synthesis(_inp(spot_change=5.0,
                                    price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_flow_confirm_falling_is_bearish(self):
        r = evaluate_synthesis(_inp(spot_change=-5.0,
                                    price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_flow_diverge_rising_is_bearish(self):
        r = evaluate_synthesis(_inp(spot_change=5.0,
                                    price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_flow_no_signal_never_votes(self):
        r = evaluate_synthesis(_inp(spot_change=5.0,
                                    price_flow_relation=PriceFlowRelation.NO_SIGNAL))
        assert r.observation.metric_name == SynthesisOutcome.NO_DIRECTIONAL_EVIDENCE.value
        assert r.direction is IntelligenceDirection.UNKNOWN

    def test_flow_without_price_direction_is_present_but_not_directional(self):
        r = evaluate_synthesis(_inp(spot_change=None,
                                    price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        rows = _evidence_map(r)
        assert any(k.startswith("read:flow:DIVERGE") for k in rows)

    def test_conflicted_support_is_bearish(self):
        r = evaluate_synthesis(_inp(
            levels=(_level(240.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, 0.8),)))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.8, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_SINGLE, rel=1e-9)

    def test_conflicted_resistance_is_bullish(self):
        r = evaluate_synthesis(_inp(
            levels=(_level(260.0, LevelKind.RESISTANCE,
                           LevelState.CONFLICTED_INTERACTION, 0.6),)))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.6, rel=1e-9)

    def test_static_level_never_votes(self):
        # Day-21 remediation: level existence alone is not directional
        r = evaluate_synthesis(_inp(
            levels=(_level(248.0, LevelKind.SUPPORT, LevelState.STATIC, 0.9),)))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0

    def test_approaching_level_never_votes(self):
        # APPROACHING != CONFIRMED_INTERACTION; approach is not a vote
        r = evaluate_synthesis(_inp(
            levels=(_level(246.0, LevelKind.SUPPORT,
                           LevelState.APPROACHING, 0.7),)))
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0

    def test_out_of_proximity_conflict_never_votes(self):
        # only proximate classified rows are the level-family input; a
        # conflicted row far from the current spot is not usable evidence
        r = evaluate_synthesis(_inp(
            levels=(_level(200.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, 0.8),)))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert r.direction is None
        assert IntelligenceIssueCode.MISSING_EVIDENCE in {
            i.code for i in r.issues}

    def test_institutional_direction_bullish(self):
        r = evaluate_synthesis(_inp(institutional_direction=IntelligenceDirection.BULLISH,
                                    institutional_strength=0.4))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.4, rel=1e-9)

    def test_institutional_default_strength(self):
        r = evaluate_synthesis(_inp(
            institutional_direction=IntelligenceDirection.BEARISH))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_institutional_mixed_never_votes(self):
        r = evaluate_synthesis(_inp(
            institutional_direction=IntelligenceDirection.MIXED,
            institutional_strength=0.9))
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        rows = _evidence_map(r)
        assert any(k.startswith("read:institutional:MIXED") for k in rows)

    def test_regime_directional_read_votes(self):
        r = evaluate_synthesis(_inp(regime_label=RegimeLabel.TRENDING,
                                    regime_direction=IntelligenceDirection.BULLISH))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_regime_neutral_direction_never_votes(self):
        # RANGING regime emits direction NEUTRAL -- present, never a vote
        r = evaluate_synthesis(_inp(regime_label=RegimeLabel.RANGING,
                                    regime_direction=IntelligenceDirection.NEUTRAL))
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        rows = _evidence_map(r)
        assert any(k.startswith("read:regime:RANGING") for k in rows)

    def test_regime_unknown_direction_never_votes(self):
        r = evaluate_synthesis(_inp(regime_label=RegimeLabel.HIGH_VOLATILITY,
                                    regime_direction=IntelligenceDirection.UNKNOWN))
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0

    def test_regime_label_alone_is_missing(self):
        # Day-25 convention: regime_direction is the read; label alone absent
        r = evaluate_synthesis(_inp(regime_label=RegimeLabel.TRENDING,
                                    regime_direction=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert IntelligenceIssueCode.MISSING_EVIDENCE in {i.code for i in r.issues}

    def test_trap_direction_votes_alone(self):
        r = evaluate_synthesis(_inp(trap_direction=IntelligenceDirection.BEARISH,
                                    trap_strength=0.7))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.7, rel=1e-9)

    def test_trap_default_strength(self):
        r = evaluate_synthesis(_inp(trap_direction=IntelligenceDirection.BULLISH))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_no_trap_never_votes(self):
        # Day-25 NO_TRAP => direction NEUTRAL: present, never a vote
        r = evaluate_synthesis(_inp(trap_direction=IntelligenceDirection.NEUTRAL))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        rows = _evidence_map(r)
        assert any(k.startswith("read:trap:NEUTRAL") for k in rows)

    def test_trap_mixed_never_votes(self):
        r = evaluate_synthesis(_inp(trap_direction=IntelligenceDirection.MIXED,
                                    trap_strength=0.8))
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0


# ---------------------------------------------------------------------------
# 4. Multi-family agreement + totals
# ---------------------------------------------------------------------------


class TestAgreement:
    def test_two_independent_bullish_families(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.CONFIRM))
        assert r.observation.metric_name == SynthesisOutcome.BULLISH_AGREEMENT.value
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_MULTI, rel=1e-9)

    def test_three_bullish_families_capped_at_one(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.CONFIRM,
            regime_label=RegimeLabel.RISK_ON,
            regime_direction=IntelligenceDirection.BULLISH))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_MULTI, rel=1e-9)

    def test_two_independent_bearish_families(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP,
            regime_label=RegimeLabel.TRENDING,
            regime_direction=IntelligenceDirection.BEARISH))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_MULTI, rel=1e-9)

    def test_totals_rows_recorded(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.CONFIRM))
        rows = _evidence_map(r)
        assert rows["synthesis:bull_total"] == pytest.approx(1.0, rel=1e-9)
        assert rows["synthesis:bear_total"] == pytest.approx(0.0, abs=1e-9)
        assert rows["synthesis:net"] == pytest.approx(1.0, rel=1e-9)

    def test_single_vote_rows_recorded(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP))
        rows = _evidence_map(r)
        assert rows["synthesis:bull_total"] == pytest.approx(0.5, rel=1e-9)
        assert rows["synthesis:net"] == pytest.approx(0.5, rel=1e-9)
        assert any(k.startswith("bull:positioning:LONG_BUILDUP")
                   and v == pytest.approx(0.5, rel=1e-9)
                   for k, v in rows.items())


# ---------------------------------------------------------------------------
# 5. Conflict resolution
# ---------------------------------------------------------------------------


class TestConflict:
    def test_balanced_conflict_is_mixed(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.DIVERGE))
        assert r.observation.metric_name == SynthesisOutcome.MATERIAL_CONFLICT.value
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_CONFLICT, rel=1e-9)

    def test_strong_bullish_vs_weak_bearish_is_not_forced_bullish(self):
        # independent material evidence on both sides => MIXED, never an
        # arbitrary choice of the stronger side
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.8))
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        rows = _evidence_map(r)
        assert rows["synthesis:bull_total"] == pytest.approx(0.5, rel=1e-9)
        assert rows["synthesis:bear_total"] == pytest.approx(0.8, rel=1e-9)

    def test_weak_bullish_vs_strong_bearish_is_mixed(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP,
            regime_label=RegimeLabel.TRENDING,
            regime_direction=IntelligenceDirection.BEARISH,
            institutional_direction=IntelligenceDirection.BULLISH,
            institutional_strength=0.2))
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.2, rel=1e-9)
        rows = _evidence_map(r)
        assert rows["synthesis:bear_total"] == pytest.approx(1.0, rel=1e-9)
        assert rows["synthesis:bull_total"] == pytest.approx(0.2, rel=1e-9)

    def test_conflict_rows_expose_both_sides(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.DIVERGE))
        rows = _evidence_map(r)
        assert any(k.startswith("bull:positioning") for k in rows)
        assert any(k.startswith("bear:flow:DIVERGE") for k in rows)

    def test_conflicting_level_and_positioning(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            levels=(_level(240.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, 0.8),)))
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_mixed_upstream_never_becomes_opposing(self):
        # MIXED institutional evidence carries NO directional implication
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.MIXED,
            institutional_strength=0.9))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_unknown_upstream_never_becomes_opposing(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.UNKNOWN,
            institutional_strength=0.9))
        assert r.direction is IntelligenceDirection.BULLISH

    def test_neutral_upstream_never_becomes_opposing(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            regime_label=RegimeLabel.RANGING,
            regime_direction=IntelligenceDirection.NEUTRAL))
        assert r.direction is IntelligenceDirection.BULLISH

    def test_no_signal_flow_never_becomes_opposing(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.NO_SIGNAL))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)


# ---------------------------------------------------------------------------
# 6. Evidence-family independence (correlation rules)
# ---------------------------------------------------------------------------


class TestFamilyIndependence:
    def test_aligned_positioning_institutional_single_vote(self):
        # Day-22 institutional derives from Day-20 OI positioning: aligned
        # reads form ONE vote at max(a, b), never the sum
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.BULLISH,
            institutional_strength=0.6))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.6, rel=1e-9)
        rows = _evidence_map(r)
        assert rows["synthesis:bull_total"] == pytest.approx(0.6, rel=1e-9)
        # the same-source read is recorded as context, never a second vote
        assert any(k.startswith("context:institutional:BULLISH") for k in rows)

    def test_aligned_positioning_institutional_never_sums(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.BULLISH,
            institutional_strength=0.6))
        assert r.signal_strength != pytest.approx(1.1, rel=1e-9)
        assert r.signal_strength != pytest.approx(1.0, rel=1e-9)

    def test_aligned_bearish_pair_single_vote(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP,
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.6))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.6, rel=1e-9)
        assert r.confidence == pytest.approx(CONFIDENCE_AGREEMENT_SINGLE, rel=1e-9)

    def test_institutional_alone_is_full_vote(self):
        r = evaluate_synthesis(_inp(
            institutional_direction=IntelligenceDirection.BULLISH,
            institutional_strength=0.4))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.4, rel=1e-9)

    def test_opposing_positioning_institutional_is_material(self):
        # genuine divergence between the two derivations => both vote
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.5))
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_trap_duplicating_family_vote_adds_no_strength(self):
        # trap pattern derives from the same family evidence: a same-direction
        # duplicate never double-counts
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP,
            trap_direction=IntelligenceDirection.BEARISH,
            trap_strength=0.5))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        rows = _evidence_map(r)
        assert any(k.startswith("context:trap:BEARISH") for k in rows)
        assert rows["synthesis:bear_total"] == pytest.approx(0.5, rel=1e-9)

    def test_trap_duplicate_never_overrides(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.SHORT_BUILDUP,
            trap_direction=IntelligenceDirection.BEARISH,
            trap_strength=0.9))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.direction is IntelligenceDirection.BEARISH

    def test_unique_direction_trap_votes(self):
        # trap counter-context with no duplicating family vote is a vote
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            trap_direction=IntelligenceDirection.BEARISH,
            trap_strength=0.5))
        assert r.direction is IntelligenceDirection.MIXED
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_trap_duplicating_level_vote_no_double_count(self):
        r = evaluate_synthesis(_inp(
            levels=(_level(240.0, LevelKind.SUPPORT,
                           LevelState.CONFLICTED_INTERACTION, 0.7),),
            trap_direction=IntelligenceDirection.BEARISH,
            trap_strength=0.5))
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(0.7, rel=1e-9)


# ---------------------------------------------------------------------------
# 7. Missing vs zero
# ---------------------------------------------------------------------------


class TestMissingVsZero:
    def test_missing_institutional_input_is_absent(self):
        # absent read: bullish positioning stands alone, clean
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_measured_zero_strength_read_is_present_but_never_a_vote(self):
        # measured-zero magnitude cannot support a directional claim
        r = evaluate_synthesis(_inp(
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        rows = _evidence_map(r)
        assert any(k.startswith("read:institutional:BEARISH") for k in rows)

    def test_zero_strength_read_never_blocks_clean_side(self):
        # measured-zero opposing read is not material opposition
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.0))
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)

    def test_missing_level_rows_and_empty_tuple_same_absence(self):
        r1 = evaluate_synthesis(_inp(levels=()))
        r2 = evaluate_synthesis(_inp(positioning=None))
        assert r1.status is r2.status is IntelligenceStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 8. Evidence structure / regime exposure / traceability
# ---------------------------------------------------------------------------


class TestEvidenceStructure:
    def test_regime_read_exposed_in_evidence(self):
        # Day-23's own regime channel stays authoritative; synthesis exposes
        # the read deterministically without fabricating a second channel
        r = evaluate_synthesis(_inp(regime_label=RegimeLabel.RISK_ON,
                                    regime_direction=IntelligenceDirection.BULLISH))
        assert r.regime is None
        rows = _evidence_map(r)
        assert any(k.startswith("bull:regime:RISK_ON") for k in rows)

    def test_every_row_carries_versions_and_timestamp(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.CONFIRM))
        for e in r.evidence:
            assert e.reference_timestamp == _REF
            assert e.model_version == "1.0.0"
            assert e.calculation_version == "1.0.0"

    def test_contract_identity(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.calculation_id == CALCULATION_ID
        assert r.contract_version == INTELLIGENCE_CONTRACT_VERSION

    def test_observation_value_is_strength(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP))
        assert r.observation.value == pytest.approx(0.5, rel=1e-9)
        assert r.observation.unit == "score_0_1"

    def test_strength_confidence_quality_separate(self):
        q = _quality()
        r = evaluate_synthesis(_inp(
            quality=q, positioning=PositioningClassification.LONG_BUILDUP))
        assert r.signal_strength == pytest.approx(0.5, rel=1e-9)
        assert r.confidence == pytest.approx(0.75, rel=1e-9)
        assert r.quality is q
        assert r.signal_strength != r.confidence
        assert r.confidence != r.quality.quality_score


# ---------------------------------------------------------------------------
# 9. Determinism + serialization
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_evaluation_identical(self):
        inp = _inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.DIVERGE,
            institutional_direction=IntelligenceDirection.BULLISH,
            institutional_strength=0.4,
            regime_label=RegimeLabel.RISK_ON,
            regime_direction=IntelligenceDirection.BULLISH)
        first = evaluate_synthesis(inp).to_dict()
        for _ in range(3):
            assert evaluate_synthesis(inp).to_dict() == first

    def test_serialization_round_trip(self):
        r = evaluate_synthesis(_inp(
            positioning=PositioningClassification.LONG_BUILDUP,
            price_flow_relation=PriceFlowRelation.CONFIRM,
            institutional_direction=IntelligenceDirection.BEARISH,
            institutional_strength=0.3))
        rebuilt = IntelligenceResult.from_dict(r.to_dict())
        assert rebuilt.to_dict() == r.to_dict()

    def test_serialization_round_trip_no_direction(self):
        r = evaluate_synthesis(_inp(
            institutional_direction=IntelligenceDirection.MIXED))
        rebuilt = IntelligenceResult.from_dict(r.to_dict())
        assert rebuilt.to_dict() == r.to_dict()

    def test_serialization_round_trip_unavailable(self):
        r = evaluate_synthesis(_inp(positioning=None))
        rebuilt = IntelligenceResult.from_dict(r.to_dict())
        assert rebuilt.to_dict() == r.to_dict()


# ---------------------------------------------------------------------------
# 10. Purity (AST guard)
# ---------------------------------------------------------------------------


class TestPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "synthesis.py"

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

    def test_no_wall_clock_or_random_tokens_in_module(self):
        text = self._MODULE.read_text(encoding="utf-8")
        for token in ("datetime.now", "datetime.utcnow", "time.time()",
                      "uuid", "random."):
            assert token not in text
