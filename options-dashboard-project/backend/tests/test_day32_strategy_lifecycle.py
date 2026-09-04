"""Day 32 — Strategy lifecycle and Opportunity Gate tests."""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState, Side
from app.market_data.quality import QualityResult
from app.opportunity.contracts import ExpectedBehavior, Opportunity
from app.quant.scenarios import OptionLeg, PositionDirection
from app.strategy_evaluation.contracts import EvaluationContext, StrategyEvaluationResult, StrategyEvaluationStatus
from app.strike_ranking.contracts import StrikeRankingResult, StrikeRankingStatus
from app.strategy_lifecycle.contracts import BlockingReasonCode, GateStatus, StrategyCandidate, StrategyLifecycleState
from app.strategy_lifecycle.lifecycle import evaluate_strategy_gate, transition_lifecycle

REF = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


def _prov(source: str = "TEST") -> Provenance:
    return Provenance(source=source, collection_mode=DataMode.BROKER_SNAPSHOT.value, received_at=REF,
                      normalization_version="1.0.0", contract_version="1.0.0", transformation_id=None)


def _quality(state: QualityState = QualityState.EXCELLENT) -> QualityResult:
    return QualityResult(quality_score=95 if state is QualityState.EXCELLENT else 55,
                         quality_state=state, critical_failure=False, issues=(), dimensions=(),
                         evaluated_at=REF, observation_time=REF, observation_type="QUOTE",
                         contract_version="1.0.0", reference_time=REF)


def _fake_opportunity(opp_id: str = "opp-1") -> Opportunity:
    obj = object.__new__(Opportunity)
    object.__setattr__(obj, "opportunity_id", opp_id)
    object.__setattr__(obj, "expected_behavior", ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE)
    object.__setattr__(obj, "invalidation", "thesis invalidated")
    object.__setattr__(obj, "provenance", _prov("OPPORTUNITY"))
    object.__setattr__(obj, "confidence", 0.8)
    object.__setattr__(obj, "quality", _quality())
    object.__setattr__(obj, "reference_timestamp", REF)
    return obj


def _fake_leg() -> OptionLeg:
    obj = object.__new__(OptionLeg)
    object.__setattr__(obj, "option_type", Side.CALL)
    object.__setattr__(obj, "strike", 25000.0)
    object.__setattr__(obj, "expiry", "2026-09-24")
    object.__setattr__(obj, "quantity", 1.0)
    object.__setattr__(obj, "direction", PositionDirection.LONG)
    object.__setattr__(obj, "entry_price", 100.0)
    object.__setattr__(obj, "implied_volatility", 0.2)
    object.__setattr__(obj, "quality", QualityState.EXCELLENT)
    object.__setattr__(obj, "provenance", _prov("LEG"))
    return obj


def _fake_ranking(candidate_id: str = "strike-1") -> StrikeRankingResult:
    obj = object.__new__(StrikeRankingResult)
    object.__setattr__(obj, "status", StrikeRankingStatus.SUCCESS)
    object.__setattr__(obj, "ranked", (type("Ranked", (), {"candidate_id": candidate_id})(),))
    object.__setattr__(obj, "suppressed", ())
    return obj


def _fake_evaluation(*, status: StrategyEvaluationStatus = StrategyEvaluationStatus.SUCCESS,
                     strategy_id: str = "strategy-1",
                     context: EvaluationContext = EvaluationContext.OPPORTUNITY,
                     quality: QualityResult | None = None) -> StrategyEvaluationResult:
    obj = object.__new__(StrategyEvaluationResult)
    object.__setattr__(obj, "status", status)
    object.__setattr__(obj, "strategy_id", strategy_id)
    object.__setattr__(obj, "evaluation_context", context)
    object.__setattr__(obj, "reference_timestamp", REF)
    object.__setattr__(obj, "legs", (_fake_leg(),))
    object.__setattr__(obj, "confidence", 0.75)
    object.__setattr__(obj, "quality", quality or _quality())
    object.__setattr__(obj, "opportunity_id", "opp-1")
    object.__setattr__(obj, "provenance", _prov("EVALUATION"))
    return obj


def _candidate(**overrides) -> StrategyCandidate:
    values = dict(candidate_id="candidate-1", opportunity_id="opp-1", strategy_id="strategy-1",
                  legs=(_fake_leg(),), selected_strike_ids=("strike-1",),
                  expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                  invalidation="thesis invalidated", evaluation=_fake_evaluation(),
                  lifecycle_state=StrategyLifecycleState.ELIGIBLE, confidence=0.75,
                  quality=_quality(), reference_timestamp=REF, provenance=_prov("OPPORTUNITY"))
    values.update(overrides)
    return StrategyCandidate(**values)


def test_valid_opportunity_produces_eligible_strategy_candidate():
    result = evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(), _fake_evaluation(),
                                    strategy_id="strategy-1", legs=(_fake_leg(),),
                                    expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF,
                                    confidence=0.75, quality=_quality())
    assert result.status is GateStatus.ELIGIBLE
    assert result.eligible is True
    assert result.lifecycle_state is StrategyLifecycleState.ELIGIBLE
    assert result.candidate is not None
    assert result.candidate.opportunity_id == "opp-1"
    assert result.candidate.selected_strike_ids == ("strike-1",)


def test_missing_opportunity_is_blocked_explicitly():
    result = evaluate_strategy_gate(None, _fake_ranking(), _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=_quality())
    assert result.status is GateStatus.BLOCKED
    assert not result.eligible
    assert BlockingReasonCode.MISSING_OPPORTUNITY in {r.code for r in result.blocking_reasons}


def test_incomplete_evaluation_cannot_become_eligible():
    result = evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(),
                                    _fake_evaluation(status=StrategyEvaluationStatus.PARTIAL),
                                    strategy_id="strategy-1", legs=(_fake_leg(),),
                                    expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=_quality())
    assert result.status is GateStatus.BLOCKED
    assert BlockingReasonCode.INCOMPLETE_EVALUATION in {r.code for r in result.blocking_reasons}


def test_missing_strike_selection_is_blocked():
    empty = object.__new__(StrikeRankingResult)
    object.__setattr__(empty, "status", StrikeRankingStatus.NOTHING_ELIGIBLE)
    object.__setattr__(empty, "ranked", ())
    object.__setattr__(empty, "suppressed", ())
    result = evaluate_strategy_gate(_fake_opportunity(), empty, _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=_quality())
    assert result.status is GateStatus.BLOCKED
    assert BlockingReasonCode.MISSING_STRIKE_SELECTION in {r.code for r in result.blocking_reasons}


def test_insufficient_quality_blocks_gate_without_coercion():
    result = evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(), _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF,
                                    quality=_quality(QualityState.INSUFFICIENT))
    assert result.status is GateStatus.BLOCKED
    assert BlockingReasonCode.INSUFFICIENT_QUALITY in {r.code for r in result.blocking_reasons}
    assert result.quality is not None
    assert result.quality.quality_state is QualityState.INSUFFICIENT


def test_degraded_quality_remains_visible_and_is_not_relabelled_success():
    degraded = _quality(QualityState.DEGRADED)
    result = evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(), _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=degraded)
    assert result.quality is degraded
    assert result.quality.quality_state is QualityState.DEGRADED


def test_lifecycle_transition_matrix_is_explicit_and_terminal():
    assert transition_lifecycle(StrategyLifecycleState.CANDIDATE, StrategyLifecycleState.EVALUATED) is StrategyLifecycleState.EVALUATED
    assert transition_lifecycle(StrategyLifecycleState.EVALUATED, StrategyLifecycleState.ELIGIBLE) is StrategyLifecycleState.ELIGIBLE
    assert transition_lifecycle(StrategyLifecycleState.CANDIDATE, StrategyLifecycleState.BLOCKED) is StrategyLifecycleState.BLOCKED
    assert transition_lifecycle(StrategyLifecycleState.EVALUATED, StrategyLifecycleState.BLOCKED) is StrategyLifecycleState.BLOCKED
    assert transition_lifecycle(StrategyLifecycleState.BLOCKED, StrategyLifecycleState.EVALUATED) is None
    assert transition_lifecycle(StrategyLifecycleState.EXPIRED, StrategyLifecycleState.ELIGIBLE) is None
    assert transition_lifecycle(StrategyLifecycleState.INVALID, StrategyLifecycleState.CANDIDATE) is None


def test_candidate_is_immutable_and_serializes_deterministically():
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.strategy_id = "other"  # type: ignore[misc]
    first = candidate.to_dict()
    second = candidate.to_dict()
    assert first == second
    json.dumps(first)


def test_blocked_gate_result_round_trips_and_preserves_provenance():
    result = evaluate_strategy_gate(None, _fake_ranking(), _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=_quality())
    encoded = result.to_dict()
    assert result.provenance is None
    assert json.dumps(encoded)
    assert result.__class__.from_dict(encoded).to_dict() == encoded


def test_gate_result_preserves_opportunity_provenance():
    result = evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(), _fake_evaluation(), strategy_id="strategy-1",
                                    legs=(_fake_leg(),), expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                    invalidation="thesis invalidated", reference_timestamp=REF, quality=_quality())
    assert result.provenance == _prov("OPPORTUNITY")
    assert result.candidate is not None
    assert result.candidate.provenance == _prov("OPPORTUNITY")


def test_same_inputs_are_context_equivalent():
    results = []
    for context in EvaluationContext:
        evaluation = _fake_evaluation(context=context)
        results.append(evaluate_strategy_gate(_fake_opportunity(), _fake_ranking(), evaluation,
                                              strategy_id="strategy-1", legs=(_fake_leg(),),
                                              expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                                              invalidation="thesis invalidated", reference_timestamp=REF,
                                              quality=_quality()).to_dict())
    normalized = [{k: v for k, v in item.items() if k != "candidate"} for item in results]
    assert all(item == normalized[0] for item in normalized)


def test_lifecycle_package_has_no_broker_or_execution_imports():
    source = Path(__file__).parents[1] / "app" / "strategy_lifecycle"
    forbidden_modules = {"time", "random", "uuid", "requests", "httpx", "sqlalchemy"}
    forbidden_identifiers = {"BrokerAdapter", "Order", "UserApproval", "RiskDecision", "authorize"}
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_modules for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or node.module.split(".")[0] not in forbidden_modules
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden_identifiers


def test_lifecycle_package_does_not_read_wall_clock():
    source = Path(__file__).parents[1] / "app" / "strategy_lifecycle"
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today"}:
                raise AssertionError(f"wall-clock access found: {node.attr}")
