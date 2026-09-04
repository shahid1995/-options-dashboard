"""Day 36 — Deterministic Final Risk Gate engine.

``evaluate_final_risk_gate(gate_input: FinalRiskGateInput, *,
reference_timestamp=None)`` is a pure domain orchestrator.  It consumes
(through the immutable ``FinalRiskGateInput`` bundle):

* an eligible Day-32 ``StrategyCandidate``;
* the authoritative Day-33 ``CentralRiskResult`` (its verdict is consumed
  WHOLE -- Day-33 semantics are never re-derived here);
* a Day-35 ``PortfolioAnalyticsResult`` (genuine portfolio analytics;
  ``None`` means the required portfolio input is absent -> UNAVAILABLE);
* an explicit, versioned ``FinalRiskPolicy``;
* a caller-supplied reference timestamp (never the wall clock);
* the caller's tenant/account context.

A thin compatibility helper ``evaluate_final_gate(candidate, central_risk,
portfolio, *, policy, reference_timestamp=None, tenant_id=None)`` wraps the
positional call into a ``FinalRiskGateInput`` for callers that predate the
input bundle.

Decision ladder (deterministic, evidence-backed)
------------------------------------------------
1. ``INVALID`` -- structural invariant failure (non-eligible lifecycle,
   empty/zero-quantity legs), candidate/central-risk identity mismatch,
   tenant mismatch, Day-33 INVALID, or Day-35 portfolio INVALID.
2. ``BLOCKED`` -- Day-33 BLOCKED (verified standalone violation) or any
   CONFIGURED final-gate rule verified as violated.
3. ``UNAVAILABLE`` -- Day-33 UNAVAILABLE or the portfolio input is absent.
4. ``PARTIAL`` -- Day-33 PARTIAL, or a CONFIGURED rule is not verifiable
   because required evidence is missing -- never a false PASS.
5. ``PASS`` -- structure valid, Day-33 PASS, portfolio supplied, every
   CONFIGURED rule verifiable and passing.  PASS means ONLY "permitted to
   proceed to the User Decision boundary".

Rules implemented
-----------------
* ``CENTRAL_RISK_PASS`` -- always evaluated: True only when Day-33 PASS.
* ``CANDIDATE_QUALITY`` -- always evaluated: True when the candidate
  carries quality evidence; None (unverifiable) when quality is missing --
  missing quality can never be manufactured into a PASS.
* ``MAX_PORTFOLIO_DELTA`` -- cap on the worst per-source current portfolio
  net-delta magnitude (source separated); not verifiable when no source
  supplies a delta.
* ``MAX_PROJECTED_DELTA`` -- cap on the worst same-source projected delta
  magnitude (authoritative Day-35 current delta + authoritative Day-33
  candidate delta); formed ONLY when candidate and portfolio share one
  Greek source -- broker/model evidence is never summed.  Not verifiable
  when no source shares both sides.
* ``MAX_CONCENTRATION_SHARE`` -- cap on the largest concentration slice
  share of the current portfolio; not verifiable for an empty portfolio.
* ``MAX_PORTFOLIO_AGE`` -- cap on the age of the supplied Day-35 portfolio
  analytics measured against the caller-supplied reference timestamp;
  future-dated analytics are not verifiable (never silently fresh).
* ``REGIME_ALLOWLIST`` -- explicit policy over the authoritative Day-23
  regime label: a known label on the configured disallowed list blocks;
  a label never manufactures direction -- an unknown regime makes the rule
  unverifiable (never guessed).

No numeric limit is ever invented: a ``None``/empty policy field means that
rule is not configured and cannot block or manufacture a PASS requirement.
Dimension sub-statuses are informational evidence states; only configured
rules and the upstream Day-33/portfolio verdicts move the overall ladder.
"""

from __future__ import annotations

from datetime import datetime

from app.central_risk.contracts import (
    CentralRiskResult,
    CentralRiskStatus,
)
from app.intelligence.contracts import RegimeLabel
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
    GateEvidence,
    GateIssue,
    GateRuleResult,
    GreekDeltaRead,
    PolicyGateAssessment,
    PortfolioImpact,
)
from app.portfolio_intelligence.contracts import PortfolioAnalyticsResult
from app.strategy_lifecycle.contracts import StrategyCandidate, StrategyLifecycleState

_PASS = FinalRiskStatus.PASS
_BLOCKED = FinalRiskStatus.BLOCKED
_PARTIAL = FinalRiskStatus.PARTIAL
_UNAVAILABLE = FinalRiskStatus.UNAVAILABLE
_INVALID = FinalRiskStatus.INVALID


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None \
        and ts.tzinfo.utcoffset(ts) is not None


def _evidence(kind: str, source: str, note: str,
              provenance=None) -> GateEvidence:
    return GateEvidence(kind=kind, source=source, note=note,
                        provenance=provenance)


def _issue(code: FinalRiskIssueCode, message: str) -> GateIssue:
    return GateIssue(code=code, message=message)


def _dim(dimension: FinalRiskGateDimension, status: FinalRiskStatus,
         note: str) -> GateDimensionAssessment:
    return GateDimensionAssessment(dimension=dimension, status=status,
                                   note=note)


def _rule(rule: FinalRiskRuleCode, passed: bool | None, message: str,
          limit: float | None = None,
          observed: float | None = None) -> GateRuleResult:
    return GateRuleResult(rule=rule, passed=passed, message=message,
                          limit=limit, observed=observed)


def evaluate_final_risk_gate(
    gate_input: FinalRiskGateInput,
    *,
    reference_timestamp: datetime | None = None,
) -> FinalRiskGateResult:
    """Evaluate the final risk gate for one strategy candidate.

    ``gate_input`` binds the eligible Day-32 ``StrategyCandidate`` that
    produced the Day-33 ``CentralRiskResult``, the genuine Day-35 portfolio
    analytics of the account the candidate would be added to (``None`` is a
    deterministic UNAVAILABLE, never a pass), the explicit ``FinalRiskPolicy``
    and the caller's tenant context.  The reference timestamp is
    caller-supplied; when omitted the Day-33 result's own reference
    timestamp is used.  The engine never reads the wall clock and never
    touches a broker, database, network or filesystem.
    """
    if not isinstance(gate_input, FinalRiskGateInput):
        raise ValueError(
            "evaluate_final_risk_gate requires a FinalRiskGateInput")
    candidate = gate_input.candidate
    central_risk = gate_input.central_risk
    portfolio = gate_input.portfolio
    policy = gate_input.policy
    tenant_id = gate_input.tenant_id

    resolved_reference = (reference_timestamp
                          if reference_timestamp is not None
                          else central_risk.reference_timestamp)
    if not _is_aware(resolved_reference):
        raise ValueError("reference_timestamp must be genuinely timezone-aware")

    issues: list[GateIssue] = []
    evidence: list[GateEvidence] = []

    # -- structural gate (A) -------------------------------------------------
    structural_ok, structural_note, structural_issues = _assess_structure(
        candidate)
    issues.extend(structural_issues)
    evidence.append(_evidence("STRUCTURAL", "day32-candidate",
                              structural_note, candidate.provenance))
    if not structural_ok:
        return _compose(candidate, central_risk, policy, _INVALID, (),
                        issues, evidence, resolved_reference,
                        central_dim=_INVALID,
                        structure_note=structural_note)

    # -- identity coherence (the Day-33 result must describe THIS candidate)
    if central_risk.candidate_id != candidate.candidate_id \
            or central_risk.strategy_id != candidate.strategy_id \
            or central_risk.opportunity_id != candidate.opportunity_id:
        issues.append(_issue(
            FinalRiskIssueCode.IDENTITY_MISMATCH,
            "the Day-33 result does not describe this candidate "
            "(candidate/strategy/opportunity identity mismatch)"))
        return _compose(candidate, central_risk, policy, _INVALID, (),
                        issues, evidence, resolved_reference,
                        central_dim=_INVALID,
                        structure_note=structural_note)

    # -- central risk gate (B): consume Day-33 whole ------------------------
    if central_risk.status is CentralRiskStatus.INVALID:
        issues.append(_issue(FinalRiskIssueCode.DAY33_INCOMPLETE,
                             "Day-33 central risk is INVALID"))
        return _compose(candidate, central_risk, policy,
                        _INVALID, (), issues, evidence, resolved_reference,
                        central_dim=_INVALID, structure_note=structural_note)
    if central_risk.status is CentralRiskStatus.UNAVAILABLE:
        issues.append(_issue(FinalRiskIssueCode.DAY33_UNAVAILABLE,
                             "Day-33 central risk is UNAVAILABLE; the final "
                             "gate cannot assess the candidate"))
        return _compose(candidate, central_risk, policy,
                        _UNAVAILABLE, (), issues, evidence,
                        resolved_reference, central_dim=_UNAVAILABLE,
                        structure_note=structural_note)
    if central_risk.status is CentralRiskStatus.PARTIAL:
        issues.append(_issue(FinalRiskIssueCode.DAY33_INCOMPLETE,
                             "Day-33 central risk is PARTIAL; incomplete "
                             "evidence is never treated as safe"))
        return _compose(candidate, central_risk, policy,
                        _PARTIAL, (), issues, evidence, resolved_reference,
                        central_dim=_PARTIAL, structure_note=structural_note)
    if central_risk.status is CentralRiskStatus.BLOCKED:
        source = central_risk.blocking_reasons[0] \
            if central_risk.blocking_reasons else None
        blocking = (_rule(FinalRiskRuleCode.CENTRAL_RISK_PASS, False,
                          "Day-33 central risk BLOCKED"
                          + (f": {source.message}" if source is not None
                             else ""),
                          limit=source.limit if source is not None else None,
                          observed=source.observed
                          if source is not None else None),)
        evidence.append(_evidence("DAY33", "central-risk-result",
                                  blocking[0].message,
                                  central_risk.provenance))
        return _compose(candidate, central_risk, policy, _BLOCKED, blocking,
                        issues, evidence, resolved_reference,
                        central_dim=_BLOCKED, structure_note=structural_note)

    # -- portfolio required (Day-36 sits AFTER Day-35 in the chain) ---------
    if portfolio is None:
        issues.append(_issue(FinalRiskIssueCode.PORTFOLIO_REQUIRED,
                             "portfolio analytics are required for the final "
                             "gate; missing portfolio evidence is never "
                             "treated as safe"))
        return _compose(candidate, central_risk, policy, _UNAVAILABLE, (),
                        issues, evidence, resolved_reference,
                        central_dim=_PASS, structure_note=structural_note)

    if portfolio.status.value == "INVALID":
        issues.append(_issue(FinalRiskIssueCode.INCOMPLETE_PORTFOLIO_EVIDENCE,
                             "Day-35 portfolio analytics are INVALID"))
        return _compose(candidate, central_risk, policy, _INVALID, (),
                        issues, evidence, resolved_reference,
                        central_dim=_PASS, structure_note=structural_note,
                        portfolio_present=True)

    # -- tenant isolation ----------------------------------------------------
    position_tenants = {p.tenant_id for p in portfolio.positions}
    if position_tenants:
        resolved_tenant = tenant_id if tenant_id is not None \
            else next(iter(position_tenants))
        if position_tenants != {resolved_tenant}:
            issues.append(_issue(FinalRiskIssueCode.TENANT_MISMATCH,
                                 "the gate tenant does not match the "
                                 "portfolio positions' tenant; cross-tenant "
                                 "assessment is never performed"))
            return _compose(candidate, central_risk, policy, _INVALID, (),
                            issues, evidence, resolved_reference,
                            central_dim=_PASS, structure_note=structural_note,
                            portfolio_present=True,
                            tenant=resolved_tenant)
    else:
        resolved_tenant = tenant_id

    # -- Day-33 PASS; evaluate the configured final-gate rules --------------
    evidence.append(_evidence("DAY33", "central-risk-result",
                              "Day-33 central risk PASS",
                              central_risk.provenance))

    context = _portfolio_impact(candidate, central_risk, portfolio)
    evidence.extend(_impact_evidence(context))

    rules: list[GateRuleResult] = []
    rules.append(_rule(FinalRiskRuleCode.CENTRAL_RISK_PASS, True,
                       "Day-33 central risk PASS"))

    # CANDIDATE_QUALITY (always evaluated; required evidence completeness) --
    # missing candidate quality can never be manufactured into a PASS.
    if candidate.quality is not None:
        rules.append(_rule(
            FinalRiskRuleCode.CANDIDATE_QUALITY, True,
            f"candidate quality {candidate.quality.quality_state.value} "
            "present"))
    else:
        rules.append(_rule(
            FinalRiskRuleCode.CANDIDATE_QUALITY, None,
            "candidate carries no quality evidence; the final gate cannot "
            "verify quality completeness (missing is never treated as safe)"))
        issues.append(_issue(FinalRiskIssueCode.MISSING_CANDIDATE_QUALITY,
                             "candidate carries no quality evidence"))

    # MAX_PORTFOLIO_AGE (portfolio-analytics freshness vs the caller's
    # reference timestamp; caller-supplied only -- never wall clock) --------
    if policy.maximum_portfolio_age_seconds is not None:
        age = (resolved_reference - portfolio.reference_timestamp).total_seconds()
        if age < 0:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PORTFOLIO_AGE, None,
                "portfolio analytics are dated in the future relative to the "
                "reference timestamp; the freshness rule cannot be verified",
                limit=policy.maximum_portfolio_age_seconds))
        else:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PORTFOLIO_AGE,
                age <= policy.maximum_portfolio_age_seconds,
                f"portfolio analytics age {age:.0f}s vs policy maximum "
                f"{policy.maximum_portfolio_age_seconds:.0f}s",
                limit=policy.maximum_portfolio_age_seconds, observed=age))

    # REGIME_ALLOWLIST (explicit policy over the authoritative Day-23 label;
    # a label never manufactures direction -- it only matches the configured
    # disallow list; an unknown regime makes the rule unverifiable) ---------
    if policy.disallowed_regimes:
        current_label = RegimeLabel(context.regime_label) \
            if context.regime_label is not None else None
        if current_label is None:
            rules.append(_rule(
                FinalRiskRuleCode.REGIME_ALLOWLIST, None,
                "regime is unknown; the regime allow-list rule cannot be "
                "verified (nothing is guessed from a missing label)"))
        elif current_label in policy.disallowed_regimes:
            rules.append(_rule(
                FinalRiskRuleCode.REGIME_ALLOWLIST, False,
                f"current regime {current_label.value} is on the configured "
                "disallowed list"))
        else:
            rules.append(_rule(
                FinalRiskRuleCode.REGIME_ALLOWLIST, True,
                f"current regime {current_label.value} is not on the "
                "configured disallowed list"))

    # MAX_PORTFOLIO_DELTA ---------------------------------------------------
    if policy.maximum_portfolio_delta is not None:
        current = [r.current_delta for r in context.delta_reads
                   if r.current_delta is not None]
        if not current:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PORTFOLIO_DELTA, None,
                "no portfolio delta evidence; the portfolio-delta rule "
                "cannot be verified",
                limit=policy.maximum_portfolio_delta))
        else:
            worst = max(abs(v) for v in current)
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PORTFOLIO_DELTA,
                worst <= policy.maximum_portfolio_delta,
                f"worst per-source portfolio delta magnitude {worst} vs cap "
                f"{policy.maximum_portfolio_delta}",
                limit=policy.maximum_portfolio_delta, observed=worst))

    # MAX_PROJECTED_DELTA ---------------------------------------------------
    if policy.maximum_projected_delta is not None:
        projected = [r.projected_delta for r in context.delta_reads
                     if r.projected_delta is not None]
        if not projected:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PROJECTED_DELTA, None,
                "no same-source projected delta could be formed (the "
                "candidate and portfolio must share one Greek source); "
                "mixed/missing source evidence is never summed",
                limit=policy.maximum_projected_delta))
        else:
            worst = max(abs(v) for v in projected)
            rules.append(_rule(
                FinalRiskRuleCode.MAX_PROJECTED_DELTA,
                worst <= policy.maximum_projected_delta,
                f"worst same-source projected delta magnitude {worst} vs "
                f"cap {policy.maximum_projected_delta}",
                limit=policy.maximum_projected_delta, observed=worst))

    # MAX_CONCENTRATION_SHARE ------------------------------------------------
    concentration_observed = _largest_concentration_share(portfolio)
    if policy.maximum_concentration_share is not None:
        if concentration_observed is None:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_CONCENTRATION_SHARE, None,
                "no concentration slices are measurable (empty portfolio); "
                "the concentration rule cannot be verified",
                limit=policy.maximum_concentration_share))
        else:
            rules.append(_rule(
                FinalRiskRuleCode.MAX_CONCENTRATION_SHARE,
                concentration_observed <= policy.maximum_concentration_share,
                f"largest concentration share {concentration_observed} vs "
                f"cap {policy.maximum_concentration_share}",
                limit=policy.maximum_concentration_share,
                observed=concentration_observed))

    failed = tuple(r for r in rules if r.passed is False)
    if failed:
        return _compose(candidate, central_risk, policy, _BLOCKED, failed,
                        issues, evidence, resolved_reference,
                        central_dim=_PASS, structure_note=structural_note,
                        portfolio_present=True, tenant=resolved_tenant,
                        context=context, rules=rules)

    unverifiable = any(r.passed is None for r in rules
                       if r.rule is not FinalRiskRuleCode.CENTRAL_RISK_PASS)
    if unverifiable:
        issues.append(_issue(FinalRiskIssueCode.UNVERIFIABLE_RULE,
                             "a configured final-gate rule is not verifiable "
                             "from the supplied evidence"))
        return _compose(candidate, central_risk, policy, _PARTIAL, (),
                        issues, evidence, resolved_reference,
                        central_dim=_PASS, structure_note=structural_note,
                        portfolio_present=True, tenant=resolved_tenant,
                        context=context, rules=rules)

    return _compose(candidate, central_risk, policy, _PASS, (), issues,
                    evidence, resolved_reference, central_dim=_PASS,
                    structure_note=structural_note,
                    portfolio_present=True, tenant=resolved_tenant,
                    context=context, rules=rules)


# ---------------------------------------------------------------------------
# Dimension and context builders
# ---------------------------------------------------------------------------


def _assess_structure(candidate: StrategyCandidate
                      ) -> tuple[bool, str, list[GateIssue]]:
    """Structural gate (A): candidate must be a supported eligible strategy.

    Mirrors the Day-33 structural checks (non-empty legs, every leg with a
    positive quantity, ELIGIBLE lifecycle, genuine evaluation).
    """
    issues: list[GateIssue] = []
    legs = candidate.legs
    if candidate.lifecycle_state is not StrategyLifecycleState.ELIGIBLE:
        issues.append(_issue(
            FinalRiskIssueCode.STRUCTURAL_INVALID,
            f"candidate lifecycle is {candidate.lifecycle_state.value}; only "
            "ELIGIBLE candidates enter the final gate"))
        return False, "candidate not ELIGIBLE", issues
    if not legs:
        issues.append(_issue(
            FinalRiskIssueCode.STRUCTURAL_INVALID,
            "strategy carries no legs; unsupported structure"))
        return False, "strategy carries no legs", issues
    if any(leg.quantity <= 0 for leg in legs):
        issues.append(_issue(
            FinalRiskIssueCode.STRUCTURAL_INVALID,
            "strategy contains a leg with non-positive quantity"))
        return False, "leg with non-positive quantity", issues
    return True, f"structure supported ({len(legs)} leg(s), every quantity " \
                 "positive)", issues


def _portfolio_impact(candidate: StrategyCandidate,
                      central_risk: CentralRiskResult,
                      portfolio: PortfolioAnalyticsResult) -> PortfolioImpact:
    """Source-separated portfolio-impact context (C).

    Reads authoritative Day-35 per-source portfolio deltas and the
    authoritative Day-33 candidate delta; a projected delta is formed ONLY
    on a shared single source.  No other arithmetic is performed.
    """
    candidate_source = central_risk.greek_risk.greeks_source
    candidate_delta = central_risk.greek_risk.delta

    portfolio_by_source = {
        entry.source: entry.delta_total
        for entry in portfolio.greeks.by_source
    }
    sources = sorted({s for s in portfolio_by_source}
                     | ({candidate_source} if candidate_source else set()))
    reads: list[GreekDeltaRead] = []
    for source in sources:
        current = portfolio_by_source.get(source)
        cand = candidate_delta if candidate_source == source else None
        projected = None
        if current is not None and cand is not None:
            projected = round(current + cand, 10)
        reads.append(GreekDeltaRead(source=source, current_delta=current,
                                    candidate_delta=cand,
                                    projected_delta=projected))

    regime_label = portfolio.regime_risk.regime_label
    scenario_state = portfolio.scenarios.state.value
    notes: list[str] = []
    if not portfolio.positions:
        notes.append("current portfolio is empty (measured zero exposure)")
    if candidate_source is None:
        notes.append("candidate carries no Greek source; no projected delta "
                     "is formed")
    elif candidate_source not in portfolio_by_source:
        notes.append("candidate Greek source is not present in the current "
                     "portfolio; no same-source projection exists")

    return PortfolioImpact(
        position_count=portfolio.exposure.position_count,
        delta_reads=tuple(reads),
        day33_worst_scenario_pnl=central_risk.scenario_risk.min_pnl,
        portfolio_scenario_state=scenario_state,
        regime_label=regime_label.value if regime_label is not None else None,
        notes=tuple(notes),
    )


def _impact_evidence(context: PortfolioImpact) -> list[GateEvidence]:
    rows: list[GateEvidence] = []
    rows.append(_evidence("PORTFOLIO", "day35-portfolio-analytics",
                          f"portfolio position count "
                          f"{context.position_count}"))
    for read in context.delta_reads:
        if read.projected_delta is not None:
            note = (f"{read.source} delta: current {read.current_delta}, "
                    f"candidate {read.candidate_delta}, projected "
                    f"{read.projected_delta} (same-source)")
        else:
            note = (f"{read.source} delta read: current "
                    f"{read.current_delta}, candidate "
                    f"{read.candidate_delta}, no same-source projection")
        rows.append(_evidence("GREEKS", f"day35-source-{read.source}", note))
    if context.day33_worst_scenario_pnl is not None:
        rows.append(_evidence(
            "SCENARIO", "day33-scenario-risk",
            f"worst supplied candidate scenario P/L "
            f"{context.day33_worst_scenario_pnl}"))
    else:
        rows.append(_evidence(
            "SCENARIO", "day33-scenario-risk",
            "candidate scenario risk carries no worst-supplied P/L "
            "(missing never becomes zero)"))
    if context.regime_label is not None:
        rows.append(_evidence("REGIME", "day35-regime-view",
                              f"known regime {context.regime_label}"))
    else:
        rows.append(_evidence("REGIME", "day35-regime-view",
                              "regime unknown; no regime condition is "
                              "evaluated and nothing is guessed"))
    return rows


def _largest_concentration_share(
        portfolio: PortfolioAnalyticsResult) -> float | None:
    """Largest slice share across the Day-35 concentration families.

    Returns ``None`` when no slices are measurable (empty portfolio) --
    missing is never zero.
    """
    view = portfolio.concentration
    slices = tuple(view.by_strike) + tuple(view.by_expiry) \
        + tuple(view.by_option_type)
    if not slices:
        return None
    return round(max(s.share for s in slices), 10)


# ---------------------------------------------------------------------------
# Result composition
# ---------------------------------------------------------------------------


def _compose(candidate: StrategyCandidate,
             central_risk: CentralRiskResult,
             policy: FinalRiskPolicy,
             status: FinalRiskStatus,
             blocking: tuple[GateRuleResult, ...],
             issues: list[GateIssue],
             evidence: list[GateEvidence],
             reference: datetime,
             *,
             central_dim: FinalRiskStatus,
             structure_note: str,
             portfolio_present: bool = False,
             tenant: str | None = None,
             rules: tuple[GateRuleResult, ...] | None = None,
             context: PortfolioImpact | None = None) -> FinalRiskGateResult:
    dimensions: list[GateDimensionAssessment] = [
        _dim(FinalRiskGateDimension.STRUCTURAL,
             _PASS if status is not _INVALID else status, structure_note),
        _dim(FinalRiskGateDimension.CENTRAL_RISK, central_dim,
             f"Day-33 central risk consumed whole "
             f"(status {central_risk.status.value})"),
    ]

    if context is None:
        # Portfolio-dependent dimensions were not reached (early ladder exit
        # before portfolio consumption) or the portfolio was not supplied.
        dim_note = ("not evaluated: the final gate exited before portfolio "
                    "consumption") if portfolio_present is False else \
            "portfolio analytics were not supplied"
        portfolio_status = status
        dimensions.append(_dim(FinalRiskGateDimension.PORTFOLIO_IMPACT,
                               portfolio_status, dim_note))
        dimensions.append(_dim(FinalRiskGateDimension.CONCENTRATION,
                               portfolio_status, dim_note))
        dimensions.append(_dim(FinalRiskGateDimension.DIRECTIONAL,
                               portfolio_status, dim_note))
    else:
        dimensions.append(_dim(FinalRiskGateDimension.PORTFOLIO_IMPACT,
                               status,
                               "portfolio impact consumed from Day-35 "
                               "analytics (source-separated)"))
        dimensions.append(_dim(FinalRiskGateDimension.CONCENTRATION, status,
                               "concentration context consumed from Day-35 "
                               "analytics"))
        dimensions.append(_dim(FinalRiskGateDimension.DIRECTIONAL, status,
                               "directional exposure is descriptive delta "
                               "evidence only"))

    if context is not None and context.regime_label is None:
        regime_dim = _UNAVAILABLE
        regime_note = ("regime unknown; no regime condition is evaluated "
                       "and a label never manufactures direction")
        if status is _PASS:
            issues.append(_issue(FinalRiskIssueCode.REGIME_UNKNOWN,
                                 "regime is unknown; the gate records no "
                                 "regime-based condition (nothing guessed)"))
    else:
        regime_dim = _PASS
        regime_note = (f"known regime {context.regime_label} (contextual "
                       "only)" if context is not None
                       else "regime context not applicable")
    dimensions.append(_dim(FinalRiskGateDimension.REGIME, regime_dim,
                           regime_note))

    if candidate.quality is not None:
        quality_dim = _PASS
        quality_note = (f"candidate quality "
                        f"{candidate.quality.quality_state.value} present")
    else:
        quality_dim = _PARTIAL
        quality_note = ("candidate carries no quality; recorded as "
                        "incomplete (never invented)")
    dimensions.append(_dim(FinalRiskGateDimension.DATA_QUALITY, quality_dim,
                           quality_note))

    result_portfolio = context if context is not None else PortfolioImpact(
        position_count=0, delta_reads=(), day33_worst_scenario_pnl=None,
        portfolio_scenario_state=None, regime_label=None,
        notes=("no portfolio context",),
    )

    return FinalRiskGateResult(
        status=status,
        candidate_id=candidate.candidate_id,
        strategy_id=candidate.strategy_id,
        opportunity_id=candidate.opportunity_id,
        tenant_id=tenant,
        central_risk_status=central_risk.status,
        dimensions=tuple(dimensions),
        policy=PolicyGateAssessment(
            policy_version=policy.policy_version,
            rules=tuple(rules) if rules is not None else tuple(blocking)),
        blocking_reasons=blocking,
        evidence=tuple(evidence),
        issues=tuple(issues),
        portfolio=result_portfolio,
        reference_timestamp=reference,
        contract_version=FINAL_RISK_GATE_CONTRACT_VERSION,
        calculation_version=FINAL_RISK_GATE_CALCULATION_VERSION,
    )


def evaluate_final_gate(
    candidate: StrategyCandidate,
    central_risk: CentralRiskResult,
    portfolio: PortfolioAnalyticsResult | None,
    *,
    policy: FinalRiskPolicy,
    reference_timestamp: datetime | None = None,
    tenant_id: str | None = None,
) -> FinalRiskGateResult:
    """Compatibility wrapper around :func:`evaluate_final_risk_gate`.

    Bundles the positional inputs into a ``FinalRiskGateInput`` and calls
    the canonical entrypoint.  New callers should use
    ``evaluate_final_risk_gate(FinalRiskGateInput(...))`` directly.
    """
    return evaluate_final_risk_gate(
        FinalRiskGateInput(candidate=candidate, central_risk=central_risk,
                           portfolio=portfolio, policy=policy,
                           tenant_id=tenant_id),
        reference_timestamp=reference_timestamp,
    )
