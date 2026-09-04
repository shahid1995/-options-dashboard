"""Day 36 — Final Risk Gate tests (TDD, genuine upstream objects).

Proves the deterministic final-gate boundary:

    eligible Day-32 StrategyCandidate
        + Day-33 CentralRiskResult
        + Day-35 PortfolioAnalyticsResult
        + explicit FinalRiskPolicy + caller-supplied reference timestamp
        -> evaluate_final_gate(...)
        -> FinalRiskGateResult (dimension assessments + rules + evidence)

Semantics locked here
---------------------
1. PASS means ONLY "permitted to proceed to the User Decision boundary" --
   never execution-approved, never a broker order, never a trade decision.
2. Day-33 is consumed whole; Day-33 BLOCKED/INVALID/UNAVAILABLE/PARTIAL map
   to the identical gate status (never manufactured into approval).
3. Portfolio evidence is consumed from genuine Day-35 analytics (empty
   portfolio is a measured zero; a missing portfolio is UNAVAILABLE).
4. No new quantitative mathematics and no invented thresholds: every
   numeric rule requires an explicit configured cap; ``None`` = the rule is
   not configured (absent, like Day-33 policy fields).
5. Broker/model source separation is preserved end to end -- a projected
   delta is formed ONLY when the candidate and the portfolio share one
   source; mixed sources are never summed.
6. Missing data stays missing (never zero / favorable). Regime labels never
   manufacture direction; unknown regime stays unknown.
7. Deterministic precedence: INVALID > BLOCKED > UNAVAILABLE > PARTIAL > PASS.
8. The gate is safe to call with no broker/execution/database infrastructure
   (pure domain, AST-guarded).
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.central_risk.contracts import (
    CentralRiskResult,
    CentralRiskStatus,
    GreekRisk,
    PayoffRisk,
    PolicyAssessment,
    PolicyRuleCode,
    PolicyRuleResult,
    RiskEvidence,
    RiskPolicy,
    ScenarioRisk,
    StructuralRisk,
)
from app.central_risk.engine import assess_candidate_risk
from app.final_risk_gate.contracts import (
    FINAL_RISK_GATE_CALCULATION_VERSION,
    FINAL_RISK_GATE_CONTRACT_VERSION,
    FinalRiskGateDimension,
    FinalRiskGateInput,
    FinalRiskGateResult,
    FinalRiskIssueCode,
    FinalRiskPolicy,
    FinalRiskRuleCode,
    FinalRiskStatus,
    GateDimensionAssessment,
    GateRuleResult,
    GreekDeltaRead,
    PolicyGateAssessment,
    final_gate_from_dict,
    final_gate_to_dict,
)
from app.final_risk_gate.gate import (
    evaluate_final_gate,
    evaluate_final_risk_gate,
)
from app.market_data.contracts import Provenance, QualityState, Side
from app.market_data.quality import QualityResult
from app.portfolio_intelligence.analytics import analyze_portfolio
from app.portfolio_intelligence.contracts import (
    GreekInput,
    PortfolioPosition,
    PositionSource,
)
from app.quant.scenarios import PositionDirection
from app.strategy_evaluation.contracts import DimensionState
from app.strategy_lifecycle.contracts import StrategyCandidate, StrategyLifecycleState

# Day-33/35 genuine builders reused below -------------------------------------------------

REF = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
NIFTY = "NIFTY"
EXPIRY = "2026-09-24"


def _prov(source: str = "test.final-gate.v1") -> Provenance:
    return Provenance(
        source=source,
        collection_mode="BROKER_SNAPSHOT",
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


# --- genuine Day-31/32 evaluation + candidate (engine-built, mirrors Day-33) ---


def _leg(*, side: Side = Side.CALL, strike: float = 20000.0,
         quantity: float = 1.0,
         direction: PositionDirection = PositionDirection.LONG,
         entry_price: float | None = 100.0) -> object:
    from app.quant.scenarios import OptionLeg

    return OptionLeg(
        option_type=side, strike=strike, expiry=EXPIRY, quantity=quantity,
        direction=direction, entry_price=entry_price,
        implied_volatility=0.2, quality=QualityState.EXCELLENT,
        provenance=_prov("LEG"),
    )


def _day31_evaluation(*, legs=None) -> object:
    """A genuine Day-31 SUCCESS StrategyEvaluationResult via the real engine."""
    from app.intelligence.contracts import (
        IntelligenceDirection,
        MarketRegime,
        RegimeLabel,
    )
    from app.quant.scenarios import ScenarioPoint
    from app.strategy_evaluation.contracts import (
        EvaluationContext,
        HistoricalEvidence,
        LiquidityEvidence,
        PayoffEvidence,
        PayoffExpirySemantics,
        RiskEvidence as Day31RiskEvidence,
        StrategyEvaluationInput,
        TailClass,
    )
    from app.strategy_evaluation.evaluation import evaluate_strategy

    return evaluate_strategy(StrategyEvaluationInput(
        strategy_id="strategy-1",
        legs=(_leg(),) if legs is None else legs,
        evaluation_context=EvaluationContext.OPPORTUNITY,
        reference_timestamp=REF,
        spot=20000.0,
        time_to_expiry=0.01,
        implied_volatility=0.2,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        payoff=PayoffEvidence(
            state=DimensionState.AVAILABLE,
            expiry_semantics=PayoffExpirySemantics.SAME_EXPIRY_EXACT,
            net_debit_credit=1.0, max_profit=100.0, max_loss=-50.0,
            tail=TailClass.NONE, breakevens=(20050.0,),
            provenance=_prov("payoff-bnd")),
        market_regime=MarketRegime(label=RegimeLabel.RANGING,
                                   source="intelligence.regime.v1",
                                   model_version="1.0.0",
                                   reference_timestamp=REF),
        regime_direction=IntelligenceDirection.NEUTRAL,
        strategy_direction=IntelligenceDirection.NEUTRAL,
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
        scenario_points=(ScenarioPoint(spot=19900.0, time_to_expiry=0.01,
                                       implied_volatility=0.2),
                         ScenarioPoint(spot=20000.0, time_to_expiry=0.01,
                                       implied_volatility=0.2),
                         ScenarioPoint(spot=20100.0, time_to_expiry=0.01,
                                       implied_volatility=0.2)),
        confidence=0.7,
        quality=_quality(),
    ))


def _candidate(evaluation=None, *, candidate_id: str | None = None,
               lifecycle: StrategyLifecycleState = StrategyLifecycleState.ELIGIBLE) -> StrategyCandidate:
    """Genuine contract-valid Day-32 candidate around a genuine Day-31
    evaluation (same composition as the Day-33 suite)."""
    from app.opportunity.contracts import ExpectedBehavior
    from app.strategy_lifecycle.contracts import StrategyCandidate

    evaluation = evaluation if evaluation is not None else _day31_evaluation()
    return StrategyCandidate(
        candidate_id=candidate_id
        if candidate_id is not None
        else "candidate:opp-1:strategy-1:strike-20000",
        opportunity_id="opp-1",
        strategy_id="strategy-1",
        legs=evaluation.legs,
        selected_strike_ids=("strike-20000",),
        expected_behavior=(
            ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE),
        invalidation_conditions=("spot breaks strike-20000",),
        evaluation=evaluation,
        lifecycle_state=lifecycle,
        confidence=evaluation.confidence,
        quality=evaluation.quality,
        reference_timestamp=REF,
        provenance=_prov("candidate"),
    )


# --- genuine Day-33 CentralRiskResult builders (typed contract objects) ---


def _day33_result(*, status: CentralRiskStatus = CentralRiskStatus.PASS,
                  candidate: StrategyCandidate | None = None,
                  greek_delta: float | None = 0.5,
                  greeks_source: str | None = "MODEL",
                  min_pnl: float | None = -25.0,
                  blocking: tuple[PolicyRuleResult, ...] = ()) -> CentralRiskResult:
    candidate = candidate if candidate is not None else _candidate()
    evaluation = candidate.evaluation
    payoff = PayoffRisk(
        state=DimensionState.AVAILABLE, max_profit=100.0, max_loss=-50.0,
        loss_unbounded=False, breakevens=(20050.0,),
        note="debit spread bounded loss", provenance=_prov("payoff"))
    greek = GreekRisk(
        state=DimensionState.AVAILABLE, delta=greek_delta, gamma=0.0001,
        theta=-5.0, vega=2.0, legs_priced=1, legs_total=1,
        greeks_source=greeks_source, note="priced",
        provenance=_prov("greeks"))
    scenario = ScenarioRisk(
        state=DimensionState.AVAILABLE, points_total=3, points_assessed=3,
        min_pnl=min_pnl, max_pnl=25.0,
        note="worst supplied scenario P/L", provenance=_prov("scenario"))
    structural = StructuralRisk(state=DimensionState.AVAILABLE,
                                note="supported", provenance=_prov("struct"))
    rules: tuple[PolicyRuleResult, ...] = ()
    if status is CentralRiskStatus.PASS:
        rules = (PolicyRuleResult(rule=PolicyRuleCode.MAX_STANDALONE_LOSS,
                                  passed=True,
                                  message="loss within cap"),)
    return CentralRiskResult(
        status=status,
        candidate_id=candidate.candidate_id,
        opportunity_id=candidate.opportunity_id,
        strategy_id=candidate.strategy_id,
        payoff_risk=payoff,
        greek_risk=greek,
        scenario_risk=scenario,
        structural_risk=structural,
        policy_assessment=PolicyAssessment(
            policy_version="policy-1.0", rules=rules),
        blocking_reasons=blocking,
        evidence=(RiskEvidence(kind="PAYOFF", source="day31-payoff-assessment",
                               note="bounded", provenance=_prov("payoff")),),
        issues=(),
        confidence=evaluation.confidence,
        quality=evaluation.quality,
        provenance=candidate.provenance,
        reference_timestamp=REF,
        contract_version="1.0.0",
        model_version=evaluation.model_version,
        calculation_version="central_risk.v1",
    )


def _blocked_day33(candidate=None) -> CentralRiskResult:
    return _day33_result(
        status=CentralRiskStatus.BLOCKED,
        candidate=candidate,
        blocking=(PolicyRuleResult(rule=PolicyRuleCode.MAX_STANDALONE_LOSS,
                                   passed=False,
                                   message="maximum standalone loss exceeded",
                                   limit=100.0, observed=250.0),),
    )


# --- genuine Day-35 PortfolioAnalyticsResult builders (real engine) ---


def _greek_input(*, delta: float = 0.4, gamma: float = 0.0001,
                 source: str = "MODEL") -> GreekInput:
    return GreekInput(delta=delta, gamma=gamma, theta=-3.0, vega=1.0, rho=0.5,
                      source=source, quality=QualityState.EXCELLENT,
                      provenance=_prov("model-greeks"),
                      calc_model="BLACK_SCHOLES_EUROPEAN",
                      calc_version="1.0.0")


def _portfolio_position(*, position_id: str = "p1", tenant_id: str = "tenant-A",
                        quantity: float = 1.0,
                        direction: PositionDirection = PositionDirection.LONG,
                        delta: float = 0.4,
                        greeks_source: str = "MODEL") -> PortfolioPosition:
    return PortfolioPosition(
        position_id=position_id,
        tenant_id=tenant_id,
        source=PositionSource.PAPER,
        underlying=NIFTY,
        expiry=EXPIRY,
        strike=20000.0,
        option_type=Side.CALL,
        quantity=quantity,
        direction=direction,
        lot_size=75,
        entry_price=100.0,
        current_price=None,
        market_value=None,
        spot=None,
        greeks=_greek_input(delta=delta, source=greeks_source),
        quality=QualityState.EXCELLENT,
        provenance=_prov("paper-pos"),
        reference_timestamp=REF,
    )


def _portfolio(positions=(), *, regime=None, tenant_id: str = "tenant-A",
               scenario_rows=()) -> object:
    positions = tuple(positions)
    # ensure consistent tenant
    positions = tuple(
        _portfolio_position(position_id=p, tenant_id=tenant_id) if isinstance(p, str) else p
        for p in positions
    )
    return analyze_portfolio(
        positions, regime=regime, scenario_rows=scenario_rows,
        reference_timestamp=REF, analysis_provenance=_prov("portfolio-analysis"),
    )


def _empty_portfolio(tenant_id: str = "tenant-A") -> object:
    return _portfolio([], tenant_id=tenant_id)


def _ranging_regime():
    from app.intelligence.contracts import MarketRegime, RegimeLabel

    return MarketRegime(label=RegimeLabel.RANGING, source="day23.regime",
                        model_version="2.1.0", reference_timestamp=REF)


def _policy(*, version: str = "final-policy-1.0",
            maximum_portfolio_delta: float | None = None,
            maximum_projected_delta: float | None = None,
            maximum_concentration_share: float | None = None,
            maximum_portfolio_age_seconds: float | None = None,
            disallowed_regimes=()) -> FinalRiskPolicy:
    return FinalRiskPolicy(
        policy_version=version,
        maximum_portfolio_delta=maximum_portfolio_delta,
        maximum_projected_delta=maximum_projected_delta,
        maximum_concentration_share=maximum_concentration_share,
        maximum_portfolio_age_seconds=maximum_portfolio_age_seconds,
        disallowed_regimes=tuple(disallowed_regimes),
    )


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------


class TestFinalRiskPolicyContract:
    def test_valid_policy_constructs(self):
        policy = _policy(maximum_portfolio_delta=500.0)
        assert policy.policy_version == "final-policy-1.0"
        assert policy.maximum_portfolio_delta == 500.0
        assert policy.maximum_projected_delta is None

    def test_blank_version_rejected(self):
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="", maximum_portfolio_delta=1.0)

    def test_negative_cap_rejected(self):
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p", maximum_portfolio_delta=-1.0)
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p", maximum_projected_delta=-0.1)

    def test_concentration_cap_must_be_valid_share(self):
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p", maximum_concentration_share=1.5)
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p", maximum_concentration_share=0.0)

    def test_unconfigured_rule_is_explicitly_none_not_zero(self):
        policy = _policy()
        assert policy.maximum_portfolio_delta is None
        assert policy.maximum_projected_delta is None
        assert policy.maximum_concentration_share is None
        assert policy.maximum_portfolio_age_seconds is None
        assert policy.disallowed_regimes == ()

    def test_negative_age_cap_rejected(self):
        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p",
                            maximum_portfolio_age_seconds=-5.0)

    def test_disallowed_regimes_must_be_regime_labels(self):
        from app.intelligence.contracts import RegimeLabel

        with pytest.raises(ValueError):
            FinalRiskPolicy(policy_version="p", disallowed_regimes=("X",))  # type: ignore[arg-type]
        p = _policy(disallowed_regimes=(RegimeLabel.HIGH_VOLATILITY,))
        assert p.disallowed_regimes == (RegimeLabel.HIGH_VOLATILITY,)

    def test_policy_round_trip(self):
        from app.intelligence.contracts import RegimeLabel

        p = _policy(maximum_portfolio_age_seconds=60.0,
                    disallowed_regimes=(RegimeLabel.HIGH_VOLATILITY,))
        restored = FinalRiskPolicy.from_dict(p.to_dict())
        assert restored == p


class TestFinalRiskGateInput:
    def test_input_bundle_validates_types(self):
        inp = FinalRiskGateInput(
            candidate=_candidate(), central_risk=_day33_result(),
            portfolio=_empty_portfolio(), policy=_policy(),
            tenant_id="tenant-A")
        assert inp.candidate.candidate_id.startswith("candidate:")
        with pytest.raises(ValueError):
            FinalRiskGateInput(candidate="not-a-candidate",  # type: ignore[arg-type]
                               central_risk=_day33_result(),
                               portfolio=None, policy=_policy())
        with pytest.raises(ValueError):
            FinalRiskGateInput(candidate=_candidate(), central_risk="x",  # type: ignore[arg-type]
                               portfolio=None, policy=_policy())
        with pytest.raises(ValueError):
            FinalRiskGateInput(candidate=_candidate(), central_risk=_day33_result(),
                               portfolio=_empty_portfolio(), policy="x")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            FinalRiskGateInput(candidate=_candidate(), central_risk=_day33_result(),
                               portfolio=_empty_portfolio(), policy=_policy(),
                               tenant_id="  ")

    def test_canonical_entrypoint_parity_with_wrapper(self):
        """The approved plan entrypoint ``evaluate_final_risk_gate`` accepts
        the immutable input bundle and agrees with the positional wrapper."""
        candidate = _candidate()
        central = _day33_result(candidate=candidate)
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        policy = _policy(maximum_concentration_share=1.0)
        via_bundle = evaluate_final_risk_gate(
            FinalRiskGateInput(candidate=candidate, central_risk=central,
                               portfolio=portfolio, policy=policy,
                               tenant_id="tenant-A"),
            reference_timestamp=REF)
        via_wrapper = evaluate_final_gate(
            candidate, central, portfolio, policy=policy,
            reference_timestamp=REF, tenant_id="tenant-A")
        assert via_bundle.status is via_wrapper.status
        assert json.dumps(final_gate_to_dict(via_bundle), sort_keys=True) == \
            json.dumps(final_gate_to_dict(via_wrapper), sort_keys=True)


# ---------------------------------------------------------------------------
# Core status ladder
# ---------------------------------------------------------------------------


class TestStatusLadder:
    def test_valid_candidate_day33_pass_with_measured_portfolio(self):
        """Well-formed inputs with a single-source portfolio reach PASS."""
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        assert result.central_risk_status is CentralRiskStatus.PASS

    def test_day33_blocked_maps_to_blocked(self):
        result = evaluate_final_gate(
            _candidate(), _blocked_day33(), _empty_portfolio(),
            policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.BLOCKED
        assert result.blocking_reasons
        assert result.central_risk_status is CentralRiskStatus.BLOCKED

    def test_day33_invalid_maps_to_invalid(self):
        result = evaluate_final_gate(
            _candidate(), _day33_result(status=CentralRiskStatus.INVALID),
            _empty_portfolio(), policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.INVALID

    def test_day33_unavailable_maps_to_unavailable(self):
        result = evaluate_final_gate(
            _candidate(), _day33_result(status=CentralRiskStatus.UNAVAILABLE),
            _empty_portfolio(), policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.UNAVAILABLE

    def test_day33_partial_maps_to_partial_not_pass(self):
        result = evaluate_final_gate(
            _candidate(), _day33_result(status=CentralRiskStatus.PARTIAL),
            _empty_portfolio(), policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.PARTIAL
        assert result.status is not FinalRiskStatus.PASS

    def test_missing_portfolio_is_unavailable_not_approval(self):
        result = evaluate_final_gate(
            _candidate(), _day33_result(), None,
            policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.UNAVAILABLE
        assert any(i.code is FinalRiskIssueCode.PORTFOLIO_REQUIRED
                   for i in result.issues)

    def test_identity_mismatch_is_invalid(self):
        other = _candidate(candidate_id="candidate:opp-9:strategy-9:strike-1")
        result = evaluate_final_gate(
            other,
            _day33_result(candidate=_candidate()),
            _empty_portfolio(), policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.INVALID
        assert any(i.code is FinalRiskIssueCode.IDENTITY_MISMATCH
                   for i in result.issues)

    def test_cross_tenant_input_is_invalid(self):
        portfolio = _portfolio(["p1"], tenant_id="tenant-A")
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-B")
        assert result.status is FinalRiskStatus.INVALID
        assert any(i.code is FinalRiskIssueCode.TENANT_MISMATCH
                   for i in result.issues)


class TestStructuralGate:
    def test_incomplete_candidate_is_invalid(self):
        """An incomplete candidate (still CANDIDATE lifecycle -- never passed
        the Opportunity Gate) is structurally INVALID for the final gate.
        Empty-leg candidates cannot be constructed upstream: Day-31 rejects
        empty legs and Day-32 never gates them into ELIGIBLE."""
        incomplete = _candidate(
            lifecycle=StrategyLifecycleState.CANDIDATE)
        result = evaluate_final_gate(
            incomplete, _day33_result(candidate=incomplete), _empty_portfolio(),
            policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.INVALID
        assert any(i.code is FinalRiskIssueCode.STRUCTURAL_INVALID
                   for i in result.issues)

    def test_non_eligible_candidate_is_invalid(self):
        candidate = _candidate()
        from app.strategy_lifecycle.contracts import StrategyCandidate

        stale = StrategyCandidate(
            candidate_id=candidate.candidate_id,
            opportunity_id=candidate.opportunity_id,
            strategy_id=candidate.strategy_id,
            legs=candidate.legs,
            selected_strike_ids=candidate.selected_strike_ids,
            expected_behavior=candidate.expected_behavior,
            invalidation_conditions=candidate.invalidation_conditions,
            evaluation=candidate.evaluation,
            lifecycle_state=StrategyLifecycleState.BLOCKED,
            confidence=candidate.confidence, quality=candidate.quality,
            reference_timestamp=REF, provenance=candidate.provenance,
        )
        result = evaluate_final_gate(
            stale, _day33_result(candidate=stale), _empty_portfolio(),
            policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.INVALID


class TestPortfolioImpactAndGreeks:
    def test_portfolio_exposure_and_delta_impact_read(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        candidate = _candidate()
        result = evaluate_final_gate(
            candidate, _day33_result(candidate=candidate), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        impact = {d.dimension: d for d in result.dimensions}
        assert impact[FinalRiskGateDimension.PORTFOLIO_IMPACT].status \
            is FinalRiskStatus.PASS
        assert result.portfolio.position_count == 1
        # Per-source delta read: candidate (MODEL 0.5) + portfolio (MODEL 0.4)
        model = next(r for r in result.portfolio.delta_reads
                     if r.source == "MODEL")
        assert model.current_delta == pytest.approx(0.4)
        assert model.candidate_delta == pytest.approx(0.5)
        assert model.projected_delta == pytest.approx(0.9)

    def test_missing_portfolio_greek_stays_missing_never_zero(self):
        # Portfolio with delta evidence absent (position without greeks) must
        # never present a zero current delta.
        pos = PortfolioPosition(
            position_id="p1", tenant_id="tenant-A", source=PositionSource.PAPER,
            underlying=NIFTY, expiry=EXPIRY, strike=20000.0,
            option_type=Side.CALL, quantity=1.0,
            direction=PositionDirection.LONG, lot_size=75,
            entry_price=100.0, current_price=None, market_value=None,
            spot=None, greeks=None, quality=QualityState.EXCELLENT,
            provenance=_prov("paper-pos"), reference_timestamp=REF)
        portfolio = analyze_portfolio((pos,), regime=_ranging_regime(),
                                      reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS  # no configured delta rule
        model = [r for r in result.portfolio.delta_reads
                 if r.source == "MODEL"][0]
        assert model.current_delta is None  # missing stays missing
        assert model.current_delta != 0.0

    def test_projected_delta_cap_violation_blocks(self):
        # Candidate delta 0.5 + portfolio delta 0.4 -> projected 0.9 > cap 0.5
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_projected_delta=0.5),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        assert any(r.rule is FinalRiskRuleCode.MAX_PROJECTED_DELTA
                   and r.passed is False for r in result.policy.rules)

    def test_mixed_sources_never_summed_into_projected(self):
        # BROKER portfolio delta 0.4 + MODEL candidate delta 0.5 -> no source
        # shares both -> projected must stay unverifiable, never 0.9.
        portfolio = _portfolio(
            ["p1"], regime=_ranging_regime())
        # rebuild the single position with BROKER-source greeks
        pos = _portfolio_position(position_id="p1", tenant_id="tenant-A",
                                  delta=0.4, greeks_source="BROKER")
        portfolio = analyze_portfolio((pos,), regime=_ranging_regime(),
                                      reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_projected_delta=0.5),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PARTIAL
        reads = {r.source: r for r in result.portfolio.delta_reads}
        assert reads["BROKER"].current_delta == pytest.approx(0.4)
        assert reads["BROKER"].candidate_delta is None
        assert reads["BROKER"].projected_delta is None
        assert reads["MODEL"].candidate_delta == pytest.approx(0.5)
        assert reads["MODEL"].current_delta is None
        assert reads["MODEL"].projected_delta is None

    def test_missing_candidate_delta_makes_projected_rule_unverifiable(self):
        candidate = _candidate()
        day33 = _day33_result(candidate=candidate, greek_delta=None)
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            candidate, day33, portfolio,
            policy=_policy(maximum_projected_delta=0.5),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PARTIAL
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_PROJECTED_DELTA)
        assert rule.passed is None

    def test_portfolio_delta_cap_evaluated_per_source(self):
        portfolio = _portfolio(
            ["p1"], regime=_ranging_regime())
        pos = _portfolio_position(position_id="p1", tenant_id="tenant-A",
                                  delta=60.0, greeks_source="MODEL")
        portfolio = analyze_portfolio((pos,), regime=_ranging_regime(),
                                      reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_portfolio_delta=50.0),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_PORTFOLIO_DELTA)
        assert rule.passed is False
        assert rule.observed == pytest.approx(60.0)

    def test_scenario_context_read_from_day33_and_day35(self):
        from app.portfolio_intelligence.contracts import ScenarioRow

        rows = (ScenarioRow(tenant_id="tenant-A", point_id="20000",
                            spot=20000.0, time_to_expiry=0.01,
                            implied_volatility=0.2, total_pnl=-30.0,
                            partial=False, quality=QualityState.EXCELLENT,
                            provenance=_prov("scenario-row")),)
        portfolio = analyze_portfolio((_portfolio_position(),), regime=None,
                                      scenario_rows=rows, reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(min_pnl=-25.0), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        # Day-33 worst scenario read is authoritative on the result.
        assert result.portfolio.day33_worst_scenario_pnl == pytest.approx(-25.0)


class TestConcentrationGate:
    def test_concentration_cap_violation_blocks(self):
        # portfolio option-type slice: one CALL position -> CE share 1.0
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_concentration_share=0.5),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_CONCENTRATION_SHARE)
        assert rule.passed is False

    def test_concentration_within_cap_passes(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_concentration_share=1.0),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_CONCENTRATION_SHARE)
        assert rule.passed is True
        assert rule.observed == pytest.approx(1.0)

    def test_empty_portfolio_concentration_unverifiable(self):
        result = evaluate_final_gate(
            _candidate(), _day33_result(), _empty_portfolio(),
            policy=_policy(maximum_concentration_share=0.5),
            reference_timestamp=REF)
        assert result.status is FinalRiskStatus.PARTIAL
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_CONCENTRATION_SHARE)
        assert rule.passed is None


class TestDirectionalAndRegime:
    def test_directional_dimension_blocks_on_delta_cap(self):
        pos = _portfolio_position(position_id="p1", tenant_id="tenant-A",
                                  delta=60.0, greeks_source="MODEL")
        portfolio = analyze_portfolio((pos,), regime=_ranging_regime(),
                                      reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_portfolio_delta=50.0),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        dim = next(d for d in result.dimensions
                   if d.dimension is FinalRiskGateDimension.DIRECTIONAL)
        assert dim.status is FinalRiskStatus.BLOCKED

    def test_regime_disallowed_label_blocks(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.HIGH_VOLATILITY,
                              source="day23.regime", model_version="2.1.0",
                              reference_timestamp=REF)
        portfolio = analyze_portfolio((_portfolio_position(),), regime=regime,
                                      reference_timestamp=REF)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(disallowed_regimes=(RegimeLabel.HIGH_VOLATILITY,)),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.REGIME_ALLOWLIST)
        assert rule.passed is False

    def test_regime_not_disallowed_passes(self):
        from app.intelligence.contracts import RegimeLabel

        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(disallowed_regimes=(RegimeLabel.HIGH_VOLATILITY,)),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.REGIME_ALLOWLIST)
        assert rule.passed is True

    def test_unknown_regime_with_regime_rule_is_unverifiable(self):
        from app.intelligence.contracts import RegimeLabel

        portfolio = _portfolio(["p1"], regime=None)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(disallowed_regimes=(RegimeLabel.HIGH_VOLATILITY,)),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PARTIAL
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.REGIME_ALLOWLIST)
        assert rule.passed is None

    def test_directional_context_is_descriptive(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        dim = next(d for d in result.dimensions
                   if d.dimension is FinalRiskGateDimension.DIRECTIONAL)
        assert dim.status is FinalRiskStatus.PASS
        # No bull/bear probability or prediction vocabulary anywhere.
        assert not hasattr(result, "bull_probability")
        assert not hasattr(result.portfolio, "direction_vote")

    def test_regime_consumed_and_never_fabricates_direction(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        regime_dim = next(d for d in result.dimensions
                          if d.dimension is FinalRiskGateDimension.REGIME)
        assert regime_dim.status is FinalRiskStatus.PASS

    def test_unknown_regime_stays_unknown_partial(self):
        portfolio = _portfolio(["p1"], regime=None)
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        regime_dim = next(d for d in result.dimensions
                          if d.dimension is FinalRiskGateDimension.REGIME)
        assert regime_dim.status is FinalRiskStatus.UNAVAILABLE
        # The gate records no directional read from a missing regime.
        assert result.portfolio.regime_label is None


class TestDataQuality:
    def test_missing_candidate_quality_recorded_never_invented(self):
        """Quality/freshness failure (design + plan Task 2): a candidate with
        no quality evidence can never produce a false PASS -- the gate is
        deterministic PARTIAL and the CANDIDATE_QUALITY rule is
        unverifiable."""
        candidate = _candidate()
        from app.strategy_lifecycle.contracts import StrategyCandidate

        no_quality = StrategyCandidate(
            candidate_id=candidate.candidate_id,
            opportunity_id=candidate.opportunity_id,
            strategy_id=candidate.strategy_id,
            legs=candidate.legs,
            selected_strike_ids=candidate.selected_strike_ids,
            expected_behavior=candidate.expected_behavior,
            invalidation_conditions=candidate.invalidation_conditions,
            evaluation=candidate.evaluation,
            lifecycle_state=StrategyLifecycleState.ELIGIBLE,
            confidence=candidate.confidence, quality=None,
            reference_timestamp=REF, provenance=candidate.provenance,
        )
        result = evaluate_final_gate(
            no_quality, _day33_result(candidate=no_quality),
            _empty_portfolio(), policy=_policy(), reference_timestamp=REF)
        assert result.status is FinalRiskStatus.PARTIAL
        quality_dim = next(d for d in result.dimensions
                           if d.dimension is FinalRiskGateDimension.DATA_QUALITY)
        assert quality_dim.status is FinalRiskStatus.PARTIAL
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.CANDIDATE_QUALITY)
        assert rule.passed is None
        assert any("quality" in i.message.lower() for i in result.issues)

    def test_stale_portfolio_analytics_blocked_by_freshness_cap(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())  # ref = REF
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_portfolio_age_seconds=60.0),
            reference_timestamp=REF + timedelta(hours=1), tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.BLOCKED
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_PORTFOLIO_AGE)
        assert rule.passed is False
        assert rule.observed == pytest.approx(3600.0)

    def test_fresh_portfolio_passes_freshness_cap(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_portfolio_age_seconds=7200.0),
            reference_timestamp=REF + timedelta(hours=1), tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_PORTFOLIO_AGE)
        assert rule.passed is True

    def test_future_dated_portfolio_freshness_unverifiable(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(maximum_portfolio_age_seconds=60.0),
            reference_timestamp=REF - timedelta(hours=1), tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PARTIAL
        rule = next(r for r in result.policy.rules
                    if r.rule is FinalRiskRuleCode.MAX_PORTFOLIO_AGE)
        assert rule.passed is None


class TestBoundaryNoExecution:
    def test_pass_is_not_execution_approved(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        result = evaluate_final_gate(
            _candidate(), _day33_result(), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.status is FinalRiskStatus.PASS
        text = json.dumps(final_gate_to_dict(result))
        for banned in ("APPROVED", "EXECUTION", "ORDER_ID", "FILL",
                       "MARGIN", "CAPITAL", "BROKER_ORDER"):
            assert banned not in text, f"found banned token {banned!r}"
        assert not hasattr(result, "execution_authorized")
        assert not hasattr(result, "order")

    def test_no_execution_vocabulary_in_contract(self):
        import app.final_risk_gate.contracts as contracts

        names = " ".join(contracts.__dict__.keys())
        for banned in ("Order", "Execution", "Fill", "Broker"):
            assert banned not in names


class TestDeterminismAndSerialization:
    def test_repeated_execution_byte_identical(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        kwargs = dict(policy=_policy(maximum_projected_delta=10.0),
                      reference_timestamp=REF, tenant_id="tenant-A")
        a = evaluate_final_gate(_candidate(), _day33_result(), portfolio, **kwargs)
        b = evaluate_final_gate(_candidate(), _day33_result(), portfolio, **kwargs)
        assert json.dumps(final_gate_to_dict(a), sort_keys=True) == \
            json.dumps(final_gate_to_dict(b), sort_keys=True)

    def test_serialization_round_trip(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        candidate = _candidate()
        result = evaluate_final_gate(
            candidate, _day33_result(candidate=candidate), portfolio,
            policy=_policy(maximum_concentration_share=1.0),
            reference_timestamp=REF, tenant_id="tenant-A")
        restored = final_gate_from_dict(final_gate_to_dict(result))
        assert isinstance(restored, FinalRiskGateResult)
        assert restored.status is result.status
        assert restored.candidate_id == result.candidate_id
        assert [r.rule for r in restored.policy.rules] == \
            [r.rule for r in result.policy.rules]
        assert restored.portfolio.delta_reads == result.portfolio.delta_reads
        assert restored.reference_timestamp == REF
        # Round trip is byte identical.
        assert json.dumps(final_gate_to_dict(restored), sort_keys=True) == \
            json.dumps(final_gate_to_dict(result), sort_keys=True)

    def test_versions_and_identity_echoed(self):
        portfolio = _portfolio(["p1"], regime=_ranging_regime())
        candidate = _candidate()
        result = evaluate_final_gate(
            candidate, _day33_result(candidate=candidate), portfolio,
            policy=_policy(), reference_timestamp=REF, tenant_id="tenant-A")
        assert result.contract_version == FINAL_RISK_GATE_CONTRACT_VERSION
        assert result.calculation_version == FINAL_RISK_GATE_CALCULATION_VERSION
        assert result.candidate_id == candidate.candidate_id
        assert result.strategy_id == candidate.strategy_id
        assert result.opportunity_id == candidate.opportunity_id
        assert result.reference_timestamp == REF

    def test_naive_reference_timestamp_rejected(self):
        with pytest.raises(ValueError):
            evaluate_final_gate(
                _candidate(), _day33_result(), _empty_portfolio(),
                policy=_policy(),
                reference_timestamp=datetime(2026, 9, 4, 10, 0))


# ---------------------------------------------------------------------------
# Genuine end-to-end chain (Day-32 gate -> Day-33 -> Day-36)
# ---------------------------------------------------------------------------


class TestGenuineChain:
    def test_full_chain_pass(self):
        """Genuine Day-28->30->31->32 pipeline candidate, genuine Day-33
        assessment and genuine Day-35 analytics reach a Day-36 PASS."""
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
        from app.opportunity.contracts import Observation
        from app.opportunity.pipeline import discover_opportunity
        from app.quant.scenarios import ScenarioPoint
        from app.strike_ranking.contracts import (
            FactorObservation,
            OptionType,
            RankingFactor,
            StrikeCandidateInput,
            StrikeRankingInput,
        )
        from app.strike_ranking.ranking import DEFAULT_RANKING_WEIGHTS, rank_strikes
        from app.strategy_evaluation.contracts import (
            EvaluationContext,
            HistoricalEvidence,
            LiquidityEvidence,
            PayoffEvidence,
            PayoffExpirySemantics,
            RiskEvidence as Day31RiskEvidence,
            StrategyEvaluationInput,
            TailClass,
        )
        from app.strategy_evaluation.evaluation import evaluate_strategy
        from app.strategy_lifecycle.lifecycle import evaluate_strategy_gate

        synthesis = IntelligenceResult(
            calculation_id="intelligence.synthesis.v1",
            status=IntelligenceStatus.SUCCESS,
            direction=IntelligenceDirection.BULLISH,
            signal_strength=0.5,
            confidence=0.75,
            time_horizon=TimeHorizon.EXPIRY,
            observation=IntelligenceObservation(
                metric_name="synthesis_strength", value=0.5,
                unit="score_0_1"),
            evidence=(IntelligenceEvidence(
                source_reference_id="synthesis:NIFTY:2026-09-24:bull",
                evidence_type=EvidenceType.QUANT_DERIVED,
                value=0.5, unit="score_0_1", reference_timestamp=REF,
                provenance=_prov(), model_version="1.0.0",
                calculation_version="1.0.0"),),
            quality=_quality(),
            provenance=_prov(),
            reference_timestamp=REF,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version="1.0.0",
            calculation_version="1.0.0",
        )
        observation = Observation(
            observation_id="obs-1", underlying=NIFTY, expiry=EXPIRY,
            upstream=synthesis)
        opportunity = discover_opportunity(
            observation, signal_id="sig-1", setup_id="stp-1",
            opportunity_id="opp-1")
        factors = tuple(
            FactorObservation(factor=f, score=0.8) for f in RankingFactor)
        ranked = rank_strikes(StrikeRankingInput(
            candidates=(
                StrikeCandidateInput(candidate_id="strike-20000",
                                     underlying=NIFTY,
                                     option_type=OptionType.CE,
                                     strike=20000.0, expiry=EXPIRY,
                                     factors=factors,
                                     opportunity=opportunity),
                StrikeCandidateInput(candidate_id="strike-20500",
                                     underlying=NIFTY,
                                     option_type=OptionType.PE,
                                     strike=20500.0, expiry=EXPIRY,
                                     factors=factors,
                                     opportunity=opportunity),
            ),
            weights=DEFAULT_RANKING_WEIGHTS, objective_id="dir-bull"))
        evaluation = evaluate_strategy(StrategyEvaluationInput(
            strategy_id="strategy-1",
            legs=(_leg(),),
            evaluation_context=EvaluationContext.OPPORTUNITY,
            reference_timestamp=REF,
            spot=20000.0,
            time_to_expiry=0.01,
            implied_volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            payoff=PayoffEvidence(
                state=DimensionState.AVAILABLE,
                expiry_semantics=PayoffExpirySemantics.SAME_EXPIRY_EXACT,
                net_debit_credit=1.0, max_profit=100.0, max_loss=-50.0,
                tail=TailClass.NONE, breakevens=(20050.0,),
                provenance=_prov("payoff-bnd")),
            market_regime=MarketRegime(label=RegimeLabel.RANGING,
                                       source="intelligence.regime.v1",
                                       model_version="1.0.0",
                                       reference_timestamp=REF),
            regime_direction=IntelligenceDirection.NEUTRAL,
            strategy_direction=IntelligenceDirection.NEUTRAL,
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
                metric_note="point-in-time supplied",
                provenance=_prov("hist-bnd")),
            scenario_points=(ScenarioPoint(spot=19900.0,
                                           time_to_expiry=0.01,
                                           implied_volatility=0.2),
                             ScenarioPoint(spot=20100.0,
                                           time_to_expiry=0.01,
                                           implied_volatility=0.2)),
            confidence=0.7,
            quality=_quality(),
            opportunity=opportunity,
        ))
        gate = evaluate_strategy_gate(
            opportunity, ranked, evaluation, strategy_id="strategy-1",
            legs=evaluation.legs)
        assert gate.eligible and gate.candidate is not None
        candidate = gate.candidate

        policy = RiskPolicy(policy_version="policy-1.0",
                            maximum_standalone_loss=200.0,
                            allow_unbounded_loss=False,
                            maximum_scenario_loss=200.0)
        central = assess_candidate_risk(candidate, policy,
                                        reference_timestamp=REF)
        assert central.status is CentralRiskStatus.PASS

        portfolio = analyze_portfolio(
            (_portfolio_position(),), regime=_ranging_regime(),
            reference_timestamp=REF)
        final = evaluate_final_gate(
            candidate, central, portfolio,
            policy=_policy(maximum_concentration_share=1.0),
            reference_timestamp=REF, tenant_id="tenant-A")
        assert final.status is FinalRiskStatus.PASS
        assert final.central_risk_status is CentralRiskStatus.PASS
        assert final.candidate_id == candidate.candidate_id


# ---------------------------------------------------------------------------
# Purity: no forbidden surfaces in the Day-36 domain
# ---------------------------------------------------------------------------

_BANNED_ROOTS = (
    "sqlalchemy", "fastapi", "requests", "httpx", "urllib", "socket",
    "subprocess", "redis", "os", "sys", "random", "secrets", "uuid",
    "pathlib", "brokers", "routers", "services", "db", "models",
    "datetime.now", "utcnow", "time.time",
)


def test_domain_modules_pure():
    root = Path(__file__).resolve().parents[1] / "app" / "final_risk_gate"
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    assert mod not in _BANNED_ROOTS, (
                        f"{path.name} imports forbidden module {mod}")
            elif isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in ("datetime", "utcnow", "uuid4", "random"):
                    raise AssertionError(
                        f"{path.name} calls wall-clock/random {name}")
