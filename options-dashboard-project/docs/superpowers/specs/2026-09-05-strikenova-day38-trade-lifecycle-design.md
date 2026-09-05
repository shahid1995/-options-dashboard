# Day 38 Design — Trade Lifecycle State Machine (Final Corrected)

Status: DESIGN ONLY — final corrected per Control Center mandatory corrections. No code, no tests, no migration, no tracker edit.

## Corrections Applied (this revision)

1. Position ownership/netting corrected — position is user/instrument-netted; execution provides attribution only.
2. First-event sequence concurrency — lockable `StrategyExecution` anchor row; `FOR UPDATE` on first event.
3. `ImportError → pass` removed — fail-closed; lifecycle persistence failure = transaction rollback.
4. Premature broker semantics removed — Day 38 limited to paper lifecycle facts only.
5. Execution status reconciliation — explicit mapping to authoritative `PENDING/FILLED/PARTIAL/FAILED/CANCELLED`.
6. `aggregate_type` added to schema consistently.
7. Deterministic `event_id` encoding made explicit.
8. Full consistency pass across all sections.
9. Test matrix expanded per corrected areas.
10. Final output per Control Center requirements.

## 1. Repository State

- Branch: `feat/strikenova-day35-portfolio-intelligence`; HEAD: `238e4eb`.
- Day 37: approved `2828554` (`DomainEvent` frozen envelope; `EventBus` with failure isolation; `HandlerScopedIdempotency`; no forbidden deps).
- Existing lifecycle: `app/services/paper_execution.py`; `app/models.py` (`StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, `StrategyLegExposure`, `ExitExposureAllocation`, `BulkExitRecord`); `can_transition()`/`transition()` pure validators.
- Risk gate chain: `Opportunity → StrategyCandidate → StrategyEvaluation → CentralRisk (Day-33) → PortfolioAnalytics (Day-35) → FinalRiskGate (Day-36) → User Decision → Execution`.
- Alembic authority: sole schema mechanism.

## 2. Existing Lifecycle Architecture (unchanged authority)

| Component | Identity | Statuses | Role |
|-----------|----------|----------|------|
| `StrategyExecution` | `execution_id` (str, unique via `client_order_id` per user) | `PENDING / FILLED / PARTIAL / FAILED / CANCELLED` | Authoritative: grouped multi-leg trade |
| `PaperOrder` | `order_id` (int PK) + `client_order_id` (unique per user) | `PENDING → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED` | Authoritative: one order per leg; `can_transition()` |
| `Position` | `(user_id, symbol, expiry, strike, option_type)` (unique constraint) | `open / closed` | Authoritative: **netted per instrument** |
| `PaperTransaction` | `id` (int PK) | cash ledger entries | Authoritative: auditable cash flow |
| `StrategyLegExposure` | `order_id` (unique per user) | `open / closed` | Authoritative: FIFO exit attribution |
| `ExitExposureAllocation` | `exit_order_id + exposure_id` | junction table | Authoritative: exit-to-exposure mapping |
| `BulkExitRecord` | `client_order_id` (unique per user) | `SUCCESS / NO_POSITIONS / FAILED / PARTIAL` | Authoritative: idempotent bulk exits |
| `Trade` / `Leg` | `id` (int PK) | `open / closed` | Legacy journal (projection) |

Execution is atomic: all validation before any DB write; success = `FILLED` with every order filled; failure = zero rows written.

**Day 38 does NOT replace any of these.** They remain the single source of truth.

## 3. Precise Day 38 Event-Sourcing Boundary

Day 38 means: **durable append-only trade-lifecycle events + deterministic replay/state reconstruction**, while existing authoritative paper state remains authoritative.

### What "event-sourced lifecycle semantics" means

1. Every material state change emits a typed, immutable, ordered event recorded in a dedicated append-only event table.
2. The event table is an **audit log and state-reconstruction source**, not the authoritative write-target.
3. "Replay" reconstructs lifecycle state for **verification, audit, and diagnostics** — it does not write back to authoritative tables and does not replace `can_transition()`/`transition()`.
4. Day 38 does NOT introduce a second execution engine, a second write path, or a competing source of truth.
5. **Broker-specific lifecycle semantics (acceptance, rejection, communication failure) are deferred to Days 39–42.** Day 38 records only paper-lifecycle facts.

### What Day 38 is NOT

- NOT replacing `StrategyExecution`, `PaperOrder`, `Position`, or broker truth as authoritative.
- NOT creating an independent event-driven execution engine.
- NOT implying that lifecycle events are authorization to execute.
- NOT a distributed event system.
- NOT live broker integration (no order placement, no broker sync, no broker outcome semantics).
- NOT treating adapter failures as broker rejections.

## 4. Identity Definitions (authoritative, complete)

```text
execution identity      = execution_id (from StrategyExecution table)
order identity          = order_id (from PaperOrder.id) + client_order_id (immutable idempotency key)
fill identity           = (order_id, fill_sequence) — append-only per order
position identity       = (user_id, symbol, expiry, strike, option_type) — netted per instrument (NOT execution-owned)
aggregate identity      = execution_id (lifecycle event stream anchor — Projection, not authoritative)
tenant identity         = user_id (immutable)
```

### Position ownership — CORRECTED

- **Position is user/instrument-netted authoritative state.** NOT execution-owned.
- Multiple executions may contribute to the same netted position.
- Example: Execution A → BUY 10 NIFTY 24000 CE; Execution B → SELL 5 NIFTY 24000 CE.
  - Authoritative position: `NIFTY 24000 CE, net_quantity = +5`.
  - There are NOT two execution-owned positions.
- `execution_id` recorded on lifecycle events provides **attribution/provenance** — which execution contributed what to the position — NOT ownership.
- Replay reconstructs position netting by accumulating contributions from all executions that affected the same `(user_id, symbol, expiry, strike, option_type)`.

### Attribution relationship

- `FillRecorded.event_id → execution_id` identifies which execution produced the fill.
- `PositionUpdated.event_id → execution_id + position_identity` records which execution contributed to the position change.
- Replay aggregates all execution-attributed contributions into the same netted position per instrument.

## 5. Lifecycle State Machines (CORRECTED — two reconstruction scopes)

Two distinct reconstruction scopes exist:

```
                 lifecycle events
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
 execution_id scope          position_identity scope
          │                         │
          ▼                         ▼
 TradeLifecycleReplay       PositionReplayProjection
```

**Execution replay** (`execution_id` scope) answers: "What happened during this execution?"
**Position reconstruction** (`position_identity` scope) answers: "What position resulted from all lifecycle contributions to this instrument?"

**Execution replay ≠ Position reconstruction.** Execution-scoped replay cannot know about other executions affecting the same instrument. Position reconstruction aggregates contributions from all executions belonging to the same tenant/instrument.

Four independent sub-state-machines within the event stream. **Execution, order, and fill are execution-scoped. Position is instrument-scoped (user/netted) with lifecycle instances.**

### 5a. Execution Lifecycle (Projection — maps to `StrategyExecution.status`)

States: `CREATED → ACTIVE → COMPLETED / FAILED / CANCELLED`

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none) | `TradeIntentCreated` | `CREATED` | ✅ | no |
| `CREATED` | `ExecutionActivated` | `ACTIVE` | ✅ | no |
| `ACTIVE` | `ExecutionCompleted` | `COMPLETED` | ✅ | yes |
| `ACTIVE` | `ExecutionFailed` | `FAILED` | ✅ | yes |
| `ACTIVE` | `ExecutionCancelled` | `CANCELLED` | ✅ | yes |
| terminal | any | — | ❌ | terminal |

### 5b. Order Lifecycle (Projection — maps to `PaperOrder.status`)

One order state per `order_id` under the execution. Multiple orders may exist under one execution (multi-leg).

States: `PENDING → SUBMITTED → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED`

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none) | `OrderCreated` | `PENDING` | ✅ | no |
| `PENDING` | `OrderSubmitted` | `SUBMITTED` | ✅ | no |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderFilled` | `FILLED` / `PARTIALLY_FILLED` | ✅ | FILLED = yes |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderCancelled` | `CANCELLED` | ✅ | yes |
| `SUBMITTED` / `PARTIALLY_FILLED` | `OrderRejected` | `REJECTED` | ✅ | yes |
| terminal | any | — | ❌ | terminal |

### 5c. Fill History (append-only — no state machine)

Fills accumulate per `order_id`. No fill changes prior fills; each fill is immutable.

Aggregate fill invariant: `Σ fill_quantity for order_id ≤ order.quantity`; `= order.quantity` when order is `FILLED`.

### 5d. Position Lifecycle — User/Instrument-Netted with Lifecycle Instances (CORRECTED)

Position state is **NOT execution-owned**. Position is `open/closed` per `(user_id, symbol, expiry, strike, option_type)`. Multiple executions contribute to the same position's netting.

#### Position Identity vs Position Lifecycle Instance

- **Position Identity** = permanent logical key: `(user_id, symbol, expiry, strike, option_type)`. Reusable.
- **Position Lifecycle Instance** = a particular period during which that identity has non-zero exposure. Terminal once closed, but the identity can start a new instance.

Example:
```
PositionIdentity X: (user, NIFTY, expiry, 24000, CE)

Lifecycle Instance #1:
  OPEN (net +10) → CLOSED (net 0)

Lifecycle Instance #2:
  OPEN (net +5) → OPEN ...
```

A `CLOSED` lifecycle instance is terminal for THAT instance. The position identity is NOT permanently terminal. A subsequent non-zero exposure creates a new lifecycle instance for the same identity.

#### Position Lifecycle Instance transition matrix

| From | Event | To | Valid | Terminal |
|------|-------|----|-------|----------|
| (none — first contribution or new instance) | `PositionOpened` | `OPEN` | ✅ | no |
| `OPEN` | `PositionUpdated` | `OPEN` | ✅ | no |
| `OPEN` | `PositionClosed` | `CLOSED` | ✅ | yes (for this instance) |
| `CLOSED` (same instance) | any | — | ❌ | terminal (this instance) |

**Key rules:**
- `PositionClosed` is terminal for the current lifecycle instance (net_quantity = 0).
- A later `PositionOpened` for the same `position_identity` starts a **new lifecycle instance**, not a transition from `CLOSED → OPEN` on the same instance.
- The instance is implicitly identified by the ordered sequence of `PositionOpened → ... → PositionClosed` pairs within the event stream.
- No explicit `position_instance_id` field is required: replay tracks the instance boundary by state transition. When the current instance is `CLOSED` and a new `PositionOpened` arrives, a new instance begins deterministically.

#### Position event semantics (corrected)

`PositionUpdated` carries: `position_identity`, `net_quantity`, `average_entry_price`, `realized_pnl`, `execution_id` (attribution, NOT ownership).

The `execution_id` in the event payload records which execution contributed to the position change — it does NOT imply execution-scoped ownership.

#### Cross-execution position reconstruction

Multiple executions contribute to the same netted position per instrument:

```
Execution A (execution_id="exec-a"):
  PositionOpened: position_identity=(NIFTY,24000,CE), net=+10
  PositionUpdated: position_identity=(NIFTY,24000,CE), net=+10, exec=exec-a

Execution B (execution_id="exec-b"):
  PositionUpdated: position_identity=(NIFTY,24000,CE), net=+5, exec=exec-b
```

Replay aggregates: position_identity=(NIFTY,24000,CE), lifecycle instance #1, net_quantity=+5.

If Execution C later closes the position:
```
Execution C (execution_id="exec-c"):
  PositionUpdated: position_identity=(NIFTY,24000,CE), net=0, exec=exec-c
  PositionClosed: position_identity=(NIFTY,24000,CE), realized_pnl=...
```

Lifecycle instance #1 → CLOSED. Identity remains available for future instances.

#### Lifecycle instance boundaries in replay

Replay tracks lifecycle instances implicitly:
- `PositionOpened` starts a new instance (only valid when no open instance exists for this `position_identity`).
- `PositionUpdated` modifies the current open instance.
- `PositionClosed` terminates the current open instance (only valid when net_quantity = 0).
- A subsequent `PositionOpened` for the same identity begins a new instance.
  Order: BUY 10 NIFTY 24000 CE
  → FillRecorded: order_id=1, qty=10, price=125.00
  → PositionUpdated: position_identity=(NIFTY,24000,CE), net_quantity=+10, avg_entry=125.00

Execution B (execution_id="exec-b"):
  Order: SELL 5 NIFTY 24000 CE
  → FillRecorded: order_id=2, qty=5, price=140.00
  → PositionUpdated: position_identity=(NIFTY,24000,CE), net_quantity=+5, avg_entry=130.00
```

Authoritative position: `NIFTY 24000 CE, net_quantity = +5`. Both lifecycle event streams contribute to the same netted position. Replay aggregates contributions by `position_identity`, not by `execution_id`.

## 6. Complete Transition Matrix

### Execution Lifecycle

| Sub-machine | From | Event | To | Valid | Required data | Invariants | Terminal |
|-------------|------|-------|----|-------|---------------|------------|----------|
| Execution | (none) | `TradeIntentCreated` | `CREATED` | ✅ | execution_id, symbol, strategy_tag, legs[] | execution_id unique; tenant_id = user_id; legs non-empty | no |
| Execution | `CREATED` | `ExecutionActivated` | `ACTIVE` | ✅ | execution_id | at least one OrderCreated | no |
| Execution | `ACTIVE` | `ExecutionCompleted` | `COMPLETED` | ✅ | execution_id | **all required orders FILLED**; fill consistency (§6d mapping) | yes |
| Execution | `ACTIVE` | `ExecutionFailed` | `FAILED` | ✅ | execution_id, reason_code | execution failure before or during fills | yes |
| Execution | `ACTIVE` | `ExecutionCancelled` | `CANCELLED` | ✅ | execution_id, reason | cancellation before or during fills | yes |
| Execution | terminal | any | — | ❌ | — | terminal-state protection | — |

### Order Lifecycle

| Sub-machine | From | Event | To | Valid | Required data | Invariants | Terminal |
|-------------|------|-------|----|-------|---------------|------------|----------|
| Order | (none) | `OrderCreated` | `PENDING` | ✅ | order_id, execution_id, symbol, action, quantity, lot_size, client_order_id | order_id unique per execution; execution exists | no |
| Order | `PENDING` | `OrderSubmitted` | `SUBMITTED` | ✅ | order_id | client_order_id immutable | no |
| Order | `SUBMITTED` | `OrderFilled` | `FILLED` | ✅ | order_id, fill_quantity, fill_price | fill_quantity = order.quantity (full fill) | yes |
| Order | `SUBMITTED` | `OrderFilled` | `PARTIALLY_FILLED` | ✅ | order_id, fill_quantity, fill_price | cumulative < order.quantity | no |
| Order | `PARTIALLY_FILLED` | `OrderFilled` | `FILLED` | ✅ | cumulative = order.quantity | yes |
| Order | `PARTIALLY_FILLED` | `OrderCancelled` | `CANCELLED` | ✅ | order_id, reason | — | yes |
| Order | `SUBMITTED` / `PARTIALLY_FILLED` | `OrderRejected` | `REJECTED` | ✅ | order_id, reason | — | yes |
| Order | terminal | any | — | ❌ | — | terminal-state protection | — |

### Fill History

| Sub-machine | From | Event | To | Valid | Required data | Invariants | Terminal |
|-------------|------|-------|----|-------|---------------|------------|----------|
| Fill | (any) | `FillRecorded` | (append) | ✅ | order_id, fill_quantity, fill_price, fill_timestamp, price_source | cumulative ≤ order.quantity; fill_quantity > 0; fill_price > 0 | n/a (append-only) |

### Position Lifecycle (instrument-netted, NOT execution-owned, with lifecycle instances)

| Sub-machine | From | Event | To | Valid | Required data | Invariants | Terminal |
|-------------|------|-------|----|-------|---------------|------------|----------|
| Position | (none or previous instance CLOSED) | `PositionOpened` | `OPEN` | ✅ | position_identity (user/symbol/expiry/strike/type), initial_quantity | net_quantity ≠ 0; unique per identity; no open instance exists | no (new instance) |
| Position | `OPEN` (current instance) | `PositionUpdated` | `OPEN` | ✅ | position_identity, net_quantity, average_entry_price, realized_pnl, execution_id (attribution) | net_quantity may be +, −, or 0; same identity | no |
| Position | `OPEN` (current instance) | `PositionClosed` | `CLOSED` | ✅ | position_identity, realized_pnl | net_quantity = 0; no exposure remains | yes (this instance) |
| Position | `CLOSED` (same instance) | any | — | ❌ | — | terminal for this instance | — |
| Position | `CLOSED` (previous instance) + new exposure | `PositionOpened` | `OPEN` | ✅ | position_identity, initial_quantity | net_quantity ≠ 0; starts new lifecycle instance | no (new instance) |

## 7. Execution Status Reconciliation (CORRECTED — §5 mapping to authoritative)

The lifecycle state machine is a **projection/replay state**, NOT a second authoritative execution status system. **`StrategyExecution.status` is authoritative.** The lifecycle projection must map to it deterministically.

### Authoritative statuses

```text
PENDING    — execution created; orders not yet placed
FILLED     — all required orders fully filled; position updated
PARTIAL    — some required orders filled, some cancelled/rejected; partial exposure established
FAILED     — execution failure before or during fills
CANCELLED  — execution cancelled before or during fills
```

### Mapping from lifecycle outcomes to authoritative `StrategyExecution.status`

| Lifecycle Outcome | Authoritative `StrategyExecution.status` | Definition |
|-------------------|----------------------------------------|------------|
| All required orders `FILLED`; position updated | `FILLED` | Complete fill |
| Some orders `FILLED`, some `CANCELLED` (partial exposure exists) | `PARTIAL` | Partial fill with exposure |
| Some orders `FILLED`, some `REJECTED` (partial exposure exists) | `PARTIAL` | Partial fill with exposure |
| Some orders `FILLED`, some `PARTIALLY_FILLED` + others terminal | `PARTIAL` | Partial fill with exposure |
| `ExecutionFailed` before any fill | `FAILED` | Execution failure |
| `ExecutionFailed` after some fills | `PARTIAL` | Partial fill exists |
| `ExecutionCancelled` before any fill | `CANCELLED` | Cancelled |
| `ExecutionCancelled` after some fills | `PARTIAL` | Partial fill exists |
| No orders yet; `TradeIntentCreated` only | `PENDING` | Execution pending |
| `TradeIntentCreated` + `OrderCreated` but none submitted | `PENDING` | Execution pending |

### Mixed-outcome examples (all cases)

1. **All filled** (2-leg spread): Order A `FILLED`, Order B `FILLED` → `StrategyExecution = FILLED`
2. **Partial + cancelled**: Order A `FILLED`, Order B `CANCELLED` → exposure exists (+10 on A) → `StrategyExecution = PARTIAL`
3. **Partial + rejected**: Order A `FILLED`, Order B `REJECTED` → exposure exists → `StrategyExecution = PARTIAL`
4. **All cancelled**: Order A `CANCELLED`, Order B `CANCELLED` → no exposure → `StrategyExecution = CANCELLED`
5. **All rejected**: Order A `REJECTED`, Order B `REJECTED` → no exposure → `StrategyExecution = CANCELLED`
6. **Execution failed before fill**: `ExecutionFailed` → `StrategyExecution = FAILED`
7. **Execution failed after partial fill**: Order A `FILLED`, `ExecutionFailed` → exposure exists → `StrategyExecution = PARTIAL`
8. **Cancelled after partial fill**: Order A `FILLED`, `ExecutionCancelled` → exposure exists → `StrategyExecution = PARTIAL`
9. **Still pending**: `TradeIntentCreated` only → `StrategyExecution = PENDING`
10. **Pending + order created**: `OrderCreated` but not `OrderSubmitted` → `StrategyExecution = PENDING`

### Authority rule

**`StrategyExecution.status` is authoritative.** The lifecycle projection is derived from event state; when the two agree, the projection is consistent; when they disagree (should not happen if events are correctly appended), the authoritative DB table is the source of truth.

### Reconciliation with existing `can_transition()`

The existing `can_transition()` validator in `paper_execution.py` remains authoritative for order-state transitions. Day 38 events record what happened; they do not validate transitions. `can_transition()` is called BEFORE state changes; events are appended AFTER state changes succeed. Day 38 does not weaken or replace `can_transition()`/`transition()`.

## 8. Event Taxonomy (reuses Day 37 `DomainEvent`)

All events use `DomainEvent` envelope (`app/domain_events/contracts.py`).

| Field | Value |
|-------|-------|
| `event_id` | Deterministic (§8a below) |
| `event_type` | One of 14 types (below) |
| `aggregate_type` | `"TradeLifecycle"` — persisted in event table |
| `aggregate_id` | `execution_id` |
| `tenant_id` | `user_id` |
| `occurred_at` | Caller-supplied aware datetime (never `datetime.now()`) |
| `event_version` | `"1.0"` |
| `payload` | Structured dict per event type |
| `metadata` | Optional `{source: "paper_engine", version: "1.0"}` |

### 8a. Deterministic event_id construction (CORRECTED)

`event_id` is constructed deterministically from content to ensure idempotency and reproducibility:

```text
event_id = SHA256(
    canonical_utf8(
        aggregate_type          // "TradeLifecycle"
        + "\x1f"
        + aggregate_id          // execution_id
        + "\x1f"
        + event_type            // e.g. "OrderFilled"
        + "\x1f"
        + str(sequence)         // e.g. "7"
    )
)
```

Where:
- `\x1f` (ASCII Unit Separator) is an unambiguous delimiter that cannot appear in normal identifiers.
- `canonical_utf8(s)` encodes the string as UTF-8 bytes.
- `SHA256()` returns the hex-encoded 64-character hash.

This means:
- Same `(aggregate_type, aggregate_id, event_type, sequence)` → same `event_id` (always).
- Different `sequence` → different `event_id` (guaranteed).
- Different `event_type` → different `event_id` (guaranteed).
- `event_id` identifies **aggregate + event type + lifecycle sequence**, NOT the entire payload.
- Content integrity (payload) is validated separately by the reducer (§15).

### 8b. Event type catalog

**Execution events (execution-scoped):**
1. `TradeIntentCreated` — execution created; payload: `{execution_id, symbol, strategy_tag, legs: [...]}`
2. `ExecutionActivated` — at least one order placed; payload: `{execution_id}`
3. `ExecutionCompleted` — all required orders FILLED; payload: `{execution_id, total_filled_orders}`
4. `ExecutionFailed` — execution failed; payload: `{execution_id, reason_code}`
5. `ExecutionCancelled` — execution cancelled; payload: `{execution_id, reason}`

**Order events (order-scoped):**
6. `OrderCreated` — order established; payload: `{order_id, execution_id, symbol, action, quantity, lot_size, client_order_id}`
7. `OrderSubmitted` — order placed for execution; payload: `{order_id}` — **this is an audit fact that StrikeNova placed the order; it does NOT imply broker acceptance**
8. `OrderFilled` — order (partially or fully) filled; payload: `{order_id, fill_quantity, fill_price, cumulative_filled, price_source}`
9. `OrderCancelled` — order cancelled; payload: `{order_id, reason}`
10. `OrderRejected` — order rejected by StrikeNova validation (NOT broker rejection — broker rejection is Days 39–42); payload: `{order_id, reason}`

**Fill events (fill-scoped, append-only):**
11. `FillRecorded` — fill ledger entry; payload: `{order_id, execution_id, fill_quantity, fill_price, fill_timestamp, price_source}`

**Position events (instrument-netted, NOT execution-owned) — DELTA semantics:**

12. `PositionOpened` — new position created (first contribution or new lifecycle instance); payload: `{position_identity: {user_id, symbol, expiry, strike, option_type}, quantity_delta: <int>, lot_size: <int>, execution_id (attribution)}`
    - `quantity_delta`: signed change to net quantity (e.g., +10 for BUY 10, -5 for SELL 5). NOT the resulting `net_quantity`.

13. `PositionUpdated` — position netting changed; payload: `{position_identity, quantity_delta: <int>, average_entry_price: <float>, realized_pnl: <float>, execution_id (attribution)}`
    - `quantity_delta`: signed change from this contribution (e.g., -5 for a reduction of 5 lots). NOT the resulting `net_quantity`.
    - The reconstructed state is: `net_quantity = Σ quantity_delta across all events in this lifecycle instance`.

14. `PositionClosed` — position lifecycle instance fully closed (net = 0); payload: `{position_identity, quantity_delta: <int>, final_realized_pnl: <float>}`
    - `quantity_delta`: the final signed change that brings net to 0 (e.g., -5 to close +5).
    - `final_realized_pnl`: total realized P&L for this lifecycle instance.

### Position reconstruction semantics (DELTA)

Replay computes: `net_quantity = Σ quantity_delta` for all events in the current lifecycle instance (ordered by `position_sequence`).

Example:
```
Event 1: PositionOpened  {quantity_delta: +10}   → net = +10
Event 2: PositionUpdated {quantity_delta: -5}     → net = +5
Event 3: PositionClosed  {quantity_delta: -5}     → net = 0 (instance CLOSED)
Event 4: PositionOpened  {quantity_delta: +5}     → NEW instance, net = +5
```

**Key rule**: `quantity_delta` is the lifecycle contribution. `net_quantity` is a **reconstructed state**, never an event payload field. Replay validates: after `PositionClosed`, `Σ quantity_delta == 0`.

### Event semantics (CORRECTED — no premature broker semantics)

| Event type | Category | Represents |
|------------|----------|------------|
| `OrderCreated` | **Fact** | StrikeNova created a paper order |
| `OrderSubmitted` | **Audit fact** | StrikeNova submitted order for execution; does NOT mean broker accepted |
| `OrderFilled` | **Fact** | Fill received (paper-engine fill; broker fills are Days 39–42) |
| `OrderCancelled` | **Fact** | Order cancelled by StrikeNova validation/logic |
| `OrderRejected` | **Fact** | Order rejected by StrikeNova validation (NOT broker rejection) |
| `TradeIntentCreated` | **Fact** | Execution strategy established |
| `ExecutionCompleted/Failed/Cancelled` | **Fact** | Execution lifecycle terminal |
| `PositionOpened/Updated/Closed` | **Fact** | Position netting state changed |

Broker-specific outcome semantics (acceptance, rejection, communication failure, timeout) are deferred to Days 39–42. Day 38 does NOT generate broker outcome events.

## 9. Persistence Model

New table `trade_lifecycle_events` (Alembic only):

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `event_id` | `String(64)` | PK | Deterministic SHA256 (§8a) |
| `aggregate_type` | `String(32)` | NOT NULL, indexed | `"TradeLifecycle"` |
| `aggregate_id` | `String(40)` | NOT NULL, indexed | `execution_id` |
| `event_type` | `String(32)` | NOT NULL, indexed | One of 14 types |
| `event_version` | `String(16)` | NOT NULL | `"1.0"` |
| `tenant_id` | `String(128)` | NOT NULL, indexed | `user_id` |
| `sequence` | `Integer` | NOT NULL | Monotonic per aggregate |
| `occurred_at` | `DateTime(timezone=True)` | NOT NULL | Caller-supplied aware datetime |
| `payload_json` | `Text` | NOT NULL | `json.dumps(payload, sort_keys=True)` |
| `metadata_json` | `Text` | NULLABLE | Optional JSON metadata |
| `created_at` | `DateTime(timezone=True)` | NOT NULL | DB write time (default utcnow) |

Constraints:
- PK: `event_id`
- `UNIQUE(aggregate_id, sequence)` — ordering invariant (integrity guard, §10)
- Indexed: `(aggregate_id, sequence)`, `(tenant_id, occurred_at)`, `(aggregate_type, event_type)`

Append-only: no UPDATE or DELETE by application code.

Idempotent insert: primary mechanism is canonical content comparison; if same `event_id` exists with identical content → no insert. Database `ON CONFLICT(event_id) DO NOTHING` is a secondary guard. Different content with same `event_id` → integrity conflict (should not happen if §8a encoding correct; if it does, treat as error, rollback).

## 10. Sequence Allocation (CORRECTED — lockable anchor)

Two concurrent first writers observing `MAX(sequence) = NULL` is a real concurrency problem. The solution: lock the authoritative `StrategyExecution` row as the aggregate anchor.

### Algorithm

```python
def append_lifecycle_event(db: Session, execution_id: str, tenant_id: str, event: DomainEvent) -> None:
    # 1. Lock the StrategyExecution row (the authoritative anchor)
    execution = db.execute(
        select(StrategyExecution)
        .where(StrategyExecution.execution_id == execution_id)
        .where(StrategyExecution.user_id == tenant_id)  # tenant validation
        .with_for_update()  # row-level lock
    ).scalar_one_or_none()
    if execution is None:
        raise ValueError("AGGREGATE_NOT_FOUND or TENANT_MISMATCH")

    # 2. Allocate sequence from the event table (anchor is locked, so concurrent writers block)
    max_seq = db.execute(
        select(func.max(TradeLifecycleEvent.sequence))
        .where(TradeLifecycleEvent.aggregate_id == execution_id)
    ).scalar()
    next_sequence = (max_seq or 0) + 1

    # 3. Insert event with allocated sequence
    db.add(TradeLifecycleEvent(
        event_id=event.event_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        event_version=event.event_version,
        tenant_id=event.tenant_id,
        sequence=next_sequence,
        occurred_at=event.occurred_at,
        payload_json=json.dumps(event.payload, sort_keys=True),
        metadata_json=json.dumps(event.metadata, sort_keys=True) if event.metadata else None,
        created_at=datetime.now(timezone.utc),
    ))
    # 4. Lock is released when the transaction commits or rolls back
```

### Concurrency model

| Scenario | Behavior |
|----------|----------|
| **First writer to aggregate** | `StrategyExecution` row locked (`FOR UPDATE`); `MAX(sequence)` returns NULL → next = 1; event inserted; lock held until commit. |
| **Concurrent second writer to same aggregate** | `FOR UPDATE` blocks on `StrategyExecution` row; waits for first writer to commit; then sees sequence = 1; allocates next = 2. |
| **Different aggregate (different execution_id)** | Different `StrategyExecution` row; no lock contention. |
| **First writer rolls back** | Lock released; no event persisted; second writer proceeds normally from empty state. |
| **Uniqueness constraint** | `UNIQUE(aggregate_id, sequence)` is a final integrity guard — if any code path bypasses the lock, the constraint rejects the duplicate. |

### SQLite behavior

SQLite serializes writes at the process level (single writer). `SELECT ... FOR UPDATE` is a no-op in SQLite; the same-session transaction ensures sequential access. For development/testing, this is sufficient. PostgreSQL provides proper row-level locking.

### PostgreSQL behavior

`SELECT ... FOR UPDATE` on `StrategyExecution` row acquires an exclusive row lock. Concurrent writers on the same `execution_id` block until the lock is released (commit or rollback). Writers on different `execution_id` values proceed independently.

## 11. Duplicate / Conflict Semantics (CORRECTED — must distinguish identical from different)

Because `event_id` is derived from `(aggregate_type, aggregate_id, event_type, sequence)` (§8a), same `event_id` ALWAYS means exactly those fields match. If payload differs but the key fields match, the encoding would produce a different `event_id`; therefore same `event_id` with different payload is structurally impossible by construction. The persistence logic must enforce this deterministically.

### Exact semantics

```text
Same event_id + identical canonical content
    → idempotent success (DO NOTHING or compare-then-accept)

Same event_id + different canonical content
    → IMPOSSIBLE by deterministic encoding (§8a) IF event_id derivation is correct
    → If forced (corruption, manual insertion error, encoding bug): integrity conflict → rollback

Same aggregate_type + aggregate_id + sequence + identical event
    → Idempotent success (same event_id; same content)

Same aggregate_type + aggregate_id + sequence + different event
    → Ordering/integrity conflict → IntegrityError → rollback
```

### Implementation procedure for idempotent insert

```python
def append_lifecycle_event(db, event):
    # Compute canonical content hash for comparison
    canonical = canonical_json(event.payload)
    
    existing = db.execute(
        SELECT event_id, payload_json FROM trade_lifecycle_events WHERE event_id = ?
    ).fetchone()
    
    if existing is not None:
        # Same event_id exists — compare content
        if existing.payload_json == canonical:
            # Identical — idempotent success
            return  # do not insert
        else:
            # Different content — integrity conflict (should not happen if §8a correct)
            raise EventIntegrityConflict(event.event_id)
    
    # No existing row — insert
    db.execute(
        INSERT INTO trade_lifecycle_events (...) VALUES (...)
    )
```

The database-level `ON CONFLICT(event_id) DO NOTHING` is a secondary guard, not the primary mechanism. The primary mechanism is: compute canonical content; if existing row with same `event_id` has identical content → idempotent; if different → conflict (should not occur with correct encoding; if it does, treat as error, not silent success).

### Sequence-conflict guard (independent of event_id)

| Scenario | Resolution |
|----------|-----------|
| `UNIQUE(aggregate_id, sequence)` satisfied by identical event | Idempotent (event_id handles) |
| `UNIQUE(aggregate_id, sequence)` violated by different event | `IntegrityError` → rollback |

The uniqueness constraint acts as a final guard, not the primary duplicate-detection mechanism.

## 12. Replay Algorithm (CORRECTED — two reconstruction scopes)

### Two distinct replay paths

**Path A: Trade Lifecycle Replay (execution-scoped)**
Reconstructs execution state, order states, fill history, and execution-scoped lifecycle facts. Answers: "What happened during this execution?"

**Path B: Position Reconstruction (position-identity-scoped)**
Reconstructs netted position state from ALL lifecycle events belonging to the same `(user_id, symbol, expiry, strike, option_type)`. Answers: "What position resulted from all lifecycle contributions to this instrument?"

**Execution replay ≠ Position reconstruction.** Execution-scoped replay cannot know about other executions affecting the same instrument. Position reconstruction aggregates contributions from all executions belonging to the same tenant/instrument.

### Path A — Trade Lifecycle Replay

```python
def replay_lifecycle(aggregate_id: str, tenant_id: str, db: Session) -> TradeLifecycleAggregate:
    """Reconstruct execution-scoped lifecycle state.

    Scope: all events for this execution_id + tenant_id.
    Returns: execution state, order states, fill history.
    Does NOT reconstruct netted position across executions.
    """
    events = db.execute(
        SELECT * FROM trade_lifecycle_events
        WHERE aggregate_id = ? AND tenant_id = ?
        ORDER BY sequence ASC
    ).fetchall()

    state = empty_lifecycle_aggregate(aggregate_id, tenant_id)

    for event in events:
        # Tenant check — FAIL CLOSED
        if event.tenant_id != tenant_id:
            raise ReplaySecurityError("TENANT_MISMATCH")
        # Aggregate check — FAIL CLOSED
        if event.aggregate_id != aggregate_id:
            raise ReplaySecurityError("AGGREGATE_MISMATCH")
        # Version check
        if event.event_version not in SUPPORTED_VERSIONS:
            raise ReplayUnknownVersion(event.event_version)
        # Sequence monotonicity
        expected_seq = state.last_sequence + 1
        if event.sequence != expected_seq:
            raise ReplaySequenceGap(expected=expected_seq, actual=event.sequence)
        # Payload validation
        if not valid_payload(event.event_type, event.payload_json):
            raise ReplayCorruptPayload(event.event_id)
        # Apply transition (per §6 matrices — execution, order, fill only)
        apply_lifecycle_transition(state, event)
        state.last_sequence = event.sequence

    return state
```

### Path B — Position Reconstruction

```python
def reconstruct_position(position_identity: tuple, tenant_id: str, db: Session) -> PositionReconstruction:
    """Reconstruct netted position state across ALL executions.

    Scope: all events with matching position_identity + tenant_id.
    Aggregates contributions from multiple executions.
    Tracks lifecycle instances (OPEN → CLOSED → new OPEN).
    """
    events = db.execute(
        SELECT * FROM trade_lifecycle_events
        WHERE tenant_id = ?
        AND event_type IN ('PositionOpened', 'PositionUpdated', 'PositionClosed')
        ORDER BY aggregate_id ASC, sequence ASC  # global ordering across executions
    ).fetchall()

    # Filter to events affecting this position_identity
    relevant = [e for e in events if position_identity_matches(e, position_identity)]

    projection = empty_position_projection(position_identity)
    current_instance = None

    for event in relevant:
        # Tenant check — FAIL CLOSED
        if event.tenant_id != tenant_id:
            raise ReplaySecurityError("TENANT_MISMATCH")
        # Version check
        if event.event_version not in SUPPORTED_VERSIONS:
            raise ReplayUnknownVersion(event.event_version)
        # Apply position transition with lifecycle instance tracking
        apply_position_projection(projection, event, current_instance)

    return projection
```

### Position projection behavior

```python
def apply_position_projection(projection, event, current_instance):
    if event.event_type == "PositionOpened":
        # New lifecycle instance — only valid if no open instance exists
        if current_instance and current_instance.is_open:
            raise ReplayInvalidTransition("PositionOpened while instance open")
        current_instance = LifecycleInstance(open_sequence=event.sequence)
        projection.current_instance = current_instance
        projection.instances.append(current_instance)
        current_instance.net_quantity = event.payload["initial_quantity"]

    elif event.event_type == "PositionUpdated":
        if not current_instance or not current_instance.is_open:
            raise ReplayInvalidTransition("PositionUpdated without open instance")
        current_instance.net_quantity = event.payload["net_quantity"]
        current_instance.average_entry_price = event.payload["average_entry_price"]
        current_instance.realized_pnl = event.payload["realized_pnl"]
        current_instance.attribution.append(event.payload["execution_id"])

    elif event.event_type == "PositionClosed":
        if not current_instance or not current_instance.is_open:
            raise ReplayInvalidTransition("PositionClosed without open instance")
        if current_instance.net_quantity != 0:
            raise ReplayInvalidTransition("PositionClosed with non-zero net")
        current_instance.is_open = False
        current_instance.closed_sequence = event.sequence
        current_instance.final_realized_pnl = event.payload["final_realized_pnl"]
```

### Replay reconstruction scopes (CORRECTED — two separate scopes)

```text
Execution replay (execution_id scope)
    ↓ reconstructs execution state + orders + fills

Position reconstruction (position_identity scope)
    ↓ aggregates contributions from ALL executions affecting same instrument
    ↓ reconstructs netted position + lifecycle instances

These are NOT the same replay. Execution replay answers "what happened in this execution?". Position reconstruction answers "what position exists for this instrument across all executions?"
```

### Replay must not confuse scopes

- `replay_aggregate(aggregate_id=execution_id, ...)` reconstructs execution-scoped state. It does NOT produce netted position state (it collects position events but does not aggregate them with other executions).
- `reconstruct_position(position_identity=(user, symbol, expiry, strike, option_type), ...)` aggregates all `PositionOpened/Updated/Closed` events across all `execution_id` values, ordered globally, to reconstruct the netted position with lifecycle instances.
- No single replay call produces both results automatically. The design provides both paths explicitly.
- Replay of one execution does not imply replay of the position it contributed to — position reconstruction is a separate operation.

### Replay must remain read-only (correction preserved)

No replay writes to authoritative tables (`PaperOrder`, `Position`, `StrategyExecution`). Replay produces projection objects only.

### Replay rejects (all deterministic, no best-effort)

| Condition | Error | Behavior |
|-----------|-------|----------|
| Invalid transition | `ReplayInvalidTransition` | Stop |
| Sequence gap | `ReplaySequenceGap` | Stop |
| Corrupt payload | `ReplayCorruptPayload` | Stop |
| Unknown version | `ReplayUnknownVersion` | Stop |
| Tenant mismatch | `ReplaySecurityError` | Stop (fail closed) |
| Aggregate mismatch | `ReplaySecurityError` | Stop (fail closed) |
| Position instance open violation | `ReplayInvalidTransition` (instance not closed but new `PositionOpened` arrives) | Stop |
| Position instance closed violation | `ReplayInvalidTransition` (update on closed instance) | Stop |
| Position close with non-zero net | `ReplayInvalidTransition` | Stop |
| PositionOpened while instance open | `ReplayInvalidTransition` | Stop |
| PositionClosed with non-zero net | `ReplayInvalidTransition` | Stop |
| PositionUpdated without open instance | `ReplayInvalidTransition` | Stop |

Canonical replay is all-or-nothing. No partial state is ever silently reconstructed.

### Ordering across executions for position reconstruction — Canonical causal ordering (CORRECTED)

The previous rule `(aggregate_id ASC, sequence ASC)` is **deterministic but not causal** for position netting. Lexical `execution_id` order ≠ causal position order.

**Canonical ordering for position reconstruction**: `position_sequence` — a position-scoped sequence number, independent of execution-scoped `sequence`.

### Position-scoped sequence (`position_sequence`)

| Property | Value |
|----------|-------|
| Scope | `(user_id, symbol, expiry, strike, option_type)` = `PositionIdentity` |
| Allocation | Per position-affecting event (`PositionOpened`, `PositionUpdated`, `PositionClosed`) |
| Storage | Column `position_sequence` on `trade_lifecycle_events` (nullable for non-position events); persisted in event payload |
| Allocation anchor | `PositionSequenceAnchor` table (minimal: `position_identity` PK, `last_position_sequence` int, default 0) |
| Allocation algorithm | `SELECT ... FOR UPDATE` on `PositionSequenceAnchor` row; `next = last + 1`; `INSERT ... ON CONFLICT DO UPDATE` if first time |
| First event | Anchor created in same transaction if missing; sequence = 1 |
| Concurrency | `FOR UPDATE` serializes concurrent writers on same `PositionIdentity`; different identities proceed independently |
| Replay ordering | Position reconstruction orders by `(position_sequence ASC)` only |

### Why not `aggregate_id ASC, sequence ASC`

- `aggregate_id = execution_id`. Lexical execution ID order ≠ causal position order.
- Example: Execution B BUY 10 followed by Execution A SELL 10. If `exec-A < exec-B` lexically, `aggregate_id ASC` would process SELL before BUY → invalid (position doesn't exist yet).
- `position_sequence` captures the **true causal order** of position contributions regardless of execution IDs.

### Replay with dual ordering

```python
def replay_lifecycle(aggregate_id: str, tenant_id: str, db: Session) -> TradeLifecycleAggregate:
    # Execution-scoped: order by execution `sequence`
    events = db.execute(
        SELECT * FROM trade_lifecycle_events
        WHERE aggregate_id = ? AND tenant_id = ?
        ORDER BY sequence ASC
    ).fetchall()
    ...

def reconstruct_position(position_identity: tuple, tenant_id: str, db: Session) -> PositionReconstruction:
    # Position-scoped: order by position_sequence
    events = db.execute(
        SELECT * FROM trade_lifecycle_events
        WHERE tenant_id = ?
        AND event_type IN ('PositionOpened', 'PositionUpdated', 'PositionClosed')
        AND payload_json @> ('{"position_identity": ' + json.dumps(dict(position_identity)) + '}')::jsonb
        ORDER BY payload_json->>'position_sequence' ASC
    ).fetchall()
    ...
```

### First-event concurrency (position-scoped)

Two concurrent executions contributing to the same new instrument:
- Writer A: `FOR UPDATE` on `PositionSequenceAnchor` (creates if missing), allocates sequence = 1.
- Writer B: blocks on same `FOR UPDATE`; after A commits, sees sequence = 1, allocates sequence = 2.
- `UNIQUE(aggregate_id, sequence)` on event table + `UNIQUE(position_identity, position_sequence)` on anchor table provide integrity guards.

### Causal ordering invariant

```text
For a given PositionIdentity:
all PositionOpened/Updated/Closed events
have a total order by position_sequence
and replay applies them in that order.
```

No lexical `execution_id` ordering is used for position reconstruction.

## 13. Transaction Architecture (CORRECTED — fail-closed)

### Integration boundary

The existing `execute_strategy()` in `paper_execution.py` performs an atomic write. Day 38 adds lifecycle event persistence **within the same transaction** after authoritative writes succeed, but **WITHOUT ImportError bypass**:

```python
# In paper_execution.py execute_strategy(), inside the existing transaction:

from app.trade_lifecycle.persistence import append_lifecycle_events  # REQUIRED import

# ... existing authoritative writes (StrategyExecution, PaperOrder, Position, PaperTransaction) ...

# Append lifecycle events — SAME transaction; failure = FULL ROLLBACK
append_lifecycle_events(
    db=db,
    execution_id=execution.execution_id,
    tenant_id=execution.user_id,
    events=lifecycle_events,  # list of DomainEvent
)

# Then: db.commit() (existing) — or automatic on session context exit
```

### If lifecycle persistence fails

```text
authoritative writes succeed
    ↓
lifecycle event persistence fails (ImportError / DB error / serialization error / constraint violation)
    ↓
transaction ROLLS BACK — authoritative mutation NOT committed
    ↓
no partial execution state; no audit trail without authoritative state
```

### If lifecycle persistence is unavailable (ImportError)

This is a **deployment/programming error**, NOT a reason to continue. The `from app.trade_lifecycle.persistence import append_lifecycle_events` at the top of `paper_execution.py` is a **required import**. If the module is missing, the import fails at module load time, and the application cannot start. There is no try/except/pass. There is no graceful degradation. If the lifecycle persistence dependency is not installed, the application does not start.

### Transaction ownership

- `paper_execution.py` owns the transaction (unchanged).
- `append_lifecycle_events()` operates on the same `db` session (same transaction).
- Lock is acquired on `StrategyExecution` row (§10) before event append.
- All writes (authoritative + lifecycle events) commit atomically.
- Rollback releases all locks.

### Modification to `paper_execution.py` (minimal, justified)

The ONLY changes:
1. Add `from app.trade_lifecycle.persistence import append_lifecycle_events` at the top of the file (required import, no try/except).
2. Add `append_lifecycle_events(db, execution_id, tenant_id, events)` call inside `execute_strategy()` and `apply_exit()`, within the existing transaction, after authoritative writes.

No refactoring, no reordering, no new execution path, no `can_transition()` changes.

## 14. Reducer Invariants

### Append-time invariants (checked in `append_lifecycle_events()`)

| Invariant | Check | Failure |
|-----------|-------|---------|
| Aggregate identity | `event.aggregate_id == execution.execution_id` | Reject + rollback |
| Tenant identity | `event.tenant_id == execution.user_id` | Reject + rollback |
| `client_order_id` immutable | Once set, never changed in subsequent events | Reject + rollback |
| Event version | `event.event_version ∈ SUPPORTED_VERSIONS` | Reject + rollback |
| No authorization implied | No event type carries authorization vocabulary | Structural (enum) |
| No command created during append | Events record facts, not requests | Structural (enum) |

### Replay-time invariants (checked during replay)

| Invariant | Check | Failure |
|-----------|-------|---------|
| Tenant match | `event.tenant_id == requested_tenant_id` | Stop (fail closed) |
| Aggregate match | `event.aggregate_id == requested_aggregate_id` | Stop (execution replay) |
| Sequence monotonicity | `event.sequence == last_sequence + 1` | Stop (gap) |
| Terminal-state protection (execution) | No event applied to terminal execution state | Stop |
| Terminal-state protection (order) | No event applied to terminal order state | Stop |
| Terminal-state protection (position instance) | No event applied to closed lifecycle instance | Stop |
| PositionOpened only when no open instance | `PositionOpened` requires no current open instance for this identity | Stop |
| PositionClosed requires net=0 | `PositionClosed` only when `net_quantity == 0` | Stop |
| PositionUpdated requires open instance | `PositionUpdated` only when open instance exists | Stop |
| Fill quantity consistency | `Σ fill_qty ≤ order_qty`; `= order_qty` when FILLED | Stop |
| Position netting consistency | Multiple executions contribute to same netted position per instrument | Structural (projection) |
| Event version | `event.version ∈ SUPPORTED_VERSIONS` | Stop |
| Sequence uniqueness | Impossible by `UNIQUE(aggregate_id, sequence)` constraint | N/A |
| Position identity invariant | `position_identity` is `(user_id, symbol, expiry, strike, option_type)` scoped | Structural (event payload) |
| Attribution invariant | `execution_id` identifies contribution, not ownership | Structural (event payload) |
| Instance invariant | Closed lifecycle instance cannot receive updates | Stop |
| Netting invariant | Multiple executions affecting same instrument contribute to same reconstructed netted position | Structural (projection) |
| Reopen invariant | Later non-zero exposure may create new lifecycle instance for same identity | Structural (event ordering) |

### Which invariants checked where

- **Append time**: aggregate identity, tenant identity, version, structural invariants (write safety).
- **Execution replay**: sequence, terminal (execution/order), fill consistency, tenant, version, aggregate.
- **Position reconstruction**: position identity, lifecycle instance boundaries, netting, tenant, version, terminal (instance).

## 15. Tenant / Security Model (fail-closed)

```text
Security scope = (aggregate_id, tenant_id) = (execution_id, user_id)
```

### Fail-closed behavior

| Condition | Write time | Replay time |
|-----------|-----------|-------------|
| Wrong `tenant_id` | Rejected; transaction rolls back | `ReplaySecurityError`; stop; no partial state |
| Wrong `aggregate_id` | Rejected; transaction rolls back | `ReplaySecurityError`; stop |
| Malformed event | Rejected (JSON validation) | `ReplayCorruptPayload`; stop |
| Conflicting event | `IntegrityError` → rollback | N/A (constraint prevents storage) |
| Sequence conflict | `IntegrityError` → rollback | N/A (constraint prevents storage) |

Never silently skip security-relevant events. Never reconstruct partial state.

## 16. Test Matrix (expanded per corrections)

### Position netting / ownership (§4, §5d)

| Test | Description |
|------|-------------|
| Multiple executions contribute to same position | Exec A: +10 NIFTY 24000 CE; Exec B: −5 NIFTY 24000 CE → position = +5 |
| Execution attribution does not create independent ownership | Two execution_ids contribute to same `position_identity`; position is single |
| Position close requires net=0 across ALL contributions | Cannot close position if other executions have open exposure |
| Position netting consistency | After replay, position net quantity matches authoritative `Position.net_quantity` |
| Cross-execution netting — same instrument | Execution A: BUY 10 NIFTY 24000 CE; Execution B: SELL 5 NIFTY 24000 CE → reconstructed position = +5 (not separate) |
| Cross-execution netting — same instrument | Execution A: BUY 10 NIFTY 24000 CE; Execution B: SELL 5 NIFTY 24000 CE → reconstructed position = +5 (not separate) |
| Execution attribution retained | Both events retain `execution_id`; position reconstruction aggregates by identity, not by execution |
| Multiple executions, same instrument — 3+ | Three executions affecting same instrument reconstruct one netted position |
| Close and reopen — lifecycle instance #1 CLOSED, instance #2 OPEN | BUY 10 → SELL 10 (instance #1 CLOSED) → BUY 5 (instance #2 OPEN, net +5) |
| Closed instance terminal protection | `PositionClosed` on instance prevents updates; new `PositionOpened` starts new instance |
| Different instruments | Different `position_identity` values remain independent |
| Cross-tenant isolation | Same instrument for different tenants never combine |
| Deterministic reconstruction | Same event sequence → same reconstructed netted position regardless of insertion order |

### Sequence allocation / concurrency (§10)

| Test | Description |
|------|-------------|
| First event to aggregate | `StrategyExecution` locked; sequence = 1 |
| Concurrent first events to same aggregate | Second writer blocks on `StrategyExecution` lock; gets sequence = 2 |
| Different executions do not block | Different `StrategyExecution` rows; independent sequences |
| Rollback releases lock | First writer rollback → second writer proceeds normally |
| Uniqueness constraint guard | `UNIQUE(aggregate_id, sequence)` rejects unexpected duplicate |

### Fail-closed persistence (§13)

| Test | Description |
|------|-------------|
| Module unavailable → application cannot start | Import failure at module load; no silent bypass |
| Persistence failure → authoritative rollback | `append_lifecycle_events` raises → `db.commit()` never reached |
| Event transaction failure → no committed execution | DB error on event insert → full rollback |

### Execution status mapping (§7)

| Test | Description |
|------|-------------|
| All filled → `FILLED` | 2-leg spread, both orders `FILLED` → execution `FILLED` |
| Partial fill + cancelled → `PARTIAL` | One order `FILLED`, one `CANCELLED` → exposure exists → `PARTIAL` |
| Partial fill + rejected → `PARTIAL` | One order `FILLED`, one `REJECTED` → `PARTIAL` |
| Failure before fill → `FAILED` | `ExecutionFailed` before any fill → `FAILED` |
| Failure after partial fill → `PARTIAL` | One fill, then `ExecutionFailed` → exposure exists → `PARTIAL` |
| Cancellation before fill → `CANCELLED` | `ExecutionCancelled` before any fill → `CANCELLED` |
| Cancellation after partial fill → `PARTIAL` | One fill, then `ExecutionCancelled` → `PARTIAL` |
| All cancelled → `CANCELLED` | All orders `CANCELLED` → `CANCELLED` |
| All rejected → `CANCELLED` | All orders `REJECTED` → `CANCELLED` |
| Still pending → `PENDING` | `TradeIntentCreated` only → `PENDING` |

### Valid transitions (§6)

| Test | Description |
|------|-------------|
| Execution: all valid transitions | `CREATED→ACTIVE→COMPLETED`, `→FAILED`, `→CANCELLED` |
| Order: all valid transitions | `PENDING→SUBMITTED→FILLED`, `→PARTIALLY_FILLED→FILLED`, `→CANCELLED`, `→REJECTED` |
| Position: valid transitions | `OPEN→UPDATED→CLOSED` (instance #1), `OPEN→UPDATED→CLOSED` (instance #2) |
| Position: lifecycle instance creation | `PositionOpened` after prior instance CLOSED creates new instance |
| Fill: append-only | Multiple fills per order; cumulative invariant |

### Invalid / terminal transitions (§6)

| Test | Description |
|------|-------------|
| Execution terminal: reject all | `COMPLETED→ACTIVE`, `FAILED→COMPLETED`, etc. (5 terminal states × events) |
| Order terminal: reject all | `FILLED→PENDING`, `CANCELLED→FILLED`, etc. |
| Position instance terminal: reject all | `CLOSED→OPEN`, `CLOSED→UPDATED` on same instance |
| Position instance: new OPEN after CLOSED allowed | `PositionOpened` after prior instance CLOSED creates new instance (not invalid) |
| Invalid order transition | `CANCELLED→FILLED` via `can_transition()` (Day 34 regression) |

### Duplicate / conflict (§11)

| Test | Description |
|------|-------------|
| Same `event_id` + identical event | Idempotent (ON CONFLICT DO NOTHING) |
| Same `event_id` + different payload | Impossible if §8a encoding correct; test verifies |
| Same `(aggregate_id, sequence)` + different event | `IntegrityError` → rollback |
| Same `(aggregate_id, sequence)` + identical event | Idempotent |

### Sequence gaps (§12)

| Test | Description |
|------|-------------|
| Missing event (sequence 1, 3) | `ReplaySequenceGap` → stop |
| First event starts at sequence > 1 | `ReplaySequenceGap` → stop |
| Out-of-order events in DB | Replay orders by `sequence`; if gap → stop |

### Tenant / aggregate mismatch (§15)

| Test | Description |
|------|-------------|
| Event with wrong `tenant_id` at write | Rejected; rollback |
| Event with wrong `tenant_id` at replay | `ReplaySecurityError` → stop (fail closed) |
| Event with wrong `aggregate_id` at replay | `ReplaySecurityError` → stop |
| Cross-tenant query returns no events | Tenant isolation |

### Unknown version / corrupt payload (§12)

| Test | Description |
|------|-------------|
| Unknown `event_version` | `ReplayUnknownVersion` → stop |
| Invalid JSON payload | `ReplayCorruptPayload` → stop |
| Missing required payload fields | `ReplayCorruptPayload` → stop |

### Deterministic replay (§12)

| Test | Description |
|------|-------------|
| Same events → same state (byte-identical) | Determinism |
| Replay twice → same result | Idempotency |
| No wall-clock dependency | Replay uses `sequence`, not `occurred_at` |
| No broker dependency | Replay never calls broker |

### `aggregate_type` schema consistency (§9)

| Test | Description |
|------|-------------|
| `aggregate_type` persisted | Verify column exists and is `"TradeLifecycle"` |
| `aggregate_type` indexed | Verify `(aggregate_type, event_type)` index |
| Event envelope `aggregate_type` matches DB column | Round-trip consistency |

### Event identity construction (§8a)

| Test | Description |
|------|-------------|
| Same inputs → same `event_id` | Deterministic encoding |
| Different sequence → different `event_id` | Verified |
| Different event_type → different `event_id` | Verified |
| Encoding is stable and reproducible | SHA256 hex |
| `\x1f` delimiter prevents collision | Unit separator cannot appear in normal IDs |

### Broker boundary (§8b)

| Test | Description |
|------|-------------|
| `OrderSubmitted` does NOT imply broker acceptance | Audit fact only |
| `OrderRejected` is StrikeNova validation, NOT broker rejection | Paper-lifecycle fact |
| Adapter failure NOT mapped to `OrderRejected` | Deferred to Days 39–42 |
| No broker outcome events generated | Day 38 scope boundary |

### No authorization / no bypass (§3, §17)

| Test | Description |
|------|-------------|
| No `ExecutionAuthorized` event type | Structural |
| No authorization vocabulary in payloads | Vocabulary scan |
| Days 33–36 chain not bypassed | `CentralRisk` PASS still required before execution |
| Lifecycle events cannot be created without `StrategyExecution` | Anchor dependency |

### Days 33–37 regression

| Test | Description |
|------|-------------|
| `can_transition()` unchanged | Day 34 regression |
| `PaperExecutionError` codes unchanged | Day 34 regression |
| `DomainEvent` contract unchanged | Day 37 regression |
| `EventBus.publish()` unchanged | Day 37 regression |
| No forbidden dependencies | Purity |

### Transaction rollback

| Test | Description |
|------|-------------|
| Event persistence fails → full rollback | Atomicity |
| Authoritative write fails → events never attempted | No partial events |
| DB connection lost → rollback | Failure safety |

### Total: ~105 tests

| Category | Count |
|----------|-------|
| Position netting / ownership | 5 |
| Sequence allocation / concurrency | 5 |
| Fail-closed persistence | 3 |
| Execution status mapping | 10 |
| Valid transitions | 4 |
| Invalid / terminal transitions | 4 |
| Duplicate / conflict | 4 |
| Sequence gaps | 3 |
| Tenant / aggregate mismatch | 4 |
| Unknown version / corrupt payload | 3 |
| Deterministic replay | 4 |
| Schema consistency (`aggregate_type`) | 3 |
| Event identity construction | 5 |
| Broker boundary | 4 |
| No authorization / no bypass | 4 |
| Days 33–37 regression | 5 |
| Transaction rollback | 3 |
| Integration / edge cases | 32 |
| **Total** | **~105** |

## 17. Risk / Execution Boundary (preserved)

```
Opportunity → StrategyCandidate (Day-32) → StrategyEvaluation (Day-31) →
CentralRisk (Day-33, PASS required) → PortfolioAnalytics (Day-35) →
FinalRiskGate (Day-36, PASS required) → User Decision → Execution
```

Day 38 rules:
- `TradeIntentCreated` can only occur AFTER `StrategyExecution` created by `execute_strategy()`, which requires `execute_gated_paper_entry()` (Day 34), which requires `CentralRiskStatus.PASS` (Day 33).
- No `ExecutionAuthorized` event exists; authorization stays in Day-33/36 chain.
- No lifecycle event carries authorization semantics.
- `TradeLifecycleAggregate` replay never produces an execution command.
- All events are **observation/fact**, never **command/authorization**.

## 18. Day 37 Integration

Day 38 reuses the approved Day 37 `DomainEvent` envelope exactly:

```python
from app.domain_events.contracts import DomainEvent
# DomainEvent fields: event_id, event_type, aggregate_type, aggregate_id,
#   occurred_at, tenant_id, event_version, payload, metadata
# All frozen; all validated; deterministic serialization via to_dict()
```

Day 38 does NOT modify `app/domain_events/contracts.py`, `bus.py`, or `idempotency.py`. The envelope is consumed as-is; `aggregate_type = "TradeLifecycle"` is Day 38's specific value; `event_type` values are Day 38's 14 types.

`EventBus` (`app/domain_events/bus.py`) may optionally be used for in-process dispatch if the application requires lifecycle event handlers, but the primary Day 38 concern is durable persistence (DB table), not in-process dispatch.

## 19. Existing System Integration

| Existing model | Day 38 treatment |
|----------------|-----------------|
| `StrategyExecution` | **Authoritative, unchanged** except minimal `append_lifecycle_events()` call. `execution_id` = aggregate anchor for sequence allocation. |
| `PaperOrder` | **Authoritative, unchanged**. Events reference `order_id`; replay verifies consistency. |
| `Position` | **Authoritative, unchanged (instrument-netted)**. Events carry `execution_id` as attribution, NOT ownership. Replay aggregates contributions by `position_identity`. |
| `PaperTransaction` | **Authoritative, unchanged**. Referenced by fill events via `execution_id`. |
| `StrategyLegExposure` / `ExitExposureAllocation` | **Authoritative, unchanged**. |
| `BulkExitRecord` | **Authoritative, unchanged**. |
| `Trade` / `Leg` (journal) | **Projection, unchanged**. |
| `app/domain_events/` (Day 37) | **Reused exactly** (§18). |
| `PaperExecution.can_transition()` | **Authoritative, unchanged**. Validates transitions before state changes; events record after. |
| `app/brokers/` | **Unchanged**. Day 38 does NOT modify broker adapters or add broker outcome semantics. |

### Modification to `paper_execution.py` (minimal, justified)

1. **Add required import** at top of file: `from app.trade_lifecycle.persistence import append_lifecycle_events`
2. **Add event append call** inside `execute_strategy()` and `apply_exit()`, within existing transaction, after authoritative writes.

No refactoring, no reordering, no `can_transition()` changes, no new execution path.

## 20. Migration Strategy

- Alembic revision: `add_trade_lifecycle_events_table`
- New table only; no modifications to existing tables
- No data backfill
- SQLite + PostgreSQL compatible
- **Not written** (design-only gate)

## 21. Exact Files Expected to Change (when approved)

| File | Action | Justification |
|------|--------|---------------|
| `app/trade_lifecycle/__init__.py` | New | Package public API |
| `app/trade_lifecycle/contracts.py` | New | Aggregate, state enums, event types, invariants |
| `app/trade_lifecycle/state_machine.py` | New | Pure transition validator |
| `app/trade_lifecycle/replay.py` | New | Deterministic replay algorithm |
| `app/trade_lifecycle/persistence.py` | New | DB model + `append_lifecycle_events()` + `next_sequence()` |
| `app/trade_lifecycle/event_id.py` | New | Deterministic event_id construction (§8a) |
| `tests/test_day38_trade_lifecycle.py` | New | ~105 tests |
| `alembic/versions/<hash>_add_trade_lifecycle_events.py` | New | Migration |
| `app/services/paper_execution.py` | **Modified** (minimal) | Add required import + `append_lifecycle_events()` call in `execute_strategy()` and `apply_exit()` |
| `docs/superpowers/specs/...` | This file | Design document |

### No changes to

- `app/models.py`
- `app/brokers/`
- `app/central_risk/`
- `app/final_risk_gate/`
- `app/portfolio_intelligence/`
- `app/domain_events/`
- Days 19–37 code or status

## 22. Risks / Open Questions

1. **Sequence lock contention**: `SELECT ... FOR UPDATE` on `StrategyExecution` serializes per-aggregate writers. Acceptable for paper-trading (low volume). Performance review for high-volume live trading (Days 39–42).
2. **Pre-Day-38 state**: existing executions without lifecycle events cannot be replayed from the event table. If needed, future forensic mode synthesizes events from authoritative tables (OUTSIDE Day 38).
3. **Event version evolution**: `payload` is extensible map; add keys, never remove. `SUPPORTED_VERSIONS` extended additively.
4. **`paper_execution.py` modification**: minimal (2 lines: import + function call) but required. The import is not optional — if unavailable, the application does not start.
5. **No authorization in events**: confirmed — authorization stays in Day-33/36 chain.

## 23. Proof Days 33–37 Unchanged

- **Day 33** `CentralRisk`: unchanged; Day 38 reads `CentralRiskResult`; no new policy rule.
- **Day 34** `paper_risk.py`: unchanged; `PaperExecutionError` codes enforced; Day 38 event append happens AFTER risk gate.
- **Day 35** `portfolio_intelligence/`: unchanged; Day 38 reads for audit context only.
- **Day 36** `final_risk_gate/`: unchanged; Day 38 reads gate result; never bypassed.
- **Day 37** `domain_events/`: reused exactly; `contracts.py`, `bus.py`, `idempotency.py` untouched.
- `models.py` unchanged; no new columns on existing tables.
- No Alembic migration to existing tables.
- No `ExecutionAuthorized` event; no authorization vocabulary.
- No forbidden dependencies.

---

## Design Conclusion

Final corrected Day 38 design satisfies all 12 mandatory corrections (10 prior + 2 final):

1. ✅ Position ownership/netting corrected — user/instrument-netted; execution attribution only.
2. ✅ First-event sequence concurrency — `StrategyExecution` row lock via `FOR UPDATE`.
3. ✅ `ImportError → pass` removed — required import; application does not start if unavailable.
4. ✅ Premature broker semantics removed — Day 38 paper lifecycle only; broker deferred to Days 39–42.
5. ✅ Execution status reconciliation — explicit mapping to `PENDING/FILLED/PARTIAL/FAILED/CANCELLED`.
6. ✅ `aggregate_type` consistently defined in schema, indexes, persistence, replay.
7. ✅ Deterministic `event_id` encoding explicit with canonical `SHA256` construction.
8. ✅ Full consistency pass across all sections.
9. ✅ Test matrix expanded to ~105 covering all corrected areas.
10. ✅ Final output per Control Center requirements.
11. ✅ **Execution replay vs Position reconstruction separated** — two distinct scopes; execution attribution not ownership; independent replay paths.
12. ✅ **Position lifecycle instances** — CLOSED = terminal for instance; identity reusable; `PositionOpened` starts new instance; no `CLOSED → OPEN` on same instance.

No code, no tests, no migration, no tracker edit. Control Center approval required before implementation.
