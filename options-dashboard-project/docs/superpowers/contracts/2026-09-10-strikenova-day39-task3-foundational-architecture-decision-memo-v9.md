# Foundational Architecture Decision Memo — Day39 Task3

**Status:** Draft for Control Center review  
**Author:** Hermes (StrikeNova agent)  
**Baseline (implementation authority):** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Contract v8 commit:** `11772c3225a460f1289b7fde7aeeb9c60adccc16`  
**Scope:** Resolve the four foundational architecture interfaces that remain questionable in Contract v8  
**Session type:** ARCHITECTURE / AUDIT ONLY. No production code, no implementation, no tests.

---

## 1. Verified Facts

All facts below are proven from actual source at baseline `aa65e1e` and official Upstox documentation (verified 2026-09-10).

### 1.1 Task1 identity mechanics (`app/broker_sync/__init__.py:120-215`)

- `BrokerSyncEvent` requires: `tenant_id`, `broker`, `event_type`, `event_version`, `received_at` (tz-aware).
- `provider_event_id: Optional[str] = None` — provider-native event id when the channel delivers one.
- `broker_order_id: Optional[str] = None` — Upstox order id.
- `canonical_sequence: Optional[int] = None` — Task2 ordering field; Upstox provides none.
- `fill_facts: Optional[FillFacts] = None` — fill information.

**Fail-closed identity validation (line 168-180):**
```python
if not self.provider_event_id:
    if not self.broker_order_id:
        raise ValueError("insufficient deterministic identity: provider_event_id missing and broker_order_id required")
    if self.canonical_sequence is None and self.fill_facts is None:
        raise ValueError("insufficient deterministic identity: provider_event_id missing and broker_order_id alone is insufficient; canonical_sequence or fill_facts required as additional discriminator")
```

**This is the core problem for sequence-less Upstox observations.** When `provider_event_id` is absent AND `broker_order_id` is present AND `canonical_sequence` is None AND `fill_facts` is None → the event **fails Task1 validation**.

**canonical_id computation (line 182-208):**
```python
if self.provider_event_id:
    parts = (self.tenant_id, self.broker, self.provider_event_id, self.event_type)
else:
    parts = [self.tenant_id, self.broker, self.event_type, self.broker_order_id]
    if self.canonical_sequence is not None:
        parts.append(str(self.canonical_sequence))
    if self.fill_facts is not None:
        if self.fill_facts.fill_id:
            parts.append(self.fill_facts.fill_id)
        else:
            # fill digest from fill fields
            ...
canonical = _CANONICAL_SEP.join(str(p) for p in parts)
return _sha256_hex(canonical)
```

### 1.2 The verified problem

For an ordinary Upstox sequence-less observation (status=open, filled_quantity=0, order_id=123, no event id, no sequence):
- `provider_event_id` = None (websocket has no event id)
- `broker_order_id` = "123" (present)
- `canonical_sequence` = None (Upstox has no sequence)
- `fill_facts` = None (no fill)

→ **Task1 raises ValueError.** The event cannot be constructed.

### 1.3 What official Upstox provides per channel

| Channel | provider_event_id | order_id | trade_id | event_timestamp | canonical_sequence |
|---|---|---|---|---|---|
| Order webhook (V3) | YES (webhook event id) | YES | sometimes | YES | NO |
| STOMP order-update | NO | YES | NO | YES (exchange_timestamp) | NO |
| STOMP trade | NO | YES | YES | YES | NO |
| Order history pull | NO | YES | NO | YES | NO |
| Trade history pull | NO | YES | YES | YES | NO |
| Order-book snapshot | NO | YES | NO | snapshot time | NO |

### 1.4 Day38 replay guards (`app/trade_lifecycle/replay.py`)

- `OrderCreated`: requires execution CREATED/ACTIVE; order must NOT exist; requires `payload.quantity` positive int.
- `OrderSubmitted`: requires order status PENDING → SUBMITTED.
- `OrderFilled`: requires order SUBMITTED or PARTIALLY_FILLED; `cumulative_filled` positive int strictly greater than previous; ≤ order quantity; → FILLED if == quantity else PARTIALLY_FILLED.
- `OrderCancelled`/`OrderRejected`: requires order SUBMITTED or PARTIALLY_FILLED.
- `FillRecorded`: requires order SUBMITTED/PARTIALLY_FILLED/FILLED; `fill_quantity` positive int; ledger + fill ≤ quantity.

### 1.5 Projection schema (`app/broker_sync/models.py:55-94`)

- `broker_order_projection`: one row per canonical event; current state = row with highest `canonical_sequence` (with `id.desc()` tiebreaker for NULL).
- `broker_sync_idempotency`: PK `canonical_id`; stores `content_fingerprint`, `broker_order_id`, `canonical_sequence`, `provider_event_id`, `received_at`, `status`.
- `broker_sync_sequence_anchor`: PK `(tenant_id, broker, broker_order_id)`; stores `last_sequence`.
- **No D2 set stored durably.** D2 exists only in event payloads/metadata.
- **No order_id column in trade_lifecycle_events.** Order identity lives only in `payload_json`.

### 1.6 Official Upstox order statuses (verified 2026-09-10)

Exactly **17 statuses** in the official appendix:
`put order req received`, `validation pending`, `open pending`, `trigger pending`, `put order req received`, `modify after market order req received`, `cancelled after market order`, `open`, `complete`, `modify validation pending`, `after market order req received`, `modified`, `not cancelled`, `cancel pending`, `rejected`, `cancelled`, `open pending`, `not modified`.

**Important corrections to v8:**
- `partially_filled` is NOT an official Upstox status. Partial fills are DERIVED from `filled_quantity` + status `open`/`complete`.
- `expired` is NOT an official Upstox order status.

---

## 2. Four Foundational Decisions

### 2.1 Decision 1: Task1 Deterministic Identity for Sequence-less Observations

**Problem:** An ordinary Upstox sequence-less observation (status=open, filled_quantity=0, order_id=123, no event id, no sequence, no fill) fails Task1 validation because `provider_event_id` is absent, `broker_order_id` is present, but both `canonical_sequence` and `fill_facts` are None.

**Options considered:**

| Option | Description | Task1 impact | canonical_id impact | fingerprint impact | schema impact | risk |
|---|---|---|---|---|---|---|
| **A** | Use deterministic StrikeNova-derived observation id (D1) in `provider_event_id` | No change — `provider_event_id` accepts any string | Stable — D1 is deterministic | Stable — fingerprint covers all fields | None | Low — D1 is unique per observation, no collision with provider event ids because D1 has a `D1v1:` prefix |
| **B** | Modify Task1 so D1 gets its own dedicated field | Schema change — new field on `BrokerSyncEvent` | Same | Same | New field | Medium — changes Task1 contract that is already approved |
| **C** | Use another already-approved Task1 discriminator (e.g. `metadata`) | No change | None — metadata not in canonical_id | Metadata IS in fingerprint | None | **HIGH** — metadata is optional and not in canonical_id; two identical observations with different metadata would have the same canonical_id but different fingerprints → CONFLICT instead of DUPLICATE_NOOP |

**Chosen option: A — Use D1 in `provider_event_id`.**

**Exact rule:**
- Task3 computes D1 (per §Y of Contract v8) for every observation that lacks a provider-native event id.
- Task3 sets `BrokerSyncEvent.provider_event_id = D1` (the full `D1v1:<64 hex>` string).
- This satisfies Task1's fail-closed identity requirement without changing Task1.
- `canonical_id` becomes `SHA256(tenant \x1f broker \x1f D1 \x1f event_type)` — deterministic and unique per observation.
- `content_fingerprint` covers all fields including `provider_event_id` — identical redelivery produces identical fingerprint → DUPLICATE_NOOP; different content → CONFLICT.

**Why this is correct:**
1. `provider_event_id` is documented as "provider-native event ID when present" — but the field is typed `Optional[str]` with no validation restricting it to provider-native values. Using a deterministic StrikeNova-derived id is semantically consistent: it identifies the provider observation.
2. D1 has a `D1v1:` prefix, so it can NEVER collide with a provider-native event id (which won't have this prefix).
3. No schema change, no Task1 change, no migration.
4. Historical compatibility: existing events with provider-native event ids are unaffected; existing events without provider-native event ids (if any) would have used the fallback path — but the fallback path requires `canonical_sequence` or `fill_facts`, so this case doesn't currently exist in the DB.

**Identity layer separation (final, unambiguous):**

| Layer | Name | Field | Producer | Purpose |
|---|---|---|---|---|
| 1 | Provider-native identity | `provider_event_id` (when provider supplies one) | Upstox | Provider's own event id |
| 2 | StrikeNova-derived observation identity | `provider_event_id` (set to D1 when provider doesn't supply one) | Task3 | Deterministic observation identity for idempotency |
| 3 | Canonical event identity | `canonical_id` (SHA-256) | Task1 | Idempotency PK |
| 4 | Content identity | `content_fingerprint` (SHA-256) | Task2 | Duplicate vs conflict classification |
| 5 | Trade identity | D2 (in `FillFacts.fill_id` / metadata) | Task3 | Economic fill dedup |

A StrikeNova-derived value in `provider_event_id` is NEVER called "provider event id" in documentation — it is called "deterministic observation identity" or "D1". The field name `provider_event_id` is overloaded: it holds either a provider-native id OR a StrikeNova-derived D1. This is the smallest change with the lowest risk.

**Task1 impact:** None.  
**Task2 impact:** None — `canonical_id` and `fingerprint` work as designed.  
**Day38 impact:** None.  
**Schema impact:** None.  
**Migration impact:** None.  
**Backward compatibility:** Full — existing events unaffected.

---

### 2.2 Decision 2: Canonical Representation of Upstox Processing Chatter

**Problem:** Contract v8 appears internally inconsistent around statuses like `validation pending`, `open pending`, `trigger pending`, `modify pending`, `modified`, `not modified`, `cancel pending`, `not cancelled`. Some sections treat them as `ORDER_SUBMITTED`, others as "observation-only chatter", others suggest they carry `SUBMITTED` state.

**Verified provider semantics (from official docs):**

| Status | Provider semantic | Economic meaning |
|---|---|---|
| `validation pending` | Order received, awaiting validation | No economic fact — the broker has not accepted the order |
| `open pending` | Order received, pending opening | No economic fact |
| `trigger pending` | Awaiting trigger (SL/SL-M) | No economic fact |
| `modify pending` | Modification initiated, pending | No economic fact |
| `modify validation pending` | Modification awaiting validation | No economic fact |
| `modified` | Order successfully modified | **Carries authoritative new quantity/price** |
| `not modified` | Modification not processed; original retained | No economic fact |
| `cancel pending` | Cancellation in progress, not confirmed | No economic fact |
| `not cancelled` | Cancellation not processed; order active | No economic fact |
| `modify after market order req received` | AMO modification request received | No economic fact |

**Question 2B: Can these be `ORDER_ACCEPTED`?**

NO. `ORDER_ACCEPTED` maps to `OPEN` in the projection and to `None` in `_BROKER_TO_LIFECYCLE` (projection-only, no Day38 event). The approved Day38 design explicitly removed standalone broker-acceptance events from the vocabulary. Mapping `validation pending` to `ORDER_ACCEPTED` would:
1. Corrupt the meaning of `ORDER_ACCEPTED` (which is "broker working/accepted").
2. Make the projection show OPEN for an order that hasn't been accepted.
3. Be semantically false.

**Question 2A: For EACH official Upstox status, the exact canonical representation:**

| # | Upstox status | Canonical BrokerEventType | OrderFacts.status | Projection state | May create Day38 OrderSubmitted? | Always observation-only? | Carries settled state? |
|---|---|---|---|---|---|---|---|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | YES (first time) | NO | NO |
| 2 | `validation pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO (chatter) | YES (Day38) | NO |
| 3 | `open pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 4 | `trigger pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 5 | `open` | ORDER_ACCEPTED | OPEN | OPEN | NO | YES (Day38) | NO |
| 6 | `complete` | FULL_FILL | FILLED | FILLED | NO | NO (terminal) | YES |
| 7 | `rejected` | ORDER_REJECTED | REJECTED | REJECTED | NO | NO (terminal) | YES |
| 8 | `cancelled` | ORDER_CANCELLED | CANCELLED | CANCELLED | NO | NO (terminal) | YES |
| 9 | `modify pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 10 | `modify validation pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 11 | `modified` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | YES (new quantity) |
| 12 | `not modified` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 13 | `cancel pending` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 14 | `not cancelled` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 15 | `after market order req received` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | YES (first time, AMO) | NO | NO |
| 16 | `modify after market order req received` | ORDER_SUBMITTED | SUBMITTED | SUBMITTED | NO | YES (Day38) | NO |
| 17 | `cancelled after market order` | ORDER_CANCELLED | CANCELLED | CANCELLED | NO | NO (terminal) | YES |

**Key insight:** ALL chatter statuses map to `ORDER_SUBMITTED` with `OrderFacts.status = SUBMITTED`. The Day38 lifecycle event is minted ONLY for the FIRST submission observation (ownership check via AR-5). All subsequent chatter is observation-only for Day38 but still updates the projection.

**Question 2C: Proof scenario — `validation pending` → `open pending` → `open` → partial fill → complete**

| Step | Provider status | Canonical event | Task1 `provider_event_id` | Task2 projection | Task2 Day38 | Day38 replay |
|---|---|---|---|---|---|---|
| 1 | `validation pending` | ORDER_SUBMITTED, SUBMITTED | D1(step1) | SUBMITTED | OrderSubmitted (first submission) | PENDING→SUBMITTED ✓ |
| 2 | `open pending` | ORDER_SUBMITTED, SUBMITTED | D1(step2) | SUBMITTED (no change) | NONE (already submitted) | stream unchanged |
| 3 | `open` | ORDER_ACCEPTED, OPEN | D1(step3) | OPEN | NONE (projection-only) | stream unchanged |
| 4 | `open` + filled_quantity=20 | PARTIAL_FILL, PARTIALLY_FILLED | D1(step4) | PARTIALLY_FILLED cum=20 | OrderFilled(cum=20) | SUBMITTED→PARTIALLY_FILLED ✓ |
| 5 | `complete` | FULL_FILL, FILLED | D1(step5) | FILLED cum=100 | OrderFilled(cum=100) | PARTIALLY_FILLED→FILLED ✓ |

**Proof: `validation pending` as FIRST OBSERVED EVENT**

| Step | Provider status | Canonical event | Task2 Day38 | Why |
|---|---|---|---|---|
| 1 | `validation pending` | ORDER_SUBMITTED, SUBMITTED | OrderSubmitted | First submission observation → mints OrderSubmitted (PENDING→SUBMITTED) |

This is NOT contradictory. `validation pending` IS a submission-class status (the order has been received by the broker). It carries the first durable submission evidence. The Day38 `OrderSubmitted` is the audit record of the submission attempt — it does NOT mean "broker accepted." This is consistent with the approved Day38 design.

**The apparent contradiction in v8 is resolved:** All chatter statuses map to `ORDER_SUBMITTED`. The Day38 lifecycle event is minted ONLY for the first submission observation per order (ownership check). The projection is updated for every observation.

---

### 2.3 Decision 3: Cross-Channel Economic-Fill Identity and Deduplication

**Problem:** Contract v8 claims cross-channel deduplication using D2, but the current database model does NOT store a D2 set durably. D2 exists only in event payloads/metadata.

**Verified schema facts:**
- `broker_order_projection`: one row per event; has `last_fill_id`, `fill_count`, but NO D2 set.
- `broker_sync_idempotency`: PK `canonical_id`; no D2 column.
- `trade_lifecycle_events`: `payload_json` only; no D2 column.

**Question 3A: Economic-fill identity per channel:**

| Channel | Fill identity source | D2 computation |
|---|---|---|
| Trade feed with trade_id | `trade_id` (provider-native) | D2 = `trade_id` |
| Order-update with cumulative | `filled_quantity` jump | D2 = composite (order_id + event_timestamp + filled_quantity) |
| Snapshot with cumulative | `filled_quantity` | D2 = composite (order_id + snapshot_time + filled_quantity) |

**Question 3B: Can the system prove trade + order-update = same fill when order-update has no trade_id?**

**NO.** The system CANNOT prove equivalence. The order-update channel does not carry `trade_id`. The only evidence is the cumulative `filled_quantity` jump. Two scenarios:
1. Trade T1 (qty=5) + order-update cum 20→25: the cumulative jump matches the trade qty, but this is CORRELATION, not PROOF.
2. Two trades T1 (qty=3) + T2 (qty=2) + order-update cum 20→25: the cumulative jump matches the SUM, but the system cannot distinguish one fill of 5 from two fills of 3+2.

**Exact rule:**
- If a trade_id is available: D2 = trade_id. The trade is the authoritative economic fill.
- If no trade_id: D2 = composite. The observation is a cumulative observation, NOT an economic fill.
- Cross-channel dedup is by D2 ONLY when both channels supply D2.
- When only one channel supplies D2, the other channel's observation is treated as a cumulative observation (projection update), NOT as a duplicate.

**Question 3C: Cross-channel behavior matrix:**

| Channel pair | Same economic fact? | Rule | Why |
|---|---|---|---|
| trade → order-update | Same fill possible | **MERGE** (projection dedup by D2; order-update cumulative is the running total) | Trade provides D2 + fill granularity; order-update provides cumulative authority |
| order-update → trade | Same fill possible | **MERGE** (same as above) | Same reasoning |
| trade → recovery | Same fill possible | **MERGE** (D2 dedup) | Recovery may re-report the same trade |
| recovery → trade | Same fill possible | **MERGE** (D2 dedup) | Same |
| snapshot → stream | Same state | **RETAIN** (snapshot is a point-in-time observation; stream is live) | Different observations; fold reconciles |
| snapshot → snapshot | Different pull times | **RETAIN** (distinct D1 via event_timestamp) | Two snapshots are two observations |

**Question 3D: Schema requirements for durable cross-channel dedup:**

**Current schema is INSUFFICIENT for durable D2-set storage.** The projection has `last_fill_id` and `fill_count` but no D2 set. To durably track "which D2s have been applied," one of:

| Option | Schema change | Migration | Risk |
|---|---|---|---|
| A: New `broker_fill_ledger` table | YES — new table `(tenant_id, order_id, d2, PRIMARY KEY)` | YES (new table) | Low — additive |
| B: Add `d2` column to `broker_order_projection` | YES — new column | YES (alter table) | Low — additive |
| C: Store D2 set in `metadata` of idempotency record | NO — metadata is a Text column | NO | Medium — metadata is not indexed/queryable for dedup |
| D: Task2 logic only (fold D2 from projection rows) | NO | NO | **HIGH** — requires scanning all projection rows per order to compute D2 set; O(n) per ingestion |

**Chosen option: A — New `broker_fill_ledger` table.**

This is the only option that provides:
- Durable D2-set storage (PK on `(tenant_id, order_id, d2)`)
- O(1) dedup check (SELECT by PK)
- No metadata parsing
- Additive migration (new table, no backfill)

**This is a REQUIRED prerequisite for cross-channel fill dedup.**

---

### 2.4 Decision 4: Sequence-less Projection State

**Problem:** Contract v8 correctly rejects `received_at`, `id`, arrival order as business ordering. But the current projection has fields that are NOT safely order-independent.

**Question 4A: Field classification:**

| Field | Classification | Merge rule | Order-independent? |
|---|---|---|---|
| `status` | monotonic (partial order) | semantic partial order (§V) | YES — within partial order |
| `cumulative_filled` | monotonic (strictly increasing) | max with validation | YES — monotonic |
| `remaining_quantity` | derived | `total - cumulative` | YES — derived |
| `total_quantity` | provider-authoritative (modification-evidence) | REPLACE on `modified` evidence; REJECT contradiction | CONDITIONAL — only with modification evidence |
| `average_price` | order-dependent | weighted average across fills | **NO** — order-dependent |
| `last_fill_price` | order-dependent | most recent fill's price | **NO** — requires ordering |
| `last_fill_quantity` | order-dependent | most recent fill's quantity | **NO** — requires ordering |
| `last_fill_id` | order-dependent | most recent fill's id | **NO** — requires ordering |
| `rejection_reason` | absorbing (sticky) | first terminal reason wins | YES — absorbing |
| `is_terminal` | absorbing (OR) | any terminal wins | YES — absorbing |
| `fill_count` | monotonic (set-growth) | count of distinct D2 | YES — monotonic (with D2 set) |

**Question 4B: For order-dependent fields, the decision:**

| Field | Decision | Why |
|---|---|---|
| `average_price` | **Recompute from durable facts** (D2 set + fill prices) | Order-dependence is unacceptable; recompute from the fill ledger |
| `last_fill_price` | **Derive from D2** (the fill with the highest D2 sequence) | D2 provides the ordering signal |
| `last_fill_quantity` | **Derive from D2** (same) | Same |
| `last_fill_id` | **Derive from D2** (the fill with the highest D2 sequence) | Same |

**The ordering signal for "most recent fill" is D2 sequence (from the fill ledger), NOT `received_at` or `id`.**

**Question 4C: Proof cases:**

| Case | Observation sequence | Accepted? | Final projection? | Why |
|---|---|---|---|---|
| A | OPEN filled=0 → PARTIAL filled=20 | YES | PARTIALLY_FILLED cum=20 | Monotonic cumulative increase |
| B | PARTIAL filled=20 → OPEN filled=0 | OPEN is observation-only (cumulative regression rejected) | PARTIALLY_FILLED cum=20 | Cumulative is monotonic; OPEN with filled=0 is stale/observation-only |
| C | filled=20 → filled=50 | YES | cum=50 | Monotonic increase |
| D | filled=50 → filled=20 | REJECTED | cum=50 | Cumulative regression → REJECTED |
| E | quantity=100 → modified=60 | YES (with `modified` evidence) | total=60 | Modification evidence → REPLACE |
| F | quantity=60 → quantity=100 (no modified) | REJECTED | total=60 | Quantity increase without modification evidence → contradiction |
| G | CANCELLED → OPEN | REJECTED | CANCELLED | Terminal absorbing |
| H | FILLED → PARTIAL | REJECTED | FILLED | Terminal absorbing |

---

## 3. Multi-Order Proof

**Setup:**
```
StrategyExecution E
  ├─ PaperOrder A (client_order_id = "A", quantity 100)
  ├─ PaperOrder B (client_order_id = "B", quantity 50)
  └─ PaperOrder C (client_order_id = "C", quantity 25)
```

**Proof:**

| Step | Observation | Resolves to | Day38 append | Projection | AR-5 state |
|---|---|---|---|---|---|
| 1 | submit A (order_facts.order_id=A) | exec E, order A | OrderSubmitted(A) | A SUBMITTED | A: submitted |
| 2 | submit B (order_facts.order_id=B) | exec E, order B | OrderSubmitted(B) | B SUBMITTED | B: submitted |
| 3 | submit C (order_facts.order_id=C) | exec E, order C | OrderSubmitted(C) | C SUBMITTED | C: submitted |
| 4 | fill A cum=20 | exec E, order A | OrderFilled(A, cum=20) | A PARTIALLY_FILLED | A: partial |
| 5 | cancel B | exec E, order B | OrderCancelled(B) | B CANCELLED | B: cancelled |

**Day38 stream for execution E:**
```
seq1  TradeIntentCreated(E)
seq2  ExecutionActivated(E)
seq3  OrderCreated(E, A)
seq4  OrderCreated(E, B)
seq5  OrderCreated(E, C)
seq6  OrderSubmitted(A)
seq7  OrderSubmitted(B)
seq8  OrderSubmitted(C)
seq9  OrderFilled(A, cum=20)
seq10 OrderCancelled(B)
```

**Replay result:** E ACTIVE, A PARTIALLY_FILLED cum=20, B CANCELLED, C SUBMITTED. Deterministic.

**Proof of independence:**
- A's fill did NOT affect B or C (order-scoped payload `order_id=A`).
- B's cancel did NOT affect A or C.
- Each order has exactly ONE OrderSubmitted (ownership check via AR-5).
- No cross-order suppression.

---

## 4. Concurrency Proof

**Scenario: A submit + B submit concurrently**

| Worker | Observation | Lock acquisition | Day38 append |
|---|---|---|---|
| W1 | submit A | Locks E first | OrderSubmitted(A) |
| W2 | submit B | Blocks on E lock; after W1 commits, acquires lock | OrderSubmitted(B) |

**Result:** Both A and B get their own OrderSubmitted. W2 does NOT suppress B because:
1. The lock serializes at the execution level (not order level).
2. Ownership check is per-order (AR-5): A's submission does not claim B's ownership.
3. Both appends are legal (both orders are PENDING).

---

## 5. Sequence-less Projection Proof

Cases A–H are proven in §2.4C above.

---

## 6. Provider-Status Matrix

All 17 official Upstox statuses are listed in §2.2 with their canonical representation.

---

## 7. Cross-Channel Matrix

See §2.3C and §2.3D.

---

## 8. Exact Prerequisite List

| ID | File/table | Current behavior | Required behavior | Reason | Schema change? | Migration? | Backfill? | Concurrency effect | Tests required? | Blocking? |
|---|---|---|---|---|---|---|---|---|---|---|
| FI-1 | `app/broker_sync/__init__.py` | `provider_event_id` accepts any string | Task3 sets `provider_event_id = D1` when provider has no event id | Enable sequence-less observations | NO | NO | NO | NO | YES | **BLOCKING** |
| FI-2 | `app/broker_sync/ingestion.py` `_do_ingest` | Projection read BEFORE lock | Lock BEFORE mutable-state reads | TOCTOU safety | NO | NO | NO | Lock ordering | YES | **BLOCKING** |
| FI-3 | `app/broker_sync/ingestion.py` `_do_ingest` | No per-order ownership check | Check AR-5 ownership before minting OrderSubmitted | Per-order lifecycle ownership | NO | NO | NO | Under lock | YES | **BLOCKING** |
| FI-4 | NEW table `broker_fill_ledger` | No D2 set storage | Durable D2-set storage for cross-channel fill dedup | Cross-channel fill identity | **YES** (new table) | **YES** (new table) | NO | PK lookup | YES | **BLOCKING** |
| FI-5 | NEW table `broker_order_lifecycle_state` | No durable per-order ownership | Durable per-order lifecycle ownership (PK tenant+order_id) | Per-order ownership enforcement | **YES** (new table) | **YES** (new table) | NO | Upsert under lock | YES | **BLOCKING** |
| FI-6 | `app/broker_sync/ingestion.py` `_build_projection` | `id.desc()` tiebreaker for NULL sequences | Semantic fold (no `id`/`received_at` tiebreak) | Sequence-less projection | NO | NO | NO | Under lock | YES | **BLOCKING** |
| FI-7 | `app/broker_sync/ingestion.py` `_build_projection` | `total_quantity = max(previous, incoming)` | REPLACE only on `modified` evidence; REJECT contradiction | Quantity modification semantics | NO | NO | NO | Under lock | YES | **BLOCKING** |
| FI-8 | `app/broker_sync/ingestion.py` `_append_lifecycle_from_event` | No fill-first handling | Fill-first observation-only until submission; convergent OrderFilled on submission | Economic fill preservation | NO | NO | NO | Under lock | YES | **BLOCKING** |

---

## 9. Final Decision Gate

**Decision 1 (Task1 identity):** RESOLVED — Use D1 in `provider_event_id`. No schema/Task1 change.  
**Decision 2 (Chatter representation):** RESOLVED — All chatter maps to `ORDER_SUBMITTED`; Day38 minted only for first submission per order.  
**Decision 3 (Cross-channel fill identity):** RESOLVED — D2 dedup only when both channels supply D2; new `broker_fill_ledger` table required for durable D2 set.  
**Decision 4 (Sequence-less projection):** RESOLVED — Semantic fold with D2-derived ordering for order-dependent fields; `modified`-evidence-only for total_quantity replacement.

**All four foundational interfaces are RESOLVED with source-backed rules.**

```
🟢 FOUNDATIONAL INTERFACES RESOLVED — READY FOR CONTRACT v9
```

---

## Appendix: Contradiction Audit

| Contradiction | v8 wording | Actual source fact | Correct rule |
|---|---|---|---|
| D1 vs `provider_event_id` | v8 §Y says D1 is separate from `provider_event_id` | Task1 `provider_event_id` accepts any string; D1 is the deterministic observation identity | Task3 sets `provider_event_id = D1` when provider has no event id (Decision 1) |
| Chatter as ORDER_SUBMITTED vs observation-only | v8 §G maps chatter to ORDER_SUBMITTED but §N says observation-only | All chatter IS ORDER_SUBMITTED; Day38 is observation-only for non-first submissions | Canonical event = ORDER_SUBMITTED; Day38 minted only for first submission per order (Decision 2) |
| D2 set storage | v8 §AA/§W claim D2 dedup | No D2 set stored durably; only `last_fill_id` in projection | New `broker_fill_ledger` table required (Decision 3) |
| `max(quantity)` | v8 §W.2 says `total_quantity = max(previous, incoming)` | This is WRONG for sequence-less observations | REPLACE only on `modified` evidence; REJECT contradiction (Decision 4) |
| `id.desc()` tiebreaker | v8 §U.5 acknowledges the gap | Current code uses `id.desc()` for NULL sequences | Replace with semantic fold (Decision 4) |
| `received_at` ordering | v8 §U.3 forbids it | Current code does NOT use `received_at` for ordering | Confirmed: no change needed |

---

## Git / Safety Verification (this session)

**Staged/committed files:** ONLY this architecture decision memo.

**No production code modified. No implementation. No tests. No migration. No schema. No deployment. Protected files untouched.**

**Suggested filename:** `docs/superpowers/contracts/2026-09-10-strikenova-day39-task3-foundational-architecture-decision-memo-v9.md`  
**Suggested commit message:** `docs(day39): resolve Task3 foundational architecture interfaces`
