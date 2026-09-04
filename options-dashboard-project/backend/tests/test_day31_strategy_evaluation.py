"""Day 31 — Strategy Evaluation Engine tests (RED-phase contract).

Proves the deterministic, broker-neutral strategy-evaluation boundary:

    Strategy Candidate -> Strategy Evaluation -> Evaluation Result

The evaluator reuses the authoritative Day-18 leg/scenario/greek math
(evaluate_leg / evaluate_portfolio on OptionLeg + CalculationContext) and
consumes caller-supplied payoff / regime / liquidity / risk / historical
evidence.  It NEVER creates orders, execution intents, positions or risk
authorization; it never reads the wall clock.

Rules locked here
-----------------
1. Context (OPPORTUNITY/PAPER/BACKTEST/RESEARCH) is metadata only:
   identical canonical inputs yield identical quantitative assessments
   regardless of context.
2. Missing != zero everywhere; missing components stay missing/None;
   evidence-free dimensions are UNAVAILABLE, never neutral or favorable.
3. Regime label alone never fabricates directional evidence; regime
   compatibility requires directional inputs.
4. Payoff math is NOT duplicated: Day 31 consumes authoritative
   caller-supplied payoff metrics; mixed-expiry approximations are
   explicitly flagged; same-expiry exact semantics preserved.
5. Greeks/scenarios orchestrate the authoritative Day-18 engine (no BSM
   copy); model sensitivities are never claimed as broker Greeks.
6. Historical behaviour is only present when real point-in-time evidence
   is supplied; no fabricated historical score.
7. Confidence and quality are echoed separately; the result contains no
   single opaque suitability number (each dimension is inspectable).
8. Status ladder: all seven dimensions assessable => SUCCESS; some
   unavailable => PARTIAL; none assessable => UNAVAILABLE; an INVALID
   supplied dimension => INVALID.
9. Evidence rows + structured issues make every assessment traceable;
   Opportunity provenance preserved when present, never synthesized.
10. Deterministic serialization, stable ordering, no wall clock, no IO,
    no broker imports, no execution side effects (AST-guarded).
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.opportunity.contracts import Opportunity
from app.opportunity.pipeline import discover_opportunity
from app.quant.contracts import CalculationContext
from app.quant.scenarios import (
    OptionLeg,
    PositionDirection,
    ScenarioPoint,
    evaluate_portfolio,
)
from app.market_data.contracts import Side
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
from app.strategy_evaluation.contracts import (  # module absent until GREEN
    DimensionState,
    EvaluationContext,
    EvaluationDimension,
    EvaluationEvidence,
    EvaluationIssue,
    HistoricalEvidence,
    LiquidityEvidence,
    PayoffEvidence,
    PayoffExpirySemantics,
    RegimeCompatibility,
    RiskEvidence,
    StrategyEvaluationInput,
    StrategyEvaluationResult,
    StrategyEvaluationStatus,
    TailClass,
)
from app.strategy_evaluation.evaluation import evaluate_strategy

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"
_EXPIRY = "2026-09-24"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _prov(source: str = "UPSTOX_SNAPSHOT_NORMALIZED") -> Provenance:
    return Provenance(
        source=source,
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


def _ctx() -> CalculationContext:
    return CalculationContext(
        reference_timestamp=_REF,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        model_version="1.0.0",
        calculation_version="1.0.0",
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
            source_reference_id="synthesis:NIFTY:2026-09-24:bull",
            evidence_type=EvidenceType.QUANT_DERIVED,
            value=strength, unit="score_0_1", reference_timestamp=_REF,
            provenance=_prov(), model_version="1.0.0",
            calculation_version="1.0.0"),),
        quality=_quality(),
        provenance=_prov(),
        reference_timestamp=_REF,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


def _opportunity(opp_id: str = "opp-1") -> Opportunity:
    obs = __import__("app.opportunity.contracts", fromlist=["Observation"]).Observation(
        observation_id="obs-1", underlying=NIFTY, expiry=_EXPIRY,
        upstream=_synthesis())
    return discover_opportunity(obs, signal_id="sig-1", setup_id="stp-1",
                                opportunity_id=opp_id)


def _leg(*, side: Side = Side.CALL, strike: float = 100.0,
         quantity: float = 1.0,
         direction: PositionDirection = PositionDirection.LONG,
         entry_price: float | None = 9.0,
         implied_volatility: float | None = 0.2,
         quality: QualityState | None = QualityState.EXCELLENT,
         prov=_UNSET) -> OptionLeg:
    return OptionLeg(
        option_type=side,
        strike=strike,
        expiry=_EXPIRY,
        quantity=quantity,
        direction=direction,
        entry_price=entry_price,
        implied_volatility=implied_volatility,
        quality=quality,
        provenance=_prov() if prov is _UNSET else prov,
    )


def _points(*spots: float) -> tuple[ScenarioPoint, ...]:
    return tuple(
        ScenarioPoint(spot=s, time_to_expiry=0.01, implied_volatility=0.2)
        for s in spots)


def _payoff(state: DimensionState = DimensionState.AVAILABLE,
           semantics: PayoffExpirySemantics = PayoffExpirySemantics.SAME_EXPIRY_EXACT,
           net: float | None = 1.0, max_profit: float | None = 100.0,
           max_loss: float | None = -50.0,
           tail: TailClass = TailClass.NONE,
           breakevens: tuple[float, ...] = (105.0,),
           prov=_UNSET) -> PayoffEvidence:
    return PayoffEvidence(
        state=state, expiry_semantics=semantics, net_debit_credit=net,
        max_profit=max_profit, max_loss=max_loss, tail=tail,
        breakevens=breakevens,
        provenance=_prov("payoff-bnd") if prov is _UNSET else prov)


def _full_inp(**overrides) -> StrategyEvaluationInput:
    """A fully-evidenced evaluation (SUCCESS path unless overridden)."""
    kwargs = dict(
        strategy_id="strat-1",
        legs=(_leg(),),
        evaluation_context=EvaluationContext.OPPORTUNITY,
        reference_timestamp=_REF,
        spot=100.0,
        time_to_expiry=0.01,
        implied_volatility=0.2,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        payoff=_payoff(),
        market_regime=MarketRegime(label=RegimeLabel.TRENDING,
                                   source="intelligence.regime.v1",
                                   model_version="1.0.0",
                                   reference_timestamp=_REF),
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
        scenario_points=_points(95.0, 100.0, 105.0),
        confidence=0.7,
        quality=_quality(),
    )
    kwargs.update(overrides)
    return StrategyEvaluationInput(**kwargs)


# ---------------------------------------------------------------------------
# 1. Contract construction / validation
# ---------------------------------------------------------------------------


class TestContractValidation:
    def test_invalid_strategy_id(self):
        with pytest.raises(ValueError):
            _full_inp(strategy_id="")

    def test_empty_legs_rejected(self):
        with pytest.raises(ValueError):
            _full_inp(legs=())

    def test_invalid_context_rejected(self):
        with pytest.raises(ValueError):
            _full_inp(evaluation_context="LIVE")  # type: ignore[arg-type]

    def test_naive_reference_timestamp_rejected(self):
        with pytest.raises(ValueError):
            _full_inp(reference_timestamp=datetime(2026, 9, 3, 10, 0, 0))

    def test_non_positive_spot_rejected(self):
        with pytest.raises(ValueError):
            _full_inp(spot=0.0)
        with pytest.raises(ValueError):
            _full_inp(spot=float("nan"))

    def test_negative_time_to_expiry_rejected(self):
        with pytest.raises(ValueError):
            _full_inp(time_to_expiry=-0.1)

    def test_confidence_range_enforced(self):
        with pytest.raises(ValueError):
            _full_inp(confidence=1.5)

    def test_context_vocabulary(self):
        vals = {c.value for c in EvaluationContext}
        assert vals == {"OPPORTUNITY", "PAPER", "BACKTEST", "RESEARCH"}

    def test_scenario_point_validation(self):
        # ScenarioPoint (Day-18) is authoritative pure data; the Day-31
        # input boundary rejects invalid scenario coordinates
        # deterministically (never NaN/Infinity/silent coercion).
        with pytest.raises(ValueError):
            _full_inp(scenario_points=(
                ScenarioPoint(spot=-1.0, time_to_expiry=0.01,
                              implied_volatility=0.2),))
        with pytest.raises(ValueError):
            _full_inp(scenario_points=(
                ScenarioPoint(spot=100.0, time_to_expiry=-0.01,
                              implied_volatility=0.2),))
        with pytest.raises(ValueError):
            _full_inp(scenario_points=(
                ScenarioPoint(spot=100.0, time_to_expiry=0.01,
                              implied_volatility=-0.2),))
        with pytest.raises(ValueError):
            _full_inp(scenario_points=(
                ScenarioPoint(spot=float("nan"), time_to_expiry=0.01,
                              implied_volatility=0.2),))


# ---------------------------------------------------------------------------
# 2. Payoff dimension
# ---------------------------------------------------------------------------


class TestPayoff:
    def test_payoff_metrics_preserved_verbatim(self):
        r = evaluate_strategy(_full_inp())
        p = r.payoff_assessment
        assert p.state is DimensionState.AVAILABLE
        assert p.net_debit_credit == 1.0
        assert p.max_profit == 100.0
        assert p.max_loss == -50.0
        assert p.tail is TailClass.NONE
        assert p.breakevens == (105.0,)
        assert p.expiry_semantics is PayoffExpirySemantics.SAME_EXPIRY_EXACT

    def test_mixed_expiry_approximation_flagged(self):
        r = evaluate_strategy(_full_inp(
            payoff=_payoff(semantics=PayoffExpirySemantics.MIXED_EXPIRY_APPROXIMATE)))
        assert r.payoff_assessment.expiry_semantics is \
            PayoffExpirySemantics.MIXED_EXPIRY_APPROXIMATE
        assert "approximate" in r.payoff_assessment.note.lower()

    def test_missing_payoff_metrics_stay_missing(self):
        r = evaluate_strategy(_full_inp(payoff=_payoff(
            net=None, max_profit=None, max_loss=None, breakevens=())))
        p = r.payoff_assessment
        assert p.net_debit_credit is None
        assert p.max_profit is None and p.max_loss is None
        assert p.breakevens == ()

    def test_no_payoff_evidence_unavailable(self):
        r = evaluate_strategy(_full_inp(payoff=None))
        assert r.payoff_assessment.state is DimensionState.UNAVAILABLE

    def test_unbounded_tail_classification_preserved(self):
        r = evaluate_strategy(_full_inp(payoff=_payoff(
            max_profit=None, tail=TailClass.UNLIMITED_GAIN)))
        assert r.payoff_assessment.tail is TailClass.UNLIMITED_GAIN


# ---------------------------------------------------------------------------
# 3. Greeks dimension (authoritative reuse)
# ---------------------------------------------------------------------------


class TestGreeks:
    def test_greeks_match_authoritative_engine(self):
        inp = _full_inp()
        r = evaluate_strategy(inp)
        g = r.greek_assessment
        assert g.state is DimensionState.AVAILABLE
        portfolio = evaluate_portfolio(
            inp.legs, _ctx(), spot=inp.spot,
            time_to_expiry=inp.time_to_expiry)
        # exact reuse: identical numbers, not a copied BSM implementation
        assert g.delta == portfolio.delta
        assert g.gamma == portfolio.gamma
        assert g.theta == portfolio.theta
        assert g.vega == portfolio.vega
        assert all(v is not None for v in (g.delta, g.gamma, g.theta, g.vega))

    def test_short_put_exposure_semantics(self):
        # short call: exposure-scaled greeks flip sign via the Day-18 engine
        inp = _full_inp(legs=(_leg(side=Side.CALL, strike=100.0,
                                   direction=PositionDirection.SHORT,
                                   entry_price=9.0),))
        r = evaluate_strategy(inp)
        assert r.greek_assessment.delta is not None
        assert r.greek_assessment.delta < 0.0  # short call delta negative

    def test_quantity_scales_exposure(self):
        one = evaluate_strategy(_full_inp(legs=(_leg(quantity=1.0),)))
        five = evaluate_strategy(_full_inp(legs=(_leg(quantity=5.0),)))
        assert five.greek_assessment.delta == pytest.approx(
            5.0 * one.greek_assessment.delta, rel=1e-9)

    def test_unpriceable_leg_keeps_missing_not_zero(self):
        # no IV anywhere => the authoritative engine cannot price: missing
        leg = _leg(implied_volatility=None)
        inp = _full_inp(legs=(leg,), implied_volatility=None)
        r = evaluate_strategy(inp)
        g = r.greek_assessment
        # components stay missing (None) -- never coerced to zero
        assert g.delta is None and g.gamma is None
        assert g.theta is None and g.vega is None
        assert g.state is DimensionState.UNAVAILABLE

    def test_multiplier_and_broker_model_separation_absent(self):
        # no broker-Greek claims: assessments expose only model sensitivities
        r = evaluate_strategy(_full_inp())
        assert r.greek_assessment.greeks_source == "MODEL"


# ---------------------------------------------------------------------------
# 4. Scenario dimension (authoritative reuse)
# ---------------------------------------------------------------------------


class TestScenarios:
    def test_empty_scenario_points_unavailable(self):
        r = evaluate_strategy(_full_inp(scenario_points=()))
        assert r.scenario_assessment.state is DimensionState.UNAVAILABLE

    def test_scenario_points_assessed_with_identity(self):
        pts = _points(95.0, 105.0)
        r = evaluate_strategy(_full_inp(scenario_points=pts))
        s = r.scenario_assessment
        assert s.state is DimensionState.AVAILABLE
        assert s.points_total == 2
        assert s.points_assessed == 2
        assert s.spot_values == (95.0, 105.0)

    def test_partial_scenario_warning_propagates(self):
        # one leg with provenance=None => authoritative engine partial
        bad = _leg(prov=None)
        r = evaluate_strategy(_full_inp(
            legs=(_leg(), bad), scenario_points=_points(100.0)))
        assert r.scenario_assessment.state is DimensionState.PARTIAL
        assert r.scenario_assessment.unavailable_reasons

    def test_min_max_pnl_over_complete_points(self):
        pts = _points(90.0, 100.0, 110.0)
        r = evaluate_strategy(_full_inp(
            legs=(_leg(entry_price=9.0),), scenario_points=pts))
        s = r.scenario_assessment
        assert s.min_pnl is not None and s.max_pnl is not None
        assert s.min_pnl <= s.max_pnl


# ---------------------------------------------------------------------------
# 5. Regime dimension
# ---------------------------------------------------------------------------


class TestRegime:
    def test_regime_compatible(self):
        r = evaluate_strategy(_full_inp(
            regime_direction=IntelligenceDirection.BULLISH,
            strategy_direction=IntelligenceDirection.BULLISH))
        assert r.regime_assessment.state is DimensionState.AVAILABLE
        assert r.regime_assessment.compatibility is RegimeCompatibility.COMPATIBLE

    def test_regime_conflicted(self):
        r = evaluate_strategy(_full_inp(
            regime_direction=IntelligenceDirection.BEARISH,
            strategy_direction=IntelligenceDirection.BULLISH))
        assert r.regime_assessment.compatibility is RegimeCompatibility.CONFLICTED

    def test_label_alone_never_fabricates_direction(self):
        r = evaluate_strategy(_full_inp(
            regime_direction=None, strategy_direction=None))
        a = r.regime_assessment
        assert a.compatibility is RegimeCompatibility.NON_DIRECTIONAL
        assert "never" in a.note.lower() or "direction" in a.note.lower()

    def test_missing_regime_unavailable(self):
        r = evaluate_strategy(_full_inp(market_regime=None))
        assert r.regime_assessment.state is DimensionState.UNAVAILABLE
        assert r.regime_assessment.compatibility is None

    def test_regime_label_metadata_preserved(self):
        r = evaluate_strategy(_full_inp())
        assert r.regime_assessment.regime_label is RegimeLabel.TRENDING

    def test_unbounded_risk_structure_flagged_not_authorized(self):
        r = evaluate_strategy(_full_inp(risk=RiskEvidence(
            state=DimensionState.AVAILABLE, structural_unbounded_loss=True,
            max_loss_estimate=None, notes=("naked short",),
            provenance=_prov("risk-bnd"))))
        a = r.risk_assessment
        assert a.structural_unbounded_loss is True
        assert a.max_loss_estimate is None  # unknown magnitude stays missing
        assert a.informational_only is True


# ---------------------------------------------------------------------------
# 6. Liquidity / risk / historical
# ---------------------------------------------------------------------------


class TestLiquidityRiskHistorical:
    def test_liquidity_available(self):
        r = evaluate_strategy(_full_inp())
        assert r.liquidity_assessment.state is DimensionState.AVAILABLE
        assert r.liquidity_assessment.spread_bps == 2.5
        assert r.liquidity_assessment.legs_complete == 1

    def test_liquidity_missing_is_unavailable_not_zero(self):
        r = evaluate_strategy(_full_inp(liquidity=None))
        a = r.liquidity_assessment
        assert a.state is DimensionState.UNAVAILABLE
        assert a.spread_bps is None  # missing != zero

    def test_risk_represented_without_authorization(self):
        r = evaluate_strategy(_full_inp())
        a = r.risk_assessment
        assert a.state is DimensionState.AVAILABLE
        assert a.structural_unbounded_loss is False
        assert a.max_loss_estimate == 50.0
        assert a.informational_only is True
        # risk note is deterministic and names its evidence
        assert a.note
        assert "authoriz" not in a.note.lower()

    def test_risk_missing_unavailable(self):
        r = evaluate_strategy(_full_inp(risk=None))
        assert r.risk_assessment.state is DimensionState.UNAVAILABLE

    def test_historical_available_only_with_real_evidence(self):
        r = evaluate_strategy(_full_inp())
        assert r.historical_assessment.state is DimensionState.AVAILABLE
        assert r.historical_assessment.observations == 120

    def test_historical_unavailable_no_fabricated_score(self):
        r = evaluate_strategy(_full_inp(historical=None))
        a = r.historical_assessment
        assert a.state is DimensionState.UNAVAILABLE
        assert a.observations is None
        assert not a.metric_note  # no invented performance summary


# ---------------------------------------------------------------------------
# 7. Evidence / provenance / status
# ---------------------------------------------------------------------------


class TestEvidenceProvenanceStatus:
    def test_evidence_rows_cover_supplied_dimensions(self):
        r = evaluate_strategy(_full_inp())
        assert len(r.evidence) >= 5
        kinds = {e.dimension for e in r.evidence}
        assert EvaluationDimension.PAYOFF in kinds
        assert EvaluationDimension.GREEKS in kinds

    def test_opportunity_provenance_preserved(self):
        opp = _opportunity("opp-9")
        r = evaluate_strategy(_full_inp(opportunity=opp))
        assert r.opportunity_id == "opp-9"
        assert r.provenance is opp.provenance

    def test_provenance_never_synthesized(self):
        r = evaluate_strategy(_full_inp(opportunity=None))
        assert r.provenance is None

    def test_full_status_success(self):
        r = evaluate_strategy(_full_inp())
        assert r.status is StrategyEvaluationStatus.SUCCESS

    def test_partial_status_when_a_dimension_unavailable(self):
        r = evaluate_strategy(_full_inp(historical=None, risk=None))
        assert r.status is StrategyEvaluationStatus.PARTIAL

    def test_invalid_supplied_dimension_makes_result_invalid(self):
        r = evaluate_strategy(_full_inp(payoff=_payoff(state=DimensionState.INVALID)))
        assert r.status is StrategyEvaluationStatus.INVALID

    def test_issues_name_unavailable_dimensions(self):
        r = evaluate_strategy(_full_inp(historical=None))
        assert r.issues
        assert EvaluationDimension.HISTORICAL in {i.dimension for i in r.issues}

    def test_confidence_quality_echoed_separately(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_strategy(_full_inp(confidence=0.42, quality=q))
        assert r.confidence == 0.42
        assert r.quality is q

    def test_confidence_never_changes_quantitative_output(self):
        base = evaluate_strategy(_full_inp(confidence=0.1))
        high = evaluate_strategy(_full_inp(confidence=0.9))
        assert base.greek_assessment.delta == high.greek_assessment.delta
        assert base.scenario_assessment.min_pnl == \
            high.scenario_assessment.min_pnl


# ---------------------------------------------------------------------------
# 7b. Remediation — dimension-level provenance (approved design §8)
# ---------------------------------------------------------------------------


class TestDimensionProvenance:
    """Dimension evidence provenance must survive into the final result.

    Lineage locked here (Day-9 canonical Provenance reused, never
    synthesized): caller-supplied dimension evidence provenance -> final
    dimension assessment + evidence row -> to_dict/from_dict round trip.
    """

    def _ev_for(self, dim: EvaluationDimension, r: StrategyEvaluationResult):
        return next(e for e in r.evidence if e.dimension is dim)

    def test_payoff_provenance_preserved(self):
        prov = _prov("payoff-src")
        r = evaluate_strategy(_full_inp(payoff=_payoff(prov=prov)))
        assert r.payoff_assessment.provenance is prov
        assert self._ev_for(EvaluationDimension.PAYOFF, r).provenance == prov

    def test_liquidity_provenance_preserved(self):
        prov = _prov("liq-src")
        r = evaluate_strategy(_full_inp(liquidity=LiquidityEvidence(
            state=DimensionState.AVAILABLE, legs_complete=1, legs_total=1,
            spread_bps=2.5, quality=QualityState.EXCELLENT,
            provenance=prov)))
        assert r.liquidity_assessment.provenance is prov
        assert self._ev_for(EvaluationDimension.LIQUIDITY, r).provenance == prov

    def test_risk_provenance_preserved(self):
        prov = _prov("risk-src")
        r = evaluate_strategy(_full_inp(risk=RiskEvidence(
            state=DimensionState.AVAILABLE, structural_unbounded_loss=False,
            max_loss_estimate=50.0, notes=("debit spread",),
            provenance=prov)))
        assert r.risk_assessment.provenance is prov
        assert self._ev_for(EvaluationDimension.RISK, r).provenance == prov

    def test_historical_provenance_preserved(self):
        prov = _prov("hist-src")
        r = evaluate_strategy(_full_inp(historical=HistoricalEvidence(
            state=DimensionState.AVAILABLE, observations=120,
            metric_note="point-in-time supplied", provenance=prov)))
        assert r.historical_assessment.provenance is prov
        assert self._ev_for(EvaluationDimension.HISTORICAL,
                            r).provenance == prov

    def test_uniform_leg_provenance_preserved_on_greeks_and_scenario(self):
        prov = _prov("leg-src")
        r = evaluate_strategy(_full_inp(legs=(_leg(prov=prov),)))
        assert r.greek_assessment.provenance == prov
        assert r.scenario_assessment.provenance == prov
        assert self._ev_for(EvaluationDimension.GREEKS,
                            r).provenance == prov
        assert self._ev_for(EvaluationDimension.SCENARIO,
                            r).provenance == prov

    def test_mixed_leg_provenance_never_synthesized(self):
        # two legs from two different sources: aggregate greeks/scenario
        # provenance is None (per-leg provenance remains on the legs)
        r = evaluate_strategy(_full_inp(legs=(
            _leg(prov=_prov("leg-a")), _leg(strike=110.0, prov=_prov("leg-b"))),
            scenario_points=_points(100.0)))
        assert r.greek_assessment.provenance is None
        assert r.scenario_assessment.provenance is None

    def test_missing_dimension_provenance_stays_none(self):
        r = evaluate_strategy(_full_inp(
            payoff=_payoff(prov=None),
            legs=(_leg(prov=None),),
            liquidity=LiquidityEvidence(
                state=DimensionState.AVAILABLE, legs_complete=1,
                legs_total=1, spread_bps=2.5,
                quality=QualityState.EXCELLENT, provenance=None),
            risk=RiskEvidence(state=DimensionState.AVAILABLE,
                              structural_unbounded_loss=False,
                              max_loss_estimate=50.0,
                              provenance=None),
            historical=HistoricalEvidence(
                state=DimensionState.AVAILABLE, observations=120,
                metric_note="point-in-time supplied", provenance=None)))
        assert r.payoff_assessment.provenance is None
        assert r.liquidity_assessment.provenance is None
        assert r.risk_assessment.provenance is None
        assert r.historical_assessment.provenance is None
        assert r.greek_assessment.provenance is None
        assert all(e.provenance is None for e in r.evidence)

    def test_opportunity_provenance_never_overwrites_dimension_provenance(self):
        dim_prov = _prov("payoff-src")
        opp = _opportunity("opp-prov")
        r = evaluate_strategy(_full_inp(payoff=_payoff(prov=dim_prov),
                                        opportunity=opp))
        # top-level provenance is the Opportunity's; the dimension keeps
        # its own distinct source
        assert r.provenance is opp.provenance
        assert opp.provenance != dim_prov
        assert r.payoff_assessment.provenance is dim_prov
        assert self._ev_for(EvaluationDimension.PAYOFF,
                            r).provenance == dim_prov

    def test_dimension_provenance_round_trip(self):
        r = evaluate_strategy(_full_inp(
            payoff=_payoff(prov=_prov("payoff-src")),
            liquidity=LiquidityEvidence(
                state=DimensionState.AVAILABLE, legs_complete=1,
                legs_total=1, spread_bps=2.5,
                quality=QualityState.EXCELLENT, provenance=_prov("liq-src")),
            risk=RiskEvidence(state=DimensionState.AVAILABLE,
                              structural_unbounded_loss=False,
                              max_loss_estimate=50.0,
                              provenance=_prov("risk-src")),
            historical=HistoricalEvidence(
                state=DimensionState.AVAILABLE, observations=120,
                metric_note="point-in-time supplied",
                provenance=_prov("hist-src")),
            legs=(_leg(prov=_prov("leg-src")),),
            opportunity=_opportunity("opp-rt")))
        r2 = StrategyEvaluationResult.from_dict(
            json.loads(json.dumps(r.to_dict())))
        assert r2.to_dict() == r.to_dict()
        for a in (r2.payoff_assessment, r2.liquidity_assessment,
                  r2.risk_assessment, r2.historical_assessment,
                  r2.greek_assessment, r2.scenario_assessment):
            assert a.provenance is not None
        assert r2.provenance is not None  # Opportunity provenance intact


# ---------------------------------------------------------------------------
# 7c. Remediation — PARTIAL must never become SUCCESS (design §6)
# ---------------------------------------------------------------------------


class TestStatusLadderRemediation:
    """A PARTIAL dimension must keep the overall status PARTIAL."""

    def test_partial_dimension_never_becomes_success(self):
        # liquidity supplied with PARTIAL state; everything else AVAILABLE
        r = evaluate_strategy(_full_inp(liquidity=LiquidityEvidence(
            state=DimensionState.PARTIAL, legs_complete=1, legs_total=2,
            spread_bps=None, quality=QualityState.DEGRADED,
            provenance=_prov("liq-partial"))))
        assert r.liquidity_assessment.state is DimensionState.PARTIAL
        assert r.status is StrategyEvaluationStatus.PARTIAL

    def test_partial_payoff_dimension_never_becomes_success(self):
        r = evaluate_strategy(_full_inp(
            payoff=_payoff(state=DimensionState.PARTIAL)))
        assert r.payoff_assessment.state is DimensionState.PARTIAL
        assert r.status is StrategyEvaluationStatus.PARTIAL

    def test_all_available_is_success(self):
        r = evaluate_strategy(_full_inp())
        assert r.status is StrategyEvaluationStatus.SUCCESS

    def test_all_unavailable_is_unavailable(self):
        r = evaluate_strategy(_full_inp(
            legs=(_leg(implied_volatility=None),),
            implied_volatility=None,
            scenario_points=(), payoff=None, market_regime=None,
            liquidity=None, risk=None, historical=None))
        assert r.status is StrategyEvaluationStatus.UNAVAILABLE

    def test_mixed_available_and_unavailable_is_partial(self):
        r = evaluate_strategy(_full_inp(historical=None))
        assert r.status is StrategyEvaluationStatus.PARTIAL

    def test_invalid_dimension_still_invalid(self):
        r = evaluate_strategy(
            _full_inp(payoff=_payoff(state=DimensionState.INVALID)))
        assert r.status is StrategyEvaluationStatus.INVALID


# ---------------------------------------------------------------------------
# 8. Context equivalence / determinism
# ---------------------------------------------------------------------------


class TestContextAndDeterminism:
    def test_context_never_changes_quantitative_result(self):
        outputs = {}
        for c in EvaluationContext:
            r = evaluate_strategy(_full_inp(evaluation_context=c))
            d = r.to_dict()
            d.pop("evaluation_context")
            outputs[c] = d
        assert len({repr(v) for v in outputs.values()}) == 1

    def test_repeated_execution_byte_identical(self):
        r1 = evaluate_strategy(_full_inp())
        r2 = evaluate_strategy(_full_inp())
        assert json.dumps(r1.to_dict(), sort_keys=True) == \
            json.dumps(r2.to_dict(), sort_keys=True)

    def test_serialization_round_trip(self):
        r = evaluate_strategy(_full_inp(opportunity=_opportunity("o1")))
        r2 = StrategyEvaluationResult.from_dict(
            json.loads(json.dumps(r.to_dict())))
        assert r2.to_dict() == r.to_dict()


# ---------------------------------------------------------------------------
# 9. Purity / boundary
# ---------------------------------------------------------------------------


class TestPurityAndBoundary:
    _PKG = pathlib.Path(__file__).resolve().parents[1] / "app" / "strategy_evaluation"

    def test_no_broker_or_execution_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi",
                     "redis", "time"}
        for path in self._PKG.glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"now", "utcnow", "today",
                                                  "time", "sleep"}
                if isinstance(node, ast.Import):
                    for a in node.names:
                        assert a.name.split(".")[0] not in forbidden
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for banned in ("app.brokers", "app.services", "app.routers",
                                   "app.market_data.gateway", "app.streaming",
                                   "app.db", "app.models", "app.opportunity.scalping"):
                        assert not module.startswith(banned)

    def test_no_order_execution_vocabulary(self):
        for path in self._PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in ("place_order", "submit_order", "modify_order",
                          "cancel_order", "create_order", "order_router",
                          "broker_client", "execute("):
                assert token not in text

    def test_no_wall_clock_or_random_tokens(self):
        for path in self._PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in ("datetime.now", "datetime.utcnow", "uuid", "random.",
                          "time.time()"):
                assert token not in text

    def test_no_risk_authorization_vocabulary(self):
        for path in self._PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8").upper()
            for token in ("ALLOW", "WARN", "BLOCK"):
                assert token not in text.replace("WARNING", "")
