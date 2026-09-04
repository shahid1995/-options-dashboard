"""Day 33 — Deterministic Central Risk Engine.

``assess_candidate_risk(candidate, policy, *, reference_timestamp=None)``
is a pure domain orchestrator.  It consumes:

* an eligible Day-32 ``StrategyCandidate`` (whose embedded Day-31
  evaluation already carries authoritative payoff / Greek / scenario
  assessments produced by the Day-31 evaluator and the Day-18 engine);
* an explicit, versioned ``RiskPolicy``;
* a caller-supplied reference timestamp (never the wall clock).

Decision ladder (deterministic, evidence-backed)
------------------------------------------------
1. ``INVALID`` — candidate lifecycle is not ELIGIBLE, the strategy is
   structurally unsupported (empty/zero-quantity legs), or the Day-31
   evaluation is INVALID.
2. ``UNAVAILABLE`` — the Day-31 evaluation is UNAVAILABLE (risk cannot be
   meaningfully assessed from supplied inputs).
3. ``PARTIAL`` — the Day-31 evaluation is PARTIAL or a configured policy
   rule is not verifiable because required evidence is missing.
4. ``BLOCKED`` — every verifiable rule is checked; any verified violation
   blocks with the failing rule exposed in ``blocking_reasons``.
5. ``PASS`` — the Day-31 evaluation is SUCCESS, every applicable rule is
   verifiable, and all pass.

Rules implemented
-----------------
* ``MAX_STANDALONE_LOSS`` — bounded max-loss magnitude must not exceed the
  configured cap; an unbounded loss can never satisfy a finite cap
  (verified violation).  ``None`` cap = rule not configured.
* ``UNBOUNDED_LOSS`` — unbounded standalone loss is permitted only when
  the policy explicitly allows it.
* ``MAX_SCENARIO_LOSS`` — worst supplied scenario loss magnitude must not
  exceed the cap (authoritative Day-18 scenario minimum; never a
  theoretical worst case).
* ``MIN_QUALITY`` — candidate quality state must be at least the policy
  minimum (EXCELLENT > GOOD > DEGRADED > INSUFFICIENT).
* ``MAX_DATA_AGE`` — data age (reference minus quality observation time)
  must not exceed the configured window; missing timestamps make the rule
  not verifiable (never silently fresh).

Risk metrics, confidence, quality and the policy decision stay separate;
no aggregate risk score is produced anywhere.
"""

from __future__ import annotations

from datetime import datetime

from app.market_data.contracts import QualityState
from app.market_data.quality import QualityResult
from app.strategy_evaluation.contracts import (
    DimensionState,
    StrategyEvaluationResult,
    StrategyEvaluationStatus,
)
from app.strategy_lifecycle.contracts import StrategyCandidate, StrategyLifecycleState
from app.central_risk.contracts import (
    CENTRAL_RISK_CALCULATION_VERSION,
    CENTRAL_RISK_CONTRACT_VERSION,
    CentralRiskIssueCode,
    CentralRiskResult,
    CentralRiskStatus,
    GreekRisk,
    PayoffRisk,
    PolicyAssessment,
    PolicyRuleCode,
    PolicyRuleResult,
    RiskEvidence,
    RiskIssue,
    RiskPolicy,
    ScenarioRisk,
    StructuralRisk,
)

#: Quality ordering used by the MIN_QUALITY rule (higher = better).
_QUALITY_ORDER = {
    QualityState.EXCELLENT: 4,
    QualityState.GOOD: 3,
    QualityState.DEGRADED: 2,
    QualityState.INSUFFICIENT: 1,
}

_PAYOFF_SOURCE = "day31-payoff-assessment"
_GREEK_SOURCE = "day31-greek-assessment"
_SCENARIO_SOURCE = "day18-scenario-assessment"
_STRUCTURAL_SOURCE = "day32-candidate-structure"
_POLICY_SOURCE = "risk-policy"


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None \
        and ts.tzinfo.utcoffset(ts) is not None


def _rule(rule: PolicyRuleCode, passed: bool | None, message: str,
          limit: float | None = None, observed: float | None = None,
          limit_quality: QualityState | None = None,
          observed_quality: QualityState | None = None) -> PolicyRuleResult:
    return PolicyRuleResult(rule=rule, passed=passed, message=message,
                            limit=limit, observed=observed,
                            limit_quality=limit_quality,
                            observed_quality=observed_quality)


def _evidence(kind: str, source: str, note: str,
              provenance=None) -> RiskEvidence:
    return RiskEvidence(kind=kind, source=source, note=note,
                        provenance=provenance)


def assess_candidate_risk(
    candidate: StrategyCandidate,
    policy: RiskPolicy,
    *,
    reference_timestamp: datetime | None = None,
) -> CentralRiskResult:
    """Evaluate the standalone risk profile of one strategy candidate.

    ``candidate`` must be a Day-32 StrategyCandidate in the ELIGIBLE
    lifecycle state; ``policy`` must be an explicit RiskPolicy.  The
    reference timestamp is caller-supplied; when omitted the candidate's
    own (caller-supplied) reference timestamp is used.  The engine never
    reads the wall clock.
    """
    if not isinstance(candidate, StrategyCandidate):
        raise ValueError("assess_candidate_risk requires a StrategyCandidate")
    if not isinstance(policy, RiskPolicy):
        raise ValueError("assess_candidate_risk requires a RiskPolicy")
    resolved_reference = candidate.reference_timestamp \
        if reference_timestamp is None else reference_timestamp
    if not _is_aware(resolved_reference):
        raise ValueError("reference_timestamp must be genuinely timezone-aware")

    issues: list[RiskIssue] = []
    evidence: list[RiskEvidence] = []

    # -- structural validation (invariants Day-33 must re-check) -----------
    structural = _assess_structure(candidate)
    evidence.append(_evidence("STRUCTURAL", _STRUCTURAL_SOURCE,
                              structural.note, candidate.provenance))

    evaluation: StrategyEvaluationResult = candidate.evaluation

    # -- domain INVALID ladder ----------------------------------------------
    if candidate.lifecycle_state is not StrategyLifecycleState.ELIGIBLE:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.NOT_ELIGIBLE_CANDIDATE,
            message=f"candidate lifecycle is {candidate.lifecycle_state.value}; "
                    "only ELIGIBLE candidates enter the central risk boundary"))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.INVALID, (), issues, evidence,
                        resolved_reference)

    if structural.state is DimensionState.INVALID:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.STRUCTURAL_INVALID,
            message=structural.note))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.INVALID, (), issues, evidence,
                        resolved_reference)

    if evaluation.status is StrategyEvaluationStatus.INVALID:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.INVALID_EVALUATION,
            message="Day-31 Strategy Evaluation is INVALID"))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.INVALID, (), issues, evidence,
                        resolved_reference)

    if evaluation.status is StrategyEvaluationStatus.UNAVAILABLE:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.UNAVAILABLE_RISK_EVIDENCE,
            message="Day-31 evaluation is UNAVAILABLE; standalone risk "
                    "cannot be meaningfully assessed"))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.UNAVAILABLE, (), issues, evidence,
                        resolved_reference)

    # -- dimension risk views from the authoritative Day-31 assessments ----
    payoff_risk = _payoff_risk(evaluation)
    greek_risk = _greek_risk(evaluation)
    scenario_risk = _scenario_risk(evaluation)
    evidence.extend([
        _evidence("PAYOFF", _PAYOFF_SOURCE, payoff_risk.note,
                  payoff_risk.provenance),
        _evidence("GREEKS", _GREEK_SOURCE, greek_risk.note,
                  greek_risk.provenance),
        _evidence("SCENARIO", _SCENARIO_SOURCE, scenario_risk.note,
                  scenario_risk.provenance),
    ])

    # PARTIAL evaluation -> incomplete evidence -> PARTIAL (never PASS).
    if evaluation.status is StrategyEvaluationStatus.PARTIAL:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.INCOMPLETE_RISK_EVIDENCE,
            message="Day-31 evaluation is PARTIAL; required evidence is "
                    "incomplete"))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.PARTIAL, (), issues, evidence,
                        resolved_reference, payoff_risk=payoff_risk,
                        greek_risk=greek_risk, scenario_risk=scenario_risk)

    # -- policy rules -------------------------------------------------------
    rules, rule_evidence, rule_issues = _evaluate_policy(
        policy, payoff_risk, scenario_risk, candidate.quality,
        resolved_reference)
    evidence.extend(rule_evidence)
    issues.extend(rule_issues)

    failed = tuple(r for r in rules if r.passed is False)
    unverifiable = any(r.passed is None for r in rules)
    if failed:
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.BLOCKED, failed, issues, evidence,
                        resolved_reference, payoff_risk=payoff_risk,
                        greek_risk=greek_risk, scenario_risk=scenario_risk,
                        rules=rules)
    if unverifiable:
        issues.append(RiskIssue(
            code=CentralRiskIssueCode.INCOMPLETE_RISK_EVIDENCE,
            message="a configured policy rule is not verifiable from the "
                    "supplied evidence"))
        return _compose(candidate, policy, evaluation, structural,
                        CentralRiskStatus.PARTIAL, (), issues, evidence,
                        resolved_reference, payoff_risk=payoff_risk,
                        greek_risk=greek_risk, scenario_risk=scenario_risk,
                        rules=rules)
    return _compose(candidate, policy, evaluation, structural,
                    CentralRiskStatus.PASS, (), issues, evidence,
                    resolved_reference, payoff_risk=payoff_risk,
                    greek_risk=greek_risk, scenario_risk=scenario_risk,
                    rules=rules)


# ---------------------------------------------------------------------------
# Dimension assessment builders
# ---------------------------------------------------------------------------


def _assess_structure(candidate: StrategyCandidate) -> StructuralRisk:
    legs = candidate.legs
    if not legs:
        return StructuralRisk(
            state=DimensionState.INVALID,
            note="strategy carries no legs; unsupported structure",
            provenance=candidate.provenance)
    zero = [leg for leg in legs if leg.quantity <= 0]
    if zero:
        return StructuralRisk(
            state=DimensionState.INVALID,
            note="strategy contains a leg with non-positive quantity; "
                 "unsupported structure",
            provenance=candidate.provenance)
    return StructuralRisk(
        state=DimensionState.AVAILABLE,
        note=f"strategy structure supported ({len(legs)} leg(s), every "
             "quantity positive)",
        provenance=candidate.provenance)


def _payoff_risk(evaluation: StrategyEvaluationResult) -> PayoffRisk:
    p = evaluation.payoff_assessment
    loss_unbounded = p.tail is not None and "UNLIMITED_LOSS" in p.tail.value
    return PayoffRisk(
        state=p.state,
        max_profit=p.max_profit,
        max_loss=p.max_loss,
        loss_unbounded=loss_unbounded,
        breakevens=p.breakevens,
        note=p.note or f"payoff risk state {p.state.value}",
        provenance=p.provenance,
    )


def _greek_risk(evaluation: StrategyEvaluationResult) -> GreekRisk:
    g = evaluation.greek_assessment
    return GreekRisk(
        state=g.state,
        delta=g.delta,
        gamma=g.gamma,
        theta=g.theta,
        vega=g.vega,
        legs_priced=g.legs_priced,
        legs_total=g.legs_total,
        greeks_source=g.greeks_source,
        note=g.note or f"greek risk state {g.state.value}",
        provenance=g.provenance,
    )


def _scenario_risk(evaluation: StrategyEvaluationResult) -> ScenarioRisk:
    s = evaluation.scenario_assessment
    return ScenarioRisk(
        state=s.state,
        points_total=s.points_total,
        points_assessed=s.points_assessed,
        min_pnl=s.min_pnl,
        max_pnl=s.max_pnl,
        note=s.note or f"scenario risk state {s.state.value} "
                       "(worst supplied scenario P/L, not theoretical)",
        provenance=s.provenance,
    )


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


def _bounded_loss_magnitude(max_loss: float | None) -> float | None:
    """Measured loss magnitude for a BOUNDED payoff.

    A negative max loss yields its magnitude; a non-negative max loss
    means no loss at the worst point (magnitude 0); missing stays missing.
    """
    if max_loss is None:
        return None
    return -max_loss if max_loss < 0 else 0.0


def _evaluate_policy(
    policy: RiskPolicy,
    payoff_risk: PayoffRisk,
    scenario_risk: ScenarioRisk,
    quality: QualityResult | None,
    reference: datetime,
) -> tuple[tuple[PolicyRuleResult, ...], list[RiskEvidence], list[RiskIssue]]:
    rules: list[PolicyRuleResult] = []
    issues: list[RiskIssue] = []

    # 1. UNBOUNDED_LOSS + MAX_STANDALONE_LOSS ------------------------------
    payoff_usable = payoff_risk.state in (DimensionState.AVAILABLE,
                                          DimensionState.PARTIAL)
    if payoff_usable and payoff_risk.loss_unbounded:
        if policy.allow_unbounded_loss is False:
            rules.append(_rule(
                PolicyRuleCode.UNBOUNDED_LOSS, False,
                "strategy has unbounded standalone loss and the policy does "
                "not permit unbounded loss"))
        else:
            rules.append(_rule(
                PolicyRuleCode.UNBOUNDED_LOSS, True,
                "strategy has unbounded standalone loss and the policy "
                "explicitly permits unbounded loss"))
        if policy.maximum_standalone_loss is not None:
            rules.append(_rule(
                PolicyRuleCode.MAX_STANDALONE_LOSS, False,
                "strategy loss is unbounded; it can never satisfy the "
                "configured maximum standalone loss cap",
                limit=policy.maximum_standalone_loss))
    elif payoff_usable:
        rules.append(_rule(
            PolicyRuleCode.UNBOUNDED_LOSS, True,
            "strategy standalone loss is bounded"))
        if policy.maximum_standalone_loss is not None:
            magnitude = _bounded_loss_magnitude(payoff_risk.max_loss)
            if magnitude is None:
                rules.append(_rule(
                    PolicyRuleCode.MAX_STANDALONE_LOSS, None,
                    "maximum standalone loss is not verifiable: no finite "
                    "bounded max-loss magnitude was supplied",
                    limit=policy.maximum_standalone_loss))
            else:
                rules.append(_rule(
                    PolicyRuleCode.MAX_STANDALONE_LOSS,
                    magnitude <= policy.maximum_standalone_loss,
                    f"maximum standalone loss magnitude {magnitude} vs cap "
                    f"{policy.maximum_standalone_loss}",
                    limit=policy.maximum_standalone_loss,
                    observed=magnitude))
    else:
        if policy.maximum_standalone_loss is not None:
            rules.append(_rule(
                PolicyRuleCode.MAX_STANDALONE_LOSS, None,
                f"payoff risk state is {payoff_risk.state.value}; standalone "
                "loss rule cannot be verified",
                limit=policy.maximum_standalone_loss))
        rules.append(_rule(
            PolicyRuleCode.UNBOUNDED_LOSS, None,
            f"payoff risk state is {payoff_risk.state.value}; unbounded-loss "
            "classification cannot be verified"))

    # 2. MAX_SCENARIO_LOSS ---------------------------------------------------
    if policy.maximum_scenario_loss is not None:
        if scenario_risk.state is DimensionState.AVAILABLE \
                and scenario_risk.min_pnl is not None:
            magnitude = -scenario_risk.min_pnl \
                if scenario_risk.min_pnl < 0 else 0.0
            rules.append(_rule(
                PolicyRuleCode.MAX_SCENARIO_LOSS,
                magnitude <= policy.maximum_scenario_loss,
                f"worst supplied scenario loss magnitude {magnitude} vs cap "
                f"{policy.maximum_scenario_loss}",
                limit=policy.maximum_scenario_loss, observed=magnitude))
        else:
            rules.append(_rule(
                PolicyRuleCode.MAX_SCENARIO_LOSS, None,
                f"scenario risk state is {scenario_risk.state.value} with no "
                "assessable worst-supplied-scenario P/L; scenario-loss rule "
                "cannot be verified",
                limit=policy.maximum_scenario_loss))

    # 3. MIN_QUALITY ----------------------------------------------------------
    if policy.minimum_quality is not None:
        if quality is None:
            rules.append(_rule(
                PolicyRuleCode.MIN_QUALITY, None,
                "candidate carries no quality; minimum-quality rule cannot "
                "be verified",
                limit_quality=policy.minimum_quality))
        elif _QUALITY_ORDER[quality.quality_state] < \
                _QUALITY_ORDER[policy.minimum_quality]:
            rules.append(_rule(
                PolicyRuleCode.MIN_QUALITY, False,
                f"candidate quality {quality.quality_state.value} is below "
                f"the policy minimum {policy.minimum_quality.value}",
                limit_quality=policy.minimum_quality,
                observed_quality=quality.quality_state))
        else:
            rules.append(_rule(
                PolicyRuleCode.MIN_QUALITY, True,
                f"candidate quality {quality.quality_state.value} meets the "
                f"policy minimum {policy.minimum_quality.value}",
                limit_quality=policy.minimum_quality,
                observed_quality=quality.quality_state))

    # 4. MAX_DATA_AGE ----------------------------------------------------------
    if policy.maximum_data_age_seconds is not None:
        if quality is None:
            rules.append(_rule(
                PolicyRuleCode.MAX_DATA_AGE, None,
                "candidate carries no quality; data-age rule cannot be "
                "verified",
                limit=policy.maximum_data_age_seconds))
        else:
            observed_at = quality.observation_time or quality.evaluated_at
            if observed_at is None:
                rules.append(_rule(
                    PolicyRuleCode.MAX_DATA_AGE, None,
                    "candidate quality carries no observation timestamp; "
                    "data-age rule cannot be verified",
                    limit=policy.maximum_data_age_seconds))
            else:
                age = (reference - observed_at).total_seconds()
                if age < 0:
                    # A future-dated observation cannot establish freshness
                    # (design §11: future inputs are never silently treated
                    # as usable); the rule is not verifiable.
                    rules.append(_rule(
                        PolicyRuleCode.MAX_DATA_AGE, None,
                        f"quality observation time {observed_at.isoformat()} "
                        "is in the future relative to the reference "
                        "timestamp; data-age rule cannot be verified",
                        limit=policy.maximum_data_age_seconds))
                else:
                    rules.append(_rule(
                        PolicyRuleCode.MAX_DATA_AGE,
                        age <= policy.maximum_data_age_seconds,
                        f"data age {age:.0f}s vs policy maximum "
                        f"{policy.maximum_data_age_seconds:.0f}s",
                        limit=policy.maximum_data_age_seconds, observed=age))

    evidence = [
        _evidence("POLICY", _POLICY_SOURCE, f"{r.rule.value}: {r.message}")
        for r in rules
    ]
    return tuple(rules), evidence, issues


# ---------------------------------------------------------------------------
# Result composition
# ---------------------------------------------------------------------------


def _compose(candidate: StrategyCandidate, policy: RiskPolicy,
             evaluation: StrategyEvaluationResult,
             structural: StructuralRisk, status: CentralRiskStatus,
             blocking: tuple[PolicyRuleResult, ...], issues: list[RiskIssue],
             evidence: list[RiskEvidence], reference: datetime,
             payoff_risk: PayoffRisk | None = None,
             greek_risk: GreekRisk | None = None,
             scenario_risk: ScenarioRisk | None = None,
             rules: tuple[PolicyRuleResult, ...] | None = None) -> CentralRiskResult:
    payoff = payoff_risk if payoff_risk is not None else PayoffRisk(
        state=DimensionState.UNAVAILABLE, max_profit=None, max_loss=None,
        loss_unbounded=False, breakevens=(), note="not assessed",
        provenance=None)
    greek = greek_risk if greek_risk is not None else GreekRisk(
        state=DimensionState.UNAVAILABLE, delta=None, gamma=None, theta=None,
        vega=None, legs_priced=0, legs_total=0, greeks_source=None,
        note="not assessed", provenance=None)
    scenario = scenario_risk if scenario_risk is not None else ScenarioRisk(
        state=DimensionState.UNAVAILABLE, points_total=0, points_assessed=0,
        min_pnl=None, max_pnl=None, note="not assessed", provenance=None)
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
            policy_version=policy.policy_version,
            rules=rules if rules is not None else ()),
        blocking_reasons=blocking,
        evidence=tuple(evidence),
        issues=tuple(issues),
        confidence=evaluation.confidence,
        quality=evaluation.quality,
        provenance=candidate.provenance,
        reference_timestamp=reference,
        contract_version=CENTRAL_RISK_CONTRACT_VERSION,
        model_version=evaluation.model_version,
        calculation_version=CENTRAL_RISK_CALCULATION_VERSION,
    )
