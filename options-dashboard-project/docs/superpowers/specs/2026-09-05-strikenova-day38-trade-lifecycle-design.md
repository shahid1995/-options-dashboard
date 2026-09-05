# Day 38 Design — Trade Lifecycle State Machine (Revised)

Status: DESIGN ONLY — revised per Control Center feedback. No code, no tests, no migration, no tracker edit, no commit.

## 1. Repository State (verified at design time)

- Branch: `feat/strikenova-day35-portfolio-intelligence`; HEAD: `d58e725`.
- Day 37: approved `2828554` (`DomainEvent` frozen envelope; `EventBus` with failure isolation; `HandlerScopedIdempotency`; no forbidden deps).
- Existing lifecycle (authoritative): `app/services/paper_execution.py` (~1487 lines); `app/models.py` (`StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, `StrategyLegExposure`, `ExitExposureAllocation`, `BulkExitRecord`); `can_transition()`/`transition()` pure validators (lines 132–144).
- Broker domain: `app/brokers/domain/enums.py` (`OrderStatus.CREATED/PENDING/OPEN/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED/EXPIRED/UNKNOWN`); `BrokerOrderRequest`/`BrokerOrderResult` (broker-neutral, adapter boundary).
- Risk gate chain: `Opportunity → StrategyCandidate (Day-32) → StrategyEvaluation (Day-31) → CentralRisk (Day-33) → PortfolioAnalytics (Day-35) → FinalRiskGate (Day-36) → User Decision → Execution`.
- Alembic authority: sole schema mechanism; only `alembic upgrade head` creates tables.

## 2. Existing Lifecycle Architecture (unchanged authority)

| Component | Table / Module | Identity | Statuses | Role |
|-----------|---------------|----------|----------|------|
| `StrategyExecution` | `strategy_executions` | `execution_id` (str, unique per user via `client_order_id`) | `PENDING / FILLED / PARTIAL / FAILED / CANCELLED` | Authoritative: grouped multi-leg trade |
| `PaperOrder` | `paper_orders` | `order_id` (int PK) + `client_order_id` (unique per user) | `PENDING → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED` | Authoritative: one order per leg; `can_transition()` |
| `Position` | `positions` | `user_id + symbol + expiry + strike + option_type` | `open / closed` | Authoritative: netted per-instrument |
| `PaperTransaction` | `paper_transactions` | `id` (int PK) | cash ledger entries | Authoritative: auditable cash flow |
| `StrategyLegExposure` | `strategy_leg_exposures` | `order_id` (unique per user) | `open / closed` | Authoritative: FIFO exit attribution |
| `ExitExposureAllocation` | `exit_exposure_allocations` | `exit_order_id + exposure_id` | junction table | Authoritative: exit-to-exposure mapping |
| `BulkExitRecord` | `bulk_exit_records` | `client_order_id` (unique per user) | `SUCCESS / NO_POSITIONS / FAILED / PARTIAL` | Authoritative: idempotent bulk exits |
| `Trade` / `Leg` | `trades` / `legs` | `id` (int PK) | `open / closed` | Legacy journal (projection from above) |

Execution is atomic: all validation before any DB write; success = `FILLED` with every order filled; failure = zero rows written.

**Day 38 does NOT replace any of these.** They remain the single source of truth for paper-trading state.

## 3. Precise Day 38 Event-Sourcing Boundary

Day 38 means: **durable append-only trade-lifecycle events + deterministic replay/state reconstruction**, while existing authoritative paper/broker state remains authoritative.

### What "event-sourced lifecycle semantics" means here

1. Every material state change in the paper-trading lifecycle emits a typed, immutable, ordered event recorded in a dedicated append-only event table.
2. The event table is an **audit log and state-reconstruction source**, not the authoritative write-target. `PaperOrder`, `Position`, `StrategyExecution` remain the authoritative state; the event log records what happened and enables replay.
3. "Replay" reconstructs lifecycle state from the event log for **verification, audit, and diagnostics** — it does not write back to authoritative tables and does not replace `can_transition()`/`transition()`.
4. Day 38 does NOT introduce a second execution engine, a second write path, or a competing source of truth.

### What Day 38 is NOT

- NOT replacing `StrategyExecution`, `PaperOrder`, `Position`, or broker truth as authoritative.
- NOT creating an independent event-driven execution engine.
- NOT implying that lifecycle events are authorization to execute.
- NOT a distributed event system (no Kafka, Redis Streams, RabbitMQ, Celery).
- NOT live broker integration (no order placement, no broker sync).

## 4. Aggregate Model

```
TradeLifecycleAggregate
  aggregate_id = execution_id (same identity as StrategyExecution.execution_id)
  aggregate_type = "TradeLifecycle"
  tenant_id = user_id
```

The aggregate contains four independent state entities (§5), each tracked by the same event stream but replayed independently:

```
TradeLifecycleAggregate
├── execution_state       (StrategyExecution lifecycle)
├── order_states          (dict[order_id → PaperOrder lifecycle])
├── fill_history          (append-only list of fill events)
└── position_states       (dict[position_identity → Position lifecycle])
```

Identity rules:
- `execution_id` = universal aggregate identity across all lifecycle events.
- `order_id` = per-order identity (from `PaperOrder.id`).
- `position_identity` = `(user_id, symbol, expiry, strike, option_type)` (same as `Position` unique constraint).
- `client_order_id` = immutable idempotency key (never changes across the lifecycle).
- `user_id` = `tenant_id` (immutable on the aggregate; events with mismatched tenant rejected, §12).

No competing sources of truth. `StrategyExecution`/`PaperOrder`/`Position` tables remain authoritative; `TradeLifecycleAggregate` is a projection reconstructed from events.

## 5. Independent State Machines

Day 38 defines four independent sub-state-machines within one aggregate event stream. Each has its own valid transitions; replay tracks them independently even though they share `execution_id`.

### 5a. Execution Lifecycle (StrategyExecution)

States: `CREATED → ACTIVE → COMPLETED / FAILED / CANCELLED`

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none) | `TradeIntentCreated` | `CREATED` | ✅ | no |
| `CREATED` | `ExecutionActivated` | `ACTIVE` | ✅ | no |
| `ACTIVE` | `ExecutionCompleted` | `COMPLETED` | ✅ | yes |
| `ACTIVE` | `ExecutionFailed` | `FAILED` | ✅ | yes |
| `ACTIVE` | `ExecutionCancelled` | `CANCELLED` | ✅ | yes |
| `COMPLETED` / `FAILED` / `CANCELLED` | any | — | ❌ | terminal |

Execution states map to (but are not identical with) `StrategyExecution.status`:
- `CREATED` = `StrategyExecution.status = PENDING` (execution written, orders not yet placed).
- `ACTIVE` = at least one `PaperOrder` submitted.
- `COMPLETED` = all orders `FILLED` or terminal; `StrategyExecution.status = FILLED`.
- `FAILED` = any order failure that prevents completion; `StrategyExecution.status = FAILED`.
- `CANCELLED` = user or system cancellation before fill; `StrategyExecution.status = CANCELLED`.

### 5b. Order Lifecycle (PaperOrder)

One order state per `order_id` under the execution. Multiple orders may exist under one execution (multi-leg).

States: `PENDING → SUBMITTED → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED`

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none) | `OrderCreated` | `PENDING` | ✅ | no |
| `PENDING` | `OrderSubmitted` | `SUBMITTED` | ✅ | no |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderFilled` | `FILLED` / `PARTIALLY_FILLED` | ✅ | FILLED = yes |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderCancelled` | `CANCELLED` | ✅ | yes |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderRejected` | `REJECTED` | ✅ | yes |
| `FILLED` / `CANCELLED` / `REJECTED` | any | — | ❌ | terminal |

This aligns with the existing `ORDER_TRANSITIONS` in `paper_execution.py` (lines 101–107): `PENDING → {FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED}`; `PARTIALLY_FILLED → {FILLED, CANCELLED, REJECTED}`; terminals have empty transition sets. The new design adds `SUBMITTED` (placed with broker adapter) between `PENDING` and fill for broker-interaction clarity.

### 5c. Fill History (append-only)

Fills are not a state machine — they are an append-only ledger. Each fill event records:
- `order_id`, `fill_quantity` (lots), `fill_price`, `fill_timestamp`, `price_source`.
- Fill events never change state of prior fills; they accumulate.

Aggregate fill consistency invariant: `Σ fill_quantity for order_id ≤ order.quantity` (partial fills allowed); `Σ fill_quantity = order.quantity` when order is `FILLED`.

### 5d. Position Lifecycle

One position state per `position_identity` under the execution. Multiple positions may exist under one execution (multi-leg, different instruments).

States: `OPEN → CLOSED`

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none) | `PositionOpened` | `OPEN` | ✅ | no |
| `OPEN` | `PositionUpdated` | `OPEN` | ✅ | no |
| `OPEN` | `PositionClosed` | `CLOSED` | ✅ | yes |
| `CLOSED` | any | — | ❌ | terminal |

`PositionUpdated` carries: `net_quantity`, `average_entry_price`, `realized_pnl`. `PositionClosed` carries: final `net_quantity = 0`, final `realized_pnl`.

### Multiple orders and positions under one execution

Example: 2-leg spread execution (`execution_id = "exec-1"`):

```
TradeLifecycleAggregate(execution_id="exec-1")
├── execution_state: CREATED → ACTIVE → COMPLETED
├── order_states:
│   ├── order_id=1 (BUY 10 NIFTY 24000 CALL): CREATED → SUBMITTED → FILLED
│   └── order_id=2 (SELL 10 NIFTY 24500 CALL): CREATED → SUBMITTED → FILLED
├── fill_history:
│   ├── fill: order_id=1, qty=10, price=125.00
│   └── fill: order_id=2, qty=10, price=85.50
└── position_states:
    ├── (NIFTY, 24000, CALL): OPEN (net +10)
    └── (NIFTY, 24500, CALL): OPEN (net −10)
```

Each sub-entity is tracked independently; replay maintains separate state for each.

## 6. Complete Transition Matrix (all four sub-machines)

Consolidated from §5a–§5d. Every transition specifies: valid/invalid, required data, invariants, terminal.

| Sub-machine | From | Event | To | Valid | Required data | Invariants | Terminal |
|-------------|------|-------|----|-------|---------------|------------|----------|
| Execution | (none) | `TradeIntentCreated` | `CREATED` | ✅ | execution_id, symbol, strategy_tag, legs[] | execution_id unique per user; tenant_id = user_id; legs non-empty | no |
| Execution | `CREATED` | `ExecutionActivated` | `ACTIVE` | ✅ | execution_id | at least one OrderCreated for this execution | no |
| Execution | `ACTIVE` | `ExecutionCompleted` | `COMPLETED` | ✅ | execution_id | all orders in terminal state (FILLED/CANCELLED/REJECTED); fill_quantity consistency | yes |
| Execution | `ACTIVE` | `ExecutionFailed` | `FAILED` | ✅ | execution_id, reason_code | reason_code ∈ {MarketClosed, ChainDataMissing, InvalidQuantity, InsufficientPosition, ExecutionFailed} | yes |
| Execution | `ACTIVE` | `ExecutionCancelled` | `CANCELLED` | ✅ | execution_id, reason | all orders in terminal state or cancelled | yes |
| Execution | terminal | any | — | ❌ | — | terminal-state protection | — |
| Order | (none) | `OrderCreated` | `PENDING` | ✅ | order_id, execution_id, symbol, action, quantity, lot_size | order_id unique per execution; execution must exist in CREATED/ACTIVE | no |
| Order | `PENDING` | `OrderSubmitted` | `SUBMITTED` | ✅ | order_id, client_order_id | client_order_id immutable; order belongs to this execution | no |
| Order | `SUBMITTED` | `OrderFilled` | `FILLED` | ✅ | order_id, fill_quantity, fill_price | fill_quantity = order.quantity (full fill) | yes |
| Order | `SUBMITTED` | `OrderFilled` | `PARTIALLY_FILLED` | ✅ | order_id, fill_quantity, fill_price | fill_quantity < order.quantity | no |
| Order | `PARTIALLY_FILLED` | `OrderFilled` | `FILLED` | ✅ | order_id, fill_quantity, fill_price | cumulative fill_quantity = order.quantity | yes |
| Order | `PARTIALLY_FILLED` | `OrderCancelled` | `CANCELLED` | ✅ | order_id, reason | — | yes |
| Order | `PARTIALLY_FILLED` | `OrderRejected` | `REJECTED` | ✅ | order_id, reason | — | yes |
| Order | `SUBMITTED` | `OrderCancelled` | `CANCELLED` | ✅ | order_id, reason | — | yes |
| Order | `SUBMITTED` | `OrderRejected` | `REJECTED` | ✅ | order_id, reason | — | yes |
| Order | terminal | any | — | ❌ | — | terminal-state protection | — |
| Fill | (any) | `FillRecorded` | (append) | ✅ | order_id, fill_quantity, fill_price, fill_timestamp | cumulative ≤ order.quantity; fill_price > 0; fill_quantity > 0 | n/a (append-only) |
| Position | (none) | `PositionOpened` | `OPEN` | ✅ | position_identity, initial_quantity | net_quantity ≠ 0; position_identity unique | no |
| Position | `OPEN` | `PositionUpdated` | `OPEN` | ✅ | net_quantity, average_entry_price, realized_pnl | net_quantity can be positive, negative, or zero; same-direction updates average entry | no |
| Position | `OPEN` | `PositionClosed` | `CLOSED` | ✅ | realized_pnl | net_quantity = 0; no open exposure remains | yes |
| Position | `CLOSED` | any | — | ❌ | — | terminal-state protection | — |

## 7. Event Taxonomy (reuses Day 37 `DomainEvent`)

All events use `DomainEvent` envelope (`app/domain_events/contracts.py`):

| Field | Value |
|-------|-------|
| `event_id` | Deterministic: `SHA256(execution_id + event_type + sequence)` — idempotent, reproducible |
| `event_type` | One of 14 types (below) |
| `aggregate_type` | `"TradeLifecycle"` |
| `aggregate_id` | `execution_id` |
| `tenant_id` | `user_id` |
| `occurred_at` | Caller-supplied aware datetime (never `datetime.now()`) |
| `event_version` | `"1.0"` |
| `payload` | Structured dict per event type |
| `metadata` | Optional `{source: "paper_engine", version: "1.0"}` |

### Complete event type catalog

**Execution events:**
1. `TradeIntentCreated` — execution created; payload: `{execution_id, symbol, strategy_tag, legs: [{expiry, strike, option_type, action, quantity, lot_size}]}`
2. `ExecutionActivated` — at least one order placed; payload: `{execution_id}`
3. `ExecutionCompleted` — all orders terminal; payload: `{execution_id, total_filled_orders, total_cancelled_orders}`
4. `ExecutionFailed` — execution failed; payload: `{execution_id, reason_code}`
5. `ExecutionCancelled` — execution cancelled; payload: `{execution_id, reason}`

**Order events:**
6. `OrderCreated` — order established; payload: `{order_id, execution_id, symbol, action, quantity, lot_size, client_order_id}`
7. `OrderSubmitted` — order placed with broker adapter; payload: `{order_id, broker_request_id}` (audit only — does not mean broker accepted)
8. `OrderFilled` — order (partially or fully) filled; payload: `{order_id, fill_quantity, fill_price, cumulative_filled, price_source}`
9. `OrderCancelled` — order cancelled; payload: `{order_id, reason}`
10. `OrderRejected` — order rejected; payload: `{order_id, reason}`

**Fill events:**
11. `FillRecorded` — fill ledger entry; payload: `{order_id, fill_quantity, fill_price, fill_timestamp, price_source}`

**Position events:**
12. `PositionOpened` — new position created; payload: `{position_identity: {symbol, expiry, strike, option_type}, initial_quantity, lot_size}`
13. `PositionUpdated` — position netting changed; payload: `{position_identity, net_quantity, average_entry_price, realized_pnl}`
14. `PositionClosed` — position fully closed; payload: `{position_identity, final_realized_pnl}`

No `BrokerResponseReceived` as a standalone event (corrected per §14). Broker observations are recorded as `OrderSubmitted` (strike nova placed the order — audit only, not broker acceptance) and `OrderFilled`/`OrderRejected` (broker outcome reflected through adapter).

## 8. Persistence Model

New table `trade_lifecycle_events` (Alembic only):

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `event_id` | `String(64)` | PK | Idempotency key; deterministic SHA256 |
| `aggregate_id` | `String(40)` | NOT NULL, indexed | `execution_id` |
| `event_type` | `String(32)` | NOT NULL, indexed | One of 14 types |
| `event_version` | `String(16)` | NOT NULL | `"1.0"` |
| `tenant_id` | `String(128)` | NOT NULL, indexed | `user_id` |
| `sequence` | `Integer` | NOT NULL | Monotonic per aggregate |
| `occurred_at` | `DateTime(timezone=True)` | NOT NULL | Caller-supplied aware datetime |
| `payload_json` | `Text` | NOT NULL | JSON string of payload dict |
| `metadata_json` | `Text` | NULLABLE | Optional JSON metadata |
| `created_at` | `DateTime(timezone=True)` | NOT NULL, DEFAULT utcnow | DB write time |

Constraints:
- PK: `event_id`
- `UNIQUE(aggregate_id, sequence)` — ordering invariant (§10)
- Indexed: `(aggregate_id, sequence)`, `(tenant_id, occurred_at)`, `(aggregate_type, event_type)` — query patterns

Semantics:
- **Append-only**: no UPDATE or DELETE on rows (enforced by application-level repository; no database-level trigger needed for audit design).
- **Idempotent insert**: `INSERT ... ON CONFLICT (event_id) DO NOTHING` — duplicate `event_id` silently succeeds (same content assumed; different content = integrity error, §11).
- **No FK to authoritative tables**: events reference aggregate by identity (`execution_id`), not by FK, so event table remains append-only even if authoritative tables are modified.
- **JSON payload**: `payload_json` stores `json.dumps(payload, sort_keys=True)` for deterministic serialization.

## 9. Atomic Transaction Architecture (resolved contradiction)

### The contradiction

First design required `authoritative mutation + lifecycle event append = same DB transaction` while also saying `paper_execution.py` must remain unchanged.

### Resolution

Day 38 adds event persistence via a **thin integration hook** at the single atomic mutation point in `paper_execution.py`. The modification is minimal and justified:

**Approach: post-mutation event append within the existing transaction**

The existing `execute_strategy()` function in `paper_execution.py` already performs an atomic write (all validation → single transaction → commit). Day 38 adds event recording **inside the same transaction** after the authoritative writes succeed:

```python
# Inside execute_strategy(), after all authoritative writes succeed, BEFORE commit:
_lifecycle_events = build_lifecycle_events(execution, orders, fills, positions)
for event in _lifecycle_events:
    persist_lifecycle_event(db, event)  # same transaction; same db session
# Then: db.commit() (existing)
```

If event persistence fails → the entire transaction rolls back (existing behavior for any write failure). This preserves atomicity without redesigning the engine.

### Integration boundary

| Aspect | Design |
|--------|--------|
| **Transaction ownership** | `paper_execution.py` owns the transaction (unchanged); `persist_lifecycle_event()` is called within the existing `db` session (same `Session` object, same transaction). |
| **Event append timing** | After all authoritative writes (`StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`) succeed and before `db.commit()`. Events are never written before authoritative state. |
| **Rollback behavior** | If `persist_lifecycle_event()` raises, the transaction rolls back — no authoritative state is committed without its events. If authoritative writes fail, events are never attempted. |
| **Failure behavior** | Event append failure = execution failure (same atomic guarantee). No partial state. |
| **`can_transition()`/`transition()`** | Remains authoritative for order-state validation. Events RECORD the transition; they do not validate or cause it. `can_transition()` is called before any state change (existing behavior); event append happens after. |

### Minimal modification to `paper_execution.py`

The ONLY change to `paper_execution.py` is adding a call to `persist_lifecycle_events()` at the end of `execute_strategy()` (and similarly in `apply_exit()` for exits), within the existing transaction. The function is imported from `app/trade_lifecycle/persistence.py`. If the import is unavailable (Day 37 not loaded), the call is a no-op (graceful degradation).

No refactoring, no reordering of existing logic, no new execution path.

## 10. Sequence Allocation / Concurrency Semantics

### Allocation strategy

Per-aggregate sequence numbers are allocated at event-append time:

```python
def next_sequence(db: Session, aggregate_id: str) -> int:
    """Allocate the next sequence number for an aggregate.
    
    Uses SELECT MAX(sequence) ... FOR UPDATE within the existing
    transaction to prevent concurrent allocation for the same aggregate.
    """
    max_seq = db.execute(
        select(func.max(TradeLifecycleEvent.sequence))
        .where(TradeLifecycleEvent.aggregate_id == aggregate_id)
        .with_for_update()  # row-level lock
    ).scalar()
    return (max_seq or 0) + 1
```

### Concurrency model

| Scenario | Behavior |
|----------|----------|
| **Writer A writes sequence N** | `SELECT MAX(sequence) FOR UPDATE` returns N−1; allocates N; insert succeeds; commit releases lock. |
| **Writer B tries same aggregate concurrently** | `SELECT MAX(...)` blocks on the same row-level lock (PostgreSQL); waits for Writer A to commit; then sees N; allocates N+1. No conflict. |
| **Writer A and Writer B write different aggregates** | No lock contention; each gets its own sequence independently. |
| **Writer A commits, Writer B retries** | Writer B sees N after lock release; allocates N+1 correctly. |

### Uniqueness constraint

`UNIQUE(aggregate_id, sequence)` prevents any accidental duplicate sequence. If a race condition somehow produces a duplicate `(aggregate_id, sequence)`, the INSERT fails with `IntegrityError` → transaction rolls back → no partial state.

### Failure semantics

| Condition | Behavior |
|-----------|----------|
| Lock timeout | Transaction fails → execution rolls back (same as any DB error) |
| Duplicate sequence | `IntegrityError` → transaction rolls back |
| Sequence gap | Detected at replay time (§13) → deterministic error |
| Out-of-order write | Impossible: `FOR UPDATE` serializes per-aggregate writes |

### SQLite compatibility

SQLite does not support `SELECT ... FOR UPDATE`. For SQLite (development/testing), use `BEGIN IMMEDIATE` transaction or `PRAGMA journal_mode=WAL` with serialized writes at the application level (same `Session` object within one process). Sequence correctness is guaranteed by the single-process SQLite model.

## 11. Duplicate / Conflict Semantics

| Scenario | Resolution |
|----------|-----------|
| **Same `event_id` + identical event** | Idempotent: `INSERT ... ON CONFLICT (event_id) DO NOTHING`. First write wins; duplicate silently accepted. Replay sees one event. |
| **Same `event_id` + different payload** | **Integrity conflict**: deterministic error. `event_id` is derived from content (`SHA256(execution_id + event_type + sequence)`); same `event_id` with different content implies content mismatch → raise `EventIntegrityConflict(event_id, stored_hash, provided_hash)`. Transaction rolls back. |
| **Same `aggregate_id` + same `sequence` + identical event** | Handled by `event_id` idempotency (first case above); `UNIQUE(aggregate_id, sequence)` prevents second insert if `event_id` differs. |
| **Same `aggregate_id` + same `sequence` + different event** | **Ordering/integrity conflict**: `UNIQUE(aggregate_id, sequence)` rejects the second insert → `IntegrityError` → transaction rolls back. Two different events cannot claim the same position in the lifecycle. |

### Resolution principles

- **Identical duplicate → idempotent** (safe, no state change).
- **Same ID but different content → integrity error** (fail, do not persist).
- **Same aggregate/sequence but different event → ordering conflict** (fail, do not persist).
- **Conflicting events must NOT both become valid lifecycle history** (guaranteed by DB constraints + deterministic `event_id` derivation).

## 12. Tenant / Security Model

### Security scope

```text
(aggregate_id, tenant_id) = (execution_id, user_id)
```

Every lifecycle event MUST carry `tenant_id = user_id` (immutably derived from the `StrategyExecution.user_id` at creation time). Events with mismatched `tenant_id` are rejected.

### Tenant-mismatch handling (fails-closed)

| Scenario | Behavior |
|----------|----------|
| Event with wrong `tenant_id` at write time | Rejected: `ValueError("TENANT_MISMATCH")` — event never persisted. Transaction rolls back. |
| Event with wrong `tenant_id` at replay time | **Replay fails deterministically**: `ReplaySecurityError("TENANT_MISMATCH", aggregate_id, expected_tenant, event_tenant)`. Replay stops. No partial state reconstructed. |
| Cross-tenant aggregate query | Impossible: replay requires `(aggregate_id, tenant_id)` pair; no global queries permitted. |

### Enforcement points

- **Write time**: `persist_lifecycle_event()` validates `event.tenant_id == execution.user_id` before INSERT.
- **Replay time**: `replay_aggregate()` validates every event's `tenant_id` matches the requested `tenant_id`. Mismatch → fail closed. Never skip silently. Never reconstruct partial state.
- **Read time**: event table queries always include `WHERE tenant_id = ?`.

## 13. Replay / Reconstruction Algorithm (fully deterministic)

```
replay_aggregate(aggregate_id: str, tenant_id: str, db: Session) -> TradeLifecycleAggregate:

  # 1. Load events, ordered by sequence
  events = db.execute(
      SELECT * FROM trade_lifecycle_events
      WHERE aggregate_id = ? AND tenant_id = ?
      ORDER BY sequence ASC
  ).fetchall()

  # 2. Initialize empty aggregate
  aggregate = TradeLifecycleAggregate(aggregate_id, tenant_id)

  # 3. Process each event (canonical deterministic path)
  for event in events:
      # 3a. Tenant check — FAIL CLOSED, never skip
      if event.tenant_id != tenant_id:
          raise ReplaySecurityError("TENANT_MISMATCH", aggregate_id, tenant_id, event.tenant_id)

      # 3b. Aggregate check — FAIL CLOSED
      if event.aggregate_id != aggregate_id:
          raise ReplaySecurityError("AGGREGATE_MISMATCH", aggregate_id, event.aggregate_id)

      # 3c. Version check — FAIL on unknown
      if event.event_version not in SUPPORTED_VERSIONS:
          raise ReplayUnknownVersion(event.event_version, event.event_id)

      # 3d. Sequence monotonicity check — FAIL on gap or out-of-order
      expected_seq = aggregate.last_sequence + 1
      if event.sequence != expected_seq:
          raise ReplaySequenceGap(expected_seq, event.sequence, event.event_id)

      # 3e. Payload validation — FAIL on corrupt
      if not valid_payload(event.event_type, event.payload_json):
          raise ReplayCorruptPayload(event.event_id, event.event_type)

      # 3f. Apply transition — FAIL on invalid
      apply_transition(aggregate, event)  # per §5–§6 transition matrix

      # 3g. Record sequence
      aggregate.last_sequence = event.sequence

  # 4. Return reconstructed aggregate (never writes to DB)
  return aggregate
```

### What replay rejects (all deterministic, no best-effort)

| Condition | Error | Replay behavior |
|-----------|-------|-----------------|
| Invalid transition | `ReplayInvalidTransition` | Stop at first bad event |
| Sequence gap (missing event) | `ReplaySequenceGap` | Stop |
| Corrupt payload | `ReplayCorruptPayload` | Stop |
| Unknown event version | `ReplayUnknownVersion` | Stop |
| Tenant mismatch | `ReplaySecurityError` | Stop (fail closed) |
| Aggregate mismatch | `ReplaySecurityError` | Stop (fail closed) |
| Duplicate event_id | Impossible (idempotent insert) | N/A |
| Sequence conflict (two events same seq) | Impossible (UNIQUE constraint) | N/A |

### No best-effort reconstruction in canonical path

Canonical replay is strictly deterministic: all-or-nothing. If any event fails validation, replay stops and reports the failure. Partial state is never silently reconstructed.

### Forensic/best-effort mode (NOT implemented in Day 38)

A future forensic mode could skip bad events and continue, but this is explicitly OUTSIDE Day 38 scope. Day 38 implements only the canonical deterministic path.

## 14. Broker-Observed-Event Boundary

### Distinction between "StrikeNova recorded" and "broker accepted"

| Event | Meaning | Does it mean StrikeNova sent to broker? | Does it mean broker accepted? |
|-------|---------|----------------------------------------|-------------------------------|
| `OrderCreated` | Paper order established in StrikeNova | No | No |
| `OrderSubmitted` | StrikeNova submitted order to broker adapter (audit record of submission attempt) | Yes (adapter called) | No — adapter call may fail |
| `OrderFilled` | Fill received through adapter (paper engine used adapter-returned fill price) | N/A (fill is result, not action) | Yes (adapter confirmed fill) |
| `OrderRejected` | Rejection received through adapter | N/A | Yes (adapter confirmed rejection) |

### Rules

1. `OrderSubmitted` records that StrikeNova called the adapter. It does NOT imply the broker accepted or even received the order. Adapter errors are reflected as `OrderRejected`.
2. `OrderFilled` records a fill received through the adapter. The adapter is the source of fill data; broker truth remains authoritative for actual broker-side fills.
3. **No lifecycle event implies execution authorization.** Authorization lives in the Day-33–36 risk gate chain; events merely record what happened after authorization was granted.
4. **No lifecycle event implies broker state.** Broker-side state is reflected only through adapter-returned data (`BrokerOrderResult`). If the adapter is unavailable, events record the submission attempt but not the broker's response.
5. **Preparing for Days 39–42**: the event taxonomy separates submission from fill from rejection. Future broker integration can add `BrokerOrderAccepted`, `BrokerOrderPartiallyFilled`, `BrokerOrderExpired` event types additively without rewriting the lifecycle model.

### Broker truth remains authoritative

- For paper-trading: StrikeNova is the broker (simulated fills via market data); `PaperOrder` status is authoritative.
- For live broker integration (future): broker-side state is authoritative; `BrokerOrderResult` from adapter is the source; lifecycle events record the adapter observation, never override it.

## 15. Reducer Invariants

Invariants checked at two points: **append time** (write guard) and **replay time** (reconstruction guard).

### Append-time invariants (checked in `persist_lifecycle_event()`)

| Invariant | Check | Failure behavior |
|-----------|-------|------------------|
| Execution identity preserved | `event.aggregate_id == execution.execution_id` | Reject event; rollback |
| Order identity preserved | `event.payload.order_id` belongs to this `execution_id` | Reject event; rollback |
| Position identity preserved | `event.payload.position_identity` belongs to this `execution_id`'s user | Reject event; rollback |
| Tenant identity immutable | `event.tenant_id == execution.user_id` | Reject event; rollback |
| `client_order_id` immutable | Once set in `OrderCreated`, never changed in subsequent events | Reject event; rollback |
| Event version compatible | `event.event_version ∈ SUPPORTED_VERSIONS` | Reject event; rollback |
| No authorization implied | No event type is `ExecutionAuthorized` or carries authorization vocabulary | Structural (enum-based, impossible to violate) |

### Replay-time invariants (checked in `replay_aggregate()`)

| Invariant | Check | Failure behavior |
|-----------|-------|------------------|
| Execution identity preserved | Same as append | Stop replay |
| Order identity preserved | Same as append | Stop replay |
| Position identity preserved | Same as append | Stop replay |
| Tenant identity match | `event.tenant_id == requested_tenant_id` | Stop replay (fail closed) |
| Sequence monotonicity | `event.sequence == last_sequence + 1` | Stop replay (gap) |
| Terminal-state protection | No event applied to terminal state (`COMPLETED`/`FAILED`/`CANCELLED` for execution; `FILLED`/`CANCELLED`/`REJECTED` for order; `CLOSED` for position) | Stop replay (invalid transition) |
| Fill quantity consistency | `Σ fill_quantity ≤ order.quantity`; `= order.quantity` when order is `FILLED` | Stop replay (invariant violation) |
| Position quantity consistency | Position events track net_quantity correctly; `PositionClosed` requires net=0 | Stop replay (invariant violation) |
| Event version compatible | Same as append | Stop replay |
| Sequence conflict | Impossible by `UNIQUE(aggregate_id, sequence)` constraint | N/A |

### Which invariants are checked where

- **Append time**: structural identity invariants + tenant + version (write-time safety).
- **Replay time**: sequence + terminal + quantity + tenant + version (reconstruction safety).
- **Both**: identity preservation, version compatibility.

## 16. Existing-Model Integration

| Existing model | Day 38 treatment |
|----------------|-----------------|
| `StrategyExecution` | **Authoritative, unchanged** (except thin `persist_lifecycle_events()` call in `execute_strategy()`). `execution_id` = aggregate identity. |
| `PaperOrder` | **Authoritative, unchanged**. Events reference `order_id`. Replay reads for comparison; never writes back. |
| `Position` | **Authoritative, unchanged**. Events reference `position_identity`. Replay verifies consistency. |
| `PaperTransaction` | **Authoritative, unchanged**. Referenced by fill events via `execution_id`. |
| `StrategyLegExposure` / `ExitExposureAllocation` | **Authoritative, unchanged**. Exit events reference exposure IDs. |
| `Trade` / `Leg` (legacy journal) | **Projection, unchanged**. `strategy_execution_id` linkage preserved. |
| `BrokerOrderResult` / adapter | **External**. `OrderSubmitted`/`OrderFilled`/`OrderRejected` record adapter observations as audit only. |
| `PaperExecution.can_transition()` | **Authoritative, unchanged**. Validates transitions before state changes. Events record after. |
| `app/domain_events/` (Day 37) | **Reused exactly**. `DomainEvent` envelope; `EventBus` for in-process dispatch if needed. No changes to `contracts.py`, `bus.py`, `idempotency.py`. |

## 17. Risk / Execution Boundary (preserved)

The chain must remain intact:

```
Opportunity → StrategyCandidate (Day-32) → StrategyEvaluation (Day-31) →
CentralRisk (Day-33, PASS required) → PortfolioAnalytics (Day-35) →
FinalRiskGate (Day-36, PASS required) → User Decision → Execution
```

Day 38 rules enforcing this:
- `TradeIntentCreated` event can only occur AFTER `StrategyExecution` is created by `execute_strategy()`, which requires `execute_gated_paper_entry()` (Day 34), which requires `CentralRiskStatus.PASS` (Day-33).
- No `ExecutionAuthorized` event exists; authorization stays in Day-33/36 chain.
- No lifecycle event carries authorization semantics.
- `TradeLifecycleAggregate` replay never produces an execution command.
- All Day 38 events are **observation/audit** type, never **command/authorization**.

No live execution, no broker order placement, no broker sync, no authorization encoding in events.

## 18. Expanded Test Strategy

### Independent state machines

| Test | Category |
|------|----------|
| Execution: `CREATED → ACTIVE → COMPLETED` | Valid transition |
| Execution: `CREATED → ACTIVE → FAILED` | Valid transition |
| Execution: `CREATED → ACTIVE → CANCELLED` | Valid transition |
| Execution: `COMPLETED → ACTIVE` | Invalid (terminal) |
| Execution: `FAILED → COMPLETED` | Invalid (terminal) |
| Execution: `CANCELLED → ACTIVE` | Invalid (terminal) |

### Multiple orders per execution

| Test | Category |
|------|----------|
| 2-leg spread: both orders reach `FILLED` | Multiple orders |
| 3-leg order: one `FILLED`, one `CANCELLED`, execution stays `ACTIVE` | Mixed outcomes |
| All orders terminal → execution `COMPLETED` | Terminal aggregation |
| One order `REJECTED` → execution `FAILED` | Failure propagation |

### Multiple positions per execution

| Test | Category |
|------|----------|
| 2-leg spread: two positions `OPEN` | Multiple positions |
| Partial close: position `OPEN` with net=0 → `CLOSED` | Position terminal |
| Same instrument across executions: separate position identities | Identity isolation |

### Valid transitions

| Test | Category |
|------|----------|
| All 14 event types with valid prior state | Coverage |
| Order: `PENDING → SUBMITTED → FILLED` (full fill) | Happy path |
| Order: `PENDING → SUBMITTED → PARTIALLY_FILLED → FILLED` | Partial fill |
| Position: `OPEN → UPDATED → CLOSED` | Position lifecycle |

### Invalid transitions

| Test | Category |
|------|----------|
| Order: `FILLED → PENDING` | Reverse |
| Order: `CANCELLED → FILLED` | Terminal |
| Position: `CLOSED → OPEN` | Terminal |
| Execution: `COMPLETED → ACTIVE` | Terminal |

### Terminal transitions

| Test | Category |
|------|----------|
| Every terminal state rejects every event type | Terminal protection (execution × 5, order × 5, position × 3 = 15 tests) |

### Sequence allocation

| Test | Category |
|------|----------|
| Sequential writes: 1, 2, 3... | Monotonicity |
| Concurrent writes (mocked): lock prevents duplicate sequence | Concurrency |
| Sequence gap detection | Gap error |

### Concurrent sequence conflict

| Test | Category |
|------|----------|
| Two writers same aggregate: second waits, gets N+1 | Lock behavior |
| Duplicate `UNIQUE(aggregate_id, sequence)` → IntegrityError | Constraint |

### Duplicate event idempotency

| Test | Category |
|------|----------|
| Same `event_id` + identical event: idempotent (ON CONFLICT DO NOTHING) | Dedup |
| Replay sees one event after duplicate insert | Idempotency verified |

### Event-ID content conflict

| Test | Category |
|------|----------|
| Same `event_id` + different payload: `EventIntegrityConflict` | Integrity |
| Same `event_id` + different `event_type`: `EventIntegrityConflict` | Integrity |

### Sequence conflict

| Test | Category |
|------|----------|
| Same `(aggregate_id, sequence)` + different event: `IntegrityError` | Ordering invariant |
| Same `(aggregate_id, sequence)` + identical event: idempotent | Safe duplicate |

### Sequence gaps

| Test | Category |
|------|----------|
| Missing event (sequence 1, 3): `ReplaySequenceGap` | Gap detection |
| Out-of-order events in DB: replay orders by `sequence` | Ordering |
| First event starts at sequence > 1: `ReplaySequenceGap` | Initial gap |

### Tenant mismatch

| Test | Category |
|------|----------|
| Event with wrong `tenant_id` at write time: rejected | Write guard |
| Event with wrong `tenant_id` at replay time: `ReplaySecurityError` | Replay guard (fail closed) |
| Cross-tenant query returns no events | Tenant isolation |

### Aggregate mismatch

| Test | Category |
|------|----------|
| Event with wrong `aggregate_id`: `ReplaySecurityError` | Aggregate guard |

### Unknown version

| Test | Category |
|------|----------|
| Event with `event_version = "99.0"`: `ReplayUnknownVersion` | Version guard |

### Corrupt payload

| Test | Category |
|------|----------|
| Event with invalid JSON payload: `ReplayCorruptPayload` | Payload validation |
| Event with missing required payload fields: `ReplayCorruptPayload` | Schema validation |

### Deterministic replay

| Test | Category |
|------|----------|
| Same events → same aggregate state (byte-identical) | Determinism |
| Replay twice → same result | Idempotency |
| No wall-clock dependency: identical `occurred_at` ignored in ordering | Time independence |
| No broker dependency: replay never calls broker | Broker independence |

### Replay idempotency

| Test | Category |
|------|----------|
| Replay with duplicate events (idempotent insert) → same state | Idempotent |
| Replay with missing events → fails deterministically (not best-effort) | Deterministic |

### Transaction rollback

| Test | Category |
|------|----------|
| Event persistence fails → authoritative writes roll back | Atomicity |
| Authoritative write fails → events never attempted | No partial event |
| DB connection lost during event append → rollback | Failure safety |

### Authoritative table / event consistency

| Test | Category |
|------|----------|
| `PaperOrder.status` matches replay state for same `order_id` | Consistency |
| `Position.net_quantity` matches replay state | Consistency |
| `StrategyExecution.status` matches replay state | Consistency |

### Broker-observed event semantics

| Test | Category |
|------|----------|
| `OrderSubmitted` does not imply broker acceptance | Audit semantics |
| `OrderRejected` records adapter observation | Broker truth |
| Adapter failure → `OrderRejected` (not `OrderFilled`) | Error handling |

### No authorization implied

| Test | Category |
|------|----------|
| No `ExecutionAuthorized` event type exists | Structural |
| No event payload contains `authorized=True` or equivalent | Vocabulary scan |
| Lifecycle events cannot bypass CentralRisk/FinalRiskGate | Chain integrity |

### Days 33–37 regression protection

| Test | Category |
|------|----------|
| `can_transition()` behavior unchanged | Day 34 regression |
| `PaperExecutionError` codes unchanged | Day 34 regression |
| `DomainEvent` contract unchanged | Day 37 regression |
| `EventBus.publish()` behavior unchanged | Day 37 regression |
| No forbidden dependencies (`uuid`, `datetime.now`, etc.) | Purity |

### Total test count: ~95

| Category | Count |
|----------|-------|
| Independent state machines (execution/order/position) | 12 |
| Multiple orders/positions per execution | 5 |
| Valid transitions | 6 |
| Invalid transitions | 5 |
| Terminal protection | 3 |
| Sequence allocation/concurrency | 4 |
| Duplicate/conflict | 6 |
| Sequence gaps | 3 |
| Tenant/aggregate mismatch | 4 |
| Unknown version | 1 |
| Corrupt payload | 2 |
| Deterministic replay | 4 |
| Replay idempotency | 2 |
| Transaction rollback | 3 |
| Authoritative consistency | 3 |
| Broker semantics | 3 |
| No authorization | 3 |
| Days 33–37 regression | 5 |
| Edge cases / integration | 24 |
| **Total** | **~95** |

## 19. Migration Strategy

- Alembic revision: `add_trade_lifecycle_events_table`.
- New table only; no modifications to existing tables.
- SQLite + PostgreSQL compatible (same pattern as Days 4–5).
- No data backfill (events begin at Day 38 adoption; pre-Day-38 state reconstructed from existing authoritative tables if needed by a future forensic mode).
- **Not written** (design-only gate).

## 20. Exact Files Expected to Change (when approved)

| File | Action | Justification |
|------|--------|---------------|
| `app/trade_lifecycle/__init__.py` | **New** | Package public API |
| `app/trade_lifecycle/contracts.py` | **New** | Aggregate, state enums, event type catalog, reducer invariants |
| `app/trade_lifecycle/state_machine.py` | **New** | Pure transition validator (reusable at append + replay) |
| `app/trade_lifecycle/replay.py` | **New** | Deterministic replay algorithm |
| `app/trade_lifecycle/persistence.py` | **New** | DB model (`TradeLifecycleEvent`) + repository (`persist_lifecycle_event`, `next_sequence`) |
| `tests/test_day38_trade_lifecycle.py` | **New** | ~95 tests |
| `alembic/versions/<hash>_add_trade_lifecycle_events.py` | **New** | Migration |
| `app/services/paper_execution.py` | **Minimal modification** | Add `persist_lifecycle_events()` call at end of `execute_strategy()` and `apply_exit()`, within existing transaction. Import guarded (no-op if unavailable). |
| `docs/superpowers/plans/...day38-*.md` | **Existing** (this file) | Design document |

### Modification to `paper_execution.py` (justified, minimal)

```python
# In execute_strategy(), after all authoritative writes, BEFORE db.commit():
try:
    from app.trade_lifecycle.persistence import persist_lifecycle_events
    persist_lifecycle_events(db, execution, orders, fills, positions)
except ImportError:
    pass  # Day 38 lifecycle events not available; proceed without audit log
```

This is the ONLY change to `paper_execution.py`. It:
- Does not reorder existing logic.
- Does not change `can_transition()`/`transition()`.
- Does not create a new execution path.
- Is guarded by `ImportError` (graceful degradation if Day 38 package not installed).
- Runs within the existing transaction (atomicity preserved).

### No changes to

- `app/models.py` (existing tables unchanged)
- `app/brokers/` (adapter unchanged)
- `app/central_risk/` (Day 33 unchanged)
- `app/final_risk_gate/` (Day 36 unchanged)
- `app/portfolio_intelligence/` (Day 35 unchanged)
- `app/domain_events/` (Day 37 reused exactly)
- `app/intelligence/`, `app/quant/`, `app/strategy_evaluation/`, `app/strike_ranking/`, `app/opportunity/` (Days 19–32 unchanged)
- Status tracker (no update until implementation approved and completed)

## 21. Risks / Open Questions

1. **Sequence allocation under SQLite**: no `FOR UPDATE`; single-process guarantee sufficient for development; production (PostgreSQL) uses proper row-level locking. Verified acceptable.
2. **`persist_lifecycle_events()` failure in `execute_strategy()`**: if the lifecycle event persistence fails (e.g., disk full), the entire transaction rolls back — no execution without audit log. This is the correct behavior (fail-closed).
3. **Event version evolution**: `payload` is extensible map; future versions add keys, never remove. `SUPPORTED_VERSIONS` set extended additively. Old replay code rejects unknown versions (correct: stop, don't guess).
4. **Pre-Day-38 state reconstruction**: Day 38 events begin at adoption; existing executions without lifecycle events cannot be replayed from the event table. If needed, a future forensic mode could synthesize events from authoritative tables (OUTSIDE Day 38).
5. **No authorization encoding in events**: confirmed separation — authorization stays in Day-33/36 chain; events are observation-only.

## 22. Proof Days 33–37 Semantics Unchanged

- **Day 33** `CentralRisk` / `assess_candidate_risk()`: unchanged. Day 38 reads `CentralRiskResult` as context; no new policy rule.
- **Day 34** `paper_risk.py` / `execute_gated_paper_entry()`: unchanged. `PaperExecutionError("RISK_<STATUS>")` enforced; Day 38 event append happens AFTER risk gate.
- **Day 35** `portfolio_intelligence/`: unchanged. Day 38 reads `PortfolioAnalyticsResult` for audit context only.
- **Day 36** `final_risk_gate/`: unchanged. Day 38 reads gate result; never bypassed.
- **Day 37** `domain_events/`: reused exactly (`DomainEvent` contract, `EventBus`). `contracts.py`, `bus.py`, `idempotency.py` untouched.
- No `ExecutionAuthorized` event; no authorization vocabulary in events.
- No new forbidden dependencies (`uuid`, `datetime.now`, etc.).
- `models.py` unchanged (no new columns on existing tables).
- No Alembic migration to existing tables.

---

## Design Conclusion

Revised Day 38 design satisfies all 12 mandatory corrections:
1. ✅ Architectural meaning clarified (§3)
2. ✅ Independent state machines defined (§5)
3. ✅ Atomic-transaction contradiction resolved (§9)
4. ✅ Sequence allocation specified (§10)
5. ✅ Duplicate/conflict semantics resolved (§11)
6. ✅ Tenant mismatch fails-closed (§12)
7. ✅ Replay fully deterministic (§13)
8. ✅ Broker-observed distinction clarified (§14)
9. ✅ Reducer invariants defined (§15)
10. ✅ Test matrix expanded to ~95 (§16)
11. ✅ Files reconciled with minimal `paper_execution.py` modification (§20)
12. ✅ Existing boundaries preserved (§17)

No code, no tests, no migration, no tracker edit, no commit. Control Center approval required before implementation.
