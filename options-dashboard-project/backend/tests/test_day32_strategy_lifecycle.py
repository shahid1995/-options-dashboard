"""Day 32 — Strategy lifecycle and Opportunity Gate tests.

Integration tests against the REAL upstream contracts.  Every upstream
object is genuinely constructed through its authoritative engine or
pipeline (never via ``object.__new__`` / ``object.__setattr__`` fakes):

    genuine Day-19 IntelligenceResult
        -> discover_opportunity(...)          # Day-28 genuine pipeline
        -> rank_strikes(...)                  # Day-30 genuine ranking engine
        -> evaluate_strategy(...)             # Day-31 genuine evaluation engine
        -> evaluate_strategy_gate(...)        # Day-32 under test

The suite proves that the gate consumes the authoritative Day-28
``Opportunity`` contract (including ``invalidation_conditions``), the
Day-30 ranked-strike result and a complete Day-31
``StrategyEvaluationResult`` (all seven assessment dimensions), and that
serialization round-trips real objects without losing semantic state.

Boundary locked here (architectural, unchanged by remediation)
--------------------------------------------------------------
* ELIGIBLE means structurally eligible for a later Risk Check — NOT
  risk-approved, NOT user-approved, NOT execution-approved.
* Missing data stays missing (never zero, never a fabricated default).
* No wall clock, randomness, IO, broker/execution or authorization
  semantics exist in the Day-32 package (AST-guarded).
"""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
from app.opportunity.contracts import ExpectedBehavior, Observation, Opportunity
from app.opportunity.pipeline import discover_opportunity
from app.quant.scenarios import OptionLeg, PositionDirection, ScenarioPoint
from app.strategy_evaluation.contracts import (
    DimensionState,
    EvaluationContext,
    HistoricalEvidence,
    LiquidityEvidence,
    PayoffEvidence,
    PayoffExpirySemantics,
    RiskEvidence,
    StrategyEvaluationInput,
    StrategyEvaluationResult,
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
    StrikeRankingResult,
)
from app.strike_ranking.ranking import DEFAULT_RANKING_WEIGHTS, rank_strikes
from app.strategy_lifecycle.contracts import (
    BlockingReasonCode,
    GateStatus,
    StrategyCandidate,
    StrategyGateResult,
    StrategyLifecycleState,
)
from app.strategy_lifecycle.lifecycle import evaluate_strategy_gate, transition_lifecycle

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


def _quality(state: QualityState = QualityState.EXCELLENT) -> QualityResult:
    return QualityResult(
        quality_score=95 if state is QualityState.EXCELLENT else 55,
        quality_state=state,
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=REF,
        observation_time=REF,
        observation_type="QUOTE",
        contract_version="1.0.0",
        reference_time=REF,
    )


def _synthesis(direction: IntelligenceDirection = IntelligenceDirection.BULLISH,
               strength: float = 0.5, confidence: float = 0.75) -> IntelligenceResult:
    """A genuine Day-19 SUCCESS IntelligenceResult."""
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
    """A genuine Day-28 Opportunity produced by the authoritative pipeline."""
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


def _legs() -> tuple[OptionLeg, ...]:
    return (_leg(),)


def _all_factors(scores: dict[RankingFactor, float] | None = None) -> tuple[FactorObservation, ...]:
    """All nine genuine factor observations (usable by default)."""
    return tuple(
        FactorObservation(factor=f, score=(scores or {}).get(f, 0.8))
        for f in RankingFactor
    )


def _strike_candidate(candidate_id: str, *, opportunity: Opportunity | None = None,
                      factors: tuple[FactorObservation, ...] | None = None,
                      option_type: OptionType = OptionType.CE,
                      strike: float = 20000.0) -> StrikeCandidateInput:
    return StrikeCandidateInput(
        candidate_id=candidate_id, underlying=NIFTY, option_type=option_type,
        strike=strike, expiry=EXPIRY,
        factors=factors if factors is not None else _all_factors(),
        opportunity=opportunity,
    )


def _ranked(opportunity: Opportunity | None = None,
            candidate_ids: tuple[str, ...] = ("strike-20000", "strike-20500")) -> StrikeRankingResult:
    """A genuine Day-30 SUCCESS result through the real ranking engine."""
    candidates = tuple(
        _strike_candidate(
            cid, opportunity=opportunity,
            option_type=OptionType.CE if i % 2 == 0 else OptionType.PE,
            strike=20000.0 + 500.0 * i)
        for i, cid in enumerate(candidate_ids))
    return rank_strikes(StrikeRankingInput(
        candidates=candidates, weights=DEFAULT_RANKING_WEIGHTS,
        objective_id="dir-bull"))


def _nothing_eligible(opportunity: Opportunity | None = None) -> StrikeRankingResult:
    """A genuine Day-30 NOTHING_ELIGIBLE result: candidate missing factors."""
    candidate = _strike_candidate(
        "strike-missing", opportunity=opportunity,
        factors=tuple(FactorObservation(factor=f, score=0.8)
                      for f in list(RankingFactor)[:8]))
    return rank_strikes(StrikeRankingInput(
        candidates=(candidate,), weights=DEFAULT_RANKING_WEIGHTS,
        objective_id="dir-bull"))


def _points(*spots: float) -> tuple[ScenarioPoint, ...]:
    return tuple(ScenarioPoint(spot=s, time_to_expiry=0.01,
                               implied_volatility=0.2) for s in spots)


def _payoff(state: DimensionState = DimensionState.AVAILABLE,
           semantics: PayoffExpirySemantics = PayoffExpirySemantics.SAME_EXPIRY_EXACT,
           net: float | None = 1.0, max_profit: float | None = 100.0,
           max_loss: float | None = -50.0,
           tail: TailClass = TailClass.NONE,
           breakevens: tuple[float, ...] = (20050.0,)) -> PayoffEvidence:
    return PayoffEvidence(
        state=state, expiry_semantics=semantics, net_debit_credit=net,
        max_profit=max_profit, max_loss=max_loss, tail=tail,
        breakevens=breakevens, provenance=_prov("payoff-bnd"))


def _full_inp(**overrides) -> StrategyEvaluationInput:
    """A fully-evidenced Day-31 evaluation input (SUCCESS path)."""
    kwargs = dict(
        strategy_id="strategy-1",
        legs=_legs(),
        evaluation_context=EvaluationContext.OPPORTUNITY,
        reference_timestamp=REF,
        spot=20000.0,
        time_to_expiry=0.01,
        implied_volatility=0.2,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        payoff=_payoff(),
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
        risk=RiskEvidence(
            state=DimensionState.AVAILABLE, structural_unbounded_loss=False,
            max_loss_estimate=50.0, notes=("debit spread",),
            provenance=_prov("risk-bnd")),
        historical=HistoricalEvidence(
            state=DimensionState.AVAILABLE, observations=120,
            metric_note="point-in-time supplied", provenance=_prov("hist-bnd")),
        scenario_points=_points(19900.0, 20000.0, 20100.0),
        confidence=0.7,
        quality=_quality(),
    )
    kwargs.update(overrides)
    return StrategyEvaluationInput(**kwargs)


def _evaluation(*, opportunity: Opportunity | None = None,
                status_hint: str = "success",
                **overrides) -> StrategyEvaluationResult:
    """A genuine Day-31 StrategyEvaluationResult through the real engine."""
    if status_hint == "partial":
        # One dimension PARTIAL keeps the overall status PARTIAL.
        overrides.setdefault(
            "liquidity",
            LiquidityEvidence(state=DimensionState.PARTIAL, legs_complete=1,
                              legs_total=2, spread_bps=None,
                              quality=QualityState.DEGRADED,
                              provenance=_prov("liq-partial")))
    elif status_hint == "invalid":
        overrides.setdefault("payoff", _payoff(state=DimensionState.INVALID))
    elif status_hint == "unavailable":
        # Mirror the genuine Day-31 all-unavailable path: legs with no IV
        # so the authoritative engine cannot price them, no scenarios and
        # no supplied dimension evidence.
        overrides.setdefault("legs",
                             (_leg(implied_volatility=None),))
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


def _gate(*, opportunity: Opportunity | None = None,
          ranked: StrikeRankingResult | None = None,
          evaluation: StrategyEvaluationResult | None = None,
          strategy_id: str | None = "strategy-1",
          legs: tuple[OptionLeg, ...] | None = None,
          expected_behavior: ExpectedBehavior | None = None,
          invalidation_conditions: tuple[str, ...] | None = None,
          reference_timestamp: datetime | None = None,
          confidence: float | None = None,
          quality: QualityResult | None = None) -> StrategyGateResult:
    return evaluate_strategy_gate(
        opportunity, ranked, evaluation, strategy_id=strategy_id,
        legs=legs if legs is not None else _legs(),
        expected_behavior=expected_behavior,
        invalidation_conditions=invalidation_conditions,
        reference_timestamp=reference_timestamp, confidence=confidence,
        quality=quality)


# ---------------------------------------------------------------------------
# 1. Valid Opportunity -> Strategy Candidate (genuine full chain)
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_genuine_opportunity_through_gate_is_eligible(self):
        opp = _opportunity()
        ranked = _ranked(opportunity=opp)
        evaluation = _evaluation(opportunity=opp)
        result = _gate(opportunity=opp, ranked=ranked, evaluation=evaluation)
        assert result.status is GateStatus.ELIGIBLE
        assert result.eligible is True
        assert result.lifecycle_state is StrategyLifecycleState.ELIGIBLE
        assert result.candidate is not None
        candidate = result.candidate
        assert candidate.opportunity_id == "opp-1"
        assert candidate.strategy_id == "strategy-1"
        # Ranked-strike integration: the real engine's candidate identities
        # are preserved verbatim and in ranked order.
        assert candidate.selected_strike_ids == tuple(
            r.candidate_id for r in ranked.ranked)
        # Day-31 evaluation integration: the genuine seven-dimension result
        # is carried whole (proven by the serialization round-trip below).
        assert candidate.evaluation.status is StrategyEvaluationStatus.SUCCESS

    def test_authoritative_invalidation_conditions_preserved(self):
        opp = _opportunity()
        result = _gate(opportunity=opp, ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.candidate is not None
        # The Day-28 authoritative tuple (not a singular string) survives the
        # boundary untouched when the caller supplies no override.
        assert result.candidate.invalidation_conditions == \
            opp.invalidation_conditions
        assert isinstance(result.candidate.invalidation_conditions, tuple)
        assert all(isinstance(c, str) and c.strip()
                   for c in result.candidate.invalidation_conditions)

    def test_explicit_invalidation_override_is_respected(self):
        override = ("custom thesis boundary",)
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(),
                       invalidation_conditions=override)
        assert result.candidate is not None
        assert result.candidate.invalidation_conditions == override

    def test_expected_behavior_falls_back_to_opportunity(self):
        opp = _opportunity()
        result = _gate(opportunity=opp, ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.candidate is not None
        assert result.candidate.expected_behavior is \
            ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE
        assert result.candidate.expected_behavior is opp.expected_behavior

    def test_candidate_identity_is_deterministic(self):
        opp = _opportunity()
        ranked = _ranked(opportunity=opp)
        evaluation = _evaluation(opportunity=opp)
        first = _gate(opportunity=opp, ranked=ranked, evaluation=evaluation)
        second = _gate(opportunity=opp, ranked=ranked, evaluation=evaluation)
        assert first.candidate is not None and second.candidate is not None
        assert first.candidate.candidate_id == second.candidate.candidate_id
        expected = "candidate:" + ":".join(
            (opp.opportunity_id, "strategy-1",
             *(r.candidate_id for r in ranked.ranked)))
        assert first.candidate.candidate_id == expected

    def test_reference_timestamp_is_caller_supplied(self):
        # The explicit caller-supplied reference wins over the evaluation's.
        other_ref = datetime(2026, 9, 4, 14, 30, tzinfo=timezone.utc)
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(),
                       reference_timestamp=other_ref)
        assert result.reference_timestamp == other_ref
        assert result.candidate is not None
        assert result.candidate.reference_timestamp == other_ref

    def test_degraded_quality_remains_visible_and_not_relabelled(self):
        degraded = _quality(QualityState.DEGRADED)
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(), quality=degraded)
        assert result.status is GateStatus.ELIGIBLE
        assert result.quality is degraded
        assert result.quality.quality_state is QualityState.DEGRADED


# ---------------------------------------------------------------------------
# 2. Missing / invalid upstream inputs are never silently accepted
# ---------------------------------------------------------------------------


class TestBlocking:
    def test_missing_opportunity_is_blocked_explicitly(self):
        result = _gate(opportunity=None, ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.status is GateStatus.BLOCKED
        assert not result.eligible
        assert result.candidate is None
        assert BlockingReasonCode.MISSING_OPPORTUNITY in \
            {r.code for r in result.blocking_reasons}

    def test_invalid_opportunity_object_is_invalid(self):
        # A non-Opportunity object must never become an eligible candidate.
        result = evaluate_strategy_gate(
            "not-an-opportunity", _ranked(), _evaluation(),
            strategy_id="strategy-1", legs=_legs(),
            reference_timestamp=REF, quality=_quality())
        assert result.status is GateStatus.INVALID
        assert not result.eligible
        assert result.candidate is None
        assert BlockingReasonCode.INVALID_OPPORTUNITY in \
            {r.code for r in result.blocking_reasons}

    def test_missing_strategy_id_is_blocked(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(), strategy_id=None)
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_STRATEGY_ID in \
            {r.code for r in result.blocking_reasons}

    def test_missing_legs_is_blocked(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(), legs=())
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_LEGS in \
            {r.code for r in result.blocking_reasons}

    def test_invalid_leg_object_is_blocked(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(),
                       legs=("not-a-leg",))  # type: ignore[arg-type]
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_LEGS in \
            {r.code for r in result.blocking_reasons}

    def test_missing_strike_selection_is_blocked(self):
        result = _gate(opportunity=_opportunity(), ranked=None,
                       evaluation=_evaluation())
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_STRIKE_SELECTION in \
            {r.code for r in result.blocking_reasons}

    def test_nothing_eligible_ranking_cannot_pass_gate(self):
        result = _gate(opportunity=_opportunity(),
                       ranked=_nothing_eligible(), evaluation=_evaluation())
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_STRIKE_SELECTION in \
            {r.code for r in result.blocking_reasons}

    def test_invalid_strike_selection_object_is_invalid(self):
        result = evaluate_strategy_gate(
            _opportunity(), "not-a-ranking", _evaluation(),
            strategy_id="strategy-1", legs=_legs(),
            reference_timestamp=REF, quality=_quality())
        assert result.status is GateStatus.INVALID
        assert BlockingReasonCode.INVALID_STRIKE_SELECTION in \
            {r.code for r in result.blocking_reasons}

    def test_missing_evaluation_is_blocked(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=None)
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.MISSING_EVALUATION in \
            {r.code for r in result.blocking_reasons}

    def test_incomplete_evaluation_cannot_become_eligible(self):
        # Genuine Day-31 PARTIAL result (a PARTIAL liquidity dimension).
        partial = _evaluation(status_hint="partial")
        assert partial.status is StrategyEvaluationStatus.PARTIAL
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=partial)
        assert result.status is GateStatus.BLOCKED
        assert not result.eligible
        assert BlockingReasonCode.INCOMPLETE_EVALUATION in \
            {r.code for r in result.blocking_reasons}

    def test_unavailable_evaluation_cannot_become_eligible(self):
        unavailable = _evaluation(status_hint="unavailable")
        assert unavailable.status is StrategyEvaluationStatus.UNAVAILABLE
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=unavailable)
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.INCOMPLETE_EVALUATION in \
            {r.code for r in result.blocking_reasons}

    def test_invalid_evaluation_is_invalid(self):
        invalid = _evaluation(status_hint="invalid")
        assert invalid.status is StrategyEvaluationStatus.INVALID
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=invalid)
        assert result.status is GateStatus.INVALID
        assert BlockingReasonCode.INVALID_EVALUATION in \
            {r.code for r in result.blocking_reasons}

    def test_evaluation_strategy_mismatch_is_invalid(self):
        evaluation = _evaluation(opportunity=_opportunity(),
                                 strategy_id="other-strategy")
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=evaluation, strategy_id="strategy-1")
        assert result.status is GateStatus.INVALID
        assert BlockingReasonCode.INVALID_EVALUATION in \
            {r.code for r in result.blocking_reasons}


# ---------------------------------------------------------------------------
# 3. Quality / freshness gates (deterministic, never fabricated)
# ---------------------------------------------------------------------------


class TestQualityAndFreshness:
    def test_insufficient_quality_blocks_without_coercion(self):
        insufficient = _quality(QualityState.INSUFFICIENT)
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation(), quality=insufficient)
        assert result.status is GateStatus.BLOCKED
        assert BlockingReasonCode.INSUFFICIENT_QUALITY in \
            {r.code for r in result.blocking_reasons}
        # The INSUFFICIENT state stays visible; it is not relabelled.
        assert result.quality is insufficient
        assert result.quality.quality_state is QualityState.INSUFFICIENT

    def test_missing_quality_is_blocked_and_never_zeroed(self):
        # No caller quality, a genuine evaluation carrying no quality and no
        # Opportunity to fall back on: quality stays genuinely missing.
        no_quality_eval = _evaluation(quality=None)
        assert no_quality_eval.quality is None
        result = _gate(opportunity=None, ranked=_ranked(),
                       evaluation=no_quality_eval, quality=None)
        assert not result.eligible
        assert BlockingReasonCode.MISSING_QUALITY in \
            {r.code for r in result.blocking_reasons}
        assert result.quality is None  # never coerced to zero/default

    def test_missing_reference_timestamp_is_blocked(self):
        result = _gate(opportunity=None, ranked=_ranked(),
                       evaluation=None, reference_timestamp=None)
        assert not result.eligible
        assert BlockingReasonCode.MISSING_REFERENCE_TIMESTAMP in \
            {r.code for r in result.blocking_reasons}

    def test_naive_reference_timestamp_is_invalid(self):
        naive = datetime(2026, 9, 4, 10, 0)
        result = evaluate_strategy_gate(
            _opportunity(), _ranked(), _evaluation(),
            strategy_id="strategy-1", legs=_legs(),
            reference_timestamp=naive, quality=_quality())
        assert result.status is GateStatus.INVALID
        assert BlockingReasonCode.INVALID_REFERENCE_TIMESTAMP in \
            {r.code for r in result.blocking_reasons}

    def test_repeated_gate_is_byte_identical(self):
        opp = _opportunity()
        ranked = _ranked(opportunity=opp)
        evaluation = _evaluation(opportunity=opp)
        first = _gate(opportunity=opp, ranked=ranked,
                      evaluation=evaluation).to_dict()
        second = _gate(opportunity=opp, ranked=ranked,
                       evaluation=evaluation).to_dict()
        assert first == second
        assert json.dumps(first, sort_keys=True) == \
            json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# 4. Lifecycle transitions (explicit, deterministic, terminal)
# ---------------------------------------------------------------------------


class TestLifecycleTransitions:
    def test_legal_transitions_are_explicit(self):
        assert transition_lifecycle(
            StrategyLifecycleState.CANDIDATE,
            StrategyLifecycleState.EVALUATED) is StrategyLifecycleState.EVALUATED
        assert transition_lifecycle(
            StrategyLifecycleState.EVALUATED,
            StrategyLifecycleState.ELIGIBLE) is StrategyLifecycleState.ELIGIBLE
        assert transition_lifecycle(
            StrategyLifecycleState.CANDIDATE,
            StrategyLifecycleState.BLOCKED) is StrategyLifecycleState.BLOCKED
        assert transition_lifecycle(
            StrategyLifecycleState.EVALUATED,
            StrategyLifecycleState.BLOCKED) is StrategyLifecycleState.BLOCKED
        assert transition_lifecycle(
            StrategyLifecycleState.CANDIDATE,
            StrategyLifecycleState.INVALID) is StrategyLifecycleState.INVALID
        assert transition_lifecycle(
            StrategyLifecycleState.EVALUATED,
            StrategyLifecycleState.INVALID) is StrategyLifecycleState.INVALID

    def test_illegal_transitions_are_rejected(self):
        assert transition_lifecycle(
            StrategyLifecycleState.BLOCKED,
            StrategyLifecycleState.EVALUATED) is None
        assert transition_lifecycle(
            StrategyLifecycleState.EXPIRED,
            StrategyLifecycleState.ELIGIBLE) is None
        assert transition_lifecycle(
            StrategyLifecycleState.INVALID,
            StrategyLifecycleState.CANDIDATE) is None
        assert transition_lifecycle(
            StrategyLifecycleState.ELIGIBLE,
            StrategyLifecycleState.BLOCKED) is None
        assert transition_lifecycle(
            StrategyLifecycleState.ELIGIBLE,
            StrategyLifecycleState.ELIGIBLE) is None

    def test_eligible_gate_lands_in_terminal_eligible_state(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.lifecycle_state is StrategyLifecycleState.ELIGIBLE


# ---------------------------------------------------------------------------
# 5. Provenance / serialization with genuine objects
# ---------------------------------------------------------------------------


class TestProvenanceAndSerialization:
    def test_opportunity_provenance_preserved_through_gate(self):
        opp = _opportunity()
        result = _gate(opportunity=opp, ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.provenance == opp.provenance
        assert result.candidate is not None
        assert result.candidate.provenance == opp.provenance

    def test_evaluation_provenance_stays_separate_and_preserved(self):
        opp = _opportunity()
        evaluation = _evaluation(opportunity=opp)
        result = _gate(opportunity=opp, ranked=_ranked(),
                       evaluation=evaluation)
        assert result.candidate is not None
        # Day-31 preserved the Opportunity provenance inside the genuine
        # evaluation; Day-32 keeps that evaluation object whole.
        assert evaluation.provenance == opp.provenance
        assert result.candidate.evaluation is evaluation

    def test_candidate_round_trips_with_genuine_evaluation(self):
        opp = _opportunity()
        result = _gate(opportunity=opp, ranked=_ranked(opportunity=opp),
                       evaluation=_evaluation(opportunity=opp))
        assert result.candidate is not None
        encoded = result.candidate.to_dict()
        restored = StrategyCandidate.from_dict(json.loads(json.dumps(encoded)))
        assert restored.to_dict() == encoded
        assert restored.opportunity_id == "opp-1"
        assert restored.invalidation_conditions == opp.invalidation_conditions
        assert restored.evaluation.status is StrategyEvaluationStatus.SUCCESS

    def test_gate_result_round_trips_with_genuine_objects(self):
        opp = _opportunity()
        result = _gate(opportunity=opp, ranked=_ranked(opportunity=opp),
                       evaluation=_evaluation(opportunity=opp))
        encoded = result.to_dict()
        restored = StrategyGateResult.from_dict(json.loads(json.dumps(encoded)))
        assert restored.to_dict() == encoded
        assert restored.eligible is True
        assert restored.candidate is not None
        assert restored.candidate.candidate_id == result.candidate.candidate_id  # type: ignore[union-attr]
        assert restored.candidate.evaluation.to_dict() == \
            result.candidate.evaluation.to_dict()  # type: ignore[union-attr]

    def test_blocked_gate_result_round_trips_and_preserves_provenance(self):
        result = _gate(opportunity=None, ranked=_ranked(),
                       evaluation=None)
        encoded = result.to_dict()
        assert result.provenance is None
        assert json.dumps(encoded)
        restored = StrategyGateResult.from_dict(encoded)
        assert restored.to_dict() == encoded
        assert restored.candidate is None
        assert restored.blocking_reasons == result.blocking_reasons


# ---------------------------------------------------------------------------
# 6. Context independence / determinism
# ---------------------------------------------------------------------------


class TestContextIndependence:
    def test_context_never_alters_gate_decision(self):
        opp = _opportunity()
        ranked = _ranked(opportunity=opp)
        decision_keys = ("status", "lifecycle_state", "eligible",
                         "blocking_reasons")
        decisions = {}
        for context in EvaluationContext:
            evaluation = _evaluation(opportunity=opp,
                                     evaluation_context=context)
            result = _gate(opportunity=opp, ranked=ranked,
                           evaluation=evaluation).to_dict()
            decisions[context] = {k: result[k] for k in decision_keys}
        first = decisions[EvaluationContext.OPPORTUNITY]
        assert all(item == first for item in decisions.values())
        assert all(item["status"] == "ELIGIBLE"
                   for item in decisions.values())


# ---------------------------------------------------------------------------
# 7. Eligibility is NOT any downstream authorization
# ---------------------------------------------------------------------------


class TestArchitecturalBoundary:
    def test_eligible_candidate_has_no_risk_or_execution_fields(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.candidate is not None
        forbidden_members = {"risk_approved", "user_approved",
                             "execution_approved", "order",
                             "allocation", "position"}
        payload = json.dumps(result.candidate.to_dict())
        for member in forbidden_members:
            assert member not in payload
        payload_result = json.dumps(result.to_dict())
        for member in forbidden_members:
            assert member not in payload_result

    def test_eligible_flag_is_not_risk_or_execution_approval(self):
        # Day 32 only answers structural eligibility.  No authorization
        # vocabulary exists anywhere on the result or its candidate.
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.eligible is True
        assert not hasattr(result, "risk_approved")
        assert not hasattr(result, "user_approved")
        assert not hasattr(result, "execution_approved")
        assert not hasattr(result, "order")

    def test_candidate_is_immutable(self):
        result = _gate(opportunity=_opportunity(), ranked=_ranked(),
                       evaluation=_evaluation())
        assert result.candidate is not None
        with pytest.raises(FrozenInstanceError):
            result.candidate.strategy_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. Purity (AST-guarded): no wall clock, randomness, IO, broker/execution
# ---------------------------------------------------------------------------


class TestPurity:
    _PKG = Path(__file__).resolve().parents[1] / "app" / "strategy_lifecycle"

    def test_lifecycle_package_has_no_broker_or_execution_imports(self):
        forbidden_modules = {"time", "random", "uuid", "requests", "httpx",
                             "sqlalchemy", "os", "sys", "socket", "pathlib"}
        forbidden_identifiers = {"BrokerAdapter", "Order", "UserApproval",
                                 "RiskDecision", "authorize", "place_order"}
        for path in self._PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(
                        alias.name.split(".")[0] not in forbidden_modules
                        for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert node.module is None or \
                        node.module.split(".")[0] not in forbidden_modules
                elif isinstance(node, ast.Name):
                    assert node.id not in forbidden_identifiers

    def test_lifecycle_package_does_not_read_wall_clock(self):
        for path in self._PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and \
                        node.attr in {"now", "utcnow", "today"}:
                    raise AssertionError(
                        f"wall-clock access found: {node.attr}")
