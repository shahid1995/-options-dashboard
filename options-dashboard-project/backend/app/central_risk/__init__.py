"""Day 33 — Central Risk Engine domain.

Deterministic standalone strategy-risk assessment for an eligible Day-32
StrategyCandidate against an explicit RiskPolicy.  PASS here means the
standalone risk-policy requirements passed -- never trade / portfolio /
capital / margin / user / execution approval.
"""

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
from app.central_risk.engine import assess_candidate_risk

__all__ = [
    "CENTRAL_RISK_CALCULATION_VERSION",
    "CENTRAL_RISK_CONTRACT_VERSION",
    "CentralRiskIssueCode",
    "CentralRiskResult",
    "CentralRiskStatus",
    "GreekRisk",
    "PayoffRisk",
    "PolicyAssessment",
    "PolicyRuleCode",
    "PolicyRuleResult",
    "RiskEvidence",
    "RiskIssue",
    "RiskPolicy",
    "ScenarioRisk",
    "StructuralRisk",
    "assess_candidate_risk",
]
