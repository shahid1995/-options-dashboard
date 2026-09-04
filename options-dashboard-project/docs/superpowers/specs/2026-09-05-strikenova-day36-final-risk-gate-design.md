# StrikeNova Day 36 — Final Risk Gate Design

**Version:** 1.0
**Date:** 2026-09-05
**Status:** Approved for implementation

## 1. Objective

Build the final deterministic risk-gating boundary between evaluated strategy candidates and the user-decision/execution boundary.

Day 36 answers: **Is this strategy candidate permitted to proceed to User Decision under the configured final risk gates?**

It does not answer whether the user should trade, place an order, approve execution, or whether a broker will accept an order.

## 2. Architectural Boundary

```text
Opportunity
  -> Strategy Candidate
  -> Strategy Evaluation
  -> Opportunity Gate
  -> Day 33 Central Risk
  -> Day 35 Portfolio Intelligence
  -> Day 36 Final Risk Gate
  -> User Decision
  -> Execution
```

Day 36 consumes the authoritative outputs of Days 32, 33 and 35. It is a gate/orchestration boundary, not a replacement for any upstream domain.

## 3. Responsibilities

The gate evaluates:

1. Structural eligibility of the Strategy Candidate.
2. Day 33 Central Risk result and evidence.
3. Incremental portfolio impact of the candidate where deterministically computable.
4. Concentration exposure constraints.
5. Directional exposure constraints.
6. Regime-aware constraints using the authoritative Day 23 regime.
7. Data-quality/freshness/completeness requirements.
8. Explicit caller-supplied/versioned policy thresholds.

The gate must preserve the distinction between metrics, analytics, confidence, quality and policy decisions.

## 4. Decision Semantics

The result is immutable and serializable. Recommended statuses:

- `PASS` — permitted to proceed to User Decision.
- `BLOCKED` — an explicit verified gate violation exists.
- `PARTIAL` — required evidence is incomplete but no verified blocking violation exists.
- `UNAVAILABLE` — required inputs are unavailable.
- `INVALID` — inputs or contracts are invalid.

`PASS` **never means execution-approved**. User approval remains a separate boundary.

No opaque aggregate risk score is required or permitted merely to produce a final decision.

## 5. Required Inputs

### Strategy Candidate / Day 32

- candidate identity
- opportunity identity
- strategy identity/template
- legs and selected strikes
- evaluation reference
- expected behavior
- invalidation conditions
- quality
- provenance
- reference timestamp

### Day 33 Central Risk

- RiskAssessment
- risk metrics
- policy decision/status
- policy version
- evidence
- quality/provenance

Day 36 must not duplicate or reinterpret Day 33 policy semantics.

### Day 35 Portfolio Intelligence

- normalized portfolio state
- portfolio exposures
- source-separated Greeks where applicable
- portfolio GEX
- scenario sensitivities
- concentration view
- directional view
- regime-aware view
- quality/provenance

### Caller Context

- explicit reference timestamp
- account/portfolio context
- candidate context
- explicit final-gate policy/configuration

No wall-clock reads are allowed.

## 6. Portfolio Impact

Where required inputs are available, Day 36 may derive deterministic incremental impact of adding the already-defined candidate to the existing portfolio analytics.

This must reuse existing authoritative quant/portfolio services. Day 36 must not introduce new Greek, GEX, scenario or regime mathematics.

Missing values remain missing. Missing data must never be silently converted to zero.

## 7. Gate Ordering

The implementation should make blocking precedence explicit and deterministic:

1. Input/contract validity.
2. Structural candidate eligibility.
3. Required evidence/quality/freshness.
4. Day 33 Central Risk status.
5. Portfolio-impact/concentration/directional/regime policy gates.
6. Produce final gate result.

A verified policy violation must not be hidden merely because another required dimension is incomplete. Conversely, incomplete evidence without a verified violation must not be fabricated into a block.

## 8. Provenance and Truth

- Broker position/account truth remains broker-authoritative.
- Paper portfolio position truth remains the existing `Position` authority.
- StrategyLegExposure remains attribution only.
- Broker/model/derived values remain source-distinguishable.
- Day 33 evidence and policy version are preserved, not recreated.
- Day 35 source separation must remain intact.
- Reference timestamps are caller-supplied and preserved.

## 9. Determinism

The Day 36 domain must be pure and deterministic:

- identical valid inputs produce identical serialized output;
- stable ordering and tie-breaking;
- no randomness;
- no UUID generation;
- no environment-dependent behavior;
- no wall-clock access.

## 10. Non-Goals / Hard Boundaries

Day 36 must NOT:

- place broker orders;
- create execution records;
- mutate positions or portfolio truth;
- approve live execution;
- bypass User Decision;
- become a broker source of truth;
- modify Day 33 policy semantics;
- modify Day 35 analytics semantics;
- replace `Position` or `StrategyLegExposure`;
- implement capital/margin logic;
- ingest historical data;
- add backtesting;
- add ML/AI;
- redesign the frontend;
- invent broker truth;
- invent portfolio thresholds that are not explicit inputs/configuration.

## 11. Suggested Package Boundary

```text
backend/app/final_risk_gate/__init__.py
backend/app/final_risk_gate/contracts.py
backend/app/final_risk_gate/gate.py
backend/tests/test_day36_final_risk_gate.py
```

No database/schema changes are expected unless implementation evidence proves persistence is required by an already-authoritative contract. Pure domain implementation is preferred.

## 12. TDD Coverage Minimum

Tests must cover at least:

- valid candidate + Day 33 PASS;
- Day 33 BLOCKED/INVALID/UNAVAILABLE;
- incomplete candidate;
- portfolio exposure impact;
- projected Greeks/GEX/scenario impact;
- concentration violation;
- directional exposure violation;
- regime-aware policy rule;
- unknown regime;
- regime label cannot manufacture direction;
- missing Greek/scenario/concentration data;
- quality/freshness failure;
- explicit policy threshold behavior;
- deterministic repeated execution and serialization;
- provenance preservation;
- caller timestamp preservation;
- no wall-clock access;
- no DB/network access;
- no broker access;
- no execution authority;
- User Decision remains external;
- tenant/account isolation;
- Day 33 evidence/policy preservation;
- Day 35 source separation preservation.

## 13. Exit Gate

Day 36 is complete only when independent verification demonstrates:

1. final gating consumes Days 32/33/35 contracts without bypass;
2. verified violations block deterministically;
3. incomplete evidence is represented correctly;
4. portfolio impact is deterministic and does not invent missing values;
5. provenance, quality, source and timestamps are preserved;
6. PASS is explicitly limited to proceeding to User Decision;
7. no execution/broker/approval authority is introduced;
8. focused, cross-day and regression tests pass;
9. static/purity/determinism/security checks are clean;
10. implementation scope is contained to Day 36.

No Day 37 work starts until Day 36 receives an independent 🟢 APPROVED verdict.
