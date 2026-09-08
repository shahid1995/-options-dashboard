# Day 39 Implementation Plan — Order-State Synchronization

> **Status:** PLAN APPROVED — implementation not yet started.
>
> **Required implementation method:** TDD + task-by-task execution using Superpowers execution/subagent workflow. Hermes Agent is the implementation worker. No deployment, production cutover, merge, or live execution is authorized by this plan.

## Goal

Build the Day 39 broker-state synchronization boundary so that normal order/fill updates are event-driven, canonical, idempotent and tenant-safe, while reconnect/restart/missed-event recovery is explicit and exceptional.

## Governing references

- Master Implementation Plan: `docs/superpowers/plans/2026-09-02-strikenova-architecture-blueprint-v1-master-implementation-plan.md`
- Day 39 design: `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`
- Day 38 lifecycle design: `docs/superpowers/specs/2026-09-05-strikenova-day38-trade-lifecycle-design.md`
- Day 38 lifecycle implementation/tests already approved at the current branch baseline.

## Global constraints

1. PostgreSQL is production transactional SoR.
2. Alembic is sole schema authority.
3. Broker truth remains authoritative for actual broker order/fill state.
4. Provider-specific concepts remain inside broker adapters.
5. Day 38 lifecycle/replay semantics must not be changed casually.
6. No continuous polling reconciliation as normal operation.
7. Recovery retrieval is bounded and exceptional.
8. No live order placement/modify/cancel wiring; that is Day 40.
9. No production credentials, deployment, cutover, or destructive changes to existing staging DB.
10. Tenant isolation is mandatory.
11. Every task follows failing test → minimal implementation → focused pass → relevant regression → diff/scope review.

---

# Task 1 — Canonical broker-event synchronization contract

## Objective

Define the broker-neutral event and synchronization contracts required by the normal event-driven path and recovery path.

## Inspect first

- existing broker domain models/enums/errors;
- `BrokerAdapter` protocol and Upstox adapter boundary;
- Day 37 event envelope;
- Day 38 lifecycle event types/replay contracts;
- existing order/fill/paper models and services.

## TDD

Write failing tests first for:

- required canonical event identity fields;
- tenant/broker/connection context;
- event type/version;
- provider identity/provenance;
- event and received timestamps;
- optional provider sequence;
- normalized order/fill state;
- immutable input/output semantics where appropriate;
- no broker-specific fields in the domain contract.

## Implementation

Add the smallest canonical contract required by the design. Reuse existing Day 37/38 primitives where compatible; do not duplicate an existing event envelope.

## Verification

Focused unit tests + relevant Day 37/38 regression tests.

## Scope gate

No provider-specific normalization logic in the generic domain contract.

---

# Task 2 — Idempotent broker-event ingestion and normalized projection

## Objective

Consume canonical broker events exactly once semantically and apply normalized local state updates transactionally.

## TDD

Write failing tests for:

1. first event applies;
2. identical duplicate is a no-op;
3. conflicting same identity is rejected;
4. tenant mismatch is rejected;
5. malformed event is rejected;
6. terminal state cannot be mutated illegally;
7. partial fill and final fill produce correct normalized state;
8. cancellation/rejection map correctly;
9. event application and idempotency bookkeeping share one transaction;
10. failed processing rolls back durable application state.

## Implementation

Introduce the narrowest ingestion/projection service possible. The service should:

```text
validate → deduplicate → map lifecycle semantics → persist projection/audit → commit
```

It must not contain provider-specific parsing.

## Verification

Focused tests, then Day 38 lifecycle regression and relevant paper-order tests.

---

# Task 3 — Upstox event normalization boundary

## Objective

Create the provider-specific mapping layer needed to convert supported Upstox order/fill events into canonical broker events.

## TDD

Use fixtures representing supported provider event shapes and test:

- accepted/active order;
- partial fill;
- full fill;
- cancellation;
- rejection;
- repeated provider event;
- malformed payload;
- missing provider identifier;
- unknown status;
- provider timestamps/sequence where available;
- credential absence from normalized event/log output.

## Implementation constraints

- Keep Upstox field names and status strings inside the adapter.
- Do not wire actual order submission.
- Do not invent provider sequence semantics when unavailable.
- Map communication failure to a canonical synchronization/recovery error, not to order rejection.

## Verification

Focused Upstox adapter tests + broker canonical contract tests + relevant existing Upstox regression.

---

# Task 4 — Reconnect/restart and exceptional recovery

## Objective

Persist enough synchronization state to detect and recover from missed broker events without continuous polling.

## TDD

Write failing tests for:

- clean startup with no cursor;
- restart with durable cursor;
- reconnect with contiguous provider sequence;
- reconnect with sequence gap;
- recovery of already-applied events is idempotent;
- bounded recovery window;
- recovery failure remains observable;
- unresolved gap does not produce false synchronized state;
- successful recovery permits normal event processing to resume.

## Persistence

If a durable cursor/recovery-state table is required, add it through Alembic using the production PostgreSQL contract. Follow Expand → Migrate → Contract discipline where the change touches existing production structures.

## Recovery rules

Recovery must be a bounded operation, not a continuously scheduled reconciler. The same canonical ingestion path must process recovered events.

## Verification

PostgreSQL integration tests for durability, rollback, idempotency and concurrent duplicate recovery writers.

---

# Task 5 — End-to-end synchronization integration

## Objective

Prove the complete Day 39 flow without live broker execution.

## TDD scenarios

At minimum:

```text
order created
→ provider event
→ canonical event
→ normalized order state

partial fill
→ canonical fill event
→ PARTIALLY_FILLED

final fill
→ canonical fill event
→ FILLED

cancel
→ CANCELLED

reject
→ REJECTED
```

Recovery scenario:

```text
provider events 1,2,3
       ↓
process 1,2
       ↓
restart / disconnect
       ↓
recover 3
       ↓
resume stream
       ↓
no duplicate state transition
```

Gap scenario:

```text
1,2,4
 ↓
sequence gap
 ↓
recovery
 ↓
3 recovered
 ↓
4 applied
```

## Safety scenarios

- duplicate event;
- conflicting duplicate;
- cross-tenant event;
- unknown order;
- malformed event;
- terminal event mutation;
- recovery replay;
- recovery failure;
- broker session expiry;
- no raw credential leakage.

## Verification

Focused Day 39 suite + Day 38 suite + broker/paper regression + PostgreSQL integration/concurrency suite.

---

# Task 6 — Final audit and Day 39 gate

## Objective

Verify that the implementation stayed within the approved architecture and has not accidentally introduced Day 40/41 functionality.

## Audit checklist

- normal path is event-driven;
- no continuous polling reconciler introduced;
- recovery is bounded and exceptional;
- broker truth remains authoritative;
- no live order submission introduced;
- no modify/cancel wiring introduced;
- no production deployment;
- no production/staging credentials committed;
- tenant isolation verified;
- provider-specific concepts remain adapter-bound;
- Day 38 replay/lifecycle behavior unchanged unless explicitly justified;
- Alembic migrations clean;
- PostgreSQL integration verified;
- no unrelated files changed;
- tests and verification evidence recorded.

## Required evidence

1. exact Git diff;
2. focused test results;
3. relevant regression results;
4. PostgreSQL integration results;
5. concurrency results where applicable;
6. migration verification;
7. protected-file audit;
8. deployment-state confirmation;
9. unresolved risks, if any.

## Day 39 Gate

**PASS only if:**

> Normal operation is event-driven; canonical broker order/fill events update local normalized state idempotently and tenant-safely; reconnect/restart/missed-event recovery is explicit, bounded and tested; continuous polling reconciliation is absent from the normal path; broker truth remains authoritative; Day 38 lifecycle semantics remain intact; and all required focused, regression, PostgreSQL and concurrency verification passes.

---

# Execution Protocol for Hermes Agent

Before starting each task:

1. Re-read this plan's task.
2. Inspect current repository state and previous task evidence.
3. Do not assume an interface exists because a report says it exists.
4. Write failing tests first.
5. Implement the smallest compatible change.
6. Run focused tests.
7. Run relevant regression tests.
8. Inspect exact diff.
9. Report evidence and risks.
10. Commit only coherent task work.
11. Stop if the task gate fails.
12. Do not start the next task until the current task is explicitly accepted by the Control Center.

## Forbidden actions

- deployment;
- production/staging database mutation except explicitly authorized disposable verification;
- production broker execution;
- adding a polling reconciliation loop;
- bypassing Alembic;
- changing Day 38 semantics without an approved design correction;
- treating broker communication errors as broker order rejection;
- exposing credentials in events/logs/tests;
- broad refactoring unrelated to Day 39.
