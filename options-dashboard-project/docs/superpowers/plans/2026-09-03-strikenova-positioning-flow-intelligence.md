# StrikeNova Day 20 — Positioning & Flow/Divergence Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic, broker-neutral Positioning Intelligence and Flow/Divergence Intelligence engines on top of the hardened Day-19 Intelligence Contract, without changing the contract or crossing into later intelligence, opportunity, risk, or execution scope.

**Architecture:** Canonical market observations and Day-12 quality feed deterministic Day-20 domain transformations. The engines produce Day-19 `IntelligenceResult` envelopes with explicit evidence, provenance, quality, direction, signal strength, confidence, and horizon. Missing data remains missing; market-domain conclusions are explicit rules rather than unconditional assumptions such as “high CE OI = resistance.”

**Tech Stack:** Python 3.13, frozen dataclasses, pytest/pytest-asyncio, existing `app.market_data`, `app.quant`, and `app.intelligence` contracts.

**Spec:** `docs/superpowers/specs/2026-09-02-strikenova-architecture-blueprint-v1-design.md`, plus the approved Day-20 design in the StrikeNova Project Control Center and the Day-19 contract at `docs/superpowers/plans/2026-09-03-strikenova-intelligence-contract.md`.

## Global Constraints

- Day-19 `IntelligenceResult` is authoritative; do not modify it to accommodate Day 20.
- Missing values stay `None`; observed zero remains zero; never substitute zero for missing data.
- `signal_strength`, `confidence`, and `QualityResult` are separate concepts and must never be collapsed.
- Preserve supplied Day-12 `QualityResult` and Day-9 provenance; never recompute/fabricate them in the intelligence layer.
- Every deterministic result uses explicitly supplied timestamps; no wall-clock access.
- No network, filesystem, database, broker, Redis, Kafka, worker, or external service dependency in engine modules.
- No frontend changes, API changes, execution/risk/portfolio changes, AI/ML, backtesting, or Day-21+ engines.
- Broker-specific payload names and imports remain outside the intelligence layer.
- TDD is mandatory: RED → GREEN → REFACTOR.
- A genuine contract deficiency discovered during implementation is a STOP-and-report condition; do not silently alter the Day-19 contract.

---

### Task 1: Map the canonical inputs and freeze Day-20 boundaries

**Files:**
- Inspect: `backend/app/market_data/contracts.py`
- Inspect: `backend/app/market_data/quality.py`
- Inspect: `backend/app/quant/contracts.py`
- Inspect: `backend/app/intelligence/contracts.py`
- Inspect: existing Day-9–19 tests for established fixture and validation conventions

**Interfaces:**
- Consumes canonical `PriceQuote`, `OptionChainRow`, `OptionChainObservation`, `Provenance`, `QualityResult`, and Day-19 intelligence contracts.
- Produces a written boundary in the implementation plan/tracker before engine code begins.

- [ ] Step 1: Inspect the exact fields and semantics available for option price, OI, volume, timestamps, quality, and provenance.
- [ ] Step 2: Confirm OI is treated as contracts and missing values remain `None`.
- [ ] Step 3: Identify the smallest pure input structures required by Day 20; do not import broker adapters.
- [ ] Step 4: If a required field does not exist in canonical contracts, stop and report the contract gap instead of modifying Day 9/19 contracts.

### Task 2: Define Positioning Intelligence input/output model

**Files:**
- Create: `backend/app/intelligence/positioning.py`
- Test: `backend/tests/test_day20_positioning.py`

**Interfaces:**
- Consumes a canonical option-chain snapshot plus explicitly supplied `QualityResult`, `Provenance`, reference timestamp, and calculation/version identifiers.
- Produces deterministic positioning measurements and Day-19 `IntelligenceResult` objects.

- [ ] Step 1: Write failing tests for CE/PE strike-level measurements: OI, OI change, volume, price context, and explicit missingness.
- [ ] Step 2: Write failing tests proving zero is preserved as zero and `None` is never converted to zero.
- [ ] Step 3: Write failing tests for CE/PE symmetry and deterministic strike ordering.
- [ ] Step 4: Write failing tests requiring supplied quality/provenance/reference timestamp to be preserved in results.
- [ ] Step 5: Run the focused tests and confirm RED.
- [ ] Step 6: Implement the minimal pure positioning value objects and calculations.
- [ ] Step 7: Add explicit aggregate CE/PE positioning measures without encoding unconditional support/resistance claims.
- [ ] Step 8: Return Day-19 results with explicit direction only when the documented deterministic rule has sufficient evidence; otherwise use `MIXED`/`UNKNOWN` or a non-success status as structurally appropriate.
- [ ] Step 9: Run focused tests and confirm GREEN.

### Task 3: Define flow and divergence calculations

**Files:**
- Create: `backend/app/intelligence/flow.py`
- Test: `backend/tests/test_day20_flow.py`

**Interfaces:**
- Consumes canonical option-chain/observation-derived numeric inputs and Day-19 metadata.
- Produces deterministic CE–PE flow, Delta divergence, Vega divergence, and price/OI relationship measurements as Day-19 intelligence results.

- [ ] Step 1: Write failing tests for CE–PE net flow with positive, negative, balanced, zero, and missing inputs.
- [ ] Step 2: Write failing tests for Delta divergence using explicitly supplied CE and PE delta measurements; do not infer deltas from broker-specific payloads.
- [ ] Step 3: Write failing tests for Vega divergence using explicitly supplied CE and PE vega measurements.
- [ ] Step 4: Write failing tests for price-vs-OI relationships with missing-field propagation.
- [ ] Step 5: Write failing tests for sign symmetry: swapping CE/PE must reverse directional relationships where the metric definition requires it.
- [ ] Step 6: Run the focused tests and confirm RED.
- [ ] Step 7: Implement the smallest deterministic calculation layer.
- [ ] Step 8: Attach structured evidence for each derived metric and preserve source provenance/version metadata.
- [ ] Step 9: Ensure no formula silently treats absent OI, delta, vega, or price as zero.
- [ ] Step 10: Run focused tests and confirm GREEN.

### Task 4: Define deterministic interpretation rules and evidence semantics

**Files:**
- Modify: `backend/app/intelligence/positioning.py`
- Modify: `backend/app/intelligence/flow.py`
- Test: `backend/tests/test_day20_positioning.py`
- Test: `backend/tests/test_day20_flow.py`

**Interfaces:**
- Consumes measurements from Tasks 2–3.
- Produces Day-19 `IntelligenceResult` with evidence-linked interpretation.

- [ ] Step 1: Write failing tests for bullish, bearish, neutral/balanced, mixed, and unknown cases using fixed golden inputs.
- [ ] Step 2: Write failing tests proving conflicting CE/PE evidence becomes `MIXED` rather than being forced into a single direction.
- [ ] Step 3: Write failing tests proving insufficient evidence cannot become `SUCCESS`.
- [ ] Step 4: Write failing tests for confidence and signal-strength separation; changing confidence must not change the measured signal strength.
- [ ] Step 5: Implement only rules documented in the Day-20 module specification; do not introduce later Day-21–26 interpretations.
- [ ] Step 6: Ensure every directional claim has the evidence needed by the rule and that missing evidence produces a structured issue/status.
- [ ] Step 7: Run the focused suite and confirm GREEN.

### Task 5: Add independent golden datasets and deterministic invariants

**Files:**
- Test: `backend/tests/test_day20_positioning.py`
- Test: `backend/tests/test_day20_flow.py`
- Create if useful: `backend/tests/fixtures/day20_golden.py`

**Interfaces:**
- Tests exercise public Day-20 engine functions/value objects only.

- [ ] Step 1: Define fixed, independently calculated golden cases for CE/PE OI flow, aggregate positioning, CE–PE net flow, delta divergence, and vega divergence.
- [ ] Step 2: Validate arithmetic independently from the implementation helpers.
- [ ] Step 3: Add repeatability tests showing identical inputs produce identical serialized results.
- [ ] Step 4: Add boundary tests for zero, missing, equal-side, extreme finite, and conflicting inputs.
- [ ] Step 5: Add serialization round-trip tests through Day-19 `to_dict()`/`from_dict()`.
- [ ] Step 6: Run the complete Day-20 focused suite and confirm GREEN.

### Task 6: Enforce purity and architecture guards

**Files:**
- Test: `backend/tests/test_day20_architecture.py`
- Modify only if needed: `backend/app/intelligence/__init__.py`

**Interfaces:**
- No runtime external dependencies are permitted.

- [ ] Step 1: Add AST/import guards rejecting wall-clock/random/network/database/broker imports in Day-20 engine modules.
- [ ] Step 2: Guard against direct instantiation of the Day-12 quality engine; quality must be supplied and preserved.
- [ ] Step 3: Guard against broker-specific field names and adapter imports.
- [ ] Step 4: Confirm engine modules remain pure and serializable.
- [ ] Step 5: Run architecture tests and confirm GREEN.

### Task 7: Regression, security, and CI verification

**Files:**
- Modify: `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`

**Interfaces:**
- No production runtime behavior outside Day 20 is changed.

- [ ] Step 1: Run Day-20 focused tests.
- [ ] Step 2: Run Days 14–20 regression block.
- [ ] Step 3: Run Days 9–20 regression block.
- [ ] Step 4: Run established security/session tests and document only genuinely pre-existing failures reproduced against the clean Day-19 baseline.
- [ ] Step 5: Run migration/infra regression from the backend working directory.
- [ ] Step 6: Run `py_compile`, `git diff --check`, secret scan, and architecture/static guards.
- [ ] Step 7: Verify no production DB, deployment, merge, cutover, or live-trading operation occurred.
- [ ] Step 8: Commit the implementation separately from tracker/docs where practical, push the branch, and wait for CI.
- [ ] Step 9: Record exact SHAs, test counts, CI checks, changed files, and residual limitations in the tracker.

### Task 8: Day-20 hard stop

- [ ] Step 1: Produce a final report containing scope, formulas/rules, tests, regressions, CI, static/security checks, and production-isolation evidence.
- [ ] Step 2: Explicitly state that Day 21+ has not started.
- [ ] Step 3: STOP. Do not implement Dynamic S/R, institutional-like activity, regime detection, events, expiry intelligence, trap detection, synthesis, opportunity, strategy, risk, execution, or AI.

## Day-20 Gate

Day 20 passes only if:

1. Positioning and Flow/Divergence engines are deterministic and broker-neutral.
2. Every successful intelligence result preserves the supplied Day-12 `QualityResult` and Day-9 provenance.
3. Missing values remain missing and are never converted into zero or neutral conclusions.
4. CE/PE symmetry and conflict behavior are explicitly tested.
5. Signal strength, confidence, and data quality remain separate.
6. Evidence is sufficient and traceable for every directional interpretation.
7. No Day-19 contract modification occurred.
8. No DB/network/broker/frontend/execution/AI/ML/backtesting dependency was introduced.
9. Focused tests, regression suites, static/security checks, and CI pass, with pre-existing failures independently reproduced where applicable.
10. Production remains untouched.

**STOP after Day 20. Day 21 requires a separate explicit authorization.**
