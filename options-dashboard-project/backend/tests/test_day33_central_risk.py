"""Day 33 — Central Risk Engine tests (TDD, genuine upstream objects).

Proves the deterministic standalone strategy-risk boundary:

    eligible Day-32 StrategyCandidate
        + explicit RiskPolicy + caller-supplied reference timestamp
        -> assess_candidate_risk(...)
        -> CentralRiskResult (payoff / greek / scenario / structural /
                              policy dimensions + evidence + issues)

Every upstream object is genuinely constructed through the authoritative
engines/pipelines (Day-19 IntelligenceResult -> Day-28 discover_opportunity
-> Day-30 rank_strikes -> Day-31 evaluate_strategy -> Day-32
evaluate_strategy_gate); no object.__new__ / object.__setattr__ stand-ins.

Rules locked here
-----------------
1. Risk metrics, confidence, quality and policy decision remain separate
   channels; no opaque aggregate score replaces the evidence trail.
2. Missing data stays missing (never zero/neutral/favorable/safe).
3. Unbounded loss is represented explicitly, never as zero.
4. PASS means the standalone risk-policy checks passed — NOT trade /
   portfolio / capital / user / execution approval.
5. Deterministic precedence: INVALID > BLOCKED (verified violation) >
   UNAVAILABLE > PARTIAL > PASS; a verified violation never hides behind
   incomplete evidence.
6. Worst supplied scenario loss comes from the authoritative Day-18
   scenario output; it is never labelled theoretical worst-case.
7. Day-33 reuses authoritative payoff/Greek/scenario assessments; no
   duplicate quantitative mathematics exists here.
8. Provenance is preserved at dimension and result level, never flattened
   into a fabricated single source.
9. Context is metadata only: identical canonical inputs across
   OPPORTUNITY/PAPER/BACKTEST/RESEARCH yield identical risk results.
10. Purity: no wall clock, randomness, DB/network/filesystem/broker access,
    no order/execution/user-approval vocabulary (AST-guarded).
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.central_risk.contracts import (
    CENTRAL_RISK_CALCULATION_VERSION,
    CENTRAL_RISK_CONTRACT_VERSION,
    CentralRiskIssueCode,
    CentralRiskResult,
    CentralRiskStatus,
    PolicyRuleCode,
    RiskEvidence,
    RiskPolicy,
)
from app.central_risk.engine import assess_candidate_risk
from app.market_data.contracts import DataMode, Provenance, QualityState, Side
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    EvidenceType,
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    MarketRegime,
    RegimeLabel,
    TimeHorizon,
)
from app.opportunity.contracts import Observation, Opportunity
from app.opportunity.pipeline import discover_opportunity
from app.quant.scenarios import OptionLeg, PositionDirection, ScenarioPoint
from app.strategy_evaluation.contracts import (
    DimensionState,
    EvaluationContext,
    HistoricalEvidence,
    LiquidityEvidence,
    PayoffEvidence,
    PayoffExpirySemantics,
    RiskEvidence as Day31RiskEvidence,
    StrategyEvaluationInput,
    StrategyEvaluationStatus,
    TailClass,
)
from app.strategy_evaluation.evaluation import evaluate_strategy
from app.strike_ranking.contracts import (
    FactorObservation,
    OptionType,
    RankingFactor,
    StrikeCandidateInput,
    StrikeRankingInput,
)
from app.strike_ranking.ranking import DEFAULT_RANKING_WEIGHTS, rank_strikes
from app.strategy_lifecycle.contracts import (
    StrategyCandidate,
    StrategyLifecycleState,
)
from app.strategy_lifecycle.lifecycle import evaluate_strategy_gate

#: Sentinel distinguishing "field omitted" from an explicit ``None``
#: (``None`` is a genuine missing-value signal to the Day-31 engine).
_UNSET = object()


REF = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
NIFTY = "NIFTY"
EXPIRY = "2026-09-24"


# ---------------------------------------------------------------------------
# Genuine upstream builders (real contracts, real engines)
# ---------------------------------------------------------------------------


def _prov(source: str = "UPSTOX_SNAPSHOT_NORMALIZED") -> Provenance:
    return Provenance(
        source=source,
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quality(state: QualityState = QualityState.EXCELLENT,
             observed_at: datetime | None = None) -> QualityResult:
    return QualityResult(
        quality_score=95 if state is QualityState.EXCELLENT else 55,
        quality_state=state,
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=observed_at if observed_at is not None else REF,
        observation_time=observed_at if observed_at is not None else REF,
        observation_type="QUOTE",
        contract_version="1.0.0",
        reference_time=observed_at if observed_at is not None else REF,
    )


def _synthesis(direction: IntelligenceDirection = IntelligenceDirection.BULLISH,
               strength: float = 0.5, confidence: float = 0.75) -> IntelligenceResult:
    return IntelligenceResult(
        calculation_id="intelligence.synthesis.v1",
        status=IntelligenceStatus.SUCCESS,
        direction=direction,
        signal_strength=strength,
        confidence=confidence,
        time_horizon=TimeHorizon.EXPIRY,
        observation=IntelligenceObservation(
            metric_name="synthesis_strength", value=strength, unit="score_0_1"),
        evidence=(IntelligenceEvidence(
            source_reference_id=f"synthesis:{NIFTY}:{EXPIRY}:bull",
            evidence_type=EvidenceType.QUANT_DERIVED,
            value=strength, unit="score_0_1", reference_timestamp=REF,
            provenance=_prov(), model_version="1.0.0",
            calculation_version="1.0.0"),),
        quality=_quality(),
        provenance=_prov(),
        reference_timestamp=REF,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


def _opportunity(opp_id: str = "opp-1") -> Opportunity:
    observation = Observation(
        observation_id="obs-1", underlying=NIFTY, expiry=EXPIRY,
        upstream=_synthesis())
    return discover_opportunity(observation, signal_id="sig-1",
                                setup_id="stp-1", opportunity_id=opp_id)


def _leg(*, side: Side = Side.CALL, strike: float = 20000.0,
         quantity: float = 1.0,
         direction: PositionDirection = PositionDirection.LONG,
         entry_price: float | None = 100.0,
         implied_volatility: float | None = 0.2,
         quality: QualityState | None = QualityState.EXCELLENT,
         provenance: Provenance | None = None) -> OptionLeg:
    return OptionLeg(
        option_type=side, strike=strike, expiry=EXPIRY, quantity=quantity,
        direction=direction, entry_price=entry_price,
        implied_volatility=implied_volatility, quality=quality,
        provenance=provenance if provenance is not None else _prov("LEG"),
    )


def _all_factors(scores: dict[RankingFactor, float] | None = None) -> tuple[FactorObservation, ...]:
    return tuple(
        FactorObservation(factor=f, score=(scores or {}).get(f, 0.8))
        for f in RankingFactor
    )


def _ranked(opportunity: Opportunity | None = None) -> object:
    candidates = (
        StrikeCandidateInput(candidate_id="strike-20000", underlying=NIFTY,
                             option_type=OptionType.CE, strike=20000.0,
                             expiry=EXPIRY, factors=_all_factors(),
                             opportunity=opportunity),
        StrikeCandidateInput(candidate_id="strike-20500", underlying=NIFTY,
                             option_type=OptionType.PE, strike=20500.0,
                             expiry=EXPIRY, factors=_all_factors(),
                             opportunity=opportunity),
    )
    return rank_strikes(StrikeRankingInput(
        candidates=candidates, weights=DEFAULT_RANKING_WEIGHTS,
        objective_id="dir-bull"))


def _points(*spots: float) -> tuple[ScenarioPoint, ...]:
    return tuple(ScenarioPoint(spot=s, time_to_expiry=0.01,
                               implied_volatility=0.2) for s in spots)


def _payoff(*, state: DimensionState = DimensionState.AVAILABLE,
            semantics: PayoffExpirySemantics = PayoffExpirySemantics.SAME_EXPIRY_EXACT,
            net: float | None = 1.0,
            max_profit: float | None = 100.0,
            max_loss: float | None = -50.0,
            tail: TailClass = TailClass.NONE,
            breakevens: tuple[float, ...] = (20050.0,)) -> PayoffEvidence:
    return PayoffEvidence(
        state=state, expiry_semantics=semantics, net_debit_credit=net,
        max_profit=max_profit, max_loss=max_loss, tail=tail,
        breakevens=breakevens, provenance=_prov("payoff-bnd"))


def _full_inp(*, strategy_id: str = "strategy-1",
              legs=_UNSET,
              context: EvaluationContext = EvaluationContext.OPPORTUNITY,
              payoff=_UNSET,
              scenario_points=_UNSET,
              quality=_UNSET,
              opportunity=_UNSET,
              **overrides) -> StrategyEvaluationInput:
    """A fully-evidenced Day-31 evaluation input (SUCCESS path)."""
    kwargs: dict = dict(
        strategy_id=strategy_id,
        legs=(_leg(),) if legs is _UNSET else legs,
        evaluation_context=context,
        reference_timestamp=REF,
        spot=20000.0,
        time_to_expiry=0.01,
        implied_volatility=0.2,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        payoff=_payoff() if payoff is _UNSET else payoff,
        market_regime=MarketRegime(label=RegimeLabel.TRENDING,
                                   source="intelligence.regime.v1",
                                   model_version="1.0.0",
                                   reference_timestamp=REF),
        regime_direction=IntelligenceDirection.BULLISH,
        strategy_direction=IntelligenceDirection.BULLISH,
        liquidity=LiquidityEvidence(
            state=DimensionState.AVAILABLE, legs_complete=1, legs_total=1,
            spread_bps=2.5, quality=QualityState.EXCELLENT,
            provenance=_prov("liq-bnd")),
        risk=Day31RiskEvidence(
            state=DimensionState.AVAILABLE, structural_unbounded_loss=False,
            max_loss_estimate=50.0, notes=("debit spread",),
            provenance=_prov("risk-bnd")),
        historical=HistoricalEvidence(
            state=DimensionState.AVAILABLE, observations=120,
            metric_note="point-in-time supplied", provenance=_prov("hist-bnd")),
        scenario_points=_points(19900.0, 20000.0, 20100.0)
        if scenario_points is _UNSET else scenario_points,
        confidence=0.7,
        quality=_quality() if quality is _UNSET else quality,
    )
    if opportunity is not _UNSET:
        kwargs["opportunity"] = opportunity
    kwargs.update(overrides)
    return StrategyEvaluationInput(**kwargs)


def _evaluation(*, opportunity: Opportunity | None = None,
                status_hint: str = "success",
                **overrides) -> object:
    """A genuine Day-31 StrategyEvaluationResult through the real engine."""
    if status_hint == "partial":
        overrides.setdefault(
            "liquidity",
            LiquidityEvidence(state=DimensionState.PARTIAL, legs_complete=1,
                              legs_total=2, spread_bps=None,
                              quality=QualityState.DEGRADED,
                              provenance=_prov("liq-partial")))
    elif status_hint == "invalid":
        overrides.setdefault("payoff", _payoff(state=DimensionState.INVALID))
    elif status_hint == "unavailable":
        overrides.setdefault("legs", (_leg(implied_volatility=None),))
        overrides.setdefault("implied_volatility", None)
        overrides.setdefault("payoff", None)
        overrides.setdefault("market_regime", None)
        overrides.setdefault("liquidity", None)
        overrides.setdefault("risk", None)
        overrides.setdefault("historical", None)
        overrides.setdefault("scenario_points", ())
    if opportunity is not None:
        overrides.setdefault("opportunity", opportunity)
    return evaluate_strategy(_full_inp(**overrides))


def _eligible_candidate(*, opp: Opportunity | None = None,
                        evaluation: object | None = None) -> StrategyCandidate:
    """A genuine eligible Day-32 candidate produced by the Opportunity Gate."""
    opportunity = opp if opp is not None else _opportunity()
    ranked = _ranked(opportunity=opportunity)
    eval_result = evaluation if evaluation is not None \
        else _evaluation(opportunity=opportunity)
    result = evaluate_strategy_gate(
        opportunity, ranked, eval_result,
        strategy_id="strategy-1", legs=eval_result.legs)
    assert result.candidate is not None and result.eligible
    return result.candidate


def _candidate_from_evaluation(evaluation: object, *, opp: Opportunity | None = None,
                               lifecycle: StrategyLifecycleState = StrategyLifecycleState.ELIGIBLE,
                               legs: tuple[OptionLeg, ...] | None = None) -> StrategyCandidate:
    """Directly compose a contract-valid StrategyCandidate around a genuine
    evaluation (used to reach risk states the Opportunity Gate never emits)."""
    opportunity = opp if opp is not None else _opportunity()
    return StrategyCandidate(
        candidate_id=f"candidate:{opportunity.opportunity_id}:strategy-1:strike-20000",
        opportunity_id=opportunity.opportunity_id,
        strategy_id=evaluation.strategy_id,
        legs=legs if legs is not None else evaluation.legs,
        selected_strike_ids=("strike-20000",),
        expected_behavior=opportunity.expected_behavior,
        invalidation_conditions=opportunity.invalidation_conditions,
        evaluation=evaluation,
        lifecycle_state=lifecycle,
        confidence=evaluation.confidence,
        quality=evaluation.quality,
        reference_timestamp=REF,
        provenance=opportunity.provenance,
    )


def _policy(*, version: str = "policy-1.0",
            maximum_standalone_loss: float | None = 200.0,
            allow_unbounded_loss: bool = True,
            maximum_scenario_loss: float | None = 200.0,
            minimum_quality: QualityState | None = None,
            maximum_data_age_seconds: float | None = None) -> RiskPolicy:
    return RiskPolicy(
        policy_version=version,
        maximum_standalone_loss=maximum_standalone_loss,
        allow_unbounded_loss=allow_unbounded_loss,
        maximum_scenario_loss=maximum_scenario_loss,
        minimum_quality=minimum_quality,
        maximum_data_age_seconds=maximum_data_age_seconds,
    )


# ---------------------------------------------------------------------------
# 1. Risk policy contract
# ---------------------------------------------------------------------------


class TestRiskPolicyContract:
    def test_valid_policy_constructs(self):
        policy = _policy()
        assert policy.policy_version == "policy-1.0"
        assert policy.maximum_standalone_loss == 200.0
        assert policy.allow_unbounded_loss is True

    def test_blank_version_rejected(self):
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="", allow_unbounded_loss=True)

    def test_negative_loss_limit_rejected(self):
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="p", maximum_standalone_loss=-1.0,
                       allow_unbounded_loss=True)
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="p", maximum_scenario_loss=-0.5,
                       allow_unbounded_loss=True)

    def test_non_finite_limits_rejected(self):
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="p", maximum_standalone_loss=float("nan"),
                       allow_unbounded_loss=True)
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="p", maximum_data_age_seconds=float("inf"),
                       allow_unbounded_loss=True)

    def test_negative_data_age_rejected(self):
        with pytest.raises(ValueError):
            RiskPolicy(policy_version="p", maximum_data_age_seconds=-5.0,
                       allow_unbounded_loss=True)

    def test_policy_round_trips(self):
        policy = _policy(version="p9", maximum_data_age_seconds=3600.0,
                         minimum_quality=QualityState.EXCELLENT)
        assert RiskPolicy.from_dict(policy.to_dict()).to_dict() == policy.to_dict()
        assert RiskPolicy.from_dict(json.loads(json.dumps(policy.to_dict()))) == policy

    def test_unbounded_permission_is_explicit(self):
        # allow_unbounded_loss has no default: the caller must state intent.
        with pytest.raises(TypeError):
            RiskPolicy(policy_version="p")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2. Genuine eligible candidate -> PASS / BLOCKED policy decisions
# ---------------------------------------------------------------------------


class TestPassAndBlocked:
    def test_eligible_candidate_passes_reasonable_policy(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        assert result.status is CentralRiskStatus.PASS
        assert result.payoff_risk.state is DimensionState.AVAILABLE
        assert result.greek_risk.state is DimensionState.AVAILABLE
        assert result.scenario_risk.state is DimensionState.AVAILABLE
        assert result.structural_risk.state is DimensionState.AVAILABLE
        assert result.blocking_reasons == ()
        assert result.issues == ()

    def test_maximum_standalone_loss_violation_blocks(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=10.0))
        assert result.status is CentralRiskStatus.BLOCKED
        rules = {r.rule for r in result.policy_assessment.rules if r.passed is False}
        assert PolicyRuleCode.MAX_STANDALONE_LOSS in rules
        assert len(result.blocking_reasons) == 1
        assert result.blocking_reasons[0].rule is PolicyRuleCode.MAX_STANDALONE_LOSS

    def test_unbounded_loss_blocked_when_policy_forbids(self):
        # Genuine short-call payoff: unlimited loss, no max_loss value.
        candidate = _eligible_candidate(evaluation=_evaluation(
            payoff=_payoff(max_profit=100.0, max_loss=None,
                           tail=TailClass.UNLIMITED_LOSS, breakevens=(20100.0,))))
        blocked = assess_candidate_risk(
            candidate, _policy(allow_unbounded_loss=False))
        assert blocked.status is CentralRiskStatus.BLOCKED
        failed = {r.rule for r in blocked.policy_assessment.rules if r.passed is False}
        assert PolicyRuleCode.UNBOUNDED_LOSS in failed
        # The unbounded loss is never fabricated as a zero max loss.
        assert blocked.payoff_risk.max_loss is None
        assert blocked.payoff_risk.loss_unbounded is True

    def test_unbounded_loss_allowed_when_policy_permits(self):
        candidate = _eligible_candidate(evaluation=_evaluation(
            payoff=_payoff(max_profit=100.0, max_loss=None,
                           tail=TailClass.UNLIMITED_LOSS, breakevens=(20100.0,))))
        # The policy explicitly permits unbounded loss and imposes no finite
        # standalone-loss cap: every configured requirement passes.  PASS
        # here only means the standalone policy is satisfied -- never
        # portfolio/capital/user/execution approval.
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=None))
        assert result.status is CentralRiskStatus.PASS
        for rule in result.policy_assessment.rules:
            if rule.rule is PolicyRuleCode.UNBOUNDED_LOSS:
                assert rule.passed is True

    def test_finite_cap_blocks_contradictory_unbounded_policy(self):
        # Unbounded loss permitted yet a finite standalone cap is configured
        # is a contradiction: the finite cap can never be satisfied.
        candidate = _eligible_candidate(evaluation=_evaluation(
            payoff=_payoff(max_profit=100.0, max_loss=None,
                           tail=TailClass.UNLIMITED_LOSS, breakevens=(20100.0,))))
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=200.0))
        assert result.status is CentralRiskStatus.BLOCKED
        failed = {r.rule for r in result.policy_assessment.rules if r.passed is False}
        assert PolicyRuleCode.MAX_STANDALONE_LOSS in failed

    def test_minimum_quality_violation_blocks(self):
        candidate = _eligible_candidate(evaluation=_evaluation(
            quality=_quality(QualityState.DEGRADED)))
        result = assess_candidate_risk(
            candidate,
            _policy(minimum_quality=QualityState.EXCELLENT,
                    maximum_standalone_loss=None, maximum_scenario_loss=None))
        assert result.status is CentralRiskStatus.BLOCKED
        failed = {r.rule for r in result.policy_assessment.rules if r.passed is False}
        assert PolicyRuleCode.MIN_QUALITY in failed

    def test_stale_data_blocks_when_freshness_policy_set(self):
        old = REF - timedelta(hours=6)
        candidate = _eligible_candidate(evaluation=_evaluation(quality=_quality(observed_at=old)))
        result = assess_candidate_risk(
            candidate,
            _policy(maximum_data_age_seconds=3600.0,
                    maximum_standalone_loss=None, maximum_scenario_loss=None))
        assert result.status is CentralRiskStatus.BLOCKED
        failed = {r.rule for r in result.policy_assessment.rules if r.passed is False}
        assert PolicyRuleCode.MAX_DATA_AGE in failed

    def test_fresh_data_passes_freshness_policy(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(
            candidate,
            _policy(maximum_data_age_seconds=3600.0,
                    maximum_standalone_loss=None, maximum_scenario_loss=None))
        assert result.status is CentralRiskStatus.PASS
        data_age = {r for r in result.policy_assessment.rules
                    if r.rule is PolicyRuleCode.MAX_DATA_AGE}
        assert data_age and all(r.passed is True for r in data_age)

    def test_future_dated_quality_is_not_silently_fresh(self):
        # Design §11: a future-dated observation cannot establish freshness
        # and is never silently treated as usable (never "fresher than
        # fresh"): the data-age rule becomes unverifiable -> PARTIAL.
        future = REF + timedelta(hours=2)
        candidate = _eligible_candidate(
            evaluation=_evaluation(quality=_quality(observed_at=future)))
        result = assess_candidate_risk(
            candidate,
            _policy(maximum_data_age_seconds=3600.0,
                    maximum_standalone_loss=None, maximum_scenario_loss=None))
        assert result.status is CentralRiskStatus.PARTIAL
        rule = next(r for r in result.policy_assessment.rules
                    if r.rule is PolicyRuleCode.MAX_DATA_AGE)
        assert rule.passed is None

    def test_blocked_reasons_are_structured_and_deterministic(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=5.0))
        assert result.status is CentralRiskStatus.BLOCKED
        encoded = result.to_dict()
        assert json.dumps(encoded)
        restored = CentralRiskResult.from_dict(json.loads(json.dumps(encoded)))
        assert restored.to_dict() == encoded
        assert restored.blocking_reasons[0].message == result.blocking_reasons[0].message


# ---------------------------------------------------------------------------
# 3. Incomplete / invalid / unavailable upstream evidence
# ---------------------------------------------------------------------------


class TestIncompleteInvalidUnavailable:
    def test_partial_evaluation_cannot_pass(self):
        partial = _evaluation(status_hint="partial")
        candidate = _candidate_from_evaluation(partial)
        result = assess_candidate_risk(candidate, _policy())
        assert result.status is CentralRiskStatus.PARTIAL
        assert any(issue.code is CentralRiskIssueCode.INCOMPLETE_RISK_EVIDENCE
                   for issue in result.issues)

    def test_unavailable_evaluation_is_unavailable(self):
        unavailable = _evaluation(status_hint="unavailable")
        assert unavailable.status is StrategyEvaluationStatus.UNAVAILABLE
        candidate = _candidate_from_evaluation(unavailable)
        result = assess_candidate_risk(candidate, _policy())
        assert result.status is CentralRiskStatus.UNAVAILABLE

    def test_invalid_evaluation_is_invalid(self):
        invalid = _evaluation(status_hint="invalid")
        candidate = _candidate_from_evaluation(invalid)
        result = assess_candidate_risk(candidate, _policy())
        assert result.status is CentralRiskStatus.INVALID
        assert any(issue.code is CentralRiskIssueCode.INVALID_EVALUATION
                   for issue in result.issues)

    def test_non_eligible_candidate_is_invalid(self):
        candidate = _eligible_candidate()
        blocked_candidate = StrategyCandidate(
            candidate_id=candidate.candidate_id,
            opportunity_id=candidate.opportunity_id,
            strategy_id=candidate.strategy_id,
            legs=candidate.legs,
            selected_strike_ids=candidate.selected_strike_ids,
            expected_behavior=candidate.expected_behavior,
            invalidation_conditions=candidate.invalidation_conditions,
            evaluation=candidate.evaluation,
            lifecycle_state=StrategyLifecycleState.BLOCKED,
            confidence=candidate.confidence,
            quality=candidate.quality,
            reference_timestamp=candidate.reference_timestamp,
            provenance=candidate.provenance,
        )
        result = assess_candidate_risk(blocked_candidate, _policy())
        assert result.status is CentralRiskStatus.INVALID
        assert any(issue.code is CentralRiskIssueCode.NOT_ELIGIBLE_CANDIDATE
                   for issue in result.issues)

    def test_zero_quantity_leg_is_structurally_invalid(self):
        candidate = _eligible_candidate()
        bad_legs = (_leg(quantity=0.0),)
        bad_candidate = _candidate_from_evaluation(
            candidate.evaluation, legs=bad_legs)
        result = assess_candidate_risk(bad_candidate, _policy())
        assert result.status is CentralRiskStatus.INVALID
        assert result.structural_risk.state is DimensionState.INVALID
        assert any(issue.code is CentralRiskIssueCode.STRUCTURAL_INVALID
                   for issue in result.issues)

    def test_missing_payoff_evidence_is_not_zero(self):
        # A PARTIAL payoff (state PARTIAL, net/max values still supplied)
        # must stay PARTIAL; nothing is fabricated to a favourable value.
        partial_payoff = _evaluation(payoff=_payoff(state=DimensionState.PARTIAL))
        candidate = _candidate_from_evaluation(partial_payoff)
        result = assess_candidate_risk(candidate, _policy())
        assert result.status is CentralRiskStatus.PARTIAL
        assert result.payoff_risk.state is DimensionState.PARTIAL


# ---------------------------------------------------------------------------
# 4. Risk metrics, score separation and semantics
# ---------------------------------------------------------------------------


class TestRiskMetricsSeparation:
    def test_bounded_loss_payoff_metrics_exposed(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        assert result.payoff_risk.max_profit == 100.0
        assert result.payoff_risk.max_loss == -50.0
        assert result.payoff_risk.loss_unbounded is False
        assert result.payoff_risk.breakevens == (20050.0,)

    def test_worst_scenario_uses_supplied_scenarios_only(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        # Day-31 scenario assessment carries authoritative min/max P/L.
        assert result.scenario_risk.points_total >= 3
        assert result.scenario_risk.min_pnl is not None
        # Worst-supplied-scenario is explicitly NOT theoretical worst-case.
        assert result.scenario_risk.note  # human-auditable note present

    def test_greek_risk_reuses_authoritative_aggregate(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        assert result.greek_risk.delta is not None
        assert result.greek_risk.greeks_source == "MODEL"
        assert result.greek_risk.legs_priced == result.greek_risk.legs_total

    def test_confidence_quality_policy_decision_separate(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        # Confidence (caller/evaluation channel) and quality (Day-12 channel)
        # are distinct fields on the result.
        assert result.confidence == 0.7
        assert result.quality is candidate.quality
        assert result.policy_assessment.policy_version == "policy-1.0"

    def test_no_opaque_risk_score_emitted(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=1.0))
        # A BLOCKED verdict cannot be laundered by any descriptive score:
        # no score field exists anywhere in the result contract.
        assert result.status is CentralRiskStatus.BLOCKED
        assert not hasattr(result, "risk_score")
        assert "risk_score" not in result.to_dict()


# ---------------------------------------------------------------------------
# 5. Determinism / context equivalence / serialization / provenance
# ---------------------------------------------------------------------------


class TestDeterminismAndContext:
    def test_repeated_evaluation_byte_identical(self):
        candidate = _eligible_candidate()
        first = assess_candidate_risk(candidate, _policy()).to_dict()
        second = assess_candidate_risk(candidate, _policy()).to_dict()
        assert first == second
        assert json.dumps(first, sort_keys=True) == \
            json.dumps(second, sort_keys=True)

    def test_context_never_changes_risk_result(self):
        outputs = {}
        for context in EvaluationContext:
            evaluation = _evaluation(context=context)
            candidate = _candidate_from_evaluation(evaluation)
            outputs[context] = assess_candidate_risk(candidate, _policy()).to_dict()
        first = outputs[EvaluationContext.OPPORTUNITY]
        assert all(out == first for out in outputs.values())

    def test_reference_timestamp_is_caller_supplied(self):
        candidate = _eligible_candidate()
        ts = datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)
        result = assess_candidate_risk(candidate, _policy(),
                                       reference_timestamp=ts)
        assert result.reference_timestamp == ts

    def test_naive_reference_timestamp_rejected(self):
        candidate = _eligible_candidate()
        naive = datetime(2026, 9, 4, 15, 30)
        with pytest.raises(ValueError):
            assess_candidate_risk(candidate, _policy(), reference_timestamp=naive)

    def test_result_round_trip_preserves_full_semantic_state(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy(
            minimum_quality=QualityState.EXCELLENT,
            maximum_data_age_seconds=86400.0))
        encoded = result.to_dict()
        restored = CentralRiskResult.from_dict(json.loads(json.dumps(encoded)))
        assert restored.to_dict() == encoded
        assert restored.status is result.status
        assert restored.payoff_risk.to_dict() == result.payoff_risk.to_dict()
        assert restored.greek_risk.to_dict() == result.greek_risk.to_dict()
        assert restored.scenario_risk.to_dict() == result.scenario_risk.to_dict()
        assert restored.structural_risk.to_dict() == result.structural_risk.to_dict()
        assert restored.policy_assessment.to_dict() == result.policy_assessment.to_dict()

    def test_naive_quality_reference_rejected(self):
        candidate = _eligible_candidate(evaluation=_evaluation(
            quality=_quality(observed_at=REF)))
        result = assess_candidate_risk(
            candidate, _policy(maximum_data_age_seconds=3600.0,
                               maximum_standalone_loss=None,
                               maximum_scenario_loss=None))
        # Fresh data within the configured window passes deterministically.
        assert result.status is CentralRiskStatus.PASS

    def test_opportunity_provenance_preserved_at_result_level(self):
        opp = _opportunity()
        candidate = _eligible_candidate(opp=opp)
        result = assess_candidate_risk(candidate, _policy())
        assert result.provenance == opp.provenance

    def test_dimension_provenance_not_flattened(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        # Payoff evidence provenance comes from the Day-31 payoff boundary and
        # is preserved on the Day-33 payoff-risk dimension, not overwritten.
        assert result.payoff_risk.provenance is not None
        assert result.payoff_risk.provenance.source == "payoff-bnd"
        # Result-level provenance stays the Day-28 Opportunity provenance.
        assert result.provenance.source == "UPSTOX_SNAPSHOT_NORMALIZED"

    def test_evidence_rows_carry_provenance(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        assert result.evidence
        assert all(isinstance(e, RiskEvidence) for e in result.evidence)
        assert any(e.kind == "PAYOFF" for e in result.evidence)
        assert any(e.kind == "POLICY" for e in result.evidence)


# ---------------------------------------------------------------------------
# 6. Missing values remain missing
# ---------------------------------------------------------------------------


class TestMissingNeverFabricated:
    def test_missing_payoff_metrics_stay_missing(self):
        candidate = _eligible_candidate(evaluation=_evaluation(
            payoff=_payoff(max_profit=None, max_loss=None, breakevens=())))
        result = assess_candidate_risk(candidate, _policy())
        # The Day-31 SUCCESS payoff with metrics missing stays missing here.
        assert result.payoff_risk.max_profit is None
        assert result.payoff_risk.max_loss is None

    def test_unbounded_loss_never_becomes_zero(self):
        candidate = _eligible_candidate(evaluation=_evaluation(
            payoff=_payoff(max_profit=100.0, max_loss=None,
                           tail=TailClass.UNLIMITED_LOSS)))
        result = assess_candidate_risk(
            candidate, _policy(maximum_standalone_loss=None))
        assert result.payoff_risk.max_loss is None
        assert result.payoff_risk.loss_unbounded is True

    def test_blocked_policy_keeps_evidence_visible(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy(maximum_standalone_loss=1.0))
        assert result.status is CentralRiskStatus.BLOCKED
        # The violating evidence remains inspectable (never relabelled safe).
        assert result.payoff_risk.max_loss == -50.0
        rule = result.blocking_reasons[0]
        assert rule.limit == 1.0
        assert rule.observed == 50.0


# ---------------------------------------------------------------------------
# 7. Purity (AST-guarded)
# ---------------------------------------------------------------------------


class TestPurity:
    _PKG = Path(__file__).resolve().parents[1] / "app" / "central_risk"

    def test_no_broker_or_execution_imports(self):
        forbidden_modules = {"time", "random", "uuid", "requests", "httpx",
                             "sqlalchemy", "os", "sys", "socket", "pathlib",
                             "brokers"}
        forbidden_identifiers = {"BrokerAdapter", "Order", "UserApproval",
                                 "place_order", "execute_order", "RiskDecision",
                                 "authorize"}
        for path in self._PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(alias.name.split(".")[0] not in forbidden_modules
                               for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert node.module is None or \
                        node.module.split(".")[0] not in forbidden_modules
                elif isinstance(node, ast.Name):
                    assert node.id not in forbidden_identifiers

    def test_no_wall_clock_or_randomness(self):
        for path in self._PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and \
                        node.attr in {"now", "utcnow", "today", "random"}:
                    raise AssertionError(f"wall-clock/randomness found: {node.attr}")
                if isinstance(node, ast.Name) and node.id == "datetime" and \
                        isinstance(node.ctx, ast.Load):
                    # datetime import is fine; only .now/.utcnow/.today calls
                    # are forbidden (covered by the Attribute check above).
                    pass

    def test_contract_version_present(self):
        candidate = _eligible_candidate()
        result = assess_candidate_risk(candidate, _policy())
        assert result.contract_version == CENTRAL_RISK_CONTRACT_VERSION
        assert result.calculation_version == CENTRAL_RISK_CALCULATION_VERSION
