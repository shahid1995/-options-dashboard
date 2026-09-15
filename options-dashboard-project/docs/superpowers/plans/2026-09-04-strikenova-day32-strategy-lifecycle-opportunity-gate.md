# StrikeNova Day 32 — Strategy Lifecycle and Opportunity Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect an existing Day-28 Opportunity, Day-30 ranked strikes, and Day-31 Strategy Evaluation into a deterministic Strategy Candidate lifecycle and Opportunity Gate without coupling the domain to risk authorization or execution.

**Architecture:** Add a small pure domain package under `backend/app/strategy_lifecycle/`. It consumes the authoritative Day-28 Opportunity, Day-30 ranking result, and Day-31 Strategy Evaluation contracts, preserving their identities, evidence, quality, timestamps, and provenance rather than recomputing them. The package emits a Strategy Candidate plus an explicit lifecycle/gate result; it creates no order, execution intent, broker call, risk authorization, database record, or user-approval decision.

**Tech Stack:** Python 3.13, frozen dataclasses/enums, existing StrikeNova domain contracts, pytest/pytest-asyncio. No new dependencies.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-03-strikenova-day32-strategy-lifecycle-opportunity-gate-design.md`

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
- Live execution cannot be enabled until all hard gates in this plan are passed and explicitly approved.
- No uncontrolled production deployment, merge, or production cutover is performed by the implementation agent.
- Each day ends with tests, verification, a short evidence record, and a gate. A failed gate keeps that day open; the calendar does not override correctness.
- Each implementation task follows TDD: failing test → minimal implementation → focused test pass → broader regression test → commit.
- Day 32 does not modify Day-28 Opportunity semantics, Day-30 ranking mathematics, or Day-31 evaluation mathematics.
- Day 32 does not introduce Day-33 centralized risk authorization, user approval, broker execution, database persistence, API endpoints, frontend behavior, ML, or AI.

---

## File map

- Create `options-dashboard-project/backend/app/strategy_lifecycle/__init__.py` — public package surface for the Day-32 contracts and gate function.
- Create `options-dashboard-project/backend/app/strategy_lifecycle/contracts.py` — immutable lifecycle vocabulary, Strategy Candidate, blocking reasons, and gate result contracts with deterministic serialization.
- Create `options-dashboard-project/backend/app/strategy_lifecycle/lifecycle.py` — pure lifecycle transition and Opportunity Gate orchestration; no I/O, wall clock, randomness, broker, or risk authorization.
- Create `options-dashboard-project/backend/tests/test_day32_strategy_lifecycle.py` — focused TDD coverage for contracts, transitions, integration, provenance, quality, missing data, serialization, determinism, and scope boundaries.
- Create/update `options-dashboard-project/docs/superpowers/specs/2026-09-03-strikenova-day32-strategy-lifecycle-opportunity-gate-design.md` — approved Day-32 design record if it is not already present on the branch.
- Modify `options-dashboard-project/docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md` — record Day-32 implementation evidence only after verification.

## Interfaces

The implementation must expose these stable domain interfaces:

```python
class StrategyLifecycleState(str, Enum):
    CANDIDATE = "CANDIDATE"
    EVALUATED = "EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"

class GateStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"

class BlockingReasonCode(str, Enum):
    MISSING_OPPORTUNITY = "MISSING_OPPORTUNITY"
    INVALID_OPPORTUNITY = "INVALID_OPPORTUNITY"
    MISSING_STRATEGY_ID = "MISSING_STRATEGY_ID"
    MISSING_LEGS = "MISSING_LEGS"
    MISSING_STRIKE_SELECTION = "MISSING_STRIKE_SELECTION"
    INVALID_STRIKE_SELECTION = "INVALID_STRIKE_SELECTION"
    MISSING_EVALUATION = "MISSING_EVALUATION"
    INVALID_EVALUATION = "INVALID_EVALUATION"
    INCOMPLETE_EVALUATION = "INCOMPLETE_EVALUATION"
    MISSING_REFERENCE_TIMESTAMP = "MISSING_REFERENCE_TIMESTAMP"
    INVALID_REFERENCE_TIMESTAMP = "INVALID_REFERENCE_TIMESTAMP"
    MISSING_QUALITY = "MISSING_QUALITY"
    INSUFFICIENT_QUALITY = "INSUFFICIENT_QUALITY"

@dataclass(frozen=True)
class StrategyCandidate:
    candidate_id: str
    opportunity_id: str
    strategy_id: str
    legs: tuple[OptionLeg, ...]
    selected_strike_ids: tuple[str, ...]
    expected_behavior: ExpectedBehavior
    invalidation_conditions: tuple[str, ...]
    evaluation: StrategyEvaluationResult
    lifecycle_state: StrategyLifecycleState
    confidence: float | None
    quality: QualityResult | None
    reference_timestamp: datetime
    provenance: Provenance | None

@dataclass(frozen=True)
class StrategyGateResult:
    status: GateStatus
    candidate: StrategyCandidate | None
    lifecycle_state: StrategyLifecycleState
    eligible: bool
    blocking_reasons: tuple[BlockingReason, ...]
    evidence: tuple[GateEvidence, ...]
    confidence: float | None
    quality: QualityResult | None
    reference_timestamp: datetime | None
    provenance: Provenance | None


def evaluate_strategy_gate(
    opportunity: Opportunity | None,
    ranked_strikes: StrikeRankingResult | None,
    evaluation: StrategyEvaluationResult | None,
    *,
    strategy_id: str | None = None,
    legs: tuple[OptionLeg, ...] = (),
    expected_behavior: ExpectedBehavior | None = None,
    invalidation_conditions: tuple[str, ...] | None = None,
    reference_timestamp: datetime | None = None,
    confidence: float | None = None,
    quality: QualityResult | None = None,
) -> StrategyGateResult: ...
```

The exact state vocabulary above is subject to repository reconciliation during implementation: if existing canonical lifecycle vocabulary already exists, reuse it rather than creating a duplicate. No state may imply risk approval, user approval, or execution approval.

---

### Task 1: Establish lifecycle contracts and serialization

**Files:**
- Create: `backend/app/strategy_lifecycle/__init__.py`
- Create: `backend/app/strategy_lifecycle/contracts.py`
- Test: `backend/tests/test_day32_strategy_lifecycle.py`

**Interfaces:**
- Consumes: Day-28 `Opportunity` / `ExpectedBehavior`; Day-30 `StrikeRankingResult`; Day-31 `StrategyEvaluationResult`; Day-18 `OptionLeg`; Day-9 `Provenance`; Day-12 `QualityResult`.
- Produces: `StrategyLifecycleState`, `GateStatus`, `BlockingReasonCode`, `BlockingReason`, `GateEvidence`, `StrategyCandidate`, `StrategyGateResult` plus deterministic `to_dict`/`from_dict` methods.

- [ ] **Step 1: Write failing contract tests.** Cover frozen construction, required identity, non-empty legs, selected-strike identity, explicit lifecycle state, timezone-aware reference timestamps, missing-vs-zero preservation, provenance/quality preservation, and JSON-safe deterministic round trips.
- [ ] **Step 2: Run focused tests to verify the new contracts fail before implementation.** Run `pytest tests/test_day32_strategy_lifecycle.py -q`; expected initial collection/import failures are acceptable at this TDD stage.
- [ ] **Step 3: Implement the minimal immutable contracts.** Reuse canonical upstream types; validate strings, tuples, timezone-aware timestamps, finite numeric fields, and provenance/quality types. Do not introduce UUIDs, random values, wall-clock reads, or I/O.
- [ ] **Step 4: Add deterministic serialization.** Preserve upstream evaluation identity and provenance references without flattening them into duplicated market-data values. Round-trip enums, timestamps, reasons, evidence, candidate legs, and quality/provenance.
- [ ] **Step 5: Run focused contract tests.** Expected: all Task-1 tests pass.

### Task 2: Implement lifecycle transitions and the Opportunity Gate

**Files:**
- Create: `backend/app/strategy_lifecycle/lifecycle.py`
- Modify: `backend/app/strategy_lifecycle/__init__.py`
- Test: `backend/tests/test_day32_strategy_lifecycle.py`

**Interfaces:**
- Consumes: Task-1 contracts plus authoritative Day-28/30/31 domain objects.
- Produces: pure `evaluate_strategy_gate(...)` and deterministic candidate identity generation from caller-supplied identifiers; no execution objects.

- [ ] **Step 1: Add failing gate tests.** Cover valid Opportunity → Strategy Candidate, missing Opportunity, invalid Opportunity, missing strategy identity/legs/strike selection/evaluation, invalid or incomplete evaluation, missing/insufficient quality, timestamp requirements, and explicit blocking reasons.
- [ ] **Step 2: Add failing lifecycle transition tests.** Permit only deterministic transitions such as `CANDIDATE → EVALUATED → ELIGIBLE` and `CANDIDATE/EVALUATED → BLOCKED`; reject transitions that skip required evidence or move backward. `EXPIRED` and `INVALID` must be terminal states.
- [ ] **Step 3: Run the new tests and confirm failure.** Run `pytest tests/test_day32_strategy_lifecycle.py -q`; expected failures identify the missing gate and transition behavior.
- [ ] **Step 4: Implement the minimum gate.** Require an authoritative Opportunity, strategy identity, structurally valid legs, ranked strike selection when the strategy requires it, and a Day-31 evaluation. Require evaluation status `SUCCESS` for `ELIGIBLE`; `PARTIAL`/`UNAVAILABLE` become explicit blocks rather than silently eligible. Preserve evaluation context-independent semantics.
- [ ] **Step 5: Implement lifecycle transitions.** Enforce the legal transition matrix in one pure function, with deterministic reasons for rejected transitions. Do not derive risk approval, user approval, or execution state from eligibility.
- [ ] **Step 6: Run focused tests.** Expected: all lifecycle/gate tests pass.

### Task 3: Integration, provenance, quality, and scope-boundary verification

**Files:**
- Test: `backend/tests/test_day32_strategy_lifecycle.py`

**Interfaces:**
- Consumes: completed Task-1/2 contracts and real Day-28/30/31 objects.
- Produces: evidence that Day 32 preserves upstream semantics and cannot bypass later gates.

- [ ] **Step 1: Add failing integration tests.** Prove selected strikes are carried by identity, evaluation is preserved without recomputation, Opportunity provenance remains distinct from dimension provenance, missing values remain missing, DEGRADED quality remains visible, INSUFFICIENT quality blocks eligibility, and the same canonical strategy produces the same result independent of evaluation context.
- [ ] **Step 2: Add failing determinism/purity tests.** Invoke the gate repeatedly with identical inputs and compare serialized output; inspect source/AST to reject imports or calls for time, random, UUID, filesystem, network, broker adapters, order services, or central risk decisions.
- [ ] **Step 3: Add failing negative-scope tests.** Assert no returned object contains order IDs, broker order types, execution status, user approval, or risk authorization vocabulary.
- [ ] **Step 4: Implement only the missing behavior.** Keep the package domain-pure and broker-neutral.
- [ ] **Step 5: Run focused tests.** Expected: all Day-32 tests pass.

### Task 4: Regression, static review, and status evidence

**Files:**
- Modify: `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: verified Day-32 package and test results.
- Produces: auditable Day-32 status entry; no application behavior change.

- [ ] **Step 1: Run focused Day-32 suite.** `pytest tests/test_day32_strategy_lifecycle.py -v`.
- [ ] **Step 2: Run relevant regression suites.** At minimum, execute the established Days 19–32 intelligence/opportunity/strategy tests and the broader backend regression boundary used for Day 31. Record exact counts and any pre-existing failures separately.
- [ ] **Step 3: Run static checks.** Run `python -m compileall`/`py_compile` for changed Python files, `git diff --check`, and the repository's applicable secret/scope checks. Verify no DB/API/frontend/broker files changed.
- [ ] **Step 4: Review the diff.** Confirm only Day-32 files, the approved design/plan, and the status tracker changed; no Day-33 risk or execution semantics entered the diff.
- [ ] **Step 5: Record verification evidence and gate outcome.** Update the Day-32 tracker entry only with fresh evidence from the exact verified commit.
- [ ] **Step 6: Commit the coherent Day-32 work.** Use a Day-32-specific commit message; do not merge or deploy.

---

## Gate

**Opportunity Gate PASS** only when:

1. A valid Day-28 Opportunity can deterministically produce a Strategy Candidate.
2. Day-30 ranked strikes are connected by stable identity without changing ranking mathematics.
3. Day-31 Strategy Evaluation is required and preserved; incomplete evaluation cannot silently become eligible.
4. Lifecycle state and blocking reasons are explicit and deterministic.
5. Missing values remain missing; quality remains separate from confidence and eligibility.
6. Opportunity provenance and evaluation/factor provenance remain distinct and preserved.
7. The same canonical strategy remains context-equivalent across Day-31 contexts.
8. No risk authorization, user approval, broker order, execution intent, DB persistence, API, frontend, ML, or AI capability is introduced.
9. Focused and regression tests pass with no unexplained new failures.
10. Static/purity/scope review is clean.

A PASS unlocks **Day 33 — Central Risk Engine Contract**. A failed gate stops the sequence.
