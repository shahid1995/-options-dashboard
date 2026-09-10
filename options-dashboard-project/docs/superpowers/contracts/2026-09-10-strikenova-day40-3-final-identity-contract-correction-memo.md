# Day40.3 — Final Identity Contract Correction Memo

**Session type:** DESIGN CORRECTION ONLY
**Status:** Correction — supersedes Day40.2 `e440250` on canonical identity, identity upgrade, recency authority, fingerprint serialization, status inventory, and ledger mutability
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`
**HEAD at session start:** `e440250` (Day40.2)
**Day40.2 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-2-final-architecture-correction-memo.md`
**Day40.1 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-1-ambiguous-fill-reconciliation-correction-memo.md`
**Day40 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-foundational-architecture-correction-memo.md`
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`
**Deliverable:** this memo ONLY. No production code, no tests, no migrations were modified.

---

## 0. Baseline verification (repository evidence, re-read this session)

All citations re-read from the working tree at HEAD `e440250` before writing this memo.

| Symbol | Committed state | Evidence |
|---|---|---|
| `BrokerSyncEvent.provider_event_id` | Optional constructor field, no externally supplied canonical identity input exists | `backend/app/broker_sync/__init__.py:129` |
| `BrokerSyncEvent.canonical_id` | **Computed property.** `provider_event_id` present ⇒ `SHA256(tenant \x1f broker \x1f provider_event_id \x1f event_type)`; absent ⇒ `SHA256(tenant \x1f broker \x1f event_type \x1f broker_order_id [\x1f canonical_sequence] [\x1f fill_id \| fill_digest])` | `__init__.py:183-210` |
| Fail-closed identity validation | Without `provider_event_id`: requires `broker_order_id` AND (`canonical_sequence` OR `fill_facts`) | `__init__.py:168-181` |
| `event_id` | Alias property returning `canonical_id` | `__init__.py:211-212` |
| Factory | `make_broker_sync_event(...)` keyword-only, passes through all fields | `__init__.py:216-258` |
| Idempotency table | `BrokerSyncIdempotency.canonical_id` is the PRIMARY KEY (String(64)); `provider_event_id` column exists | `backend/app/broker_sync/models.py:33,42,51` |
| Task2 fingerprint | `_content_fingerprint` — JSON `sort_keys=True, ensure_ascii=True, default=str` over tenant/broker/event_type/event_version/provider_event_id/source_mode/broker_order_id/canonical_sequence (+ event_timestamp, order_facts, fill_facts, metadata when present) | `backend/app/broker_sync/ingestion.py:67-107` |
| Task2 conflict rule | same `canonical_id` + same fingerprint ⇒ `DUPLICATE_NOOP`; same `canonical_id` + different fingerprint ⇒ `CONFLICT` | `ingestion.py:853-885` |
| `ORDER_PROCESSING` | NOT in `BrokerEventType` (9 values) — Day40's additive change is still unimplemented | `__init__.py:21-35` |

No source, test, migration, or protected file was modified in this session.

---

## 1. Executive decision

Four blocking findings from independent verification of Day40.2 are resolved:

1. **One canonical identity contract (Issue 1, Invariant N):** Architecture **Option B** — `BrokerSyncEvent` gains an optional, immutable, constructor-supplied field `canonical_event_id`. When supplied, the `canonical_id` property vends it; when absent, the property computes the legacy value unchanged. The Day40.2 `SHA256(D1 \x1f content_fingerprint)` becomes the **canonical_event_id derivation contract** that Task3 must use when supplying the override. Task1's fallback formula is retained verbatim for all callers that do not supply the override. §2 is the definitive contract; Day40.2 §2.3's claim that Task3 could "use" the D1 decomposition without any Task1 change is **corrected** — it was not implementable against `__init__.py:183-210`.
2. **Corrected official status inventory (Issue 2, Invariant R):** The current official Upstox Order Status appendix (verified 2026-09-10 directly from `https://upstox.com/developer/api-documentation/appendix/order-status/`) contains **exactly 17 values** which do **not** match Day40.2 §6.3. `partial fill` and `expired` are not official values; `modify validation pending` and `cancelled after market order` are. `rejected by rms` is not an order-status value. §3 is the corrected inventory and supersedes Day40.2 §6.3.
3. **Identity upgrade without PK mutation (Issue 3, Invariant O):** Day40.2 §3.1/§3.2 ("fill row `fill_eq_key=C→T1`") contradicted its own "PK is never mutated in place". Corrected to an **immutable alias model**: the composite fill row is never re-keyed; the TRADE_ID fill is a distinct row; a separate alias relation carries C→T; lineage rows record every transition. §4 supersedes Day40.2 §3.
4. **Recency authority, fingerprint serialization, ledger mutability (Issues 4–6, Invariants P, Q):** §5 defines the authoritative ordering ladder (local receipt order is never a substitute for provider truth); §6 defines exact canonical fingerprint serialization (FPv2); §7 classifies every ledger table as immutable or mutable.

All tests remain **SPEC** (§10). **Task3 implementation authorization: NOT GRANTED. Task3 remains 🔴 LOCKED.**

---

## 2. Issue 1 — Single canonical identity contract (Invariant N)

### 2.1 The two identities today (the defect, stated exactly)

- **Task1 committed identity** (`canonical_id`, `__init__.py:183-210`): computed from `(tenant, broker, provider_event_id, event_type)` or, without `provider_event_id`, from `(tenant, broker, event_type, broker_order_id[, canonical_sequence][, fill_digest])`. **Content participates in identity** via `fill_digest`; **the object cannot accept an externally supplied identity**.
- **Day40.2 identity** (§2.1): `canonical_id = SHA256(D1 \x1f content_fingerprint)` where D1 is the observation-correlation key and the fingerprint is the content hash. Content participates **only via the fingerprint**, and D1 — not Task1's field tuple — is the correlation axis.

These are two different functions of two different field sets. Day40.2 §2.3 asserted Task3 would "USE the D1/fingerprint decomposition when constructing Task1 events", but no mechanism exists for Task3 to hand Task1 an identity: every construction path funnels through the property at `__init__.py:183-210`. Two competing canonical identities would persist at runtime — exactly the condition the verification rejected.

### 2.2 Architecture decision: Option B (explicit, with alternatives rejected)

**Chosen — Option B: introduce an explicit `canonical_event_id` field on `BrokerSyncEvent`, distinct from any internally computed value, vended through the existing `canonical_id` property.**

- **Option A rejected (change Task1's formula):** Task1's computed identity is load-bearing for every existing caller, test suite, and persisted `broker_sync_idempotency` row (`models.py:33` keys on it). Rewriting the formula changes identity for already-persisted events, breaks the committed Task1/Task2 contract tests, and silently re-identifies history. Day40's correction discipline (additive-only changes to Task1) forbids it.
- **Option C rejected (redefine D1/canonical_id layering to make D1 == Task1 identity):** D1 is deliberately weaker than event identity (it excludes all content). Making D1 the event identity would fold distinct content observations onto one idempotency PK and reintroduce the Day40 F1 defect. The two-level design (correlation identity + content-participating event identity) is correct; only the delivery mechanism was missing.
- **Option B rationale:** it makes the Day40.2 definition *implementable* with a strictly additive Task1 change, keeps one property (`canonical_id`) as the single identity evaluator, preserves every existing behavior, and gives Task3 an explicit, typed channel for the identity it derives.

### 2.3 Exact formula

Two derivation regimes, one evaluator:

```
Task1 legacy (computed; UNCHANGED)               # __init__.py:183-210, verbatim
  provider_event_id present:
      SHA256( tenant \x1f broker \x1f provider_event_id \x1f event_type )
  provider_event_id absent:
      SHA256( tenant \x1f broker \x1f event_type \x1f broker_order_id
              [ \x1f canonical_sequence ]
              [ \x1f fill_id | SHA256(canonical fill JSON) ] )

canonical_event_id (Task3-supplied; NEW derivation contract, "CEID")
  D1                  = SHA256("D1v1:" \x1f tenant \x1f broker \x1f order_id \x1f event_type [\x1f trade_id])   # Day40 §2.2, unchanged
  content_fingerprint = SHA256(canonical_serialization_v2(observation))                                     # §6 of this memo (FPv2)
  CEID                = SHA256( "CEIDv1:" \x1f D1 \x1f content_fingerprint )
```

Rules:

- `CEID` is a 64-character lowercase hex string; the constructor rejects anything else (`ValueError`).
- The `"CEIDv1:"` prefix guarantees structural disjointness from the legacy regime's inputs (which never begin with that literal before the separator join), so a CEID-supplied identity can never collide with a legacy-computed one except by SHA-256 second-preimage (negligible).
- Same D1 + same fingerprint ⇒ same CEID (determinism, Invariant Q + I). Same D1 + different fingerprint ⇒ different CEID, same D1 (correction identity separation, Invariant J).
- D1 remains **correlation identity only**; it is never an idempotency key and never a ledger PK.

### 2.4 Exact field ownership

| Artifact | Owner (derives) | Owner (stores) | Consumers |
|---|---|---|---|
| D1 | Task3 normalization (from provider observation) | Task3 observation ledger; `event.metadata["strikenova"]["d1"]` | Task3 (correlation, CEID derivation); Task2 (verification only) |
| content_fingerprint (FPv2) | Task3 normalization (§6) | Task3 observation ledger; `event.metadata["strikenova"]["content_fingerprint"]` | Task3 (CEID derivation, duplicate/correction classification); Task2 (verification only) |
| `canonical_event_id` (CEID) | Task3 (`SHA256("CEIDv1:" \x1f D1 \x1f FPv2)`) | Task1 field (immutable after construction); Task2 idempotency PK | Task1 (vends via `canonical_id`); Task2 (PK, dup/conflict) |
| legacy `canonical_id` | Task1 property (computed) | Task1 property (not stored on the object) | All existing callers; unchanged behavior |
| `provider_event_id` | Provider (when it exists) | Task1 field; Task2 idempotency column | Task1 legacy identity input; Day39 conflict rule scope |
| `source_mode`, `received_at` | Our pipeline | Task1 fields | Provenance only — never any identity input |

### 2.5 Exact constructor/API change (specified; NOT applied)

`BrokerSyncEvent` (dataclass, `__init__.py:115-212`):

1. Append one field, **last**, with default — positional compatibility preserved for all existing call shapes:

```
canonical_event_id: Optional[str] = None        # 64-char lowercase hex or None
```

2. `__post_init__` additions: if `canonical_event_id is not None`, require `isinstance(str)` and full match `^[0-9a-f]{64}$`, else `ValueError("canonical_event_id must be a 64-character lowercase hex string")`. No other validation change.
3. `canonical_id` property becomes:

```
if self.canonical_event_id is not None:
    return self.canonical_event_id
# ... existing computation, byte-for-byte unchanged ...
```

4. `event_id` alias unchanged (returns `canonical_id`).
5. `make_broker_sync_event` gains keyword-only `canonical_event_id: Optional[str] = None`, passed through.
6. Task1 does **not** recompute or verify the CEID against D1/fingerprint (it does not possess them). Verification is Task2's, below.

**Task2 ingestion change (specified; NOT applied):** when `event.metadata["strikenova"]` carries `d1` + `content_fingerprint`, Task2 MUST verify `SHA256("CEIDv1:" \x1f d1 \x1f content_fingerprint) == event.canonical_id`; mismatch ⇒ `REJECTED` (reason `canonical identity mismatch`) before the idempotency check. Events without the metadata block (legacy, tests, non-Task3 adapters) skip verification. This binds the override to the derivation contract without burdening Task1.

**Task3 metadata contract (specified):**

```
metadata = {
  "strikenova": {
    "d1": "<64 hex>",                  # correlation identity used for CEID
    "content_fingerprint": "<64 hex>", # FPv2 digest used for CEID
    "d1_version": "D1v1",
    "fp_version": "FPv2",
  },
  "upstox": { ...raw provider payload, verbatim... },
}
```

### 2.6 Backward compatibility (five guarantees)

1. **Default construction unchanged:** `canonical_event_id=None` ⇒ `canonical_id` computes exactly as committed (`__init__.py:183-210` byte-for-byte). Every Task1/Task2 committed test expectation holds without modification.
2. **Fail-closed validation unchanged:** `__init__.py:168-181` rules apply as committed. A CEID-supplied event with no `provider_event_id`, no `broker_order_id`, no `canonical_sequence`, and no `fill_facts` is **legal** — the identity discriminator requirement is satisfied by the supplied CEID itself (this is precisely the sequence-less order-observation case Day40.2 §2.3 flagged as a prerequisite).
3. **No re-identification of stored rows:** `BrokerSyncIdempotency` rows keep their committed `canonical_id` keys; nothing is recomputed or migrated.
4. **Fallback output unchanged:** no constructor-input combination that validated before Day40.3 yields a different `canonical_id` after Day40.3.
5. **Structural non-collision:** `"CEIDv1:"` prefix ⇒ CEID-keyed and legacy-keyed rows occupy disjoint identity families; a cross-family duplicate can only be resolved semantically (same D1+FPv2 ⇒ same CEID ⇒ same PK dedup), never by hash collision.

### 2.7 Existing persisted event behavior

- Persisted idempotency rows (keyed by legacy computed ids) remain the join keys for their events. No re-derivation, no backfill, no migration — ever.
- During transition, both identity families coexist: legacy events (tests, adapters) keep legacy keys; Task3 events carry CEID keys.
- The projection fold orders applications by **provider authority signals (§5)**, never by key family or arrival order; key family is not a recency signal.
- Legacy events may be superseded by CEID-keyed corrections for the same D1 scope; the fold's later-authoritative-wins semantics (§5) make this unambiguous without touching stored rows.

### 2.8 Conflict semantics (single table; Task2 rule untouched)

| Incoming vs stored | Condition | Action | Source |
|---|---|---|---|
| same `canonical_id` (either family) | same Task2 fingerprint (`ingestion.py:67-107`) | `DUPLICATE_NOOP` | `ingestion.py:853-885`, unchanged |
| same `canonical_id` | different Task2 fingerprint | `CONFLICT` | `ingestion.py:853-885`, unchanged |
| different `canonical_id`, same D1 | different FPv2 (correction) | **new immutable event; `APPLIED`** — never CONFLICT | Day40.2 §2.4 carve-out, retained |
| different D1 | — | `DISTINCT` | unchanged |
| CEID event with mismatching metadata digest | verification (§2.5) fails | `REJECTED` | NEW, Task2 |

**Channel-convergence prerequisite (Task3 normalization contract, bounded):** Task2's fingerprint includes `source_mode` and `canonical_sequence`, so two constructions of the *same* semantic observation that differ in those fields would CONFLICT. Task3 MUST therefore reconstruct redeliveries of an already-delivered (D1, FPv2) observation with the **first authorized delivery's** identity-bearing fields (stored with the observation), so Task2 sees same `canonical_id` + same fingerprint ⇒ `DUPLICATE_NOOP`. Where a channel cannot reproduce them, Task3 must not emit the second construction as a new event; it records the delivery on the existing observation. This is a Task3 requirement, not a Task1/Task2 change.

### 2.9 What changes vs Day40.2 (governance)

| Day40.2 text | Verdict |
|---|---|
| §2.1 `canonical_id = SHA256(D1 \x1f content_fingerprint)` | **Retained as the CEID derivation contract**, renamed `canonical_event_id` to free the `canonical_id` name for Task1's single evaluator (§2.3) |
| §2.3 "Day40.2 does NOT change Task1 code; Task3's normalization will USE the D1/fingerprint decomposition when constructing Task1 events" | **CORRECTED** — not implementable as written; Option B's additive field is the mechanism (§2.2, §2.5) |
| §2.2 decision table (SAME/CHANGED_OBSERVATION/DISTINCT) | **Retained**, with `canonical_id` column read as CEID |
| §2.4 Day39 conflict-rule carve-out | **Retained** verbatim |
| §7 "Canonical Event ID (canonical_id)" row | **Superseded** by §2.3/§2.4 of this memo (ownership + formula) |
| §6.3 status inventory | **Superseded** by §3 of this memo |
| §3 identity upgrade | **Superseded** by §4 of this memo |
| §8 case 39/43 recency footnote | **Superseded** by §5 of this memo |
| everything else (§4 concurrency, §5 observed_count, §6.1/§6.2 governance) | **Retained** |

---

## 3. Issue 2 — Official Upstox status inventory (Invariant R)

### 3.1 Verification (performed this session, current official documentation)

Source: **Upstox Developer API — Appendix › Order Status**, `https://upstox.com/developer/api-documentation/appendix/order-status/` (fetched 2026-09-10; the page states it "provides a comprehensive list of the various statuses an order can hold"). The appendix lists **exactly 17 values**, in page order:

`validation pending`, `modify pending`, `trigger pending`, `put order req received`, `modify after market order req received`, `cancelled after market order`, `open`, `complete`, `modify validation pending`, `after market order req received`, `modified`, `not cancelled`, `cancel pending`, `rejected`, `cancelled`, `open pending`, `not modified`.

**Corrections vs Day40.2 §6.3:**

- `partial fill` (Day40.2 row 15) is **NOT an official order-status value**. Partial-fill state is *derived*: provider status `open`/`complete` with `0 < filled_quantity < quantity` ⇒ `PARTIAL_FILL` (this restores the v8 §G correction, which Day40.2 silently dropped).
- `expired` (Day40.2 row 17, incl. its parenthetical note) is **NOT an official order-status value**. `ORDER_EXPIRED` remains in the Task1 catalog for non-Upstox providers only; no Upstox status maps to it. The Task1 enum is unchanged in this session.
- `modify validation pending` and `cancelled after market order` **are** official values and are restored to the inventory (they were present in the Day39 v8 §G matrix and the Day39 final-foundational-correction memo's verified list).
- `rejected by rms` is **not an order-status value**. It appears in provider prose as `status_message_raw` ("Description of the order's status as received from RMS" — Get Order Details field docs). It is preserved as raw metadata on whatever order status it accompanies (typically `rejected`); it is never a distinct canonical event, never an identity input.

### 3.2 Corrected inventory — exact 17 rows

Columns: provider status (verbatim) → canonical event type → `OrderFacts` projection (status + notable fields) → raw metadata preservation. Common preservation rules apply to every row (see 3.3).

| # | Provider status (verbatim) | Canonical event type | OrderFacts.status | OrderFacts notable fields | Preserved raw metadata (beyond common) |
|---|---|---|---|---|---|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | `is_terminal=False` | — |
| 2 | `after market order req received` | ORDER_SUBMITTED | SUBMITTED | `is_terminal=False`; `is_amo=True` provenance | `metadata["upstox"]["is_amo"]` |
| 3 | `validation pending` | ORDER_PROCESSING | SUBMITTED | projection-only chatter | — |
| 4 | `open pending` | ORDER_PROCESSING | SUBMITTED | projection-only chatter | — |
| 5 | `trigger pending` | ORDER_PROCESSING | SUBMITTED | projection-only chatter (SL/SL-M armed) | — |
| 6 | `modify pending` | ORDER_PROCESSING | SUBMITTED | projection-only chatter | — |
| 7 | `modify validation pending` | ORDER_PROCESSING | SUBMITTED | projection-only chatter | — |
| 8 | `modified` | ORDER_PROCESSING | SUBMITTED | `total_quantity` = provider quantity (modification ack is the quantity authority) | prior vs new quantity in raw payload |
| 9 | `not modified` | ORDER_PROCESSING | SUBMITTED | order retained; NOT a rejection | `metadata["upstox"]["status_message"]` (reason) |
| 10 | `cancel pending` | ORDER_PROCESSING | SUBMITTED | cancellation in progress, unconfirmed | — |
| 11 | `not cancelled` | ORDER_PROCESSING | SUBMITTED | order remains active; NOT a rejection | `metadata["upstox"]["status_message"]` (reason) |
| 12 | `modify after market order req received` | ORDER_PROCESSING | SUBMITTED | AMO modification request | `metadata["upstox"]["is_amo"]` |
| 13 | `rejected` | ORDER_REJECTED | REJECTED | `is_terminal=True`; `rejection_reason = status_message` when present | `status_message`, `status_message_raw` (incl. any "rejected by rms" prose) |
| 14 | `complete` | FULL_FILL | FILLED | `is_terminal=True`; `cumulative_filled = filled_quantity`; `average_price`; derived `PARTIAL_FILL` only when `0 < filled_quantity < quantity` | — |
| 15 | `open` | ORDER_ACCEPTED | OPEN | projection-only (`_BROKER_TO_LIFECYCLE[ORDER_ACCEPTED] = None`, `ingestion.py:124-147`); derived `PARTIAL_FILL` / `PARTIALLY_FILLED` when `0 < filled_quantity < quantity` | — |
| 16 | `cancelled` | ORDER_CANCELLED | CANCELLED | `is_terminal=True` | — |
| 17 | `cancelled after market order` | ORDER_CANCELLED | CANCELLED | `is_terminal=True`; AMO cancellation | `metadata["upstox"]["is_amo"]` |

### 3.3 Common preservation rules (all 17 rows, Invariant F retained)

1. Every event round-trips the provider payload verbatim under `metadata["upstox"]` — the coarse `OrderFacts` projection never erases provider truth.
2. `metadata["upstox"]["status"]` carries the status token verbatim (exact casing/spacing).
3. `status_message` / `status_message_raw` are preserved whenever non-null (notably rows 9, 11, 13; `status_message_raw` is where RMS prose such as "rejected by rms" surfaces).
4. `exchange_timestamp`, `order_timestamp`, `filled_quantity`, `average_price`, `pending_quantity` are preserved on every observation (they are fingerprint inputs per §6 and authority evidence per §5).
5. **Unknown status policy (fail-closed):** a status token outside this 17-row inventory is never mapped by analogy. The observation is rejected at normalization, stored raw, flagged for operator review, and the inventory is re-verified against the official appendix before any addition. Invariant R binds the implementation to exactly this list.
6. `ORDER_EXPIRED` is never emitted from any Upstox status; it exists in the Task1 catalog for other providers only.

---

## 4. Issue 3 — Identity upgrade without PK mutation (Invariant O)

### 4.1 The contradiction, stated exactly

Day40.2 §3.1 declares "the ledger is append-only; a PK is never mutated in place for an upgrade", yet §3.2 cases A/C specify `fill row fill_eq_key = C→T1` — a **mutation of the `fill_eq_key` component of the fill row's primary key** `(tenant_id, order_id, fill_eq_key)`. Both cannot hold. Corrected model: the composite fill row is **never re-keyed**; identity moves through explicit relations.

### 4.2 Model objects

| Object | Table (design) | Identity | Mutability |
|---|---|---|---|
| Raw observation | `broker_fill_ledger_observation` | `(tenant_id, observation_id UUID)` | **Immutable forever** — content, fingerprint, `fill_eq_key` as observed (`C` or `T`), provenance |
| Provisional identity | composite `C = SHA256("FILLKEYv1:" \x1f tenant \x1f order \x1f \x1f exchange_ts \x1f qty \x1f price)` | provisional; quarantined scope | never upgraded in place |
| Authoritative identity | trade_id `T` (provider-minted) | economic fill identity | the only RECONCILED-eligible fill identity |
| Economic fill row | `broker_fill_ledger_fill` | `(tenant_id, order_id, fill_eq_key)` | **Row identity immutable**; mutable columns per §4.4 |
| **Alias relation (NEW)** | `broker_fill_identity_alias` | `(tenant_id, order_id, from_eq_key)` → `to_eq_key`, UNIQUE | current alias pointer; versioned by lineage |
| Lineage / audit | `broker_fill_identity_lineage` | `(tenant_id, lineage_id UUID)` | **Append-only** |

`broker_fill_identity_alias` (the Day40.2 gap):

```
tenant_id, order_id,
from_eq_key  (= composite C; UNIQUE with tenant+order),
to_eq_key    (= trade_id T1, or NULL while unresolved),
alias_state  (UNRESOLVED | AUTHORITATIVE | SPLIT | CONTRADICTED),
created_at, last_transition_at
```

The alias is the **only** thing that changes when an upgrade happens; it is a relation, not a row re-key. Every change appends a lineage row.

### 4.3 Required transitions (all five explicit cases)

| Transition | Procedure | Alias state | Fill rows | Lineage outcome | Emission |
|---|---|---|---|---|---|
| **C → T1** (upgrade) | History/stream proves exactly one trade_id T1 with matching (qty, price, cumulative). Observation row untouched (`fill_eq_key=C` forever). Fill row `(tenant, order, T1)` created (`fill_identity_type=TRADE_ID`). Alias `C→T1`. | UNRESOLVED → AUTHORITATIVE | C row (if it existed) marked `SUPERSEDED_BY_ALIAS`, frozen — never deleted, never re-keyed; T1 row RECONCILED | `from=C, to=T1, trigger=PROVIDER_HISTORY\|STREAM, outcome=UPGRADED` | 1 canonical fill event under `D1(fill, T1)` |
| **C → T1/T2** (split) | History proves two trades matching C's content; `qty(T1)+qty(T2) == cumulative_after(C)` enforced, else CONTRADICTED path | UNRESOLVED → SPLIT | T1 and T2 rows created; C row frozen | `outcome=SPLIT, trade_ids=[T1,T2]` | 2 events |
| **C → no candidate** | No trade matches | stays UNRESOLVED | C row stays AMBIGUOUS | `outcome=NO_CANDIDATE` | none; re-checked on every provider payload |
| **C → T1 later contradicted** | Authoritative evidence shows T1's content ≠ observation's content, or a later authoritative observation contradicts the mapping | AUTHORITATIVE → CONTRADICTED (operator review); **T1 row is NOT deleted** | T1 row flagged; a corrected mapping may create `T1'` as a distinct row with its own lineage; original T1 row and all lineage rows retained | `outcome=CONTRADICTED, evidence_ref` | none automatic; operator adjudication only |
| **two workers C → T1** | Both attempt alias update + T1 creation inside the §4.1 (Day40.2) LOCK→READ→CLASSIFY→AUTHORIZE→WRITE→EMIT→COMMIT transaction; `alias` UNIQUE on `(tenant, order, from_eq_key)` + fill-row PK arbitration ⇒ exactly one authoritative alias/one T1 row/one emission; the loser re-reads, observes the alias, records an audit lineage row of the race (both lineage rows retained, Day40.2 §3.2F behavior preserved) | single AUTHORITATIVE | single T1 row | two lineage rows (winner + race audit) | exactly once |

Additional rules:

- **Simultaneous canonical identity upgrade (adversarial case 58):** the same arbitration applies when two workers derive the authoritative identity at once (one upgrading C→T1 while another delivers a second C observation): observation rows are append-only (no arbitration needed), the alias UNIQUE constraint arbitrates the upgrade, and `observed_count` increments on the loser's re-read.
- **No delete, no re-key:** no transition updates any primary-key component of any row. `SUPERSEDED_BY_ALIAS` is a mutable *column* on the frozen composite row.
- **Cumulative conservation:** sum of split fill quantities must equal the composite's `cumulative_after`; mismatch ⇒ CONTRADICTED + quarantine, never a guessed split.
- **Trade-id-less segments** (e.g. MF rows with empty trade_id): can never reach an authoritative identity; remain UNRESOLVED with cumulative flowing at the order level — unchanged limitation (Day40.2 §11.2).

### 4.4 Mutable columns of `broker_fill_ledger_fill` (the only ones)

`reconciliation_state`, `observed_count`, `canonical_id` (last emitted event), `last_authority_evidence_ref`, `frozen_reason` (`SUPERSEDED_BY_ALIAS` / `CONTRADICTED` markers), timestamps. Everything else — especially `fill_eq_key` and `fill_identity_type` — is written once at insert and never updated.

---

## 5. Issue 4 — Correction / recency authority (Invariant P)

### 5.1 Problem

Day40.2 case 39/43 footnote resolves stale-vs-correction via "latest provider observation wins" with the broker-order state snapshot as fallback — i.e., arrival order in disguise. Insufficiently precise. Superseded by the authority ladder below. **Local receipt order is never a recency signal. There is no bounded exception.**

### 5.2 Authoritative ordering signals (acceptable evidence, ranked)

| Rank | Signal | Source | Use |
|---|---|---|---|
| S1 | `provider_sequence` | provider stream, when the provider documents one | higher sequence ⇒ later observation |
| S2 | `exchange_timestamp` (provider event time) | Upstox order book / order details (`exchange_timestamp`, second precision) | later timestamp ⇒ later observation |
| S3 | Authoritative order-history ordering | provider order-history / trade-history endpoint: the endpoint's row set and order are the provider's authoritative statement of the order's state and fill sequence | a history-sourced observation supersedes stream/poll-sourced content for the same scope once fetched and matching `(order_id, scope)` |
| S4 | Operator adjudication | documented operator decision + evidence ref | terminal resolution of quarantined conflicts |

Nothing else is admissible. In particular: `received_at`, `source_mode`, worker identity, and partition/consumer offsets are **provenance, never authority**.

### 5.3 Classification decision (given same D1, differing fingerprints, any arrival order)

```
CLASSIFY(candidate B, current C):            # B arrived after C was applied
  if S1 available for both and seq(B) ≠ seq(C):  B newer ⇔ seq(B) > seq(C)
  elif S2 available for both and ts(B) ≠ ts(C):  B newer ⇔ ts(B) > ts(C)
  elif S3 available:                              B newer ⇔ B is history-sourced (and C is not)
  else:                                           UNRESOLVED
  B newer  ⇒ LEGITIMATE_CORRECTION   → apply (new CEID; fold update)
  B older  ⇒ STALE                   → store immutable observation (resolution=STALE); do NOT apply
  equal/absent ⇒ UNRESOLVED          → QUARANTINE (below)
```

- **LEGITIMATE_CORRECTION:** produces a new immutable event (different CEID, same D1); projection folds to the corrected content; prior event retained (Invariants I/J/K intact).
- **STALE:** the observation is permanently preserved with `resolution=STALE` and the authority evidence used (signal + values); no emission; no projection change. It is never applied, regardless of how much later it arrived.
- **UNRESOLVED / QUARANTINED:** no provider-authoritative ordering exists. The current content stays applied (first application was legal; ordering questions only arise once two contents conflict); the challenger is quarantined with `resolution=UNRESOLVED`, flagged for operator review, and automatically re-evaluated whenever a new authoritative signal appears (history refetch, provider sequence appearing). It is never auto-resolved by arrival order.
- **Terminal protection:** once a terminal state (FILLED/CANCELLED/REJECTED) is RECONCILED on an authoritative signal, a later non-terminal observation for the same D1 is quarantined for review (does not auto-apply) — consistent with Day40.2 §4.2's SUPERSEDED handling.
- **Single-observation note:** the ladder engages only when two authoritative-eligible contents conflict for the same D1. A lone observation applies without ordering questions.
- **Equal-timestamp tie:** Upstox `exchange_timestamp` has second precision; two distinct contents with equal timestamps are UNRESOLVED (not resolved by receipt order).

This corrects Day40.2 case 39 (was: "latest provider observation wins … quarantining out-of-order arrivals that lack authority") and case 43 (was: broker-order snapshot as recency authority). Both now resolve exclusively through S1–S4.

---

## 6. Issue 5 — Content fingerprint serialization (Invariant Q)

### 6.1 Two fingerprints, one rule set

- **FPv1** — Task2's `_content_fingerprint` (`ingestion.py:67-107`), JSON `sort_keys=True, ensure_ascii=True, default=str`. **Unchanged** (backward compatibility, §2.6). Its weaknesses (float rendering via `str`, no Unicode normalization, provenance fields included) are irrelevant to identity because CEID no longer depends on it.
- **FPv2** — the Task3 observation fingerprint, an input to CEID. Specified below; MUST be deterministic across implementations (Python/TS) via shared test vectors (§10).

### 6.2 FPv2 canonical serialization — exact

**Field set (order observation):** `tenant_id`, `broker`, `provider_order_id`, `event_type`, `provider_status` (verbatim token), `total_quantity`, `filled_quantity`, `cancelled_quantity`, `average_price`, `reject_reason`, `event_timestamp`, `trade_id` (empty string for non-fills).
**Excluded (provenance, never fingerprinted):** `provider_event_id`, `source_mode`, `received_at`, `provider_sequence`, worker/channel metadata. Rationale: channel convergence — the same semantic fact via STREAM and RECOVERY must produce the same FPv2 (and hence the same CEID ⇒ `DUPLICATE_NOOP`).

**Encoding rules:**

| Aspect | Rule |
|---|---|
| Structure | single JSON object; **no positional field order** — keys sorted lexicographically by Unicode code point (ascending) on the NFC-normalized key strings |
| Encoding | UTF-8 bytes of `JSON.stringify`-equivalent output with non-ASCII escaped (`ensure_ascii` semantics) so the byte stream is ASCII; separators `,`/`:` without whitespace |
| Nested objects | sorted the same way; arrays (none exist in FPv2's field set) would preserve given order — FPv2 contains no arrays |
| Null representation | `null` and **absent key are identical**: the key is omitted from the object |
| Empty string | **semantically distinct from null**: serialized as `""` ⇒ different fingerprint (the provider sent a value; §8 case 56) |
| Integers (quantities) | must be integral: serialize as base-10 integer (`20`, `20.0`, `20.00` ⇒ `20`); a non-integral quantity is a normalization error (fail-closed, REJECTED) |
| Decimals (prices) | fixed-point decimal, **never binary float**: parse as Decimal/string; strip trailing zeros in the fraction; drop the decimal point when the fraction is empty (`100`, `100.0`, `100.00` ⇒ `100`; `100.100` ⇒ `100.1`; `0.10` ⇒ `0.1`); precision differences are real differences (`100.10000000001` ≠ `100.1`) |
| Timestamps | timezone-aware input required (matches Task1 validation, `__init__.py:150-152`); convert to UTC; render RFC 3339 `YYYY-MM-DDTHH:MM:SS.mmmZ` with sub-millisecond digits **truncated** (deterministic, documented as lossy) |
| Unicode | all strings NFC-normalized (`UAX #15`) before serialization |
| Booleans | `true`/`false` JSON literals (Python `bool` is not a quantity) |
| Digest | `SHA256` over the UTF-8 bytes; lowercase hex |

**Determinism obligations:** same semantic observation ⇒ byte-identical canonical object ⇒ same FPv2 across languages/implementations (Invariant Q). Equivalent payloads with different JSON key ordering produce identical FPv2 (case 55). Implementations MUST NOT parse numeric fields as binary floats (use Decimal/string), MUST NOT rely on host locale, and MUST apply the table above verbatim. FPv2 is versioned (`fp_version: "FPv2"` in metadata, §2.5); any rule change ⇒ new version ⇒ new CEID family (old rows never re-fingerprinted).

---

## 7. Issue 6 — Immutable vs mutable ledger tables

**The entire ledger is NOT "append-only".** Classification (supersedes the unqualified Day40.2 §3.1 phrase "The ledger is append-only"):

| Class | Tables | Mutability contract |
|---|---|---|
| **A. Immutable raw observations** | `broker_fill_ledger_observation`; `broker_sync_idempotency` (insert-only rows: inserted once at first application, never updated); `trade_lifecycle_events`; canonical-event outbox (`canonical_event`) | append-only; no UPDATE/DELETE ever |
| **B. Current economic-fill identity/state** | `broker_fill_ledger_fill` | mutable **columns only** (§4.4); row identity `(tenant_id, order_id, fill_eq_key)` immutable; no re-key, no delete; superseded rows frozen in place |
| **C. Immutable lineage/audit** | `broker_fill_identity_lineage`; state-transition audit rows; operator adjudication records | append-only; every B/D mutation and every §4.3 transition appends here |
| **D. Mutable projections/counters** | normalized order projection (current state per order); `broker_sync_sequence_anchor` (CAS-updated); `observed_count` (column on B) | mutable current-state; every mutation inside the §4.1 (Day40.2) transaction contract; derived data must be rebuildable by folding A |

Rules: "append-only" may only be claimed for classes A and C. Classes B and D are current-state stores whose changes are legitimate — but only through the transaction contract with an audit row in C. Any design text that calls the whole ledger append-only is imprecise and is corrected by this section.

---

## 8. Adversarial cases 44–58 (retaining 1–43)

Legend: `D1` observation correlation id; `FP` = FPv2; `CEID` = canonical_event_id; `T1id` = Task1 identity in force (`canonical_id`); `Ledger` = observation/fill/alias identity effect; `Lin` = lineage; `St` = state; `Em` = emission; `Pr` = projection; `Result` = final result.

| # | Input | D1 | FP | CEID | T1id | Ledger | Lin | St | Em | Pr | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 44 | same provider fact as legacy-computed event AND as Task3 CEID event | same | same | CEID ≠ legacy Task1 id (different regime) | legacy: computed; Task3: supplied override | two idempotency keys — disjoint families, no silent merge | none | both recorded | none | fold sees both; Task3 path authoritative for its scopes | ONE identity per event; one evaluator (`canonical_id`); cross-family dedup only via same D1+FP ⇒ same CEID (Invariant N) |
| 45 | observation **with** `provider_event_id` | D1(order) | FP(content) | `H("CEIDv1:"‖D1‖FP)` | override = CEID | row keyed CEID | n/a | APPLIED | per event class | updated | provider id = provenance + Day39-conflict scope; identity is CEID |
| 46 | observation **without** `provider_event_id` (no seq, no fill_facts) | D1(order) | FP(content) | CEID | override = CEID (fail-closed satisfied by supplied identity, §2.6-2) | row keyed CEID | n/a | APPLIED | per event class | updated | deterministic identity without provider ids; redelivery ⇒ same CEID ⇒ DUPLICATE_NOOP; corrected content ⇒ new CEID ⇒ APPLIED (never CONFLICT) |
| 47 | same D1 / same FP / same CEID, STREAM then RECOVERY | same | same | same | same | one row (or observed_count++) | none | unchanged | none | none | idempotent (channel convergence; §5.3 reconstruction rule) |
| 48 | same D1 / different FP (correction) | same | different | **different** | different | two immutable events | n/a | stays RECONCILED | CHANGED_OBSERVATION | fold update | correction identity separated (J); never CONFLICT in D1 path |
| 49 | composite C → T1 upgrade | class → D1(fill,T1) | same content | new CEID under D1(fill,T1) | fill events keyed D1(fill,T1) | observation row immutable (`fill_eq_key=C` forever); fill row `(t,o,T1)` created; C row frozen `SUPERSEDED_BY_ALIAS` | `C→T1, outcome=UPGRADED` | AMBIGUOUS→RECONCILED | 1 fill event | fill counted once | **no PK component mutated anywhere** (O) |
| 50 | composite C → T1/T2 split | class → D1(fill,T1)+D1(fill,T2) | per row | two fill CEIDs | two fill events | two fill rows; C frozen | `outcome=SPLIT, [T1,T2]` | RECONCILED×2 | 2 events | both counted; `qty(T1)+qty(T2)==cum(C)` enforced | split recorded; no merged fill |
| 51 | stale correction arriving after newer truth (B.ts < C.ts) | same | different | (B: would-be new CEID) | B not constructed as event | B stored as immutable observation, `resolution=STALE` + evidence | race audit row | unchanged RECONCILED | none | none | STALE preserved, never applied — authority ts, not arrival (P) |
| 52 | newer correction arriving after stale delivery (B.ts > C.ts, B arrives second) | same | different | new CEID | new event | new immutable event | n/a | stays RECONCILED | new canonical event | fold update to B | LEGITIMATE_CORRECTION on provider authority; arrival order irrelevant |
| 53 | same D1 / different FP / no S1, equal-or-absent S2, no S3 | same | different | n/a for challenger | none | challenger quarantined `resolution=UNRESOLVED`; re-evaluated on new authority | operator-flag row | keeps current content | none (challenger) | keeps current content | UNRESOLVED/QUARANTINED — fail-closed (P); never receipt-order truth |
| 54 | one order traversing all 17 official statuses | distinct per observation | distinct per observation (status ∈ FP) | distinct | distinct | 17 immutable observations | n/a | §4.2 transitions | per §3.2 mapping | SUBMITTED→…→FILLED / CANCELLED | exact 1:1 mapping; unknown token ⇒ REJECTED fail-closed (R) |
| 55 | equivalent payloads, different JSON key order | same | **same** (Q) | same | same | one row | none | unchanged | none | none | fingerprint determinism proven (case 55 + FPV tests) |
| 56 | field null vs absent vs empty string | same | null/absent ⇒ same FP; `""` ⇒ different FP | null/absent ⇒ same CEID; `""` ⇒ different CEID | correspondingly same/different | one row vs two rows | none | DUPLICATE_NOOP vs two observations | none | — | deterministic; semantic difference preserved (§6.2) |
| 57 | `20` vs `20.0` (qty); `100` vs `100.0` vs `100.00` vs `100.100` (price) | same | `20`≡`20.0`; `100`≡`100.0`≡`100.00`; ≠ `100.1` | correspondingly same/different | same/different | one row vs two | none | DUPLICATE_NOOP vs distinct | none | — | numeric normalization deterministic; precision differences honest (§6.2) |
| 58 | simultaneous canonical identity upgrade (two workers derive/apply C→T1 at once; or one upgrades while another delivers a second C observation) | class → T1 | same | same fill CEID | one event | alias UNIQUE arbitrates; single fill row `(t,o,T1)`; observations append-only | winner + race-audit lineage rows (both retained) | single RECONCILED | exactly once | counted once | exactly-once; no PK mutation; Day40.2 §3.2F behavior preserved under alias model |

Cases 1–43 remain as specified in Day40/Day40.1/Day40.2, with case 39/43 recency resolution re-bound to §5.3 and cases 33–37 re-bound to the alias model of §4 (their outcomes are unchanged; only the mechanism — no PK mutation — is corrected).

---

## 9. Invariants N–R (added to Day40.1 A–H and Day40.2 I–M)

| # | Invariant | Defense | SPEC tests |
|---|---|---|---|
| **N** — single canonical identity contract | Task1 and the Day40.2 lineage define ONE implementable canonical event identity: the `canonical_id` property is the only evaluator; CEID is its supplied input; D1 is correlation-only | §2 (Option B; derivation + ownership + verification); structural non-collision §2.6-5 | T1ID-01/02/03, CAN-01..06 |
| **O** — identity-upgrade immutability | a provisional (composite) identity is never mutated in place; upgrades create distinct authoritative rows linked by alias + lineage; observation rows immutable forever | §4 (alias relation; frozen `SUPERSEDED_BY_ALIAS`; no PK-component updates) | UPG-04..09 |
| **P** — provider-order authority | local receipt order can never manufacture provider recency; stale/correction resolved only by S1–S4; otherwise UNRESOLVED/QUARANTINED | §5 ladder; quarantine + operator path; no bounded receipt-order exception | ORD-01..05 |
| **Q** — deterministic fingerprint | equivalent canonical content always yields the same FPv2 across implementations | §6 canonical serialization + cross-implementation vectors | FPV-01..05, CAN-05 |
| **R** — status completeness | the canonical status inventory exactly matches the authoritative provider inventory (17 rows, verified 2026-09-10); unknown ⇒ fail-closed | §3 inventory + unknown-status policy | GOV-02..04 |

---

## 10. Test specification — SPEC only

No tests executed. All entries are design specifications for the implementation phase. Existing suites (e.g. `test_day39_task1_canonical_contract.py`) must pass unmodified — that is guarantee §2.6-1.

| Area | Test | Status |
|---|---|---|
| Task1/Day40.2 identity compatibility | T1ID-01: constructor-supplied `canonical_event_id` is vended by `canonical_id`/`event_id`; metadata digest verifies at Task2; mismatch ⇒ REJECTED | SPEC |
| | T1ID-02: backward compat — every pre-Day40.3 construction shape yields the committed `canonical_id` values (existing suites pass unmodified) | SPEC |
| | T1ID-03: `canonical_event_id=None` ⇒ computed fallback; CEID format enforcement (reject non-64-hex) | SPEC |
| canonical ID determinism | CAN-01: same D1+FP ⇒ same CEID; CAN-02: same D1, different FP ⇒ different CEID, same D1; CAN-03: different D1 ⇒ different CEID; CAN-04: `"CEIDv1:"` prefix disjointness from legacy family | SPEC |
| canonical ID correction semantics | CAN-05: correction (same D1, new FP) emits new immutable event; old retained; fold applies by §5.3 authority — never CONFLICT in D1 path | SPEC |
| alias upgrade without PK mutation | UPG-04: C→T1 — observation row byte-identical post-upgrade; alias created; fill row keyed T1; frozen C row marked, not re-keyed; lineage complete | SPEC |
| C→T1 | UPG-05: exactly-one candidate ⇒ AUTHORITATIVE alias + RECONCILED fill + 1 emission | SPEC |
| C→T1/T2 | UPG-06: SPLIT — 2 fills, cumulative conservation enforced, 2 emissions | SPEC |
| no candidate / contradiction | UPG-07: NO_CANDIDATE quarantine persists; UPG-08: CONTRADICTED — T1 row retained + flagged, operator-only resolution | SPEC |
| concurrent upgrade | UPG-09: two workers C→T1 (case 58) — exactly-once emission, both lineage rows | SPEC |
| stale/correction ordering | ORD-01: stale-after-newer rejected with evidence (case 51); ORD-02: correction-after-stale applied (case 52) | SPEC |
| no authoritative ordering | ORD-03: UNRESOLVED ⇒ quarantined, current content kept, re-evaluated on new authority (case 53); ORD-04: S1 beats receipt order; ORD-05: equal S2 timestamps ⇒ UNRESOLVED | SPEC |
| exact 17-status mapping | GOV-02: parametrized 17 rows (§3.2) ⇒ verbatim status/event/OrderFacts/metadata; GOV-03: unknown token ⇒ REJECTED + raw preserved; GOV-04: `rejected by rms` prose preserved as metadata, never a status; no Upstox status ⇒ ORDER_EXPIRED | SPEC |
| cross-implementation fingerprint determinism | FPV-01: key-order independence (case 55); FPV-02: shared Python/TS test vectors — byte-identical canonical JSON and digests; FPV-03: null≡absent; FPV-04: `""`≠null (case 56); FPV-05: numeric normalization incl. Decimal-vs-float hazard (case 57) | SPEC |

---

## 11. Remaining limitations (explicit)

1. **Composite equivalence still cannot prove SAME** without provider trade ids (unchanged): identical `(order_id, ts, qty, price)` composites are quarantined AMBIGUOUS; no emission without corroboration.
2. **Trade-id-less segments** can never reach an authoritative fill identity; cumulative flows at order level; individual fill events withheld unless operator-mapped (unchanged).
3. **`ORDER_PROCESSING` is still unimplemented** in `BrokerEventType` (`__init__.py:21-35`); until Day40's additive Task1 change lands, §3.2 rows 3–12 have no runtime canonical event type. This memo does not implement it.
4. **The Task1 additive change (§2.5) and Task2 verification hook are specified, not implemented.** Until they land, Task3 has no channel to supply CEID — Foundation remains NOT CLEARED by construction.
5. **Cross-channel reconstruction (§2.8)** is a Task3 obligation relying on stored first-delivery identity fields; channels that cannot reproduce them require the quarantine path.
6. **Upstox `exchange_timestamp` is second-precision**: same-second content conflicts are UNRESOLVED unless S1/S3 apply.
7. All tests are SPEC; none executed. Foundation green requires: Task1 additive change + Task2 verification hook + ledger/alias migrations + independent verification pass — none performed here.

---

## 12. Final gate

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | No Day38 change; `ORDER_ACCEPTED → None` projection-only retained (`ingestion.py:124-147`); fold semantics untouched |
| Task1 | 🟡 REVISION REQUIRED | Additive `canonical_event_id` field + format validation + property short-circuit specified (§2.5); NOT implemented; existing behavior guaranteed unchanged (§2.6) |
| D1 | 🟢 APPROVED | Correlation-only identity reaffirmed; explicitly not event identity, not ledger PK (§2.1, §2.3) |
| Canonical ID | 🟡 SINGLE CONTRACT DEFINED | ONE implementable contract (Invariant N): CEID derivation + Option B mechanism; 🟡 because the additive Task1 change is unimplemented — Day40.2's 🟢 was premature (no mechanism existed) |
| Fill Identity | 🟡 YELLOW | TRADE_ID path deterministic; composite path fail-closed AMBIGUOUS (provider limitation) |
| Fill Ledger | 🟢 APPROVED | Mutability classes explicit (§7); Day40.2 §4 state machine + transaction contract retained |
| Identity Upgrade | 🟢 APPROVED | PK contradiction eliminated — immutable alias model (§4); original observations preserved through every transition |
| Ordering Authority | 🟡 DEFINED, NOT IMPLEMENTED | Authority ladder S1–S4 + UNRESOLVED quarantine (§5); receipt order excluded outright (Invariant P) |
| Fingerprint Determinism | 🟡 SPECIFIED | FPv2 canonical serialization (§6) with cross-implementation vector requirement; vectors not yet produced |
| Status Inventory | 🟢 APPROVED (CORRECTED) | Exact 17 rows verified against the current official appendix this session (§3); Day40.2 §6.3 superseded |
| Source-of-Truth Governance | 🟢 APPROVED | Day40.2 §6.1/§6.2 retained; Day40.2-supersessions table (§2.9); Day39 §8 example amendment still pending approval |
| Task3 Design | 🟡 YELLOW | Consistent with the actual Task1 runtime model (§2); quarantine limitations documented; not independently verified |
| **Task3 Implementation** | **🔴 LOCKED** | **Task3 implementation authorization: NOT GRANTED** |
| Foundation | 🟡 **NOT CLEARED** | Requires: Task1 additive change + Task2 verification hook + ORDER_PROCESSING + alias/ledger migrations + SPEC implementation + independent verification pass. **NOT GREEN.** |

```
Task3 implementation authorization: NOT GRANTED
```

---

## 13. Safety report

- **BASELINE:** implementation authority `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`; HEAD at session start `e440250` (Day40.2). Pre-existing unrelated working-tree modifications (upstox adapter/mapper/services/tests) were observed and left untouched.
- **DAY40.3 MEMO:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-3-final-identity-contract-correction-memo.md` (this file)
- **FILES CHANGED:** one memo added (this file); no other file created, modified, or deleted
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (design only; the Upstox appendix was re-verified from the official documentation)
- **COMMIT:** single memo commit (see git output); only this memo staged — no code, tests, migrations, or other docs included
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 NOT CLEARED (Foundation) — per gate rules; NOT GREEN
- **TASK3 STATUS:** 🔴 LOCKED — Task3 implementation authorization: NOT GRANTED
