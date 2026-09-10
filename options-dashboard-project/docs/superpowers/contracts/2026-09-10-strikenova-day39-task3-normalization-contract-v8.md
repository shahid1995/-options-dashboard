# Contract v8 — StrikeNova Day39 Task3: Upstox Normalization Contract

**Status:** Draft for Control Center review
**Author:** Hermes (StrikeNova agent)
**Baseline (implementation authority):** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`
**Published Contract v7 commit:** `1e5a89b28245ddf99daf024730743169ecb96887`
**Scope:** Day39 Task3 only — normalization contract, NOT implementation
**Output file:** `docs/superpowers/contracts/2026-09-10-strikenova-day39-task3-normalization-contract-v8.md`
**Session type:** CONTRACT / ARCHITECTURE / AUDIT ONLY. No production code, no Task2/Task3 implementation, no tests, no migrations, no schema changes, no deployment.

**Protected files (must remain untouched):**

1. `options-dashboard-project/backend/app/brokers/adapters/upstox/adapter.py`
2. `options-dashboard-project/backend/app/brokers/adapters/upstox/mapper.py`
3. `options-dashboard-project/backend/app/services/paper_execution.py`
4. `options-dashboard-project/backend/app/services/upstox.py`
5. `options-dashboard-project/backend/tests/test_upstox_adapter.py`

---

## A. Purpose and Scope

This contract defines **Day39 Task3**: the pure normalization layer that converts Upstox provider order observations into `BrokerSyncEvent` canonical events (Task1 canonical contract), and defines the exact semantics that Task2 (durable ingestion) and Day38 (lifecycle replay) must satisfy for the full pipeline to be correct.

**Contract v8 is a revision of Contract v7.** Every claim in v8 is either verified against repository source (baseline `aa65e1e`) or against the current official Upstox developer documentation, and every v7 defect named by the Control Center review is corrected:

| Issue | v7 defect | v8 correction |
|---|---|---|
| 1 | §G status matrix was a literal placeholder | §G contains the complete 17-status matrix with CONFIRMED/OBSERVED/UNKNOWN confidence per value |
| 2 | provider-native vs derived identity conflated | §X–§Z separates the five identity layers exactly |
| 3 | D1 collision resistance unspecified | §Y defines exact fields, canonical serialization, null semantics, and collision analysis |
| 4 | cross-channel identity unresolved | §AA defines deduplicate/merge/retain rule per channel pair |
| 5 | `canonical_sequence=None` semantics underspecified | §U defines the semantic state model; quantity modification is explicit |
| 6 | `received_at` tie-break risk | §U/§V/§W forbid `received_at` from any business decision |
| 7 | terminal-first replay over-claimed | §Q proves Day38 replay guards; terminal-first is observation-only until legal |
| 8 | fill-first semantics undefined | §P defines fill-first convergence without double-counting |
| 9 | submission ownership ambiguous | §I/§J make ownership strictly order-scoped (tenant + execution_id + order_id) |
| 10 | timestamp semantics ambiguous | §AB defines exact per-timestamp behavior |
| 11 | null-tag behavior unspecified | §AE/§AI define one consistent rule fitting Task2 fail-closed identity |
| 25 | durable order-scoped ownership hidden | §J + §AW AR-5 define the durable representation (dedicated table) |

**Scope boundary:**
- Task3 receives validated Upstox provider observations.
- Task3 emits `BrokerSyncEvent` (Task1 canonical contract).
- Task3 does NOT own lifecycle decisions, idempotency, projection mutations, Day38 writes, broker ordering, or recovery; it never touches a database.
- Task3 is NOT a state machine, NOT a lock holder, NOT an idempotency store.

**Out of scope for this contract:**
- Task2 durable ingestion (referenced; prerequisite changes listed in §AW are NOT implemented here).
- Day38 state machine and replay (documented in `app/trade_lifecycle/`; referenced but not modified).
- Upstox adapter implementation details (Task3 is pure; the adapter is the boundary).
- Schema changes, migrations, protected files (explicitly excluded; §AW names required future changes but nothing is implemented in this session).

### A.1 Source-of-truth hierarchy

1. **Repository source at baseline `aa65e1e`** — authoritative for existing behavior. Never invent behavior; every behavioral claim is traceable to a file/function (§C, §D).
2. **Current official Upstox developer documentation** — authoritative for provider facts (§E, §G). Never carry a provider claim from v7 without re-verification.
3. **Contract v7** — prior design evidence only. Not authoritative. Anything v7 claims that source or official docs contradict is discarded.

### A.2 What this contract guarantees

A developer must be able to implement Task3 from this document **without making a new architectural decision**. §BA performs the implementability audit; if any ambiguity remains, this contract is incomplete by definition.

---

## B. Definitions

| Term | Definition |
|---|---|
| **Upstox raw observation** | Provider payload from Upstox order webhooks, STOMP order-update/trade messages, or order-history/position snapshots (status, quantities, prices, timestamps, order id, trade/transaction id). |
| **NormalizationContext** | The immutable context passed into the pure Task3 normalizer: tenant, broker, application-order resolution, authoritative lot size, source mode, and the raw observation. |
| **Pure Task3 normalizer** | A function `(NormalizationContext) -> BrokerSyncEvent | Failure`. No DB access, no locks, no randomness, no wall-clock dependence beyond what the raw observation provides. Same input → same output. |
| **BrokerSyncEvent** | The Task1 canonical event (frozen dataclass). Immutable, deterministic identity, tenant-scoped. |
| **Provider-native identity** | Identity assigned by Upstox: `order_id` (order identity), `trade_id`/transaction id (trade identity), provider message/event id when the channel delivers one. |
| **provider_event_id** | `BrokerSyncEvent.provider_event_id`: the provider-native event identifier when the delivering channel provides one; `None` when the channel provides none (Upstox websocket order-update messages do not deliver a stable per-message event id). |
| **D1** | **Deterministic provider-observation identity.** A StrikeNova-derived SHA-256 key identifying one specific provider observation. NEVER called "provider event id". Collision-resistant per §Y. |
| **D2** | **Deterministic provider-trade identity.** A StrikeNova-derived key identifying one specific economic fill/trade. Prefer provider `trade_id`; deterministic composite fallback per §Z. NEVER called "provider trade id". |
| **canonical_id** | Task1 `BrokerSyncEvent.canonical_id`: deterministic SHA-256 identity of the canonical event (tenant-scoped). NOT a provider event id; computed from `provider_event_id` when present, else from broker-order + discriminator. |
| **content fingerprint** | Task2 `_content_fingerprint()`: separate SHA-256 over all semantically relevant canonical content; used for duplicate-vs-conflict classification. |
| **OrderFacts** | Normalized order-level state in `BrokerSyncEvent.order_facts`. Frozen value object. |
| **FillFacts** | Normalized fill-level state in `BrokerSyncEvent.fill_facts`. Frozen value object; `fill_timestamp` must be timezone-aware. |
| **canonical_sequence** | Task2 broker-ordering field (`BrokerSyncEvent.canonical_sequence`). Positive int or `None`. Upstox provides NO provider sequence, so Task3 leaves it `None`; Task2 never fabricates it. |
| **Task2** | Durable ingestion: validation, tenant isolation, broker ordering, durable idempotency, terminal enforcement, normalized projection, Day38 lifecycle append. Owns `broker_sync_idempotency`, `broker_order_projection`, `broker_sync_sequence_anchor` tables. |
| **Day38** | Append-only lifecycle event stream (`trade_lifecycle_events`) + deterministic replay state machine (`replay_execution_events`). |
| **TradeLifecycleEvent** | Persisted Day38 event. NO relational `order_id` column; `order_id` lives in `payload_json`. |
| **StrategyExecution** | Day38 aggregate (`aggregate_id`). Serialization/aggregate boundary. `app/models.py:95`. |
| **PaperOrder** | Application order/leg. `client_order_id` = canonical application-order reference; `execution_id` → owning execution. Lifecycle ownership boundary. `app/models.py:137`. |
| **Durable order-scoped ownership record** | The AR-5 table `broker_order_lifecycle_state` (§J.4, §AW.5): per-order lifecycle ownership evidence independent of `payload_json` scanning. |
| **Semantic projection current state** | The fold of ALL `BrokerOrderProjection` rows for (tenant, broker, broker_order_id) under the §V/§W merge lattice. NOT "the latest row by id". |
| **Observation-only** | A canonical event that updates the projection (durable normalized state) but produces NO Day38 lifecycle event because Day38 replay cannot legally accept it (§N). |
| **Projection-only broker event** | `ORDER_ACCEPTED`: maps to lifecycle event type `None`; projection + idempotency are persisted, no Day38 event, no Day38 sequence consumed. |
| **Quarantine** | A deterministic REJECTED outcome (Task2 `IngestionError` action) leaving no durable state other than observability for recovery (§R). |
| **received_at** | Task1 operational receipt timestamp. Operational metadata ONLY; never business ordering (§U.3). |

---

## C. Verified Repository Baseline

Verified by direct inspection of baseline `aa65e1e` (and the current working tree, which is unchanged for these files apart from protected-file modifications that are excluded from this contract).

### C.1 Domain model

- `StrategyExecution` (`app/models.py:95`): `user_id` (str, index), `execution_id` (str(40), index), `client_order_id` (str(64)), `status` (str(12), default "PENDING"). Unique `(user_id, client_order_id)`.
- `PaperOrder` (`app/models.py:137`): `user_id` (str, index), `client_order_id` (str(64)), `execution_id` (str(40), nullable, index), `quantity` (int, LOTS), `lot_size` (int, contracts per lot), `status` (str(20), default "PENDING"), `filled_quantity` (int, LOTS, default 0), `fill_price` (float, nullable), `rejected_reason` (str(255), nullable). Unique `(user_id, client_order_id)`.
- One `StrategyExecution` contains one or more `PaperOrder` rows.
- `PaperOrder.execution_id` → owning `StrategyExecution.execution_id`. Execution = Day38 aggregate; PaperOrder = lifecycle ownership boundary (§I).

### C.2 Task1 canonical contract (`app/broker_sync/__init__.py`)

- `BrokerEventType`: ORDER_SUBMITTED, ORDER_ACCEPTED, ORDER_REJECTED, ORDER_CANCELLED, ORDER_EXPIRED, PARTIAL_FILL, FULL_FILL, FILL_RECORDED, ORDER_RECOVERED (line 21).
- `BrokerEventSourceMode`: STREAM, RECOVERY, POLLED_SNAPSHOT (line 35).
- `CanonicalOrderState`: PENDING, SUBMITTED, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED, UNKNOWN (line 43).
- `OrderFacts` (line 61): `order_id`, `broker_order_id`, `status`, `total_quantity`, `cumulative_filled`, `average_price`, `last_fill_price`, `last_fill_quantity`, `rejection_reason`, `is_terminal`.
- `FillFacts` (line 77): `fill_id`, `fill_quantity`, `fill_price`, `fill_timestamp` (must be tz-aware), `cumulative_filled_after`, `remaining_after`.
- `BrokerSyncEvent` (line 120): `tenant_id`, `broker`, `event_type`, `event_version`, `received_at` (tz-aware), `provider_event_id` (optional), `event_timestamp` (optional, tz-aware), `source_mode`, `provider_sequence` (optional, positive int), `broker_order_id` (optional), `canonical_sequence` (optional, positive int), `order_facts`, `fill_facts`, `metadata` (deep-frozen Mapping).
- `BrokerSyncEvent.__post_init__` fail-closed identity rules (line 169):
  - `provider_event_id` OR `broker_order_id` must be present.
  - If neither → `ValueError`.
  - If `provider_event_id` absent AND `broker_order_id` present alone → requires `canonical_sequence` or `fill_facts` as additional discriminator.
- `canonical_id` (line 182): if `provider_event_id` → `SHA256(tenant \x1f broker \x1f provider_event_id \x1f event_type)`; else → `SHA256(tenant \x1f broker \x1f event_type \x1f broker_order_id [\x1f canonical_sequence | fill discriminator])`. Never uses `received_at`.
- `metadata` is deep-frozen; `canonical_id` is deterministic irrespective of metadata.

### C.3 Task2 durable ingestion (`app/broker_sync/ingestion.py`)

- `_BROKER_TO_LIFECYCLE` (line 144): ORDER_SUBMITTED→OrderSubmitted; ORDER_ACCEPTED→None (projection-only); PARTIAL_FILL→OrderFilled; FILL_RECORDED→FillRecorded; FULL_FILL→OrderFilled; ORDER_CANCELLED→OrderCancelled; ORDER_REJECTED→OrderRejected; ORDER_EXPIRED→OrderCancelled.
- `_map_to_lifecycle_event_type` (line 171): unknown types raise `IngestionError(REJECTED)`. `ORDER_RECOVERED` is therefore rejected at the mapping layer — recovery is a later task.
- `_event_canonical_state` (line 193): maps event type → canonical state (ORDER_ACCEPTED→OPEN, PARTIAL_FILL/FILL_RECORDED→PARTIALLY_FILLED, FULL_FILL→FILLED, etc.).
- `_validate_broker_sequence_position` (line 214): position validation without advancement; returns None when `canonical_sequence is None` (no validation possible by definition). Gap/stale raise REJECTED.
- `_ensure_broker_sequence_anchor` (line 279) / `_advance_broker_sequence` (line 319): first-use anchor creation and advancement INSIDE the SAVEPOINT (v4/v5 fixes).
- `_validate_quantity_invariants` (line 380): negative fill rejected; cumulative regression rejected; cumulative < prev + fill rejected; overfill rejected; remaining inconsistency rejected; fill > total rejected. FAIL CLOSED, no silent repair.
- `_build_projection` (line 471): carries forward previous state only when `canonical_sequence is not None`; total_quantity replaced by `order_facts.total_quantity` when present; cumulative replaced by fill cumulative; remaining derived.
- `_append_lifecycle_from_event` (line 570): maps event → Day38 type; aggregate = resolved `execution_id`; payload includes `canonical_id`, `broker`, `broker_event_type`, `broker_event_version`, `provider_event_id`, `source_mode`, `broker_order_id`, `event_timestamp`, `order_facts`, `fill_facts`; Day38 replay-required fields: `order_id` (STRICTLY from `order_facts.order_id` — the canonical application-order reference; NEVER `broker_order_id`), `cumulative_filled` (positive int), `fill_quantity` (positive int).
- `_resolve_execution_identity` (line 686): STRICT — requires `order_facts.order_id`; maps `PaperOrder.client_order_id == order_id` (tenant-scoped) → `PaperOrder.execution_id`. NO fallback to `broker_order_id`. Returns None → REJECTED (fail closed).
- `_lock_execution_for_sequencing` (line 738): `SELECT ... FOR UPDATE` on `StrategyExecution` (tenant + execution_id). SQLite treats FOR UPDATE as no-op.
- `_allocate_day38_sequence` (line 768): lock + `next_event_sequence(db, tenant, "TradeLifecycle", execution_id)`.
- `ingest_canonical_event` (line 790) → `_do_ingest` (line 824): durable idempotency check first (DUPLICATE_NOOP / CONFLICT), then sequence validation, same-sequence conflict reclassify, lifecycle mapping, execution identity resolution (fail closed), **previous projection read BEFORE the lock**, terminal enforcement, quantity invariants, projection build, Day38 sequence allocation (lock acquired here), then SAVEPOINT { ensure anchor, add projection, add idempotency, append lifecycle, advance sequence }, with SAIntegrityError/IngestionError(CONFLICT) reclassification to DUPLICATE_NOOP/CONFLICT.

### C.4 Day38 lifecycle (`app/trade_lifecycle/`)

- `TradeLifecycleEvent` (`persistence.py:81`): `event_id` (SHA-256 PK), `aggregate_type`, `aggregate_id`, `event_type`, `event_version`, `tenant_id`, `sequence`, `payload_json`, `metadata_json`. Unique `(tenant_id, aggregate_type, aggregate_id, sequence)`. **No `order_id` column.**
- `event_id` (`envelope.py:44`): `SHA256(tenant \x1f aggregate_type \x1f aggregate_id \x1f event_type \x1f sequence)`.
- `replay_execution_events` (`replay.py:553`): contiguous sequence from 1; tenant/aggregate/type mismatch → `ReplaySecurityError`; version guard; terminal-execution protection; per-event transition guards:
  - `TradeIntentCreated`: only when execution is None (CREATED).
  - `ExecutionActivated`: only from CREATED (→ ACTIVE).
  - `OrderCreated`: requires execution CREATED/ACTIVE; requires `payload.quantity` positive int; order must not already exist (PENDING).
  - `OrderSubmitted`: requires order PENDING (→ SUBMITTED).
  - `OrderFilled`: requires order SUBMITTED or PARTIALLY_FILLED; `cumulative_filled` positive int strictly greater than previous; ≤ order quantity; (→ FILLED if == quantity else PARTIALLY_FILLED).
  - `OrderCancelled`/`OrderRejected`: requires order SUBMITTED or PARTIALLY_FILLED.
  - `FillRecorded`: requires order SUBMITTED/PARTIALLY_FILLED/FILLED; `fill_quantity` positive int; ledger + fill ≤ quantity.
  - Terminal order states: FILLED, CANCELLED, REJECTED. Terminal execution states: COMPLETED, FAILED, CANCELLED.

### C.5 Schema facts

- `trade_lifecycle_events`: no `order_id` relational column (payload only).
- `broker_order_projection`: one row per applied canonical event; lookup ordered by `canonical_sequence.desc().nullslast(), id.desc()` — the `id` tiebreaker is insert-order dependent for `None`-sequence rows (Blockers B3, §U.5, §W.9).
- `broker_sync_idempotency`: PK `canonical_id`; stores tenant, broker, broker_order_id, canonical_sequence, event_type, event_version, content_fingerprint, source_mode, provider_event_id, received_at, status.
- `broker_sync_sequence_anchor`: per (tenant, broker, broker_order_id) last_sequence.
- `strategy_executions`, `paper_orders`: as in C.1.

### C.6 The five + three architectural blockers (verified in source)

| ID | Blocked behavior | Verified in | Required fix |
|---|---|---|---|
| B1 | Execution lock serializes, but lifecycle ownership must be per-`PaperOrder` | `_do_ingest` locks execution; never checks per-order `OrderSubmitted` ownership | AR-1 order-scoped ownership check (§J, §AW.1) |
| B2 | `previous` projection read BEFORE lock | `_do_ingest` line ~980 reads projection; lock at `_allocate_day38_sequence` | AR-2 lock before mutable-state reads (§L, §AW.2) |
| B3 | `canonical_sequence=None` lookup uses `id.desc()` tiebreaker | `_do_ingest` projection query; `_build_projection` | AR-3 post-lock re-read + AR-4 semantic merge (§U–§W, §AW.3/4) |
| B4 | No durable per-order lifecycle ownership representation | `TradeLifecycleEvent` has no `order_id` column | AR-5 dedicated `broker_order_lifecycle_state` table (§J.4, §AW.5) |
| B5 | Fill-first convergence undefined | No fill-before-submission handling in Task2 | AR-6 fill-first reconciliation (§P, §AW.6) |
| B6 | Terminal-first replay boundary undefined | Replay guards reject terminal without SUBMITTED/PARTIALLY_FILLED | AR-7 terminal-first observation-only boundary (§Q, §AW.7) |
| B7 | Current projection is "latest row", not materialized semantic state | Projection lookup + fold semantics unspecified | AR-8 current-projection representation (§V, §AW.8) |
| B8 | `received_at`/`id` could influence business ordering | `id.desc()` tiebreaker; no documented prohibition | §U.3/§W explicit prohibition; AR-4 |

---

## D. Verified Task1/Task2/Day38 Mechanics

### D.1 Identity chain (verified)

```
Upstox observation
  ├─ provider_order_id (order_id)          → BrokerSyncEvent.broker_order_id
  ├─ provider_trade_id (trade_id)          → FillFacts.fill_id (D2 preferred source)
  ├─ provider event id (webhook only)      → BrokerSyncEvent.provider_event_id
  ├─ exchange_timestamp (epoch ms UTC)     → BrokerSyncEvent.event_timestamp
  └─ channel                                → BrokerSyncEvent.source_mode

BrokerSyncEvent:
  ├─ provider_event_id  present → canonical_id = SHA256(tenant,broker,provider_event_id,event_type)
  └─ provider_event_id  absent  → canonical_id = SHA256(tenant,broker,event_type,broker_order_id[,canonical_sequence|fill discriminator])

Task2 idempotency: canonical_id PK; fingerprint distinguishes DUPLICATE_NOOP vs CONFLICT
Task2 projection: BrokerOrderProjection row per applied event
Task2 lifecycle: TradeLifecycleEvent(aggregate_id = execution_id, payload.order_id = order_facts.order_id)
```

### D.2 The five identity layers (distinction table)

| Layer | Producer | Value | Purpose | Never used for |
|---|---|---|---|---|
| Provider-native order id | Upstox | `order_id` (e.g. `240108010918222`) | Broker order identity | Application order identity, lifecycle ownership |
| Provider-native trade id | Upstox | `trade_id`/transaction id | Economic fill identity (D2 source) | Observation identity |
| D1 | Task3 | SHA-256 (deterministic) | One observation identity | Lifecycle ownership, business precedence |
| D2 | Task3 | provider `trade_id` or SHA-256 composite | One economic fill identity | Observation identity |
| `canonical_id` | Task1 | SHA-256 | Canonical event identity (idempotency PK) | Provider-native identity |
| content fingerprint | Task2 | SHA-256 over full content | Duplicate vs conflict | Identity of any kind |

`provider_event_id` is the **provider-native event identity** when the channel delivers one; D1 is the **deterministic provider-observation identity**; D2 is the **deterministic provider-trade identity**; `canonical_id` is the **canonical event identity**; the fingerprint is the **content identity**. A StrikeNova-derived hash is never called "provider event id" and never called "provider trade id".

### D.3 What Task2 actually does with each canonical event type (verified)

| BrokerEventType | Projection state | Day38 lifecycle | Day38 sequence | Terminal |
|---|---|---|---|---|
| ORDER_SUBMITTED | SUBMITTED | OrderSubmitted | consumed | no |
| ORDER_ACCEPTED | OPEN | none (projection-only) | NOT consumed | no |
| ORDER_REJECTED | REJECTED | OrderRejected | consumed | yes |
| ORDER_CANCELLED | CANCELLED | OrderCancelled | consumed | yes |
| ORDER_EXPIRED | EXPIRED | OrderCancelled | consumed | yes |
| PARTIAL_FILL | PARTIALLY_FILLED | OrderFilled | consumed | no |
| FULL_FILL | FILLED | OrderFilled | consumed | yes |
| FILL_RECORDED | PARTIALLY_FILLED | FillRecorded | consumed | no |
| ORDER_RECOVERED | (rejected at mapping) | — | — | — |

Day38 sequence consumption is independent of `canonical_sequence`; projection-only events consume NO Day38 sequence (else gaps).

---

## E. Upstox Official Documentation Sources

Provider facts in this contract are verified against the current official Upstox developer documentation:

| Source | URL | Used for |
|---|---|---|
| Order Status appendix | `https://upstox.com/developer/api-documentation/appendix/order-status/` | §G complete status inventory (17 statuses) |
| Place/Modify/Cancel order v3 | `https://upstox.com/developer/api-documentation/v3/...` | Order lifecycle, order_id format, terminal behavior of modify/cancel on completed orders |
| Get Order History / Get Trades | `https://upstox.com/developer/api-documentation/...` | RECOVERY/POLLED_SNAPSHOT fields (order status, filled_quantity, trade/transaction ids, exchange_timestamp) |
| WebSocket / STOMP | `https://upstox.com/developer/api-documentation/...` (websocket order-update & trade feed) | STREAM channel semantics, absence of per-message event id |

**Verification date:** 2026-09-10. If the appendix changes, confidence markers in §G must be re-evaluated before implementation.

### E.1 Channel facts (verified)

- Upstox order-webhook (V3 webhooks) delivers a per-event payload with provider event id.
- Upstox STOMP websocket (order-update and trade feeds) delivers messages **without a stable per-message event id**; each message carries order id / trade id and an exchange timestamp.
- The websocket trade feed carries `trade_id` (transaction id); the order-update feed carries `order_id`, `status`, quantities, and does NOT carry trade ids.
- `exchange_timestamp` (epoch milliseconds, UTC) is the provider event time; `order_timestamp` is the order placement time.
- There is **no** provider sequence number on Upstox order events — `canonical_sequence` is therefore always `None` from Task3 (§U).

---

## F. Status Confidence Model

Three confidence classes, defined operationally:

| Class | Meaning | Evidence required |
|---|---|---|
| **CONFIRMED** | Listed in the current official Upstox Order Status appendix (§G source) | Exact value appears in the appendix at verification date |
| **OBSERVED** | Seen in live/documented payloads beyond the appendix (e.g. `filled_quantity` semantics; legacy SDK values) | Repo adapter evidence or official SDK/payload samples |
| **UNKNOWN** | Not present in any current official source; value cannot be confirmed | Absence from appendix; no payload evidence. Anything in this class must FAIL CLOSED at Task3 (never guessed, never coerced) |

**Counting rule (Issue 1 correction):** the official appendix lists **exactly 17 order statuses**. No status is invented, duplicated, or renamed. `partially_filled` and `expired` are NOT official Upstox order statuses; partial fills are OBSERVED from `filled_quantity` with status `open`/`complete`, and expiry is not an order status (GTT rule expiry exists separately). Any v7 mention of `partially_filled` as a status value is corrected here.

---

## G. Complete 17-Status Matrix

Source: official Upstox Order Status appendix (E). This replaces the v7 §G placeholder.

Cols: Upstox status | confidence | provider meaning | canonical broker event | projected canonical state | Day38 lifecycle | terminal | observation class | fill-bearing?

| # | Upstox status | Conf | Meaning | Canonical event | Projected state | Day38 | Terminal | Class | Fill-bearing |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `put order req received` | CONFIRMED | Request to place order received by broker | ORDER_SUBMITTED | SUBMITTED | OrderSubmitted | no | submission evidence | no |
| 2 | `validation pending` | CONFIRMED | Order received, awaiting validation | ORDER_SUBMITTED | SUBMITTED | **none** (already submitted) | no | chatter (repeated submission observation) | no |
| 3 | `open pending` | CONFIRMED | Order received, pending opening | ORDER_SUBMITTED | SUBMITTED | none | no | chatter | no |
| 4 | `trigger pending` | CONFIRMED | Awaiting trigger to market (SL/SL-M) | ORDER_SUBMITTED | SUBMITTED | none | no | chatter | no |
| 5 | `open` | CONFIRMED | Active and open in market (broker accepted) | ORDER_ACCEPTED | OPEN | **none** (projection-only) | no | broker working | no |
| 6 | `complete` | CONFIRMED | Fully executed | FULL_FILL | FILLED | OrderFilled | yes | terminal fill | yes (filled_quantity == quantity) |
| 7 | `rejected` | CONFIRMED | Rejected by exchange | ORDER_REJECTED | REJECTED | OrderRejected | yes | terminal | no |
| 8 | `cancelled` | CONFIRMED | Successfully cancelled | ORDER_CANCELLED | CANCELLED | OrderCancelled | yes | terminal | no |
| 9 | `modify pending` | CONFIRMED | Modification initiated, pending | ORDER_SUBMITTED | SUBMITTED | none | no | chatter/modification observation | no |
| 10 | `modify validation pending` | CONFIRMED | Modification awaiting validation | ORDER_SUBMITTED | SUBMITTED | none | no | chatter/modification observation | no |
| 11 | `modified` | CONFIRMED | Order successfully modified | ORDER_SUBMITTED | SUBMITTED | none | no | modification acknowledgment (quantity authority) | no |
| 12 | `not modified` | CONFIRMED | Modification not processed; original state retained | ORDER_SUBMITTED | SUBMITTED | none | no | modification failure observation | no |
| 13 | `cancel pending` | CONFIRMED | Cancellation in progress, not confirmed | ORDER_SUBMITTED | SUBMITTED | none | no | chatter | no |
| 14 | `not cancelled` | CONFIRMED | Cancellation not processed; order active | ORDER_SUBMITTED | SUBMITTED | none | no | cancellation failure observation | no |
| 15 | `after market order req received` | CONFIRMED | New after-market order request received | ORDER_SUBMITTED | SUBMITTED | none | no | submission evidence (AMO) | no |
| 16 | `modify after market order req received` | CONFIRMED | AMO modification request received | ORDER_SUBMITTED | SUBMITTED | none | no | chatter/modification observation | no |
| 17 | `cancelled after market order` | CONFIRMED | After-market order cancelled | ORDER_CANCELLED | CANCELLED | OrderCancelled | yes | terminal (AMO) | no |

**Explicitly NOT Upstox order statuses (corrections):**
- `partially_filled` — NOT in the appendix. Partial-fill state is **derived**: status `open`/`complete` + `filled_quantity` between 0 and quantity. Task3 normalizes the derived state into `PARTIAL_FILL` (order not complete, filled_quantity > 0) or `FULL_FILL` (complete, filled_quantity == quantity, or complete alone).
- `expired` — NOT in the appendix. `ORDER_EXPIRED` canonical remains in the Task1 catalog for non-Upstox providers; Task3 must never emit `ORDER_EXPIRED` from an Upstox status (no source status maps to it). If a future Upstox field exposes expiry, re-verify before adding.

### G.1 Status → canonical mapping rules (final)

| Rule | Provider evidence | Canonical event |
|---|---|---|
| R-SUBMIT | `put order req received` OR `after market order req received` (first durable submission evidence for the order) | ORDER_SUBMITTED |
| R-CHATTER | `validation pending`, `open pending`, `trigger pending`, `modify pending`, `modify validation pending`, `cancel pending`, `not modified`, `not cancelled` | ORDER_SUBMITTED (repeated submission observation; §O prevents duplicate Day38 submission) |
| R-MODIFIED | `modified` (carries authoritative new quantity + price) | ORDER_SUBMITTED (modification observation; quantity authority per §AC) |
| R-OPEN | `open` | ORDER_ACCEPTED (projection-only) |
| R-REJECTED | `rejected` | ORDER_REJECTED |
| R-CANCELLED | `cancelled`, `cancelled after market order` | ORDER_CANCELLED |
| R-FULL | `complete` | FULL_FILL |
| R-PARTIAL | `open`/`complete` + `0 < filled_quantity < quantity` | PARTIAL_FILL |
| R-UNKNOWN | any unrecognized value | Task3 Failure (fail closed; §AJ) |

---

## H. Provider Semantic State Machine

Upstox order statuses are **provider operational states**, not StrikeNova canonical lifecycle states.

### H.1 Provider state categories

1. **Submission evidence** — `put order req received`, `after market order req received`. The ONLY statuses that can legally create the first `OrderSubmitted` Day38 event (§O ownership).
2. **Request/processing chatter** — `validation pending`, `open pending`, `trigger pending`, `modify pending`, `modify validation pending`, `cancel pending`, `not modified`, `not cancelled`, `modify after market order req received`. Observation-only; never mint Day38 transitions.
3. **Modification acknowledgment** — `modified`. Carries authoritative new quantity/price (quantity authority per §AC.2). Observation-only for Day38.
4. **Broker working state** — `open`. The only "accepted/working" status → ORDER_ACCEPTED → projection-only (no Day38 event; `_BROKER_TO_LIFECYCLE` = None).
5. **Provider fill state** — derived from `filled_quantity` + status. `complete` → FULL_FILL; `open`/`complete` with partial fill → PARTIAL_FILL.
6. **Provider terminal state** — `cancelled`, `rejected`, `complete` (+ `cancelled after market order`). Terminal canonical events only when Day38-legal (§Q); otherwise observation-only terminal projection.

### H.2 Key semantic rule

> Non-terminal provider status ≠ broker working state. Only `open` means broker working/acceptance. Every other non-terminal value is submission/modification/processing observation. Day38 transitions are minted only from durable evidence under the lock (§K), never from status chatter.

### H.3 Why chatter must not mint Day38 transitions

- `OrderSubmitted` is the Day38 audit record of the submission attempt; the approved Day38 design mandates "No lifecycle event implies broker state" and there is no standalone broker-acceptance event in the Day38 vocabulary (§13/§14, reflected in `_BROKER_TO_LIFECYCLE`).
- Minting `OrderSubmitted` per chatter status would produce the non-replayable stream PENDING→SUBMITTED→SUBMITTED (`replay.py:_apply_order_submitted` rejects order not in PENDING).
- Therefore ONE submission observation creates `OrderSubmitted`; every later submission-class observation is observation-only unless it carries a new economic fact (§O).

### H.4 Derived-fill authority

`PARTIAL_FILL`/`FULL_FILL` are derived from `(status, filled_quantity, quantity)`:
- `complete` → FULL_FILL regardless of supplied `filled_quantity` (provider guarantees full execution).
- `open` + `0 < filled_quantity < quantity` → PARTIAL_FILL with cumulative = `filled_quantity`, remaining = `quantity - filled_quantity`.
- `open` + `filled_quantity == quantity` → FULL_FILL (provider may report full under `open` before `complete`).
- `open` + `filled_quantity == 0` → no fill; ORDER_ACCEPTED (projection-only).
- Any negative/absent `filled_quantity` with non-terminal status → fail closed (§AJ).
- `cancelled`/`rejected` + `filled_quantity > 0` → terminal event carries the fill facts as OBSERVED (fill-bearing terminal); the fill is a real economic fact D2-counted once (§P).

---

## I. Application Order / Execution Model

### I.1 Domain model (verified, §C.1)

- `StrategyExecution.execution_id` = Day38 aggregate identity = **serialization / aggregate boundary**.
- `PaperOrder.client_order_id` = canonical application-order reference = **lifecycle ownership boundary**.
- `PaperOrder.execution_id` = which execution owns this order.
- `PaperOrder.quantity` is in LOTS; `PaperOrder.lot_size` is contracts per lot (§AD).

### I.2 Ownership predicate

Lifecycle ownership is:

```
ownership(execution_id, order_id) =
    EXISTS PaperOrder p
    WHERE p.user_id = tenant
      AND p.client_order_id = order_id
      AND p.execution_id = execution_id
```

A Day38 lifecycle event for `order_id` is legal only when the owning execution aggregate is the one being appended to AND the broker observation resolves through this predicate. **`broker_order_id` NEVER substitutes for `order_id`** (§D.2, `_resolve_execution_identity` fails closed).

### I.3 Multi-order model (Issue 9)

```
StrategyExecution E
  ├── PaperOrder A (client_order_id = "A")
  ├── PaperOrder B (client_order_id = "B")
  └── PaperOrder C (client_order_id = "C")
```

- Each PaperOrder independently receives its own `OrderSubmitted(A)`, `OrderSubmitted(B)`, `OrderSubmitted(C)`.
- Repeated observations for A never produce a second `OrderSubmitted(A)` (§O).
- Fills for B never touch A's cumulative; cumulative is order-scoped in both projection and Day38 payload (§V, §AS).
- The execution aggregate serializes the writes (lock); ownership decisions remain order-scoped (B1 distinction, §26 of the review).

---

## J. Lifecycle Ownership Rule

### J.1 The rule

> A broker observation may produce a Day38 lifecycle event for `order_id` if and only if, under the execution lock (§L), durable evidence shows the order has NOT already reached that lifecycle state, AND the deterministic identity of the observation is not a duplicate of an already-applied observation.

Ownership is therefore: **tenant + execution_id + order_id + lifecycle-state evidence**. Not execution_id alone. Not broker_order_id.

### J.2 Durable evidence sources

| Evidence | Where | Used for |
|---|---|---|
| `broker_sync_idempotency` | canonical_id PK | observation applied once (dedup) |
| `broker_order_projection` | per-event rows + semantic fold | current normalized order state |
| `trade_lifecycle_events` | append-only stream | Day38 lifecycle state (currently via `payload_json.order_id` — replaced for ownership by AR-5) |
| **`broker_order_lifecycle_state` (AR-5)** | dedicated table (new) | per-order durable ownership: last lifecycle event type + sequence per (tenant, order_id) |

### J.3 What does NOT decide ownership

- `received_at` — operational metadata (§U.3).
- `canonical_sequence` — Task2 ordering only, and `None` for Upstox (§U).
- `provider_event_id`/D1 — observation identity, not lifecycle evidence.
- Insert order / `id.desc()` — not semantic evidence (§W.9).
- Broker order id — never an application order identity (§D.2).

### J.4 Decision: durable order-scoped ownership representation (AR-5)

The reviewer requires an explicit decision on `payload_json` scanning.

**V8 decision: `payload_json` scanning is NOT acceptable as the durable ownership invariant.** Reasoning:

1. `payload_json` is a Text column with no indexable structure; per-order lifecycle queries require a full-stream scan per ingestion decision.
2. Correctness under concurrency relies entirely on the lock serializing the scan; that is safe but brittle and unprovable at the schema level (no unique constraint can enforce "one OrderSubmitted per order").
3. The Day38 stream is owned by Day38; Task2 deriving ownership by re-parsing its payloads couples Task2 to Day38 payload shape and to the replay guards.

**Required durable representation (prerequisite, NOT implemented in this session):** a new Task2-owned table

```
broker_order_lifecycle_state (
  tenant_id        str(128)  NOT NULL,
  order_id         str(64)   NOT NULL,          -- application order id (order_facts.order_id)
  execution_id     str(40)   NOT NULL,          -- owning execution (aggregate)
  broker           str(32)   NOT NULL,
  broker_order_id  str(64),                     -- provider order id (last observed)
  last_event_type  str(32)  NOT NULL,           -- last Day38 lifecycle event applied for this order
  last_sequence    int       NOT NULL,          -- Day38 sequence of last_event_type
  last_cumulative  int       NOT NULL DEFAULT 0,
  is_terminal      bool      NOT NULL DEFAULT false,
  updated_at       datetime  NOT NULL,
  PRIMARY KEY (tenant_id, order_id),
  UNIQUE (tenant_id, execution_id, order_id),
  INDEX (tenant_id, execution_id)
)
```

- **Migration required:** yes (new table in broker_sync schema, single forward revision).
- **Backfill required:** no (new capability; existing streams remain readable, and ownership for pre-existing orders is computed from the lifecycle stream ONCE during the migration or the first post-migration ingest under the lock — deterministic, documented).
- **Unique constraint:** PK `(tenant_id, order_id)` enforces one ownership record per order (schema-level "one submission ownership" enforcement).
- **Concurrency:** writes happen only inside the execution-lock + SAVEPOINT; upsert is `INSERT ... ON CONFLICT (tenant_id, order_id) DO UPDATE`.
- **Rollback:** migration downgrade drops the table; no Day38 table is touched.

§AW.5 carries the full prerequisite table row.

### J.5 Submission ownership (AR-1)

Under the lock: if `broker_order_lifecycle_state(order_id).last_event_type == "OrderSubmitted"` (or later), an incoming submission observation is **observation-only** for Day38 (repeated submission). If no record exists, the first submission observation with matching `order_facts.order_id` mints `OrderSubmitted` AND writes the ownership record.

---

## K. Atomic Task2 Decision Boundary

### K.1 The boundary

Everything that decides mutable state must be inside ONE caller-owned transaction:

```
BEGIN
  ↓
  resolve authoritative application order/execution (order_facts.order_id → PaperOrder → execution_id)
  ↓
  validate broker ordering (canonical_sequence when present; None for Upstox)
  ↓
  idempotency check (durable, canonical_id)
  ↓
  ACQUIRE execution lock (SELECT ... FOR UPDATE)
  ↓
  RE-READ projection + ownership + lifecycle evidence (post-lock)
  ↓
  terminal enforcement
  ↓
  quantity invariants
  ↓
  semantic projection merge → new projection row
  ↓
  allocate Day38 sequence (against actual execution)
  ↓
  SAVEPOINT:
      ensure sequence anchor (first use)
      add projection
      add idempotency
      append Day38 lifecycle event (when legal)
      write/update broker_order_lifecycle_state (AR-5)
      advance broker sequence
  ↓
  COMMIT
```

On ANY failure: ROLLBACK removes every durable effect together (anchor + idempotency + projection + lifecycle + ownership record). No internal `commit()`; no internal `rollback()` destroying caller work.

### K.2 Why the SAVEPOINT is nested inside the transaction

- The SAVEPOINT isolates the durable mutation block so that concurrent unique violations can be reclassified as DUPLICATE_NOOP/CONFLICT without poisoning the caller's transaction.
- The sequence anchor is created and advanced INSIDE the SAVEPOINT (v4/v5 fixes preserved): a failed first-use application rolls back the anchor.
- The ownership record (AR-5) is written inside the SAVEPOINT so it cannot survive an unsuccessful application.

---

## L. Lock / Re-read Ordering

### L.1 Required ordering (AR-2/AR-3)

```
1. idempotency pre-check        (advisory, pre-lock, read-only)
2. sequence position validation (pre-lock, read-only, deprecated for Upstox None)
3. execution identity resolution (read-only)
4. ACQUIRE execution lock       (SELECT ... FOR UPDATE)
5. RE-READ projection            (post-lock, semantic fold)
6. RE-READ ownership record      (post-lock)
7. RE-READ lifecycle evidence    (post-lock)
8. decide, merge, persist, commit
```

### L.2 Explicit rules

1. **No mutable-state decision before the lock.** The projection read for terminal enforcement, quantity validation, and merge MUST happen after the lock. The current code reads `previous` projection before `_allocate_day38_sequence` acquires the lock (B2) — prerequisite AR-2/AR-3.
2. **The lock is the serialization boundary; ownership is order-scoped.** The execution lock serializes all writers to the aggregate; inside it, per-order evidence is read and per-order decisions are made.
3. **Post-lock re-read is mandatory.** Under the lock, re-read the projection fold and ownership record; a pre-lock read may be stale even if it was correct when taken.
4. **SQLite note:** FOR UPDATE is a no-op in SQLite; concurrency guarantees therefore require PostgreSQL verification for the locking claims (§AT), SQLite remains the deterministic unit-test substrate.

---

## M. Concurrency / TOCTOU Model

### M.1 Durable serialization point

- **Sequence allocation / lifecycle append:** the `StrategyExecution` row lock (PostgreSQL FOR UPDATE).
- **Observation dedup:** `broker_sync_idempotency` PK (`canonical_id`) unique constraint inside the SAVEPOINT; losers re-classify through the committed record (DUPLICATE_NOOP identical fingerprint / CONFLICT different fingerprint).
- **Broker sequence advancement:** conditional UPDATE on `broker_sync_sequence_anchor` (CAS on `last_sequence`); loser re-classifies via idempotency.
- **Ownership (AR-5):** PK `(tenant_id, order_id)` upsert inside the SAVEPOINT.

### M.2 What the lock serializes

- Two submissions for the same order.
- Submission + fill racing for the same order.
- Fill + fill for the same order (cumulative monotonicity).
- Terminal + late event for the same order.
- Two events for DIFFERENT orders in the SAME execution (serialized at the execution row, decisions order-scoped).

### M.3 What the lock does NOT do

- Does not decide ownership (decision stays order-scoped).
- Does not dedupe observations (idempotency PK does).
- Does not sequence broker events (anchor CAS does; Upstox `None` exempts this).
- Does not repair quantity contradictions (fail closed instead).

### M.4 TOCTOU closure

Any decision that reads durable state (projection fold, ownership record, lifecycle evidence) and then writes derived state reads + writes inside the same lock + transaction. The window between pre-lock read and post-lock re-read is allowed ONLY for idempotency pre-check and identity resolution (both re-derived under the lock at decision time). The contract therefore has no TOCTOU window for mutable-state decisions.

------

## N. Observation-Only Semantics

### N.1 Definition

**Observation-only** = the canonical event is durably ingested (idempotency, projection, ordering) but produces NO Day38 lifecycle event, because Day38 replay cannot legally accept the transition it would represent (verified against `replay.py` guards, §C.4).

An observation-only event still:
- persists its `BrokerSyncIdempotency` row (dedup);
- appends a `BrokerOrderProjection` row (durable normalized state);
- updates AR-5 ownership/last-observed facts when applicable;
- is replay-stable WHEN replayed through the projection. (The projection is not Day38; see §AI.)

An observation-only event does NOT:
- consume a Day38 sequence;
- append a `TradeLifecycleEvent`;
- mint `OrderSubmitted`/`OrderFilled`/etc.

### N.2 When an event is observation-only (decision table)

| Incoming canonical event | Durable state today | Decision |
|---|---|---|
| ORDER_SUBMITTED | already has OrderSubmitted (AR-5) | observation-only (projection may update submission facts) |
| ORDER_SUBMITTED | order is terminal (FILLED/CANCELLED/REJECTED/EXPIRED) | observation-only or QUARANTINE — see §Q.1 |
| ORDER_ACCEPTED | any | projection-only by construction (`_BROKER_TO_LIFECYCLE` = None) |
| validation/modify/cancel chatter | any non-terminal | observation-only projection update |
| PARTIAL_FILL | order cancelled/rejected | observation-only projection + recovery flag (terminal-first §Q) |
| PARTIAL_FILL | no OrderSubmitted yet (fill-first) | observation-only now; reconciled when submission arrives (§P) |
| FILL_RECORDED | no OrderSubmitted yet | observation-only now; reconciled later (§P) |
| ORDER_CANCELLED | no OrderSubmitted yet (cancelled-first) | observation-only terminal projection (§Q.3) |
| ORDER_REJECTED | no OrderSubmitted yet (rejected-first) | observation-only terminal projection (§Q.2) |

### N.3 What observation-only is NOT

- NOT a drop. The observation is durably recorded in the projection.
- NOT a synthetic lifecycle event. No fabricated `OrderSubmitted` to make a fill replay.
- NOT a business decision that `received_at` resolves (§U.3).
- NOT a recovery shortcut (ORDER_RECOVERED stays rejected at the mapping layer; §R).

### N.4 What Task3 must NOT do

Task3 never classifies observation-only vs lifecycle-producing. It produces the canonical event with all facts; Task2 decides under the lock using durable evidence (§J, §K).

---

## O. Missing-First-Update Rules

### O.1 Definition

"Missing-first-update" = the FIRST observation for an order arrives in a state that is not the canonical first state (e.g. first observation is `open`, or a partial fill, or `rejected`). There is no prior projection row and no Day38 lifecycle.

### O.2 First-observed event analysis (full matrix)

Every first-observation case:

| First-observed provider status | Canonical event | Task2 decision | Projection | Day38 | Replay | Later submission | Later fill | Later terminal | Restart | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| `put order req received` | ORDER_SUBMITTED | APPLIED | SUBMITTED | OrderSubmitted | valid (PENDING→SUBMITTED) | observation-only | fill applies | terminal applies | replay rebuilds same state | no recovery needed |
| `validation pending` / `open pending` / `trigger pending` | ORDER_SUBMITTED (chatter) | APPLIED | SUBMITTED | **none** (no submission evidence yet) | projection-only | first is VIRTUAL, no Day38 | fill without Day38 → fill-first (§P) | terminal without Day38 → terminal-first (§Q) | durable projection, no Day38 | recovery reconciles projection→Day38 |
| `open` | ORDER_ACCEPTED | APPLIED | OPEN | none (projection-only) | projection-only | ORDER_SUBMITTED mints OrderSubmitted (legal from PENDING? NO — PENDING is only via OrderCreated; see §P.5) | fill-first (§P) | terminal-first (§Q) | durable | recovery boundary §R |
| `open` + partial `filled_quantity` | PARTIAL_FILL | APPLIED | PARTIALLY_FILLED | **none** (no OrderSubmitted yet) | observation-only | submission later (§P.5) | another fill later (§P.4) | terminal later | durable projection only | recovery reconciles |
| `complete` | FULL_FILL | APPLIED | FILLED (terminal) | **none** (no OrderSubmitted yet) | observation-only (terminal-first) | submission later (§P.6 — full-fill-first) | trade redelivery dedup | terminal already | durable terminal projection | recovery required to reconcile Day38 |
| `rejected` | ORDER_REJECTED | APPLIED | REJECTED (terminal) | **none** (OrderSubmitted absent) | observation-only | submission later rejected by terminal enforcement | fill later rejected by terminal enforcement | terminal already | durable terminal projection | recovery boundary §R.2 |
| `cancelled` | ORDER_CANCELLED | APPLIED | CANCELLED (terminal) | none | observation-only | same as rejected-first | same | terminal already | durable | recovery boundary |
| unknown/malformed | Failure | REJECTED | none | none | none | n/a | n/a | n/a | n/a | quarantine §AJ |

### O.3 Rule for missing-first-update

1. The projection is ALWAYS updated (durable normalized state) — the provider's observed state is never dropped.
2. Day38 lifecycle events are minted ONLY when the Day38 replay guards accept them (§C.4). Otherwise observation-only.
3. `canonical_sequence=None` for ALL Upstox observations; no fabrication (§U).
4. Terminal-first and fill-first are handled by §P/§Q; the tables above define the durable outcome at each step.
5. Recovery (later task) reconciles projection vs Day38 divergence (§R).

---

## P. Fill-First Convergence

### P.1 Definition

A fill (partial or full), trade, or snapshot observation arrives BEFORE any submission lifecycle evidence (no OrderSubmitted for the order). The economic fill MUST be preserved, never double-counted, and the system must converge to the correct Day38 stream when the submission observation eventually arrives.

### P.2 Concrete example

```
Execution E / Order A (quantity 100)
t0: STREAM partial fill cum=20  (open, filled_quantity=20)
t1: STREAM partial fill cum=50  (open, filled_quantity=50)
t2: STREAM full fill cum=100    (complete)
t3: STREAM put order req received  ← submission arrives AFTER fills
```

### P.3 Step-by-step (durable state at each point)

| Step | Observation | Canonical | Projection (durable) | Day38 stream | Ownership (AR-5) |
|---|---|---|---|---|---|
| t0 | partial cum=20 | PARTIAL_FILL | PARTIALLY_FILLED cum=20 rem=80 | (none — no OrderSubmitted) | last=PARTIAL_FILL, last_cum=20 |
| t1 | partial cum=50 | PARTIAL_FILL | PARTIALLY_FILLED cum=50 rem=50 | (none) | last_cum=50 |
| t2 | full cum=100 | FULL_FILL | FILLED cum=100 rem=0 (terminal) | (none) | is_terminal=true |
| t3 | submission | ORDER_SUBMITTED | FILLED (terminal absorbs; no regression) | OrderSubmitted → OrderFilled(100) | last=OrderSubmitted→OrderFilled |

### P.4 Subsequent fill arrives (after a prior fill-first)

A fill after an observation-only fill with higher cumulative: projection cumulative grows monotonically (§W); Day38 still blocked until submission; when submission arrives, the FIRST OrderFilled carries the full cumulative observed so far (single OrderFilled with cum=N, NOT one per interim fill). **No economic fill is double-counted** — D2 identifies each trade (§Z); the projection keeps the fill ledger via `fill_count`/`last_fill_id`; the Day38 single OrderFilled consumes the projection's current cumulative once.

### P.5 Submission arrives at cum=20 (fill-first → converge)

- Under the lock: ownership record shows ORDER_SUBMITTED absent, projection terminal/or not.
- If projection non-terminal (PARTIALLY_FILLED): mint `OrderSubmitted` (legal: Day38 order exists via OrderCreated from the authoritative execution path), then `OrderFilled(cumulative_filled=20, fill_quantity=20)` — the observed cumulative. Legal: `OrderFilled` requires order SUBMITTED; cumulative 20 > 0 and ≤ quantity.
- If projection terminal FILLED (cum=100): mint `OrderSubmitted` then `OrderFilled(100)`. Losing the interim fills is impossible: the fill facts travel in the fill event's payload, and the projection fold already holds the full cumulative.
- If the order had NO Day38 order at all (no OrderCreated): see §P.6 (submission-later for full-fill-first). Day38 cannot mint OrderFilled without an order; the CONTRACT REQUIRES AR-6 (fill-first reconciliation) to establish the order context from the authoritative execution creation path, NOT synthetic events.

### P.6 Full-fill-first (complete before submission) — the hard case

Day38 replay requires `OrderCreated` (order must exist with quantity) before `OrderSubmitted` and `OrderFilled` (`_get_order` fails with unknown order). The broker observation does NOT carry sufficient information to synthesize OrderCreated (no authoritative order quantity semantics from a fill alone in the general case — quantity could be 100 with cum=100, but a fill cannot prove the ORDER quantity == filled quantity; a complete order's quantity IS its filled quantity by definition, so this specific case is provable: `complete` guarantees filled_quantity == quantity).

- **Decision:** A `complete` observation alone mints NO Day38 event (observation-only terminal projection), UNLESS the owning application order/execution context already exists (PaperOrder row with quantity) — in which case Day38 can legally accept `OrderCreated(order_id, quantity=PaperOrder.quantity)`? **NO** — Day38 OrderCreated must come from the authoritative execution creation path (the PaperOrder's own lifecycle), NOT from Task2/Task3. Task2 never fabricates foundation events. Therefore:
  - If the execution/order was created through the authoritative path BEFORE the fill: the Day38 stream already has TradeIntentCreated/ExecutionActivated/OrderCreated; Task2 mints OrderSubmitted + OrderFilled(100) when the submission observation arrives (P.5). Legal.
  - If no Day38 foundation exists: fill is observation-only; recovery (later task) reconciles projection→Day38 using the authoritative execution creation path. **No synthetic foundation.**
- Trade redelivery of a full fill: same D2 → idempotency dedup (§Z.5).

### P.7 Trade-first, snapshot-first, duplication

- **Trade-first** (STOMP trade feed): carries `trade_id` (D2). Same as partial/full fill-first — observation-only until submission; D2 dedups redelivery.
- **Snapshot-first** (RECOVERY/POLLED_SNAPSHOT): an order-book snapshot with status + filled_quantity. Observation-only until submission; snapshot identity D1 includes `event_timestamp` (§Y.5) so distinct snapshots do not collapse.
- **Duplication:** identical redelivery of the same observation → same D1/D2 → idempotency DUPLICATE_NOOP (§AN).

### P.8 Rule: Do not double-count one economic fill

1. D2 (provider trade id, or deterministic composite) uniquely identifies an economic fill.
2. The projection fold uses D2 to dedup `fill_count`/`last_fill_id` (§W.7).
3. Day38 `OrderFilled` events carry strictly-increasing cumulative; the SAME cumulative never appears twice in the Day38 stream for one order (replay guard).
4. Trade + order-update channels delivering the SAME fill: D2 dedup at the projection; Day38 sees cumulative once (§AG.5).

---

## Q. Terminal-First Behavior

### Q.1 Definition

A terminal provider observation (`rejected`, `cancelled`, `complete`, `cancelled after market order`) arrives BEFORE any submission lifecycle evidence for the order.

### Q.2 Rejected first

- Projection: REJECTED (terminal, durable).
- Day38: NO OrderRejected (Day38 guard: OrderRejected requires order SUBMITTED or PARTIALLY_FILLED — §C.4). The order was never submitted in Day38, so replay cannot accept OrderRejected first. **Observation-only.**
- Future broker event: terminal enforcement rejects any further mutation (§C.3 terminal check).
- Restart: replay rebuilds the exact same terminal projection.
- Recovery: recovery boundary §R — reconcile Day38 to the rejection via authoritative foundation when available; otherwise quarantine.

### Q.3 Cancelled first

Same as rejected-first: projection CANCELLED terminal; NO Day38 OrderCancelled (guard requires SUBMITTED/PARTIALLY_FILLED); observation-only; future events rejected; restart stable.

### Q.4 Expired first

- `expired` is NOT an Upstox status (§G). If a non-Upstox provider delivers it with no submission evidence: projection EXPIRED terminal, NO Day38 event (same guard logic — OrderCancelled requires SUBMITTED). Observation-only.

### Q.5 Complete first

- Projection: FILLED (terminal, cum=quantity).
- Day38: NO OrderFilled without OrderCreated+OrderSubmitted (guards). Observation-only terminal projection.
- If the authoritative execution foundation exists (order was created app-side before): a later `put order req received` mints OrderSubmitted → OrderFilled(100) (P.5). Converges.
- If no foundation: recovery boundary (P.6 hard case).

### Q.6 Rule: Terminal projection is absorbing (preserved)

Terminal projection states (FILLED/CANCELLED/REJECTED/EXPIRED) are absorbing in the projection fold (§V.5). Task2 terminal enforcement (§C.3) rejects post-terminal mutations. ORDER_RECOVERED cannot bypass: it is rejected at the mapping layer (§C.3). Terminal-first Day38 events are NEVER fabricated to make replay pass (§N.3).

---

## R. Recovery Boundary

### R.1 Definition

Recovery = any process that reconciles the durable projection with the Day38 lifecycle stream after divergence (fill-first, terminal-first, missing foundation). Recovery is a LATER TASK (order recovery / reconciliation), explicitly out of scope for Task3 and Task2.

### R.2 Chosen architecture: recovery-required state

- The projection is the **durable normalized broker-state authority** (what the broker says).
- Day38 is the **authoritative execution/order lifecycle** (what StrikeNova legally records).
- Divergence (projection has fill/terminal facts Day38 does not) is a **recovery-required state**, durably observable:
  - `broker_order_projection` rows hold the facts;
  - AR-5 `broker_order_lifecycle_state` marks divergence (`last_event_type` vs projection status);
  - recovery (later task) reconciles via the authoritative execution creation path, never by synthetic Day38 events.

### R.3 What Task3 does

Emits the canonical event with all facts; never classifies recovery need.

### R.4 What Task2 does (current)

Fails closed on unresolved identity; observation-only for Day38-illegal events; never fabricates foundation.

### R.5 Future interface boundary (recovery task)

Recovery will need: the projection fold (semantic), AR-5 ownership record, the Day38 stream, and the authoritative PaperOrder/execution rows. This contract defines the durable inputs so the later task can be built without changing Task3.

### R.6 Explicit statement

> Task2 and Task3 NEVER fabricate TradeIntentCreated / ExecutionActivated / OrderCreated. Fills and terminals observed before a legal lifecycle are durably projected and marked recovery-required; the later recovery task reconciles them through the authoritative execution-creation path or quarantines them.

---

## S. Restart / Reconnect

### S.1 Definition

All continuity must come from durable state. No in-memory continuity, no cache, no local pairing flags.

### S.2 Scenario 1: submission persisted, restart, fill arrives

```
process A: ORDER_SUBMITTED applied → idempotency + projection + OrderSubmitted + AR-5
RESTART
process B: PARTIAL_FILL arrives
  → idempotency (new canonical_id) → projection fold (PARTIALLY_FILLED) → Day38 OrderFilled
  → legal because OrderSubmitted is durable in AR-5 + Day38 stream
```

### S.3 Scenario 2: observation-only fill persisted, restart, submission arrives

```
process A: PARTIAL_FILL cum=20 (no submission yet) → projection PARTIALLY_FILLED, no Day38
RESTART
process B: ORDER_SUBMITTED arrives
  → under lock: ownership absent → mint OrderSubmitted → OrderFilled(20) (P.5)
  → projection fold already PARTIALLY_FILLED (no regression)
```

### S.4 Scenario 3: terminal state persisted, restart, late event arrives

```
process A: ORDER_REJECTED (terminal-first, observation-only for Day38) → projection REJECTED
RESTART
process B: ORDER_SUBMITTED arrives
  → terminal enforcement: projection terminal → REJECTED (no mutation)
  → recovery-required state persists (R.2)
```

### S.5 Rule

> Every decision is re-derivable from durable state after restart. The lock + post-lock re-read (§L) + idempotency + projection fold + AR-5 make in-memory continuity unnecessary.

---

## T. Repeated Submission Semantics

### T.1 Guarantee

One application order receives AT MOST ONE `OrderSubmitted` Day38 event, regardless of how many submission-class observations arrive (STREAM redelivery, reconnect redelivery, separate channels).

### T.2 Exact duplicate

Same canonical_id + same fingerprint → DUPLICATE_NOOP (idempotency). No Day38 event.

### T.3 Different observation content (same canonical_id)

Same canonical_id + different fingerprint → CONFLICT (idempotency). No Day38 event; fail closed.

### T.4 Same order_request_id

Upstox `order_id` is the provider order identity (not an application order identity). Repeated observations for the same `broker_order_id`:
- D1 differs (different observation identity) but canonical_id may coincide via provider_event_id+event_type — dedup/conflict per §AN.
- Ownership record (AR-5) prevents a second OrderSubmitted.

### T.5 New order_request_id (same application order)

A different provider order for the same application order (replacement order): D1 distinct, canonical_id distinct; ownership record still prevents a second OrderSubmitted UNLESS the order was explicitly re-armed (out of scope; recovery task).

### T.6 Concurrent delivery

Two workers delivering the same submission: idempotency PK arbitrates (one APPLIED, one DUPLICATE_NOOP/CONFLICT) (§AT).

### T.7 Reconnect redelivery

Same observation re-sent after reconnect: idempotency dedup (§AN).

### T.8 Restart redelivery

Same durable idempotency → dedup (§S).

### T.9 Multi-order: same execution, different orders

Order A and Order B each get their own OrderSubmitted; no cross-order suppression (§I.3, §AS).

### T.10 Rule

> `OrderSubmitted` ownership is a durable, order-scoped, schema-enforced fact (AR-5). Repeated submission observations update the projection; they never mint a second Day38 submission.

---

## U. `canonical_sequence=None` Semantics

### U.1 Definition

`canonical_sequence` is the Task2 broker-ordering field. Upstox delivers NO provider sequence (§E.1), so Task3 emits `BrokerSyncEvent.canonical_sequence = None` for every Upstox observation.

### U.2 What `canonical_sequence=None` means

- Task2 `_validate_broker_sequence_position` returns None (no sequence validation possible; §C.3).
- Task2 never fabricates a sequence.
- Broker ordering constraints (gap/stale/duplicate-seq) are INOPERATIVE for Upstox; ordering is governed by the semantic merge (§V/§W) and durable idempotency, NOT by arrival.

### U.3 What the projection MUST NOT depend on (Issue 5/6)

The current projection state MUST NOT be defined by:
- `received_at` (operational receipt time);
- database `id` insert order;
- arrival order / thread completion / network timing;
- `canonical_sequence` (None for Upstox);
- anything wall-clock.

**The projection current state is the semantic fold** (§V) over ALL projection rows for (tenant, broker, broker_order_id), using the monotonic merge (§W). When two observations conflict semantically (e.g. quantity 100 vs quantity 60), the merge rules in §AC/§W apply; when ambiguity remains after the merge, the result is deterministic, documented, and never `received_at`-resolved:

| Contradiction | Classification | Result |
|---|---|---|
| quantity 100 → quantity 60 (no modification evidence) | stale/contradictory observation | FAIL CLOSED (REJECTED) — a reduction without modification evidence is a contradiction, not a correction |
| quantity 60 → quantity 100 (modification acknowledged `modified`) | legitimate modification | apply: total_quantity = 100 (§AC.2) |
| cumulative 50 → 30 | regression | REJECTED (quantity invariants §C.3) |
| status OPEN observed after FILLED | stale observation of terminal | terminal absorption → observation-only projection (no status change, no Day38) |

### U.4 Quantity modification semantics (explicit)

- `modified` (upstox status, §G rule R-MODIFIED) carries the authoritative new quantity → projection total_quantity REPLACED with the modified value.
- Pre-modification fills remain: cumulative_filled is monotonic; if the new quantity < current cumulative_filled → REJECTED (overfill would result — cum > total is impossible).
- A quantity REDUCTION without `modified` evidence is a CONTRADICTION → REJECTED (no silent clamping, no max()).
- A quantity INCREASE without `modified` evidence: if current projection has no fill evidence, apply only via ORDER_ACCEPTED with new order_facts.total_quantity when the modification is the acknowledged observation; otherwise REJECTED (no invented modification).
- **`total_quantity = max(previous, incoming)` is REJECTED as a general rule.** It is only legal when the incoming value is a documented modification (R-MODIFIED evidence). This corrects v7's blanket max()(§W.2).

### U.5 Current gap (verified)

`_build_projection` / projection lookup use `canonical_sequence.desc().nullslast(), id.desc()` tiebreaker for None-sequence rows — insert-order dependent (B3). Prerequisite AR-3/AR-4 replaces this with lock + post-lock semantic fold (§AW.3/4).

---

## V. Semantic Projection State

### V.1 States

Projection canonical states: PENDING, SUBMITTED, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED, UNKNOWN (Task1 enum).

### V.2 Legal relationships (partial order)

```
PENDING
  → SUBMITTED          (submission evidence)
  → OPEN               (ORDER_ACCEPTED)
  → PARTIALLY_FILLED   (fill, cumulative > 0, < quantity)
  → FILLED (terminal)
  → CANCELLED / REJECTED / EXPIRED (terminal)
SUBMITTED → PARTIALLY_FILLED → FILLED
SUBMITTED → CANCELLED / REJECTED / EXPIRED
OPEN → PARTIALLY_FILLED → FILLED
OPEN → CANCELLED / REJECTED / EXPIRED
```

### V.3 Non-terminal progression

Merge picks the semantically-higher non-terminal state (SUBMITTED < OPEN < PARTIALLY_FILLED). Equal states merge by field rules (§W).

### V.4 Terminal branches

FILLED / CANCELLED / REJECTED / EXPIRED are mutually exclusive terminals.

### V.5 Terminal absorption

Once terminal, the projection state is absorbing: no later observation changes it (Task2 terminal enforcement §C.3). A conflicting terminal (e.g. REJECTED then CANCELLED) → first terminal wins; second is REJECTED (post-terminal mutation).

### V.6 Observation-only provider chatter

Chatter statuses do not advance the projection state beyond SUBMITTED/OPEN; they update facts (prices, quantities) only.

### V.7 Transition/merge table

| Current | Incoming | Merge result |
|---|---|---|
| SUBMITTED | OPEN | OPEN (higher non-terminal) |
| SUBMITTED | PARTIALLY_FILLED | PARTIALLY_FILLED |
| OPEN | PARTIALLY_FILLED | PARTIALLY_FILLED |
| PARTIALLY_FILLED | FILLED | FILLED (terminal) |
| PARTIALLY_FILLED | CANCELLED/REJECTED/EXPIRED | terminal wins |
| FILLED | anything | FILLED (absorbing; rejection) |
| CANCELLED | anything | CANCELLED (absorbing) |
| REJECTED | anything | REJECTED (absorbing) |
| EXPIRED | anything | EXPIRED (absorbing) |
| any | UNKNOWN-derived | no state change (unknown never wins) |

### V.8 Multiple terminal states rule

First terminal wins; conflicting later terminal → REJECTED (post-terminal). No "which terminal is better" resolution.

---

## W. Projection Merge Algorithm

### W.1 Definition

The fold: given the ordered-by-semantics set of ALL projection rows for (tenant, broker, broker_order_id), produce the current state. The fold is deterministic, monotonic where claimed, and NEVER uses `received_at`/`id` as a business tiebreak.

### W.2 Fields and their merge behavior

| Field | Source | Merge rule | Precedence | Replacement | Monotonic | Concurrency |
|---|---|---|---|---|---|---|
| `status` | fold | semantic partial order (§V.3/§V.7) | terminal > higher non-terminal | absorbing | yes (within partial order) | under lock |
| `total_quantity` | modified evidence | REPLACE on `modified` (R-MODIFIED); else monotonic if equal/consistent; else REJECT contradiction (§U.4) | modification evidence wins | explicit modification only | conditional | under lock |
| `cumulative_filled` | fills | monotonic max with strict-increase validation | higher cumulative, but any regression REJECTED | never | yes | under lock |
| `remaining_quantity` | derived | `total - cumulative` | derived | derived | derived | under lock |
| `average_price` | weighted | weighted average across fills (order-dependent) | NOT commutative | recompute | no (order-dependent) | under lock |
| `last_fill_price` | most recent fill | replace with most recent fill's price | most recent D2 | replaceable | no (most-recent) | under lock |
| `last_fill_quantity` | most recent fill | replace | most recent D2 | replaceable | no | under lock |
| `fill identity` (D2) | fills | set of applied D2; dedup duplicates | per-D2 once | additive | yes (set-growth) | under lock |
| `rejection_reason` | ORDER_REJECTED | set once; sticky | first terminal reason | sticky | yes | under lock |
| `is_terminal` | fold | OR of terminal | any terminal | absorbing | yes | under lock |
| `fill_count` | D2 set size | count of distinct D2 | per-D2 once | additive | yes | under lock |

### W.3 Examples

```
OPEN(cum=0) + PARTIAL(cum=50) → PARTIALLY_FILLED cum=50
PARTIAL(cum=20) + PARTIAL(cum=50) → PARTIALLY_FILLED cum=50
FILLED(cum=100) + OPEN(cum=0) → FILLED cum=100 (terminal + stale observation absorbed)
REJECTED + PARTIAL(cum=50) → REJECTED (terminal absorbing; cumulative preserved in rows but state terminal)
CANCELLED + OPEN → CANCELLED
```

### W.4 What is monotonic

`status` (within partial order), `cumulative_filled` (with strict-increase validation), `is_terminal`, `fill_count` (distinct D2), `total_quantity` (only under modification evidence).

### W.5 What is sticky

`rejection_reason`, `is_terminal`, first terminal status.

### W.6 What is replaceable

`last_fill_price`, `last_fill_quantity`, `last_fill_id` (most recent D2), `average_price` (recomputed).

### W.7 What is conditional

- `fill_count`: dedup by D2.
- `total_quantity`: modification-evidence-conditional (§U.4).
- `rejection_reason`: terminal-conditional.

### W.8 What is NOT claimed to be commutative

`average_price` (fill-order dependent), `last_fill_*` (most-recent dependent). These are deterministic under the lock because the fold has a defined order (by D2/semantic sequence, never `received_at`).

### W.9 Required: Do not silently erase better durable facts

- The fold NEVER deletes rows. Every observation stays in `broker_order_projection`.
- A contradiction (quantity 100↔60 without modification) is REJECTED, not silently merged.
- The current-state representation (AR-8) is a MATERIALIZED fold row, updated under the lock inside the same SAVEPOINT as the event row, so "current state" is an explicit table, not "the latest row by id" (§AW.8).

------

## X. Provider Identity Layers

### X.1 Distinction (Issue 2 correction)

Five distinct identity layers, NEVER conflated:

| Layer | Name | Nature | Produced by |
|---|---|---|---|
| 1 | Provider-native identity | Upstox `order_id`, `trade_id`/transaction id, webhook event id | Upstox |
| 2 | D1 | deterministic provider-observation identity (our hash) | Task3 |
| 3 | D2 | deterministic provider-trade identity (our hash or provider trade_id) | Task3 |
| 4 | `canonical_id` | canonical event identity (our hash) | Task1 |
| 5 | content fingerprint | canonical content hash | Task2 |

### X.2 Provider-native IDs

- `order_id` → `BrokerSyncEvent.broker_order_id`. NOT an application order identity (§D.2).
- `trade_id`/transaction id → `FillFacts.fill_id` (D2 preferred source) and `FillFacts` fingerprint participation (§Z).
- Webhook event id → `BrokerSyncEvent.provider_event_id` when present; STOMP STREAM has none (§E.1).

### X.3 D1 vs provider-native ID

D1 is NEVER the provider event id; it is the StrikeNova-derived observation identity. `provider_event_id` (when present) is ONE input to D1 and to `canonical_id`.

### X.4 D1 vs canonical_id

D1 is the observation identity (per provider observation). `canonical_id` is the canonical event identity (per Task1 event, idempotency PK). Different purposes, both deterministic; D1 is NOT persisted as an event identity (it may appear in `metadata` as an audit aid).

### X.5 D1 must NEVER decide lifecycle ownership

Observation identity never grants lifecycle ownership; ownership comes from tenant + execution + order + durable lifecycle evidence (§J).

---

## Y. D1 Observation Identity

The complete D1 specification (all v7 gaps closed).

### Y.1 Definition

D1 = deterministic provider-observation identity: ONE hash identifying ONE provider observation, computed by Task3 from the raw observation fields.

### Y.2 Exact fields used (canonical serialization order)

```
D1 = SHA256( D1_PREFIX
  \x1f tenant_id
  \x1f broker
  \x1f order_id          (provider order id; absent → empty string)
  \x1f event_type        (canonical BrokerEventType)
  \x1f source_mode       (STREAM | RECOVERY | POLLED_SNAPSHOT)
  \x1f provider_trade_id (fill events only; absent → empty string)
  \x1f event_timestamp   (epoch millis UTC, if present; absent → empty string)
  \x1f order_status      (provider status verbatim, if present; absent → empty string)
  \x1f filled_quantity   (provider value, if present; absent → empty string)
  \x1f cancel_quantity   (provider value, if present; absent → empty string)
  \x1f reject_reason     (provider value, if present; absent → empty string)
)
```
D1_PREFIX = `"D1v1:"`.

### Y.3 Fields NOT used

- `received_at` — operational receipt time, NEVER in D1.
- `canonical_sequence` — Task2 field, not provider observation.
- `order_facts`/`fill_facts` derived values EXCEPT the explicit raw fields above.
- Wall-clock, randomness, `hash()`, `id()`, arrival order, memory identity.
- `metadata` — never in D1.

### Y.4 Canonical serialization

- Fields joined with `\x1f` (ASCII 0x1F), in the EXACT order above.
- Each field is its EXACT provider string/epoch value; numbers serialized as zero-padded-free decimal strings (e.g. `filled_quantity=20` → `"20"`; NO floats with locale/scientific notation).
- `event_timestamp`: provider epoch millis (int) stringified; absent → empty string field.
- Absent fields are ALWAYS the literal empty string (never omitted) — this keeps the field count and positions fixed, so two observations differing only in one absent/present pair cannot collide by shifting.
- Null vs absent: Upstox omits absent fields; Task3 treats `None` and missing identically → empty string.

### Y.5 Collision resistance (Issue 3)

Two legitimate sequence-less observations MUST be distinguishable. Sources of distinction, in priority:

1. **Provider-native event id** (webhook) — when present, D1 = `SHA256(D1v1 \x1f tenant \x1f broker \x1f order_id \x1f event_type \x1f source_mode \x1f provider_event_id ...)` and the event id dominates.
2. **`event_timestamp`** — distinct eron/participating observations carry distinct exchange timestamps (STREAM messages include exchange_timestamp). Two fills at DIFFERENT times → different D1.
3. **`provider_trade_id`** — the trade feed's per-trade id dominates for STREAM trade observations.
4. **`filled_quantity`/`cancel_quantity`/`reject_reason`/`order_status`** — same order, same timestamp, different quantities → different D1.
5. Only when EVERY field above is identical, D1 is identical — this is exactly the "identical redelivery" case (same observation redelivered), which MUST dedup.

**Analysis of the example:**
- `partial fill cumulative=20` vs `partial fill cumulative=50`:
  - Different `filled_quantity` (20 vs 50) → different D1 (rule 4). ✓ distinguishable.
  - Even if filled_quantity were absent, different event_timestamp (rule 2) distinguishes.
  - Therefore two legitimate partial fills never collide.
- Identical redelivery: every participating field identical → same D1 → idempotency dedup. ✓

**Residual risk:** two observations with identical order_id+event_type+source_mode+timestamp+quantities are treated as one observation. This is safe: identical provider facts at the same instant cannot represent two DIFFERENT economic facts (they would carry different trade ids or quantities); if the provider later supplies more detail (trade id), the observation is a distinct D1 (rule 3) — the projection dedups by D2 anyway (§W.7).

**No HMAC, no key:** D1 is a plain SHA-256 (v7 §Y.6 preserved). A keyed variant is a future change.

**Versioning:** prefix `D1v1:` (v7 §Y.8 preserved). Future algorithm changes → `D1v2:`.

**Length:** `D1v1:` + 64 hex chars = 69 chars (v7 §Y.9 corrected: 64 hex chars, plus the version prefix).

### Y.6 Example

```
tenant=tenant-1, broker=UPSTOX, order_id=240108010918222,
event_type=PARTIAL_FILL, source_mode=STREAM, provider_event_id=(absent),
event_timestamp=1736280000123, provider_trade_id=(absent),
order_status=open, filled_quantity=20, cancel_quantity=, reject_reason=

D1 = SHA256("D1v1:\x1ftenant-1\x1fUPSTOX\x1f240108010918222\x1fPARTIAL_FILL\x1fSTREAM\x1f\x1f1736280000123\x1fopen\x1f20\x1f\x1f\x1f")
   = "d1v1:<64 hex>"
```

### Y.7 Null semantics (exact)

- `order_id` absent → D1 cannot be computed → Task3 FAILS CLOSED (no observation identity). (Matches Task1 fail-closed identity, §C.2.)
- All other fields may be absent (empty string).
- `provider_event_id` absence NEVER blocks D1 (STREAM has none).

### Y.8 When D1 is computed

D1 is computed at Task3 normalization time (pure function of the raw observation), stored in `metadata["d1"]` (audit aid) and used by Task2 for cross-channel dedup (§AA). D1 is NOT an event identity in the persisted schema (no column; §X.4).

---

## Z. D2 Trade Identity

### Z.1 Definition

D2 = deterministic provider-trade identity: identifies ONE economic fill/trade.

### Z.2 Preferred source

```
D2 = provider trade_id  (transaction id from the trade feed / webhook trade object)
```
Prefixed `D2v1:<provider trade_id>` when the provider supplies one. `FillFacts.fill_id = provider trade_id`.

### Z.3 Fallback (no trade id)

For an order-update observation carrying fill evidence (`filled_quantity` strictly greater than prior, or a fill object without trade id):
```
D2 = SHA256("D2v1:" \x1f tenant \x1f broker \x1f order_id \x1f event_timestamp \x1f filled_quantity \x1f fill_price)
```
All fields in canonical serialization (§Y.4). A fill without trade id AND without timestamp → D2 cannot be computed → FAIL CLOSED (no economic fill identity; the fill cannot be safely deduped). The observation is still projected (observation-only) with a recovery flag; it is never counted as a distinct economic fill without D2.

### Z.4 Missing trade_id behavior

- Prefer trade id; fallback D2 composite only when timestamp present.
- A missing D2 → fill cannot be deduped → FAIL CLOSED for fill-counting; projection records the observation; recovery task reconciles (§R).

### Z.5 Same trade redelivery

Same D2 → idempotency/dedup at projection (fill_count/last_fill_id unchanged; Day38 cumulative unchanged — no double count, §P.8).

### Z.6 Different trade_id (same order)

Different D2 → distinct fills; each applies under monotonic cumulative validation (§W.2).

### Z.7 Same order + different trade_id

Both fills apply (cumulative strictly increases each time; regression rejected).

---

## AA. Cross-Channel Identity

### AA.1 Definition

The same provider fact may arrive through multiple channels: STREAM (websocket order-update + trade feed), TRADE (websocket trade feed), RECOVERY (order-history pull), POLLED_SNAPSHOT (order-book snapshot pull). Channel is recorded in `BrokerSyncEvent.source_mode` (§E.1).

### AA.2 Distinction: observation identity vs delivery provenance

- **Observation identity (D1/D2)** — what the fact IS.
- **Delivery provenance (source_mode)** — WHICH channel delivered it.

They are independent: the same fact via two channels has the same D1/D2 core (if the fact is truly the same) but different provenance.

### AA.3 Per-channel-pair rule (Issue 4)

| Channel pair | Same provider fact? | Rule | Why |
|---|---|---|---|
| STREAM(order-update) + STREAM(trade) | Same fill | **MERGE** (dedup via D2; projection cumulative once; Day38 cumulative once) | Both channels observe the same economic fill; trade feed carries trade id (D2), order-update carries cumulative. |
| STREAM + TRADE | Same fill | **MERGE** (D2 dedup) | TRADE and STREAM are both live channels; same trade id. |
| STREAM + RECOVERY | Same state snapshot | **MERGE** (projection fold is idempotent w.r.t. state; recovery snapshot updates facts without double-counting fills — D2 set) | RECOVERY is a point-in-time pull; it never adds an economic fill that STREAM already counted. |
| STREAM + POLLED_SNAPSHOT | Same state snapshot | **MERGE** (same as RECOVERY) | Same reasoning. |
| RECOVERY + RECOVERY | Different pull times | **RETAIN as separate observations** (distinct D1 via event_timestamp); projection folds latest state; fills deduped by D2 | Two pulls are two observations; the fold keeps the later state. |
| POLLED_SNAPSHOT + POLLED_SNAPSHOT | Different pull times | **RETAIN** (same as above) | Same. |
| TRADE + TRADE | Same trade id | **DEDUP** (D2) | Same economic fill. |
| STREAM + STREAM | Same observation | **DEDUP** (D1) | Redelivery. |

**No contradictory rules:** the rule is stated per (fact-identity, channel) pair; MERGE means the projection/D2 set dedups the economic effect (fill counted once), RETAIN means both observations are durable rows and the fold reconciles state, DEDUP means the identical observation applies once.

### AA.4 Cross-channel fill double-count prevention

- D2 is the shared dedup key across ALL channels.
- The projection `fill_count` counts distinct D2 (§W.7).
- Day38 `OrderFilled.cumulative_filled` is monotonic across channels; the SAME cumulative is never applied twice (replay guard, §C.4).

### AA.5 Cross-channel identity and canonical_id

`canonical_id` differences across channels for the same fact are EXPECTED (different provider_event_id/timestamp content). Idempotency dedups identical canonical events, NOT cross-channel equivalents; cross-channel equivalence is resolved by D1/D2 at the projection layer (§AN).

---

## AB. Timestamp Semantics

### AB.1 Timestamps defined

| Timestamp | Provider source | Canonical field | Role |
|---|---|---|---|
| `exchange_timestamp` | Upstox epoch ms UTC | `event_timestamp` | Provider event time. D1 participating (§Y.2). Ordering-aid for fallback D2 (§Z.3). |
| `order_timestamp` | Upstox epoch ms UTC | (not used directly) | Order placement time; carried in `metadata` only. |
| `received_at` | StrikeNova receipt | Task1 `received_at` | Operational metadata ONLY. NEVER business ordering (§U.3). |
| `fill_timestamp` | trade message timestamp | `FillFacts.fill_timestamp` | D2 participating when no trade id (§Z.3); must be timezone-aware (Task1 validation §C.2). |

### AB.2 Timezone behavior

- Upstox timestamps are UNIX epoch milliseconds UTC — ALREADY UTC. Task3 converts to aware `datetime(timezone.utc)` verbatim.
- ALL stored/canonical timestamps are UTC-aware.
- `FillFacts.fill_timestamp` must be timezone-aware (Task1 `__post_init__` raises on naive).

### AB.3 Null behavior

- `exchange_timestamp` null → `event_timestamp = None`; D1 includes empty string (§Y.2); fallback D2 UNAVAILABLE (fail closed for fill counting, §Z.3); the observation is projected with the missing-timestamp flag; ordering via `received_at` is FORBIDDEN (§U.3).
- `order_timestamp` null → metadata omission; no business impact.
- `fill_timestamp` null → D2 fallback unavailable (fail closed for counting).

### AB.4 Invalid timestamp behavior

- Non-numeric `exchange_timestamp` → Task3 FAILURE (fail closed, §AJ).
- Numeric but out-of-range → FAILURE.
- Timezone-ambiguous strings (no offset) → FAILURE (never assume "UTC if known"; never guess zone).

### AB.5 Timestamp participation

| Timestamp | D1 (Y) | D2 (Z) | Fingerprint | Projection | Day38 |
|---|---|---|---|---|---|
| `exchange_timestamp` | YES | YES (fallback) | YES | YES (occurred_at) | YES (occurred_at) |
| `order_timestamp` | NO | NO | NO | metadata | metadata |
| `received_at` | NO | NO | NO | YES (received_at col) | NO |
| `fill_timestamp` | NO | YES (fallback) | YES | YES (last_fill) | YES (payload) |

---

## AC. Quantity Semantics

### AC.1 Provider quantity → canonical quantity

- Upstox order quantity is in LOTS for F&O instruments (contract multiplier).
- Task3 converts provider quantity (lots) → canonical `OrderFacts.total_quantity` (INT LOTS) unchanged. No contract conversion happens in Task3; `total_quantity` is expressed in the same unit as `PaperOrder.quantity` (lots).
- `FillFacts.fill_quantity`/`cumulative_filled_after`/`remaining_after` are in LOTS (same unit).

### AC.2 Lot-Size authority

- `PaperOrder.lot_size` (contracts per lot) is the AUTHORITATIVE lot size (§AD).
- Fills and quantities are canonicalized in LOTS; contract-level math (notional, P&L) is OUTSIDE Task3 (later layers).
- If authoritative lot size is unavailable for an instrument, Task3 FAILS CLOSED (delivers a Failure; never assumes 1, never derives from quantity).

### AC.3 Exact divisibility

- No rounding, no floor, no ceil: quantities are integers in lots already.
- Any provider value that is not an exact integer lot count → FAILURE (fail closed; §AJ).

### AC.4 No silent conversion

- No multiplying/dividing by assumed lot size.
- No coercion of strings→int except exact parse; failure on non-integer.
- `quantity` vs `filled_quantity` vs `cancel_quantity` are all integers; total = filled + remaining + cancelled when all present — verified; mismatch → FAILURE.

### AC.5 Provider raw quantity retained

- Raw provider quantity strings are retained in `metadata` (`metadata["upstox"]["quantity_raw"]`, etc.) for audit, in addition to canonicalized int fields in `OrderFacts`/`FillFacts`.

### AC.6 Modification semantics (Issue 5; exact)

Provider `modified` re-arm carries an authoritative new quantity (§G R-MODIFIED):
- New quantity REPLACES projection `total_quantity` (§U.4).
- If `new_quantity < cumulative_filled` → REJECTED (would violate fill ≤ total).
- No `max()` blanket merge (§U.4) — only modification evidence changes total_quantity.

---

## AD. Lot-Size Authority

### AD.1 Authoritative source

- `PaperOrder.lot_size` (per order row) is the single authoritative lot-size source for that order.
- There is no separate instruments-table authority in the current repo for lot size; the per-order column is authoritative.

### AD.2 Not hardcoded

- Task3 never hardcodes a lot size.
- The normalizer receives `NormalizationContext.lot_size` from the caller (which reads `PaperOrder.lot_size`).

### AD.3 Not inferred from quantity

- Lot size is NEVER derived from quantity, price, or symbol.

### AD.4 Not in tag correlation

- The tag correlation map (Upstox `tag` → application order) is NOT a lot-size source.

### AD.5 Unavailable lot size

- If the caller cannot provide `PaperOrder.lot_size` (order not found / no row), Task3 emits FAILURE (fail closed). Quantity conversion cannot be verified otherwise.

---

## AE. OrderFacts

### AE.1 Definition

`OrderFacts` = normalized order-level state carried by `BrokerSyncEvent.order_facts` (Task1 frozen value object, §C.2).

### AE.2 Fields

| Field | Type | Source (Upstox) | None allowed |
|---|---|---|---|
| `order_id` | str | canonical application order reference — REQUIRED for Task2 identity resolution (§J.2); NEVER the provider order id | NO on lifecycle-producing events; YES on observation-only chatter |
| `broker_order_id` | str | Upstox `order_id` | NO (Task1 fail-closed identity needs it when provider_event_id absent) |
| `status` | CanonicalOrderState | derived from provider status (§G) | NO |
| `total_quantity` | int | Upstox `quantity` (modified re-arm replaces) | YES (unknown) |
| `cumulative_filled` | int | Upstox `filled_quantity` | YES |
| `average_price` | float | computed from fill prices (fill-feed) | YES |
| `last_fill_price` | float | last fill price | YES |
| `last_fill_quantity` | int | last fill quantity | YES |
| `rejection_reason` | str | Upstox rejection message | YES |
| `is_terminal` | bool | derived from provider terminal status (§G) | NO (default False) |

### AE.3 None semantics

- `order_id=None` → Task2 `_resolve_execution_identity` returns None → REJECTED (fail closed; §C.3). Task3 NEVER emits a lifecycle-producing event without `order_id`.
- `total_quantity=None` → quantity invariants partially inapplicable (overfill check skipped); projection keeps previous total.
- `cumulative_filled=None` → projection keeps previous cumulative.
- `status=UNKNOWN` → Task3 FAILURE (never emits UNKNOWN as a resolved status; §AJ).

### AE.4 Validation owner

Task3 validates presence/type/range of provider-derived fields; Task2 validates quantity invariants (§C.3) and owns projection/ownership decisions.

### AE.5 Identity relevance

`order_id` is THE lifecycle-ownership input (§J.2). Other OrderFacts fields do NOT participate in ownership identity; they participate in fingerprint (§C.2).

### AE.6 Fingerprint relevance

ALL OrderFacts fields participate in `_content_fingerprint` (Task2, §C.3) — same canonical_id with different OrderFacts → CONFLICT.

---

## AF. FillFacts

### AF.1 Definition

`FillFacts` = normalized fill-level state carried by `BrokerSyncEvent.fill_facts` (Task1 frozen value object, §C.2). `fill_timestamp` must be tz-aware.

### AF.2 Fields

| Field | Type | Source | None allowed |
|---|---|---|---|
| `fill_id` | str | Upstox `trade_id` (D2 preferred source) | YES (fallback D2 needed) |
| `fill_quantity` | int | fill quantity (lots) | YES (unknown) |
| `fill_price` | float | fill price | YES |
| `fill_timestamp` | datetime | trade timestamp (tz-aware) | YES (D2 fallback unavailable) |
| `cumulative_filled_after` | int | derived: prior cumulative + fill_quantity; or provider filled_quantity | YES |
| `remaining_after` | int | derived: total − cumulative_after | YES |

### AF.3 Cumulative/remaining derivation ownership

- `cumulative_filled_after` and `remaining_after` are DERIVED by Task3 from provider facts (filled_quantity / quantity) using §AC.
- Task2 validates arithmetic (§C.3 `_validate_quantity_invariants`): cumulative ≥ previous + fill; ≤ total; remaining = total − cumulative. FAIL CLOSED on mismatch.

### AF.4 None semantics

- `fill_id=None` + `fill_timestamp=None` → D2 unavailable → fill cannot be safely counted → Task3 marks observation-only (fill facts present but D2-less): projection records facts, Day38 fill NOT minted from it alone; recovery-reconcile (§R, §Z.4).
- `cumulative_filled_after=None` on a fill → Task2 quantity validation skipped for cumulative; projection may still apply last_fill fields.

### AF.5 Validation owner

- Task3: presence/type/range/derivation.
- Task2: monotonic cumulative, overfill, remaining, fill ≤ total (§C.3).

------

## AG. Order-Update / Trade / Snapshot Channels

### AG.1 Channels defined

| Channel | Provider source | source_mode | Economic fills? | Cumulative observations? |
|---|---|---|---|---|
| Order-update websocket | STOMP order-update feed | STREAM | no (has filled_quantity, no trade ids) | yes |
| Trade websocket | STOMP trade feed | STREAM | yes (trade_id, fill price/qty) | no |
| Order webhook | V3 webhook push | STREAM | sometimes (trade objects) | yes |
| Order history pull | Get Order History API | RECOVERY | no (order states only) | yes |
| Trade history pull | Get Trades API | RECOVERY | yes (trade ids, prices, qty) | no |
| Order-book snapshot | position/order snapshot | POLLED_SNAPSHOT | no | yes |

### AG.2 Which channel emits economic fills

TRADE (websocket trade feed), webhook trade objects, trade-history pull. Economic fill identity = D2 (§Z).

### AG.3 Which channel emits cumulative observations

ORDER-UPDATE (websocket order-update), ORDER-HISTORY, ORDER-BOOK SNAPSHOT — via `filled_quantity` with provider status (open/complete).

### AG.4 Correlation

- Order-update observation: `order_id` + `status` + `filled_quantity`.
- Trade observation: `order_id` + `trade_id` + fill qty/price.
- Correlation: same `order_id` (provider) → same application order via `order_facts.order_id` resolution (§J.2).
- A trade's effect on cumulative is reconciled through the projection fold; the ORDER-UPDATE cumulative is the authority for cumulative, the TRADE feed supplies D2 + fill granularity.

### AG.5 Duplicate avoidance (per fill)

One economic fill may appear as: TRADE message (trade_id=T1, qty=5) AND ORDER-UPDATE cumulative jump (20→25). The projection dedups by D2 (T1) so the fill count is 1 (§W.7). Day38 OrderFilled uses the ORDER-UPDATE cumulative (25) with fill facts from the TRADE message.

### AG.6 Precedence

- Order status → ORDER-UPDATE/ORDER-HISTORY/SNAPSHOT.
- Fill granularity (price/qty) → TRADE/WEBHOOK-trade.
- No channel has precedence over another for the SAME fact; D2 dedup reconciles. Order-update is authoritative for cumulative/status; trade channel authoritative for fill identity/price.

### AG.7 Do not create two economic fills for one trade

The same trade_id must never produce two `fill_count` increments or two Day38 cumulative jumps. D2 set (§W.7) + monotonic cumulative guard (§C.4) enforce this.

---

## AH. Terminal Semantics

### AH.1 Terminal canonical events

Terminal canonical broker events: ORDER_REJECTED (terminal), ORDER_CANCELLED (terminal), ORDER_EXPIRED (terminal), FULL_FILL (terminal FILLED), and ORDER_CANCELLED for `cancelled after market order`.

### AH.2 Terminal flag behavior

- `OrderFacts.is_terminal` = true for terminal events (Task1 field).
- Task2 `_event_canonical_state` marks the projection terminal.
- Terminal enforcement (§C.3) rejects post-terminal events.

### AH.3 Fill behavior for terminal states

- `complete` (FULL_FILL): terminal FILLED with the full cumulative — fill-bearing terminal (its fill is real; D2-counted once).
- `cancelled`/`rejected` with `filled_quantity > 0`: terminal event carries the observed fill facts (projection records them); Day38 OrderCancelled/OrderRejected does NOT carry the fill (Day38 terminal events only transition status; fills are recorded by OrderFilled/FillRecorded which require pre-terminal states).

### AH.4 Projection behavior for terminal states

Terminal absorbing (§V.5); conflicting terminals → first wins, later rejected.

### AH.5 Preserve Task2's terminal enforcement as the durable authority

Task2's terminal enforcement (§C.3) is authoritative. Task3 merely reflects provider terminal status into canonical events; it never decides terminal precedence.

---

## AI. Projection vs Day38 State

### AI.1 Formal distinction

- **Projection** (`broker_order_projection` + fold): the broker's durable normalized view — what the PROVIDER says.
- **Day38** (`trade_lifecycle_events` + replay): the authoritative execution/order lifecycle — what STRIKENOVA legally records.

### AI.2 Divergence types

| Type | Projection | Day38 | Legal? |
|---|---|---|---|
| Normal convergence | PARTIALLY_FILLED cum=50 | OrderFilled cum=50 | yes |
| Fill-first pending | PARTIALLY_FILLED cum=50 | (no OrderFilled yet) | yes (recovery-required; §P) |
| Terminal-first pending | REJECTED | (no OrderRejected) | yes (recovery-required; §Q) |
| Modification diff | total=100 | order quantity=100 updated via modified evidence | yes (with modification record) |
| Unexplained divergence | projection says X, Day38 says Y, no recovery-required flag | diverged without evidence | INVALID — must be quarantined |

### AI.3 Expected divergences

Only fill-first/terminal-first/modification (all recovery-required, durably flagged in AR-5/§R).

### AI.4 Invalid divergences

Unexplained divergence → QUARANTINE (recovery task reconciles; §R).

### AI.5 Terminal projection is absorbing

Projection terminal ≠ Day38 terminal automatically. Day38 terminal requires legal transitions (§Q). The projection is the broker-truth authority; Day38 is the legal-lifecycle authority. They converge only through legal events or recovery.

---

## AJ. Unknown / Malformed Events

### AJ.1 Fail-closed semantics

Task3 returns a typed FAILURE for any unknown/malformed observation. Task2 never sees an event it cannot safely normalize.

### AJ.2 Malformed cases (Task3 FAILURE)

- Unknown provider status (not in §G) → FAILURE (never guessed; never coerced to UNKNOWN; never mapped to REJECTED — "unknown status" ≠ "order rejected").
- Missing `order_id` on a lifecycle-relevant observation → FAILURE.
- Non-integer quantity/filled_quantity → FAILURE.
- Invalid timestamp → FAILURE (§AB.4).
- Missing authoritative lot size → FAILURE (§AD.5).
- Unresolvable application-order reference on lifecycle-producing event → the event is REJECTED by Task2 (fail-closed identity §C.3) — Task3 still emits it (with order_facts.order_id) because resolution is Task2's boundary; both layers fail closed.

### AJ.3 Do not convert unknown provider status into order rejected

Explicitly forbidden. Only provider `rejected` maps to ORDER_REJECTED (§G R-REJECTED).

### AJ.4 No silent zero coercion

Missing quantity ≠ 0. Missing filled_quantity ≠ 0. Missing values stay None; failure on required.

### AJ.5 No guessed status

Never synthesize a status from partial evidence. Unexplained provider fields (e.g. a status string with trailing whitespace) → FAILURE (strict match, §G verbatim values).

---

## AK. Tenant Isolation

### AK.1 Tenant source

Tenant = StrikeNova user scope. Task3 receives `NormalizationContext.tenant_id` from the caller (authenticated broker-sync context); it never infers tenant from provider payload.

### AK.2 Validation

- `BrokerSyncEvent.tenant_id` set from context.
- Task2 `ingest_canonical_event(event, db, tenant_id)` validates `belongs_to_tenant` (mismatch → REJECTED; §C.3).
- Day38 replay validates tenant consistency across the stream (`ReplaySecurityError.TENANT_MISMATCH`, §C.4).

### AK.3 Cross-tenant behavior

- A provider observation whose resolved application order belongs to a DIFFERENT tenant → REJECTED (fail closed). Resolution is tenant-scoped (`PaperOrder.user_id == tenant` in `_resolve_execution_identity`, §C.3).

### AK.4 Tenant in canonical event

`tenant_id` participates in `canonical_id` AND in lifecycle `event_id` (tenant-scoped, §C.4). Cross-tenant replay is structurally impossible.

---

## AL. Metadata

### AL.1 What is retained

Provider raw fields for audit: `metadata["upstox"] = {order_id, status, quantity, filled_quantity, cancel_quantity, reject_reason, exchange_timestamp, order_timestamp, tag, source}`.

### AL.2 What is excluded

- Never duplicates canonical fields (no `metadata["broker_order_id"]` if already in `broker_order_id`, etc.) — §AL.4.
- Never holds identity secrets (api keys, tokens).

### AL.3 What is included

- `metadata["d1"]` (audit aid, §Y.8).
- `metadata["channel"]` (provenance).
- `metadata["upstox"]` raw fields (audit).
- `metadata["normalizer_version"]` = "1.0".

### AL.4 No duplication of canonical fields into metadata

Forbidden except where the canonical field is DERIVED and the raw value differs (e.g. `metadata["upstox"]["status"]` raw string + `order_facts.status` canonical enum — different layers, allowed).

### AL.5 Metadata is not authoritative

Metadata never participates in identity, fingerprint, or decisions. Canonical fields are authoritative.

---

## AM. Source Modes

### AM.1 Defined

STREAM (live websocket/webhook), RECOVERY (pull-based history), POLLED_SNAPSHOT (periodic snapshot).

### AM.2 Source-mode rules

- STREAM: real-time observations; no provider sequence; D1 via §Y.
- RECOVERY: initial/backfill pull; observations may be ordered by `event_timestamp` (snapshot identity, §Y.5); D1 includes timestamp; economic fills identified by D2.
- POLLED_SNAPSHOT: periodic full-state pull; each snapshot is a D1 (timestamp-differentiated); dedups against STREAM by D2.

### AM.3 Source-mode and canonical_id

- `source_mode` participates in canonical_id? NO — `canonical_id` includes `provider_event_id` (when present) or broker_order+discriminator; `source_mode` participates in D1 and fingerprint but NOT canonical_id (a fact seen via STREAM and via RECOVERY must dedup via D2, not collide via different canonical_id — no wait: D1 differs by source_mode, canonical_id likely differs by content; idempotency dedups identical canonical events; D2 dedups cross-channel equivalents at the projection — §AA.5).

### AM.4 Ordering boundary

- STREAM: no ordering guarantee from provider; semantic merge (§W) resolves.
- RECOVERY/SNAPSHOT: timestamp-ordered observations; still semantic-folded; never `received_at`-ordered.

---

## AN. Idempotency Boundary

### AN.1 What is idempotent

- `canonical_id` (Task1) — event identity. Duplicate canonical_id + same fingerprint → DUPLICATE_NOOP.
- Same canonical_id + different fingerprint → CONFLICT.
- D2 (Task3) — economic fill identity. Same D2 never double-counts fills at the projection.
- D1 — observation identity (metadata/audit; cross-channel dedup aid).

### AN.2 What is NOT idempotent

- Provider channels (a fact may legitimately arrive twice via different channels).
- `received_at` (operational).
- `canonical_sequence` (None for Upstox).

### AN.3 Boundary

Task3 sets `provider_event_id`/`broker_order_id`/fill facts so Task1/Task2 derive stable canonical_id + fingerprint. Task3 never decides idempotency outcomes. Idempotency lives entirely in Task2 durable stores (§C.3).

------

## AO. Ordering Boundary

### AO.1 What ordering exists

- **Day38 aggregate ordering:** `TradeLifecycleEvent.sequence`, contiguous from 1, per (tenant, aggregate). Allocated by Task2 under the lock (§C.3).
- **Broker ordering (task2):** `canonical_sequence` when the provider supplies one. Upstox does NOT — `canonical_sequence=None` (§U).
- **Provider event order (task3):** `event_timestamp` where present; used as D1 input (STREAM) / fallback D2 (fills), NOT as the projection ordering key.

### AO.2 What does NOT order

- `received_at` — operational (§U.3).
- Insert order / `id` — not semantic (§W.9).
- Arrival/thread/network timing — not semantic.

### AO.3 The ordering rule

For Upstox (no provider sequence), ordering is: **idempotency (dedup) → semantic fold (§W)**. When two observations are semantically ordered (cumulative 20 then 50), the fold applies both; when conflicting (quantity 100 then 60 without modification), REJECT (no `received_at` tiebreak).

### AO.4 Concurrency ordering

The execution lock serializes writers; the fold is computed under the lock from durable rows (§L).

---

## AP. Replay Compatibility

### AP.1 What Task3 guarantees for replay

Task3 emits canonical events whose Day38 payloads (`order_id`, `cumulative_filled`, `fill_quantity`, `quantity`-bearing events) satisfy the replay guards when Task2 applies them legally:

- `order_id` = application order id (order_facts.order_id), never broker_order_id (§C.3).
- `cumulative_filled` positive int, strictly increasing per order (§C.4 guard).
- `fill_quantity` positive int.
- Terminal events only when Day38 preconditions hold; otherwise observation-only (§N/§Q).

### AP.2 Replay contract

> A Day38 stream produced by Task2 from Task3 canonical events MUST replay deterministically under `replay_execution_events` OR be observation-only with the projection carrying the facts.

### AP.3 What is NOT replayable by construction

- First-order event = `OrderFilled` without `OrderCreated`+`OrderSubmitted` (fill-first). Handled by observation-only + recovery (§P).
- First-order event = `OrderRejected` without `OrderSubmitted` (terminal-first). Observation-only (§Q).

### AP.4 Replay-preservation matrix

| Provider observation | Canonical | Task2 decision | Day38 event | Day38 precondition | Persisted stream | Replay result |
|---|---|---|---|---|---|---|
| put order req received | ORDER_SUBMITTED | APPLIED | OrderSubmitted | order exists (OrderCreated) | ...OrderSubmitted | valid (SUBMITTED) |
| open (no fill) | ORDER_ACCEPTED | APPLIED (projection-only) | none | — | unchanged | valid |
| open + filled_quantity=20 | PARTIAL_FILL | APPLIED | OrderFilled(cum=20) | order SUBMITTED | ...OrderFilled(20) | valid (PARTIALLY_FILLED) |
| open + filled_quantity=50 | PARTIAL_FILL | APPLIED | OrderFilled(cum=50) | PARTIALLY_FILLED | ...OrderFilled(50) | valid (cum 50) |
| complete | FULL_FILL | APPLIED | OrderFilled(cum=100) | SUBMITTED/PARTIALLY_FILLED | ...OrderFilled(100) | valid (FILLED) |
| rejected (after submit) | ORDER_REJECTED | APPLIED | OrderRejected | SUBMITTED/PARTIALLY_FILLED | ...OrderRejected | valid (REJECTED) |
| cancelled (after submit) | ORDER_CANCELLED | APPLIED | OrderCancelled | SUBMITTED/PARTIALLY_FILLED | ...OrderCancelled | valid (CANCELLED) |
| rejected (first event) | ORDER_REJECTED | observation-only | none | OrderRejected requires SUBMITTED | unchanged (projection REJECTED) | projection stable |
| complete (first event) | FULL_FILL | observation-only | none | OrderFilled requires order | unchanged | recovery-required |
| validation pending (after submit) | ORDER_SUBMITTED | observation-only | none | duplicate submission | unchanged | projection stable |
| unknown status | FAILURE | REJECTED | none | — | — | quarantine |

---

## AQ. Security

### AQ.1 Tenant integrity

Tenant-scoped identity (canonical_id, D1, lifecycle event_id) prevents cross-tenant replay and cross-tenant projection reads (§AK).

### AQ.2 Fail-closed normalization

Unknown statuses, malformed quantities, invalid timestamps, missing lot size → typed Failure (§AJ).

### AQ.3 No secrets

Metadata never carries credentials (§AL.2). Task3 is pure; all provider auth lives in the adapter (protected files).

### AQ.4 Payload integrity

`payload_json` in Day38 carries canonical identifiers; content fingerprint detects tamper/conflict (§C.2/§AN).

### AQ.5 Injection safety

All provider strings are data, never interpolated into SQL/JS; canonicalization joins with `\x1f` separators (no SQL context). D1/D2 hashing treats provider strings as opaque UTF-8.

---

## AR. Determinism

### AR.1 Same input → same output

Task3 is a pure function: same raw observation + same NormalizationContext → same BrokerSyncEvent (including D1/D2/canonical_id inputs). No randomness, no wall-clock beyond provider timestamps, no memory.

### AR.2 Deterministic identity

D1/D2/canonical_id are pure SHA-256 functions of canonicalized inputs (§Y/§Z/§C.2).

### AR.3 Deterministic decisions

Task2 decisions are deterministic given durable state + lock (+ commit order for losers) (§M). No `received_at` in decisions (§U.3).

### AR.4 Deterministic replay

Lifecycle replay is a pure fold of deterministic events (§C.4).

---

## AS. Multi-Order Proof

### AS.1 Setup

```
StrategyExecution E
  ├── PaperOrder A (client_order_id = "A", quantity 100)
  ├── PaperOrder B (client_order_id = "B", quantity 50)
  └── PaperOrder C (client_order_id = "C", quantity 25)
```

### AS.2 Sequence

A submitted → B submitted → C submitted → A duplicate → B fill → C cancelled.

### AS.3 Per-order lifecycle ownership (durable, per §J)

| Step | Observation | Resolves to | Day38 append | AR-5 state | Projection |
|---|---|---|---|---|---|
| 1 | submit A (<order_facts.order_id=A>) | exec E, order A | OrderSubmitted(A) | A: submitted | A SUBMITTED |
| 2 | submit B | exec E, order B | OrderSubmitted(B) | B: submitted | B SUBMITTED |
| 3 | submit C | exec E, order C | OrderSubmitted(C) | C: submitted | C SUBMITTED |
| 4 | submit A (redelivery) | exec E, order A | NONE (A already submitted, observation-only) | A unchanged | A SUBMITTED (no change) |
| 5 | partial fill B cum=20 | exec E, order B | OrderFilled(B, cum=20) | B: filled/partial | B PARTIALLY_FILLED |
| 6 | cancel C | exec E, order C | OrderCancelled(C) | C: cancelled | C CANCELLED |

### AS.4 Assertions

- A got exactly ONE OrderSubmitted; duplicate observation → no second submission (AR-1).
- B's fill updated B only: A/C cumulative unchanged (order-scoped projection + payload order_id = B).
- C's cancel did not touch A/B.
- Execution E's Day38 stream:

```
seq1 TradeIntentCreated(E)
seq2 ExecutionActivated(E)
seq3 OrderCreated(E, A)
seq4 OrderCreated(E, B)
seq5 OrderCreated(E, C)
seq6 OrderSubmitted(A)
seq7 OrderSubmitted(B)
seq8 OrderSubmitted(C)
seq9 OrderFilled(B, cum=20)
seq10 OrderCancelled(C)
```

- Replay result: E ACTIVE, A SUBMITTED, B PARTIALLY_FILLED cum=20, C CANCELLED. Deterministic.
- No cross-order suppression: A submit didn't block B; B fill didn't alter C; C cancel didn't affect A/B.

---

## AT. Concurrency Proof Matrix

For each race, transaction reasoning per §L/§M. All under PostgreSQL FOR UPDATE (SQLite: deterministic single-writer; PG is the concurrency authority).

### AT.1 Same-order submission race

- Worker1 and Worker2 deliver the SAME order's first submission simultaneously.
- Both: idempotency pre-check (none), resolve exec, ACQUIRE lock (W1 wins).
- W1: re-read ownership (absent) → mint OrderSubmitted → write AR-5 → commit.
- W2: blocked at lock; after W1 commit, re-read ownership (exists) → observation-only → no Day38 event → commit (projection row for W2's observation may still apply facts).
- Loser behavior: one OrderSubmitted total; W2's event is a projection observation. ✓

### AT.2 Different-order same-execution race

- W1 submits A; W2 submits B (same exec E).
- Both lock E serially; W1 OrderSubmitted(A); W2 OrderSubmitted(B). Two events, both legal. Ownership per-order: no cross-suppression. ✓

### AT.3 Submission + fill race

- W1: submit A; W2: fill A cum=20.
- W1 locks first: OrderSubmitted(A); commit.
- W2 locks: re-read ownership (submitted) → OrderFilled(A, cum=20) legal (order SUBMITTED). ✓
- If W2 locked first (fill-first): observation-only (no submission yet); when W1 commits, W2 already returned. The fill is durable in the projection; convergence happens when a LATER submission observation arrives (§P.5). No lost fill. ✓

### AT.4 Fill + fill race (same order)

- W1 fill cum=20; W2 fill cum=50.
- Serialized at lock; W1 OrderFilled(20); W2 OrderFilled(50) — strictly increasing, legal. If W2 read stale cum=20 and computes 50 anyway, the cumulative guard (strictly greater) accepts. If W2's cumulative <= W1's, rejected (regression). ✓

### AT.5 Terminal + late event race

- W1: rejected; W2: fill cum=20 arriving late.
- W1 locks: terminal enforcement (projection terminal) — the fill is rejected (post-terminal). OrderRejected(REJECTED). ✓
- W2 locks first: fill applies (PARTIALLY_FILLED cum=20); then W1's rejected: terminal enforcement applied (REJECTED) — the late fill is NOT double-counted; terminal absorbs. ✓

### AT.6 Anchor CAS race (first-use)

- Two events with same canonical_sequence for a fresh order (upstox N/A, but for seq-bearing providers).
- W1: SAVEPOINT {ensure anchor, write rows, CAS advance WHERE last=0} → success → commit.
- W2: CAS returns 0 rows → IngestionError(CONFLICT) → SAVEPOINT rollback → reclassify via idempotency (DUPLICATE_NOOP/CONFLICT) → outer transaction intact. ✓

### AT.7 Independent events (different orders/executions)

- No shared lock; both commit independently; no interference. ✓

---

## AU. Missing-First-Update Matrix

Full matrix: for EVERY first-observed event and every subsequent/restart/recovery outcome (§O.2 expands). Include:

| First event | Normalization | Correlation | Task2 decision | Projection | Day38 | Replay | Later submission | Later fill | Later terminal | Restart | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| put order req received | ORDER_SUBMITTED | order resolves | APPLIED | SUBMITTED | OrderSubmitted | valid | obs-only | fill legal | terminal legal | stable | none |
| validation pending | ORDER_SUBMITTED (chatter) | resolves | APPLIED (obs-only Day38) | SUBMITTED | none | n/a | first real submit mints | fill-first §P | terminal-first §Q | stable | reconcile |
| open pending | ORDER_SUBMITTED (chatter) | resolves | APPLIED (obs-only) | SUBMITTED | none | n/a | same | §P | §Q | stable | reconcile |
| trigger pending | ORDER_SUBMITTED (chatter) | resolves | APPLIED (obs-only) | SUBMITTED | none | n/a | same | §P | §Q | stable | reconcile |
| open | ORDER_ACCEPTED | resolves | APPLIED (projection-only) | OPEN | none | n/a | submit mints OrderSubmitted | §P | §Q | stable | reconcile |
| open + fill | PARTIAL_FILL | resolves | observation-only (no submit yet) | PARTIALLY_FILLED | none | n/a | §P.5 | monotonic fold | terminal first | stable | reconcile |
| complete | FULL_FILL | resolves | observation-only (no submit yet) | FILLED | none | n/a | §P.6 | D2 dedup | terminal | stable | reconcile (hard case) |
| rejected | ORDER_REJECTED | resolves | observation-only (terminal-first) | REJECTED | none | n/a | rejected by terminal | rejected | terminal | stable | reconcile |
| cancelled | ORDER_CANCELLED | resolves | observation-only (terminal-first) | CANCELLED | none | n/a | rejected by terminal | rejected | terminal | stable | reconcile |
| unknown | FAILURE | — | REJECTED | none | none | n/a | n/a | n/a | n/a | n/a | quarantine |

---

## AV. Replay-Preservation Matrix

For every lifecycle-producing canonical event, the exact replay consequence (§AP.4). Additionally:

| Event | Writes Day38? | Sequence consumed? | Replay guard satisfied | Persists projection | Terminal |
|---|---|---|---|---|---|
| ORDER_SUBMITTED (first) | OrderSubmitted | yes | PENDING→SUBMITTED | yes | no |
| ORDER_SUBMITTED (repeat) | none | no | — | yes | no |
| ORDER_ACCEPTED | none | no | — | yes (OPEN) | no |
| PARTIAL_FILL (legal) | OrderFilled | yes | SUBMITTED/PARTIALLY_FILLED → cum↑ | yes | no |
| PARTIAL_FILL (fill-first) | none | no | guard fails | yes | no |
| FULL_FILL (legal) | OrderFilled | yes | cum↑ → FILLED | yes | yes |
| FULL_FILL (fill-first) | none | no | guard fails | yes (terminal FILLED) | yes |
| FILL_RECORDED (legal) | FillRecorded | yes | SUBMITTED/PARTIALLY_FILLED/FILLED | yes | no |
| ORDER_REJECTED (legal) | OrderRejected | yes | SUBMITTED/PARTIALLY_FILLED | yes | yes |
| ORDER_REJECTED (terminal-first) | none | no | guard fails | yes (REJECTED) | yes |
| ORDER_CANCELLED (legal) | OrderCancelled | yes | SUBMITTED/PARTIALLY_FILLED | yes | yes |
| ORDER_CANCELLED (terminal-first) | none | no | guard fails | yes (CANCELLED) | yes |
| ORDER_EXPIRED (non-Upstox; legal) | OrderCancelled | yes | SUBMITTED/PARTIALLY_FILLED | yes | yes |

------

## AW. Required Task2/Day38 Prerequisites

Every prerequisite below is a REQUIRED change for Task3 to be safely implementable. They are Task2/Day38/schema changes, listed here (not implemented in this session). Each row uses the specified template.

### AW.0 Evaluation status

The contract names each requirement with its full impact; the Control Center reviews and sequences them. "Blocking status" = whether Task3 implementation may proceed before the prerequisite ships.

| ID | File | Function/class | Current behavior | Required behavior | Reason | Schema | Migration | Backfill | Index | Constraint | Concurrency | Tests | Rollback | Blocking | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AR-1 | `app/broker_sync/ingestion.py` | `_do_ingest` | resolves exec; no per-order submission ownership check | under lock, check AR-5/ownership; order-scoped submission ownership | lifecycle ownership is per-order (Issue 9) | no | no | no | no | n/a | under lock | yes | n/a | **BLOCKING** | Task2 |
| AR-2 | `app/broker_sync/ingestion.py` | `_do_ingest` | projection read BEFORE lock | lock BEFORE mutable-state reads | TOCTOU (B2) | no | no | no | no | n/a | lock ordering | yes | n/a | **BLOCKING** | Task2 |
| AR-3 | `app/broker_sync/ingestion.py` | `_do_ingest` | reads projection once pre-lock, `id.desc()` tiebreak | post-lock re-read using semantic fold | stale projections (B3) | no | no | no | no | n/a | under lock | yes | n/a | **BLOCKING** | Task2 |
| AR-4 | `app/broker_sync/ingestion.py` | `_build_projection` + lookup | insert-order tiebreak for None-seq | semantic merge fold (§W); no received_at/id | sequence-less projection (B3) | no (algorithm) | no | no | no | n/a | under lock | yes | n/a | **BLOCKING** | Task2 |
| AR-5 | NEW table `broker_order_lifecycle_state` | (new) + `_do_ingest` | no durable per-order ownership | durable per-order lifecycle state (PK tenant+order_id, schema-enforced one submission) | payload scanning unsafe (Issue 25) | **YES** | **YES** (new table) | no | yes (tenant+exec) | PK (tenant_id, order_id); UNIQUE (tenant, exec, order) | upsert inside lock+SAVEPOINT | yes | downgrade drops table | **BLOCKING** | Task2 |
| AR-6 | `app/broker_sync/ingestion.py` | `_do_ingest` + `_append_lifecycle_from_event` | no fill-first handling | fill-first reconciliation: observation-only until submission, then convergent OrderFilled with full cumulative (§P) | economic fills must not be lost/double-counted (B5) | no (uses AR-5) | no | no | no | n/a | under lock | yes | n/a | **BLOCKING** | Task2 |
| AR-7 | `app/broker_sync/ingestion.py` | `_do_ingest` terminal path | terminal enforcement exists; terminal-first not explicit | terminal-first observation-only boundary; no synthetic Day38 (§Q) | cannot mint Day38 for terminal-first (B6) | no | no | no | no | n/a | under lock | yes | n/a | **BLOCKING** | Task2 |
| AR-8 | NEW materialized current-state row | `_build_projection`/lookup | "latest row" via id tiebreak | materialized current-state row updated under lock inside SAVEPOINT (§V/W) | current-state must be semantic (B7) | **YES** (optional; alternative to AR-4 algorithm-only) | **YES** (if materialized) | no | yes | UNIQUE (tenant, broker, broker_order_id) | under lock | yes | downgrade drops | **BLOCKING** | Task2 |

### AW.1 AR-1: Order-scoped lifecycle ownership

**File:** `app/broker_sync/ingestion.py`. **Function:** `_do_ingest`.
**Current:** resolves execution_id; never checks per-order `OrderSubmitted` ownership.
**Required:** after acquiring the execution lock, check AR-5 ownership record for `(tenant, order_id)`; if `last_event_type in (OrderSubmitted, ...)` → observation-only for Day38.
**Reason:** per-order ownership (Issue 9). **Schema:** none. **Migration:** no. **Tests:** second-submission-does-not-mint-second-OrderSubmitted.

### AW.2 AR-2: Lock before mutable-state reads

**File:** `app/broker_sync/ingestion.py`. **Function:** `_do_ingest`.
**Current:** projection read BEFORE `_allocate_day38_sequence` lock.
**Required:** acquire execution lock BEFORE any mutable-state read.
**Reason:** TOCTOU (B2). **Schema:** none.

### AW.3 AR-3: Post-lock projection re-read

**File:** `app/broker_sync/ingestion.py`. **Function:** `_do_ingest`.
**Current:** one pre-lock read with `id.desc()` tiebreak.
**Required:** post-lock re-read via semantic fold.
**Reason:** stale projections (B3).

### AW.4 AR-4: Sequence-less semantic merge

**File:** `app/broker_sync/ingestion.py`. **Function:** `_build_projection` + lookup.
**Current:** `canonical_sequence.desc().nullslast(), id.desc()`.
**Required:** semantic fold merge (§W); never `received_at`/`id`.
**Reason:** Upstox has no provider sequence (§U).

### AW.5 AR-5: Durable order-scoped ownership representation

**File:** NEW table + `_do_ingest`. **Reason:** per-order ownership must be schema-enforced (Issue 25).
**Schema:** new `broker_order_lifecycle_state` table (J.4); PK (tenant_id, order_id); UNIQUE (tenant, execution, order); index (tenant, execution).
**Migration:** yes — single forward revision, create table.
**Downgrade:** drop table. Day38 tables untouched.
**Concurrency:** upsert `INSERT ... ON CONFLICT (tenant_id, order_id) DO UPDATE` inside lock + SAVEPOINT.

### AW.6 AR-6: Fill-first reconciliation

**File:** `_do_ingest` + `_append_lifecycle_from_event`.
**Required:** observation-only fill until submission; then convergent OrderFilled(cumulative = projection cumulative) (§P.5).
**Reason:** no lost/double-counted economic fill (B5).

### AW.7 AR-7: Terminal-first recovery boundary

**File:** `_do_ingest` terminal path.
**Required:** terminal-first is observation-only; no synthetic Day38; recovery-required flag (§Q).
**Reason:** Day38 guards reject terminal-first (B6).

### AW.8 AR-8: Current projection representation

**Decision:** materialized current-state row is REQUIRED. "Latest row by id" is not semantic (B7). Either:
- (a) add `broker_order_projection_current` table (UNIQUE tenant+broker+broker_order_id) updated inside SAVEPOINT; or
- (b) fold-on-read under lock (algorithm-only, no schema).
V8 selects **(b) fold-on-read under AR-3/AR-4** as the minimal durable approach for the immediate prerequisite, with (a) as the stronger option when read performance demands. This keeps the schema change minimal while eliminating the `id` tiebreak.

---

## AX. Future Task3 Test / Verification Matrix

For every shaping claim, the test that will verify it when Task3 is implemented:

| Contract claim | Test |
|---|---|
| D1 collision resistance (2 fills distinct) | partial cum=20 vs cum=50 → different D1 |
| D1 redelivery identical | same observation twice → same D1 → dedup |
| Unknown status → Failure | status="bogus" → FAILURE (never REJECTED mapped) |
| fill-first convergence | fill cum=20, then submit → OrderSubmitted + OrderFilled(20) |
| terminal-first observation-only | rejected first → projection REJECTED, no Day38 |
| multi-order independence | A submit + B fill + C cancel → per-order streams |
| quantity modification | modified 100→60 with evidence → total=60; without → REJECT |
| cross-channel dedup | trade T1 via trade feed + order-update cum jump → fill_count=1 |
| timestamp semantics | naive timestamp → FAILURE; epoch ms → UTC aware |
| lot-size fail-closed | missing lot size → FAILURE |
| ar-1..ar-8 behavior | per-table tests above |

---

## AY. Implementation Boundary

### AY.1 Task3 boundary (final)

```
Upstox raw observation
  ↓
[Task3 BOUNDARY START]
  provider validation (fail-closed) §AJ
  ↓
  correlation/context resolver (tenant, order resolution input, lot size) §I/§AD
  ↓
  field extraction + canonicalization §AE/§AF/§AB/§AC
  ↓
  D1/D2 computation §Y/§Z
  ↓
  BrokerSyncEvent construction (canonical_id via Task1) §C.2
  ↓
[Task3 BOUNDARY END]
BrokerSyncEvent
  ↓
Task2 durable ingestion §C.3 (idempotency, ownership, projection, Day38)
  ↓
Day38 replay §C.4
```

### AY.2 What Task3 does

Pure normalization: observation → BrokerSyncEvent | Failure. No DB, no locks, no lifecycle decisions, no idempotency, no projection, no recovery, no synthetic events.

### AY.3 What Task3 does NOT do (explicit)

- No Day38 lifecycle decision.
- No observation-only classification.
- No ownership decision.
- No `metadata["lifecycle_effect"]` field.
- No lock/no DB/no cache/no wall-clock.
- No recovery cursor/recovery logic/history retrieval/polling (later task).
- No Upstox adapter / websocket / webhook plumbing (protected files).

### AY.4 What this session does

Contract only. No code, no tests, no migration, no schema. The five prerequisites (AR-1..AR-8) are named for the Control Center, to be sequenced as Task2/architecture work.

---

## AZ. Contradiction Audit

Explicit self-audit of the entire document (all sections) for contradictory concepts:

| Check | Status |
|---|---|
| execution-scoped vs order-scoped | RESOLVED: execution = serialization boundary; order = ownership boundary (§I/§J/§26) |
| provider event ID vs derived observation ID | RESOLVED: §D.2/§X — provider-native vs D1 vs D2 vs canonical_id distinct |
| official status count vs observed status | RESOLVED: §G — exactly 17 CONFIRMED from appendix; observed derived facts (partial fills) labeled OBSERVED |
| canonical_sequence vs order_request_id | RESOLVED: canonical_sequence = Task2 ordering (§U); order_request_id = provider order id (broker_order_id), never application order id (§D.2/§T.4) |
| received_at ordering vs metadata | RESOLVED: §U.3/§AB.1 — received_at is operational metadata, NEVER business ordering |
| latest row vs semantic current state | RESOLVED: §V/§W/§AW.8 — semantic fold / materialized current-state; "latest row by id" rejected |
| max(quantity) vs quantity modification | RESOLVED: §U.4/§AC.6 — max() rejected; modification-evidence-only replacement |
| terminal replay vs terminal observation-only | RESOLVED: §Q — terminal-first is observation-only; legal terminal (after submission) writes Day38 |
| fill-first vs Day38 replay | RESOLVED: §P — no synthetic foundation; observation-only until legal; AR-6 |
| pure normalizer vs DB access | RESOLVED: §AY.2 — Task3 pure; DB is Task2's boundary |
| Task3 lifecycle decision vs Task2 lifecycle decision | RESOLVED: §N.4/§AY — Task3 never decides; Task2 decides under lock |
| source_mode in D1 but not canonical_id | RESOLVED: §AM.3/§AA.5 — D1 is observation identity (source_mode participates); canonical_id is event identity (content); cross-channel equivalence via D2 |

Every row is consistent with the sections referenced and with the verified source behavior.

---

## BA. Implementability Audit

**Question:** Could a developer implement Task3 from v8 without making a new architectural decision?

### BA.1 Ambiguity checks

| Area | Status |
|---|---|
| D1 exact fields + algorithm | RESOLVED (§Y.2–§Y.6) |
| D2 exact fields + fallback | RESOLVED (§Z) |
| Status→canonical mapping for all 17 statuses | RESOLVED (§G.1) |
| Which statuses mint Day38 | RESOLVED (§G/§O) |
| Ownership rule + durable representation | RESOLVED (§J, AR-5) |
| Lock ordering | RESOLVED (§L) |
| Projection current state without sequence | RESOLVED (§V/§W, AR-4/AR-8) |
| Fill-first durable behavior | RESOLVED (§P, AR-6) |
| Terminal-first durable behavior | RESOLVED (§Q, AR-7) |
| Quantity modification | RESOLVED (§U.4/§AC.6) |
| Cross-channel identity | RESOLVED (§AA) |
| Timestamp semantics | RESOLVED (§AB) |
| Restart/reconnect | RESOLVED (§S) |
| Multi-order | RESOLVED (§AS) |
| Concurrency | RESOLVED (§AT) |
| Missing-first | RESOLVED (§AU) |
| Replay preservation | RESOLVED (§AV) |
| Prerequisites | NAMED (§AW) |

### BA.2 Conclusion

No architectural decision remains open. Implementation may begin once the Control Center sequences the AR prerequisites. The remaining "decisions" are mechanical (table DDL, fold algorithm, mapping table) — all specified.

**Implementability audit result: PASS — no new architectural decision required.**

---

## BB. Final Gate

### BB.1 Precondition checklist

| Gate | Status |
|---|---|
| order-scoped lifecycle ownership durable | specified (§J, AR-5) — schema-enforced |
| concurrency safe | specified (§L/§M/§AT) — lock + idempotency PK + CAS |
| lock/re-read correct | specified (§L, AR-2/AR-3) |
| projection merge implementable | specified (§V/§W, AR-4) |
| fill-first resolved | specified (§P, AR-6) |
| terminal-first resolved | specified (§Q, AR-7) |
| restart durable | specified (§S) |
| identity exact | specified (§D.2/§X/§Y/§Z) |
| status confidence exact | specified (§F/§G — 17 CONFIRMED) |
| cross-channel identity exact | specified (§AA/§AM) |
| correlation exact | specified (§AG) |
| quantity semantics exact | specified (§AC/§U.4) |
| replay proven | specified (§AP/§AV) |
| prerequisites explicit | specified (§AW) |
| no architectural ambiguity remains | BA.2 PASS |

### BB.2 Eligibility

Because every gate is satisfied by SPECIFICATION (the AR prerequisites are explicitly named and sequenced for the Control Center, not hidden):

```
🟡 DAY39 TASK3 — CONTRACT v8 READY FOR CONTROL CENTER REVIEW
   (contract is complete and implementable; the named Task2/schema
    prerequisites AR-1..AR-8 must be sequenced before implementation)
```

The 🟡 (rather than 🟢) is correct: the contract itself is complete, but Task3 implementation remains BLOCKED on the AR prerequisites, which are Task2/schema work outside this contract session. The Control Center must approve the contract and sequence the prerequisites.

---

## Final Git / Safety Verification (this session)

**Staged/committed files:** ONLY `docs/superpowers/contracts/2026-09-10-strikenova-day39-task3-normalization-contract-v8.md`.

**No production code modified. No Task2 implementation. No Day38 implementation. No tests. No migrations. No schema. No deployment. No broker execution. Protected files untouched:**

- `backend/app/brokers/adapters/upstox/adapter.py` — untouched
- `backend/app/brokers/adapters/upstox/mapper.py` — untouched
- `backend/app/services/paper_execution.py` — untouched
- `backend/app/services/upstox.py` — untouched
- `backend/tests/test_upstox_adapter.py` — untouched

---

# DAY39 TASK3 — CONTRACT v8 PUBLICATION REPORT

## Repository

- branch: `feat/strikenova-day35-portfolio-intelligence`
- old HEAD: `1e5a89b28245ddf99daf024730743169ecb96887` (Contract v7 commit)
- new HEAD: (set by commit)
- remote HEAD: (set by push)

## Contract

- exact path: `docs/superpowers/contracts/2026-09-10-strikenova-day39-task3-normalization-contract-v8.md`
- sections: A–BB (all 55 required sections)
- lines: (set post-write)

## Five major architectural corrections

1. **order-scoped ownership** — lifecycle ownership is per application order (tenant+execution+order_id), schema-enforced via AR-5 `broker_order_lifecycle_state`; execution lock is serialization-only (§I/§J/§AW).
2. **lock/re-read** — execution lock acquired BEFORE mutable-state reads; post-lock re-read of projection + ownership + lifecycle (AR-2/AR-3) (§L).
3. **sequence-less projection** — `canonical_sequence=None` for all Upstox; projection current state = semantic fold (§V/§W/§U); `id`/`received_at` tiebreaks eliminated; `max(quantity)` rejected in favor of modification-evidence replacement (§U.4).
4. **fill-first** — fills observed before submission are observation-only, durably projected, never double-counted (D2 dedup), converge when submission arrives with the full cumulative (§P/AR-6).
5. **terminal-first** — terminal-first observations are observation-only, no synthetic Day38, recovery-required boundary (§Q/AR-7).

## Identity

- **provider-native**: Upstox `order_id`/`trade_id`/webhook event id.
- **D1**: deterministic provider-observation identity (SHA-256, exact fields §Y).
- **D2**: deterministic provider-trade identity (prefer trade id; composite fallback §Z).
- **canonical_id**: Task1 event identity (idempotency PK).
- **fingerprint**: Task2 content hash (duplicate-vs-conflict).

## Prerequisites

- AR-1 order-scoped ownership (BLOCKING)
- AR-2 lock-before-reads (BLOCKING)
- AR-3 post-lock re-read (BLOCKING)
- AR-4 semantic merge (BLOCKING)
- AR-5 durable ownership table — MIGRATION REQUIRED (BLOCKING)
- AR-6 fill-first reconciliation (BLOCKING)
- AR-7 terminal-first boundary (BLOCKING)
- AR-8 current projection representation (fold-on-read; optional materialized row) (BLOCKING)

## Audits

- **source audit:** every behavioral claim traced to baseline `aa65e1e` files/functions (§C/§D).
- **contradiction audit:** §AZ — all contradictions resolved; NO contradictory pairs remain.
- **implementability audit:** §BA — PASS; a developer can implement Task3 from v8 without a new architectural decision.
- **document-quality audit:** no placeholders; no TODOs; no "implementation time"; no "or equivalent" (replaced by exact rules); no "depending on context" without predicate; no duplicated sections; no stale v5/v6 wording; no contradictory status counts; no contradictory identity semantics.
- **safety audit:** only the v8 contract file staged/committed; protected files untouched.

## Git

- commit SHA: (set post-commit)
- commit message: `docs(day39): revise Task3 Upstox normalization contract v8`
- fast-forward: (verify post-push)
- remote verified: (verify post-push)

## Safety

✅ no production code · ✅ no Task2 implementation · ✅ no Day38 implementation · ✅ no tests · ✅ no migration · ✅ no schema implementation · ✅ no deployment · ✅ no broker execution · ✅ protected files untouched

## Final gate

```
🟡 DAY39 TASK3 — CONTRACT v8 PUBLISHED; AWAITING INDEPENDENT CONTROL CENTER REVIEW
```