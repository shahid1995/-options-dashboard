"""Day 31 — Deterministic strategy evaluation orchestration.

``evaluate_strategy(StrategyEvaluationInput) -> StrategyEvaluationResult``
is a pure domain orchestrator.  It delegates all quantitative mathematics
to the authoritative Day-18 scenario/leg engine (``evaluate_leg`` /
``evaluate_portfolio`` on ``OptionLeg`` + ``CalculationContext``) and
consumes caller-supplied payoff / regime / liquidity / risk / historical
evidence verbatim.

Rules enforced here
-------------------
* The engine never reads the wall clock: the caller-supplied
  ``reference_timestamp`` is the only notion of "now", and the Day-14
  ``CalculationContext`` is built solely from explicit input fields.
* Context (OPPORTUNITY/PAPER/BACKTEST/RESEARCH) is echoed metadata only
  and never changes the quantitative assessments.
* Missing evidence yields UNAVAILABLE dimensions (never zero/neutral);
  partially priceable legs yield PARTIAL with structured reasons;
  INVALID supplied evidence yields an INVALID result.
* Payoff metrics are reported verbatim (never recomputed, never
  fabricated); mixed-expiry valuations stay flagged approximate.
* Regime compatibility requires directional inputs; a regime label alone
  never fabricates direction.
* Risk is informational/evaluative only -- no authorization member exists.
* Historical behaviour exists only from supplied point-in-time evidence.
* Confidence and Day-12 quality are echoed and never influence any
  assessment state or value.
* Opportunity provenance (Day-28) is preserved when present; it is never
  synthesized when absent.
* No order/execution/position/risk-authorization objects are created.
"""

from __future__ import annotations

from app.intelligence.contracts import IntelligenceDirection, MarketRegime
from app.market_data.contracts import Provenance
from app.quant.contracts import CalculationContext, CalculationStatus
from app.quant.scenarios import PortfolioScenarioResult, evaluate_portfolio
from app.strategy_evaluation.contracts import (
    DimensionState,
    EvaluationDimension,
    EvaluationEvidence,
    EvaluationIssue,
    GreekAssessment,
    HistoricalAssessment,
    LiquidityAssessment,
    PayoffAssessment,
    PayoffExpirySemantics,
    RegimeAssessment,
    RegimeCompatibility,
    RiskAssessment,
    ScenarioAssessment,
    StrategyEvaluationInput,
    StrategyEvaluationResult,
    StrategyEvaluationStatus,
)

_ALL_DIMENSIONS: tuple[EvaluationDimension, ...] = tuple(EvaluationDimension)

_DIRECTIONAL = (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH)


def _context_for(inp: StrategyEvaluationInput) -> CalculationContext:
    return CalculationContext(
        reference_timestamp=inp.reference_timestamp,
        risk_free_rate=inp.risk_free_rate,
        dividend_yield=inp.dividend_yield,
        model_version=inp.model_version,
        calculation_version=inp.calculation_version,
    )


def _portfolio_at(inp: StrategyEvaluationInput, *, spot: float,
                  time_to_expiry: float,
                  implied_volatility: float | None) -> PortfolioScenarioResult:
    return evaluate_portfolio(
        inp.legs, _context_for(inp), spot=spot,
        time_to_expiry=time_to_expiry,
        implied_volatility=implied_volatility,
    )


def _shared_leg_provenance(inp: StrategyEvaluationInput) -> Provenance | None:
    """Single shared provenance when every leg carries the same Day-9 source.

    Aggregated Greek/scenario assessments span all legs: provenance is
    attributed only when every leg is present with one identical source;
    mixed or partially-missing leg provenance yields ``None`` (per-leg
    provenance stays on the legs; nothing is synthesized).
    """
    provs = [leg.provenance for leg in inp.legs]
    if not provs or any(p is None for p in provs):
        return None
    first = provs[0]
    return first if all(p == first for p in provs) else None


def _assess_payoff(inp: StrategyEvaluationInput) -> tuple[PayoffAssessment, str]:
    ev = inp.payoff
    if ev is None:
        return (PayoffAssessment(
            state=DimensionState.UNAVAILABLE, expiry_semantics=None,
            net_debit_credit=None, max_profit=None, max_loss=None,
            tail=None, breakevens=(), note="no payoff evidence supplied",
            provenance=None),
            "no payoff evidence supplied")
    note = (f"payoff metrics supplied (state {ev.state.value}; "
            f"semantics {ev.expiry_semantics.value})")
    if ev.expiry_semantics is PayoffExpirySemantics.MIXED_EXPIRY_APPROXIMATE:
        note += " -- mixed-expiry result is an approximation, not exact"
    return (PayoffAssessment(
        state=ev.state, expiry_semantics=ev.expiry_semantics,
        net_debit_credit=ev.net_debit_credit, max_profit=ev.max_profit,
        max_loss=ev.max_loss, tail=ev.tail, breakevens=ev.breakevens,
        note=note, provenance=ev.provenance), note)


def _assess_greeks(inp: StrategyEvaluationInput) -> tuple[GreekAssessment, str]:
    port = _portfolio_at(inp, spot=inp.spot,
                         time_to_expiry=inp.time_to_expiry,
                         implied_volatility=inp.implied_volatility)
    priced = sum(1 for r in port.leg_results
                 if r.status is CalculationStatus.SUCCESS)
    total = len(port.leg_results)
    reasons = tuple(f"{i.code.value}: {i.message}" for i in port.unavailable_reasons)
    if priced == 0:
        state = DimensionState.UNAVAILABLE
        note = (f"no leg priced by the authoritative Day-18 engine "
                f"({len(reasons)} reason(s))")
    elif priced < total:
        state = DimensionState.PARTIAL
        note = (f"{priced}/{total} legs priced by the authoritative engine "
                "-- partial greek exposure; missing components stay missing")
    else:
        state = DimensionState.AVAILABLE
        note = "model greeks aggregated by the authoritative Day-18 engine"
    return (GreekAssessment(
        state=state, delta=port.delta, gamma=port.gamma, theta=port.theta,
        vega=port.vega, legs_priced=priced, legs_total=total,
        greeks_source="MODEL", note=note,
        provenance=_shared_leg_provenance(inp)), note)


def _assess_scenarios(inp: StrategyEvaluationInput) -> tuple[ScenarioAssessment, str]:
    if not inp.scenario_points:
        return (ScenarioAssessment(
            state=DimensionState.UNAVAILABLE, points_total=0,
            points_assessed=0, spot_values=(), min_pnl=None, max_pnl=None,
            unavailable_reasons=(),
            note="no scenario points supplied -- scenario dimension unavailable",
            provenance=_shared_leg_provenance(inp)),
            "no scenario points supplied")
    pnls: list[float] = []
    partial_points = 0
    reasons: list[str] = []
    assessed = 0
    for point in inp.scenario_points:
        port = _portfolio_at(inp, spot=point.spot,
                             time_to_expiry=point.time_to_expiry,
                             implied_volatility=point.implied_volatility)
        if port.partial:
            partial_points += 1
            reasons.extend(f"{i.code.value}: {i.message}"
                           for i in port.unavailable_reasons)
        if not port.partial and port.total_pnl is not None:
            pnls.append(port.total_pnl)
        assessed += 1
    state = DimensionState.PARTIAL if partial_points else DimensionState.AVAILABLE
    note = (f"{assessed - partial_points}/{assessed} scenario points fully "
            "priced by the authoritative Day-18 engine")
    if reasons:
        note += f"; {len(reasons)} warning(s) propagated"
    return (ScenarioAssessment(
        state=state, points_total=assessed, points_assessed=assessed,
        spot_values=tuple(p.spot for p in inp.scenario_points),
        min_pnl=min(pnls) if pnls else None,
        max_pnl=max(pnls) if pnls else None,
        unavailable_reasons=tuple(reasons), note=note,
        provenance=_shared_leg_provenance(inp)), note)


def _assess_regime(inp: StrategyEvaluationInput) -> tuple[RegimeAssessment, str]:
    regime: MarketRegime | None = inp.market_regime
    if regime is None:
        return (RegimeAssessment(
            state=DimensionState.UNAVAILABLE, compatibility=None,
            regime_label=None,
            note="no authoritative market regime supplied -- regime "
            "dimension unavailable (never inferred from labels)"),
            "no market regime supplied")
    strategy_dir = inp.strategy_direction
    regime_dir = inp.regime_direction
    strategy_dir = strategy_dir if strategy_dir in _DIRECTIONAL else None
    regime_dir = regime_dir if regime_dir in _DIRECTIONAL else None
    if strategy_dir is not None and regime_dir is not None:
        if strategy_dir is regime_dir:
            compat = RegimeCompatibility.COMPATIBLE
            note = (f"strategy direction {strategy_dir.value} compatible "
                    f"with regime {regime.label.value} direction "
                    f"{regime_dir.value}")
        else:
            compat = RegimeCompatibility.CONFLICTED
            note = (f"strategy direction {strategy_dir.value} conflicts "
                    f"with regime {regime.label.value} direction "
                    f"{regime_dir.value}")
    else:
        compat = RegimeCompatibility.NON_DIRECTIONAL
        missing = []
        if strategy_dir is None:
            missing.append("strategy direction")
        if regime_dir is None:
            missing.append("regime directional evidence")
        note = (f"regime label {regime.label.value} recorded without "
                f"directional evidence ({', '.join(missing)} missing) -- "
                "a regime label alone never fabricates direction")
    return (RegimeAssessment(
        state=DimensionState.AVAILABLE, compatibility=compat,
        regime_label=regime.label, note=note), note)


def _assess_liquidity(inp: StrategyEvaluationInput) -> tuple[LiquidityAssessment, str]:
    ev = inp.liquidity
    if ev is None:
        return (LiquidityAssessment(
            state=DimensionState.UNAVAILABLE, legs_complete=None,
            legs_total=None, spread_bps=None,
            note="no liquidity evidence supplied -- missing liquidity is "
            "never treated as zero", provenance=None),
            "no liquidity evidence supplied")
    return (LiquidityAssessment(
        state=ev.state, legs_complete=ev.legs_complete,
        legs_total=ev.legs_total, spread_bps=ev.spread_bps,
        note=(f"liquidity evidence supplied "
              f"({ev.legs_complete}/{ev.legs_total} legs complete)"),
        provenance=ev.provenance), "")


def _assess_risk(inp: StrategyEvaluationInput) -> tuple[RiskAssessment, str]:
    ev = inp.risk
    if ev is None:
        return (RiskAssessment(
            state=DimensionState.UNAVAILABLE, structural_unbounded_loss=None,
            max_loss_estimate=None, informational_only=True,
            note="no risk evidence supplied -- risk remains unevaluated "
            "(informational/evaluative only)", provenance=None),
            "no risk evidence supplied")
    note = "risk characteristics recorded (informational/evaluative only; no decision here)"
    if ev.notes:
        note += "; " + "; ".join(ev.notes)
    return (RiskAssessment(
        state=ev.state, structural_unbounded_loss=ev.structural_unbounded_loss,
        max_loss_estimate=ev.max_loss_estimate, informational_only=True,
        note=note, provenance=ev.provenance), note)


def _assess_historical(inp: StrategyEvaluationInput) -> tuple[HistoricalAssessment, str]:
    ev = inp.historical
    if ev is None:
        return (HistoricalAssessment(
            state=DimensionState.UNAVAILABLE, observations=None,
            metric_note=None,
            note="no point-in-time historical evidence supplied -- no "
            "historical score is fabricated", provenance=None),
            "no historical evidence supplied")
    return (HistoricalAssessment(
        state=ev.state, observations=ev.observations,
        metric_note=ev.metric_note,
        note=(f"historical evidence supplied ({ev.observations} point-in-time "
              "observations)"), provenance=ev.provenance), "")


def evaluate_strategy(inp: StrategyEvaluationInput) -> StrategyEvaluationResult:
    """Evaluate one strategy candidate deterministically (pure)."""
    if not isinstance(inp, StrategyEvaluationInput):
        raise ValueError("evaluate_strategy requires a StrategyEvaluationInput")

    payoff, payoff_note = _assess_payoff(inp)
    greeks, greeks_note = _assess_greeks(inp)
    scenario, scenario_note = _assess_scenarios(inp)
    regime, regime_note = _assess_regime(inp)
    liquidity, liquidity_note = _assess_liquidity(inp)
    risk, risk_note = _assess_risk(inp)
    historical, historical_note = _assess_historical(inp)

    assessments = {
        EvaluationDimension.PAYOFF: (payoff.state, payoff_note,
                                    payoff.provenance),
        EvaluationDimension.GREEKS: (greeks.state, greeks_note,
                                     greeks.provenance),
        EvaluationDimension.SCENARIO: (scenario.state, scenario_note,
                                       scenario.provenance),
        EvaluationDimension.REGIME: (regime.state, regime_note, None),
        EvaluationDimension.LIQUIDITY: (liquidity.state, liquidity_note,
                                        liquidity.provenance),
        EvaluationDimension.RISK: (risk.state, risk_note, risk.provenance),
        EvaluationDimension.HISTORICAL: (historical.state, historical_note,
                                         historical.provenance),
    }
    _sources = {
        EvaluationDimension.PAYOFF: "payoff-boundary",
        EvaluationDimension.GREEKS: "day18-evaluate_portfolio",
        EvaluationDimension.SCENARIO: "day18-scenario-grid",
        EvaluationDimension.REGIME: "market-regime-channel",
        EvaluationDimension.LIQUIDITY: "liquidity-boundary",
        EvaluationDimension.RISK: "risk-boundary",
        EvaluationDimension.HISTORICAL: "historical-boundary",
    }

    evidence = tuple(
        EvaluationEvidence(
            dimension=dim, state=assessments[dim][0],
            source=_sources[dim], note=assessments[dim][1],
            provenance=assessments[dim][2])
        for dim in _ALL_DIMENSIONS)
    issues = tuple(
        EvaluationIssue(dimension=dim, message=assessments[dim][1])
        for dim in _ALL_DIMENSIONS
        if assessments[dim][0] in (DimensionState.UNAVAILABLE,
                                   DimensionState.INVALID))

    states = [assessments[d][0] for d in _ALL_DIMENSIONS]
    if any(s is DimensionState.INVALID for s in states):
        status = StrategyEvaluationStatus.INVALID
    elif all(s is DimensionState.AVAILABLE for s in states):
        status = StrategyEvaluationStatus.SUCCESS
    elif all(s is DimensionState.UNAVAILABLE for s in states):
        status = StrategyEvaluationStatus.UNAVAILABLE
    else:
        status = StrategyEvaluationStatus.PARTIAL

    provenance = (inp.opportunity.provenance if inp.opportunity else None)
    return StrategyEvaluationResult(
        status=status,
        strategy_id=inp.strategy_id,
        evaluation_context=inp.evaluation_context,
        reference_timestamp=inp.reference_timestamp,
        legs=inp.legs,
        payoff_assessment=payoff,
        greek_assessment=greeks,
        scenario_assessment=scenario,
        regime_assessment=regime,
        liquidity_assessment=liquidity,
        risk_assessment=risk,
        historical_assessment=historical,
        evidence=evidence,
        issues=issues,
        confidence=inp.confidence,
        quality=inp.quality,
        opportunity_id=inp.opportunity_id,
        provenance=provenance,
        contract_version=inp.contract_version,
        model_version=inp.model_version,
        calculation_version=inp.calculation_version,
    )
