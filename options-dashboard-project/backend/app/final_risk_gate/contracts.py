"""Day 36 — Final Risk Gate contracts.

Pure, immutable, deterministic contracts for the final gate boundary that
sits between Day-35 Portfolio Intelligence and the User Decision boundary:

    eligible Day-32 StrategyCandidate
        + Day-33 CentralRiskResult
        + Day-35 PortfolioAnalyticsResult
        + explicit FinalRiskPolicy + caller-supplied reference timestamp
        -> evaluate_final_gate(...)
        -> FinalRiskGateResult

Semantics locked here
---------------------
* ``PASS`` means ONLY "this candidate is permitted to proceed to the User
  Decision boundary under the configured final risk gates".  It is NOT
  execution-approved, NOT a broker order, NOT a trade decision, NOT user
  approval, NOT a capital/margin decision.
* Day-33 Central Risk is consumed whole (its semantics are unchanged and
  never re-derived here); Day-33 BLOCKED / INVALID / UNAVAILABLE / PARTIAL
  map to the identical final-gate status -- incomplete evidence is never
  silently treated as safe.
* Day-35 Portfolio analytics are consumed whole.  The final gate performs no
  new Greek/GEX/scenario mathematics; the ONLY arithmetic it performs is a
  same-source delta projection (authoritative Day-35 portfolio per-source
  delta + authoritative Day-33 candidate delta), and it is produced only
  when BOTH sides share one Greek source -- broker and model evidence are
  never summed (Day-35 source separation is preserved).
* No numeric limit is invented: every numeric rule needs an explicit
  configured cap; ``None`` means that rule is NOT configured (absent, like
  the Day-33 ``RiskPolicy`` ``None`` fields).
* Missing data stays missing (never zero / neutral / favourable).  A regime
  label never manufactures directional evidence; unknown regime stays
  unknown.
* No wall clock, randomness, IO, broker, order, execution or user-approval
  vocabulary exists anywhere in this package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.central_risk.contracts import CentralRiskStatus
from app.market_data.contracts import Provenance

#: Day-36 contract version (independent of Day-33/35 versions).
FINAL_RISK_GATE_CONTRACT_VERSION = "1.0.0"
#: Deterministic engine calculation version for the final gate evaluation.
FINAL_RISK_GATE_CALCULATION_VERSION = "final_risk_gate.v1"


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class FinalRiskStatus(str, Enum):
    """Deterministic final-gate verdict.

    * ``PASS`` — structure is valid, Day-33 central risk PASSES, and every
      CONFIGURED final-gate rule passes.  PASS = permitted to proceed to the
      User Decision boundary ONLY (never execution approval).
    * ``BLOCKED`` — a verified violation exists (Day-33 BLOCKED or a
      configured final-gate rule fails); evidence stays visible.
    * ``PARTIAL`` — the final assessment is possible but required evidence is
      incomplete (Day-33 PARTIAL or an unverifiable configured rule); never
      a false PASS.
    * ``UNAVAILABLE`` — the final assessment cannot be meaningfully made
      from the supplied inputs (Day-33 UNAVAILABLE or no portfolio).
    * ``INVALID`` — structural/identity/tenant invariants fail or Day-33 is
      INVALID.
    """

    PASS = "PASS"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class FinalRiskGateDimension(str, Enum):
    """The seven Day-36 gate dimensions (A-G of the approved design)."""

    STRUCTURAL = "STRUCTURAL"
    CENTRAL_RISK = "CENTRAL_RISK"
    PORTFOLIO_IMPACT = "PORTFOLIO_IMPACT"
    CONCENTRATION = "CONCENTRATION"
    DIRECTIONAL = "DIRECTIONAL"
    REGIME = "REGIME"
    DATA_QUALITY = "DATA_QUALITY"


class FinalRiskRuleCode(str, Enum):
    """Explicit, machine-readable final-gate rule identifiers.

    ``CENTRAL_RISK_PASS`` is always evaluated.  The numeric rules are
    evaluated ONLY when their cap is configured (``None`` = not configured).
    """

    CENTRAL_RISK_PASS = "CENTRAL_RISK_PASS"
    MAX_PORTFOLIO_DELTA = "MAX_PORTFOLIO_DELTA"
    MAX_PROJECTED_DELTA = "MAX_PROJECTED_DELTA"
    MAX_CONCENTRATION_SHARE = "MAX_CONCENTRATION_SHARE"


class FinalRiskIssueCode(str, Enum):
    """Structured issue categories (evidence-backed, never opaque)."""

    STRUCTURAL_INVALID = "STRUCTURAL_INVALID"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    PORTFOLIO_REQUIRED = "PORTFOLIO_REQUIRED"
    INVALID_REFERENCE_TIMESTAMP = "INVALID_REFERENCE_TIMESTAMP"
    DAY33_INCOMPLETE = "DAY33_INCOMPLETE"
    DAY33_UNAVAILABLE = "DAY33_UNAVAILABLE"
    REGIME_UNKNOWN = "REGIME_UNKNOWN"
    INCOMPLETE_PORTFOLIO_EVIDENCE = "INCOMPLETE_PORTFOLIO_EVIDENCE"
    UNVERIFIABLE_RULE = "UNVERIFIABLE_RULE"
    MISSING_CANDIDATE_QUALITY = "MISSING_CANDIDATE_QUALITY"


# ---------------------------------------------------------------------------
# Validation helpers
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


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None \
        and ts.tzinfo.utcoffset(ts) is not None


def _fmt_ts(ts: datetime) -> str | None:
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


# ---------------------------------------------------------------------------
# Final risk policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinalRiskPolicy:
    """Explicit final-gate policy.

    ``None`` limit fields mean that particular rule is NOT configured (an
    explicit configuration choice -- never a zero limit and never an
    invented threshold).  The final gate never blocks on an unconfigured
    rule.
    """

    policy_version: str
    maximum_portfolio_delta: float | None = None
    maximum_projected_delta: float | None = None
    maximum_concentration_share: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.policy_version, "policy_version")
        for name in ("maximum_portfolio_delta", "maximum_projected_delta"):
            value = getattr(self, name)
            _require_finite_or_none(value, name)
            if value is not None and value < 0.0:
                raise ValueError(f"{name} must be non-negative or None")
        share = self.maximum_concentration_share
        if share is not None:
            _require_finite_or_none(share, "maximum_concentration_share")
            if not (0.0 < share <= 1.0):
                raise ValueError(
                    "maximum_concentration_share must be within (0, 1] "
                    "or None")

    def to_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "maximum_portfolio_delta": self.maximum_portfolio_delta,
            "maximum_projected_delta": self.maximum_projected_delta,
            "maximum_concentration_share": self.maximum_concentration_share,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FinalRiskPolicy":
        return cls(
            policy_version=data["policy_version"],
            maximum_portfolio_delta=data.get("maximum_portfolio_delta"),
            maximum_projected_delta=data.get("maximum_projected_delta"),
            maximum_concentration_share=data.get(
                "maximum_concentration_share"),
        )


# ---------------------------------------------------------------------------
# Rule / issue / evidence rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateRuleResult:
    """One explicit final-gate rule outcome.

    ``passed`` is True (satisfied), False (verified violation) or None (not
    verifiable because required evidence is missing/unavailable).  ``limit``
    / ``observed`` carry the numeric magnitudes for the configured rules.
    """

    rule: FinalRiskRuleCode
    passed: bool | None
    message: str
    limit: float | None = None
    observed: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule, FinalRiskRuleCode):
            raise ValueError("rule must be a FinalRiskRuleCode")
        if self.passed is not None and not isinstance(self.passed, bool):
            raise ValueError("passed must be bool or None")
        _require_text(self.message, "message")
        _require_finite_or_none(self.limit, "limit")
        _require_finite_or_none(self.observed, "observed")

    def to_dict(self) -> dict:
        return {"rule": self.rule.value, "passed": self.passed,
                "message": self.message, "limit": self.limit,
                "observed": self.observed}

    @classmethod
    def from_dict(cls, data: dict) -> "GateRuleResult":
        return cls(rule=FinalRiskRuleCode(data["rule"]),
                   passed=data["passed"], message=data["message"],
                   limit=data.get("limit"), observed=data.get("observed"))


@dataclass(frozen=True)
class PolicyGateAssessment:
    """The evaluated final-gate policy: every evaluated rule with its
    outcome."""

    policy_version: str
    rules: tuple[GateRuleResult, ...]

    def __post_init__(self) -> None:
        _require_text(self.policy_version, "policy_version")
        if not isinstance(self.rules, tuple) or not all(
                isinstance(r, GateRuleResult) for r in self.rules):
            raise ValueError("rules must be a tuple of GateRuleResult")

    def to_dict(self) -> dict:
        return {"policy_version": self.policy_version,
                "rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyGateAssessment":
        return cls(policy_version=data["policy_version"],
                   rules=tuple(GateRuleResult.from_dict(r)
                               for r in data["rules"]))


@dataclass(frozen=True)
class GateEvidence:
    """One structured evidence row backing a material final-gate conclusion.

    ``kind`` uses stable labels (STRUCTURAL / DAY33 / PORTFOLIO / GREEKS /
    CONCENTRATION / DIRECTIONAL / REGIME / QUALITY / POLICY).  ``provenance``
    preserves the canonical Day-9 provenance of the underlying source when
    one exists (never invented).
    """

    kind: str
    source: str
    note: str
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        _require_text(self.source, "source")
        _require_text(self.note, "note")
        if self.provenance is not None and not isinstance(self.provenance,
                                                          Provenance):
            raise ValueError("provenance must be a Provenance or None")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "note": self.note,
                "provenance": _fmt_provenance(self.provenance)}

    @classmethod
    def from_dict(cls, data: dict) -> "GateEvidence":
        return cls(kind=data["kind"], source=data["source"], note=data["note"],
                   provenance=_prov_from_dict(data.get("provenance")))


@dataclass(frozen=True)
class GateIssue:
    """A structured issue naming why the gate could not fully pass."""

    code: FinalRiskIssueCode
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, FinalRiskIssueCode):
            raise ValueError("code must be a FinalRiskIssueCode")
        _require_text(self.message, "message")

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> "GateIssue":
        return cls(code=FinalRiskIssueCode(data["code"]),
                   message=data["message"])


# ---------------------------------------------------------------------------
# Dimension assessments and portfolio impact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDimensionAssessment:
    """Outcome of one final-gate dimension.

    Each dimension carries its own deterministic status plus an explicit
    note.  Status reuse of :class:`FinalRiskStatus` is intentional -- every
    dimension is itself a small gate decision; ``PASS`` never leaks outside
    the overall result's "proceed to User Decision" meaning.
    """

    dimension: FinalRiskGateDimension
    status: FinalRiskStatus
    note: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, FinalRiskGateDimension):
            raise ValueError("dimension must be a FinalRiskGateDimension")
        if not isinstance(self.status, FinalRiskStatus):
            raise ValueError("status must be a FinalRiskStatus")
        _require_text(self.note, "note")

    def to_dict(self) -> dict:
        return {"dimension": self.dimension.value, "status": self.status.value,
                "note": self.note}

    @classmethod
    def from_dict(cls, data: dict) -> "GateDimensionAssessment":
        return cls(dimension=FinalRiskGateDimension(data["dimension"]),
                   status=FinalRiskStatus(data["status"]),
                   note=data["note"])


@dataclass(frozen=True)
class GreekDeltaRead:
    """Source-separated delta read for the portfolio-impact dimension.

    ``current_delta`` is the authoritative Day-35 portfolio per-source delta;
    ``candidate_delta`` is the authoritative Day-33 candidate delta.  The
    projected delta is formed ONLY when the candidate and the portfolio share
    ONE Greek source (``current_delta`` and ``candidate_delta`` both present
    on this row); broker and model evidence are never summed, so mixed-source
    inputs yield ``None`` projected values (never a fabricated total).
    """

    source: str
    current_delta: float | None
    candidate_delta: float | None
    projected_delta: float | None

    def __post_init__(self) -> None:
        _require_text(self.source, "source")
        for name in ("current_delta", "candidate_delta", "projected_delta"):
            _require_finite_or_none(getattr(self, name), name)

    def to_dict(self) -> dict:
        return {"source": self.source, "current_delta": self.current_delta,
                "candidate_delta": self.candidate_delta,
                "projected_delta": self.projected_delta}

    @classmethod
    def from_dict(cls, data: dict) -> "GreekDeltaRead":
        return cls(source=data["source"],
                   current_delta=data.get("current_delta"),
                   candidate_delta=data.get("candidate_delta"),
                   projected_delta=data.get("projected_delta"))


@dataclass(frozen=True)
class PortfolioImpact:
    """Descriptive portfolio-impact context consumed from Day-35 analytics.

    Read-only context: no new mathematics is performed beyond the documented
    same-source delta projection.  Missing scenario P/L stays missing and a
    regime label is echoed only when actually known.
    """

    position_count: int
    delta_reads: tuple[GreekDeltaRead, ...]
    day33_worst_scenario_pnl: float | None
    portfolio_scenario_state: str | None
    regime_label: str | None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.position_count, int) or self.position_count < 0:
            raise ValueError("position_count must be a non-negative int")
        if not isinstance(self.delta_reads, tuple) or not all(
                isinstance(r, GreekDeltaRead) for r in self.delta_reads):
            raise ValueError("delta_reads must be a tuple of GreekDeltaRead")
        _require_finite_or_none(self.day33_worst_scenario_pnl,
                                "day33_worst_scenario_pnl")
        if not isinstance(self.notes, tuple) or not all(
                isinstance(n, str) for n in self.notes):
            raise ValueError("notes must be a tuple of strings")

    def to_dict(self) -> dict:
        return {
            "position_count": self.position_count,
            "delta_reads": [r.to_dict() for r in self.delta_reads],
            "day33_worst_scenario_pnl": self.day33_worst_scenario_pnl,
            "portfolio_scenario_state": self.portfolio_scenario_state,
            "regime_label": self.regime_label,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PortfolioImpact":
        return cls(
            position_count=data["position_count"],
            delta_reads=tuple(GreekDeltaRead.from_dict(r)
                              for r in data["delta_reads"]),
            day33_worst_scenario_pnl=data.get("day33_worst_scenario_pnl"),
            portfolio_scenario_state=data.get("portfolio_scenario_state"),
            regime_label=data.get("regime_label"),
            notes=tuple(data.get("notes", [])),
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinalRiskGateResult:
    """Deterministic final-gate verdict for one strategy candidate.

    ``dimensions`` carries the seven Day-36 gate assessments (A-G);
    ``policy`` carries every evaluated rule; ``blocking_reasons`` carries
    exactly the failed rules on BLOCKED (empty otherwise).  ``portfolio`` is
    the source-separated impact context consumed from Day-35.
    """

    status: FinalRiskStatus
    candidate_id: str
    strategy_id: str
    opportunity_id: str
    tenant_id: str | None
    central_risk_status: CentralRiskStatus
    dimensions: tuple[GateDimensionAssessment, ...]
    policy: PolicyGateAssessment
    blocking_reasons: tuple[GateRuleResult, ...]
    evidence: tuple[GateEvidence, ...]
    issues: tuple[GateIssue, ...]
    portfolio: PortfolioImpact
    reference_timestamp: datetime
    contract_version: str = FINAL_RISK_GATE_CONTRACT_VERSION
    calculation_version: str = FINAL_RISK_GATE_CALCULATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, FinalRiskStatus):
            raise ValueError("status must be a FinalRiskStatus")
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.strategy_id, "strategy_id")
        _require_text(self.opportunity_id, "opportunity_id")
        if not isinstance(self.central_risk_status, CentralRiskStatus):
            raise ValueError("central_risk_status must be a CentralRiskStatus")
        if not isinstance(self.dimensions, tuple) or not all(
                isinstance(d, GateDimensionAssessment)
                for d in self.dimensions):
            raise ValueError("dimensions must hold GateDimensionAssessment")
        if not isinstance(self.policy, PolicyGateAssessment):
            raise ValueError("policy must be a PolicyGateAssessment")
        if not isinstance(self.blocking_reasons, tuple) or not all(
                isinstance(r, GateRuleResult)
                for r in self.blocking_reasons):
            raise ValueError("blocking_reasons must hold GateRuleResult")
        if not isinstance(self.evidence, tuple) or not all(
                isinstance(e, GateEvidence) for e in self.evidence):
            raise ValueError("evidence must hold GateEvidence")
        if not isinstance(self.issues, tuple) or not all(
                isinstance(i, GateIssue) for i in self.issues):
            raise ValueError("issues must hold GateIssue")
        if not isinstance(self.portfolio, PortfolioImpact):
            raise ValueError("portfolio must be a PortfolioImpact")
        if not _is_aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely "
                             "timezone-aware")
        _require_text(self.contract_version, "contract_version")
        _require_text(self.calculation_version, "calculation_version")
        # Semantic consistency: BLOCKED implies at least one failed rule.
        if self.status is FinalRiskStatus.BLOCKED and not self.blocking_reasons:
            raise ValueError("BLOCKED requires at least one failed rule")
        if self.status is not FinalRiskStatus.BLOCKED and self.blocking_reasons:
            raise ValueError("blocking_reasons are only present on BLOCKED")

    def to_dict(self) -> dict:
        return {
            "contract": "final_risk_gate.result",
            "version": self.contract_version,
            "status": self.status.value,
            "candidate_id": self.candidate_id,
            "strategy_id": self.strategy_id,
            "opportunity_id": self.opportunity_id,
            "tenant_id": self.tenant_id,
            "central_risk_status": self.central_risk_status.value,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "policy": self.policy.to_dict(),
            "blocking_reasons": [r.to_dict() for r in self.blocking_reasons],
            "evidence": [e.to_dict() for e in self.evidence],
            "issues": [i.to_dict() for i in self.issues],
            "portfolio": self.portfolio.to_dict(),
            "reference_timestamp": _fmt_ts(self.reference_timestamp),
            "calculation_version": self.calculation_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FinalRiskGateResult":
        return cls(
            status=FinalRiskStatus(data["status"]),
            candidate_id=data["candidate_id"],
            strategy_id=data["strategy_id"],
            opportunity_id=data["opportunity_id"],
            tenant_id=data.get("tenant_id"),
            central_risk_status=CentralRiskStatus(
                data["central_risk_status"]),
            dimensions=tuple(GateDimensionAssessment.from_dict(d)
                             for d in data["dimensions"]),
            policy=PolicyGateAssessment.from_dict(data["policy"]),
            blocking_reasons=tuple(GateRuleResult.from_dict(r)
                                   for r in data.get("blocking_reasons", [])),
            evidence=tuple(GateEvidence.from_dict(e) for e in data["evidence"]),
            issues=tuple(GateIssue.from_dict(i) for i in data["issues"]),
            portfolio=PortfolioImpact.from_dict(data["portfolio"]),
            reference_timestamp=datetime.fromisoformat(
                data["reference_timestamp"]),
            contract_version=data["version"],
            calculation_version=data["calculation_version"],
        )


def final_gate_to_dict(result: FinalRiskGateResult) -> dict:
    """Deterministic JSON-safe dict for the full final-gate result."""
    if not isinstance(result, FinalRiskGateResult):
        raise TypeError("final_gate_to_dict requires a FinalRiskGateResult")
    return result.to_dict()


def final_gate_from_dict(data: dict) -> FinalRiskGateResult:
    """Rebuild the full final-gate result from ``final_gate_to_dict``."""
    if not isinstance(data, dict):
        raise TypeError("final_gate_from_dict requires a dict")
    return FinalRiskGateResult.from_dict(data)


__all__ = [
    "FINAL_RISK_GATE_CALCULATION_VERSION",
    "FINAL_RISK_GATE_CONTRACT_VERSION",
    "FinalRiskGateDimension",
    "FinalRiskGateResult",
    "FinalRiskIssueCode",
    "FinalRiskPolicy",
    "FinalRiskRuleCode",
    "FinalRiskStatus",
    "GateDimensionAssessment",
    "GateEvidence",
    "GateIssue",
    "GateRuleResult",
    "GreekDeltaRead",
    "PolicyGateAssessment",
    "PortfolioImpact",
    "final_gate_from_dict",
    "final_gate_to_dict",
]
