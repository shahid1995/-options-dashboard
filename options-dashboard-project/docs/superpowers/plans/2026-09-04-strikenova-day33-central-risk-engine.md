# StrikeNova Day 33 — Central Risk Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the deterministic standalone Central Risk Engine that evaluates an eligible Day-32 Strategy Candidate against explicit risk evidence and risk policy without portfolio, capital/margin, user-approval, broker, or execution authority.

**Architecture:** Add a pure domain risk boundary that consumes the authoritative Day-32 candidate and existing quantitative/scenario evidence. Reuse existing payoff, Greek, scenario, quality, timestamp and provenance contracts rather than duplicating mathematics. Separate risk metrics, policy decisions, confidence, quality and any descriptive score.

**Tech Stack:** Python 3.13, existing StrikeNova backend domain contracts, pytest/pytest-asyncio, existing deterministic serialization and quality/provenance conventions.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-04-strikenova-day33-central-risk-engine-design.md`

## Global Constraints

- PostgreSQL is the production transactional system of record; SQLite remains only where explicitly supported for local development/test compatibility.
- Alembic is the sole authoritative schema-management mechanism.
- Production schema changes use `Expand → Migrate → Contract`.
- Broker truth remains authoritative for actual broker orders, fills, positions, account state and broker-provided values.
- StrikeNova owns derived intelligence and must distinguish broker-provided values from calculated/model values.
- Opportunity discovery never directly implies an order; preserve `Observation → Signal → Setup → Opportunity → Strategy Candidate → Risk Check → User Decision → Execution`.
- Deterministic, explainable intelligence must exist before ML augmentation.
- Evidence, confidence and data quality remain separate concepts; no opaque single score replaces the evidence trail.
- Every intelligence result must carry freshness, completeness, validity, consistency, continuity, anomaly and provenance context as applicable.
- User broker connections are not the platform's historical-data acquisition mechanism; historical acquisition remains admin-controlled.
- Broker credentials must be encrypted at rest and never logged or exposed to frontend code.
- Strict tenant isolation and resource ownership are mandatory.
- AI begins read/analyze/simulate only; unrestricted live execution is not an initial capability.
- Live execution cannot be enabled until all hard gates in the plan are passed and explicitly approved.
- No uncontrolled production deployment, merge, or production cutover is performed by the implementation agent.
- Each day ends with tests, verification, a short evidence record, and a gate. A failed gate keeps that day open; the calendar does not override correctness.
- Each implementation task follows TDD: failing test → minimal implementation → focused test pass → broader regression test → commit.
- Day 33 must not duplicate authoritative payoff, Greek, GEX, IV, scenario, strike-ranking, or strategy-evaluation mathematics.
- Day 33 owns standalone strategy risk only; portfolio risk is Day 34, capital/margin is Day 35, final risk gate is Day 36.
- FreeBuff must not deploy, perform production cutover, change production credentials, or enable live execution.

---

## Repository Reconnaissance Before Coding

### Task 1: Inspect and map existing risk/quantitative contracts

**Files:**
- Inspect `backend/app/` risk-related modules and existing risk contracts.
- Inspect Day-18 scenario/time-analysis contracts.
- Inspect Day-31 `strategy_evaluation` contracts and evaluator.
- Inspect Day-32 `strategy_lifecycle` contracts and lifecycle gate.
- Inspect canonical quality, provenance and calculation-context contracts.

**Interfaces:**
- Consumes: repository's existing authoritative domain contracts.
- Produces: a documented implementation map; no code change if existing contracts already provide the needed boundary.

- [ ] Search for existing risk, payoff, Greek, scenario and policy types before creating new ones.
- [ ] Confirm exact Day-32 candidate type and eligibility semantics.
- [ ] Confirm existing quality/freshness enum and serialization conventions.
- [ ] Confirm canonical provenance type and calculation/version fields.
- [ ] Identify any existing standalone risk implementation that must be reused or retired rather than duplicated.
- [ ] Record findings in the Day-33 plan/status evidence.

**Verification:** repository search and source inspection. Do not implement until this mapping is complete.

---

## Contract and Policy Foundation

### Task 2: Define failing tests for the risk-policy contract

**Files:**
- Create/modify the Day-33 risk contract module identified by Task 1.
- Test: `backend/tests/test_day33_central_risk.py`

**Interfaces:**
- Consumes: explicit policy inputs and canonical existing types.
- Produces: immutable, validated, deterministic risk-policy contract.

- [ ] Write tests for finite/non-negative policy values where applicable.
- [ ] Write tests for explicit handling of unbounded-loss permission.
- [ ] Write tests for quality/freshness policy fields only where repository conventions support them.
- [ ] Write tests for stable policy version and deterministic serialization.
- [ ] Run focused tests and confirm RED.

### Task 3: Implement the minimal risk-policy contract

**Files:**
- Modify/create the contract module selected by Task 1.

- [ ] Implement only fields justified by existing architecture and the approved spec.
- [ ] Validate policy invariants.
- [ ] Implement deterministic serialization.
- [ ] Run the focused policy tests and confirm GREEN.

**Commit:** `feat(day33): add central risk policy contract`

---

## Risk Evidence Contracts

### Task 4: Write failing tests for risk-dimension evidence

**Files:**
- Day-33 contract module.
- `backend/tests/test_day33_central_risk.py`

**Interfaces:**
- Consumes: authoritative payoff/Greek/scenario evidence from existing domains.
- Produces: typed risk-dimension assessments with explicit state and evidence.

- [ ] Test `AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, and `INVALID` dimension states.
- [ ] Test missing values remain missing rather than becoming zero.
- [ ] Test evidence retains provenance.
- [ ] Test confidence and quality remain separate fields.
- [ ] Test deterministic serialization.
- [ ] Run focused tests and confirm RED.

### Task 5: Implement risk-dimension contracts

**Files:**
- Day-33 contract module.

- [ ] Implement immutable dimension/evidence contracts.
- [ ] Reuse canonical `Provenance` and quality types.
- [ ] Represent unbounded loss explicitly.
- [ ] Keep dimension evidence separate rather than flattening it.
- [ ] Run focused tests and confirm GREEN.

**Commit:** `feat(day33): add standalone risk evidence contracts`

---

## Central Risk Engine

### Task 6: Write failing tests for payoff and structural risk

**Files:**
- `backend/tests/test_day33_central_risk.py`

- [ ] Build genuine Day-32 candidate fixtures through Day-19 → Day-28 → Day-30 → Day-31 → Day-32 composition where practical.
- [ ] Test bounded payoff.
- [ ] Test unbounded payoff.
- [ ] Test missing payoff evidence.
- [ ] Test malformed/invalid strategy structure.
- [ ] Test no fabricated zero for missing maximum loss.
- [ ] Run and confirm RED.

### Task 7: Implement payoff/structural risk evaluation by reusing authoritative inputs

**Files:**
- Day-33 engine module.

- [ ] Consume existing payoff/strategy evidence rather than reimplementing payoff mathematics.
- [ ] Produce explicit structural failures.
- [ ] Preserve bounded/unbounded semantics.
- [ ] Run focused tests and confirm GREEN.

### Task 8: Write failing tests for Greek risk

**Files:**
- `backend/tests/test_day33_central_risk.py`

- [ ] Test aggregation of supported Greeks with explicit leg quantity/sign/multiplier semantics.
- [ ] Test missing Greek components.
- [ ] Test model/live distinction where canonical inputs expose it.
- [ ] Test provenance preservation.
- [ ] Run and confirm RED.

### Task 9: Implement Greek-risk evaluation

**Files:**
- Day-33 engine module.

- [ ] Reuse authoritative quantitative contracts.
- [ ] Do not create a second Greek implementation.
- [ ] Preserve missing components and provenance.
- [ ] Run focused tests and confirm GREEN.

### Task 10: Write failing tests for scenario risk

**Files:**
- `backend/tests/test_day33_central_risk.py`

- [ ] Test reuse of Day-18 scenario outputs.
- [ ] Test worst supplied scenario loss.
- [ ] Test partial/unavailable scenario evidence.
- [ ] Test that “worst supplied scenario” is not labeled theoretical worst-case.
- [ ] Run and confirm RED.

### Task 11: Implement scenario-risk evaluation

**Files:**
- Day-33 engine module.

- [ ] Consume existing scenario/time-analysis results.
- [ ] Preserve scenario identity, warnings and partial state.
- [ ] Do not duplicate scenario mathematics.
- [ ] Run focused tests and confirm GREEN.

**Commit:** `feat(day33): implement central standalone risk dimensions`

---

## Policy Decision and Result Composition

### Task 12: Write failing tests for policy evaluation and result status

**Files:**
- `backend/tests/test_day33_central_risk.py`

- [ ] Test policy PASS.
- [ ] Test explicit policy BLOCKED.
- [ ] Test incomplete evidence produces PARTIAL rather than false PASS.
- [ ] Test unavailable evidence produces UNAVAILABLE when appropriate.
- [ ] Test invalid authoritative input produces INVALID.
- [ ] Test a high descriptive risk score cannot override BLOCKED policy.
- [ ] Test PASS/BLOCKED/PARTIAL/UNAVAILABLE/INVALID are deterministic.
- [ ] Run and confirm RED.

### Task 13: Implement policy evaluation and final result

**Files:**
- Day-33 engine module and contracts.

- [ ] Implement deterministic decision precedence.
- [ ] Keep policy violations explicit and evidence-backed.
- [ ] Preserve confidence and quality separately.
- [ ] Preserve result-level and dimension-level provenance.
- [ ] Include reference timestamp and version metadata.
- [ ] Add a descriptive score only if repository/design evidence justifies it; otherwise omit it.
- [ ] Run focused tests and confirm GREEN.

### Task 14: Write failing tests for determinism, context equivalence and purity

**Files:**
- `backend/tests/test_day33_central_risk.py`

- [ ] Evaluate identical inputs repeatedly and compare deterministic serialized output.
- [ ] Evaluate equivalent inputs across `OPPORTUNITY`, `PAPER`, `BACKTEST`, and `RESEARCH` where the existing contract supports those contexts.
- [ ] Assert no wall-clock dependence.
- [ ] Assert no randomness.
- [ ] Assert no database/network/filesystem/broker dependency.
- [ ] Assert no execution or user-approval vocabulary/authority.
- [ ] Run and confirm RED.

### Task 15: Implement final deterministic composition and purity boundary

**Files:**
- Day-33 engine/contracts only.

- [ ] Ensure caller-supplied reference time is the only temporal input.
- [ ] Ensure context is metadata only.
- [ ] Ensure deterministic ordering of evidence/issues.
- [ ] Ensure JSON-safe deterministic serialization.
- [ ] Run focused tests and confirm GREEN.

**Commit:** `feat(day33): add deterministic central risk engine`

---

## Verification and Documentation

### Task 16: Run focused and regression verification

**Files:**
- No source changes expected.

- [ ] Run Day-33 focused tests.
- [ ] Run Days19–33 regression.
- [ ] Run Days9–33 regression.
- [ ] Run security/session regression and record any pre-existing failures separately.
- [ ] Run infrastructure/migration regression where applicable.
- [ ] Run Python compilation/static checks.
- [ ] Run purity/AST checks.
- [ ] Run unused-import and secret scans.
- [ ] Verify no unrelated files changed.
- [ ] Verify Day34/Day35/Day36 code was not introduced.

### Task 17: Independent diff and architectural review

- [ ] Compare implementation against the approved Day-33 spec line by line.
- [ ] Verify no duplicate payoff/Greek/scenario mathematics.
- [ ] Verify missing ≠ zero.
- [ ] Verify policy decision is not a portfolio/capital/execution decision.
- [ ] Verify provenance, quality and confidence remain separate.
- [ ] Verify genuine upstream objects are used in tests.
- [ ] Verify no broker calls, order objects, DB/API/frontend changes or production changes entered the scope.

### Task 18: Record evidence and commit the coherent Day-33 batch

**Files:**
- `options-dashboard-project/docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`
- Day-33 design/plan if evidence requires correction.

- [ ] Record focused/regression/static verification evidence.
- [ ] Record unresolved issues, explicitly distinguishing pre-existing failures.
- [ ] Update Day-33 status only after verification evidence exists.
- [ ] Commit the coherent implementation and evidence.
- [ ] Do not deploy.

**Expected final gate:** 🟢 PASS only when all Day-33 requirements are independently verified.

A PASS unlocks Day 34 — Portfolio Risk and Concentration Intelligence.
