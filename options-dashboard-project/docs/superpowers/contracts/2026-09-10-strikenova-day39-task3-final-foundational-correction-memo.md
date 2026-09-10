# Revised Foundational Architecture Design Memo — Day39 Task3

**Status:** Revision — supersedes `1072de4`  
**Author:** Hermes (StrikeNova agent)  
**Baseline (implementation authority):** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`  
**Scope:** Resolve all 8 findings from the rejected green gate  
**Session type:** DESIGN REVISION ONLY

---

## 1. Official Status Inventory

### 1.1 Provider-documented statuses (official Upstox appendix, verified 2026-09-10)

The official Upstox Order Status appendix lists **exactly 17 values**. This is the authoritative provider vocabulary.

| # | Provider status value | Provider-documented meaning |
|---|---|---|
| 1 | `validation pending` | The order has been received and is awaiting validation. |
| 2 | `modify pending` | A request to modify the order has been initiated and is pending. |
| 3 | `trigger pending` | The order is awaiting a trigger to move it to the market. |
| 4 | `put order req received` | The request to place a new order has been received. |
| 5 | `modify after market order req received` | A modification request for an after-market order has been received. |
| 6 | `cancelled after market order` | The after-market order has been cancelled. |
| 7 | `open` | The order is active and open in the market. |
| 8 | `complete` | The order has been fully executed. |
| 9 | `modify validation pending` | A modification request has been received and is pending validation. |
| 10 | `after market order req received` | A new after-market order request has been received. |
| 11 | `modified` | The order has been successfully modified. |
| 12 | `not cancelled` | The request for cancellation was not processed; the order remains active. |
| 13 | `cancel pending` | The order is in the process of cancellation but the cancellation is not yet confirmed. |
| 14 | `rejected` | The order was not accepted and has been rejected by the exchange. |
| 15 | `cancelled` | The order has been successfully cancelled. |
| 16 | `open pending` | The order has been received and is pending opening. |
| 17 | `not modified` | The request for modification was not processed; the order remains in its original state. |

### 1.2 Canonical/internal semantic vocabulary (StrikeNova)

These are NOT provider values. They are the canonical event types and states used internally.

**Canonical broker event types (`BrokerEventType`):**
- `ORDER_SUBMITTED` — the submission attempt was observed
- `ORDER_ACCEPTED` — broker reports order is working/open (projection-only for Day38)
- `ORDER_REJECTED` — broker/exchange rejected the order
- `ORDER_CANCELLED` — order was cancelled
- `ORDER_EXPIRED` — order expired (non-Upstox; reserved)
- `PARTIAL_FILL` — partial fill observed
- `FULL_FILL` — full fill observed
- `FILL_RECORDED` — fill recorded (post-submission fill ledger entry)
- `ORDER_RECOVERED` — recovery event (rejected at mapping layer for Task2)

**Canonical order states (`CanonicalOrderState`):**
- `PENDING` — order created but not yet submitted
- `SUBMITTED` — submission attempt observed
- `OPEN` — broker reports order is working/open
- `PARTIALLY_FILLED` — partially filled
- `FILLED` — fully filled
- `CANCELLED` — cancelled
- `REJECTED` — rejected
- `EXPIRED` — expired
- `UNKNOWN` — unknown/unrecognized

### 1.3 Provider-to-canonical mapping

| Provider status | Canonical event type | Canonical order state | Notes |
|---|---|---|---|
| `put order req received` | ORDER_SUBMITTED | SUBMITTED | First submission evidence |
| `after market order req received` | ORDER_SUBMITTED | SUBMITTED | First submission evidence (AMO) |
| `validation pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `open pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `trigger pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `modify pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `modify validation pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `modified` | ORDER_OBSERVED | SUBMITTED | Modification acknowledgment |
| `not modified` | ORDER_OBSERVED | SUBMITTED | Modification failure observation |
| `cancel pending` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `not cancelled` | ORDER_OBSERVED | SUBMITTED | Cancellation failure observation |
| `modify after market order req received` | ORDER_OBSERVED | SUBMITTED | Processing observation |
| `open` | ORDER_ACCEPTED | OPEN | Broker working/accepted |
| `complete` | FULL_FILL | FILLED | Terminal fill |
| `rejected` | ORDER_REJECTED | REJECTED | Terminal rejection |
| `cancelled` | ORDER_CANCELLED | CANCELLED | Terminal cancellation |
| `cancelled after market order` | ORDER_CANCELLED | CANCELLED | Terminal cancellation (AMO) |

**Important:** Partial fills are NOT a provider status. They are DERIVED from `filled_quantity` between 0 and quantity with status `open` or `complete`.

---

## 2. D1 Observation Identity — Redesigned

### 2.1 The defect in the previous design

The previous design included mutable content fields (like `average_price`, `filled_quantity`, `reject_reason`) in D1. This caused:

```
different average_price
→ same D1 (if avg_price not in D1)
→ same canonical_id
→ different fingerprint
→ CONFLICT
```

This is unacceptable. A legitimate provider observation change (e.g. average_price update) must NOT produce a CONFLICT.

### 2.2 Identity vs Content vs Provenance — Formal Model

Every provider observation is decomposed into three orthogonal layers:

#### Layer A: Provider-Observation Identity (D1)

**Purpose:** Uniquely identifies WHICH provider fact this observation represents.  
**Property:** Deterministic, stable for the same provider fact, different for different provider facts.  
**Used for:** `canonical_id` (idempotency PK).  
**Rule:** Same provider fact → same D1 → same `canonical_id`. Different provider fact → different D1 → different `canonical_id`.

#### Layer B: Observation Content (fingerprint)

**Purpose:** Captures WHAT the provider reported at that observation.  
**Property:** Can change between observations of the same provider fact (e.g. price updates, quantity changes).  
**Used for:** `content_fingerprint` (duplicate vs conflict classification).  
**Rule:** Same content → same fingerprint → DUPLICATE_NOOP. Different content → different fingerprint → CONFLICT (if same D1).

#### Layer C: Delivery Provenance

**Purpose:** Captures HOW the system received the observation.  
**Property:** Independent of the provider fact itself.  
**Used for:** `source_mode`, `received_at`, `provider_event_id` (when provider-supplied).  
**Rule:** Same provider fact via different channels → same D1, different provenance.

### 2.3 D1 Input Field Classification

| Field | Classification | Rationale |
|---|---|---|
| `tenant_id` | Identity | Tenant scope |
| `broker` | Identity | Broker scope |
| `order_id` (provider) | Identity | Which provider order |
| `event_type` (canonical) | Identity | What kind of observation |
| `provider_trade_id` | Identity | Which economic fill (fill events only) |
| `event_timestamp` | **Content** | Provider-reported time — mutable for corrections |
| `order_status` (provider) | **Content** | Provider-reported status — mutable |
| `filled_quantity` (provider) | **Content** | Provider-reported quantity — mutable |
| `cancel_quantity` (provider) | **Content** | Provider-reported quantity — mutable |
| `reject_reason` (provider) | **Content** | Provider-reported reason — mutable |
| `average_price` | **Content** | Provider-reported price — mutable |
| `source_mode` | **Provenance** | How we received it |
| `received_at` | **Provenance** | When we received it |

### 2.4 D1 Specification (Revised)

```
D1 = SHA256("D1v1:" \x1f
    tenant_id \x1f
    broker \x1f
    order_id(provider) \x1f
    event_type(canonical) \x1f
    provider_trade_id(or empty))
```

**Only identity fields participate in D1.** Content fields (event_timestamp, order_status, filled_quantity, etc.) do NOT participate in D1. They participate in the fingerprint.

### 2.5 Consequence: Same provider fact, different content

When the same provider fact is observed again with different content (e.g. updated `average_price`):

```
Same D1 → Same canonical_id → Different fingerprint → CONFLICT
```

This is CORRECT behavior. The system detects that the same observation identity has conflicting content. The caller decides: accept the new content (update projection) or reject as conflict.

### 2.6 Consequence: Different provider facts

When two genuinely different provider observations occur (e.g. two different fills):

```
Different D1 (different trade_id) → Different canonical_id → Both APPLIED
```

### 2.7 Consequence: Same provider fact via different channels

When the same provider fact is delivered via STREAM then RECOVERY:

```
Same D1 (identity fields identical) → Same canonical_id → Same fingerprint → DUPLICATE_NOOP
```

The `source_mode` is NOT in D1, so channel differences do not create different observations.

---

## 3. Observation Identity vs Delivery Provenance

### 3.1 The three layers (formal)

| Layer | Question answered | Fields | Used for |
|---|---|---|---|
| **A. Provider-observation identity** | Which provider fact? | `tenant_id`, `broker`, `order_id`, `event_type`, `provider_trade_id` | D1 → `canonical_id` |
| **B. Observation content** | What was reported? | `event_timestamp`, `order_status`, `filled_quantity`, `cancel_quantity`, `reject_reason`, `average_price`, `total_quantity`, `cumulative_filled`, `last_fill_price`, `last_fill_quantity`, `rejection_reason`, `is_terminal` | `content_fingerprint` |
| **C. Delivery provenance** | How did we receive it? | `source_mode`, `received_at`, `provider_event_id` (when provider-supplied) | Audit, ordering aid |

### 3.2 Rules for common scenarios

| Scenario | D1 | canonical_id | Fingerprint | Result |
|---|---|---|---|---|
| Same provider fact received twice (identical content) | Same | Same | Same | DUPLICATE_NOOP |
| Same provider fact via different channels (identical content) | Same | Same | Same | DUPLICATE_NOOP |
| Same provider fact with corrected content (e.g. updated price) | Same | Same | Different | CONFLICT (caller decides) |
| Genuinely changed provider observation (e.g. new fill) | Different | Different | Different | Both APPLIED |
| Conflicting observations (same identity, irreconcilable content) | Same | Same | Different | CONFLICT → quarantine |

### 3.3 Correction/supersession

When the provider corrects a previous observation (e.g. updates `average_price`):

1. Same D1 → Same `canonical_id`.
2. Different fingerprint → CONFLICT detected.
3. Task2 decides: if the new content is a documented correction (e.g. `modified` status), accept and update projection. Otherwise, quarantine for recovery.

### 3.4 Conflicting observations

When two observations have the same D1 but irreconcilable content:

1. Same D1 → Same `canonical_id`.
2. Different fingerprint → CONFLICT.
3. Task2 quarantines the observation (REJECTED with deterministic reason).
4. Recovery (later task) reconciles.

---

## 4. ORDER_PROCESSING Task1 Contract Change

### 4.1 Acknowledgment

**`ORDER_PROCESSING` is a Task1 contract change.** The current `BrokerEventType` enum does NOT contain `ORDER_PROCESSING`. Adding it requires:

1. New enum value in `BrokerEventType`.
2. New mapping in `_BROKER_TO_LIFECYCLE`.
3. New test coverage.
4. Documentation update.

This is NOT "zero Task1 impact." It is a controlled, additive Task1 change.

### 4.2 Exact enum/value

```python
class BrokerEventType(str, Enum):
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_PROCESSING = "ORDER_PROCESSING"  # NEW
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FULL_FILL = "FULL_FILL"
    FILL_RECORDED = "FILL_RECORDED"
    ORDER_RECOVERED = "ORDER_RECOVERED"
```

### 4.3 Why it is required

The existing vocabulary cannot truthfully represent provider processing observations:

- `ORDER_SUBMITTED` means "the submission attempt was observed." Processing chatter is NOT the submission attempt.
- `ORDER_ACCEPTED` means "broker working/accepted." Processing chatter is NOT acceptance.
- `ORDER_REJECTED`/`ORDER_CANCELLED` mean terminal states. Processing chatter is NOT terminal.

Without `ORDER_PROCESSING`, the system must either:
1. Misrepresent processing chatter as `ORDER_SUBMITTED` (false claim), or
2. Misrepresent processing chatter as `ORDER_ACCEPTED` (false claim).

`ORDER_PROCESSING` is the smallest additive change that preserves semantic truthfulness.

### 4.4 Where it is emitted

Task3 emits `ORDER_PROCESSING` for these provider statuses:
- `validation pending`, `open pending`, `trigger pending`
- `modify pending`, `modify validation pending`
- `modified`, `not modified`
- `cancel pending`, `not cancelled`
- `modify after market order req received`

### 4.5 Backward compatibility

- **Additive only.** Existing event types are unchanged.
- **Existing events unaffected.** No migration of existing data.
- **Existing tests unaffected.** New tests added for `ORDER_PROCESSING`.
- **Day38 unaffected.** `ORDER_PROCESSING` maps to `None` in `_BROKER_TO_LIFECYCLE` (projection-only).

### 4.6 Required Task1 tests

1. `ORDER_PROCESSING` is a valid `BrokerEventType` value.
2. `ORDER_PROCESSING` maps to `None` in `_BROKER_TO_LIFECYCLE`.
3. `ORDER_PROCESSING` event with valid D1 produces valid `canonical_id`.
4. `ORDER_PROCESSING` event with same D1 + same fingerprint → DUPLICATE_NOOP.
5. `ORDER_PROCESSING` event with same D1 + different fingerprint → CONFLICT.
6. `ORDER_PROCESSING` does NOT mint Day38 lifecycle events.
7. `ORDER_PROCESSING` updates projection state correctly.

---

## 5. ORDER_PROCESSING Projection Semantics

### 5.1 The semantic question

When the provider says an order is "processing" (e.g. `validation pending`), what is the projection state?

**The projection state is NOT derived from the canonical event type.** It is derived from the provider status.

### 5.2 Projection state derivation rule

```
OrderFacts.status = f(provider_status)
```

Where `f` maps provider status to canonical order state:

| Provider status | `OrderFacts.status` | Rationale |
|---|---|---|
| `validation pending` | SUBMITTED | Order was received; submission evidence exists |
| `open pending` | SUBMITTED | Order was received; submission evidence exists |
| `trigger pending` | SUBMITTED | Order was received; submission evidence exists |
| `modify pending` | SUBMITTED | Order was submitted; modification in progress |
| `modify validation pending` | SUBMITTED | Order was submitted; modification in progress |
| `modified` | SUBMITTED | Order was submitted; modification applied |
| `not modified` | SUBMITTED | Order was submitted; modification failed |
| `cancel pending` | SUBMITTED | Order was submitted; cancellation in progress |
| `not cancelled` | SUBMITTED | Order was submitted; cancellation failed |
| `modify after market order req received` | SUBMITTED | Order was submitted; AMO modification in progress |
| `open` | OPEN | Broker reports order is working |
| `complete` | FILLED | Fully executed |
| `rejected` | REJECTED | Rejected by exchange |
| `cancelled` | CANCELLED | Cancelled |
| `cancelled after market order` | CANCELLED | Cancelled (AMO) |

### 5.3 Why SUBMITTED is correct for processing chatter

The provider status `validation pending` means "the order has been received and is awaiting validation." This implies the submission attempt was made. The order is in a post-submission, pre-acceptance processing state. `SUBMITTED` is the correct canonical order state because:

1. The submission attempt was observed (evidenced by the order being received).
2. The order is NOT yet accepted (that would be `OPEN`).
3. The order is NOT yet rejected/cancelled (those are terminal).

### 5.4 Distinction between submission and processing

| Concept | Provider evidence | Canonical event | Projection state |
|---|---|---|---|
| Order request submitted | `put order req received`, `after market order req received` | ORDER_SUBMITTED | SUBMITTED |
| Broker processing/validation | `validation pending`, `open pending`, `trigger pending`, `modify pending`, etc. | ORDER_PROCESSING | SUBMITTED |
| Broker accepted | `open` | ORDER_ACCEPTED | OPEN |
| Broker rejected | `rejected` | ORDER_REJECTED | REJECTED |
| Exchange/order lifecycle | `complete`, `cancelled`, etc. | FULL_FILL, ORDER_CANCELLED | FILLED, CANCELLED |

The canonical event preserves the provider observation. The projection state is derived from the provider status, NOT from the canonical event type.

---

## 6. Cross-Channel Fill Deduplication

### 6.1 The problem

The same economic fill may appear via multiple channels:
- STREAM trade feed (with `trade_id`)
- RECOVERY trade history (with `trade_id`)
- STREAM order-update (cumulative `filled_quantity` jump, no `trade_id`)
- RECOVERY order history (cumulative `filled_quantity`, no `trade_id`)

### 6.2 Fill equivalence key

The **fill equivalence key** is:

```
fill_eq_key = (tenant_id, broker, order_id, provider_trade_id_or_composite)
```

Where `provider_trade_id_or_composite` is:
1. **Preferred:** Provider `trade_id` (when available).
2. **Fallback:** Deterministic composite of `(order_id, event_timestamp, fill_quantity, fill_price)` — ONLY when `trade_id` is absent.

### 6.3 Equivalence rules

| Record A | Record B | Equivalence | Rule |
|---|---|---|---|
| trade with `trade_id=T1` | trade with `trade_id=T1` | **SAME FILL** | Same `trade_id` → same economic fill |
| trade with `trade_id=T1` | recovery with `trade_id=T1` | **SAME FILL** | Same `trade_id` → same economic fill |
| trade with `trade_id=T1` | order-update cum jump | **CANNOT PROVE** | Different identity; order-update is cumulative observation |
| order-update cum=20 | order-update cum=20 | **SAME OBSERVATION** | Same cumulative value; dedup by D1 |
| order-update cum=20 | order-update cum=50 | **DIFFERENT OBSERVATION** | Different cumulative value; different D1 |
| partial fill (qty=5) | partial fill (qty=5) | **SAME FILL** | Same composite key |
| partial fill (qty=5) | partial fill (qty=3) | **DIFFERENT FILL** | Different quantity; different composite key |
| corrected fill (price updated) | original fill | **CHANGED OBSERVATION** | Same D1, different fingerprint → CONFLICT |

### 6.4 Same fill via different channels

When the same fill (same `trade_id`) arrives via STREAM then RECOVERY:

1. Same D1 (same identity fields including `trade_id`).
2. Same `canonical_id`.
3. Same fingerprint (if content identical) → DUPLICATE_NOOP.
4. Different fingerprint (if content differs) → CONFLICT.

### 6.5 Changed observation of the same fill

When a fill is corrected (e.g. `average_price` updated):

1. Same D1 (same `trade_id`).
2. Same `canonical_id`.
3. Different fingerprint → CONFLICT.
4. Task2 decides: if correction is documented (e.g. `modified` status), accept and update. Otherwise quarantine.

### 6.6 Distinct fills

When two different fills occur (different `trade_id` or different composite):

1. Different D1.
2. Different `canonical_id`.
3. Both APPLIED.

### 6.7 Irreconcilable conflict

When two observations have the same D1 but irreconcilable content:

1. Same D1 → Same `canonical_id`.
2. Different fingerprint → CONFLICT.
3. Task2 quarantines (REJECTED with deterministic reason).
4. Recovery (later task) reconciles.

### 6.8 Schema requirement

The current schema (`broker_order_projection`) does NOT store a D2 set. To durably track "which fills have been applied," a new table is required:

```
broker_fill_ledger (
    tenant_id        str(128)  NOT NULL,
    order_id         str(64)   NOT NULL,          -- provider order id
    fill_eq_key      str(128)  NOT NULL,          -- trade_id or composite
    fill_quantity    int,
    fill_price       float,
    source_mode      str(32),
    applied_at       datetime  NOT NULL,
    PRIMARY KEY (tenant_id, order_id, fill_eq_key)
)
```

This is a REQUIRED prerequisite for cross-channel fill dedup.

---

## 7. D1 Field Review

### 7.1 Classification of each candidate field

| Field | Classification | Participates in D1? | Rationale |
|---|---|---|---|
| `tenant_id` | Identity | YES | Tenant scope |
| `broker` | Identity | YES | Broker scope |
| `order_id` (provider) | Identity | YES | Which provider order |
| `event_type` (canonical) | Identity | YES | What kind of observation |
| `provider_trade_id` | Identity | YES (fill events) | Which economic fill |
| `event_timestamp` | **Content** | NO | Provider-reported time — mutable for corrections |
| `order_status` (provider) | **Content** | NO | Provider-reported status — mutable |
| `filled_quantity` (provider) | **Content** | NO | Provider-reported quantity — mutable |
| `cancel_quantity` (provider) | **Content** | NO | Provider-reported quantity — mutable |
| `reject_reason` (provider) | **Content** | NO | Provider-reported reason — mutable |
| `average_price` | **Content** | NO | Provider-reported price — mutable |
| `source_mode` | **Provenance** | NO | How we received it |
| `received_at` | **Provenance** | NO | When we received it |

### 7.2 Why mutable fields are excluded from D1

Including mutable fields (like `average_price`, `event_timestamp`, `reject_reason`) in D1 causes:

```
Same provider fact observed twice with different content
→ Different D1
→ Different canonical_id
→ Both APPLIED (instead of CONFLICT)
→ Duplicate economic fills counted
```

This is the defect identified in Finding #2. The fix is to exclude ALL mutable content fields from D1.

### 7.3 Why `source_mode` is excluded from D1

`source_mode` is delivery provenance, not observation identity. The same provider fact received via STREAM and RECOVERY must produce the same D1 (so it dedups as DUPLICATE_NOOP, not two separate observations).

### 7.4 Why `event_timestamp` is excluded from D1

`event_timestamp` is provider-reported content. It can change for corrections. If included in D1, a corrected timestamp would produce a different D1 → different `canonical_id` → both APPLIED → duplicate.

### 7.5 Why `reject_reason` is excluded from D1

`reject_reason` is provider-reported content. It can change for corrections. Same reasoning as `event_timestamp`.

---

## 8. Deterministic Test Matrix

### 8.1 D1 identity tests

| Test | Input A | Input B | Expected D1 | Expected canonical_id |
|---|---|---|---|---|
| Same observation | Same fields | Same fields | Same | Same |
| Different `trade_id` | trade_id=T1 | trade_id=T2 | Different | Different |
| Different `order_id` | order_id=O1 | order_id=O2 | Different | Different |
| Different `event_type` | SUBMITTED | PROCESSING | Different | Different |
| Different `average_price` | avg=100 | avg=101 | **Same** | **Same** |
| Different `event_timestamp` | t=1000 | t=2000 | **Same** | **Same** |
| Different `source_mode` | STREAM | RECOVERY | **Same** | **Same** |
| Different `order_status` | validation pending | open pending | **Same** | **Same** |
| Different `filled_quantity` | filled=20 | filled=50 | **Same** | **Same** |

### 8.2 Idempotency tests

| Test | Scenario | Expected |
|---|---|---|
| Identical redelivery | Same D1, same fingerprint | DUPLICATE_NOOP |
| Same fact, different channel | Same D1, same fingerprint | DUPLICATE_NOOP |
| Same fact, corrected content | Same D1, different fingerprint | CONFLICT |
| Different facts | Different D1 | Both APPLIED |

### 8.3 Canonical event mapping tests

| Test | Provider status | Expected canonical event |
|---|---|---|
| Submission | `put order req received` | ORDER_SUBMITTED |
| Processing | `validation pending` | ORDER_PROCESSING |
| Processing | `open pending` | ORDER_PROCESSING |
| Processing | `modified` | ORDER_PROCESSING |
| Accepted | `open` | ORDER_ACCEPTED |
| Terminal fill | `complete` | FULL_FILL |
| Terminal rejection | `rejected` | ORDER_REJECTED |
| Terminal cancellation | `cancelled` | ORDER_CANCELLED |

### 8.4 Projection state tests

| Test | Provider status | Expected `OrderFacts.status` |
|---|---|---|
| Processing | `validation pending` | SUBMITTED |
| Processing | `open pending` | SUBMITTED |
| Processing | `modified` | SUBMITTED |
| Accepted | `open` | OPEN |
| Terminal | `complete` | FILLED |

### 8.5 Fill dedup tests

| Test | Scenario | Expected |
|---|---|---|
| Same `trade_id` via STREAM then RECOVERY | Same D1, same fingerprint | DUPLICATE_NOOP |
| Same `trade_id`, corrected price | Same D1, different fingerprint | CONFLICT |
| Different `trade_id` | Different D1 | Both APPLIED |
| No `trade_id`, same composite | Same D1, same fingerprint | DUPLICATE_NOOP |
| No `trade_id`, different composite | Different D1 | Both APPLIED |

---

## 9. Final Gate

### Day38
```
🟢 APPROVED — no changes required
```

### Task1
```
🟡 CONTRACT CHANGE REQUIRED — additive:
  - New enum value ORDER_PROCESSING
  - New _BROKER_TO_LIFECYCLE mapping (ORDER_PROCESSING → None)
  - New test coverage (7 tests)
  - Documentation update
  - No migration, no breaking changes
```

### Task3 Design
```
🟢 RESOLVED — all 8 findings addressed:
  1. Official status inventory corrected (17 values, no duplicates)
  2. D1 redesigned — identity/content/provenance separated
  3. Identity vs delivery provenance formalized
  4. ORDER_PROCESSING Task1 impact acknowledged
  5. ORDER_PROCESSING projection semantics defined
  6. Cross-channel fill dedup formalized
  7. D1 field review completed
  8. Deterministic test matrix provided
```

### Task3 Implementation
```
🔴 LOCKED — remains locked until:
  - Task1 ORDER_PROCESSING change is approved and implemented
  - broker_fill_ledger table migration is approved
  - broker_order_lifecycle_state table migration is approved
  - Lock-before-read ordering is implemented
  - Semantic fold (no id/received_at tiebreak) is implemented
```

### Foundation
```
🟢 RESOLVED — architecture is internally consistent and source-backed
```

---

## Appendix: Prerequisite List (Updated)

| ID | File/table | Current | Required | Schema | Migration | Blocking |
|---|---|---|---|---|---|---|
| PR-1 | `app/broker_sync/__init__.py` | No `ORDER_PROCESSING` | Add `ORDER_PROCESSING` enum value | NO | NO | YES |
| PR-2 | `app/broker_sync/ingestion.py` `_BROKER_TO_LIFECYCLE` | No `ORDER_PROCESSING` mapping | Add `ORDER_PROCESSING → None` | NO | NO | YES |
| PR-3 | `app/broker_sync/__init__.py` `provider_event_id` | Documented as "provider-native only" | Amend to "provider-native or D1" | NO | NO | YES |
| PR-4 | `app/broker_sync/ingestion.py` `_do_ingest` | Projection read before lock | Lock before mutable-state reads | NO | NO | YES |
| PR-5 | NEW `broker_fill_ledger` | No D2 set storage | Durable D2-set storage | YES | YES | YES |
| PR-6 | NEW `broker_order_lifecycle_state` | No per-order ownership | Durable per-order ownership | YES | YES | YES |
| PR-7 | `app/broker_sync/ingestion.py` `_build_projection` | `id.desc()` tiebreaker | Semantic fold | NO | NO | YES |
| PR-8 | `app/broker_sync/ingestion.py` `_build_projection` | `max(quantity)` | REPLACE on `modified` evidence only | NO | NO | YES |
| PR-9 | `app/broker_sync/ingestion.py` `_append_lifecycle_from_event` | No fill-first handling | Fill-first observation-only | NO | NO | YES |

---

## Git / Safety Verification (this session)

**Output:** ONLY this revised design memo.

**No production code modified. No implementation. No tests. No migration. No schema. No deployment. Protected files untouched.**
