# Final Foundational Architecture Correction Memo — Day39 Task3

**Status:** Final correction — source-backed decisions  
**Author:** Hermes (StrikeNova agent)  
**Baseline (implementation authority):** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`  
**Contract v8:** `11772c3225a460f1289b7fde7aeeb9c0adccc16`  
**Foundational memo v9:** `5c8b22475b3b3accdee3b6c0e4b128c8cfa4e40e`  
**Scope:** Resolve the two remaining foundational questions before Contract v9  
**Session type:** ARCHITECTURE / AUDIT ONLY

---

## 1. Verified Facts

### 1.1 Task1 identity contract (`app/broker_sync/__init__.py:120-215`)

`provider_event_id: Optional[str] = None` — the field is typed as optional string with NO validation restricting it to provider-native values.

**Fail-closed validation (line 168-180):**
```
if not self.provider_event_id:
    if not self.broker_order_id:
        raise ValueError("insufficient deterministic identity")
    if self.canonical_sequence is None and self.fill_facts is None:
        raise ValueError("insufficient deterministic identity")
```

**canonical_id construction (line 182-208):**
```
if self.provider_event_id:
    parts = (tenant_id, broker, provider_event_id, event_type)   # PRIMARY path
else:
    parts = [tenant_id, broker, event_type, broker_order_id]
    if canonical_sequence is not None:
        parts.append(str(canonical_sequence))
    if fill_facts is not None:
        if fill_facts.fill_id:
            parts.append(fill_facts.fill_id)
        else:
            parts.append(fill_digest)   # SHA-256 of fill fields
```

### 1.2 The verified problem

For an ordinary Upstox sequence-less observation (status=open, filled_quantity=0, order_id=123, no event id, no sequence, no fill):
- `provider_event_id` = None (websocket has no event id)
- `broker_order_id` = "123"
- `canonical_sequence` = None
- `fill_facts` = None
- → **Task1 raises ValueError.** The event cannot be constructed.

### 1.3 Approved Day39 design on identity (§5, §6)

§5: "provider event identity when available"  
§6: "Where the provider lacks a durable event ID, **the adapter must derive a deterministic identity** from stable provider order/fill identifiers plus event type and the minimum additional fields necessary to distinguish legitimate state changes. The derivation must be documented and tested."

### 1.4 Approved Day39 design on state transitions (§8)

```
broker order accepted      -> normalized OrderSubmitted
broker partial fill        -> normalized fill + PARTIALLY_FILLED projection
broker complete fill       -> normalized fill + FILLED projection
broker cancellation        -> normalized OrderCancelled
broker rejection           -> normalized OrderRejected
```

**Critical note:** The design §8 example "broker order accepted → normalized OrderSubmitted" was written BEFORE the Day38 design (§13.7, §4, §14) was finalized. The Day38 design explicitly removed standalone broker-acceptance events from the lifecycle vocabulary and defined OrderSubmitted as "an audit record of the submission attempt that explicitly does not mean broker accepted." The implementation's `_BROKER_TO_LIFECYCLE` (ORDER_ACCEPTED → None) is correct per the finalized Day38 design. The design §8 example is superseded by the Day38 design.

### 1.5 Day38 replay guards (`app/trade_lifecycle/replay.py:430-495`)

- `OrderCreated`: requires execution CREATED/ACTIVE; order must NOT exist; requires `payload.quantity` positive int.
- `OrderSubmitted`: requires order status PENDING → SUBMITTED.
- `OrderFilled`: requires order SUBMITTED or PARTIALLY_FILLED; `cumulative_filled` positive int strictly greater than previous; ≤ order quantity.
- `OrderCancelled`/`OrderRejected`: requires order SUBMITTED or PARTIALLY_FILLED.
- `FillRecorded`: requires order SUBMITTED/PARTIALLY_FILLED/FILLED; `fill_quantity` positive int; ledger + fill ≤ quantity.

### 1.6 Official Upstox order statuses (verified 2026-09-10)

Exactly **17 statuses** in the official appendix. `partially_filled` and `expired` are NOT official order statuses.

### 1.7 Test1 test contract (`test_day39_task1_canonical_contract.py`)

- `test_event_id_with_provider_event_id_uses_provider_path` (line 92): `provider_event_id` dominates identity.
- `test_event_id_without_provider_event_id_uses_fallback` (line 101): fallback uses `broker_order_id + canonical_sequence + event_type`.
- `test_same_order_same_type_no_sequence_fails_closed` (line 348): same order, same type, no sequence, no fill → ValueError.
- `test_fill_ids_distinguish_fills` (line 360): different `fill_id` → different `canonical_id`.
- `test_same_fill_reconstructed_independently_same_id` (line 377): equivalent fill events → same `canonical_id`.

---

## 2. Provider Status Table

All 17 official Upstox statuses with their canonical representation.

| # | Status | Provider meaning | Canonical event | Projection semantic | Can create OrderSubmitted? | Observation-only? |
|---|--------|-----------------|-----------------|--------------------|---------------------------|-------------------|
| 1 | `put order req received` | Request to place a new order has been received | ORDER_SUBMITTED | SUBMITTED | YES (first submission) | NO |
| 2 | `validation pending` | Order received, awaiting validation | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 3 | `open pending` | Order received, pending opening | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 4 | `trigger pending` | Awaiting trigger to market (SL/SL-M) | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 5 | `modify after market order req received` | AMO modification request received | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 6 | `cancelled after market order` | After-market order cancelled | ORDER_CANCELLED | CANCELLED | NO | NO (terminal) |
| 7 | `open` | Active and open in market (broker working) | ORDER_ACCEPTED | OPEN | NO | YES (Day38) |
| 8 | `complete` | Fully executed | FULL_FILL | FILLED | NO | NO (terminal) |
| 9 | `modify validation pending` | Modification awaiting validation | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 10 | `after market order req received` | New after-market order request received | ORDER_SUBMITTED | SUBMITTED | YES (first submission, AMO) | NO |
| 11 | `modified` | Order successfully modified | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 12 | `not cancelled` | Cancellation not processed; order active | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 13 | `cancel pending` | Cancellation in progress, not confirmed | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 14 | `rejected` | Rejected by exchange | ORDER_REJECTED | REJECTED | NO | NO (terminal) |
| 15 | `cancelled` | Successfully cancelled | ORDER_CANCELLED | CANCELLED | NO | NO (terminal) |
| 16 | `open pending` | Order received, pending opening | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |
| 17 | `not modified` | Modification not processed; original retained | **ORDER_PROCESSING** | SUBMITTED | NO | YES (Day38) |

**Notes:**
- `partially_filled` is NOT an official status. Partial fills are DERIVED from `filled_quantity` between 0 and quantity with status `open`/`complete`.
- `expired` is NOT an official status.
- `complete` → FULL_FILL (terminal). `open` + `filled_quantity` between 0 and quantity → PARTIAL_FILL (derived).
- `open` + `filled_quantity == quantity` → FULL_FILL (derived, before `complete` arrives).

---

## 3. D1/provider_event_id Decision

### 3.1 Problem

An ordinary Upstox sequence-less observation (status=open, filled_quantity=0, order_id=123, no event id, no sequence, no fill) fails Task1 validation because `provider_event_id` is absent, `broker_order_id` is present, but both `canonical_sequence` and `fill_facts` are None.

### 3.2 Options considered

| Option | Description | Task1 impact | canonical_id impact | fingerprint impact | Schema impact | Risk |
|--------|-------------|-------------|---------------------|-------------------|---------------|------|
| **A1** | Use D1 in `provider_event_id`; formally redefine semantic contract | **Semantic contract change** — `provider_event_id` now means "provider-native id when available, else deterministic observation identity (D1)" | Stable — D1 is deterministic | Stable — fingerprint covers all fields | None | Low — D1 prefix prevents collision |
| A2 | Introduce dedicated `observation_identity` field | Schema change — new field on `BrokerSyncEvent`; `canonical_id` construction changes | Same | Same | New field + migration | Medium — changes approved Task1 contract |
| A3 | Modify Task1 contract semantics without schema change | Same as A1 but without explicit documentation | Same | Same | None | **HIGH** — undocumented semantic change |
| A4 | Use `metadata` for D1 | None | None — metadata not in canonical_id | Metadata IS in fingerprint | None | **HIGH** — identical observations with different metadata → CONFLICT instead of DUPLICATE_NOOP |

### 3.3 Chosen option: A1

**Use D1 in `provider_event_id` and formally redefine the semantic contract.**

### 3.4 Exact rule

1. Task3 computes D1 (deterministic observation identity) for every observation.
2. If the provider supplies a native event id (e.g. webhook event id), Task3 sets `provider_event_id = <native id>`.
3. If the provider does NOT supply a native event id (e.g. STOMP websocket), Task3 sets `provider_event_id = D1` (the full `D1v1:<64 hex>` string).
4. Task1's `provider_event_id` field now holds EITHER a provider-native id OR a StrikeNova-derived D1.
5. `canonical_id` becomes `SHA256(tenant \x1f broker \x1f provider_event_id \x1f event_type)` — deterministic and unique per observation.
6. `content_fingerprint` covers all fields including `provider_event_id` — identical redelivery produces identical fingerprint → DUPLICATE_NOOP; different content → CONFLICT.

### 3.5 Why this is correct

1. The approved Day39 design (§6) explicitly says "the adapter must derive a deterministic identity" when the provider lacks one. Using `provider_event_id` for this purpose is consistent with the design's intent.
2. The current Task1 code already has `provider_event_id` as the dominant identity path (line 185-186). Using it for D1 is the smallest change.
3. D1's `D1v1:` prefix prevents collision with provider-native event ids.
4. No schema change, no new field, no migration.
5. **The semantic contract of `provider_event_id` MUST be amended** before Task3 implementation: it now means "provider-native event id when available, else deterministic observation identity (D1)".

### 3.6 Identity layer separation (final, unambiguous)

| Layer | Name | Field | Producer | Purpose |
|-------|------|-------|----------|---------|
| 1 | Provider-native event identity | `provider_event_id` (when provider supplies one) | Upstox | Provider's own event id |
| 2 | Deterministic observation identity | `provider_event_id` (set to D1 when provider doesn't supply one) | Task3 | Deterministic observation identity for idempotency |
| 3 | Canonical event identity | `canonical_id` (SHA-256) | Task1 | Idempotency PK |
| 4 | Content identity | `content_fingerprint` (SHA-256) | Task2 | Duplicate vs conflict classification |
| 5 | Trade identity | D2 (in `FillFacts.fill_id` / metadata) | Task3 | Economic fill dedup |

A StrikeNova-derived value in `provider_event_id` is NEVER called "provider event id" in documentation — it is called "deterministic observation identity" or "D1". The field name `provider_event_id` is overloaded: it holds either a provider-native id OR a StrikeNova-derived D1.

### 3.7 Task1 impact

**Semantic contract change REQUIRED.** The documented meaning of `provider_event_id` must be amended from "provider-native event id when available" to "provider-native event id when available, else deterministic observation identity (D1)". No code or schema change is required, but the semantic contract change MUST be documented and tested.

### 3.8 D1 identity fields (final)

```
D1 = SHA256("D1v1:" \x1f
    tenant_id \x1f
    broker \x1f
    order_id(provider) \x1f
    event_type(canonical) \x1f
    source_mode \x1f
    provider_trade_id(or empty) \x1f
    event_timestamp(epoch ms or empty) \x1f
    order_status(provider verbatim or empty) \x1f
    filled_quantity(provider or empty) \x1f
    cancel_quantity(provider or empty) \x1f
    reject_reason(provider or empty))
```

**Fields NOT used:** `received_at`, `canonical_sequence`, `id`, wall-clock, randomness, `hash()`, `id()`, arrival order, memory identity, `metadata`, derived `order_facts`/`fill_facts` (only raw provider fields participate).

**Timestamp participation:** `event_timestamp` (provider epoch ms) participates in D1. `received_at` does NOT.

**Source-mode participation:** `source_mode` participates in D1 (STREAM/RECOVERY/POLLED_SNAPSHOT). Different channels delivering the same fact have different D1 — this is intentional (they are different observations of the same fact).

**Null semantics:** Absent fields are ALWAYS the literal empty string (never omitted) — this keeps field count and positions fixed, preventing collision by shifting.

**Collision resistance proof:**
- `partial fill cum=20` vs `partial fill cum=50`: different `filled_quantity` → different D1. ✓
- `partial fill at t=1000` vs `partial fill at t=2000`: different `event_timestamp` → different D1. ✓
- Identical redelivery: every field identical → same D1 → DUPLICATE_NOOP. ✓
- `null exchange_timestamp`: empty string field → still distinguished by other fields (status, quantities). ✓

---

## 4. Chatter Canonical Representation Decision

### 4.1 Problem

Contract v8 appears internally inconsistent: some sections treat `validation pending`, `open pending`, etc. as `ORDER_SUBMITTED`; others treat them as "observation-only chatter"; others suggest they carry `SUBMITTED` state.

### 4.2 The core semantic problem

**Can `validation pending` truthfully be represented as `ORDER_SUBMITTED`?**

NO. `ORDER_SUBMITTED` means "the submission attempt was observed." `validation pending` is NOT the submission attempt — it is a processing state AFTER submission. Representing it as `ORDER_SUBMITTED` would be a FALSE claim that the submission event itself was observed.

The Day38 `OrderSubmitted` is the audit record of the submission attempt. Minting it for `validation pending` would be fabricating a submission event that wasn't observed. This violates the "Do not fabricate Day38 history" rule.

### 4.3 Can these be represented as `ORDER_ACCEPTED`?

NO. `ORDER_ACCEPTED` maps to projection state `OPEN` and means "broker working/accepted." `validation pending` is NOT `OPEN`. `open pending` is NOT `OPEN`. `trigger pending` is NOT `OPEN`. `modify pending` is NOT `OPEN`. `modified` is NOT `OPEN`. `not modified` is NOT `OPEN`. `cancel pending` is NOT `OPEN`. `not cancelled` is NOT `OPEN`.

Only `open` itself is `OPEN`. Reusing `ORDER_ACCEPTED` for all processing chatter would corrupt the projection semantic.

### 4.4 Options considered

| Option | Description | Semantic correctness | Task1 impact | Projection impact | Replay impact |
|--------|-------------|---------------------|-------------|------------------|--------------|
| 1 | ORDER_SUBMITTED for all chatter | **FALSE** — claims submission was observed | None | Corrupted — SUBMITTED for non-submission | Fabricated OrderSubmitted |
| 2 | ORDER_ACCEPTED for all chatter | **FALSE** — claims OPEN for non-OPEN | None | Corrupted — OPEN for non-OPEN | N/A (projection-only) |
| **3** | **New canonical event type `ORDER_PROCESSING`** | **TRUE** — "provider processing observation" | New enum value + mapping | Clean — projection state derived from provider status | None (projection-only) |
| 4 | Existing vocabulary + observation semantics | **FALSE** — no existing term fits | None | Corrupted | N/A |

### 4.5 Chosen option: 3 — New canonical event type `ORDER_PROCESSING`

### 4.6 Exact rule

1. Add `ORDER_PROCESSING` to `BrokerEventType` enum.
2. `ORDER_PROCESSING` maps to `None` in `_BROKER_TO_LIFECYCLE` (projection-only, no Day38 lifecycle event).
3. The projection semantic state is derived from the provider status, NOT from the event type:
   - `validation pending`, `open pending`, `trigger pending`, `modify pending`, `modify validation pending`, `modified`, `not modified`, `cancel pending`, `not cancelled` → projection state = SUBMITTED (the order has been submitted and is being processed).
   - `open` → handled by `ORDER_ACCEPTED` (projection state = OPEN), NOT by `ORDER_PROCESSING`.
4. `ORDER_PROCESSING` NEVER mints a Day38 lifecycle event. It is always observation-only for Day38.
5. `ORDER_PROCESSING` updates the projection (durable normalized state) on every observation.

### 4.7 Why this is correct

1. **Semantically truthful:** `ORDER_PROCESSING` means "the provider reported a processing state." It does NOT claim the submission was accepted, rejected, or that a fill occurred.
2. **No corruption of existing semantics:** `ORDER_SUBMITTED` still means "submission attempt observed." `ORDER_ACCEPTED` still means "broker working/accepted." `ORDER_PROCESSING` is a new, distinct concept.
3. **Replay-safe:** `ORDER_PROCESSING` never mints Day38 events, so it cannot corrupt the lifecycle stream.
4. **Projection-correct:** The projection state is derived from the provider status (SUBMITTED for processing chatter), which is the semantically correct state.

### 4.8 Task1 impact

**New enum value `ORDER_PROCESSING`** added to `BrokerEventType`. No other Task1 changes.

### 4.9 Task2 impact

**New mapping** in `_BROKER_TO_LIFECYCLE`: `ORDER_PROCESSING.value → None` (projection-only).

### 4.10 Day38 impact

**None.** `ORDER_PROCESSING` never mints Day38 events.

---

## 5. Submission Ownership Rule

### 5.1 The rule

A provider observation may create Day38 `OrderSubmitted` **if and only if**:
1. The observation's canonical event type is `ORDER_SUBMITTED` (not `ORDER_PROCESSING`), AND
2. The observation is the FIRST submission observation for the order (ownership check via AR-5 `broker_order_lifecycle_state`), AND
3. The order's Day38 lifecycle has not yet reached SUBMITTED.

### 5.2 Which provider status may create OrderSubmitted

**Only `put order req received` and `after market order req received`** may create Day38 `OrderSubmitted`. These are the only statuses that semantically represent the submission attempt.

**All other statuses** (including `validation pending`, `open pending`, `trigger pending`, `modify pending`, `modify validation pending`, `modified`, `not modified`, `cancel pending`, `not cancelled`) are `ORDER_PROCESSING` and NEVER create `OrderSubmitted`.

### 5.3 First observed provider message vs first submission

If `validation pending` is the FIRST observed event (submission missing from stream):
- Canonical event: `ORDER_PROCESSING`
- Projection: SUBMITTED (derived from provider status)
- Day38: **NONE** (no OrderSubmitted minted)
- The submission is missing from the stream → recovery path (later task) reconciles.

**We do NOT fabricate `OrderSubmitted` for `validation pending`.** The canonical event must be truthful. If the submission was not observed, we do not claim it was.

### 5.4 Lifecycle ownership scope

`tenant + execution_id + application_order_id` (NOT execution-only).

The durable ownership record (AR-5 `broker_order_lifecycle_state`) tracks per-order lifecycle state. The execution lock serializes writers; ownership decisions remain order-scoped.

---

## 6. Five Proof Sequences

### P1: `put order req received` → `validation pending` → `open pending` → `open` → `complete`

| Step | Provider status | Canonical event | provider_event_id | Projection | Day38 | Replay |
|------|----------------|-----------------|-------------------|------------|-------|--------|
| 1 | `put order req received` | ORDER_SUBMITTED | D1(step1) | SUBMITTED | OrderSubmitted | PENDING→SUBMITTED ✓ |
| 2 | `validation pending` | ORDER_PROCESSING | D1(step2) | SUBMITTED | NONE | stream unchanged |
| 3 | `open pending` | ORDER_PROCESSING | D1(step3) | SUBMITTED | NONE | stream unchanged |
| 4 | `open` | ORDER_ACCEPTED | D1(step4) | OPEN | NONE | stream unchanged |
| 5 | `complete` | FULL_FILL | D1(step5) | FILLED cum=100 | OrderFilled(cum=100) | OPEN→FILLED ✓ |

**Day38 stream:** TradeIntentCreated → ExecutionActivated → OrderCreated → OrderSubmitted → OrderFilled(100). **Replays deterministically.**

### P2: `validation pending` FIRST observed → `open` → `complete`

| Step | Provider status | Canonical event | provider_event_id | Projection | Day38 | Replay |
|------|----------------|-----------------|-------------------|------------|-------|--------|
| 1 | `validation pending` | ORDER_PROCESSING | D1(step1) | SUBMITTED | NONE | no OrderSubmitted |
| 2 | `open` | ORDER_ACCEPTED | D1(step2) | OPEN | NONE | stream unchanged |
| 3 | `complete` | FULL_FILL | D1(step3) | FILLED cum=100 | **NONE** (no OrderSubmitted yet) | **RECOVERY-REQUIRED** |

**Day38 stream:** TradeIntentCreated → ExecutionActivated → OrderCreated. **No OrderSubmitted → OrderFilled is ILLEGAL** (replay guard: order must be SUBMITTED). **Recovery-required state.** The submission was missed from the stream. Recovery (later task) reconciles.

**This is correct behavior.** We do NOT fabricate OrderSubmitted for `validation pending`. The canonical event is truthful.

### P3: `put order req received` → `modify pending` → `modified` → `open` → `complete`

| Step | Provider status | Canonical event | Projection | Day38 |
|------|----------------|-----------------|------------|-------|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | OrderSubmitted |
| 2 | `modify pending` | ORDER_PROCESSING | SUBMITTED | NONE |
| 3 | `modified` | ORDER_PROCESSING | SUBMITTED (new quantity) | NONE |
| 4 | `open` | ORDER_ACCEPTED | OPEN | NONE |
| 5 | `complete` | FULL_FILL | FILLED | OrderFilled(cum=100) |

**Day38 stream:** ... → OrderSubmitted → OrderFilled(100). **Replays deterministically.**

### P4: `put order req received` → `cancel pending` → `cancelled`

| Step | Provider status | Canonical event | Projection | Day38 |
|------|----------------|-----------------|------------|-------|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | OrderSubmitted |
| 2 | `cancel pending` | ORDER_PROCESSING | SUBMITTED | NONE |
| 3 | `cancelled` | ORDER_CANCELLED | CANCELLED | OrderCancelled |

**Day38 stream:** ... → OrderSubmitted → OrderCancelled. **Replays deterministically.**

### P5: `put order req received` → `rejected`

| Step | Provider status | Canonical event | Projection | Day38 |
|------|----------------|-----------------|------------|-------|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | OrderSubmitted |
| 2 | `rejected` | ORDER_REJECTED | REJECTED | OrderRejected |

**Day38 stream:** ... → OrderSubmitted → OrderRejected. **Replays deterministically.**

---

## 7. Identity Vectors

### 7.1 D1 fields (authoritative)

| Field | Source | Participates in D1? | Why |
|-------|--------|---------------------|-----|
| `tenant_id` | StrikeNova context | YES | Tenant-scoped identity |
| `broker` | StrikeNova context | YES | Broker-scoped identity |
| `order_id` (provider) | Upstox `order_id` | YES | Order-scoped identity |
| `event_type` (canonical) | Task3 classification | YES | Distinguishes observation types |
| `source_mode` | STREAM/RECOVERY/POLLED | YES | Different channels = different observations |
| `provider_trade_id` | Upstox `trade_id` | YES (fill events) | Distinguishes fills |
| `event_timestamp` | Upstox `exchange_timestamp` | YES (when present) | Distinguishes observations at different times |
| `order_status` (provider) | Upstox status verbatim | YES | Distinguishes processing states |
| `filled_quantity` (provider) | Upstox `filled_quantity` | YES | Distinguishes fill observations |
| `cancel_quantity` (provider) | Upstox `cancel_quantity` | YES | Distinguishes cancel observations |
| `reject_reason` (provider) | Upstox rejection message | YES | Distinguishes rejection observations |

### 7.2 Fields NOT in D1

| Field | Why excluded |
|-------|-------------|
| `received_at` | Operational receipt time, not provider fact |
| `canonical_sequence` | Task2 ordering field, not provider observation |
| `id` (database) | Database identity, not provider fact |
| `metadata` | Audit aid, not identity |
| `order_facts` (derived) | Derived from provider fields; raw provider fields already participate |
| `fill_facts` (derived) | Derived from provider fields; raw provider fields already participate |
| Wall-clock, randomness, `hash()`, `id()` | Non-deterministic |
| Arrival order, memory identity | Non-deterministic |

### 7.3 provider_event_id semantics

`provider_event_id` holds EITHER:
- A provider-native event id (e.g. webhook event id), OR
- A StrikeNova-derived D1 (when provider has no event id).

The field is overloaded. In documentation, a StrikeNova-derived value is called "deterministic observation identity" or "D1", NEVER "provider event id".

### 7.4 canonical_id

`canonical_id = SHA256(tenant_id \x1f broker \x1f provider_event_id \x1f event_type)`

When `provider_event_id` holds D1: `canonical_id = SHA256(tenant \x1f broker \x1f D1 \x1f event_type)`.

### 7.5 Fingerprint

`content_fingerprint = SHA256(sorted-json of all semantically relevant fields including provider_event_id, order_facts, fill_facts, metadata, event_timestamp, source_mode, canonical_sequence)`.

### 7.6 Timestamp participation

| Timestamp | D1 | Fingerprint | Projection | Day38 |
|-----------|-----|-------------|------------|-------|
| `event_timestamp` (provider) | YES | YES | occurred_at | occurred_at |
| `received_at` (StrikeNova) | NO | YES | received_at | NO |

### 7.7 Source-mode participation

`source_mode` participates in D1 and fingerprint but NOT in `canonical_id` (the `canonical_id` construction does not include `source_mode`). Wait — this is a problem. Let me check the actual `canonical_id` construction:

```python
if self.provider_event_id:
    parts = (self.tenant_id, self.broker, self.provider_event_id, self.event_type)
```

`source_mode` is NOT in `canonical_id`. This means two observations of the same fact via different channels (STREAM vs RECOVERY) would have the same `canonical_id` if they have the same `provider_event_id` (D1) and `event_type`. But D1 includes `source_mode`, so D1 differs by channel → `provider_event_id` differs → `canonical_id` differs. ✓

### 7.8 Determinism proofs

| Scenario | D1 | canonical_id | Fingerprint | Result |
|----------|-----|-------------|-------------|--------|
| Identical redelivery | Same | Same | Same | DUPLICATE_NOOP |
| Different cumulative value | Different (filled_quantity) | Different | Different | Different event → CONFLICT if same canonical_id, but canonical_id is also different → separate events |
| Different average price | Same D1 (avg_price not in D1) | Same | Different | Same canonical_id, different fingerprint → CONFLICT |
| Different request generation | Different D1 (event_timestamp or status) | Different | Different | Different event |
| `null exchange_timestamp` | Different D1 (empty string vs value) | Different | Different | Different event |

---

## 8. Task1/Task2/Day38 Prerequisites

| ID | File/table | Current behavior | Required behavior | Reason | Schema change? | Migration? | Blocking? |
|----|------------|-----------------|-------------------|--------|---------------|-----------|-----------|
| FI-1a | `app/broker_sync/__init__.py` | `provider_event_id` documented as "provider-native event id when available" | Amend semantic contract to "provider-native event id when available, else deterministic observation identity (D1)" | Enable sequence-less observations | NO | NO | **BLOCKING** (semantic contract change) |
| FI-1b | `app/broker_sync/__init__.py` | No `ORDER_PROCESSING` enum value | Add `ORDER_PROCESSING` to `BrokerEventType` | Canonical representation for processing chatter | NO (enum) | NO | **BLOCKING** |
| FI-1c | `app/broker_sync/ingestion.py` `_BROKER_TO_LIFECYCLE` | No `ORDER_PROCESSING` mapping | Add `ORDER_PROCESSING.value → None` (projection-only) | Day38 mapping for new event type | NO | NO | **BLOCKING** |
| FI-2 | `app/broker_sync/ingestion.py` `_do_ingest` | Projection read BEFORE lock | Lock BEFORE mutable-state reads | TOCTOU safety | NO | NO | **BLOCKING** |
| FI-3 | `app/broker_sync/ingestion.py` `_do_ingest` | No per-order ownership check | Check AR-5 ownership before minting OrderSubmitted | Per-order lifecycle ownership | NO | NO | **BLOCKING** |
| FI-4 | NEW table `broker_fill_ledger` | No D2 set storage | Durable D2-set storage for cross-channel fill dedup | Cross-channel fill identity | YES (new table) | YES (new table) | **BLOCKING** |
| FI-5 | NEW table `broker_order_lifecycle_state` | No durable per-order ownership | Durable per-order lifecycle ownership (PK tenant+order_id) | Per-order ownership enforcement | YES (new table) | YES (new table) | **BLOCKING** |
| FI-6 | `app/broker_sync/ingestion.py` `_build_projection` | `id.desc()` tiebreaker for NULL sequences | Semantic fold (no `id`/`received_at` tiebreak) | Sequence-less projection | NO | NO | **BLOCKING** |
| FI-7 | `app/broker_sync/ingestion.py` `_build_projection` | `total_quantity = max(previous, incoming)` | REPLACE only on `modified` evidence; REJECT contradiction | Quantity modification semantics | NO | NO | **BLOCKING** |
| FI-8 | `app/broker_sync/ingestion.py` `_append_lifecycle_from_event` | No fill-first handling | Fill-first observation-only until submission; convergent OrderFilled on submission | Economic fill preservation | NO | NO | **BLOCKING** |

---

## 9. Remaining Blockers

### 9.1 Resolved

1. **Task1 identity for sequence-less observations:** RESOLVED — Use D1 in `provider_event_id`; amend semantic contract.
2. **Processing chatter canonical representation:** RESOLVED — New `ORDER_PROCESSING` event type; projection-only; projection state derived from provider status.
3. **Submission ownership:** RESOLVED — Only `put order req received` and `after market order req received` create OrderSubmitted; AR-5 tracks per-order ownership.
4. **Cross-channel fill identity:** RESOLVED (in foundational memo v9) — D2 dedup only when both channels supply D2; new `broker_fill_ledger` table required.
5. **Sequence-less projection state:** RESOLVED (in foundational memo v9) — Semantic fold with D2-derived ordering; `modified`-evidence-only for total_quantity replacement.

### 9.2 Remaining architectural prerequisites (all BLOCKING for Task3 implementation)

- FI-1a: Semantic contract change for `provider_event_id` (documentation + test)
- FI-1b: New `ORDER_PROCESSING` enum value
- FI-1c: New `_BROKER_TO_LIFECYCLE` mapping
- FI-2: Lock before mutable-state reads
- FI-3: Per-order ownership check (AR-5)
- FI-4: New `broker_fill_ledger` table (migration)
- FI-5: New `broker_order_lifecycle_state` table (migration)
- FI-6: Semantic fold (no `id`/`received_at` tiebreak)
- FI-7: `modified`-evidence-only for total_quantity
- FI-8: Fill-first handling

---

## 10. Final Decision Gate

**Decision 1 (provider_event_id semantics):** RESOLVED — Use D1 in `provider_event_id`; formally amend semantic contract.  
**Decision 2 (processing chatter):** RESOLVED — New `ORDER_PROCESSING` event type; projection-only; projection state derived from provider status.  
**Decision 3 (submission ownership):** RESOLVED — Only `put order req received` and `after market order req received` create OrderSubmitted; AR-5 tracks per-order ownership.  
**Decision 4 (cross-channel fill identity):** RESOLVED (in v9 memo) — D2 dedup only when both channels supply D2; new `broker_fill_ledger` table required.  
**Decision 5 (sequence-less projection):** RESOLVED (in v9 memo) — Semantic fold with D2-derived ordering; `modified`-evidence-only for total_quantity replacement.

**All foundational architecture decisions are RESOLVED with source-backed rules.**

```
🟢 FOUNDATIONAL ARCHITECTURE FULLY RESOLVED — WRITE CONTRACT v9
```

---

## Appendix: Contradiction Audit

| Contradiction | v8 wording | Actual source fact | Correct rule |
|---|---|---|---|
| D1 vs `provider_event_id` | v8 §Y says D1 is separate from `provider_event_id` | Task1 `provider_event_id` accepts any string; design §6 says adapter must derive identity when provider lacks one | Task3 sets `provider_event_id = D1` when provider has no event id; semantic contract amended (Decision 1) |
| Chatter as ORDER_SUBMITTED | v8 §G maps chatter to ORDER_SUBMITTED | ORDER_SUBMITTED means "submission attempt observed"; chatter is NOT submission | New ORDER_PROCESSING event type; projection state derived from provider status (Decision 2) |
| Chatter as ORDER_ACCEPTED | v8 §H suggests chatter could be OPEN | ORDER_ACCEPTED maps to OPEN; chatter is NOT open | Only `open` itself is ORDER_ACCEPTED; all other chatter is ORDER_PROCESSING (Decision 2) |
| `max(quantity)` | v8 §W.2 says `total_quantity = max(previous, incoming)` | This is WRONG for sequence-less observations | REPLACE only on `modified` evidence; REJECT contradiction (Decision 5) |
| `id.desc()` tiebreaker | v8 §U.5 acknowledges the gap | Current code uses `id.desc()` for NULL sequences | Replace with semantic fold (Decision 5) |
| `received_at` ordering | v8 §U.3 forbids it | Current code does NOT use `received_at` for ordering | Confirmed: no change needed |
| First observed = validation pending | v8 §O.2 says validation pending → APPLIED → SUBMITTED → none | v8 is contradictory about whether validation pending creates OrderSubmitted | validation pending is ORDER_PROCESSING; NEVER creates OrderSubmitted; only `put order req received` creates OrderSubmitted (Decision 3) |

---

## Git / Safety Verification (this session)

**Staged/committed files:** ONLY this final correction memo.

**No production code modified. No implementation. No tests. No migration. No schema. No deployment. Protected files untouched.**
