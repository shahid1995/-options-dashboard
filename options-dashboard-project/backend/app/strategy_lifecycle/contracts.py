"""Day 32 — Strategy lifecycle and Opportunity Gate contracts.

Pure, immutable domain contracts connecting Day-28 Opportunity, Day-30
strike ranking and Day-31 Strategy Evaluation. No execution or risk
authorization semantics live here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import DimensionResult, IssueSeverity, QualityDimension, QualityIssue, QualityIssueCode, QualityResult
from app.opportunity.contracts import ExpectedBehavior
from app.quant.scenarios import OptionLeg
from app.strategy_evaluation.contracts import StrategyEvaluationResult

STRATEGY_LIFECYCLE_CONTRACT_VERSION = "1.0.0"


class StrategyLifecycleState(str, Enum):
    CANDIDATE = "CANDIDATE"
    EVALUATED = "EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class GateStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"


class BlockingReasonCode(str, Enum):
    MISSING_OPPORTUNITY = "MISSING_OPPORTUNITY"
    INVALID_OPPORTUNITY = "INVALID_OPPORTUNITY"
    MISSING_STRATEGY_ID = "MISSING_STRATEGY_ID"
    MISSING_LEGS = "MISSING_LEGS"
    MISSING_STRIKE_SELECTION = "MISSING_STRIKE_SELECTION"
    INVALID_STRIKE_SELECTION = "INVALID_STRIKE_SELECTION"
    MISSING_EVALUATION = "MISSING_EVALUATION"
    INVALID_EVALUATION = "INVALID_EVALUATION"
    INCOMPLETE_EVALUATION = "INCOMPLETE_EVALUATION"
    MISSING_REFERENCE_TIMESTAMP = "MISSING_REFERENCE_TIMESTAMP"
    INVALID_REFERENCE_TIMESTAMP = "INVALID_REFERENCE_TIMESTAMP"
    MISSING_QUALITY = "MISSING_QUALITY"
    INSUFFICIENT_QUALITY = "INSUFFICIENT_QUALITY"


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be genuinely timezone-aware")


def _finite(value: float | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
        raise ValueError(f"{name} must be finite or None")


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _prov_to_dict(value: Provenance | None) -> dict | None:
    return _json_value(value) if value is not None else None


def _prov_from_dict(value: dict | None) -> Provenance | None:
    if value is None:
        return None
    return Provenance(source=value["source"], collection_mode=value["collection_mode"],
                      received_at=datetime.fromisoformat(value["received_at"]),
                      normalization_version=value["normalization_version"],
                      contract_version=value["contract_version"],
                      transformation_id=value.get("transformation_id"))


def _quality_to_dict(value: QualityResult | None) -> dict | None:
    return _json_value(value) if value is not None else None


def _quality_from_dict(value: dict | None) -> QualityResult | None:
    if value is None:
        return None
    def issue_from_dict(item: dict) -> QualityIssue:
        return QualityIssue(dimension=QualityDimension(item["dimension"]), code=QualityIssueCode(item["code"]),
                            severity=IssueSeverity(item["severity"]), message=item["message"], field=item.get("field"))
    dimensions = tuple(
        DimensionResult(dimension=QualityDimension(item["dimension"]), status=item["status"], score=item.get("score"),
                        issues=tuple(issue_from_dict(issue) for issue in item.get("issues", [])))
        for item in value.get("dimensions", [])
    )
    return QualityResult(
        quality_score=value["quality_score"], quality_state=QualityState(value["quality_state"]),
        critical_failure=value["critical_failure"], issues=tuple(issue_from_dict(x) for x in value.get("issues", [])),
        dimensions=dimensions,
        evaluated_at=datetime.fromisoformat(value["evaluated_at"]) if value.get("evaluated_at") else None,
        observation_time=datetime.fromisoformat(value["observation_time"]) if value.get("observation_time") else None,
        observation_type=value["observation_type"], contract_version=value.get("contract_version"),
        reference_time=datetime.fromisoformat(value["reference_time"]) if value.get("reference_time") else None,
    )


def _leg_to_dict(leg: OptionLeg) -> dict:
    return _json_value(leg)


def _leg_from_dict(data: dict) -> OptionLeg:
    from app.market_data.contracts import Side
    from app.quant.scenarios import PositionDirection
    return OptionLeg(option_type=Side(data["option_type"]), strike=data["strike"], expiry=data["expiry"],
                     quantity=data["quantity"], direction=PositionDirection(data["direction"]),
                     entry_price=data.get("entry_price"), implied_volatility=data.get("implied_volatility"),
                     quality=QualityState(data["quality"]) if data.get("quality") else None,
                     provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class BlockingReason:
    code: BlockingReasonCode
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, BlockingReasonCode):
            raise ValueError("code must be a BlockingReasonCode")
        _require_text(self.message, "message")

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> "BlockingReason":
        return cls(code=BlockingReasonCode(data["code"]), message=data["message"])


@dataclass(frozen=True)
class GateEvidence:
    kind: str
    passed: bool
    message: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be bool")
        _require_text(self.message, "message")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance or None")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "passed": self.passed, "message": self.message,
                "provenance": _prov_to_dict(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "GateEvidence":
        return cls(kind=data["kind"], passed=data["passed"], message=data["message"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class StrategyCandidate:
    candidate_id: str
    opportunity_id: str
    strategy_id: str
    legs: tuple[OptionLeg, ...]
    selected_strike_ids: tuple[str, ...]
    expected_behavior: ExpectedBehavior
    invalidation: str
    evaluation: StrategyEvaluationResult
    lifecycle_state: StrategyLifecycleState
    confidence: float | None
    quality: QualityResult | None
    reference_timestamp: datetime
    provenance: Provenance | None

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.opportunity_id, "opportunity_id")
        _require_text(self.strategy_id, "strategy_id")
        if not isinstance(self.legs, tuple) or not self.legs or not all(isinstance(x, OptionLeg) for x in self.legs):
            raise ValueError("legs must be a non-empty tuple of OptionLeg")
        if not isinstance(self.selected_strike_ids, tuple) or not self.selected_strike_ids or not all(isinstance(x, str) and x.strip() for x in self.selected_strike_ids):
            raise ValueError("selected_strike_ids must be a non-empty tuple of strings")
        if not isinstance(self.expected_behavior, ExpectedBehavior):
            raise ValueError("expected_behavior must be ExpectedBehavior")
        _require_text(self.invalidation, "invalidation")
        if not isinstance(self.evaluation, StrategyEvaluationResult):
            raise ValueError("evaluation must be StrategyEvaluationResult")
        if not isinstance(self.lifecycle_state, StrategyLifecycleState):
            raise ValueError("lifecycle_state must be StrategyLifecycleState")
        _finite(self.confidence, "confidence")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1] or None")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be QualityResult or None")
        _aware(self.reference_timestamp, "reference_timestamp")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance or None")

    def to_dict(self) -> dict:
        return {"contract": "strategy_lifecycle.candidate", "version": STRATEGY_LIFECYCLE_CONTRACT_VERSION,
                "candidate_id": self.candidate_id, "opportunity_id": self.opportunity_id,
                "strategy_id": self.strategy_id, "legs": [_leg_to_dict(leg) for leg in self.legs],
                "selected_strike_ids": list(self.selected_strike_ids), "expected_behavior": self.expected_behavior.value,
                "invalidation": self.invalidation, "evaluation": self.evaluation.to_dict(),
                "lifecycle_state": self.lifecycle_state.value, "confidence": self.confidence,
                "quality": _quality_to_dict(self.quality), "reference_timestamp": self.reference_timestamp.isoformat(),
                "provenance": _prov_to_dict(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyCandidate":
        return cls(candidate_id=data["candidate_id"], opportunity_id=data["opportunity_id"], strategy_id=data["strategy_id"],
                   legs=tuple(_leg_from_dict(x) for x in data["legs"]), selected_strike_ids=tuple(data["selected_strike_ids"]),
                   expected_behavior=ExpectedBehavior(data["expected_behavior"]), invalidation=data["invalidation"],
                   evaluation=StrategyEvaluationResult.from_dict(data["evaluation"]),
                   lifecycle_state=StrategyLifecycleState(data["lifecycle_state"]), confidence=data.get("confidence"),
                   quality=_quality_from_dict(data.get("quality")),
                   reference_timestamp=datetime.fromisoformat(data["reference_timestamp"]),
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class StrategyGateResult:
    status: GateStatus
    candidate: StrategyCandidate | None
    lifecycle_state: StrategyLifecycleState
    eligible: bool
    blocking_reasons: tuple[BlockingReason, ...]
    evidence: tuple[GateEvidence, ...]
    confidence: float | None
    quality: QualityResult | None
    reference_timestamp: datetime | None
    provenance: Provenance | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be GateStatus")
        if self.candidate is not None and not isinstance(self.candidate, StrategyCandidate):
            raise ValueError("candidate must be StrategyCandidate or None")
        if not isinstance(self.lifecycle_state, StrategyLifecycleState):
            raise ValueError("lifecycle_state must be StrategyLifecycleState")
        if not isinstance(self.eligible, bool):
            raise ValueError("eligible must be bool")
        if not isinstance(self.blocking_reasons, tuple) or not all(isinstance(x, BlockingReason) for x in self.blocking_reasons):
            raise ValueError("blocking_reasons must be a tuple of BlockingReason")
        if not isinstance(self.evidence, tuple) or not all(isinstance(x, GateEvidence) for x in self.evidence):
            raise ValueError("evidence must be a tuple of GateEvidence")
        _finite(self.confidence, "confidence")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1] or None")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be QualityResult or None")
        if self.reference_timestamp is not None:
            _aware(self.reference_timestamp, "reference_timestamp")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance or None")
        if self.eligible and self.status is not GateStatus.ELIGIBLE:
            raise ValueError("eligible result must have ELIGIBLE status")
        if not self.eligible and self.status is GateStatus.ELIGIBLE:
            raise ValueError("ELIGIBLE status must set eligible=True")

    def to_dict(self) -> dict:
        return {"contract": "strategy_lifecycle.gate_result", "version": STRATEGY_LIFECYCLE_CONTRACT_VERSION,
                "status": self.status.value, "candidate": self.candidate.to_dict() if self.candidate else None,
                "lifecycle_state": self.lifecycle_state.value, "eligible": self.eligible,
                "blocking_reasons": [x.to_dict() for x in self.blocking_reasons],
                "evidence": [x.to_dict() for x in self.evidence], "confidence": self.confidence,
                "quality": _quality_to_dict(self.quality),
                "reference_timestamp": self.reference_timestamp.isoformat() if self.reference_timestamp else None,
                "provenance": _prov_to_dict(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyGateResult":
        return cls(status=GateStatus(data["status"]),
                   candidate=StrategyCandidate.from_dict(data["candidate"]) if data.get("candidate") else None,
                   lifecycle_state=StrategyLifecycleState(data["lifecycle_state"]), eligible=data["eligible"],
                   blocking_reasons=tuple(BlockingReason.from_dict(x) for x in data.get("blocking_reasons", [])),
                   evidence=tuple(GateEvidence.from_dict(x) for x in data.get("evidence", [])),
                   confidence=data.get("confidence"), quality=_quality_from_dict(data.get("quality")),
                   reference_timestamp=datetime.fromisoformat(data["reference_timestamp"]) if data.get("reference_timestamp") else None,
                   provenance=_prov_from_dict(data.get("provenance")))
