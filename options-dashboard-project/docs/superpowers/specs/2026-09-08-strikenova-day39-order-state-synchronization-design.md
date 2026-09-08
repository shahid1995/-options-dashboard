# Day 39 Design — Order-State Synchronization

Status: DESIGN APPROVED — implementation not yet started.

## 1. Purpose

Day 39 introduces the broker-state synchronization boundary required between the Day 38 lifecycle foundation and the Day 40 Upstox order-execution adapter.

The goal is to make **normal broker order/fill state propagation event-driven**, idempotent, tenant-safe, and auditable, while defining an explicit exceptional recovery path for reconnects/restarts and missed events.

Day 39 does not enable unrestricted live execution and does not replace broker truth or the existing authoritative paper-trading models.

## 2. Governing Architecture

The Master Implementation Plan defines Day 39 as:

- consume broker order/fill events where supported;
- update local normalized state idempotently;
- define reconnect/restart recovery for missed events;
- do not introduce continuous polling reconciliation as the normal path.

The production transactional system of record remains PostgreSQL. Alembic remains the sole schema authority. Broker truth remains authoritative for actual broker orders, fills, positions, and account state.

Day 38 remains the lifecycle/replay foundation. Its replay functions reconstruct state deterministically and do not write authoritative state.

## 3. Scope Boundary

### In scope

1. Canonical broker-event synchronization contract.
2. Provider-specific event normalization boundary.
3. Idempotent ingestion and normalized local projection/update semantics.
4. Explicit handling for duplicate, malformed, out-of-order, unknown, and terminal events.
5. Reconnect/restart recovery semantics.
6. Bounded exceptional recovery retrieval interface, without making polling the normal path.
7. Auditability and tenant isolation.
8. Unit, integration, PostgreSQL, and regression tests for the above.

### Out of scope

- Actual live order placement.
- Live modify/cancel wiring.
- Production broker credentials.
- Production deployment or cutover.
- Continuous background polling reconciliation.
- Replacing `StrategyExecution`, `PaperOrder`, `Position`, or broker truth as authoritative state.
- Distributed event infrastructure or microservice extraction.
- Changing Day 38 lifecycle semantics.
- Day 40 execution-adapter work.
- Day 41 execution-safety hardening.

## 4. Synchronization Flow

Normal path:

```text
Broker event stream / webhook where supported
            |
            v
Provider-specific adapter
            |
            v
Canonical BrokerEvent
            |
            v
Tenant + identity validation
            |
            v
Idempotency / ordering guard
            |
            v
Lifecycle event / normalized projection update
            |
            v
Authoritative local normalized state
```

Recovery path:

```text
stream disconnect / process restart / detected gap
            |
            v
mark synchronization state as recovering
            |
            v
bounded broker history/order-fill retrieval
            |
            v
normalize recovered records
            |
            v
idempotently apply missing events
            |
            v
validate continuity / terminal state
            |
            v
resume event stream
```

Recovery retrieval is exceptional and bounded. It is not a timer-driven reconciliation loop.

## 5. Canonical Broker Event Contract

The synchronization layer must consume a broker-neutral event structure containing, at minimum:

- tenant/user identity;
- broker identity;
- canonical event identity;
- provider event identity when available;
- event type;
- broker order identity when available;
- canonical execution/order/fill references when available;
- event timestamp from the broker where available;
- received timestamp;
- source/mode metadata;
- payload version/schema version;
- normalized status or fill information;
- provenance sufficient to diagnose the source.

Provider-specific fields remain inside the adapter boundary. Domain consumers must not branch on Upstox field names, status strings, URLs, or raw payload structures.

## 6. Event Identity and Idempotency

Canonical identity must be deterministic and tenant-scoped.

Required semantics:

- identical event received again → no duplicate state mutation;
- same event identity with conflicting canonical content → reject as conflict;
- duplicate recovered event → harmless no-op;
- event identity must never permit cross-tenant reuse;
- idempotency must be enforced transactionally at the PostgreSQL boundary.

Where the provider lacks a durable event ID, the adapter must derive a deterministic identity from stable provider order/fill identifiers plus event type and the minimum additional fields necessary to distinguish legitimate state changes. The derivation must be documented and tested.

## 7. Ordering and Continuity

Where the broker provides sequence information, the synchronization layer records and validates it.

Rules:

- strictly increasing contiguous sequence → normal apply;
- duplicate sequence with identical event → idempotent no-op;
- sequence gap → enter recovery path rather than silently applying an incomplete stream;
- stale/out-of-order event → reject or quarantine according to the canonical event contract;
- no provider sequence available → use deterministic event identity and broker timestamps/order identifiers, without inventing false sequence guarantees.

Day 39 must not claim stronger ordering guarantees than the broker actually provides.

## 8. State-Transition Semantics

The synchronization layer does not create a second lifecycle state machine. It translates authoritative broker observations into the existing canonical lifecycle vocabulary and invokes the Day 38 lifecycle semantics.

Examples:

```text
broker order accepted      -> normalized OrderSubmitted
broker partial fill        -> normalized fill + PARTIALLY_FILLED projection
broker complete fill       -> normalized fill + FILLED projection
broker cancellation        -> normalized OrderCancelled
broker rejection           -> normalized OrderRejected
```

A broker communication failure is not automatically an order rejection.

Unknown or malformed provider states fail closed and remain observable for recovery/diagnostics.

## 9. Authoritative-State Rule

Broker truth is authoritative for actual broker order/fill state.

The local synchronized state is a normalized projection/cache/audit representation used by StrikeNova services. A local projection must never silently override a broker-confirmed state.

Day 39 therefore distinguishes:

```text
broker observation
    !=
StrikeNova derived interpretation
    !=
local projection
```

Any future conflict-resolution policy must preserve broker authority.

## 10. Reconnect and Restart Recovery

The synchronization subsystem must persist enough durable state to determine whether recovery is required. At minimum, recovery state must identify:

- tenant/broker connection;
- last successfully applied provider event/sequence where supported;
- synchronization status;
- recovery reason;
- recovery attempt metadata where required for diagnostics.

On restart, the process must not assume in-memory state is complete. It must restore the durable cursor/state and either resume safely or enter recovery.

On stream reconnect, the subsystem must determine whether events may have been missed. If the broker supplies sequence continuity, a gap triggers recovery. Otherwise the documented provider-specific recovery strategy is used.

Recovery is complete only when the system can establish the required continuity boundary and safely resume normal event-driven processing.

## 11. Exceptional Recovery Contract

Recovery retrieval must be a bounded operation such as:

```text
recover(connection, from_cursor, to_cursor_or_now)
```

It must:

1. fetch a bounded history window;
2. normalize broker records through the same canonical adapter boundary;
3. feed records through the same idempotent ingestion path;
4. never create duplicate lifecycle events;
5. report unresolved gaps explicitly;
6. leave the connection in a recoverable/failed state rather than pretending success.

There must be no always-on `while True: fetch orders; compare; reconcile` implementation.

## 12. Failure Semantics

The implementation must explicitly test:

- duplicate broker event;
- conflicting duplicate event;
- malformed event;
- unknown broker order ID;
- unknown status;
- terminal order receiving another event;
- partial fill followed by full fill;
- cancellation after partial fill;
- disconnect during event processing;
- restart with durable cursor;
- provider sequence gap;
- out-of-order event;
- recovery replay of already-applied events;
- tenant mismatch;
- broker authentication/session expiry;
- recovery failure.

No failure mode may silently corrupt normalized state.

## 13. Persistence and Transaction Boundary

Any synchronization cursor, event-ingestion record, or durable recovery state introduced by Day 39 must use PostgreSQL-compatible schema and Alembic migrations.

The transaction boundary must ensure that event application and its idempotency marker cannot commit independently.

If processing fails, the event's durable application and associated synchronization bookkeeping must roll back together unless the event is intentionally quarantined by an explicitly designed and tested mechanism.

## 14. Testing Strategy

### Unit tests

- canonical event construction;
- provider normalization;
- deterministic identity;
- duplicate/conflict semantics;
- ordering/continuity rules;
- transition mapping;
- recovery state decisions.

### PostgreSQL integration

- transactional idempotency;
- concurrent duplicate writers;
- tenant isolation;
- durable cursor behavior;
- rollback semantics;
- recovery replay.

SQLite may be used for deterministic local tests where appropriate, but it is not accepted as proof of PostgreSQL concurrency behavior.

### Regression

Day 38 lifecycle/replay tests and relevant existing broker/paper tests must continue to pass. Existing protected paper and broker foundations must remain unchanged unless a concrete Day 39 defect requires a narrowly justified change.

## 15. Security and Operational Invariants

- Broker credentials never enter canonical event payloads or logs.
- Tenant identity is validated before applying an event.
- Raw broker payloads remain adapter-boundary data.
- No synchronization event authorizes an order by itself.
- No live execution is enabled by Day 39.
- No production deployment or cutover occurs as part of Day 39.
- Recovery cannot mutate the existing staging database destructively.

## 16. Exit Gate

Day 39 is PASS only when:

> Normal broker order/fill synchronization is event-driven, canonical, idempotent, tenant-safe and auditable; reconnect/restart/missed-event recovery is explicit and bounded; recovery is exceptional rather than continuous polling; broker truth remains authoritative; Day 38 lifecycle semantics remain unchanged; PostgreSQL transactional behavior is verified; and focused + relevant regression tests pass.

## 17. Architectural Decision

**Recommended and approved:** implement a canonical event-driven synchronization boundary with provider adapters, transactional idempotency, durable synchronization cursors, and bounded exceptional recovery. Do not implement a polling reconciler as the normal operating mechanism.
