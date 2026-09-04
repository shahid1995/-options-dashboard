# StrikeNova Day 33 — Central Risk Engine Design

**Status:** APPROVED FOR IMPLEMENTATION

## 1. Objective

Day 33 establishes StrikeNova's authoritative standalone strategy-risk boundary after the Day-32 Opportunity Gate.

The Day-33 boundary answers:

> **Given an eligible, evaluated Strategy Candidate, what is its standalone risk profile, and does it satisfy the applicable deterministic risk-policy requirements?**

It does not decide whether the user should trade, whether the portfolio can support the strategy, whether capital/margin is available, or whether an order may be executed.

The lifecycle remains:

`Observation → Signal → Setup → Opportunity → Strategy Candidate → Strategy Evaluation → Risk Check → User Decision → Execution`

## 2. Architectural Boundary

Day 28 owns Opportunity discovery.

Day 30 owns multi-factor strike ranking.

Day 31 owns deterministic Strategy Evaluation and consumes authoritative quantitative/scenario evidence.

Day 32 owns Strategy Candidate composition and the Opportunity Gate. An `ELIGIBLE` candidate is the required input boundary for Day 33.

Day 33 owns standalone strategy risk assessment and deterministic risk-policy evaluation.

Day 34 will own portfolio-level risk and concentration. Day 35 will own capital/margin intelligence. Day 36 will own the final risk gate before User Decision.

Day 33 must not duplicate authoritative payoff, Greek, GEX, IV, or scenario mathematics. It must reuse or consume the existing quantitative contracts/results established in earlier days.

## 3. Core Principles

- Risk evidence is authoritative; an opaque aggregate score is not.
- Risk metrics, risk score, confidence, quality, and policy decision are separate channels.
- Missing data remains missing and is never converted to zero, neutral, favorable, or safe evidence.
- Broker-provided values and StrikeNova model/calculated values remain distinguishable.
- Data quality and freshness remain explicit inputs to risk interpretation.
- Reference time is caller supplied; no wall clock is used by the pure engine.
- The engine is deterministic and explainable.
- Day 33 is broker-neutral and has no execution authority.
- Portfolio/account/capital/margin concerns remain outside the standalone risk boundary.

## 4. Inputs

The implementation should first inspect the repository for existing canonical risk/configuration contracts and reuse them where appropriate rather than creating duplicate types.

Conceptually the engine consumes:

- Day-32 `StrategyCandidate`;
- explicit caller-supplied reference timestamp;
- explicit `RiskPolicy` configuration/version;
- authoritative payoff evidence or existing strategy-payoff result;
- authoritative Greek evidence/results;
- authoritative Day-18 scenario/time-analysis evidence/results;
- relevant market/model context required by those calculations;
- quality, freshness and provenance metadata.

The engine does not fetch missing inputs.

## 5. Risk Dimensions

### 5.1 Payoff Risk

Where supported by authoritative strategy/payoff inputs, expose:

- maximum profit;
- maximum loss;
- breakeven points;
- bounded/unbounded loss;
- bounded/unbounded profit;
- payoff asymmetry;
- directional upside/downside exposure.

Undefined or unbounded loss must be represented explicitly, never as zero.

Payoff state uses the established assessment vocabulary:

`AVAILABLE | PARTIAL | UNAVAILABLE | INVALID`

### 5.2 Greek Risk

Aggregate strategy Greek exposures using authoritative quantitative semantics and explicit leg quantities/signs/multipliers where applicable:

- delta;
- gamma;
- theta;
- vega;
- rho where supported.

Missing components remain missing. Model/live distinctions must be preserved.

### 5.3 Scenario Risk

Day 33 consumes the existing Day-18 Scenario & Time Analysis outputs rather than reimplementing scenario mathematics.

The result may expose:

- supplied scenario identities;
- scenario P&L/loss;
- worst supplied scenario loss;
- time/expiry sensitivity;
- volatility-shock sensitivity;
- combined scenario warnings or partial states.

“Worst supplied scenario” must not be represented as theoretical absolute worst-case loss.

### 5.4 Structural Risk

Detect invalid or unsupported strategy structures, including malformed legs, missing required quantities, incompatible required inputs, unsupported payoff structures, or invalid authoritative inputs.

### 5.5 Data-Quality Risk

Risk interpretation must preserve the established quality framework. Freshness, completeness, validity, consistency, continuity and anomaly information are evidence channels, not silent coercions.

## 6. Risk Policy

Risk policy must be explicit, deterministic, versioned and serializable.

The implementation must inspect existing repository policy/configuration conventions before introducing fields. Candidate policy dimensions may include:

- maximum standalone loss;
- maximum permitted scenario loss;
- maximum strategy Greek exposures where a legitimate policy exists;
- whether unbounded loss is permitted;
- minimum required quality;
- maximum permissible data age/freshness;
- policy version.

No account-capital or margin threshold belongs in Day 33 merely because it appears useful; those are Day-35 concerns unless an existing canonical contract proves otherwise.

## 7. Result and Decision Semantics

Conceptual result:

```text
CentralRiskResult
├── status
├── strategy_identity
├── opportunity_id
├── risk_decision
├── payoff_risk
├── greek_risk
├── scenario_risk
├── structural_risk
├── policy_assessment
├── risk_score (optional, descriptive only)
├── evidence[]
├── confidence
├── quality
├── provenance
├── reference_timestamp
├── contract_version
├── model_version
├── calculation_version
└── issues[]
```

Result status:

- `PASS` — required risk evidence is sufficiently available and policy requirements pass;
- `BLOCKED` — risk is sufficiently known but an explicit risk-policy rule fails;
- `PARTIAL` — risk assessment is possible but required information is incomplete;
- `UNAVAILABLE` — risk cannot be meaningfully assessed from supplied inputs;
- `INVALID` — the candidate or authoritative inputs violate a domain invariant.

The exact enum names must follow existing repository conventions if a canonical risk vocabulary already exists.

## 8. Risk Score

A risk score, if retained, is descriptive only. It cannot authorize or override policy.

The implementation must not introduce an arbitrary weighted risk score without a documented domain justification. A result such as `risk_score=82, decision=BLOCKED` must remain valid.

## 9. Evidence and Explainability

Every material risk conclusion must be traceable to structured evidence.

Example:

```text
Decision: BLOCKED

Reasons:
- Maximum loss exceeds the configured policy limit.
- Worst supplied downside scenario exceeds the configured threshold.

Evidence:
- Payoff result and provenance
- Scenario result and provenance
- Risk policy version
```

A bare number without evidence is insufficient.

## 10. Provenance

Provenance must be preserved at the dimension/evidence level and at the result level where appropriate.

Day-30 factor provenance, Day-31 evaluation provenance, and Day-32 Opportunity provenance must not be flattened into a fabricated single source.

Risk calculations may add transformation/calculation provenance when genuinely produced by Day 33, using the repository's canonical provenance type.

## 11. Freshness and Reference Time

The caller supplies the reference timestamp. The pure engine must not call the system clock.

Freshness policy is explicit. Stale, future, missing, degraded and insufficient inputs retain their actual states and are handled according to policy rather than silently converted into usable values.

## 12. Context Equivalence

If the same canonical strategy and quantitative inputs are evaluated in `OPPORTUNITY`, `PAPER`, `BACKTEST`, or `RESEARCH` context, the risk mathematics and policy result must be equivalent. Context is descriptive metadata only unless an explicit policy contract states otherwise.

## 13. Boundaries to Day 34, Day 35 and Day 36

Day 33 does not calculate portfolio concentration, cross-strategy correlation, portfolio allocation, account exposure, portfolio VaR, or other cross-strategy measures. Those belong to Day 34.

Day 33 may expose standalone maximum loss and scenario loss, but it does not decide whether the account has enough capital or margin. Day 35 owns that boundary.

Day 33 does not provide final risk authorization for execution. Day 36 owns the final risk gate before User Decision.

Eligibility, risk PASS, and execution approval are separate concepts.

## 14. Domain Purity and Security

The core risk engine must not perform database, network, filesystem, broker, environment, randomness or wall-clock operations.

No broker credentials, order IDs, execution intents, fills, positions, or order-placement APIs are accepted as Day-33 domain inputs unless a future approved design explicitly changes this boundary.

Tenant/resource ownership remains an outer application concern; the pure engine receives already-authorized domain objects and must not bypass ownership boundaries.

## 15. Non-Goals

Day 33 explicitly excludes:

- portfolio risk;
- capital allocation;
- margin authorization;
- broker margin calls;
- order creation/submission;
- execution;
- user approval;
- position reconciliation;
- historical-data ingestion;
- backtesting/walk-forward engines;
- ML or AI risk prediction;
- frontend/API/database changes unless an approved repository convention makes one strictly necessary;
- duplicate payoff, Greek, GEX, IV or scenario mathematics.

## 16. TDD and Verification

TDD is mandatory: failing tests first, minimal implementation, focused pass, regression, static/purity review, scope review and evidence recording.

Focused coverage must include valid and invalid Day-32 candidates, missing/partial dimensions, bounded and unbounded payoff, Greek aggregation, scenario reuse, freshness/quality behavior, policy pass/violation/unknown states, provenance, serialization, deterministic repeated evaluation, context equivalence, missing-versus-zero, score/confidence/quality separation, no portfolio/capital/execution authority, and no I/O/wall-clock/randomness/broker dependency.

Tests must use genuine upstream Day-19 through Day-32 objects where practical, not fabricated `object.__new__` stand-ins that bypass validation.

## 17. Success Gate

Day 33 is PASS only when an eligible Day-32 Strategy Candidate can deterministically produce an explainable standalone risk assessment using authoritative quantitative/scenario evidence, with explicit policy semantics and correct handling of missing/incomplete/invalid/stale data; provenance, confidence and quality remain distinct; and no portfolio, capital/margin, user-approval or execution authority enters the implementation.

A PASS unlocks Day 34 — Portfolio Risk and Concentration Intelligence.
