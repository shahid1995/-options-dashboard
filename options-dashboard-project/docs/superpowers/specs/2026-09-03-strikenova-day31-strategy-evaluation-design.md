# StrikeNova Day 31 — Strategy Evaluation Engine Design

**Date:** 2026-09-03  
**Status:** DESIGN — approved by product owner; implementation authorization is a separate gate  
**Repository:** `shahid1995/-options-dashboard`  
**Branch:** `feat/strikenova-day1-security`  
**Depends on:** Days 14–30 approved, especially Day 18 Scenario & Time Analysis, Day 19 Intelligence Contract, Day 28 Opportunity, Day 30 Best-Strike Ranking

## 1. Objective

Build a deterministic, broker-neutral **Strategy Evaluation Engine** that evaluates an already-defined strategy candidate against supplied market/context evidence.

The evaluator answers:

> Given this strategy and this market/context, how does the strategy behave and how suitable is it?

It does **not** answer whether an order should be placed. The hierarchy remains:

`Observation → Signal → Setup → Opportunity → Strategy Candidate → Strategy Evaluation → Risk Check → User Decision → Execution`

Day 31 must unify strategy evaluation semantics so the same evaluation logic can be consumed by opportunity, paper, backtest, and research contexts without context-specific financial math.

## 2. Architectural principles

1. **Reuse existing quantitative contracts.** Do not recreate payoff, Greeks, scenario, or risk mathematics when an authoritative contract already exists.
2. **Deterministic foundation.** Same canonical inputs and model versions produce the same serialized result.
3. **Evidence before conclusion.** Every material assessment identifies the evidence used and preserves provenance where available.
4. **Missing ≠ zero.** Missing data is unavailable/partial, never a fabricated favorable or unfavorable value.
5. **Score ≠ confidence ≠ quality.** A suitability/evaluation score must never silently overwrite caller confidence or data quality.
6. **Broker-neutral.** Broker adapters are upstream data providers only; no broker concepts or credentials enter this domain.
7. **No execution authority.** Evaluation cannot create orders, execution intents, positions, or risk authorization.
8. **Pure domain boundary.** No database, network, filesystem, broker, wall-clock, randomness, or environment reads inside the deterministic evaluator.

## 3. Inputs

The evaluator receives explicit typed inputs representing:

- strategy identity and legs;
- evaluation context (`OPPORTUNITY`, `PAPER`, `BACKTEST`, `RESEARCH`);
- valuation/reference timestamp supplied by caller;
- current market observations required by the evaluation;
- payoff/risk calculation inputs;
- Greeks/model inputs;
- scenario inputs/results using the existing scenario contracts where available;
- authoritative market regime when available;
- liquidity/spread observations when available;
- risk assessment inputs using existing/shared risk contracts;
- historical evidence when actually available;
- caller-supplied confidence/quality/provenance metadata;
- model/calculation contract versions where applicable.

The engine must not obtain missing inputs itself.

### Context semantics

Evaluation context identifies **where the same evaluator is being consumed**. It must not alter the underlying financial calculations. If identical canonical strategy/market inputs are supplied, changing context alone must not change the deterministic quantitative outputs.

## 4. Evaluation dimensions

### 4.1 Payoff

Reuse the authoritative strategy payoff/risk calculation. Evaluate and expose, where defined:

- net debit/credit;
- premium outlay where applicable;
- maximum profit/loss and unlimited-tail classification;
- breakevens;
- payoff profile/curve when supplied by the shared contract.

Same-expiry theoretical results remain authoritative; mixed-expiry approximation must remain explicitly marked as approximate rather than being presented as exact.

Day 31 must not reimplement the payoff engine.

### 4.2 Greeks

Consume authoritative model/live Greek inputs or shared Greek contracts. Preserve the distinction between broker/model values where the upstream contract provides it.

Strategy-level Greek aggregation must use explicit leg quantity, action/sign and multiplier semantics. Missing Greek components remain missing; they are not replaced with zero.

At minimum the result may expose Delta, Gamma, Theta and Vega assessments plus the underlying evidence/source for each assessment.

### 4.3 Scenarios and time analysis

Reuse the existing Scenario & Time Analysis domain. Day 31 may orchestrate supplied scenario calculations and summarize their results, but must not duplicate the scenario pricing mathematics.

Scenario outputs should preserve:

- scenario identity/input;
- resulting P/L or model-value effect;
- warnings/partial state;
- reference timestamp/model version where available.

### 4.4 Regime compatibility

Consume the authoritative market-regime contract when supplied. The evaluator may assess whether the strategy's expected behavior is compatible, conflicted, or not assessable against the supplied regime.

A regime label alone must never fabricate directional evidence. Missing regime remains missing.

### 4.5 Liquidity

Evaluate supplied liquidity/spread observations for the strategy legs. Do not infer liquidity from unrelated labels or from absence of data.

Potential evidence includes:

- bid/ask spread quality;
- tradability/liquidity score supplied upstream;
- per-leg completeness;
- degraded/unavailable state.

### 4.6 Risk

Risk is an **evaluation dimension/input**, not Day-31 authorization.

Day 31 may consume existing payoff/risk metrics and shared risk contracts. It must not become the central portfolio risk engine and must not authorize execution.

Risk findings must distinguish:

- measured/modelled risk;
- unavailable risk information;
- structural unboundedness;
- downstream authorization, which is explicitly out of scope.

### 4.7 Historical behavior

Historical behavior is evidence only when actual point-in-time historical inputs are supplied. Day 31 must never invent a historical score from current data.

If historical evidence is unavailable, the historical assessment is explicitly unavailable/partial and the overall result records the limitation.

Day 31 does not implement the backtesting engine, data ingestion pipeline, walk-forward validation, or ML.

## 5. Result contract

Proposed domain package:

`backend/app/strategy_evaluation/`

with focused contracts and deterministic evaluation logic.

Conceptual result:

```text
StrategyEvaluationResult
├── status
├── strategy identity
├── evaluation_context
├── evaluation_score / suitability assessment
├── payoff_assessment
├── greek_assessment
├── scenario_assessment
├── regime_assessment
├── liquidity_assessment
├── risk_assessment
├── historical_assessment
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

The exact field names/types must follow existing repository conventions after implementation inspection; this conceptual contract is the boundary, not permission to invent parallel versions of established contracts.

## 6. Assessment semantics

Every dimension has an explicit state such as:

- `AVAILABLE` — sufficiently complete and valid;
- `PARTIAL` — some required evidence is absent/degraded but a bounded assessment is possible;
- `UNAVAILABLE` — required evidence is absent or invalid;
- `INVALID` — supplied contract/input is invalid.

No dimension may silently convert `UNAVAILABLE` to zero.

An overall result must not claim `SUCCESS` when required evaluation dimensions are unavailable if the requested evaluation explicitly requires them. The result must identify which dimensions prevented completeness.

## 7. Suitability score, confidence and quality

These are separate channels:

- **Evaluation/suitability score:** deterministic assessment of the supplied strategy against the requested evaluation objective.
- **Confidence:** confidence in the evaluation based on evidence completeness/consistency and caller/model metadata; it is not the suitability score.
- **Quality:** upstream data-quality state/result; it is not a strategy score.

No arbitrary weighting model should be introduced merely to create one opaque number. Component assessments and evidence remain inspectable. If an overall score is used, its formula and required components must be explicit, deterministic, bounded, and documented.

## 8. Evidence and provenance

Evidence must be structured rather than generated prose.

Every material assessment should be traceable to its source. Where a factor/dimension has its own source, preserve factor-level provenance using the canonical Day-9 `Provenance` contract. Opportunity provenance, if the strategy originated from Day 28, remains separately preserved.

The intended lineage is:

`market/quant source → evaluation input → dimension assessment → strategy evaluation → explanation/evidence`

Missing provenance remains `None`; it is never synthesized from an unrelated Opportunity provenance.

## 9. Determinism and purity

The evaluator must:

- use caller-supplied reference time only;
- avoid `datetime.now()`/`utcnow()` and equivalent wall-clock reads;
- avoid randomness/UUID generation for calculation identity;
- avoid network/DB/filesystem calls;
- avoid broker imports;
- avoid environment-dependent branching;
- use stable ordering for collections;
- serialize deterministically;
- preserve canonical numeric semantics and finite-value validation.

## 10. Context-equivalence invariant

For the same strategy, canonical market inputs, scenario inputs, model versions, and reference timestamp:

`evaluate(context=OPPORTUNITY)`
`evaluate(context=PAPER)`
`evaluate(context=BACKTEST)`
`evaluate(context=RESEARCH)`

must produce equivalent quantitative assessments. Context may be echoed as metadata, but it must not alter the financial result.

## 11. Explicit non-goals

Day 31 does **not** implement:

- order creation/submission;
- execution intent;
- broker gateway/adapters;
- user approval;
- central portfolio risk authorization;
- position mutation;
- database persistence/migrations;
- API endpoints;
- frontend UI;
- historical-data ingestion;
- backtesting engine;
- walk-forward validation;
- ML/model training;
- Day 32 strategy lifecycle;
- Day 33 central risk engine.

## 12. TDD requirements

Before implementation, tests must establish the contract and fail against the absent/new behavior. Minimum coverage:

1. contract validation and finite numeric rules;
2. context validation;
3. payoff reuse and exact-vs-approximate semantics;
4. Greek aggregation and missing values;
5. scenario reuse and warning propagation;
6. regime compatibility and missing-regime behavior;
7. liquidity assessment;
8. risk assessment without authorization;
9. historical available/unavailable semantics;
10. evidence and factor-level provenance propagation;
11. confidence/quality separation;
12. deterministic ordering and serialization;
13. context-equivalence;
14. purity/no-I/O boundary;
15. no execution/order side effects.

## 13. Gate

Day 31 passes only when:

1. the same strategy evaluates consistently across opportunity/paper/backtest contexts;
2. payoff, Greeks, scenarios, regime, liquidity, risk and historical evidence are represented without duplicated authoritative math;
3. missing inputs remain explicitly missing/partial/unavailable;
4. evidence and provenance survive the complete result path;
5. evaluation score, confidence and quality remain distinct;
6. the result is deterministic and serializable;
7. no execution/risk authorization behavior exists;
8. focused and regression tests pass with fresh evidence;
9. static/purity/security checks pass;
10. scope contains no Day-32+ implementation.

**Implementation remains separately gated after this design.**
