# Day40.5 — Final No-Trade-ID Fill Gate Correction Memo

**Session type:** DESIGN CORRECTION ONLY
**Status:** Correction — supersedes Day40.4 `f18c9eb` on the pre-Task2 gate's treatment of no-trade-id economic fills; all other Day40.4 provisions remain in force
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`
**HEAD at session start:** `f18c9eb` (Day40.4)
**Day40.4 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-4-identity-boundary-correction-memo.md`
**Day40.3 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-3-final-identity-contract-correction-memo.md`
**Deliverable:** this memo ONLY. No production code, no tests, no migrations were modified in this session.

---

## 0. The regression, stated exactly

Day40.4 §3.2/§3.3 defined ONE universal pre-Task2 gate with `UNIQUE (tenant_id, broker, d1, content_fingerprint)` and classified any repeated `(D1, FPv2)` as `DUPLICATE_DELIVERY` → no second `BrokerSyncEvent` → no Task2 call. For no-trade-id economic fills this is **unsound**:

```
Fill A: order=O1, trade_id="", timestamp=T, quantity=5, price=100
Fill B: order=O1, trade_id="", timestamp=T, quantity=5, price=100
```

A and B may be **two genuinely distinct economic executions** whose observable attributes are identical (identical second-precision timestamps, equal quantities, equal prices). They produce identical D1 (same order, same fill class, empty trade_id) and identical FPv2 (same content). Under the Day40.4 gate: Fill A → gate row; Fill B → `DUPLICATE_DELIVERY` → STOP. The second execution **never reaches `broker_fill_ledger`** — its evidence is collapsed into `delivery_count=2` on one row. That silently merges two real fills, violating the fail-closed no-merge requirement (Day40.1 §4; Day40.2 §11.1) that all prior memos preserved.

Root cause: **observation equivalence was conflated with economic-fill equivalence.** `(D1, FPv2)` proves "the provider reported the same content" — it does NOT prove "these are deliveries of one economic event." The equivalence is sound only where the semantic domain guarantees that identical reported content implies one observation. Order-lifecycle snapshots have that property (one live status per order at a time; a redelivery is the same status snapshot). No-ID fills do not (two executions are simultaneously real with equal attributes).

---

## 1. Executive decision

1. **Lane split (Issue 3):** the single pre-Task2 gate is replaced by three lanes — (A) order observations: D1+FPv2 delivery dedup **retained**; (B) identifiable fills (trade_id present): dedup by **economic identity** (trade_id), never by delivery dedup; (C) no-ID fills: **no delivery dedup at all** — every payload becomes an immutable raw observation first, then economic equivalence is evaluated, and AMBIGUOUS when unprovable (§2).
2. **Delivery evidence (Issue 4):** a no-ID fill is `DUPLICATE` only on a provable **delivery identity** (stable provider event/delivery id, provider sequence, recovery cursor/event reference, authoritative history row identity). Observable attributes (timestamp/qty/price/D1/FPv2) are correlation candidates only — never proof (§3).
3. **Case A vs Case B (Issue 5):** same delivery delivered twice → dedup at the delivery layer, no duplicate economic fill; two distinct no-ID fills with identical attributes → **both observations preserved, AMBIGUOUS, no canonical emission, never one gate row with delivery_count=2** (§4).
4. **Raw observation identity (Issue 6):** `broker_fill_ledger_observation.observation_id` is an immutable surrogate UUID and the **sole PK**; `(D1, FPv2)` is never the sole identity of an unknown economic fill; the Day40.4 gate's UNIQUE is **struck** for fill-lane routing (§5).
5. **Ledger boundary (Issue 7):** the four-layer architecture is made explicit — `broker_sync_observation` dedups only provable-identity deliveries; `broker_fill_ledger_observation` preserves every raw fill observation; `broker_fill_ledger_fill` holds economic identity; alias/lineage maps provisional to authoritative (§6).
6. **Concurrency (Issue 8):** six scenarios analyzed; the raw-insert-first ordering plus Day40.2 §4.1/§4.3 contracts yield exactly-once for identifiable fills, distinct-row preservation for concurrent identical no-ID fills (§7).
7. Invariants X, Y, Z, AA (§8); adversarial cases 74–85 (§9); SPEC tests (§10); final gate (§11).

**Corrected rule (the memo in one sentence):** *duplicate delivery is a statement about deliveries and requires delivery evidence; a fill is an economic event and requires economic identity; `(D1, FPv2)` establishes neither for a no-ID fill.*

---

## 2. Three lanes through the boundary (supersedes Day40.4 §3.2's single gate)

### 2.1 Lane A — ORDER OBSERVATIONS (dedup retained)

```
provider status/lifecycle observation (no fill content)
→ D1(order) + FPv2
→ broker_sync_observation gate: UNIQUE (tenant_id, broker, d1, content_fingerprint)
   NEW → construct Task2 event (binding per Day40.4 §3.5)
   DUPLICATE_DELIVERY → stop (no Task2)          ← sound here: same D1+FPv2 ⇒ same
   CONTENT_CORRECTION → new CEID event            status snapshot; a redelivery IS
   STALE / UNRESOLVED → stop, per Day40.3 §5.3    the same provider observation
→ Task2 (idempotency PK = canonical_id)
```

Rationale for retaining dedup here: an order's lifecycle snapshot is a **single-valued fact per (order, class)** at any instant. Two deliveries carrying identical `(D1, FPv2)` can only be redeliveries of one snapshot (cross-channel convergence, Day40.4 §3.1). Stream and recovery are views over one provider state; identical content ⇒ same observation. Where Upstox later exposes a stable delivery id for order events, Lane A may adopt it (§3.5) — today's documented provider surface provides none, and the status snapshot property suffices.

### 2.2 Lane B — IDENTIFIABLE FILLS (provider_trade_id present)

```
fill observation with trade_id T
→ raw row in broker_fill_ledger_observation (ALWAYS, first — §6)
→ economic identity = (tenant, broker, provider_order_id, T)     [D2]
→ fill ledger: existing fill row for the same D2?
   yes → economic dedup: SAME content ⇒ DUPLICATE_FILL (no-op, observed_count++,
          both raw rows preserved); DIFFERENT content ⇒ CONFLICT (Day39 conflict
          rule on economic identity; operator adjudication)
   no  → create fill row (tenant, order, T), state PENDING→RECONCILED on proof
→ canonical fill event keyed D1(fill, T); Task2 submission per Day40.2 §3.2A
```

Never routed through delivery dedup: the provider minted the economic identity. Two deliveries of trade T are economically the same fill **because T says so**, regardless of `(D1, FPv2)` equality or difference (content differences between two T-deliveries are corrections/conflicts, not new fills).

### 2.3 Lane C — NON-IDENTIFIABLE FILLS (trade_id absent)

```
fill observation with trade_id absent/empty
→ raw row in broker_fill_ledger_observation (ALWAYS, first — §6)
   raw_observation_id = new immutable UUID, one per received payload — NO dedup
   up front, NO collapse, NO delivery_count merging
→ equivalence evaluation (§4):
   delivery-evidence duplicate → mark duplicate_of(observation_id); no new economic effect
   otherwise → candidate correlation vs composite C (candidate ONLY, §3)
→ economic identity: composite C quarantined scope
   → AMBIGUOUS unless trade_id evidence upgrades (Day40.3 §4 alias model)
→ NO canonical economic fill event until reconciliation proves identity
→ preserved forever; re-evaluated on every authoritative payload
```

**No-ID fills never pass through the Lane-A semantic-dedup rule.** A duplicate classification for a no-ID fill requires delivery evidence (§3), not attribute coincidence.

---

## 3. Duplicate delivery for no-ID fills — evidence rules (Invariant Y)

### 3.1 Admissible delivery evidence (any ONE proves same-delivery)

| Evidence | Proves | Conditions |
|---|---|---|
| Stable provider event/delivery identifier (`provider_event_id`) minted per provider *delivery* | same delivery | must be documented as delivery-scoped and unique per delivery; an id minted per *event* (not per delivery) that is re-sent on redelivery also qualifies — scope must be documented, not assumed |
| Provider sequence, if the provider documents delivery ordering for fill events | same delivery (redelivery of seq n) | requires provider-documented sequence; absent today for Upstox fills — usable when a provider supplies it |
| Recovery cursor / event reference (our own cursor positions into the provider's event stream, e.g. websocket sequence offsets) | same delivery | our cursor identity is stable and delivery-scoped; two deliveries with the same cursor ref are the same stream event; acceptable as delivery evidence because it indexes provider deliveries, not economic events |
| Authoritative history row identity (order/trade-history endpoint row id or row coordinates — `(order_id, trade list position)` per fetch) | same history record | the same history row re-fetched is the same record; note this indexes *records*, so re-fetch dedup at record scope is sound, but record identity is NOT economic identity for no-ID rows (the endpoint does not key executions) |
| Another documented provider-specific stable delivery identifier | same delivery | must be documented in the provider contract memo before use |

### 3.2 Inadmissible as proof (correlation candidates only)

`exchange_timestamp` equality, quantity equality, price equality, D1 equality, FPv2 equality, source_mode, arrival order, worker identity. These **never** prove duplicate delivery or economic equivalence for no-ID fills. They may feed the *candidate correlation* for later trade_id upgrade (Day40.3 §4.3) — candidacy is not proof.

### 3.3 Absence of delivery evidence ⇒ never DUPLICATE

If no admissible delivery identity exists for a no-ID payload (the common case today), the observation is **never** classified DUPLICATE. It is a new raw observation row, every time, and proceeds to equivalence evaluation → AMBIGUOUS unless proven otherwise. Fail-closed: undecidable ⇒ preserve, never merge.

### 3.4 Lane A evidence note

Order-observation dedup in Lane A currently rests on the status-snapshot domain property (§2.1), not on a delivery id. That is a documented domain-guarantee exception to the delivery-evidence rule, bounded to Lane A. If any provider surfaces stable delivery ids for order events, Lane A should prefer them.

### 3.5 Decision table (Lane C equivalence)

| Evidence situation | Classification | Effect |
|---|---|---|
| Delivery id/cursor/sequence proves same delivery as an existing raw row | DUPLICATE (delivery-scoped) | mark `duplicate_of` on the new raw row (row kept); no new economic effect; no Task2 |
| Delivery evidence shows a DIFFERENT delivery id (or absent) + attributes identical to an existing no-ID observation | DISTINCT OBSERVATION (candidate) | new raw row; economic equivalence **unprovable** ⇒ composite stays AMBIGUOUS; no emission |
| No delivery evidence + later trade_id evidence matches (qty/price/cumulative) | UPGRADE candidate | Day40.3 §4.3 alias flow (UPGRADED / SPLIT / NO_CANDIDATE / CONTRADICTED) |
| No delivery evidence + attributes differ from all prior no-ID observations | DISTINCT OBSERVATION | new raw row; new/updated composite scope; AMBIGUOUS unless provable |

---

## 4. Two identical no-ID fills — Case A vs Case B (Invariant Z)

**Case A — same delivery delivered twice (with delivery evidence):**

```
delivery D_x (event id / cursor ref) arrives via STREAM → raw row R1 (uuid-1)
delivery D_x arrives again via RECOVERY → raw row R2 (uuid-2), duplicate_of=R1
→ economic effect: ONE (the fill ledger saw one delivery)
→ no duplicate economic fill; R1 and R2 both preserved (R2 marked duplicate)
```

**Case B — two genuinely distinct executions with identical observable attributes (no delivery evidence, the default today):**

```
execution E1 (T, 5, 100) → raw row R1 (uuid-1), no delivery id
execution E2 (T, 5, 100) → raw row R2 (uuid-2), no delivery id, NOT duplicate_of
→ both are DISTINCT OBSERVATION rows — never one row with delivery_count=2
→ economic identity: both correlate to composite C(O1, T, 5, 100) — candidate only
→ equivalence: UNPROVABLE (attributes identical is exactly why identity is unprovable)
→ composite C: AMBIGUOUS, observed_count reflects distinct observations
→ NO canonical emission; NO projection change; both raw rows preserved forever
→ await authoritative reconciliation (history/trade_id evidence, Day40.3 §4.3)
→ if history later proves two distinct trades: SPLIT → T1, T2 rows (case 81)
   if history proves one trade: contradiction/merge adjudication — operator path
```

**The decisive property:** Case B's second execution can never collapse into one gate row with `delivery_count=2` — raw rows are keyed by surrogate UUID and inserted before any equivalence decision. Losing the second execution's evidence is structurally impossible (Invariant X/AA).

---

## 5. Observation record identity (Issue 6)

### 5.1 Identity layering for fills

```
raw_observation_id  (immutable surrogate UUID, PK of broker_fill_ledger_observation)
   — one per RECEIVED payload; assigned before any classification
D1                  (observation correlation key — candidate correlation only for no-ID fills)
FPv2                (content hash — correlation candidate only for no-ID fills)
provider_trade_id   (nullable — present ⇒ Lane B economic identity input)
delivery_evidence   (provider event id / sequence / cursor ref / history row id — nullable)
source_mode, received_at, raw content (verbatim payload)
```

`raw_observation_id` is the identity of the *record*. `(D1, FPv2)` is a *property* of the record's content. For no-ID fills the pair is never a uniqueness constraint, never a dedup key, and never an economic identity.

### 5.2 Corrected gate table (supersedes Day40.4 §3.3 for fill lanes)

| Table | UNIQUE / PK | Applies to |
|---|---|---|
| `broker_sync_observation` | PK `(tenant, observation_id uuid)`; UNIQUE `(tenant, broker, d1, content_fingerprint)` | **Lane A only** (order observations). The Day40.4 UNIQUE constraint is retained but routing to this table is now lane-gated: fill payloads MUST NOT evaluate against it |
| `broker_fill_ledger_observation` | PK `(tenant, observation_id uuid)` — **surrogate only**; NO UNIQUE on (D1, FPv2); optional index (non-unique) on `(tenant, order, d1)` for lookup | every fill payload, Lane B and Lane C, inserted first |
| `broker_fill_ledger_fill` | PK `(tenant, order, fill_eq_key)` (Day40.3 §4 unchanged) | economic identity rows only |
| `broker_fill_identity_alias` / `_lineage` | per Day40.3 §4.2 | provisional→authoritative mapping |

**Struck text:** Day40.4 §3.3's presentation of `broker_sync_observation.UNIQUE(tenant, broker, d1, content_fingerprint)` as a universal pipeline gate is corrected to Lane A scope. Day40.4 §3.2's flow diagram is corrected by §2 above. Day40.4 §3.3's transaction contract (INSERT..ON CONFLICT..RETURNING + FOR UPDATE, single tx with Task2) remains authoritative **for Lane A**.

---

## 6. Broker-fill-ledger boundary (Issue 7)

```
broker_sync_observation            — delivery dedup WHERE IDENTITY IS PROVABLE
                                     (Lane A: status-snapshot domain guarantee;
                                      fill lanes: only with delivery evidence, §3)
broker_fill_ledger_observation     — PRESERVES EVERY RAW FILL OBSERVATION
                                     (immutable, surrogate-UUID PK, insert-first)
broker_fill_ledger_fill            — ECONOMIC-FILL IDENTITY
                                     (TRADE_ID authoritative; COMPOSITE provisional)
broker_fill_identity_alias/lineage — MAPS PROVISIONAL OBSERVATIONS TO AUTHORITATIVE FILLS
                                     (immutable lineage; alias pointer per Day40.3 §4)
```

For no-ID fills the mandatory path is: **raw observation → ledger observation → equivalence evaluation → AMBIGUOUS if unproven.** A raw fill observation must never disappear merely because its `(D1, FPv2)` matches another observation's — the matching observation is evidence *about correlation*, not a deletion/merge instruction. Equivalence may mark `duplicate_of` (delivery proof, Case A) — a pointer, never a suppression of the raw row.

---

## 7. Concurrency (Issue 8)

All scenarios run inside the Day40.2 §4.1 transaction contract (LOCK→READ→CLASSIFY→AUTHORIZE→WRITE→EMIT→COMMIT), lock order observation→fill→alias/lineage→canonical_event unchanged.

| # | Scenario | Raw observation rows | Fill identity rows | Dedup result | Reconciliation state | Canonical emission |
|---|---|---|---|---|---|---|
| 1 | Same identifiable trade_id T, two workers | 2 raw rows (one per delivery; delivery-evidence dedup may mark the second) | both target PK (tenant, order, T); UNIQUE + PK arbitration → 1 row | economic dedup by T: loser re-reads RECONCILED → no-op (Day40.2 §4.3A) | single RECONCILED T1 | exactly once |
| 2 | Same no-ID delivery, two workers, delivery evidence present (same cursor ref) | 2 raw rows (R2 `duplicate_of` R1 — pointer write arbitrated by row lock; if both insert before either reads, one marks the other; **both rows persist regardless**) | composite C row AMBIGUOUS; delivery-level dedup only — no second economic effect | DUPLICATE (delivery-scoped) via evidence | AMBIGUOUS (economic identity still unproven — delivery identity ≠ economic identity) | none |
| 3 | Two distinct no-ID fills with identical attributes, two workers | **2 raw rows — guaranteed**: surrogate-UUID inserts never conflict; no UNIQUE is evaluated on (D1, FPv2); each tx inserts its row before any equivalence read | one composite C row; both observations correlate as candidates; `observed_count` reflects distinct observations (2) | no dedup (no delivery evidence) | AMBIGUOUS — never collapsed, never emitted | none |
| 4 | No-ID fill observed, later trade_id T1 arrives (history/stream) | raw rows unchanged (immutable) | alias C→T1 per Day40.3 §4.3; fill row (tenant, order, T1) created | upgrade transition | AMBIGUOUS→RECONCILED via UPGRADED lineage | 1 fill event under D1(fill, T1) |
| 5 | Two no-ID observations concurrently upgraded to different trade_ids T1, T2 | raw rows unchanged | two alias/fill writes to distinct PKs (tenant, order, T1) and (tenant, order, T2) — no PK collision; cumulative-conservation check `qty(T1)+qty(T2) == cum(C)` must hold (SPLIT) else CONTRADICTED | SPLIT (per Day40.3 §4.3) | RECONCILED×2 via SPLIT lineage | 2 fill events |
| 6 | Legacy + CEID duplicate delivery for a no-ID fill | delivery-evidence dedup applies identically in both families — the delivery identity, not the identity family, decides; second delivery marks duplicate_of | composite C single row | DUPLICATE (only if delivery evidence; otherwise 2 raw rows stay distinct) | AMBIGUOUS | none |

Key concurrency property: **raw-insert-first** means the only serialization point for Case 3 is nothing at all — two workers never contend on a fill-observation uniqueness constraint (there is none); contention exists only at the composite fill row (single AMBIGUOUS row, incremented `observed_count`) and follows the Day40.2 §4.3B contract.

---

## 8. Invariants X, Y, Z, AA (added to Day40.1 A–H, Day40.2 I–M, Day40.3 N–R, Day40.4 S–W)

| # | Invariant | Defense | SPEC tests |
|---|---|---|---|
| **X** — unknown-fill preservation | Every raw economic-fill observation without proven identity remains durably represented, even when its observable attributes collide with another observation | §5.2 surrogate-UUID PK, no (D1, FPv2) UNIQUE on fill observations; §4 Case B | NIF-01..04 |
| **Y** — no semantic overreach | A delivery-dedup key is never treated as economic-fill identity unless provider evidence proves that equivalence; attributes/D1/FPv2 are correlation candidates only | §3.1/§3.2 evidence rules; §2.2/§2.3 lane routing | NIF-05..07, DEL-01..02 |
| **Z** — two identical no-ID fills | Two genuinely distinct fills with identical observable no-ID attributes cannot collapse into one applied fill OR one duplicate-delivery record | §4 Case B (distinct raw rows, AMBIGUOUS composite, no emission); §7 scenario 3 | NIF-02, NIF-04, NIF-08 |
| **AA** — raw observation preservation | Every received economic-fill payload has an immutable observation record **before** any ambiguity/dedup decision can discard or suppress it | §2.3/§6 insert-first ordering; §5.1 identity layering | NIF-03, NIF-09 |

---

## 9. Adversarial cases 74–85

Columns: raw_observation_id · D1 · FPv2 · delivery identity · economic identity · equivalence · ledger state · Task2 submission · canonical event · projection · audit result. Cases 1–73 remain in force; cases 44–48/59–61/67–68 unchanged; cases 62–66, 71–72 are **Lane A** scenarios (unchanged for orders); case 70's fill observation now routes per Lane C.

| # | Input | raw_observation_id | D1 | FPv2 | Delivery identity | Economic identity | Equivalence | Ledger state | Task2 submission | Canonical event | Projection | Audit result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 74 | Same no-ID fill delivered twice, delivery evidence (cursor ref) present | 2 distinct UUIDs (R2 duplicate_of R1) | same | same | SAME (proven) | composite C (unproven) | DUPLICATE (delivery-scoped) | 2 raw rows + 1 composite C AMBIGUOUS | none (2nd stopped at delivery layer) | none | unchanged | delivery dedup with full preservation |
| 75 | Two genuinely distinct no-ID fills, identical D1/FPv2, no delivery evidence | 2 distinct UUIDs, neither duplicate_of | same | same | ABSENT | composite C shared — candidate only | DISTINCT OBSERVATION (unprovable ⇒ not duplicate) | 2 raw rows; C AMBIGUOUS, observed_count=2 | none | none | unchanged (no fill emission) | **no merge** (X, Z) — the Day40.4 defect case, now fail-closed |
| 76 | Two distinct no-ID fills, identical attributes, sequential arrival | 2 UUIDs | same | same | absent | C candidate | DISTINCT | as 75 | none | none | unchanged | preserved across time |
| 77 | Two distinct no-ID fills, identical attributes, concurrent arrival | 2 UUIDs (no insert contention — no uniqueness evaluated) | same | same | absent | C candidate | DISTINCT | as 75; both commits independent | none | none | unchanged | §7 scenario 3 |
| 78 | No-ID duplicate delivery with different source_mode (delivery evidence present) | 2 UUIDs (R2 duplicate_of R1) | same | same | SAME (proven) | C | DUPLICATE (delivery-scoped) | 2 raw rows | none (2nd) | none | unchanged | source_mode never re-identifies (T/W retained) |
| 79 | Two distinct no-ID fills, different source_mode, no delivery evidence | 2 UUIDs | same | same | ABSENT | C candidate | DISTINCT (mode is not evidence) | 2 raw rows; C AMBIGUOUS | none | none | unchanged | Y enforced — mode is provenance |
| 80 | No-ID fill later upgraded to T1 (history evidence) | original UUID unchanged | class → D1(fill, T1) | content | absent at insert; T1 evidence later | C → T1 | UPGRADE | raw row immutable; alias C→T1; fill row (order, T1) RECONCILED | YES (fill event via Task2 at upgrade) | 1 fill event, CEID = H(D1(fill,T1)‖FPv2) | fill counted once | Day40.3 §4.3 flow |
| 81 | Two no-ID observations later upgraded to T1/T2 | 2 UUIDs unchanged | class → two fill D1s | per row | absent | C → T1 + T2 | SPLIT | 2 fill rows RECONCILED; cumulative conservation enforced | YES ×2 | 2 events | both counted | §7 scenario 5 |
| 82 | No-ID fill never reconciled | UUID preserved forever | class | content | absent | stays COMPOSITE | none proven | AMBIGUOUS forever; re-evaluated every payload | none | none | cumulative flows at order level only | permanent quarantine (documented limitation) |
| 83 | Provider delivery identifier present and proves duplicate | 2 UUIDs (R2 duplicate_of R1) | same | same | SAME (proven) | C | DUPLICATE (delivery-scoped) | 2 raw rows | none (2nd) | none | unchanged | evidence-based dedup (Case A) |
| 84 | Provider delivery identifier absent (default today) | 1 UUID per payload — never deduped | same or different | same or different | ABSENT | C candidate | never DUPLICATE by default | distinct raw rows per payload | only if economic identity later proven | only after upgrade | unchanged | §3.3 fail-closed |
| 85 | Raw observation persistence before dedup decision | UUID assigned at insert, before classification | recorded | recorded | recorded (nullable) | recorded (nullable) | evaluation happens AFTER insert | raw row exists regardless of outcome | n/a | n/a | n/a | AA holds by construction |

---

## 10. Test specification — SPEC only

No tests executed. Existing suites must pass unmodified (Day40.4 §2.4 criterion still applies).

| Area | Test | Status |
|---|---|---|
| no-ID identical-fill preservation | NIF-01: two identical-attribute no-ID fills ⇒ 2 raw rows, composite AMBIGUOUS, no emission; NIF-02: no `(D1, FPv2)` uniqueness on fill observations (insert never conflicts) | SPEC |
| duplicate delivery with provable delivery identity | DEL-01: same delivery ref twice ⇒ R2 duplicate_of R1, both rows persist, one economic effect; DEL-02: different delivery refs ⇒ never duplicate despite identical attributes | SPEC |
| sequential identical no-ID fills | NIF-04 (case 76): second arrival is a new raw row; delivery_count semantics restricted to delivery-evidence dedup | SPEC |
| concurrent identical no-ID fills | NIF-08 (case 77): two workers ⇒ 2 raw rows committed independently; single composite row, observed_count=2 | SPEC |
| raw observation persistence | NIF-03/09 (case 85): observation row exists before and after every classification outcome; no UPDATE/DELETE on raw rows | SPEC |
| ledger reconciliation after late trade_id | NIF-05 (case 80): upgrade ⇒ alias + RECONCILED + 1 emission; NIF-06 (case 81): split ⇒ 2 fills, cumulative conservation; contradiction path flagged | SPEC |
| no-ID permanent quarantine | NIF-07 (case 82): unreconciled composite stays AMBIGUOUS; no emission; re-evaluation on every payload | SPEC |
| delivery identity vs economic identity separation | Y-01: delivery dedup does not create/modify fill identity rows; Y-02: economic dedup (Lane B) does not suppress raw rows; Y-03: Lane A routing never sees fill payloads (lane-gate test) | SPEC |
| Lane B identifiable-fill correctness | NIF-10: same trade_id twice ⇒ economic dedup, one fill, raw rows both preserved; different content under same T ⇒ CONFLICT path | SPEC |

---

## 11. Final gate

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | No Day38 change; fold semantics untouched |
| D1 | 🟢 APPROVED | Correlation-only; demoted to candidate-correlation for no-ID fills (§5.1) |
| Canonical ID | 🟡 SINGLE CONTRACT (mechanism pending) | Day40.3 §2 unchanged |
| CEID Constructor Contract | 🟡 DEFINED (Option A) | Day40.4 §2 unchanged |
| Channel Convergence | 🟡 DEFINED, LANE-CORRECTED | Day40.4 §3 retained **for Lane A only**; fill lanes re-routed (§2, §5.2); duplicate-delivery semantics now evidence-scoped (§3) |
| Legacy/CEID Coexistence | 🟡 DEFINED (Option B binding) | Day40.4 §4 unchanged; case 7 (§7) extends it to no-ID fills via delivery evidence |
| Fill Identity | 🟢 MODEL CORRECTED | Lane B/C split (§2.2/§2.3); delivery identity ≠ economic identity (§3); Case A/B distinguished (§4) |
| Identity Upgrade | 🟢 APPROVED | Day40.3 §4 alias model unchanged; operates on preserved raw rows |
| Ordering Authority | 🟡 DEFINED | Day40.3 §5 ladder unchanged; applies to corrections, never to no-ID dedup |
| FPv2 | 🟡 SPECIFIED + VECTORED | Day40.4 §6 V1–V13 unchanged; FPv2 role for no-ID fills demoted to correlation candidate (§5.1) |
| Status Inventory | 🟢 APPROVED | Day40.3 §3.2 + Day40.4 §5 edge rules unchanged |
| Task3 Design | 🟡 YELLOW | Internally consistent, lane-complete, fail-closed for no-ID fills; not independently verified |
| **Task3 Implementation** | **🔴 LOCKED** | **Task3 implementation authorization: NOT GRANTED** |
| Foundation | 🟡 **NOT CLEARED** | Requires: Task1 additive change + gate/ledger migrations (now incl. lane routing + raw-first inserts) + Task2 verification hook + ORDER_PROCESSING + SPEC implementation + independent verification. **NOT GREEN.** |

The six §13 proof conditions: (1) no-ID fills cannot be silently merged — §4 Case B, §5.2, §7-3, Invariants X/Z; (2) duplicate delivery ≠ economic-fill identity — §3, Invariant Y; (3) every raw fill observation preserved — §6, Invariant AA; (4) identifiable fills still deduplicate correctly — §2.2, §7-1; (5) channel convergence remains safe — §2.1 Lane A retained, §3.4 bounded; (6) concurrency preserves the duplicate-vs-distinct distinction — §7. All six are **specified and internally verified**; none is implemented or independently verified.

```
Task3 implementation authorization: NOT GRANTED
```

---

## 12. Safety report

- **BASELINE:** implementation authority `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`; HEAD at session start `f18c9eb` (Day40.4)
- **DAY40.5 MEMO:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-5-no-id-fill-boundary-correction-memo.md` (this file)
- **FILES CHANGED:** one memo added (this file); no other file created, modified, or deleted
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (design only)
- **COMMIT:** single memo commit (see git output); only this memo staged — no code, tests, migrations, or other docs included
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 NOT CLEARED (Foundation) — NOT GREEN
- **TASK3 STATUS:** 🔴 LOCKED — Task3 implementation authorization: NOT GRANTED
