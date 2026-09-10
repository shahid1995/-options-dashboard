# Day40.6 — Final Raw-Ingress, Lane-A Soundness, and Provider-Evidence Correction Memo

**Session type:** DESIGN CORRECTION ONLY
**Status:** Correction — supersedes Day40.5 `fc76b90` on raw-ingress durability, Lane-A dedup soundness, and delivery-evidence authority; all other Day40.5 provisions remain in force
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`
**HEAD at session start:** `fc76b90` (Day40.5)
**Day40.5 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-5-no-id-fill-boundary-correction-memo.md`
**Day40.4 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-4-identity-boundary-correction-memo.md`
**Provider-verification sources (fetched 2026-09-10, official):** Portfolio Stream Feed (`get-portfolio-stream-feed`), Get Trade History (`get-trades-for-day`), Order Status Appendix
**Deliverable:** this memo ONLY. No production code, no tests, no migrations, no modifications to existing contract files.

---

## 0. The three findings, accepted

1. **Preservation-by-construction was overstated.** Day40.5 §2.3 inserted the raw fill row "first" but inside the same transaction as classification/emission (Day40.5 §7 inherited Day40.2 §4.1's single-transaction contract). A downstream rollback erases the raw row: "insert first" is not "durably preserved." Corrected by a two-phase boundary (§1).
2. **Lane A's dedup soundness was asserted, not proven.** The proof offered ("one live status per order") is insufficient — a single status can coexist with materially different snapshots (pending_quantity drained, price modified, tag changed). Corrected by a complete field review of the authoritative order-update payload, an explicit canonical semantic projection, and a completeness proof with a schema-drift guard (§3–§5).
3. **"Delivery evidence" conflated provider truth with system-local bookkeeping.** A recovery cursor proves *we fetched this position before*; it does not prove *the provider emitted one economic event*. Corrected by an evidence-authority matrix (§6) and the current-data boundary (§7).

---

## 1. Durable raw-ingress boundary (two-phase; Invariants AB/AC)

### 1.1 Conceptual model (adopted as specified)

```
PROVIDER DELIVERY (websocket frame / REST response / webhook POST)
   ↓
PHASE 1 — RAW INGEST COMMIT        [transaction 1: raw only]
   INSERT broker_raw_observation (raw_observation_id UUID, tenant, broker,
   received_at, source_mode, raw_payload_bytes, delivery evidence,
   order_id/trade_id if trivially extractable, ingestion_status=RAW_RECEIVED,
   processing_status=PENDING, created_at)
   COMMIT                          ← touches NOTHING else; no parsing required
   ↓ durable observation exists (PostgreSQL WAL-durable)
PHASE 2 — PROCESSING               [transaction 2..n: everything else]
   claim row (FOR UPDATE SKIP LOCKED) → normalize → lane route → dedup →
   construct events → Task2 → emission → projection inputs
   processing_status advanced; failures recorded ON the raw row, never erasing it
```

**The five questions, answered:**

- **A. What transaction commits the raw payload?** Phase 1's dedicated transaction, whose only write is the raw row. No normalization, classification, gate, ledger, Task2, or emission work participates.
- **B. Can downstream failure roll back the raw payload?** No. Phase 2 runs in separate transaction(s) after Phase 1 has committed. Any Phase-2 failure (normalization, dedup, Task2, projection feed) marks `processing_status=FAILED` + `last_error` on the already-committed raw row; the raw bytes are untouched (Invariant AC).
- **C. Crash immediately after raw insert — does the observation remain?** Yes, once Phase 1's COMMIT returns. If the process crashes *during* Phase 1 (before COMMIT), the payload was never accepted by the ingestion boundary and the channel's at-least-once redelivery re-ingests it; there is no half-preserved state.
- **D. Crash before downstream processing — how is it resumed?** A recovery scan/claim loop selects rows with `processing_status ∈ {PENDING, FAILED}` (and stale `IN_PROGRESS` leases) using `FOR UPDATE SKIP LOCKED`, and re-enters Phase 2. Resumption is at-least-once; safety comes from idempotent Phase-2 effects (E).
- **E. Can the same raw observation be processed more than once safely?** Yes. Reprocessing re-derives the same D1/FPv2 from the same raw bytes; every downstream effect is idempotent by key: Lane-A gate UNIQUE (same ⇒ duplicate no-op), Task2 `canonical_id` PK (same ⇒ `DUPLICATE_NOOP`), fill-ledger PK arbitration, alias/lineage append-with-audit. `attempt_count` increments; no duplicate business effect is possible.
- **F. Relationship raw ↔ attempts ↔ canonical events ↔ projection?** `raw_observation_id` is 1:N to processing attempts and 0..N to canonical events (one payload may canonicalize into zero events — duplicate/stale/quarantined — or into several, e.g. an order observation plus an explicit fill observation, §8-8). The projection folds **canonical events only**; raw rows are input evidence, never projection sources, never derived from downstream state.

**Why single-transaction retention is rejected (not merely renamed):** keeping raw+classification in one tx makes preservation conditional on downstream success — exactly the violation the audit identified. The Day40.2 §4.1 LOCK→…→COMMIT contract and Day40.4 §3.3's gate transaction are **retained as the Phase-2 transaction contract**; Day40.5's "raw insert first" is corrected to "raw commit is Phase 1, before the Phase-2 transaction begins."

### 1.2 Supersessions

| Prior text | Verdict |
|---|---|
| Day40.5 §2.3 "raw row … ALWAYS, first" (same tx) | **Superseded** — raw commit is its own Phase-1 transaction |
| Day40.4 §3.3 gate+Task2 single tx | **Retained** as Phase 2 only |
| Day40.2 §4.1 ledger transaction contract | **Retained** as Phase 2 only |
| Day40.5 §6 "raw observation → ledger observation" | **Refined** — fill-domain ledger observation is a Phase-2 derived record linked to `raw_observation_id` (§2) |

---

## 2. Raw-ingest schema contract (minimum durable structure)

```
broker_raw_observation
  raw_observation_id  UUID  PRIMARY KEY           -- immutable surrogate
  tenant_id, broker
  received_at          TIMESTAMPTZ                -- boundary acceptance time
  source_mode          ('STREAM'|'RECOVERY'|'POLLED_SNAPSHOT'|'WEBHOOK')
  raw_payload          JSONB / BYTEA              -- verbatim provider bytes/payload
  delivery_evidence    JSONB (nullable)           -- §6-matrix entries, with class labels
  provider_order_id    TEXT (nullable)            -- if trivially extractable pre-normalization
  provider_trade_id    TEXT (nullable)            -- if trivially extractable pre-normalization
  d1                   CHAR(64) (nullable)        -- set when derived SAFELY (post-parse)
  content_fingerprint  CHAR(64) (nullable)        -- FPv2/FPv2-A, set when derived SAFELY
  ingestion_status     ('RAW_RECEIVED'|'RAW_NORMALIZED'|'RAW_CLASSIFIED'|'CANONICALIZED'|
                        'NORMALIZATION_FAILED'|'CLASSIFICATION_FAILED')
  processing_status    ('PENDING'|'IN_PROGRESS'|'SUCCEEDED'|'FAILED'|'QUARANTINED')
  attempt_count        INTEGER DEFAULT 0
  last_error           TEXT (nullable)
  created_at           TIMESTAMPTZ
```

**Status distinctions:** `RAW_RECEIVED` = bytes committed, nothing parsed. `RAW_NORMALIZED` = parsed, mandatory fields extracted, D1/FPv2 derived and recorded. `RAW_CLASSIFIED` = lane routed + delivery/economic dedup decided. `CANONICALIZED` = canonical event(s) emitted/authorized. Error states keep `ingestion_status` honest (a row that failed parsing is `NORMALIZATION_FAILED`, never masquerades as normalized).

**Rules:** raw persistence does **not** depend on normalization — a `RAW_RECEIVED` row with unparsed bytes is a complete, replayable evidence record. `d1`/`content_fingerprint` are nullable precisely because a payload that cannot be safely parsed must still be preserved without them. No UPDATE ever touches `raw_payload`, `raw_observation_id`, `received_at`, or provenance columns; only status/attempt/error columns are mutable (the mutable-column discipline of Day40.3 §7, class B/D style, applied to this table).

---

## 3. Raw payload survives normalization failure (Invariant AC)

Exhaustive handling — every failure class leaves the raw record intact and replayable:

| Failure | Phase-1 result | Phase-2 result | Raw record after |
|---|---|---|---|
| Malformed provider payload (unparseable JSON/bytes) | committed (`RAW_RECEIVED`) | parse exception → `NORMALIZATION_FAILED`, `last_error` set | **preserved verbatim**; replay/adjudication possible; no D1/FPv2 (null) |
| Missing mandatory fields (e.g. no `order_id`, no `status`) | committed | normalization error → `NORMALIZATION_FAILED` | preserved; operator/replay after provider clarification |
| Unknown provider status token (not in the 17-row inventory) | committed | parse OK; lane routing **fails closed** → `CLASSIFICATION_FAILED` + quarantine flag (Day40.3 §3.3-5) | preserved with raw status token; inventory re-verification precedes any mapping |
| Invalid quantity (non-integral/negative/absent when required) | committed | normalization error → `NORMALIZATION_FAILED` | preserved; FPv2 never computed from invalid input |
| Invalid timestamp (naive/unparseable/out-of-range) | committed | normalization error (timezone-aware rule, Day40.3 §6.2) | preserved |
| Invalid decimal (non-finite, unparseable) | committed | normalization error (Decimal rule) | preserved |
| Schema drift (unknown fields, changed types, renamed fields) | committed | parse OK; **drift guard** (§4.3) → `CLASSIFICATION_FAILED`/`QUARANTINED` | preserved; field-classification review before dedup resumes |
| Normalization exception (any bug) | committed | `FAILED` + `last_error` + stack ref | preserved; fix + replay (§8, case 89) |

**Rule, verbatim:** provider bytes received → durable raw record → normalization may fail → raw record remains available for replay/adjudication. No normalization error may erase the original provider evidence.

---

## 4. Lane A soundness — complete authoritative field review (Issue 4)

### 4.1 Source of authority

The current official **Portfolio Stream Feed** order-update message (`wss://feed/portfolio-stream-feed`, `update_type=order`), fetched 2026-09-10. The documented payload contains exactly these fields (sample + field table):

`update_type`, `user_id`, `userId`, `exchange`, `instrument_token`, `instrument_key`, `trading_symbol`, `tradingsymbol` (documented as deprecated), `product`, `order_type`, `average_price`, `price`, `trigger_price`, `quantity`, `disclosed_quantity`, `pending_quantity`, `transaction_type`, `order_ref_id`, `exchange_order_id`, `parent_order_id`, `validity`, `status`, `is_amo`, `variety`, `tag`, `exchange_timestamp`, `status_message`, `order_id`, `order_request_id`, `order_timestamp`, `filled_quantity`, `guid` (present in sample; **no field-table documentation**), `placed_by`, `status_message_raw`.

Notably **absent** from the order-update stream: `trade_id`, any provider event/delivery identifier, any sequence number, `cancelled_quantity`, `status_message_raw` is present but `rejected_by_rms`-style tokens are prose, not statuses. (Trade identity exists only on the trade-history endpoint — §7.)

### 4.2 Field classification (identity / semantic / audit-only / provenance / irrelevant)

| Field | Class | In FPv2-A? | Rationale |
|---|---|---|---|
| `order_id` | IDENTITY | — (D1 component) | which order |
| `status` | semantic order-state content | YES | drives event type + OrderFacts.status |
| `quantity` | semantic | YES | `total_quantity`; modify changes it |
| `filled_quantity` | semantic | YES | fill progress; OrderFacts.cumulative_filled |
| `pending_quantity` | semantic | YES | derived state; changes with fills (case 90) |
| `average_price` | semantic | YES | OrderFacts.average_price |
| `price` | semantic | YES | modify changes it (case 91) |
| `trigger_price` | semantic | YES | SL/SL-M modify changes it (case 92) |
| `status_message` | semantic | YES | `rejection_reason` source (case 95) |
| `exchange_order_id` | semantic (identity-adjacent) | YES | exchange-assigned; ""→assigned transition; change ⇒ new observation (case 93-analog) |
| `exchange_timestamp` | semantic (provider event time) | YES | `event_timestamp`; ordering authority S2 |
| `disclosed_quantity` | audit-only | no | market-depth behavior; no canonical field maps from it; change preserved in raw |
| `tag` | audit-only | no | user tag; no canonical mapping (case 93) |
| `status_message_raw` | audit-only | no | RMS prose; metadata only; no canonical mapping |
| `validity`, `variety`, `product`, `order_type`, `transaction_type`, `exchange`, `instrument_token`, `instrument_key`, `trading_symbol`/`tradingsymbol`, `parent_order_id`, `is_amo`, `order_ref_id`, `order_timestamp`, `placed_by`, `user_id`/`userId` | order attributes — static per order lifetime (Upstox modify semantics cover qty/price/trigger/validity only; type/side/product/symbol are not modifiable in place) | no (drift-guarded) | static ⇒ cannot differ across observations of the same `order_id`; verified per-delivery by the drift guard, not assumed |
| `update_type` | lane router | no | routing decision; not order state |
| `order_request_id` | correlation-only | no | request-cycle counter (§6); no canonical mapping |
| `guid` | **UNMAPPED/undocumented** | no | not in the field table; drift-guarded: preserved raw; non-null appearance ⇒ quarantine Lane-A dedup for review |

### 4.3 The canonical semantic projection and the completeness proof (Issue 5 — **Option B**, with drift guard)

**Canonical projection:**

```
Π_A(order observation) = ( event_type, status, quantity, filled_quantity,
    pending_quantity, average_price, price, trigger_price, status_message,
    exchange_order_id, exchange_timestamp )
```

**FPv2-A ≡ Π_A exactly** (field-for-field). The Day40.3 §6.2 field list is corrected: `cancelled_quantity` is not a payload field (dropped; derived `quantity − filled − pending` when consistent, else absent); `pending_quantity`, `price`, `trigger_price`, `status_message`, `exchange_order_id` are added.

**Proof of the invariant** — `same Lane-A D1 + same FPv2-A ⇒ same semantic provider observation under Π_A`:

1. D1 fixes `(tenant, broker, order_id, event_type)` — the observation's class and order.
2. FPv2-A is computed over exactly the Π_A fields (§6.2 serializer rules unchanged).
3. Therefore equal (D1, FPv2-A) ⇒ equal Π_A values ⇒ identical canonical semantic content. Any change to a projected field — status, quantities, prices, message, exchange id, exchange time — changes FPv2-A ⇒ a different observation. **The dedup gate cannot erase a material change** (material ≡ Π_A-visible, by definition of the projection, with every OrderFacts input contained in Π_A).
4. Excluded fields cannot change Π_A: each excluded field has either (a) **no canonical mapping** (audit-only/correlation: disclosed_quantity, tag, status_message_raw, order_request_id, update_type — the §4.2 mapping table shows every canonical field's source, and none of these appear), or (b) **static-per-order** semantics (attribute class) — and staticness is not assumed: the **drift guard** compares every attribute-class field against the order's first-seen attribute set on every observation; any difference ⇒ `CLASSIFICATION_FAILED` + quarantine (Lane-A dedup suspended for that order pending review), so a schema change or provider behavior change cannot silently pass through dedup. Unmapped fields (`guid`, future additions) are drift-guarded the same way: present-and-non-default ⇒ quarantine, never dedup.

This is Option B as required — an explicit canonical projection with a proof that omitted provider fields cannot change it — hardened by the fail-closed drift guard for the "provider changes something we classified static" residue. Option A (stuff every field into the fingerprint) is rejected: it makes audit-only chatter (`tag`, `status_message_raw`, deprecated aliases) manufacture canonical corrections, eroding the correction semantics of §5. "One live status per order" is **withdrawn** as a proof; it survives only as intuition.

### 4.4 Lane-A correction semantics (Issue 6) — every listed case

| Same status, changed… | Classification | Why |
|---|---|---|
| `pending_quantity` | **CORRECTION — new observation** | ∈ Π_A; fill progress changed; fold update; may also spawn the explicit fill observation (§8-8) |
| `price` | **CORRECTION — new observation** | ∈ Π_A; modify ack semantics |
| `trigger_price` | **CORRECTION — new observation** | ∈ Π_A |
| `exchange_order_id` | **CORRECTION — new observation** + review flag | ∈ Π_A; identity-adjacent; a change without a status transition is anomalous |
| `tag` | **AUDIT-ONLY change** | ∉ Π_A; raw record preserves both payloads; no new canonical observation; a modify that changed the tag also changes status/price ⇒ observed there |
| `order_request_id` | **AUDIT/correlation-only change** | ∉ Π_A; request-cycle marker; raw preserved; no canonical observation |
| `status_message` | **CORRECTION — new observation** | ∈ Π_A (projected to `rejection_reason`); any content change ⇒ new fingerprint |

No dedup decision can erase a material change: material ≡ Π_A-visible; every Π_A field is fingerprinted.

---

## 5. Provider delivery-evidence matrix (Issue 7; Invariant AE)

| Evidence source | Class | Delivery-proof scope | Current-data status |
|---|---|---|---|
| `provider_event_id` | **A** — provider-authoritative **iff documented as delivery-scoped & unique** | same delivery | Upstox order stream: **no such field** → FUTURE PROVIDER CAPABILITY; must not be contracted as current |
| `provider_sequence` | **A** iff provider documents delivery ordering | same delivery | Upstox: **not documented** → FUTURE |
| Recovery cursor (our fetch/window token) | **B** — system-local delivery reference | "we ingested this position before" — suppresses OUR re-ingest only | INTERNAL STRIKENOVA MECHANISM |
| Websocket offset/frame index | **B** | local stream position only (Upstox documents no delivery offsets) | INTERNAL |
| Order-history row position | **B** | position in OUR enumeration of a provider-authoritative record set; record content is provider truth, position is ours | INTERNAL indexing of SUPPORTED-TODAY data |
| Trade-history row position | **B** | same | INTERNAL indexing of SUPPORTED-TODAY data |
| `exchange_timestamp` | **C** — correlation only | equal times do not prove same delivery; it IS ordering authority S2 for corrections (Day40.3 §5) | SUPPORTED TODAY (as ordering signal, not delivery id) |
| `order_request_id` | **C** | request-cycle marker, not delivery identity | SUPPORTED TODAY (as correlation) |
| `order_ref_id` | **C** | order-scoped internal id; stable per order; never delivery-scoped | SUPPORTED TODAY (as order correlation) |
| `exchange_order_id` | **C** (for delivery) | provider-authoritative ORDER identity, not delivery identity | SUPPORTED TODAY (as order identity) |
| `trade_id` | **D for delivery evidence** — scope mismatch (economic, not delivery); simultaneously **A-class ECONOMIC identity** | proves the trade, never the delivery | **SUPPORTED TODAY on trade-history** ("Trade ID generated from exchange"); absent from the order stream |
| Local arrival timestamp | **D** | never | INTERNAL provenance |
| Worker ID | **D** | never | INTERNAL |
| Consumer offset | **B** | local consumption position only | INTERNAL |

**The distinction, explicit (Invariant AE):** a class-B reference may prove *"we fetched/received this stream position before"* — sufficient to suppress our own duplicate ingest work — but does **not** prove *"the provider emitted one economic event here."* Only class-A evidence (documented provider delivery identity) supports delivery-scoped claims about provider behavior; and for Upstox today, **no class-A delivery evidence exists** on either channel. A class-B token must never be persisted, logged, or reasoned about as "provider identity"; it carries its class label in `delivery_evidence` JSONB.

---

## 6. Upstox current-data boundary (Issue 8)

| Capability | Status | Consequence |
|---|---|---|
| `trade_id` on fills | **SUPPORTED TODAY — trade-history endpoint only** | Lane B (identifiable fills) is realizable **from trade history**; order-stream fill progress never carries `trade_id` |
| `trade_id` in the order-update stream | **NOT SUPPLIED** | stream-derived fill observations are always Lane C |
| Provider event identity (order updates or fills) | **NOT SUPPLIED** | FUTURE PROVIDER CAPABILITY — must not be contracted as current |
| Provider delivery sequence | **NOT SUPPLIED** | FUTURE |
| Stable provider delivery identity | **NOT SUPPLIED** | FUTURE |
| Recovery cursor / consumer offsets / worker ids | **INTERNAL STRIKENOVA MECHANISM** | class B forever; never "provider truth" |

**Current no-ID path (binding):** for any fill whose trade_id is absent (all order-stream-derived fill progress today, and any trade-history row lacking trade_id):

```
NO TRADE_ID + NO AUTHORITATIVE DELIVERY IDENTITY
→ RAW PRESERVE (Phase 1 commit)
→ equivalence unprovable ⇒ AMBIGUOUS
→ NO ECONOMIC CANONICAL FILL
```

This is the Day40.5 §6 fail-closed conclusion, now grounded in the verified current-data boundary rather than assumption. Day40.5 §3's delivery-evidence classes remain *defined* for the day a provider supplies class-A evidence; **today they are vacuous for Upstox** (except internal class-B references, which deduplicate only our own ingest work — §7 cases 96/97).

---

## 7. Duplicate delivery vs raw preservation, precisely ordered (Invariant AF)

```
RAW PAYLOAD → DURABLE COMMIT (Phase 1) → delivery classification (Phase 2)
→ economic reconciliation (Phase 2)
```

A duplicate-delivery classification may suppress **downstream economic processing** — it MUST NOT suppress raw evidence. A proven duplicate retains: `raw_observation_id`, `duplicate_of` pointer, delivery evidence **with its class label**, provenance (`source_mode`, `received_at`), and the raw payload. Under the two-phase boundary this holds by construction: the duplicate decision is a Phase-2 status write on an already-committed Phase-1 row. Day40.5 §3's rule (duplicate ≠ economic identity) is preserved verbatim; its durability is upgraded from "insert-first-in-tx" to "committed-before-classification."

**Class-B dedup caveat (new, precise):** an internal recovery cursor may legitimately suppress *re-ingest of the same stream position* (case 96) — that is bookkeeping about our own pipeline. It must never suppress a *new provider payload* that happens to arrive at a position we associate with the past (case 97): class-B equality plus payload difference ⇒ the payload difference wins (new raw row, drift/equivalence evaluation), because the cursor is not provider truth.

---

## 8. Concurrency under the durable-ingress boundary (Issue 10)

| # | Case | Raw rows | Locks / tx boundaries | Retry | Dedup | Economic effect | Canonical effect |
|---|---|---|---|---|---|---|---|
| 1 | Same provider delivery, two workers | Phase 1 insert-always ⇒ 2 raw rows (or 1 if a delivery-debounce UNIQUE is enabled for a token-carrying channel — optional, class-B or A labeled) | Phase-1 txs independent; Phase 2 claims rows via SKIP LOCKED | redelivery re-ingested, then classified | Phase-2 delivery classification links `duplicate_of` | one economic effect (second suppressed at delivery layer) | zero or one canonical event (first only) |
| 2 | Two distinct no-ID fills, same attributes | 2 raw rows (Phase 1 never dedups) | independent txs; Phase-2 equivalence vs composite C | n/a | none (no class-A evidence) | composite C AMBIGUOUS, observed_count=2 (Day40.5 §4B) | none |
| 3 | Raw commit succeeds, worker crashes | 1 raw row `PENDING` | Phase 1 already committed; Phase-2 lease expires | recovery scan re-claims (at-least-once) | reprocessing is idempotent (idempotent Phase-2 keys) | eventual, exactly-once effect | eventual, exactly-once |
| 4 | Raw commit succeeds, canonicalization fails | 1 raw row, `NORMALIZATION_FAILED`/`CLASSIFICATION_FAILED` + `last_error` | Phase-2 tx rolls back its effects; status write commits in its own small tx | replay after fix (case 89) | re-evaluated on replay | none until success | none until success |
| 5 | Duplicate delivery detected after both raw rows committed | 2 raw rows, both retained | Phase-2 classification under row lock | n/a | `duplicate_of` pointer written; AF satisfied | one economic effect | first delivery's canonical event only |
| 6 | Same raw observation reprocessed | same row, `attempt_count++` | SKIP LOCKED claim (two concurrent reprocessors: one waits/wins, then re-reads) | idempotent | Lane-A gate / Task2 PK / fill PK all no-op on replay | unchanged | unchanged (no second event) |
| 7 | Same identifiable trade (trade_id from history) arrives concurrently | 2 raw rows (one per delivery/record) | Phase-2 fill-ledger PK arbitration (Day40.2 §4.3A) | loser re-reads RECONCILED → no-op | economic dedup by trade identity | one fill row | exactly one fill event |
| 8 | One provider payload ⇒ order observation + explicit fill observation | **1 raw row** (shared input evidence) | Phase 2 derives both observations in the payload's processing tx (or sequential txs, both linked to the raw row) | replay re-derives both; each path idempotent by its own keys | each observation classified in its own lane (A / C per Day40.5 §2) | fill observation evaluated per Lane C | up to two canonical observations, each with own D1/FPv2, both referencing the same `raw_observation_id` |

---

## 9. Formal invariants AB–AF (added to A–H, I–M, N–R, S–W, X–AA)

| # | Invariant | Defense | SPEC tests |
|---|---|---|---|
| **AB** — durable raw preservation | Once a provider payload is accepted by the ingestion boundary (Phase-1 COMMIT), its raw evidence survives all downstream failures | §1 two-phase boundary; Phase-1 tx contains only the raw row | RAW-01..03 |
| **AC** — normalization-failure preservation | A normalization failure cannot erase or roll back the raw provider evidence | §3 failure table; status-only mutation of raw rows | RAW-04..05 |
| **AD** — Lane-A fingerprint soundness | Lane-A dedup may only collapse observations when the fingerprint represents the complete semantic observation under the defined canonical projection | §4.3 Π_A = FPv2-A; completeness proof; drift guard | LNA-01..03 |
| **AE** — provider-evidence provenance | A system-local delivery reference cannot be represented as provider-authoritative identity unless the provider contract explicitly establishes it | §5 matrix with class labels persisted in `delivery_evidence`; class-B suppression bounded to re-ingest | EVD-01..03 |
| **AF** — duplicate preservation | A duplicate delivery may suppress downstream processing but can never delete or overwrite raw evidence | §7 ordering; duplicate keeps payload + pointer + provenance | DUP-01 |

---

## 10. Adversarial cases 86–104

Columns: raw identity · delivery identity · economic identity · D1 · FPv2 · processing state · dedup result · canonical effect · projection · recovery path. Cases 1–85 remain in force; fill-lane cases (74–85) now execute over the two-phase boundary (raw rows = Phase-1 commits; equivalence = Phase 2).

| # | Input | Raw identity | Delivery identity | Economic identity | D1 | FPv2 | Processing state | Dedup result | Canonical effect | Projection | Recovery path |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 86 | raw commit succeeds, worker crashes | committed, `PENDING` | n/a yet | n/a | set post-parse | set post-parse | `IN_PROGRESS` lease expires | none | none yet | unchanged | recovery scan re-claims; idempotent Phase 2 |
| 87 | raw normalization fails (invalid decimal) | committed, `NORMALIZATION_FAILED` | n/a | n/a | null (not safely derivable) | null | `FAILED` + last_error | none | none | unchanged | fix normalizer; replay from raw bytes |
| 88 | unknown provider status token | committed | n/a | n/a | order D1 derivable | not computed (fail-closed) | `CLASSIFICATION_FAILED` + quarantine | none | none | unchanged | inventory re-verification → operator/replay |
| 89 | raw record replay (operator/replay after fix) | same raw_observation_id | as recorded | as recorded | re-derived | re-derived | `attempt_count++` → `CANONICALIZED` | re-evaluated, idempotent | same as fresh processing (no dup by keys) | folds once | replay loop |
| 90 | Lane A: same status, changed pending_quantity | 2 raw rows | none (Upstox) | n/a | same | **different** | both `RAW_CLASSIFIED` | 2nd = new observation (Π_A changed) | CORRECTION event | fold update | n/a (correct behavior) |
| 91 | Lane A: same status, changed price | 2 raw rows | none | n/a | same | different | as 90 | new observation | CORRECTION event | fold update | n/a |
| 92 | Lane A: same status, changed trigger_price | 2 raw rows | none | n/a | same | different | as 90 | new observation | CORRECTION event | fold update | n/a |
| 93 | Lane A: same status, changed tag | 2 raw rows | none | n/a | same | **same** (tag ∉ Π_A) | `CANONICALIZED` | audit-only change — no new observation | none | unchanged | raw rows retain both payloads (AF) |
| 94 | Lane A: same status, changed order_request_id | 2 raw rows | none (correlation-only) | n/a | same | same | `CANONICALIZED` | audit/correlation-only | none | unchanged | raw retained |
| 95 | Lane A: same status, changed status_message | 2 raw rows | none | n/a | same | different (∈ Π_A) | `RAW_CLASSIFIED` | new observation | CORRECTION event (rejection_reason updated) | fold update | n/a |
| 96 | system-local cursor repeated (same position, same payload) | 1 raw row (re-ingest suppressed) — or 2nd raw row if insert-always; both retained | **B-class** reference | n/a | same | same | `SUCCEEDED` | class-B re-ingest dedup only | none (already processed) | unchanged | cursor bookkeeping |
| 97 | same cursor ref, **different** provider payload | 2 raw rows — payload difference wins | B-class (never provider truth) | n/a | differ (or same D1, diff FP) | different | `RAW_CLASSIFIED` | NOT suppressed (AE) | per lanes (correction if Lane A) | folds per content | n/a |
| 98 | history row reused/changed across fetches | raw per fetch; record identity labeled B-class | B-class position + provider record content | per content | per content | per content | `RAW_CLASSIFIED` | content equality ⇒ dedup at record scope; content change ⇒ correction | per lane | folds per content | content, not position, decides |
| 99 | raw duplicate with proven delivery identity (future class-A) | 2 raw rows | **A-class** proven same | n/a | same | same | `CANONICALIZED` | DUPLICATE (delivery-scoped); `duplicate_of` | first only | unchanged | both raw rows retained (AF) |
| 100 | raw duplicate without delivery identity (today's default) | 2 raw rows — never deduped | ABSENT | n/a | same | same | `RAW_CLASSIFIED` | NOT duplicate (no evidence) | Lane A: 2nd is new observation iff Π_A changed, else audit-only; Lane C: distinct observations | per content | n/a |
| 101 | same raw observation reprocessed concurrently | 1 row | as recorded | as recorded | same | same | SKIP LOCKED serializes; `attempt_count` reflects both | idempotent no-op | none (keys hold) | unchanged | claim/lease loop |
| 102 | raw commit succeeds, Task2 fails | committed | as recorded | as recorded | set | set | `FAILED` (phase=task2) | gate row state intact per its own tx | none | unchanged | replay; Task2 PK idempotency on retry |
| 103 | raw commit succeeds, projection feed fails | committed, `CANONICALIZED` | as recorded | as recorded | set | set | event committed; projection rebuilds by fold | n/a | event durable | rebuilt by replay fold (Day38) | projection rebuild from canonical stream |
| 104 | one payload ⇒ order observation + explicit fill observation | 1 raw row shared | none | fill: composite C candidate | two D1s | two FPv2s | `CANONICALIZED` | each lane independently (A order; C fill) | order event (+ fill event only if provable) | order state updates; fill only if identity proven | replay re-derives both from raw |

---

## 11. Test specification — SPEC only

No tests added or executed. Existing suites must pass unmodified (Day40.4 §2.4 criterion stands).

| Area | Test | Status |
|---|---|---|
| durable raw-ingest crash recovery | RAW-01: Phase-1 commit ⇒ crash ⇒ row present; RAW-02: recovery scan re-claims PENDING/FAILED; RAW-03: reprocessing idempotent (case 101) | SPEC |
| normalization-failure preservation | RAW-04: each §3 failure class ⇒ raw bytes intact + status honest; RAW-05: no D1/FPv2 fabrication from unparsed input | SPEC |
| replay of durable raw observation | RAW-06 (case 89): replay re-derives identical D1/FPv2; canonical effects dedup by keys | SPEC |
| Lane-A field completeness | LNA-01: Π_A ≡ FPv2-A field set against the 34-field payload inventory (§4.1–4.2); LNA-02: every excluded field has a mapping proof or drift guard (§4.3) | SPEC |
| Lane-A omitted-field semantics | LNA-03: cases 90–95 classifications hold; drift guard quarantines attribute/mapped-field changes (guid non-null ⇒ quarantine) | SPEC |
| provider-evidence classification | EVD-01: matrix classes (§5) asserted per source; EVD-02: class-B labels persisted and never rendered as provider identity; EVD-03 (case 97): cursor match + payload difference ⇒ payload wins | SPEC |
| local-vs-provider identity | EVD-02/03 (shared) | SPEC |
| duplicate preservation | DUP-01 (cases 99/100): duplicate keeps raw_observation_id, duplicate_of, evidence+class, provenance, payload | SPEC |
| concurrent raw ingestion | CON-R1: two workers, same delivery (case 1); CON-R2: two distinct no-ID fills (case 2) ⇒ 2 raw rows, AMBIGUOUS | SPEC |
| Task2 failure after raw commit | T2F-01 (case 102): raw retained; replay succeeds; no duplicate emission | SPEC |
| projection failure after raw commit | PJF-01 (case 103): canonical event durable; projection rebuilt by fold | SPEC |

---

## 12. Deliverable

This memo only: `docs/superpowers/contracts/2026-09-10-strikenova-day40-6-final-raw-ingress-and-lane-a-soundness-correction-memo.md`. No code, tests, migrations, or modifications to existing contract files.

---

## 13. Final gate

| Area | Gate | Evidence |
|---|---|---|
| **Raw Ingress Durability** | 🟡 DEFINED (two-phase) | §1: Phase-1 commit precedes all downstream; crash/rollback windows answered A–F; not implemented |
| **Normalization-Failure Preservation** | 🟡 DEFINED | §3 exhaustive failure table; status honesty rules; not implemented |
| **Lane A Soundness** | 🟡 PROVEN AT DESIGN LEVEL | §4: complete 34-field review; Π_A = FPv2-A; Option-B completeness proof + drift guard; "one live status" proof withdrawn |
| **Provider Evidence** | 🟡 CLASSIFIED | §5/§6: A/B/C/D matrix; current-data boundary verified from official docs; no class-A delivery evidence exists for Upstox today |
| **No-ID Fill Safety** | 🟢 MODEL CORRECTED (fail-closed) | §6: no trade_id (stream) + no delivery identity ⇒ RAW PRESERVE → AMBIGUOUS → NO ECONOMIC CANONICAL FILL; trade_id supported today only via trade history (Lane B) |
| **Duplicate Preservation** | 🟡 DEFINED | §7: AF holds by construction under two-phase ordering |
| **Concurrency** | 🟡 DEFINED | §8: eight cases with rows/locks/tx/retry/dedup/effects |
| Task3 Design | 🟡 YELLOW | Internally consistent across Day40.2–40.6; not independently verified |
| **Task3 Implementation** | **🔴 LOCKED** | **Task3 implementation authorization: NOT GRANTED** |
| Foundation | 🟡 **NOT CLEARED** | The six §15 conditions are designed, not implemented: raw evidence survives downstream failure (§1/§3), Lane-A dedup cannot erase material changes (§4.3), provider-vs-local evidence separated (§5), no-ID fills fail-closed (§6), duplicate preservation guaranteed (§7), concurrency preserves distinctions (§8). **NOT GREEN.** |

```
Task3 implementation authorization: NOT GRANTED
```

---

## 14. Safety report

- **BASELINE:** implementation authority `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`; HEAD at session start `fc76b90` (Day40.5)
- **DAY40.6 MEMO:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-6-final-raw-ingress-and-lane-a-soundness-correction-memo.md` (this file)
- **FILES CHANGED:** one memo added (this file); no other file created, modified, or deleted
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (design only; provider payload fields were verified from the current official Upstox documentation)
- **COMMIT:** single memo commit (see git output); only this memo staged — no code, tests, migrations, or other docs included
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 NOT CLEARED (Foundation) — NOT GREEN
- **TASK3 STATUS:** 🔴 LOCKED — Task3 implementation authorization: NOT GRANTED
