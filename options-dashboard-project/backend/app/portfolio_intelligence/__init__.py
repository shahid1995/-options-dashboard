"""StrikeNova Day 35 — Portfolio Intelligence (pure analytics domain).

A deterministic, broker-neutral analytics layer that CONSUMES authoritative
position truth (paper ``Position`` net rows for paper portfolios, broker
observed rows for broker portfolios) and shared quantitative/intelligence
services, and produces multidimensional portfolio analytics:

    exposures / Greeks / portfolio-owned GEX / scenario sensitivity /
    concentration / directional / regime-aware risk views
        -> PortfolioAnalyticsResult

Boundaries (locked):
* It is an analytical consumer — never a new source of position/broker/
  account truth, never a second quant engine, never a risk-policy decision.
* Missing data stays missing; explicit AVAILABLE/PARTIAL/UNAVAILABLE/INVALID
  states are preserved.
* Provenance (Day-9) and quality (Day-9 vocabulary) are preserved; the
  Day-23 ``MarketRegime`` is consumed whole; no wall clock, randomness,
  database, network, filesystem or broker access exists in the domain.
"""

from app.portfolio_intelligence.analytics import analyze_portfolio
from app.portfolio_intelligence.contracts import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    GEX_METHOD_VERSION,
    GREEKS_SOURCE_BROKER,
    GREEKS_SOURCE_MODEL,
    MODEL_VERSION,
    ConcentrationSlice,
    ConcentrationView,
    DeltaPosture,
    DirectionalView,
    EvidenceState,
    ExposureSlice,
    GexSourceTotal,
    GreekContribution,
    GreekInput,
    GreekSourceTotal,
    LargestAbsoluteExposure,
    PortfolioAnalyticsResult,
    PortfolioExposure,
    PortfolioGexExposure,
    PortfolioGreekExposure,
    PortfolioIssue,
    PortfolioIssueCode,
    PortfolioPosition,
    PortfolioScenarioSensitivity,
    PortfolioStatus,
    PositionSource,
    RegimeRiskView,
    ScenarioRow,
    portfolio_result_from_dict,
    portfolio_result_to_dict,
)
from app.portfolio_intelligence.normalization import (
    broker_position_to_input,
    paper_position_to_input,
)

__all__ = [
    "CALCULATION_VERSION",
    "CONTRACT_VERSION",
    "GEX_METHOD_VERSION",
    "GREEKS_SOURCE_BROKER",
    "GREEKS_SOURCE_MODEL",
    "MODEL_VERSION",
    "ConcentrationSlice",
    "ConcentrationView",
    "DeltaPosture",
    "DirectionalView",
    "EvidenceState",
    "ExposureSlice",
    "GexSourceTotal",
    "GreekContribution",
    "GreekInput",
    "GreekSourceTotal",
    "LargestAbsoluteExposure",
    "PortfolioAnalyticsResult",
    "PortfolioExposure",
    "PortfolioGexExposure",
    "PortfolioGreekExposure",
    "PortfolioIssue",
    "PortfolioIssueCode",
    "PortfolioPosition",
    "PortfolioScenarioSensitivity",
    "PortfolioStatus",
    "PositionSource",
    "RegimeRiskView",
    "ScenarioRow",
    "analyze_portfolio",
    "broker_position_to_input",
    "paper_position_to_input",
    "portfolio_result_from_dict",
    "portfolio_result_to_dict",
]
