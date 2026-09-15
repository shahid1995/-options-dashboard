"""Day 33 — Central Risk Engine contracts (approved design).

Pure, immutable, deterministic contracts for the standalone strategy-risk
boundary that consumes an eligible Day-32 StrategyCandidate plus an
explicit RiskPolicy:

    eligible Day-32 StrategyCandidate
        + RiskPolicy + caller-supplied reference timestamp
        -> assess_candidate_risk(...)
        -> CentralRiskResult

Semantics locked here
---------------------
* Risk metrics, confidence, quality and the policy decision are separate
  channels.  No opaque aggregate risk score exists; no weighted-score
  laundering is possible (a BLOCKED verdict cannot be overridden).
* PASS means the standalone risk-policy requirements passed -- NOT trade,
  portfolio, capital, margin, user or execution approval.
* Missing data stays missing (never zero / neutral / favourable / safe).
  Unbounded loss is represented explicitly (``loss_unbounded``) and never
  fabricated as a zero maximum loss.
* Authoritative payoff/Greek/scenario assessments from Day 31 (which
  themselves reuse Day 18) are consumed whole; no duplicate quantitative
  mathematics exists here.
* The worst supplied scenario P/L is exactly the authoritative Day-18
  scenario minimum -- never labelled theoretical worst-case.
* Provenance is preserved at dimension level and result level; nothing is
  flattened into a fabricated single source.
* Dimension states reuse the established assessment vocabulary
  (DimensionState: AVAILABLE | PARTIAL | UNAVAILABLE | INVALID).
* Identity/versions are explicit; no wall clock, randomness, IO, broker
  or execution semantics exist anywhere in this package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import QualityResult
from app.strategy_evaluation.contracts import DimensionState

#: Day-33 contract version (independent of Day-19/28/31/32 versions).
CENTRAL_RISK_CONTRACT_VERSION = "1.0.0"
#: Deterministic engine calculation version for the risk-policy evaluation.
CENTRAL_RISK_CALCULATION_VERSION = "central_risk.v1"


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class CentralRiskStatus(str, Enum):
    """Deterministic standalone-risk verdict.

    * ``PASS`` — required risk evidence is sufficiently available and every
      applicable policy requirement passes.
    * ``BLOCKED`` — risk is sufficiently known and an explicit policy rule
      fails (evidence stays visible).
    * ``PARTIAL`` — risk assessment is possible but required information is
      incomplete; never a false PASS.
    * ``UNAVAILABLE`` — risk cannot be meaningfully assessed from the
      supplied inputs.
    * ``INVALID`` — the candidate or authoritative inputs violate a domain
      invariant (non-eligible lifecycle, structurally invalid legs, INVALID
      Day-31 evaluation).

    PASS is NOT approval of any kind (trade/portfolio/capital/user/
    execution).  Those decisions live in Day 34+ boundaries.
    """

    PASS = "PASS"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class PolicyRuleCode(str, Enum):
    """Explicit, machine-readable risk-policy rule identifiers."""

    MAX_STANDALONE_LOSS = "MAX_STANDALONE_LOSS"
    UNBOUNDED_LOSS = "UNBOUNDED_LOSS"
    MAX_SCENARIO_LOSS = "MAX_SCENARIO_LOSS"
    MIN_QUALITY = "MIN_QUALITY"
    MAX_DATA_AGE = "MAX_DATA_AGE"


class CentralRiskIssueCode(str, Enum):
    """Structured issue categories (evidence-backed, never opaque)."""

    NOT_ELIGIBLE_CANDIDATE = "NOT_ELIGIBLE_CANDIDATE"
    INVALID_EVALUATION = "INVALID_EVALUATION"
    STRUCTURAL_INVALID = "STRUCTURAL_INVALID"
    INCOMPLETE_RISK_EVIDENCE = "INCOMPLETE_RISK_EVIDENCE"
    UNAVAILABLE_RISK_EVIDENCE = "UNAVAILABLE_RISK_EVIDENCE"
    INVALID_REFERENCE_TIMESTAMP = "INVALID_REFERENCE_TIMESTAMP"


# ---------------------------------------------------------------------------
# Value helpers (deterministic)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_finite_or_none(value: float | None, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or None")


def _require_non_negative_or_none(value: float | None, name: str) -> None:
    _require_finite_or_none(value, name)
    if value is not None and value < 0.0:
        raise ValueError(f"{name} must be non-negative or None")


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None \
        and ts.tzinfo.utcoffset(ts) is not None


def _fmt_ts(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if not _is_aware(ts):
        raise ValueError("cannot serialize a non-genuinely-aware datetime")
    return ts.isoformat()


def _fmt_provenance(prov: Provenance | None) -> dict | None:
    if prov is None:
        return None
    return {
        "source": prov.source,
        "collection_mode": prov.collection_mode,
        "received_at": prov.received_at.isoformat(),
        "normalization_version": prov.normalization_version,
        "contract_version": prov.contract_version,
        "transformation_id": prov.transformation_id,
    }


def _prov_from_dict(data: dict | None) -> Provenance | None:
    if not data:
        return None
    return Provenance(
        source=data["source"],
        collection_mode=data["collection_mode"],
        received_at=datetime.fromisoformat(data["received_at"]),
        normalization_version=data["normalization_version"],
        contract_version=data["contract_version"],
        transformation_id=data.get("transformation_id"),
    )


def _fmt_quality(quality: QualityResult | None) -> dict | None:
    """Compact JSON-safe projection (state + score), matching the Day-30/31
    quality projection convention."""
    if quality is None:
        return None
    return {"quality_state": quality.quality_state.value,
            "quality_score": quality.quality_score}


def _quality_from_projection(data: dict | None) -> QualityResult | None:
    if not data:
        return None
    return QualityResult(
        quality_score=int(data["quality_score"]),
        quality_state=QualityState(data["quality_state"]),
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=None,
        observation_time=None,
        observation_type="CENTRAL_RISK",
        contract_version="1.0.0",
        reference_time=None,
    )


# ---------------------------------------------------------------------------
# Risk policy (explicit, deterministic, versioned, serializable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskPolicy:
    """Explicit standalone-risk policy.

    ``None`` limit fields mean that particular policy rule is NOT
    configured (an explicit configuration choice -- never a zero limit).
    ``allow_unbounded_loss`` is mandatory and has no default: the caller
    must state whether unbounded standalone loss is permitted.
    """

    policy_version: str
    allow_unbounded_loss: bool
    maximum_standalone_loss: float | None = None
    maximum_scenario_loss: float | None = None
    minimum_quality: QualityState | None = None
    maximum_data_age_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.policy_version, "policy_version")
        if not isinstance(self.allow_unbounded_loss, bool):
            raise ValueError("allow_unbounded_loss must be a bool")
        _require_non_negative_or_none(self.maximum_standalone_loss,
                                      "maximum_standalone_loss")
        _require_non_negative_or_none(self.maximum_scenario_loss,
                                      "maximum_scenario_loss")
        if self.minimum_quality is not None and not isinstance(
                self.minimum_quality, QualityState):
            raise ValueError("minimum_quality must be a QualityState or None")
        _require_non_negative_or_none(self.maximum_data_age_seconds,
                                      "maximum_data_age_seconds")

    def to_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "allow_unbounded_loss": self.allow_unbounded_loss,
            "maximum_standalone_loss": self.maximum_standalone_loss,
            "maximum_scenario_loss": self.maximum_scenario_loss,
            "minimum_quality": self.minimum_quality.value
            if self.minimum_quality else None,
            "maximum_data_age_seconds": self.maximum_data_age_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RiskPolicy":
        return cls(
            policy_version=data["policy_version"],
            allow_unbounded_loss=data["allow_unbounded_loss"],
            maximum_standalone_loss=data.get("maximum_standalone_loss"),
            maximum_scenario_loss=data.get("maximum_scenario_loss"),
            minimum_quality=QualityState(data["minimum_quality"])
            if data.get("minimum_quality") else None,
            maximum_data_age_seconds=data.get("maximum_data_age_seconds"),
        )


# ---------------------------------------------------------------------------
# Risk-dimension assessments (evidence-backed; states are authoritative)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PayoffRisk:
    """Standalone payoff-risk view consuming the Day-31 payoff assessment.

    ``max_loss`` stays ``None`` when the payoff has no finite maximum loss
    (unbounded loss) -- it is NEVER fabricated as zero.
    """

    state: DimensionState
    max_profit: float | None
    max_loss: float | None
    loss_unbounded: bool
    breakevens: tuple[float, ...]
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState):
            raise ValueError("state must be a DimensionState")
        _require_finite_or_none(self.max_profit, "max_profit")
        _require_finite_or_none(self.max_loss, "max_loss")
        if not isinstance(self.loss_unbounded, bool):
            raise ValueError("loss_unbounded must be a bool")
        if not isinstance(self.breakevens, tuple) or not all(
                isinstance(b, (int, float)) and math.isfinite(b)
                for b in self.breakevens):
            raise ValueError("breakevens must be a tuple of finite numbers")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"state": self.state.value, "max_profit": self.max_profit,
                "max_loss": self.max_loss, "loss_unbounded": self.loss_unbounded,
                "breakevens": list(self.breakevens), "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "PayoffRisk":
        return cls(state=DimensionState(data["state"]),
                   max_profit=data["max_profit"], max_loss=data["max_loss"],
                   loss_unbounded=data["loss_unbounded"],
                   breakevens=tuple(data["breakevens"]), note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class GreekRisk:
    """Aggregate strategy Greek exposure (reused Day-31 aggregate result).

    Missing components stay ``None``; the authoritative source label
    (MODEL vs broker) is preserved.
    """

    state: DimensionState
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    legs_priced: int
    legs_total: int
    greeks_source: str | None
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState):
            raise ValueError("state must be a DimensionState")
        for name in ("delta", "gamma", "theta", "vega"):
            _require_finite_or_none(getattr(self, name), name)
        if not isinstance(self.legs_priced, int) or not isinstance(self.legs_total, int) \
                or self.legs_priced < 0 or self.legs_total < 0 \
                or self.legs_priced > self.legs_total:
            raise ValueError("legs_priced must be within [0, legs_total]")
        if self.greeks_source is not None:
            _require_text(self.greeks_source, "greeks_source")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"state": self.state.value, "delta": self.delta, "gamma": self.gamma,
                "theta": self.theta, "vega": self.vega,
                "legs_priced": self.legs_priced, "legs_total": self.legs_total,
                "greeks_source": self.greeks_source, "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "GreekRisk":
        return cls(state=DimensionState(data["state"]), delta=data["delta"],
                   gamma=data["gamma"], theta=data["theta"], vega=data["vega"],
                   legs_priced=data["legs_priced"], legs_total=data["legs_total"],
                   greeks_source=data.get("greeks_source"), note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class ScenarioRisk:
    """Scenario-risk view consuming the authoritative Day-18 scenario output.

    ``min_pnl`` is the worst supplied scenario P/L -- explicitly NOT a
    theoretical absolute worst-case loss.
    """

    state: DimensionState
    points_total: int
    points_assessed: int
    min_pnl: float | None
    max_pnl: float | None
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState):
            raise ValueError("state must be a DimensionState")
        if not isinstance(self.points_total, int) or not isinstance(self.points_assessed, int) \
                or self.points_total < 0 or self.points_assessed < 0 \
                or self.points_assessed > self.points_total:
            raise ValueError("points_assessed must be within [0, points_total]")
        _require_finite_or_none(self.min_pnl, "min_pnl")
        _require_finite_or_none(self.max_pnl, "max_pnl")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"state": self.state.value, "points_total": self.points_total,
                "points_assessed": self.points_assessed, "min_pnl": self.min_pnl,
                "max_pnl": self.max_pnl, "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioRisk":
        return cls(state=DimensionState(data["state"]),
                   points_total=data["points_total"],
                   points_assessed=data["points_assessed"],
                   min_pnl=data["min_pnl"], max_pnl=data["max_pnl"],
                   note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class StructuralRisk:
    """Structural validation of the candidate strategy.

    ``AVAILABLE`` means the strategy structure is supported (non-empty
    legs, every leg with a positive quantity).  Anything else is
    ``INVALID`` with an explicit finding in ``note``.
    """

    state: DimensionState
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState) \
                or self.state not in (DimensionState.AVAILABLE, DimensionState.INVALID):
            raise ValueError("structural state must be AVAILABLE or INVALID")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"state": self.state.value, "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "StructuralRisk":
        return cls(state=DimensionState(data["state"]), note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyRuleResult:
    """One explicit policy-rule outcome.

    ``passed`` is True (satisfied), False (verified violation) or None
    (not verifiable because the required evidence is missing/unavailable).
    ``observed`` / ``limit`` carry the numeric magnitudes for loss/age
    rules; ``observed_quality`` / ``limit_quality`` carry the states for
    the minimum-quality rule.
    """

    rule: PolicyRuleCode
    passed: bool | None
    message: str
    limit: float | None = None
    observed: float | None = None
    limit_quality: QualityState | None = None
    observed_quality: QualityState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule, PolicyRuleCode):
            raise ValueError("rule must be a PolicyRuleCode")
        if self.passed is not None and not isinstance(self.passed, bool):
            raise ValueError("passed must be bool or None")
        _require_text(self.message, "message")
        _require_finite_or_none(self.limit, "limit")
        _require_finite_or_none(self.observed, "observed")
        for name in ("limit_quality", "observed_quality"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, QualityState):
                raise ValueError(f"{name} must be a QualityState or None")

    def to_dict(self) -> dict:
        return {"rule": self.rule.value, "passed": self.passed,
                "message": self.message, "limit": self.limit,
                "observed": self.observed,
                "limit_quality": self.limit_quality.value
                if self.limit_quality else None,
                "observed_quality": self.observed_quality.value
                if self.observed_quality else None}

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyRuleResult":
        return cls(rule=PolicyRuleCode(data["rule"]), passed=data["passed"],
                   message=data["message"], limit=data["limit"],
                   observed=data["observed"],
                   limit_quality=QualityState(data["limit_quality"])
                   if data.get("limit_quality") else None,
                   observed_quality=QualityState(data["observed_quality"])
                   if data.get("observed_quality") else None)


@dataclass(frozen=True)
class PolicyAssessment:
    """The evaluated policy: every configured rule with its outcome."""

    policy_version: str
    rules: tuple[PolicyRuleResult, ...]

    def __post_init__(self) -> None:
        _require_text(self.policy_version, "policy_version")
        if not isinstance(self.rules, tuple) or not all(
                isinstance(r, PolicyRuleResult) for r in self.rules):
            raise ValueError("rules must be a tuple of PolicyRuleResult")

    def to_dict(self) -> dict:
        return {"policy_version": self.policy_version,
                "rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyAssessment":
        return cls(policy_version=data["policy_version"],
                   rules=tuple(PolicyRuleResult.from_dict(r)
                               for r in data["rules"]))


# ---------------------------------------------------------------------------
# Evidence / issues
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskEvidence:
    """One structured evidence row backing a material risk conclusion.

    ``kind`` uses stable labels (PAYOFF / GREEKS / SCENARIO / STRUCTURAL /
    QUALITY / FRESHNESS / POLICY).  ``provenance`` preserves the Day-9
    provenance of the underlying source when one exists (never invented).
    """

    kind: str
    source: str
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        _require_text(self.source, "source")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "RiskEvidence":
        return cls(kind=data["kind"], source=data["source"], note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class RiskIssue:
    """A structured issue naming the reason risk could not be fully
    assessed or the candidate was rejected."""

    code: CentralRiskIssueCode
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, CentralRiskIssueCode):
            raise ValueError("code must be a CentralRiskIssueCode")
        _require_text(self.message, "message")

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> "RiskIssue":
        return cls(code=CentralRiskIssueCode(data["code"]), message=data["message"])


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CentralRiskResult:
    """Deterministic standalone-risk verdict for one strategy candidate.

    ``blocking_reasons`` carries exactly the failed policy rules (empty for
    PASS / PARTIAL / UNAVAILABLE / INVALID).  ``quality`` is the compact
    Day-12 projection; ``confidence`` is the echoed evaluation channel.
    Result-level ``provenance`` is the Day-28 Opportunity provenance;
    dimension evidence keeps its own provenance (never flattened).
    """

    status: CentralRiskStatus
    candidate_id: str
    opportunity_id: str
    strategy_id: str
    payoff_risk: PayoffRisk
    greek_risk: GreekRisk
    scenario_risk: ScenarioRisk
    structural_risk: StructuralRisk
    policy_assessment: PolicyAssessment
    blocking_reasons: tuple[PolicyRuleResult, ...]
    evidence: tuple[RiskEvidence, ...]
    issues: tuple[RiskIssue, ...]
    confidence: float | None
    quality: QualityResult | None
    provenance: Provenance | None
    reference_timestamp: datetime
    contract_version: str = CENTRAL_RISK_CONTRACT_VERSION
    model_version: str | None = None
    calculation_version: str = CENTRAL_RISK_CALCULATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, CentralRiskStatus):
            raise ValueError("status must be a CentralRiskStatus")
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.opportunity_id, "opportunity_id")
        _require_text(self.strategy_id, "strategy_id")
        if not isinstance(self.payoff_risk, PayoffRisk) \
                or not isinstance(self.greek_risk, GreekRisk) \
                or not isinstance(self.scenario_risk, ScenarioRisk) \
                or not isinstance(self.structural_risk, StructuralRisk):
            raise ValueError("risk dimensions must be typed Day-33 assessments")
        if not isinstance(self.policy_assessment, PolicyAssessment):
            raise ValueError("policy_assessment must be a PolicyAssessment")
        if not isinstance(self.blocking_reasons, tuple) or not all(
                isinstance(r, PolicyRuleResult) for r in self.blocking_reasons):
            raise ValueError("blocking_reasons must be a tuple of PolicyRuleResult")
        if not isinstance(self.evidence, tuple) or not all(
                isinstance(e, RiskEvidence) for e in self.evidence):
            raise ValueError("evidence must be a tuple of RiskEvidence")
        if not isinstance(self.issues, tuple) or not all(
                isinstance(i, RiskIssue) for i in self.issues):
            raise ValueError("issues must be a tuple of RiskIssue")
        if self.confidence is not None and \
                not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be within [0, 1] or None")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a QualityResult or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")
        if not _is_aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        _require_text(self.contract_version, "contract_version")
        _require_text(self.calculation_version, "calculation_version")
        # Semantic consistency: BLOCKED implies at least one failed rule.
        if self.status is CentralRiskStatus.BLOCKED and not self.blocking_reasons:
            raise ValueError("BLOCKED requires at least one failed policy rule")
        if self.status is not CentralRiskStatus.BLOCKED and self.blocking_reasons:
            raise ValueError("blocking_reasons are only present on BLOCKED")

    def to_dict(self) -> dict:
        return {
            "contract": "central_risk.result",
            "version": self.contract_version,
            "status": self.status.value,
            "candidate_id": self.candidate_id,
            "opportunity_id": self.opportunity_id,
            "strategy_id": self.strategy_id,
            "payoff_risk": self.payoff_risk.to_dict(),
            "greek_risk": self.greek_risk.to_dict(),
            "scenario_risk": self.scenario_risk.to_dict(),
            "structural_risk": self.structural_risk.to_dict(),
            "policy_assessment": self.policy_assessment.to_dict(),
            "blocking_reasons": [r.to_dict() for r in self.blocking_reasons],
            "evidence": [e.to_dict() for e in self.evidence],
            "issues": [i.to_dict() for i in self.issues],
            "confidence": self.confidence,
            "quality": _fmt_quality(self.quality),
            "provenance": _fmt_provenance(self.provenance),
            "reference_timestamp": _fmt_ts(self.reference_timestamp),
            "model_version": self.model_version,
            "calculation_version": self.calculation_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CentralRiskResult":
        return cls(
            status=CentralRiskStatus(data["status"]),
            candidate_id=data["candidate_id"],
            opportunity_id=data["opportunity_id"],
            strategy_id=data["strategy_id"],
            payoff_risk=PayoffRisk.from_dict(data["payoff_risk"]),
            greek_risk=GreekRisk.from_dict(data["greek_risk"]),
            scenario_risk=ScenarioRisk.from_dict(data["scenario_risk"]),
            structural_risk=StructuralRisk.from_dict(data["structural_risk"]),
            policy_assessment=PolicyAssessment.from_dict(data["policy_assessment"]),
            blocking_reasons=tuple(PolicyRuleResult.from_dict(r)
                                   for r in data.get("blocking_reasons", [])),
            evidence=tuple(RiskEvidence.from_dict(e) for e in data["evidence"]),
            issues=tuple(RiskIssue.from_dict(i) for i in data["issues"]),
            confidence=data["confidence"],
            quality=_quality_from_projection(data.get("quality")),
            provenance=_prov_from_dict(data.get("provenance")),
            reference_timestamp=datetime.fromisoformat(data["reference_timestamp"]),
            contract_version=data["version"],
            model_version=data.get("model_version"),
            calculation_version=data["calculation_version"],
        )
