# StrikeNova Day 31 — Strategy Evaluation Engine Implementation Plan

**Date:** 2026-09-03  
**Design:** `docs/superpowers/specs/2026-09-03-strikenova-day31-strategy-evaluation-design.md`  
**Branch:** `feat/strikenova-day1-security`  
**Implementation gate:** Product owner approved the design; FreeBuff must implement only after receiving the separate implementation prompt.

## Goal

Implement a deterministic, broker-neutral Strategy Evaluation Engine that unifies payoff, Greeks, scenarios, regime, liquidity, risk and historical evidence while reusing existing authoritative contracts and preserving evidence/provenance.

## File map

Expected implementation boundary (verify against current repository before editing):

- `backend/app/strategy_evaluation/__init__.py` — package exports only.
- `backend/app/strategy_evaluation/contracts.py` — frozen/enforced Day-31 input, assessment and result contracts; reuses existing canonical types rather than duplicating them.
- `backend/app/strategy_evaluation/evaluation.py` — pure orchestration/evaluation logic; delegates authoritative calculations to existing shared domains.
- `backend/tests/test_day31_strategy_evaluation.py` — complete Day-31 contract, semantic, determinism, provenance, and boundary tests.
- `docs/superpowers/specs/2026-09-03-strikenova-day31-strategy-evaluation-design.md` — authoritative design; do not rewrite during implementation except for narrowly discovered contract corrections approved in review.
- `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md` — append Day-31 implementation evidence only after implementation/testing; never declare the independent gate PASS.

If an existing backend strategy/scenario/risk contract is authoritative, reuse it. Do not create duplicate payoff, Greek, scenario, provenance, or central-risk models merely to simplify implementation.

## Task 1 — Repository reconnaissance

1. Confirm current branch and HEAD.
2. Confirm Day 30 remediation is present and working tree is clean.
3. Read Day-31 design and Master Implementation Plan.
4. Locate existing canonical strategy/leg, payoff, Greek, scenario/time, risk, regime, quality, provenance and historical contracts.
5. Map exact reusable APIs and identify any backend/frontend boundary that cannot be reused directly.
6. Do not modify code during reconnaissance.

## Task 2 — Write failing contract tests

Create `backend/tests/test_day31_strategy_evaluation.py` before implementation.

Tests must cover:

- valid/invalid strategy identity and legs;
- evaluation context values;
- caller-supplied reference timestamp;
- payoff result reuse, including same-expiry exact and mixed-expiry approximation semantics;
- Greek aggregation with explicit action/quantity/multiplier semantics;
- missing Greek components remain missing;
- scenario reuse and warning/partial propagation;
- regime compatibility using the authoritative regime channel;
- regime label alone does not fabricate directional evidence;
- liquidity/spread evidence and unavailable semantics;
- risk assessment as informational/evaluative only;
- historical evidence available vs unavailable, with no fabricated score;
- evidence rows and factor/dimension provenance preservation;
- Opportunity provenance preservation when present;
- confidence and quality remain separate from suitability/evaluation score;
- explicit partial/unavailable/invalid result statuses;
- deterministic repeated evaluation and serialization;
- context-equivalence for identical canonical inputs;
- no order/execution/risk-authorization side effects;
- purity boundary: no clock/random/DB/network/filesystem/broker dependencies.

Run the focused tests and record RED evidence. Do not weaken tests to obtain RED.

## Task 3 — Implement contracts minimally

Implement the smallest contract surface needed to satisfy the design and tests.

Required properties:

- finite numeric validation where numeric fields are bounded/required;
- explicit missing/partial/unavailable states;
- stable serialization/deserialization;
- canonical provenance type reuse;
- evidence structured enough to identify dimension, source and state;
- no generated UUIDs or timestamps inside the domain;
- no credentials or broker-specific fields.

Do not introduce an opaque score without an explicit documented formula and required components.

## Task 4 — Implement deterministic evaluation orchestration

Implement `evaluation.py` as a pure domain orchestrator.

Rules:

- delegate payoff calculations to the authoritative existing payoff/strategy calculator where usable;
- delegate scenario calculations to the existing scenario/time domain rather than copying Black-Scholes/scenario math;
- use authoritative/shared Greek contracts/calculations;
- consume supplied regime/liquidity/risk/historical evidence;
- preserve warnings and quality state;
- never substitute missing values with zero;
- never read wall-clock time;
- never perform I/O;
- never create orders/execution intents;
- never authorize risk;
- never mutate input strategy/Opportunity objects.

If an existing calculation is frontend-only and cannot be safely imported into the backend, do not copy a large implementation opportunistically. Stop and report the boundary as a design issue rather than silently creating a second authoritative engine.

## Task 5 — Focused GREEN and refactor

Run Day-31 tests.

Fix only implementation defects. Refactor only after green while preserving the design boundary.

Verify:

- all Day-31 tests pass;
- deterministic serialization is stable;
- all missing-data cases are honest;
- evidence/provenance survives every result hop;
- context does not change quantitative results;
- no execution behavior is present.

## Task 6 — Regression ladder

Run fresh regression suites, using the repository's current test organization:

1. Day 31 focused suite.
2. Days 19–31 intelligence/opportunity/strategy regression.
3. Days 14–18 quantitative regression.
4. Days 9–13 market-data/provenance/quality regression.
5. Security/session regression.
6. Infrastructure/Alembic/PostgreSQL compatibility regression.

Document exact counts and distinguish reproducible pre-existing failures from new failures.

## Task 7 — Static and scope verification

Run:

- `py_compile` / repository Python syntax checks;
- `git diff --check`;
- AST purity guard;
- unused-import scan;
- secret scan;
- scope audit against the Day-31 design.

Reject the implementation if it adds DB/API/frontend/broker/execution behavior or touches Day-32+ implementation.

## Task 8 — Commit and tracker evidence

Create a focused implementation commit, e.g.:

`feat(strategy-evaluation): implement Day 31 deterministic evaluation`

Then update the status tracker with:

- baseline SHA;
- implementation SHA;
- files changed;
- TDD RED/GREEN evidence;
- focused/regression/static evidence;
- scope isolation;
- known pre-existing failures;
- production isolation.

Do not write `APPROVED` or `PASS` as the Day-31 gate verdict. The independent architect decides that after reviewing the actual diff and fresh evidence.

## Final verification gate

The implementation is ready for independent review only if:

- the design is faithfully implemented;
- tests are fresh and passing within the documented baseline exceptions;
- provenance/evidence is complete;
- score/confidence/quality are distinct;
- missing data is never fabricated;
- existing authoritative calculations are reused;
- context-equivalence holds;
- deterministic/pure boundaries hold;
- no execution or central-risk authorization leaked into Day 31;
- no Day-32+ work is present;
- CI checks relevant to the commit succeed.
