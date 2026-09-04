"""StrikeNova Day 36 — Final Risk Gate (pure deterministic domain).

Sits between Day-35 Portfolio Intelligence and the User Decision boundary:

    eligible Day-32 StrategyCandidate
        + Day-33 CentralRiskResult
        + Day-35 PortfolioAnalyticsResult
        + explicit FinalRiskPolicy + caller-supplied reference timestamp
        -> evaluate_final_gate(...) -> FinalRiskGateResult

Boundaries (locked):
* ``PASS`` = permitted to proceed to the User Decision boundary ONLY --
  never execution/trade/broker approval, never an order or a fill.
* Day-33 central risk is consumed whole (its semantics are unchanged);
  Day-35 portfolio analytics are consumed whole with broker/model source
  separation preserved (the only arithmetic is a same-source delta
  projection, never a broker+model sum).
* No numeric limit is invented: ``None`` policy fields mean the rule is not
  configured.  Missing data stays missing; regime labels never manufacture
  direction; no wall clock, randomness, database, network, filesystem or
  broker access exists in the domain.
"""

from app.final_risk_gate.contracts import (
    FINAL_RISK_GATE_CALCULATION_VERSION,
    FINAL_RISK_GATE_CONTRACT_VERSION,
    FinalRiskGateDimension,
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
    final_gate_from_dict,
    final_gate_to_dict,
)
from app.final_risk_gate.gate import evaluate_final_gate

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
    "evaluate_final_gate",
    "final_gate_from_dict",
    "final_gate_to_dict",
]
