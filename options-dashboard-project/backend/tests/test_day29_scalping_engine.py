"""Day 29 — Scalping Opportunity Engine tests (RED-phase contract).

Proves the deterministic scalping layer on the Day-28 pipeline:

    typed channel evidence (intelligence results)
        -> freshness evaluation (caller-supplied as_of, explicit policy)
        -> eligibility / suppression cascade
        -> Day-28 chain (Observation -> Signal -> Setup -> Opportunity)
        -> deterministic ranking
        STOP at Opportunity -- never an order, never an execution intent.

Rules locked by these tests
---------------------------
1. Freshness is explicit and deterministic: ``as_of`` is caller-supplied
   (the engine never reads the wall clock); reference timestamps are never
   invented; missing timestamps are never treated as fresh; a future
   timestamp is invalid, never fresh.  Defaults mirror the Day-12
   freshness semantics (fresh <= 60s, stale > 300s).
2. Fresh evidence is accepted; DECAYING evidence (60s < age <= 300s)
   degrades rank but does not drop the candidate; STALE evidence (age >
   300s) suppresses the candidate (gate: degrade or suppress safely).
3. Interpretation requirements mirror Days 20-26/28: SUCCESS status,
   BULLISH/BEARISH direction, present-and-usable quality
   (state != INSUFFICIENT; DEGRADED usable and visible), present horizon.
4. Missing != zero: absent context roles are not opposing evidence, not
   agreement, and not a suppression; missing quality is never upgraded;
   missing timestamps are never fresh.
5. Only a SUCCESS directional context read can oppose or corroborate the
   interpretation direction; NEUTRAL / MIXED / UNKNOWN / PARTIAL context
   never opposes.  Role labels never drive direction.
6. Ranking is a documented additive formula over freshness, Day-12
   quality index, signal strength and confidence (weights sum to 1.0);
   deterministic ordering (rank desc, then underlying/candidate_id asc);
   stale candidates can never be ranked; identical inputs => identical
   output.
7. A ranked candidate wraps the *unchanged* Day-28 Opportunity
   (CANDIDATE, thesis, evidence chain, regime/horizon/quality/provenance
   preserved by identity); ids are deterministic.
8. Purity: no wall clock / random / UUID / network / DB / broker /
   filesystem behavior (AST-guarded); no order/execution vocabulary.

Golden arithmetic (independent)
-------------------------------
Single eligible candidate, interpretation + 1 context, both FRESH,
quality EXCELLENT 95, strength 0.5, confidence 0.75:
    fresh_component = 1.0
    rank = 0.30*1.00 + 0.25*0.95 + 0.25*0.50 + 0.20*0.75 = 0.8125
Same with the context DECAYING:
    fresh_component = (1.0 + 0.75)/2 = 0.875
    rank = 0.30*0.875 + 0.2375 + 0.125 + 0.15 = 0.7750
Interpretation alone DECAYING:
    fresh_component = 0.75 -> rank = 0.7375 (degraded, still ranked)
Strength 0.8 vs 0.3 (same otherwise): 0.8875 vs 0.7625.
Stale interpretation (age > 300s): suppressed STALE_EVIDENCE.
Age == 60s -> FRESH ranked; age == 300s -> DECAYING ranked;
age > 300s -> STALE suppressed.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    EvidenceType,
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceIssue,
    IntelligenceIssueCode,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    MarketRegime,
    RegimeLabel,
    TimeHorizon,
)
from app.opportunity.contracts import (
    ExpectedBehavior,
    Opportunity,
    OpportunityStatus,
)
from app.opportunity.scalping import (  # module absent until GREEN
    EvidenceRole,
    FreshnessState,
    ScalpingCandidateInput,
    ScalpingFreshnessPolicy,
    ScalpingInput,
    ScalpingStatus,
    SuppressionReason,
    evaluate_scalping,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"
SYNTH = "intelligence.synthesis.v1"
FLOW_ID = "intelligence.flow_divergence.v1"


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX_SNAPSHOT_NORMALIZED",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=_REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quality(state: QualityState = QualityState.EXCELLENT,
             score: int | None = None) -> QualityResult:
    quality_score = 95 if state is QualityState.EXCELLENT else 55
    if score is not None:
        quality_score = score
    return QualityResult(
        quality_score=quality_score,
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


def _regime(label: RegimeLabel = RegimeLabel.TRENDING) -> MarketRegime:
    return MarketRegime(label=label, source="intelligence.regime.v1",
                        model_version="1.0.0", reference_timestamp=_REF)


def _evidence(value: float = 0.5, key: str = "bull:test") -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=f"synthesis:{NIFTY}:2026-09-24:{key}",
        evidence_type=EvidenceType.QUANT_DERIVED,
        value=value,
        unit="score_0_1",
        reference_timestamp=_REF,
        provenance=_prov(),
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


def _result(*, direction: IntelligenceDirection | None = IntelligenceDirection.BULLISH,
            status: IntelligenceStatus = IntelligenceStatus.SUCCESS,
            strength: float | None = 0.5,
            confidence: float | None = 0.75,
            horizon: TimeHorizon | None = TimeHorizon.EXPIRY,
            quality=_UNSET, regime=None, calc_id: str = SYNTH,
            issue_codes: tuple[IntelligenceIssueCode, ...] = (),
            ts: datetime | None = _REF, evidence_value: float = 0.5,
            ev_key: str = "bull:test") -> IntelligenceResult:
    q = quality if quality is not _UNSET else _quality()
    issues = tuple(
        IntelligenceIssue(code=c, message=c.value) for c in issue_codes
    ) if issue_codes else ()
    if status is IntelligenceStatus.SUCCESS:
        return IntelligenceResult(
            calculation_id=calc_id,
            status=status,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=IntelligenceObservation(
                metric_name="synthesis_strength",
                value=float(strength or 0.0), unit="score_0_1"),
            evidence=(_evidence(evidence_value, ev_key),),
            regime=regime,
            quality=q,
            provenance=_prov(),
            reference_timestamp=ts,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version="1.0.0",
            calculation_version="1.0.0",
            issues=issues,
        )
    if status is IntelligenceStatus.PARTIAL:
        return IntelligenceResult(
            calculation_id=calc_id,
            status=status,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=None,
            evidence=(_evidence(evidence_value, ev_key),),
            regime=regime,
            quality=q,
            provenance=_prov(),
            reference_timestamp=ts,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version="1.0.0",
            calculation_version="1.0.0",
            issues=issues or (
                IntelligenceIssue(code=IntelligenceIssueCode.MISSING_EVIDENCE,
                                  message="partial"),
            ),
        )
    return IntelligenceResult(
        calculation_id=calc_id,
        status=status,
        direction=None,
        signal_strength=None,
        confidence=None,
        time_horizon=None,
        observation=None,
        evidence=(),
        regime=regime,
        quality=q,
        provenance=_prov(),
        reference_timestamp=ts,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="1.0.0",
        calculation_version="1.0.0",
        issues=issues or (
            IntelligenceIssue(code=IntelligenceIssueCode.MISSING_EVIDENCE,
                              message="unavailable"),
        ),
    )


def _cand(candidate_id: str = "c1", underlying: str = NIFTY,
          result: IntelligenceResult | None = None,
          context: tuple = (), expiry: str = "2026-09-24") -> ScalpingCandidateInput:
    return ScalpingCandidateInput(
        candidate_id=candidate_id,
        underlying=underlying,
        expiry=expiry,
        interpretation=result if result is not None else _result(),
        context=context,
    )


def _ctx(role: EvidenceRole, result: IntelligenceResult):
    from app.opportunity.scalping import ContextEvidence
    return ContextEvidence(role=role, result=result)


def _asof(offset_seconds: float = 0.0) -> datetime:
    return _REF + timedelta(seconds=offset_seconds)


def _ages(seconds: float) -> datetime:
    return _REF + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# 1. Policy + input validation
# ---------------------------------------------------------------------------


class TestPolicyAndInput:
    def test_defaults_mirror_day12_freshness_semantics(self):
        p = ScalpingFreshnessPolicy()
        assert p.fresh_seconds == 60.0
        assert p.stale_seconds == 300.0

    def test_policy_requires_positive_ordered_finite_thresholds(self):
        with pytest.raises(ValueError):
            ScalpingFreshnessPolicy(fresh_seconds=0.0)
        with pytest.raises(ValueError):
            ScalpingFreshnessPolicy(stale_seconds=0.0)
        with pytest.raises(ValueError):
            ScalpingFreshnessPolicy(fresh_seconds=400.0, stale_seconds=300.0)
        with pytest.raises(ValueError):
            ScalpingFreshnessPolicy(fresh_seconds=float("nan"))

    def test_candidate_requires_text_fields(self):
        with pytest.raises(ValueError):
            ScalpingCandidateInput(candidate_id="", underlying=NIFTY,
                                   interpretation=_result())
        with pytest.raises(ValueError):
            ScalpingCandidateInput(candidate_id="c1", underlying="",
                                   interpretation=_result())
        with pytest.raises(ValueError):
            ScalpingCandidateInput(candidate_id="c1", underlying=NIFTY,
                                   interpretation=None)  # type: ignore[arg-type]

    def test_candidate_context_items_must_be_typed(self):
        with pytest.raises(ValueError):
            ScalpingCandidateInput(candidate_id="c1", underlying=NIFTY,
                                   interpretation=_result(),
                                   context=("not-a-context",))  # type: ignore[assignment]

    def test_naive_as_of_rejected(self):
        inp = ScalpingInput(
            candidates=(_cand(),),
            as_of=datetime(2026, 9, 3, 10, 0, 0),  # naive
        )
        with pytest.raises(ValueError):
            evaluate_scalping(inp)

    def test_empty_candidates_yields_empty(self):
        r = evaluate_scalping(ScalpingInput(candidates=(), as_of=_asof()))
        assert r.status is ScalpingStatus.EMPTY
        assert r.ranked == ()
        assert r.suppressed == ()

    def test_missing_as_of_suppresses_every_candidate(self):
        r = evaluate_scalping(ScalpingInput(candidates=(_cand("a"), _cand("b"))))
        assert r.status is ScalpingStatus.NOTHING_ELIGIBLE
        assert r.ranked == ()
        assert [s.reason for s in r.suppressed] == \
            [SuppressionReason.NO_REFERENCE_TIME] * 2


# ---------------------------------------------------------------------------
# 2. Freshness matrix
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_fresh_interpretation_is_ranked(self):
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(),), as_of=_asof(0.0)))
        assert r.status is ScalpingStatus.SUCCESS
        assert len(r.ranked) == 1
        assert r.suppressed == ()

    def test_age_exactly_fresh_boundary_is_fresh(self):
        # age == fresh_seconds (60.0) -> FRESH -> ranked
        cand = _cand(result=_result(ts=_REF))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(60.0)))
        assert len(r.ranked) == 1
        assert r.ranked[0].evidence_freshness[0].state is FreshnessState.FRESH

    def test_age_just_over_fresh_is_decaying_but_ranked(self):
        cand = _cand(result=_result(ts=_REF))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(60.000001)))
        assert len(r.ranked) == 1
        assert r.ranked[0].evidence_freshness[0].state is FreshnessState.DECAYING

    def test_age_exactly_stale_is_decaying_not_stale(self):
        cand = _cand(result=_result(ts=_REF))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(300.0)))
        assert len(r.ranked) == 1  # decaying at the stale boundary
        assert r.ranked[0].evidence_freshness[0].state is FreshnessState.DECAYING

    def test_stale_interpretation_suppressed(self):
        cand = _cand(result=_result(ts=_REF))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(300.000001)))
        assert r.status is ScalpingStatus.NOTHING_ELIGIBLE
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.STALE_EVIDENCE
        assert "300" in r.suppressed[0].detail

    def test_stale_context_suppresses(self):
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BULLISH, calc_id=FLOW_ID,
            ts=_ages(-400.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof(0.0)))
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.STALE_EVIDENCE

    def test_decaying_context_degrades_rank_not_eligibility(self):
        fresh = _cand("fresh", result=_result(
            strength=0.5, confidence=0.75, ts=_ages(0.0)))
        # context 400s old would be stale; 100s old is decaying
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BULLISH, calc_id=FLOW_ID,
            ts=_ages(-100.0)))
        dec = _cand("dec", result=_result(
            strength=0.5, confidence=0.75, ts=_ages(0.0)),
            context=(ctx,))
        r = evaluate_scalping(ScalpingInput(
            candidates=(fresh, dec), as_of=_asof(0.0)))
        ids = [x.candidate_id for x in r.ranked]
        assert ids == ["fresh", "dec"]          # both ranked
        assert r.ranked[0].rank == pytest.approx(0.8125, rel=1e-9)   # all FRESH
        assert r.ranked[1].rank == pytest.approx(0.7750, rel=1e-9)   # 0.875 mean

    def test_missing_timestamp_never_fresh(self):
        # SUCCESS requires an aware ts by contract, so use a PARTIAL
        # interpretation-quality context whose ts is None -> NO_TIMESTAMP
        ctx = _ctx(EvidenceRole.REGIME, _result(
            status=IntelligenceStatus.PARTIAL, ts=None))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof(0.0)))
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.NO_TIMESTAMP

    def test_future_timestamp_is_invalid_never_fresh(self):
        cand = _cand(result=_result(ts=_ages(+120.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(0.0)))
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.INVALID_TIMESTAMP

    def test_custom_policy_thresholds_are_honored(self):
        p = ScalpingFreshnessPolicy(fresh_seconds=10.0, stale_seconds=30.0)
        # age 20s -> decaying under the strict policy -> still ranked
        cand = _cand(result=_result(ts=_REF))
        r = evaluate_scalping(ScalpingInput(
            candidates=(cand,), as_of=_asof(20.0), policy=p))
        assert len(r.ranked) == 1
        # age 40s -> stale under the strict policy -> suppressed
        cand2 = _cand(result=_result(ts=_REF))
        r2 = evaluate_scalping(ScalpingInput(
            candidates=(cand2,), as_of=_asof(40.0), policy=p))
        assert r2.ranked == ()
        assert r2.suppressed[0].reason is SuppressionReason.STALE_EVIDENCE


# ---------------------------------------------------------------------------
# 3. Interpretation gates (status / quality / direction)
# ---------------------------------------------------------------------------


class TestInterpretationGates:
    def test_partial_interpretation_suppressed(self):
        cand = _cand(result=_result(status=IntelligenceStatus.PARTIAL))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.UNINTERPRETABLE

    def test_unavailable_interpretation_suppressed(self):
        cand = _cand(result=_result(status=IntelligenceStatus.UNAVAILABLE))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.UNINTERPRETABLE

    def test_missing_quality_never_upgraded(self):
        # missing Day-12 quality surfaces upstream as PARTIAL (Day-19
        # contract: SUCCESS requires the preserved QualityResult) -- the
        # status gate suppresses it; missing quality is never upgraded
        cand = _cand(result=_result(status=IntelligenceStatus.PARTIAL,
                                    quality=None))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.UNINTERPRETABLE

    def test_success_with_quality_none_is_not_constructible(self):
        # guards the invariant: a SUCCESS directional read always carries
        # the preserved Day-12 QualityResult (Day-19 contract)
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.SUCCESS, quality=None)

    def test_insufficient_quality_suppressed(self):
        cand = _cand(result=_result(quality=_quality(QualityState.INSUFFICIENT)))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.INSUFFICIENT_QUALITY

    def test_degraded_quality_usable_and_visible(self):
        q = _quality(QualityState.DEGRADED)
        cand = _cand(result=_result(quality=q))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert len(r.ranked) == 1
        assert r.ranked[0].opportunity.quality is q
        assert r.ranked[0].opportunity.quality.quality_state is QualityState.DEGRADED

    def test_neutral_direction_suppressed(self):
        cand = _cand(result=_result(
            direction=IntelligenceDirection.NEUTRAL, strength=0.0))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.NON_DIRECTIONAL

    def test_unknown_direction_suppressed(self):
        cand = _cand(result=_result(
            direction=IntelligenceDirection.UNKNOWN, strength=0.4,
            confidence=0.6))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.NON_DIRECTIONAL

    def test_mixed_direction_suppressed(self):
        cand = _cand(result=_result(
            direction=IntelligenceDirection.MIXED, strength=0.4))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert r.suppressed[0].reason is SuppressionReason.NON_DIRECTIONAL

    def test_bearish_interpretation_supported(self):
        cand = _cand(result=_result(direction=IntelligenceDirection.BEARISH))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        assert len(r.ranked) == 1
        assert r.ranked[0].opportunity.direction is IntelligenceDirection.BEARISH


# ---------------------------------------------------------------------------
# 4. Context / conflict semantics
# ---------------------------------------------------------------------------


class TestContextAndConflict:
    def test_agreeing_directional_context_ranked(self):
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BULLISH, calc_id=FLOW_ID,
            ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        assert len(r.ranked) == 1
        assert r.suppressed == ()

    def test_opposing_directional_context_suppressed(self):
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BEARISH, calc_id=FLOW_ID,
            ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.CONFLICTED_CONTEXT

    def test_opposing_direction_with_stronger_context_still_suppressed(self):
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BEARISH, calc_id=FLOW_ID,
            strength=0.9, confidence=0.95, ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        assert r.ranked == ()
        assert r.suppressed[0].reason is SuppressionReason.CONFLICTED_CONTEXT

    def test_neutral_context_never_opposes(self):
        ctx = _ctx(EvidenceRole.EVENT_EXPIRY, _result(
            direction=IntelligenceDirection.NEUTRAL,
            calc_id="intelligence.expiry_event.v1", strength=0.0,
            ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        assert len(r.ranked) == 1
        assert r.suppressed == ()

    def test_unknown_and_mixed_context_never_oppose(self):
        for d in (IntelligenceDirection.UNKNOWN, IntelligenceDirection.MIXED):
            ctx = _ctx(EvidenceRole.REGIME, _result(
                direction=d, calc_id="intelligence.regime.v1",
                strength=0.4, confidence=0.6, ts=_ages(0.0)))
            r = evaluate_scalping(ScalpingInput(
                candidates=(_cand(context=(ctx,)),), as_of=_asof()))
            assert len(r.ranked) == 1, d

    def test_no_context_is_missing_not_opposition(self):
        # an interpretation with zero context is eligible (fresh alone)
        r = evaluate_scalping(ScalpingInput(candidates=(_cand(),), as_of=_asof()))
        assert len(r.ranked) == 1
        assert len(r.ranked[0].evidence_freshness) == 1  # interpretation only

    def test_role_label_never_drives_direction(self):
        # the SAME bearish result is opposing whatever role labels it
        bear = _result(direction=IntelligenceDirection.BEARISH,
                       calc_id=FLOW_ID, ts=_ages(0.0))
        for role in (EvidenceRole.FLOW, EvidenceRole.POSITIONING,
                     EvidenceRole.GEX_GAMMA):
            r = evaluate_scalping(ScalpingInput(
                candidates=(_cand(context=(_ctx(role, bear),)),), as_of=_asof()))
            assert r.suppressed[0].reason is SuppressionReason.CONFLICTED_CONTEXT

    def test_context_quality_does_not_gate(self):
        # context quality is not a gate; only its freshness/direction are
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BULLISH, calc_id=FLOW_ID,
            quality=_quality(QualityState.INSUFFICIENT), ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        assert len(r.ranked) == 1


# ---------------------------------------------------------------------------
# 5. Ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_golden_single_candidate_rank(self):
        cand = _cand(result=_result(strength=0.5, confidence=0.75))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        # interpretation alone, FRESH: fresh_component 1.0
        # 0.30*1.0 + 0.25*0.95 + 0.25*0.5 + 0.20*0.75
        assert r.ranked[0].rank == pytest.approx(0.8125, rel=1e-9)

    def test_strength_outranks_weakness(self):
        a = _cand("a", result=_result(strength=0.8, confidence=0.75))
        b = _cand("b", result=_result(strength=0.3, confidence=0.75))
        r = evaluate_scalping(ScalpingInput(candidates=(a, b), as_of=_asof()))
        assert [x.candidate_id for x in r.ranked] == ["a", "b"]
        assert r.ranked[0].rank == pytest.approx(0.8875, rel=1e-9)
        assert r.ranked[1].rank == pytest.approx(0.7625, rel=1e-9)

    def test_quality_difference_orders(self):
        high = _cand("hi", result=_result(strength=0.5, confidence=0.75,
                                          quality=_quality(QualityState.EXCELLENT)))
        low = _cand("lo", result=_result(strength=0.5, confidence=0.75,
                                         quality=_quality(QualityState.DEGRADED)))
        r = evaluate_scalping(ScalpingInput(candidates=(low, high), as_of=_asof()))
        assert [x.candidate_id for x in r.ranked] == ["hi", "lo"]
        assert r.ranked[1].rank == pytest.approx(0.7125, rel=1e-9)

    def test_decaying_interpretation_ranks_below_identical_fresh(self):
        fresh = _cand("f", result=_result(strength=0.5, confidence=0.75,
                                          ts=_ages(0.0)))
        dec = _cand("d", result=_result(strength=0.5, confidence=0.75,
                                        ts=_ages(-100.0)))
        r = evaluate_scalping(ScalpingInput(candidates=(fresh, dec), as_of=_asof()))
        assert [x.candidate_id for x in r.ranked] == ["f", "d"]
        assert r.ranked[0].rank == pytest.approx(0.8125, rel=1e-9)
        assert r.ranked[1].rank == pytest.approx(0.7375, rel=1e-9)  # 0.75 comp

    def test_stale_never_ranked(self):
        stale = _cand("s", result=_result(strength=0.9, confidence=0.95,
                                          quality=_quality(score=100),
                                          ts=_ages(-500.0)))
        fresh = _cand("f", result=_result(strength=0.1, confidence=0.1,
                                          ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(candidates=(stale, fresh), as_of=_asof()))
        assert [x.candidate_id for x in r.ranked] == ["f"]
        assert [s.candidate_id for s in r.suppressed] == ["s"]
        assert r.suppressed[0].reason is SuppressionReason.STALE_EVIDENCE

    def test_tie_breaks_by_candidate_id_deterministically(self):
        same = _result()
        a = _cand("b-cand", result=same)
        b = _cand("a-cand", result=_result())
        r = evaluate_scalping(ScalpingInput(candidates=(a, b), as_of=_asof()))
        assert [x.candidate_id for x in r.ranked] == ["a-cand", "b-cand"]

    def test_repeated_execution_identical(self):
        cands = tuple(
            _cand(c, result=_result(strength=0.1 * (i + 1))) for i, c in
            enumerate(("c1", "c2", "c3", "c4")))
        r1 = evaluate_scalping(ScalpingInput(candidates=cands, as_of=_asof()))
        r2 = evaluate_scalping(ScalpingInput(candidates=cands, as_of=_asof()))
        assert [(x.candidate_id, round(x.rank, 12)) for x in r1.ranked] == \
            [(x.candidate_id, round(x.rank, 12)) for x in r2.ranked]
        assert [s.candidate_id for s in r1.suppressed] == \
            [s.candidate_id for s in r2.suppressed]

    def test_rank_bounded_and_explained(self):
        cand = _cand(result=_result(strength=1.0, confidence=1.0,
                                    quality=_quality(score=100)))
        r = evaluate_scalping(ScalpingInput(candidates=(cand,), as_of=_asof()))
        top = r.ranked[0]
        assert top.rank == pytest.approx(1.0, rel=1e-9)
        assert top.explanation
        assert "0.30" in top.explanation and "0.25" in top.explanation


# ---------------------------------------------------------------------------
# 6. Day-28 Opportunity integration
# ---------------------------------------------------------------------------


class TestOpportunityIntegration:
    def test_ranked_wraps_day28_opportunity(self):
        r = evaluate_scalping(ScalpingInput(candidates=(_cand(),), as_of=_asof()))
        opp = r.ranked[0].opportunity
        assert isinstance(opp, Opportunity)
        assert opp.status is OpportunityStatus.CANDIDATE
        assert opp.direction is IntelligenceDirection.BULLISH
        assert opp.expected_behavior is ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE
        assert opp.invalidation_conditions
        assert opp.thesis

    def test_upstream_identity_preserved_through_chain(self):
        result = _result(regime=_regime())
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(result=result),), as_of=_asof()))
        opp = r.ranked[0].opportunity
        assert opp.upstream is result
        assert opp.regime is result.regime
        assert opp.quality is result.quality
        assert opp.time_horizon is TimeHorizon.EXPIRY
        assert opp.evidence == result.evidence

    def test_deterministic_ids_from_candidate_id(self):
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand("k1"),), as_of=_asof()))
        opp = r.ranked[0].opportunity
        assert opp.opportunity_id == "opp-k1"
        assert opp.setup_id == "stp-k1"
        assert opp.underlying == NIFTY
        assert opp.expiry == "2026-09-24"

    def test_suppressed_candidates_never_create_opportunities(self):
        stale = _cand("s", result=_result(ts=_ages(-500.0)))
        neutral = _cand("n", result=_result(
            direction=IntelligenceDirection.NEUTRAL, strength=0.0))
        r = evaluate_scalping(ScalpingInput(
            candidates=(stale, neutral), as_of=_asof()))
        assert r.status is ScalpingStatus.NOTHING_ELIGIBLE
        assert r.ranked == ()
        assert len(r.suppressed) == 2

    def test_evidence_freshness_rows_cover_all_supplied(self):
        ctx = _ctx(EvidenceRole.REGIME, _result(
            direction=IntelligenceDirection.BULLISH,
            calc_id="intelligence.regime.v1", ts=_ages(0.0)))
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand(context=(ctx,)),), as_of=_asof()))
        rows = r.ranked[0].evidence_freshness
        assert len(rows) == 2
        assert all(x.state is FreshnessState.FRESH for x in rows)


# ---------------------------------------------------------------------------
# 7. Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_result_round_trip(self):
        ctx = _ctx(EvidenceRole.FLOW, _result(
            direction=IntelligenceDirection.BEARISH, calc_id=FLOW_ID,
            ts=_ages(0.0)))
        stale = _cand("s", result=_result(ts=_ages(-500.0)))
        good = _cand("g", result=_result(strength=0.5, confidence=0.75),
                     context=(ctx,))
        r = evaluate_scalping(ScalpingInput(
            candidates=(stale, good), as_of=_asof()))
        assert r.status is ScalpingStatus.NOTHING_ELIGIBLE
        data = r.to_dict()
        blob = json.dumps(data)
        assert isinstance(blob, str)
        r2 = type(r).from_dict(json.loads(blob))
        assert r2.to_dict() == data

    def test_success_round_trip(self):
        r = evaluate_scalping(ScalpingInput(
            candidates=(_cand("a"), _cand("b")), as_of=_asof()))
        assert r.status is ScalpingStatus.SUCCESS
        r2 = type(r).from_dict(json.loads(json.dumps(r.to_dict())))
        assert r2.to_dict() == r.to_dict()
        assert len(r2.ranked) == 2
        assert isinstance(r2.ranked[0].opportunity, Opportunity)


# ---------------------------------------------------------------------------
# 8. Purity / execution boundary
# ---------------------------------------------------------------------------


class TestPurityAndBoundary:
    _MOD = pathlib.Path(__file__).resolve().parents[1] / "app" / "opportunity" / "scalping.py"

    def test_no_broker_or_execution_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi",
                     "redis", "time"}
        tree = ast.parse(self._MOD.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today", "time",
                                              "sleep"}
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for banned in ("app.brokers", "app.services", "app.routers",
                               "app.quant", "app.market_data.gateway",
                               "app.streaming", "app.db"):
                    assert not module.startswith(banned)

    def test_no_order_execution_vocabulary(self):
        text = self._MOD.read_text(encoding="utf-8").lower()
        for token in ("place_order", "submit_order", "modify_order",
                      "cancel_order", "create_order", "order_router",
                      "broker_client", "execute("):
            assert token not in text

    def test_no_wall_clock_or_random_tokens(self):
        text = self._MOD.read_text(encoding="utf-8")
        for token in ("datetime.now", "datetime.utcnow", "uuid", "random.",
                      "time.time()"):
            assert token not in text
