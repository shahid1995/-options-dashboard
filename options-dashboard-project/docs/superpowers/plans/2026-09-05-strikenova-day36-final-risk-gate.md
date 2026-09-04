# StrikeNova Day 36 — Final Risk Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a deterministic final risk-gating domain that consumes the Day 32 Strategy Candidate, Day 33 Central Risk, and Day 35 Portfolio Intelligence outputs and permits only eligible candidates to proceed to User Decision.

**Architecture:** Keep Day 36 as a pure broker-neutral domain boundary. Reuse authoritative upstream contracts and analytics; compute only deterministic incremental portfolio impact/gate checks needed by the final policy. PASS means “proceed to User Decision,” never execution approval.

**Tech Stack:** Python 3.x, existing StrikeNova backend domain contracts, pytest, immutable/serializable domain contracts.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-05-strikenova-day36-final-risk-gate-design.md`

## Global Constraints

- PostgreSQL is the production transactional source of record; Day 36 should remain persistence-free unless an existing authoritative contract proves persistence is required.
- Alembic is the sole schema authority; no ad-hoc schema changes.
- Broker truth remains authoritative for broker positions/account state.
- Existing paper `Position` remains authoritative for paper positions.
- `StrategyLegExposure` remains attribution only.
- Missing values are not silently converted to zero.
- Deterministic, explainable intelligence before ML.
- Evidence, confidence, data quality and policy decisions remain distinct.
- User broker connections are not historical-data acquisition.
- No broker credentials, orders, execution, live trading, user approval or production cutover.
- No new Greek/GEX/scenario/regime mathematics.
- No direct Opportunity-to-Order path.
- No wall-clock, randomness, UUID generation, DB/network/filesystem side effects in the pure domain.
- TDD is mandatory: RED → minimal implementation → GREEN → regression.
- No Day 37 work until independent Day 36 verification yields 🟢 APPROVED.

---

### Task 1: Establish Day 36 contracts and failing tests

**Files:**
- Create: `options-dashboard-project/backend/app/final_risk_gate/__init__.py`
- Create: `options-dashboard-project/backend/app/final_risk_gate/contracts.py`
- Test: `options-dashboard-project/backend/tests/test_day36_final_risk_gate.py`

**Interfaces:**
- Consumes: existing Day 32 Strategy Candidate, Day 33 Central Risk result, Day 35 Portfolio State/Analytics contracts.
- Produces: immutable `FinalRiskGateInput`, policy/configuration contract, per-gate assessment contract, and `FinalRiskGateResult` with explicit status/decision semantics.

- [ ] **Step 1: Inspect existing Day 32, Day 33 and Day 35 contracts and reuse their exact field/type semantics.**
- [ ] **Step 2: Write failing tests for valid input, invalid/incomplete input, statuses, serialization and source/provenance preservation.**
- [ ] **Step 3: Run the Day 36 test module and confirm the new tests fail for the intended missing contracts/behavior.**
- [ ] **Step 4: Implement the smallest immutable contracts required by the tests.**
- [ ] **Step 5: Run the focused contract tests and confirm GREEN.**
- [ ] **Step 6: Commit the contract/test increment with a Day 36 task-specific message.**

---

### Task 2: Implement deterministic final gate evaluation

**Files:**
- Modify: `options-dashboard-project/backend/app/final_risk_gate/gate.py`
- Modify: `options-dashboard-project/backend/app/final_risk_gate/contracts.py` only if required by Task 1 findings
- Test: `options-dashboard-project/backend/tests/test_day36_final_risk_gate.py`

**Interfaces:**
- Consumes: Task 1 contracts plus authoritative Day 32/33/35 objects.
- Produces: deterministic `evaluate_final_risk_gate(...) -> FinalRiskGateResult`.

- [ ] **Step 1: Add failing tests for structural eligibility, Day 33 PASS/BLOCKED/PARTIAL/UNAVAILABLE/INVALID handling, quality/freshness, and explicit policy thresholds.**
- [ ] **Step 2: Run those tests and verify RED.**
- [ ] **Step 3: Implement structural and Day 33 gate precedence without duplicating Day 33 policy semantics.**
- [ ] **Step 4: Implement deterministic data-quality/freshness checks using caller-supplied timestamps only.**
- [ ] **Step 5: Run the focused tests and verify GREEN.**
- [ ] **Step 6: Commit the gate-policy increment.**

---

### Task 3: Add deterministic portfolio-impact and multidimensional policy checks

**Files:**
- Modify: `options-dashboard-project/backend/app/final_risk_gate/gate.py`
- Modify: `options-dashboard-project/backend/app/final_risk_gate/contracts.py` only if required
- Test: `options-dashboard-project/backend/tests/test_day36_final_risk_gate.py`

**Interfaces:**
- Consumes: Day 35 normalized portfolio analytics plus already-defined candidate strategy/legs and explicit final-gate policy.
- Produces: portfolio-impact evidence and gate assessments for concentration, directional and regime-aware constraints.

- [ ] **Step 1: Write failing tests for incremental exposure/Greeks/GEX/scenario impact.**
- [ ] **Step 2: Write failing tests for concentration and directional policy violations.**
- [ ] **Step 3: Write failing tests for regime-aware rules, unknown regime, and the invariant that a regime label alone cannot manufacture directional evidence.**
- [ ] **Step 4: Write failing tests for missing Greek/scenario/concentration evidence and verified-violation precedence.**
- [ ] **Step 5: Run the focused tests and verify RED.**
- [ ] **Step 6: Implement only deterministic reuse of existing quant/portfolio services; do not introduce new Greek/GEX/scenario/regime math.**
- [ ] **Step 7: Ensure missing inputs remain missing and incomplete evidence becomes PARTIAL/UNAVAILABLE rather than fabricated zeros or invented violations.**
- [ ] **Step 8: Run focused tests and verify GREEN.**
- [ ] **Step 9: Commit the portfolio-impact increment.**

---

### Task 4: Prove purity, determinism, isolation and boundary safety

**Files:**
- Test: `options-dashboard-project/backend/tests/test_day36_final_risk_gate.py`
- Modify: Day 36 package files only if a test exposes a defect.

**Interfaces:**
- Consumes: complete Day 36 gate implementation.
- Produces: executable proof that Day 36 has no execution/broker/DB/network/clock/randomness authority and preserves tenant/account context.

- [ ] **Step 1: Add failing tests for repeated execution/byte-stable serialization and caller timestamp preservation.**
- [ ] **Step 2: Add failing tests/invariants for no wall-clock, DB, network, broker or execution calls.**
- [ ] **Step 3: Add failing tests for Day 33 evidence/policy-version preservation and Day 35 source-separated Greeks/GEX semantics.**
- [ ] **Step 4: Add tenant/account isolation assertions appropriate to existing project conventions.**
- [ ] **Step 5: Run the focused test module and verify RED where behavior is absent.**
- [ ] **Step 6: Implement the minimum fixes needed and verify GREEN.**
- [ ] **Step 7: Run Python compilation, purity/static checks, secret scan and deterministic serialization checks used by prior approved days.**
- [ ] **Step 8: Commit the boundary-hardening increment.**

---

### Task 5: Full verification, evidence and Day 36 gate review

**Files:**
- Modify: `options-dashboard-project/docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`
- Test: existing project suites plus `backend/tests/test_day36_final_risk_gate.py`

**Interfaces:**
- Consumes: all Day 36 implementation commits.
- Produces: fresh verification evidence and a tracker entry identifying exact commits/tests and the Day 36 verdict.

- [ ] **Step 1: Run Day 36 focused tests.**
- [ ] **Step 2: Run Days 19–36 cross-day intelligence tests.**
- [ ] **Step 3: Run the broader Days 9–36 regression suite.**
- [ ] **Step 4: Run security/session regression and record the exact status of known pre-existing failures separately.**
- [ ] **Step 5: Run infrastructure/migration compatibility checks used by prior days where applicable.**
- [ ] **Step 6: Inspect the complete Day 36 diff for scope, architecture and contract violations.**
- [ ] **Step 7: Verify no production deployment, merge, live execution, broker mutation or schema cutover occurred.**
- [ ] **Step 8: Update the status tracker with exact HEAD, test counts, static checks, scope and gate verdict.**
- [ ] **Step 9: Commit the evidence/tracker update.**
- [ ] **Step 10: Independently review the final remote diff and verification evidence before declaring Day 36 approved.**

---

## Final Acceptance Checklist

- [ ] Day 32 candidate eligibility is preserved.
- [ ] Day 33 Central Risk remains the authoritative central risk-policy layer.
- [ ] Day 35 portfolio analytics remain authoritative for portfolio-derived state.
- [ ] Verified violations cannot be hidden by unrelated incomplete dimensions.
- [ ] Missing data is never silently zero-filled.
- [ ] Portfolio impact is deterministic and traceable.
- [ ] Concentration/directional/regime-aware checks are explicit and configurable, not invented.
- [ ] Unknown regime does not manufacture directional evidence.
- [ ] Broker/model sources remain distinguishable.
- [ ] Provenance, quality and timestamps survive the gate.
- [ ] PASS means only “proceed to User Decision.”
- [ ] No user approval or execution authority is implemented.
- [ ] No DB/network/broker/wall-clock/randomness dependency exists in the pure domain.
- [ ] Focused and regression tests pass with known unrelated/pre-existing failures explicitly identified.
- [ ] Final remote diff is scope-contained.
- [ ] Independent review yields 🟢 DAY 36 APPROVED.
