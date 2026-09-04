"""Day 32 — pure Strategy Candidate lifecycle and Opportunity Gate."""

from __future__ import annotations

from datetime import datetime

from app.market_data.quality import QualityResult
from app.opportunity.contracts import ExpectedBehavior, Opportunity
from app.quant.scenarios import OptionLeg
from app.strategy_evaluation.contracts import StrategyEvaluationResult, StrategyEvaluationStatus
from app.strike_ranking.contracts import StrikeRankingResult, StrikeRankingStatus
from app.strategy_lifecycle.contracts import (
    BlockingReason,
    BlockingReasonCode,
    GateEvidence,
    GateStatus,
    StrategyCandidate,
    StrategyGateResult,
    StrategyLifecycleState,
)


_LEGAL_TRANSITIONS: dict[StrategyLifecycleState, frozenset[StrategyLifecycleState]] = {
    StrategyLifecycleState.CANDIDATE: frozenset({
        StrategyLifecycleState.EVALUATED,
        StrategyLifecycleState.BLOCKED,
        StrategyLifecycleState.INVALID,
    }),
    StrategyLifecycleState.EVALUATED: frozenset({
        StrategyLifecycleState.ELIGIBLE,
        StrategyLifecycleState.BLOCKED,
        StrategyLifecycleState.INVALID,
    }),
    StrategyLifecycleState.ELIGIBLE: frozenset(),
    StrategyLifecycleState.BLOCKED: frozenset(),
    StrategyLifecycleState.EXPIRED: frozenset(),
    StrategyLifecycleState.INVALID: frozenset(),
}


def transition_lifecycle(
    current: StrategyLifecycleState,
    target: StrategyLifecycleState,
) -> StrategyLifecycleState | None:
    """Return the target only when the lifecycle transition is legal."""
    if not isinstance(current, StrategyLifecycleState) or not isinstance(target, StrategyLifecycleState):
        return None
    return target if target in _LEGAL_TRANSITIONS[current] else None


def _reason(code: BlockingReasonCode, message: str) -> BlockingReason:
    return BlockingReason(code=code, message=message)


def _evidence(kind: str, passed: bool, message: str, provenance=None) -> GateEvidence:
    return GateEvidence(kind=kind, passed=passed, message=message, provenance=provenance)


def _candidate_id(opportunity_id: str, strategy_id: str, strike_ids: tuple[str, ...]) -> str:
    # Stable, human-auditable identity derived only from explicit inputs.
    return "candidate:" + ":".join((opportunity_id, strategy_id, *strike_ids))


def evaluate_strategy_gate(
    opportunity: Opportunity | None,
    ranked_strikes: StrikeRankingResult | None,
    evaluation: StrategyEvaluationResult | None,
    *,
    strategy_id: str | None = None,
    legs: tuple[OptionLeg, ...] = (),
    expected_behavior: ExpectedBehavior | None = None,
    invalidation: str | None = None,
    reference_timestamp: datetime | None = None,
    confidence: float | None = None,
    quality: QualityResult | None = None,
) -> StrategyGateResult:
    """Compose Day-28/30/31 outputs and decide Day-32 structural eligibility.

    The function is deliberately caller-timestamped and side-effect free.
    Eligibility is only permission to proceed to Day 33 risk checking; it is
    never an execution, risk, or user-approval decision.
    """
    reasons: list[BlockingReason] = []
    evidence: list[GateEvidence] = []

    if opportunity is None:
        reasons.append(_reason(BlockingReasonCode.MISSING_OPPORTUNITY, "Opportunity is required"))
    elif not isinstance(opportunity, Opportunity):
        reasons.append(_reason(BlockingReasonCode.INVALID_OPPORTUNITY, "Opportunity has an invalid domain type"))
    else:
        evidence.append(_evidence("OPPORTUNITY", True, "authoritative Opportunity supplied", opportunity.provenance))

    if not strategy_id or not isinstance(strategy_id, str) or not strategy_id.strip():
        reasons.append(_reason(BlockingReasonCode.MISSING_STRATEGY_ID, "strategy_id is required"))
    else:
        evidence.append(_evidence("STRATEGY_ID", True, "strategy identity supplied"))

    if not isinstance(legs, tuple) or not legs:
        reasons.append(_reason(BlockingReasonCode.MISSING_LEGS, "strategy legs are required"))
    elif not all(isinstance(leg, OptionLeg) for leg in legs):
        reasons.append(_reason(BlockingReasonCode.MISSING_LEGS, "strategy legs contain an invalid domain object"))
    else:
        evidence.append(_evidence("LEGS", True, f"{len(legs)} strategy leg(s) supplied"))

    strike_ids: tuple[str, ...] = ()
    if ranked_strikes is None:
        reasons.append(_reason(BlockingReasonCode.MISSING_STRIKE_SELECTION, "ranked strike selection is required"))
    elif not isinstance(ranked_strikes, StrikeRankingResult):
        reasons.append(_reason(BlockingReasonCode.INVALID_STRIKE_SELECTION, "ranked strike result has an invalid domain type"))
    elif ranked_strikes.status is not StrikeRankingStatus.SUCCESS or not ranked_strikes.ranked:
        reasons.append(_reason(BlockingReasonCode.MISSING_STRIKE_SELECTION, "no eligible ranked strike selection is available"))
    else:
        ids = tuple(getattr(item, "candidate_id", None) for item in ranked_strikes.ranked)
        if not ids or not all(isinstance(item, str) and item.strip() for item in ids):
            reasons.append(_reason(BlockingReasonCode.INVALID_STRIKE_SELECTION, "ranked strike selection has invalid candidate identities"))
        else:
            strike_ids = ids
            evidence.append(_evidence("STRIKE_SELECTION", True, f"{len(strike_ids)} ranked strike identity(ies) preserved"))

    if evaluation is None:
        reasons.append(_reason(BlockingReasonCode.MISSING_EVALUATION, "Day-31 Strategy Evaluation is required"))
    elif not isinstance(evaluation, StrategyEvaluationResult):
        reasons.append(_reason(BlockingReasonCode.INVALID_EVALUATION, "Strategy Evaluation has an invalid domain type"))
    elif evaluation.status is StrategyEvaluationStatus.INVALID:
        reasons.append(_reason(BlockingReasonCode.INVALID_EVALUATION, "Day-31 Strategy Evaluation is INVALID"))
    elif evaluation.status is not StrategyEvaluationStatus.SUCCESS:
        reasons.append(_reason(BlockingReasonCode.INCOMPLETE_EVALUATION, f"Day-31 Strategy Evaluation is {evaluation.status.value}; SUCCESS is required"))
    else:
        evidence.append(_evidence("STRATEGY_EVALUATION", True, "Day-31 Strategy Evaluation is complete", evaluation.provenance))

    if evaluation is not None and isinstance(evaluation, StrategyEvaluationResult) and strategy_id:
        if getattr(evaluation, "strategy_id", None) != strategy_id:
            reasons.append(_reason(BlockingReasonCode.INVALID_EVALUATION, "strategy_id does not match the Day-31 evaluation"))

    resolved_reference = reference_timestamp
    if resolved_reference is None and isinstance(evaluation, StrategyEvaluationResult):
        resolved_reference = evaluation.reference_timestamp
    if resolved_reference is None:
        reasons.append(_reason(BlockingReasonCode.MISSING_REFERENCE_TIMESTAMP, "an explicit reference timestamp is required"))
    elif resolved_reference.tzinfo is None or resolved_reference.tzinfo.utcoffset(resolved_reference) is None:
        reasons.append(_reason(BlockingReasonCode.INVALID_REFERENCE_TIMESTAMP, "reference timestamp must be genuinely timezone-aware"))
    else:
        evidence.append(_evidence("REFERENCE_TIMESTAMP", True, "timezone-aware reference timestamp supplied"))

    resolved_quality = quality
    if resolved_quality is None and isinstance(evaluation, StrategyEvaluationResult):
        resolved_quality = evaluation.quality
    if resolved_quality is None and isinstance(opportunity, Opportunity):
        resolved_quality = opportunity.quality
    if resolved_quality is None:
        reasons.append(_reason(BlockingReasonCode.MISSING_QUALITY, "quality is required and cannot be fabricated"))
    elif resolved_quality.quality_state is QualityState.INSUFFICIENT:
        reasons.append(_reason(BlockingReasonCode.INSUFFICIENT_QUALITY, "INSUFFICIENT quality blocks the Opportunity Gate"))
    else:
        evidence.append(_evidence("QUALITY", True, f"quality state {resolved_quality.quality_state.value} remains visible"))

    resolved_confidence = confidence
    if resolved_confidence is None and isinstance(evaluation, StrategyEvaluationResult):
        resolved_confidence = evaluation.confidence
    if resolved_confidence is None and isinstance(opportunity, Opportunity):
        resolved_confidence = opportunity.confidence

    if reasons:
        return StrategyGateResult(
            status=GateStatus.BLOCKED if not any(r.code in {
                BlockingReasonCode.INVALID_OPPORTUNITY,
                BlockingReasonCode.INVALID_STRIKE_SELECTION,
                BlockingReasonCode.INVALID_EVALUATION,
                BlockingReasonCode.INVALID_REFERENCE_TIMESTAMP,
            } for r in reasons) else GateStatus.INVALID,
            candidate=None,
            lifecycle_state=StrategyLifecycleState.BLOCKED if not any(r.code in {
                BlockingReasonCode.INVALID_OPPORTUNITY,
                BlockingReasonCode.INVALID_STRIKE_SELECTION,
                BlockingReasonCode.INVALID_EVALUATION,
                BlockingReasonCode.INVALID_REFERENCE_TIMESTAMP,
            } for r in reasons) else StrategyLifecycleState.INVALID,
            eligible=False,
            blocking_reasons=tuple(reasons),
            evidence=tuple(evidence),
            confidence=resolved_confidence,
            quality=resolved_quality,
            reference_timestamp=resolved_reference,
            provenance=opportunity.provenance if isinstance(opportunity, Opportunity) else None,
        )

    candidate = StrategyCandidate(
        candidate_id=_candidate_id(opportunity.opportunity_id, strategy_id, strike_ids),
        opportunity_id=opportunity.opportunity_id,
        strategy_id=strategy_id,
        legs=legs,
        selected_strike_ids=strike_ids,
        expected_behavior=expected_behavior or opportunity.expected_behavior,
        invalidation=invalidation or opportunity.invalidation,
        evaluation=evaluation,
        lifecycle_state=StrategyLifecycleState.ELIGIBLE,
        confidence=resolved_confidence,
        quality=resolved_quality,
        reference_timestamp=resolved_reference,
        provenance=opportunity.provenance,
    )
    return StrategyGateResult(
        status=GateStatus.ELIGIBLE,
        candidate=candidate,
        lifecycle_state=StrategyLifecycleState.ELIGIBLE,
        eligible=True,
        blocking_reasons=(),
        evidence=tuple(evidence),
        confidence=resolved_confidence,
        quality=resolved_quality,
        reference_timestamp=resolved_reference,
        provenance=opportunity.provenance,
    )
