# StrikeNova Day 38 — Trade Lifecycle State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic, append-only trade lifecycle events and replay/state-reconstruction semantics for execution and position lifecycles without replacing the existing authoritative paper-trading state.

**Architecture:** Add a durable lifecycle/audit event layer beside the existing paper-trading model. `StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, and related paper-engine state remain authoritative; lifecycle events record and replay lifecycle facts without performing write-back or duplicating existing accounting/netting logic. Execution lifecycle replay and position lifecycle replay are separate state machines sharing the same immutable event store and transaction/idempotency rules.

**Tech Stack:** Python 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.43, Alembic 1.15.2, PostgreSQL 16, pytest/pytest-asyncio, existing StrikeNova paper-execution services and models.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-05-strikenova-day38-trade-lifecycle-design.md`

## Global Constraints

- PostgreSQL is the production transactional system of record; SQLite remains only where explicitly supported for local development/test compatibility.
- Alembic is the sole authoritative schema-management mechanism.
- Production schema changes use `Expand → Migrate → Contract`.
- Broker truth remains authoritative for actual broker orders, fills, positions, account state and broker-provided values.
- The lifecycle event stream is an append-only audit/reconstruction layer; it does not replace authoritative paper or broker state.
- Execution lifecycle replay and position reconstruction are separate concerns.
- Position identity is `(user_id, symbol, expiry, strike, option_type)` and reconstructed position quantity is the sum of signed `quantity_delta` values.
- A lifecycle instance is scoped to one position identity plus `position_sequence`; a later `PositionOpened` creates a new lifecycle instance after a previous instance closes.
- `position_sequence` allocation is concurrency-safe and scoped by the complete PositionIdentity.
- `position_sequence` and `quantity_delta` are relational database columns, not payload-only values.
- Duplicate events are idempotent only when their canonical content is identical; reuse of an event ID with different content is rejected.
- Reuse of the same aggregate sequence with different content is rejected.
- Replay rejects sequence gaps, tenant mismatches, terminal-state mutations, and invalid transitions deterministically.
- A zero-crossing position update is decomposed into close-to-zero plus open-of-remainder events rather than allowing a single event to cross lifecycle boundaries.
- `PositionClosed` carries the signed final delta that brings the reconstructed net quantity to zero.
- SQLite deterministic tests do not constitute proof of concurrency correctness; PostgreSQL integration tests are required for allocation/rollback/concurrency behavior.
- No production deployment, Railway database mutation, live broker execution, cutover, or merge is part of Day 38.
- Every implementation task follows TDD: failing test → minimal implementation → focused pass → relevant regression → commit.

---

## Repository Baseline and Intended File Map

Before implementation, inspect the current branch and follow established module/test conventions. Do not create duplicate domain abstractions if an existing equivalent boundary already exists.

**Expected files/areas:**

- Inspect: `options-dashboard-project/backend/app/models.py` — existing authoritative `StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, and related paper-trading models.
- Inspect: `options-dashboard-project/backend/app/services/paper_execution.py` — existing authoritative paper execution/position/accounting path.
- Inspect: `options-dashboard-project/backend/tests/test_paper_execution.py` — regression contract for existing paper execution behavior.
- Create or modify: `options-dashboard-project/backend/app/models.py` — only if the repository convention requires ORM models to live here; add lifecycle event/sequence-anchor models without changing existing paper semantics.
- Create: `options-dashboard-project/backend/app/services/trade_lifecycle.py` — lifecycle event envelope, validation, append/idempotency, replay, and position-sequence allocation boundary unless an existing domain-service location is clearly more appropriate.
- Create: `options-dashboard-project/backend/tests/test_trade_lifecycle.py` — deterministic domain/replay/transition/idempotency tests.
- Create: `options-dashboard-project/backend/tests/test_trade_lifecycle_postgres.py` — PostgreSQL-only transaction/concurrency/rollback integration tests, using the repository's existing PostgreSQL test fixture conventions.
- Create: `options-dashboard-project/backend/alembic/versions/<revision>_trade_lifecycle_events.py` — Alembic migration for lifecycle persistence and constraints, following the repository's existing revision naming convention.
- Inspect/modify: relevant schema/registry exports only if required by existing project import conventions.

Do not modify frontend files during Day 38 unless an existing shared type/test boundary makes a minimal compatibility change unavoidable and the change is explicitly justified in the implementation report.

---

# Task 1: Persistence model and Alembic expansion

**Files:**
- Inspect: `backend/app/models.py`
- Create/Modify: lifecycle ORM model location following repository convention
- Create: `backend/alembic/versions/<revision>_trade_lifecycle_events.py`
- Test: `backend/tests/test_trade_lifecycle.py`

**Interfaces:**
- Produces persistent `TradeLifecycleEvent` records with relational tenant, aggregate, sequence, position identity, position sequence, event type/version, signed quantity delta, event ID, timestamp, and canonical payload/metadata fields.
- Produces `PositionSequenceAnchor` scoped by the complete PositionIdentity.

- [ ] **Step 1: Inspect existing ORM/migration conventions and record exact import/table naming conventions.**

Run:
```bash
cd options-dashboard-project/backend
sed -n '1,260p' app/models.py
grep -R "class .*Base\|__tablename__\|UniqueConstraint\|ForeignKey" -n app/models.py | head -80
ls -1 alembic/versions | tail -20
```

Expected: existing SQLAlchemy/Alembic conventions are identified before adding new objects.

- [ ] **Step 2: Write failing persistence-contract tests.**

Add tests asserting that the lifecycle event persistence contract exposes, at minimum:
```python
def test_lifecycle_event_has_relational_sequence_and_quantity_delta_columns():
    columns = {column.name for column in TradeLifecycleEvent.__table__.columns}
    assert "sequence" in columns
    assert "position_sequence" in columns
    assert "quantity_delta" in columns


def test_position_sequence_uniqueness_is_scoped_to_full_position_identity():
    constraints = [
        constraint
        for constraint in TradeLifecycleEvent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    names = {constraint.name for constraint in constraints}
    assert "uq_trade_lifecycle_position_sequence" in names
```

Use the repository's actual model import path and adapt only names, not semantics.

- [ ] **Step 3: Run the focused tests and verify RED.**

Run:
```bash
pytest backend/tests/test_trade_lifecycle.py -q
```

Expected: FAIL because the lifecycle persistence models/constraints do not yet exist.

- [ ] **Step 4: Implement the minimal ORM persistence model.**

The event model must contain explicit relational fields for:
```text
tenant_id
aggregate_type
aggregate_id
sequence
position identity fields (user_id, symbol, expiry, strike, option_type)
position_sequence
event_type
event_version
quantity_delta
event_id
occurred_at
payload/canonical metadata
```

The sequence-anchor identity must cover the full position identity. Do not use a globally shared position sequence.

- [ ] **Step 5: Add the Alembic migration using Expand semantics.**

Create the lifecycle tables, indexes, foreign keys where compatible with existing ownership models, and uniqueness constraints without modifying/removing existing paper-trading columns.

The position lifecycle uniqueness must distinguish:
```text
(user_id, symbol, expiry, strike, option_type, position_sequence)
```

The aggregate execution stream must enforce the required aggregate/sequence uniqueness.

- [ ] **Step 6: Run model tests and migration syntax verification.**

Run:
```bash
pytest backend/tests/test_trade_lifecycle.py -q
python -m compileall backend/app backend/alembic
```

Expected: focused persistence tests PASS; Python compilation succeeds.

- [ ] **Step 7: Commit the persistence slice.**

Run:
```bash
git add backend/app backend/alembic backend/tests/test_trade_lifecycle.py
git commit -m "feat(day38): add lifecycle event persistence foundation"
```

---

# Task 2: Immutable lifecycle event envelope and canonical identity

**Files:**
- Create/Modify: `backend/app/services/trade_lifecycle.py`
- Test: `backend/tests/test_trade_lifecycle.py`

**Interfaces:**
- Produces an immutable event representation with deterministic canonical content.
- Provides event identity/content comparison used by append idempotency.

- [ ] **Step 1: Write failing event-envelope tests.**

```python
def test_event_envelope_contains_explicit_lifecycle_fields():
    event = make_event(
        event_id="evt-1",
        tenant_id="tenant-a",
        aggregate_type="execution",
        aggregate_id="exec-1",
        sequence=1,
        event_type="ExecutionActivated",
        quantity_delta=None,
    )
    assert event.event_id == "evt-1"
    assert event.sequence == 1
    assert event.event_type == "ExecutionActivated"
    assert event.tenant_id == "tenant-a"


def test_canonical_content_is_stable_for_same_event():
    first = make_event(...)
    second = make_event(...)
    assert canonical_event_content(first) == canonical_event_content(second)
```

- [ ] **Step 2: Run tests to verify RED.**

Run:
```bash
pytest backend/tests/test_trade_lifecycle.py -k "event_envelope or canonical" -q
```

Expected: FAIL because the lifecycle envelope/canonicalization boundary is absent.

- [ ] **Step 3: Implement the minimal immutable event contract.**

Use immutable Python structures (for example frozen dataclasses) and explicit types. Required semantics:
- `event_id` is caller-provided/idempotency identity.
- `aggregate_type` distinguishes execution and position streams.
- `aggregate_id` identifies the execution aggregate or lifecycle aggregate.
- `sequence` is causal aggregate sequence, not lexical ordering of IDs.
- `position_sequence` is present for position lifecycle events.
- `quantity_delta` is signed and relationally persisted for position events.
- `event_version` supports future schema evolution.
- canonical payload serialization is deterministic.

- [ ] **Step 4: Run focused tests.**

Run:
```bash
pytest backend/tests/test_trade_lifecycle.py -k "event_envelope or canonical" -q
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/trade_lifecycle.py backend/tests/test_trade_lifecycle.py
git commit -m "feat(day38): define immutable lifecycle event envelope"
```

---

# Task 3: Execution lifecycle state machine and deterministic replay

**Files:**
- Modify: `backend/app/services/trade_lifecycle.py`
- Test: `backend/tests/test_trade_lifecycle.py`

**Interfaces:**
- `replay_execution_events(events) -> ExecutionLifecycleState`
- Validates causal sequence and state transitions.

- [ ] **Step 1: Write RED tests for valid execution lifecycle.**

Use an explicit valid stream such as:
```python
[
    event("TradeIntentCreated", 1),
    event("ExecutionActivated", 2),
    event("OrderCreated", 3),
    event("OrderSubmitted", 4),
    event("OrderFilled", 5),
    event("FillRecorded", 6),
    event("ExecutionCompleted", 7),
]
```

Assert the reconstructed state is deterministic and terminal only after completion.

- [ ] **Step 2: Write RED tests for invalid transitions and terminal mutation.**

Cover:
```python
# OrderFilled before OrderSubmitted -> reject
# ExecutionCompleted before activation -> reject
# ExecutionFailed after ExecutionCompleted -> reject
# Any lifecycle mutation after a terminal state -> reject
```

- [ ] **Step 3: Write RED test for sequence gaps.**

```python
def test_execution_replay_rejects_sequence_gap():
    events = [event("ExecutionActivated", 1), event("OrderCreated", 3)]
    with pytest.raises(LifecycleSequenceError):
        replay_execution_events(events)
```

- [ ] **Step 4: Run RED tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "execution or transition or sequence_gap" -q
```

Expected: FAIL.

- [ ] **Step 5: Implement the minimal execution state machine.**

Define explicit states and transition validation rather than scattered string checks. Replay must consume the ordered event stream and return a new state object without mutating database state.

Do not introduce broker-specific acceptance logic here; broker semantics belong to later execution days.

- [ ] **Step 6: Run focused execution tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "execution or transition or sequence_gap" -q
```

Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/services/trade_lifecycle.py backend/tests/test_trade_lifecycle.py
git commit -m "feat(day38): add execution lifecycle state machine"
```

---

# Task 4: Position lifecycle replay and sequence semantics

**Files:**
- Modify: `backend/app/services/trade_lifecycle.py`
- Test: `backend/tests/test_trade_lifecycle.py`

**Interfaces:**
- `PositionIdentity = (user_id, symbol, expiry, strike, option_type)`
- `replay_position_events(events) -> PositionLifecycleState`
- `PositionSequenceAllocator.allocate(identity, session) -> int`

- [ ] **Step 1: Write RED tests for signed delta reconstruction.**

```python
def test_position_replay_sums_signed_quantity_deltas():
    events = [
        position_event("PositionOpened", 1, +10),
        position_event("PositionUpdated", 2, -2),
        position_event("PositionClosed", 3, -8),
    ]
    state = replay_position_events(events)
    assert state.net_quantity == 0
    assert state.status == "CLOSED"
```

- [ ] **Step 2: Write RED test for lifecycle reuse.**

```python
def test_closed_position_identity_can_open_new_sequence():
    first = [position_event("PositionOpened", 1, +10, position_sequence=1),
             position_event("PositionClosed", 2, -10, position_sequence=1)]
    second = [position_event("PositionOpened", 1, +5, position_sequence=2)]
    assert replay_position_events(first).status == "CLOSED"
    assert replay_position_events(second).status == "OPEN"
```

- [ ] **Step 3: Write RED test for corrected close semantics.**

The canonical worked example must be:
```text
PositionOpened +10
PositionUpdated -2
PositionClosed -8
net = 0
```

Never encode a `PositionClosed` event with `quantity_delta=0` when a non-zero delta is required to reach zero.

- [ ] **Step 4: Write RED test for zero crossing decomposition.**

```python
def test_zero_crossing_is_close_then_open_new_lifecycle():
    # Existing long +10, incoming signed delta -15.
    result = decompose_position_delta(current_quantity=10, requested_delta=-15)
    assert result == [
        ("PositionClosed", -10),
        ("PositionOpened", -5),
    ]
```

- [ ] **Step 5: Run RED tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "position or zero_crossing" -q
```

Expected: FAIL.

- [ ] **Step 6: Implement minimal position replay and zero-crossing semantics.**

Rules:
- Position quantity = sum of signed `quantity_delta`.
- `PositionOpened` starts a lifecycle instance.
- `PositionUpdated` is valid only while the instance is open and must not cross zero.
- `PositionClosed` must bring quantity exactly to zero.
- Once closed, later mutation of that sequence is rejected.
- A new lifecycle instance uses a new `position_sequence`.
- A zero-crossing request is represented as close-to-zero followed by open-of-remainder.

- [ ] **Step 7: Run focused position tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "position or zero_crossing" -q
```

Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add backend/app/services/trade_lifecycle.py backend/tests/test_trade_lifecycle.py
git commit -m "feat(day38): add deterministic position lifecycle replay"
```

---

# Task 5: Atomic append, duplicate idempotency, conflict rejection, and tenant isolation

**Files:**
- Modify: `backend/app/services/trade_lifecycle.py`
- Test: `backend/tests/test_trade_lifecycle.py`

**Interfaces:**
- `append_lifecycle_event(session, event) -> AppendResult`
- Canonical duplicate/conflict classification.

- [ ] **Step 1: Write RED tests for event-ID idempotency.**

```python
def test_identical_event_id_and_content_is_idempotent():
    first = append(event_id="evt-1", payload={"state": "active"})
    second = append(event_id="evt-1", payload={"state": "active"})
    assert second.idempotent is True
    assert second.persisted_event_id == first.persisted_event_id
```

- [ ] **Step 2: Write RED test for event-ID content conflict.**

```python
def test_same_event_id_with_different_content_is_rejected():
    append(event_id="evt-1", payload={"state": "active"})
    with pytest.raises(LifecycleConflictError):
        append(event_id="evt-1", payload={"state": "failed"})
```

- [ ] **Step 3: Write RED test for aggregate-sequence conflict.**

Identical aggregate + sequence + canonical content is idempotent; different content at the same aggregate sequence is rejected.

- [ ] **Step 4: Write RED test for tenant mismatch.**

An event whose tenant does not match the authenticated/transaction context must fail closed and must not expose another tenant's event contents.

- [ ] **Step 5: Run RED tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "idempotent or conflict or tenant" -q
```

Expected: FAIL.

- [ ] **Step 6: Implement append semantics with transaction-aware lookup.**

The implementation must:
- canonicalize event content before comparison;
- classify exact duplicates as idempotent;
- reject conflicting reuse of `event_id`;
- reject conflicting reuse of aggregate sequence;
- enforce tenant ownership before returning existing event details;
- persist event and any required sequence allocation in the same database transaction.

Do not implement silent last-write-wins behavior.

- [ ] **Step 7: Run focused idempotency/tenant tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "idempotent or conflict or tenant" -q
```

Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add backend/app/services/trade_lifecycle.py backend/tests/test_trade_lifecycle.py
git commit -m "feat(day38): enforce lifecycle append idempotency and conflicts"
```

---

# Task 6: Concurrency-safe position sequence allocation and rollback

**Files:**
- Modify: lifecycle service/model code
- Test: `backend/tests/test_trade_lifecycle_postgres.py`

**Interfaces:**
- `allocate_position_sequence(session, position_identity) -> int`

- [ ] **Step 1: Write RED PostgreSQL transaction tests.**

Cover:
```text
same PositionIdentity, concurrent first allocation -> distinct sequences
same symbol but different expiry -> independent sequence namespace
same symbol/expiry but different option_type -> independent namespace
sequence allocation rollback -> number is not committed as an orphan lifecycle record
```

- [ ] **Step 2: Run the PostgreSQL tests and verify RED.**

Run using the repository's existing PostgreSQL test setup:
```bash
pytest backend/tests/test_trade_lifecycle_postgres.py -q
```

Expected: FAIL because the allocator and persistence transaction are not implemented.

- [ ] **Step 3: Implement transactional allocation.**

Use the repository's SQLAlchemy transaction conventions and PostgreSQL locking/upsert behavior to make first-event allocation concurrency-safe. The anchor identity must be the complete PositionIdentity.

Sequence allocation and first lifecycle event persistence must occur in one transaction so a rollback cannot leave a committed sequence anchor that has no lifecycle event.

- [ ] **Step 4: Run PostgreSQL concurrency tests.**

```bash
pytest backend/tests/test_trade_lifecycle_postgres.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app backend/tests/test_trade_lifecycle_postgres.py
 git commit -m "feat(day38): make position sequence allocation transactional"
```

---

# Task 7: Replay purity and authoritative-state non-interference

**Files:**
- Modify: lifecycle replay service if needed
- Test: `backend/tests/test_trade_lifecycle.py`
- Regression: `backend/tests/test_paper_execution.py`

**Interfaces:**
- Replay functions return reconstructed state and do not mutate authoritative paper records.

- [ ] **Step 1: Write RED replay-purity test.**

Snapshot relevant `StrategyExecution`, `PaperOrder`, `Position`, and `PaperTransaction` values, replay lifecycle events, then assert the snapshots are unchanged.

- [ ] **Step 2: Run the focused purity test and verify RED.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "purity or non_interference" -q
```

Expected: FAIL if replay currently performs write-back.

- [ ] **Step 3: Implement read-only replay.**

Replay must construct in-memory state only. It must not recalculate cash, average price, P&L, exposure, or authoritative position rows; those remain existing paper-engine responsibilities.

- [ ] **Step 4: Run purity test.**

```bash
pytest backend/tests/test_trade_lifecycle.py -k "purity or non_interference" -q
```

Expected: PASS.

- [ ] **Step 5: Run paper-execution regression.**

```bash
pytest backend/tests/test_paper_execution.py -q
```

Expected: PASS with no semantic change to existing paper execution behavior.

- [ ] **Step 6: Commit.**

```bash
git add backend/app backend/tests/test_trade_lifecycle.py backend/tests/test_paper_execution.py
git commit -m "test(day38): prove lifecycle replay does not mutate paper state"
```

---

# Task 8: Integration observation boundary with existing paper execution

**Files:**
- Inspect/Modify: `backend/app/services/paper_execution.py`
- Modify: lifecycle service/tests only as required
- Test: `backend/tests/test_paper_execution.py`

**Interfaces:**
- Existing paper execution remains the authoritative command path.
- Lifecycle recorder may observe/persist lifecycle facts inside the same transaction boundary.

- [ ] **Step 1: Write RED integration test for lifecycle recording alongside a paper execution.**

The test should execute one existing paper trade through the established endpoint/service and assert lifecycle events are recorded for the lifecycle facts selected by the Day38 contract, while authoritative `Position`, cash ledger, fills, and P&L behavior remains unchanged.

- [ ] **Step 2: Run integration test and verify RED.**

```bash
pytest backend/tests/test_paper_execution.py -k "lifecycle" -q
```

Expected: FAIL because paper execution is not yet connected to the lifecycle recorder.

- [ ] **Step 3: Add the smallest observation hook.**

Do not duplicate existing netting/accounting/idempotency logic. Record lifecycle facts at the existing transaction boundary so a failed paper execution cannot leave misleading lifecycle events committed independently.

- [ ] **Step 4: Run lifecycle integration and full paper execution tests.**

```bash
pytest backend/tests/test_paper_execution.py -k "lifecycle" -q
pytest backend/tests/test_paper_execution.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app backend/tests/test_paper_execution.py
 git commit -m "feat(day38): observe paper execution through lifecycle events"
```

---

# Task 9: Comprehensive lifecycle regression and migration verification

**Files:**
- Modify only tests/docs if verification exposes a concrete defect.

- [ ] **Step 1: Run all Day38 lifecycle tests.**

```bash
pytest backend/tests/test_trade_lifecycle.py -q
pytest backend/tests/test_trade_lifecycle_postgres.py -q
```

Expected: all Day38 tests PASS.

- [ ] **Step 2: Run relevant paper-trading regression.**

```bash
pytest backend/tests/test_paper_execution.py -q
```

Expected: PASS.

- [ ] **Step 3: Verify Alembic migration against PostgreSQL.**

Use the repository's supported PostgreSQL test/migration workflow to verify:
- upgrade from the current schema succeeds;
- lifecycle tables/indexes/constraints exist;
- duplicate/constraint behavior matches tests;
- application metadata and migration state agree.

Do not modify Railway production database.

- [ ] **Step 4: Verify no SQLite-only assumption is used for concurrency claims.**

Confirm PostgreSQL-specific tests are the evidence for concurrent first allocation and transaction rollback behavior.

- [ ] **Step 5: Inspect the complete diff for scope creep.**

Run:
```bash
git status --short
git diff --stat <day38-base-sha>..HEAD
git diff --name-only <day38-base-sha>..HEAD
```

Expected: only Day38 lifecycle implementation, tests, migration, and necessary documentation are changed.

- [ ] **Step 6: Run the relevant backend regression suite.**

Run the repository's normal backend test command after the focused suites pass. Do not substitute the full suite for focused TDD evidence.

Expected: no new unexplained failures.

- [ ] **Step 7: Record verification evidence.**

Record exact commands, pass counts, migration verification, concurrency evidence, and any residual non-blocking risks in the Day38 implementation report/status artifact according to repository convention.

- [ ] **Step 8: Commit verification evidence.**

```bash
git add backend docs
 git commit -m "test(day38): verify trade lifecycle state machine"
```

---

# Day38 Exit Gate

Day 38 is **PASS** only when all of the following are demonstrated with fresh evidence:

1. The lifecycle event store is append-only and transactionally persisted.
2. Execution lifecycle transitions are explicit, deterministic, and invalid transitions are rejected.
3. Sequence gaps are rejected.
4. Position lifecycle replay deterministically reconstructs net quantity from signed relational `quantity_delta` values.
5. `PositionClosed` carries the final signed delta that reaches zero.
6. A closed lifecycle can be reused only through a new `position_sequence`.
7. Zero-crossing is decomposed into close-to-zero plus open-of-remainder semantics.
8. Position sequence allocation is scoped to the full PositionIdentity and is concurrency-safe under PostgreSQL.
9. Sequence allocation and first lifecycle-event persistence roll back atomically.
10. Exact duplicate events are idempotent; conflicting duplicate content is rejected.
11. Aggregate sequence conflicts are rejected deterministically.
12. Tenant mismatches fail closed.
13. Replay is deterministic and does not mutate authoritative paper state.
14. Existing paper execution regression tests remain green.
15. Alembic migration verification succeeds against PostgreSQL.
16. No production deployment, Railway production DB mutation, live broker execution, merge, or cutover occurred.
17. Diff review confirms no unrelated architectural changes.

**Gate statement:** Given the same valid lifecycle event stream, replay always reconstructs the same execution and position state; invalid transitions, sequence conflicts, tenant violations, duplicate-content conflicts and zero-crossing violations are rejected deterministically; existing authoritative paper state remains unchanged as the source of truth.

Only after this gate is independently verified does Day 39 become active.
