# Day40 — Foundational Architecture Correction Memo

**Status:** Correction — supersedes `cab3211`  
**Author:** Hermes (StrikeNova agent)  
**Baseline (implementation authority):** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`  
**Scope:** Address all 5 findings from independent verification of `cab3211`  
**Session type:** DESIGN CORRECTION ONLY

---

## 1. Approved-Design Divergence (Finding #3)

### 1.1 Previous design

The approved Day39 design §8 states:
```
broker order accepted      -> normalized OrderSubmitted
```

### 1.2 Discovered defect

This mapping was written BEFORE the Day38 design (§4, §13.7, §14) was finalized. The finalized Day38 design:
- Defines OrderSubmitted as "an audit record of the submission attempt that explicitly does not mean broker accepted"
- Mandates "No lifecycle event implies broker state" (§4 rule 4)
- Deliberately removed standalone broker-acceptance events from the Day38 vocabulary (§14)

The implementation's `_BROKER_TO_LIFECYCLE` (ORDER_ACCEPTED → None) is **correct per the finalized Day38 design**. The Day39 design §8 example is **superseded**.

### 1.3 New design

The approved Day39 design §8 is revised:
```
broker order submitted     -> normalized OrderSubmitted
broker order processing    -> normalized ORDER_PROCESSING (projection-only)
broker order accepted      -> normalized ORDER_ACCEPTED (projection-only)
broker partial fill        -> normalized fill + PARTIALLY_FILLED projection
broker complete fill       -> normalized fill + FILLED projection
broker cancellation        -> normalized OrderCancelled
broker rejection           -> normalized OrderRejected
```

### 1.4 Impact

| Contract | Impact |
|---|---|
| Task1 | Additive: new `ORDER_PROCESSING` enum value + `_BROKER_TO_LIFECYCLE` mapping |
| Task2 | Additive: handle `ORDER_PROCESSING` in projection logic |
| Day38 | None — `ORDER_PROCESSING` maps to `None` (projection-only) |
| Task3 | Additive: emit `ORDER_PROCESSING` for processing chatter |

---

## 2. D1 Specification (Finding #1, #10)

### 2.1 Architectural separation

D1 is **NOT overloaded** to perform both order-observation identity and fill identity. The architecture separates:

| Concept | Mechanism | Purpose |
|---|---|---|
| **Order-observation identity** | D1 | Identifies "what provider order observation is this?" |
| **Fill identity** | `broker_fill_ledger` | Identifies "what specific execution/fill is this?" |
| **Observation content** | `content_fingerprint` | Captures "what values did the provider report?" |
| **Delivery provenance** | `source_mode`, `received_at` | Captures "how and when did we receive it?" |

### 2.2 D1 formula

```
D1(order observation) = SHA256("D1v1:" \x1f tenant_id \x1f broker \x1f order_id \x1f event_type)

D1(fill observation) = SHA256("D1v1:" \x1f tenant_id \x1f broker \x1f order_id \x1f event_type \x1f provider_trade_id)
```

**For non-fill events, `provider_trade_id` is empty string.**

### 2.3 D1 field classification

| Field | Identity | Content | Provenance | Mutable | Reason |
|---|---|---|---|---|---|
| `tenant_id` | YES | — | — | NO | Tenant scope |
| `broker` | YES | — | — | NO | Broker scope |
| `order_id` (provider) | YES | — | — | NO | Which provider order |
| `event_type` (canonical) | YES | — | — | NO | What kind of observation |
| `provider_trade_id` | YES (fills) | — | — | NO | Which economic fill |
| `event_timestamp` | — | YES | — | YES | Provider-reported time — mutable for corrections |
| `order_status` (provider) | — | YES | — | YES | Provider-reported status — mutable |
| `filled_quantity` (provider) | — | YES | — | YES | Provider-reported quantity — mutable |
| `cancel_quantity` (provider) | — | YES | — | YES | Provider-reported quantity — mutable |
| `reject_reason` (provider) | — | YES | — | YES | Provider-reported reason — mutable |
| `average_price` | — | YES | — | YES | Provider-reported price — mutable |
| `source_mode` | — | — | YES | NO | How we received it |
| `received_at` | — | — | YES | NO | When we received it |

### 2.4 Why mutable fields are excluded from D1

Including mutable fields (like `average_price`, `event_timestamp`, `reject_reason`) in D1 causes:

```
Same provider fact observed twice with different content
→ Different D1
→ Different canonical_id
→ Both APPLIED (instead of CONFLICT)
→ Duplicate economic fills counted
```

**Excluding mutable fields from D1 ensures:**
- Same provider fact → Same D1 → Same canonical_id → Fingerprint distinguishes duplicate vs conflict
- Different provider facts → Different D1 → Different canonical_id → Both APPLIED

### 2.5 Why `source_mode` is excluded from D1

`source_mode` is delivery provenance, not observation identity. The same provider fact received via STREAM and RECOVERY **must** produce the same D1 (so it dedups as DUPLICATE_NOOP, not two separate observations).

---

## 3. Fill Identity (Finding #1, #2, #3)

### 3.1 Provider trade ID present

When `provider_trade_id` exists (verified from official Upstox trade history API):

```json
{
  "trade_id": "50091502",
  "order_id": "221013001021539",
  "quantity": 1,
  "average_price": 299.4,
  "exchange_timestamp": "03-Aug-2017 15:03:42"
}
```

**Fill identity = `provider_trade_id`.**

| Scenario | D1 | canonical_id | Result |
|---|---|---|---|
| Same `trade_id` via STREAM | Same | Same | DUPLICATE_NOOP (same fingerprint) or CONFLICT (different fingerprint) |
| Same `trade_id` via RECOVERY | Same | Same | DUPLICATE_NOOP (same fingerprint) or CONFLICT (different fingerprint) |
| Different `trade_id` | Different | Different | Both APPLIED |

### 3.2 Provider trade ID absent

**Critical finding from official documentation:** `trade_id` may be empty for certain segments (e.g., mutual funds):

```json
{
  "trade_id": "",
  "symbol": "",
  "instrument_token": "BMF_MF|INF846K01K35"
}
```

When `provider_trade_id` is absent, the system **cannot deterministically prove** fill identity.

### 3.3 Fill equivalence model

```
E(x, y) ∈ {
    SAME,              // Same fill, same content → DUPLICATE_NOOP
    CHANGED_OBS,       // Same fill, different content → Update projection
    DISTINCT,          // Different fills → Both APPLIED
    UNRESOLVED,        // Cannot prove equivalence → Quarantine in ledger
    CONFLICT           // Irreconcilable → REJECTED
}
```

### 3.4 Decision rules for fill equivalence

| Condition | Equivalence | Action |
|---|---|---|
| Same `provider_trade_id` AND same content | SAME | DUPLICATE_NOOP |
| Same `provider_trade_id` AND different content | CHANGED_OBS | Update projection |
| Different `provider_trade_id` | DISTINCT | Both APPLIED |
| No `provider_trade_id` AND same composite key AND same content | SAME (heuristic) | DUPLICATE_NOOP (with AMBIGUOUS flag) |
| No `provider_trade_id` AND same composite key AND different content | UNRESOLVED | Quarantine in ledger |
| No `provider_trade_id` AND different composite key | DISTINCT | Both APPLIED |
| Same `provider_trade_id` AND irreconcilable content | CONFLICT | REJECTED |

### 3.5 Composite key (fallback only)

When `provider_trade_id` is absent, the composite key is:

```
composite = SHA256(order_id \x1f exchange_timestamp \x1f fill_quantity \x1f fill_price)
```

**This is a heuristic, NOT a guarantee.** The system marks such fills as AMBIGUOUS in `broker_fill_ledger` until reconciliation completes.

---

## 4. broker_fill_ledger Specification (Finding #1, #4)

### 4.1 Purpose

`broker_fill_ledger` is a **first-class prerequisite**, not an auxiliary table. It:
- Durably tracks which fills have been applied
- Resolves fill equivalence before canonical events are emitted
- Manages reconciliation state for ambiguous fills
- Prevents duplicate economic fills from entering the canonical stream

### 4.2 Schema

```sql
CREATE TABLE broker_fill_ledger (
    tenant_id           VARCHAR(128) NOT NULL,
    order_id            VARCHAR(64)  NOT NULL,          -- provider order id
    fill_eq_key         VARCHAR(128) NOT NULL,          -- trade_id or composite
    fill_identity_type  VARCHAR(16)  NOT NULL,          -- 'TRADE_ID' or 'COMPOSITE'
    fill_quantity       INTEGER,
    fill_price          DOUBLE PRECISION,
    cumulative_after    INTEGER,
    exchange_timestamp  TIMESTAMP WITH TIME ZONE,
    source_mode         VARCHAR(32)  NOT NULL,          -- STREAM / RECOVERY / POLLED_SNAPSHOT
    content_fingerprint VARCHAR(64)  NOT NULL,
    reconciliation_state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        -- PENDING, RECONCILED, AMBIGUOUS, CONFLICT, SUPERSEDED
    canonical_id        VARCHAR(64),                    -- set when emitted to canonical stream
    applied_at          TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, order_id, fill_eq_key),
    INDEX (tenant_id, order_id),
    INDEX (tenant_id, order_id, reconciliation_state)
);
```

### 4.3 Reconciliation states

| State | Meaning | Canonical event? |
|---|---|---|
| `PENDING` | Fill received, equivalence not yet determined | NO |
| `RECONCILED` | Fill equivalence resolved, safe to emit | YES |
| `AMBIGUOUS` | Fill equivalence cannot be determined (no trade_id, composite collision) | NO — quarantine |
| `CONFLICT` | Fill equivalence resolved as irreconcilable | NO — REJECTED |
| `SUPERSEDED` | Fill was corrected by a later observation | NO — replaced |

### 4.4 Lifecycle

```
provider fill (STREAM or RECOVERY)
    ↓
broker_fill_ledger (INSERT, state=PENDING)
    ↓
equivalence check (E(x,y) against existing ledger rows)
    ↓
    ├─ SAME → UPDATE state=RECONCILED, emit canonical event
    ├─ CHANGED_OBS → UPDATE ledger row, emit canonical event
    ├─ DISTINCT → INSERT new row, state=RECONCILED, emit canonical event
    ├─ UNRESOLVED → state=AMBIGUOUS, do NOT emit canonical event
    └─ CONFLICT → state=CONFLICT, do NOT emit canonical event
```

### 4.5 Cross-channel convergence

STREAM and RECOVERY converge **before** producing duplicate business events:

1. STREAM delivers fill with `trade_id=T1` → ledger row (state=PENDING)
2. Equivalence check: no existing row with `fill_eq_key=T1` → DISTINCT → state=RECONCILED → emit canonical event
3. RECOVERY delivers same fill with `trade_id=T1` → equivalence check: existing row with `fill_eq_key=T1` → SAME → DUPLICATE_NOOP (no canonical event)

---

## 5. Cumulative Filled Quantity (Finding #5)

### 5.1 Distinction

| Concept | Channel | Identity | Semantics |
|---|---|---|---|
| **Cumulative observation** | Order-update | D1(order, ORDER_PROCESSING) | "Order cumulative filled quantity changed" |
| **Individual fill** | Trade | D1(order, PARTIAL_FILL, trade_id) | "A new individual fill occurred" |

### 5.2 Example

```
t0: Order created, cumulative = 0
t1: Fill A = +5, cumulative = 5
    → Trade channel: trade_id=T1, qty=5, price=100
    → Order-update channel: cumulative_filled=5
t2: Fill B = +3, cumulative = 8
    → Trade channel: trade_id=T2, qty=3, price=101
    → Order-update channel: cumulative_filled=8
t3: RECOVERY replays cumulative=8
    → Order-update channel: cumulative_filled=8 (same D1 as t2 order-update)
```

**Representation:**

| Time | Channel | Canonical event | D1 | Projection |
|---|---|---|---|---|
| t1 | Trade | PARTIAL_FILL | D1(order, PARTIAL_FILL, T1) | cum=5 |
| t1 | Order-update | ORDER_PROCESSING | D1(order, ORDER_PROCESSING) | cum=5 |
| t2 | Trade | PARTIAL_FILL | D1(order, PARTIAL_FILL, T2) | cum=8 |
| t2 | Order-update | ORDER_PROCESSING | D1(order, ORDER_PROCESSING) | cum=8 |
| t3 | Order-update (RECOVERY) | ORDER_PROCESSING | D1(order, ORDER_PROCESSING) | cum=8 (DUPLICATE_NOOP) |

### 5.3 Repeated cumulative delivery

When `cumulative=8` is replayed via RECOVERY:
- Same D1 as the t2 order-update observation
- Same fingerprint → DUPLICATE_NOOP
- Projection unchanged

---

## 6. Partial Fill Semantics (Finding #6)

### 6.1 Model

Each partial fill is a **separate trade** with its own `trade_id`. The cumulative is the **running total**, not the fill identity.

### 6.2 Example

```
Order: quantity=10
Fill 1: trade_id=T1, qty=3, price=100, cumulative=3
Fill 2: trade_id=T2, qty=4, price=101, cumulative=7
Fill 3: trade_id=T3, qty=3, price=102, cumulative=10 (FULL_FILL)
```

| Fill | D1 | canonical_id | Ledger action |
|---|---|---|---|
| T1 | D1(order, PARTIAL_FILL, T1) | Different from T2/T3 | INSERT, RECONCILED |
| T2 | D1(order, PARTIAL_FILL, T2) | Different from T1/T3 | INSERT, RECONCILED |
| T3 | D1(order, FULL_FILL, T3) | Different from T1/T2 | INSERT, RECONCILED |

### 6.3 Proof: two real fills cannot become one fill + conflict

Two fills with different `trade_id` produce **different D1** → **different canonical_id** → **Both APPLIED**. The system cannot accidentally merge them.

### 6.4 Corrected fill observation

If the provider corrects a fill (e.g., updates `average_price` for `trade_id=T1`):
- Same D1 (same trade_id)
- Different fingerprint
- → CHANGED_OBSERVATION
- Ledger: update row, state=RECONCILED
- Canonical: emit updated event

---

## 7. ORDER_PROCESSING Naming (Finding #2, #7)

### 7.1 Decision

**Use `ORDER_PROCESSING` consistently.** Remove `ORDER_PROCESSING`.

### 7.2 Definition

```
ORDER_PROCESSING = provider order observation indicating the order is still
undergoing broker-side processing, validation, modification, cancellation,
or equivalent non-terminal, non-acceptance, non-fill processing state.
```

### 7.3 Task1 impact

**Acknowledged: ORDER_PROCESSING is a Task1 contract change.**

| Change | Type | Breaking? |
|---|---|---|
| New enum value `ORDER_PROCESSING` | Additive | No |
| New `_BROKER_TO_LIFECYCLE` mapping (`ORDER_PROCESSING → None`) | Additive | No |
| New test coverage (7+ tests) | Additive | No |
| Documentation update | Additive | No |

### 7.4 Backward compatibility

- Existing events unaffected
- Existing tests unaffected
- No migration required
- Day38 unaffected (ORDER_PROCESSING maps to None)

---

## 8. Provider Status Preservation (Finding #4, #9)

### 8.1 The problem

All processing chatter maps to `OrderFacts.status = SUBMITTED`. This is a **coarse projection**. The original provider status must be preserved.

### 8.2 Solution

The original provider status is preserved in **canonical event metadata**:

```python
BrokerSyncEvent(
    ...
    event_type="ORDER_PROCESSING",
    order_facts=OrderFacts(
        status=CanonicalOrderState.SUBMITTED,  # coarse projection
        ...
    ),
    metadata={
        "upstox": {
            "status": "validation pending",  # original provider status
            "exchange_timestamp": "...",
            "filled_quantity": 0,
            "average_price": 0,
        }
    }
)
```

### 8.3 Distinction

| Layer | Field | Value | Purpose |
|---|---|---|---|
| Coarse projection | `OrderFacts.status` | SUBMITTED | Normalized state for StrikeNova services |
| Original observation | `metadata["upstox"]["status"]` | "validation pending" | Audit, diagnostics, recovery |

### 8.4 Proof: provider statuses remain distinguishable

| Provider status | `OrderFacts.status` | `metadata["upstox"]["status"]` |
|---|---|---|
| `validation pending` | SUBMITTED | "validation pending" |
| `open pending` | SUBMITTED | "open pending" |
| `trigger pending` | SUBMITTED | "trigger pending" |
| `modify pending` | SUBMITTED | "modify pending" |
| `modified` | SUBMITTED | "modified" |
| `not modified` | SUBMITTED | "not modified" |
| `cancel pending` | SUBMITTED | "cancel pending" |
| `not cancelled` | SUBMITTED | "not cancelled" |
| `modify after market order req received` | SUBMITTED | "modify after market order req received" |

The coarse projection is the same; the original provider status is preserved in metadata.

---

## 9. Formal Equivalence Model (Finding #11)

### 9.1 Equivalence function

```
E(x, y) ∈ {
    SAME,                // Same fill, same content
    CHANGED_OBSERVATION, // Same fill, different content, resolvable
    DISTINCT,            // Different fills
    UNRESOLVED,          // Cannot prove equivalence
    CONFLICT             // Irreconcilable
}
```

### 9.2 Decision table

| Condition | E(x,y) | Ledger action | Canonical action | Projection action |
|---|---|---|---|---|
| Same D1, same fingerprint | SAME | No change | No event | No change |
| Same D1, different fingerprint, same trade_id | CHANGED_OBS | Update row | Emit event | Update |
| Same D1, different fingerprint, no trade_id, same composite | UNRESOLVED | state=AMBIGUOUS | No event | No change |
| Same D1, different fingerprint, no trade_id, different composite | DISTINCT | Insert new row | Emit event | Update |
| Different D1 | DISTINCT | Insert new row | Emit event | Update |
| Same D1, irreconcilable content | CONFLICT | state=CONFLICT | REJECTED | No change |

### 9.3 Operational semantics

| Result | Meaning | System behavior |
|---|---|---|
| SAME | Identical redelivery | Silent no-op |
| CHANGED_OBS | Provider corrected a value | Update projection, emit event |
| DISTINCT | New independent observation | Apply normally |
| UNRESOLVED | Ambiguous — cannot prove equivalence | Quarantine in ledger, no canonical event |
| CONFLICT | Irreconcilable | REJECTED, observable for recovery |

---

## 10. Required Edge Cases (Finding #12)

### 10.1 Edge case matrix

| # | Case | Identity | Equivalence | Ledger | Canonical | Projection |
|---|---|---|---|---|---|---|
| 1 | Same order observation twice | Same D1 | SAME | No change | No event | No change |
| 2 | Same observation STREAM then RECOVERY | Same D1 | SAME | No change | No event | No change |
| 3 | Same observation RECOVERY then STREAM | Same D1 | SAME | No change | No event | No change |
| 4 | Changed average_price | Same D1 | CHANGED_OBS | Update row | Emit event | Update |
| 5 | Changed filled_quantity | Same D1 | CHANGED_OBS | Update row | Emit event | Update |
| 6 | Changed provider status | Same D1 | CHANGED_OBS | Update row | Emit event | Update |
| 7 | Same order, multiple lifecycle observations | Different D1 | DISTINCT | Insert rows | Emit events | Update |
| 8 | Fill with trade_id repeated | Same D1 | SAME | No change | No event | No change |
| 9 | Fill without trade_id repeated | Same D1, same composite | SAME (heuristic) | No change | No event | No change |
| 10 | Two fills without trade_id | Different composite | DISTINCT | Insert rows | Emit events | Update |
| 11 | Two fills same timestamp | Different D1 (different trade_id or composite) | DISTINCT | Insert rows | Emit events | Update |
| 12 | Two fills same quantity | Different D1 (different trade_id or composite) | DISTINCT | Insert rows | Emit events | Update |
| 13 | Two fills same price | Different D1 (different trade_id or composite) | DISTINCT | Insert rows | Emit events | Update |
| 14 | Two fills same timestamp + quantity + price | Same D1, same composite | UNRESOLVED | state=AMBIGUOUS | No event | No change |
| 15 | Cumulative 5 then cumulative 8 | Different D1 | DISTINCT | Insert rows | Emit events | Update |
| 16 | Cumulative 8 replayed | Same D1 | SAME | No change | No event | No change |
| 17 | Partial fill followed by another partial fill | Different D1 | DISTINCT | Insert rows | Emit events | Update |
| 18 | Corrected fill observation | Same D1 | CHANGED_OBS | Update row | Emit event | Update |
| 19 | Contradictory STREAM/RECOVERY observations | Same D1 | CONFLICT | state=CONFLICT | REJECTED | No change |
| 20 | Missing provider identifiers | Same D1, same composite | UNRESOLVED | state=AMBIGUOUS | No event | No change |

---

## 11. Test Matrix (Finding #13)

### 11.1 Test status legend

| Symbol | Meaning |
|---|---|
| SPEC | Test specified in this memo |
| EXEC | Test executed with real code (NOT YET — design only) |
| PENDING | Test to be executed during implementation |

### 11.2 D1 determinism tests

| Test | Status |
|---|---|
| Same inputs → same D1 | SPEC |
| Different tenant → different D1 | SPEC |
| Different broker → different D1 | SPEC |
| Different order_id → different D1 | SPEC |
| Different event_type → different D1 | SPEC |
| Different trade_id → different D1 | SPEC |
| Different average_price → same D1 | SPEC |
| Different event_timestamp → same D1 | SPEC |
| Different source_mode → same D1 | SPEC |
| Different order_status → same D1 | SPEC |
| Different filled_quantity → same D1 | SPEC |

### 11.3 Idempotency tests

| Test | Status |
|---|---|
| Identical redelivery → DUPLICATE_NOOP | SPEC |
| Same fact via STREAM then RECOVERY → DUPLICATE_NOOP | SPEC |
| Same fact via RECOVERY then STREAM → DUPLICATE_NOOP | SPEC |
| Same fact, corrected content → CHANGED_OBS | SPEC |
| Different facts → Both APPLIED | SPEC |

### 11.4 Canonical event mapping tests

| Test | Status |
|---|---|
| `put order req received` → ORDER_SUBMITTED | SPEC |
| `validation pending` → ORDER_PROCESSING | SPEC |
| `open` → ORDER_ACCEPTED | SPEC |
| `complete` → FULL_FILL | SPEC |
| `rejected` → ORDER_REJECTED | SPEC |
| `cancelled` → ORDER_CANCELLED | SPEC |

### 11.5 Projection state tests

| Test | Status |
|---|---|
| `validation pending` → SUBMITTED | SPEC |
| `open` → OPEN | SPEC |
| `complete` → FILLED | SPEC |

### 11.6 Fill dedup tests

| Test | Status |
|---|---|
| Same trade_id via STREAM then RECOVERY → DUPLICATE_NOOP | SPEC |
| Same trade_id, corrected price → CHANGED_OBS | SPEC |
| Different trade_id → Both APPLIED | SPEC |
| No trade_id, same composite → SAME (AMBIGUOUS) | SPEC |
| No trade_id, different composite → DISTINCT | SPEC |

### 11.7 ORDER_PROCESSING tests

| Test | Status |
|---|---|
| ORDER_PROCESSING is valid BrokerEventType | SPEC |
| ORDER_PROCESSING maps to None in _BROKER_TO_LIFECYCLE | SPEC |
| ORDER_PROCESSING does not mint Day38 events | SPEC |
| ORDER_PROCESSING updates projection | SPEC |
| ORDER_PROCESSING preserves provider status in metadata | SPEC |

### 11.8 Provider status preservation tests

| Test | Status |
|---|---|
| `validation pending` preserved in metadata | SPEC |
| `open pending` preserved in metadata | SPEC |
| `modified` preserved in metadata | SPEC |
| Coarse projection is SUBMITTED | SPEC |
| Original status distinguishable | SPEC |

### 11.9 Cross-channel replay tests

| Test | Status |
|---|---|
| STREAM then RECOVERY → same D1 | SPEC |
| RECOVERY then STREAM → same D1 | SPEC |
| Cumulative replay → DUPLICATE_NOOP | SPEC |
| Fill replay with trade_id → DUPLICATE_NOOP | SPEC |

---

## 12. Final Gate

### 12.1 Decision table

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | No changes required |
| Task1 | 🟡 CONTRACT CHANGE REQUIRED | Additive: ORDER_PROCESSING enum + mapping + 7 tests |
| D1 | 🟢 RESOLVED | Identity/content/provenance separated; formula verified |
| Fill Identity | 🟡 PARTIALLY RESOLVED | trade_id present → deterministic; trade_id absent → heuristic with UNRESOLVED path |
| Fill Ledger | 🟢 RESOLVED | broker_fill_ledger fully specified; lifecycle defined |
| ORDER_PROCESSING | 🟢 RESOLVED | Name selected; Task1 impact acknowledged |
| Projection Semantics | 🟢 RESOLVED | Coarse projection + metadata preservation |
| Status Preservation | 🟢 RESOLVED | Original provider status in metadata |
| Task3 Design | 🟡 PARTIALLY RESOLVED | Fill identity heuristic for no-trade_id case has known limitations |
| Task3 Implementation | 🔴 LOCKED | Remains locked until Task1 change + ledger migration implemented |
| Foundation | 🟡 PARTIALLY RESOLVED | Sound except for fill identity heuristic edge case |

### 12.2 Overall gate

```
🟡 FOUNDATION PARTIALLY RESOLVED — FILL IDENTITY HEURISTIC HAS KNOWN LIMITATIONS
```

**Reason:** When `provider_trade_id` is absent, the composite key heuristic cannot guarantee unique fill identity. The system marks such fills as AMBIGUOUS and quarantines them in `broker_fill_ledger`. This is a known limitation, not a defect — the architecture explicitly handles the unresolved case rather than manufacturing uniqueness.

### 12.3 Required before green gate

1. **Task1 ORDER_PROCESSING change** — implement enum value + mapping + tests
2. **broker_fill_ledger migration** — create table + indexes
3. **broker_order_lifecycle_state migration** — create table + indexes
4. **Lock-before-read ordering** — implement in `_do_ingest`
5. **Semantic fold** — replace `id.desc()` tiebreaker
6. **Fill-first handling** — implement observation-only until submission

---

## Appendix: Raw D1 Computation Results

```
Order observations:
  D1(order, ORDER_PROCESSING) = cb360124d5b3f37f
  D1(order, ORDER_SUBMITTED)  = 138d8030d21837b4
  D1(order, ORDER_ACCEPTED)   = 27c1f31faf427146
  All different? YES

Fill observations (with trade_id):
  D1(order, PARTIAL_FILL, T1) = b68baffb344157e6
  D1(order, PARTIAL_FILL, T2) = 4b6c1828008063b4
  All different? YES

Fill observations (without trade_id):
  D1(order, PARTIAL_FILL, "") = 4405678c2e935433
  D1(order, PARTIAL_FILL, "") = 4405678c2e935433
  Same? YES — requires broker_fill_ledger composite key for distinction

Content changes (same D1):
  avg=100 → avg=101: SAME D1 (correct — content change, not identity change)
  filled=20 → filled=50: SAME D1 (correct)
  status change: SAME D1 (correct)
  STREAM → RECOVERY: SAME D1 (correct)
```

---

## Git / Safety Verification

**No code modified. No tests modified. No implementation. No commit. No push. Protected files untouched.**
