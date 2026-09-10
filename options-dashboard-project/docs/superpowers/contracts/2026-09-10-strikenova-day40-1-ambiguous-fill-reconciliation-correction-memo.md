# Day40.1 — Ambiguous Fill Reconciliation + Fill Identity Boundary

**Session type:** DESIGN CORRECTION ONLY  
**Status:** Correction — supersedes Day40 `c189105` on the fill-identity boundary  
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`  
**Day40 correction memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-foundational-architecture-correction-memo.md`  
**Previous correction (rejected at gate):** `cab3211e1b7f60e73ca92e593c16b3ba45027bd2`

---

## 0. Baseline verification (repository evidence)

Verified against the committed baseline `aa65e1e` (read-only):

| Symbol | Committed state | Evidence |
|---|---|---|
| `BrokerEventType` | 9 values: `ORDER_SUBMITTED, ORDER_ACCEPTED, ORDER_REJECTED, ORDER_CANCELLED, ORDER_EXPIRED, PARTIAL_FILL, FULL_FILL, FILL_RECORDED, ORDER_RECOVERED` | `backend/app/broker_sync/__init__.py:21-35` |
| `ORDER_PROCESSING` | **ABSENT** from the enum | same file |
| `ORDER_OBSERVED` | **ABSENT** from the enum (never existed in code) | same file |
| `_BROKER_TO_LIFECYCLE` | 8 entries; `ORDER_ACCEPTED → None` precedent already established for projection-only events | `backend/app/broker_sync/ingestion.py:144-176` |
| `BrokerEventSourceMode` | `STREAM, RECOVERY, POLLED_SNAPSHOT` | `backend/app/broker_sync/__init__.py` |

No source, test, migration, or protected file was modified in this session.

---

## 1. Executive decision

The five Day40 findings are resolved as follows:

1. **D1 is NOT authoritative economic-fill identity.** It is an observation correlation identity. The authoritative fill-identity boundary is `broker_fill_ledger`. (Sections 2–3)
2. **AMBIGUOUS fills have a defined resolution path** — provider trade history, later STREAM, or RECOVERY supplying `provider_trade_id` upgrades identity from `COMPOSITE` to `TRADE_ID`. (Section 7)
3. **When no stronger identity ever arrives, the fill remains quarantined** in `AMBIGUOUS` — it is persistent, observable, re-reconcilable, and NEVER auto-merged. (Sections 6–7)
4. **Concurrent ingestion of the same fill is protected** by a unique constraint, atomic upsert, and lock ordering; canonical emission is exactly-once via the Task2 `canonical_id` idempotency layer. (Section 9)
5. **Two genuinely distinct fills cannot silently collapse** — the composition-identical case is classified `AMBIGUOUS` (never `SAME`), so no economic fill event is emitted until provider evidence distinguishes them. (Sections 5, 6, Invariant C)
6. **D1 without `provider_trade_id` identifies only the observation class/correlation key** — never a unique fill. (Section 3)
7. **The Day40 §7.1 typo is corrected**: `USE ORDER_PROCESSING`, `REMOVE ORDER_OBSERVED`. (Section 12)
8. The four-layer separation (provider observation identity / economic fill identity / observation content / delivery provenance) is held throughout. (Section 2)

**Task3 implementation authorization: NOT GRANTED.** Task3 implementation remains 🔴 LOCKED. This memo and its predecessors are the only artifacts of this session.

---

## 2. Four-layer separation

| Layer | Concept | Mechanism | Example |
|---|---|---|---|
| A. Provider observation identity | Which provider order observation is this? | `D1` (order-observation formula) | `D1(order, ORDER_PROCESSING)` for a `validation pending` update |
| B. Economic fill identity | Which specific execution/fill is this? | `broker_fill_ledger.fill_eq_key` (+ `reconciliation_state`) | `trade_id=T1`, or quarantined composite |
| C. Observation content | What values did the provider report? | `content_fingerprint` (hash of mutable content) | filled_quantity, average_price, provider status |
| D. Delivery provenance | How and when did we receive it? | `source_mode`, `received_at` | STREAM vs RECOVERY |

**D1 must not be overloaded.** D1 answers "what is this observation correlated to?"; the ledger answers "which economic fill is this?"; the fingerprint answers "what did the provider say?"; provenance answers "how did it get here?". Overloading D1 with fill-identity work is what caused the Day40 F1 defect.

---

## 3. D1 specification and boundary

### 3.1 Formulas (unchanged from Day40 — correct as-is)

```
D1(order observation) = SHA256("D1v1:" \x1f tenant_id \x1f broker \x1f order_id \x1f event_type)
D1(fill observation)  = SHA256("D1v1:" \x1f tenant_id \x1f broker \x1f order_id \x1f event_type \x1f provider_trade_id)
```

For non-fill events `provider_trade_id` is the empty string — the fill formula then **degenerates to the order-observation formula** (identical hash), which is exactly the point: without a trade id, D1 identifies the observation class `(tenant, broker, order, event_type)`, nothing more.

### 3.2 Field classification

| Field | Identity | Content | Provenance | Mutable | Reason |
|---|---|---|---|---|---|
| `tenant_id` | YES (order obs) | — | — | NO | Tenant scope of the observation |
| `broker` | YES | — | — | NO | Broker scope |
| `order_id` (provider) | YES | — | — | NO | Which provider order the observation refers to |
| `event_type` (canonical) | YES | — | — | NO | Which observation class (`ORDER_PROCESSING`, `PARTIAL_FILL`, …) |
| `provider_trade_id` | YES for fill observations; **absent → class-level only** | — | — | NO | Present: which economic fill. Absent: D1 does NOT claim fill identity |
| `event_timestamp` | — | YES | — | YES | Provider-reported; corrections change content, not identity |
| `order_status` (provider) | — | YES | — | YES | Mutable provider content |
| `filled_quantity` (provider) | — | YES | — | YES | Mutable provider content |
| `cancel_quantity` (provider) | — | YES | — | YES | Mutable provider content |
| `reject_reason` (provider) | — | YES | — | YES | Mutable provider content |
| `average_price` | — | YES | — | YES | Mutable provider content |
| `source_mode` | — | — | YES | NO | Delivery channel; must not affect identity (channel convergence) |
| `received_at` | — | — | YES | NO | System receipt time; audit only |
| `provider_event_id` (when provider supplies) | — | YES | — | YES | Provider-supplied but not proven stable/unique by Upstox stream; treated as content, not identity |

### 3.3 Semantics per category

- **Identity fields** establish which external observation the record correlates to. Changing one changes the observation.
- **Content fields** describe what the provider reported AT that observation. Changing one must NOT create a new identity — it creates a corrected observation of the same fact (CHANGED_OBSERVATION), which is the entire point of the Day40 F1 fix: `different average_price → same D1 → same canonical_id → different fingerprint → CHANGED_OBSERVATION`, never CONFLICT.
- **Provenance fields** describe delivery. STREAM vs RECOVERY of the same provider fact MUST produce the same D1 so they converge (Invariant D).

---

## 4. Fill identity boundary

1. **`broker_fill_ledger` is the authoritative fill-identity boundary.** Only the ledger can classify a fill record as `RECONCILED` and authorize canonical emission.
2. **With `provider_trade_id`:** `fill_eq_key = trade_id`, `fill_identity_type = 'TRADE_ID'`. This IS economic-fill identity per provider semantics (Upstox trade history supplies `trade_id`; distinct rows in the provider's own trade history are distinct executions).
3. **Without `provider_trade_id`:** the composite `(order_id, exchange_timestamp, fill_quantity, fill_price)` is a **correlation key only**. Identical composites do NOT prove the same fill (Section 5). The row enters as `PENDING`, is evaluated, and if it cannot be proven identical to an existing row it is classified `AMBIGUOUS`, never `RECONCILED` on composite evidence alone.
4. **A canonical economic fill event MUST NOT be emitted until the ledger state is `RECONCILED`** (Section 8, Invariant G).

---

## 5. Same composite does NOT prove SAME

The Day40 wording `No trade_id AND same composite AND same content → SAME (heuristic)` is **corrected**. The classification is:

```
No trade_id AND same composite AND same content → UNRESOLVED → ledger state = AMBIGUOUS
```

Rationale — adversarial example (the failure Day40.1 must prevent):

```
Fill A: no trade_id, order=O1, exchange_timestamp=T, qty=5, price=100
Fill B: no trade_id, order=O1, exchange_timestamp=T, qty=5, price=100
        (provider actually executed TWO separate fills with indistinguishable attributes)
```

Identical `(order_id, exchange_timestamp, quantity, price)` does not prove one fill. Two fills of the same size executed at the same second at the same price are indistinguishable from provider data alone. Therefore:

- **NEVER** classify composite-colliding records as `SAME`.
- **NEVER** merge them.
- Classify `AMBIGUOUS`; quarantine; no canonical emission; await provider evidence that differentiates them (Section 7).

The cost of over-union is a silent economic undercount (two fills counted as one) — forbidden by Invariant C. The cost of quarantine is a delayed fill event — acceptable and observable.

---

## 6. AMBIGUOUS → resolution: the fill state machine

### 6.1 States and full contract

| State | Entry condition | Allowed transitions | Transition trigger | Authoritative evidence | Canonical emission | Projection change | Row replaceable? | Operator needed? | Terminal? |
|---|---|---|---|---|---|---|---|---|---|
| `PENDING` | New fill record inserted (fill_eq_key computed) | → RECONCILED, → AMBIGUOUS, → CONFLICT | Equivalence evaluation E(x,y) vs existing rows (Section 9) | none yet | NO | NO | yes (idempotent upsert) | NO | NO |
| `RECONCILED` | Equivalence proven: (a) trade_id match, or (b) provider trade history maps composite → exactly one trade_id | → SUPERSEDED | Provider corrected/superseded the fill | provider_trade_id, provider trade history | **YES** | YES | no (append-only; correction creates new row + SUPERSEDED) | NO | NO (supersedable) |
| `AMBIGUOUS` | Composite collides with existing row OR no stronger identity available; cannot prove SAME or DISTINCT | → RECONCILED, → CONFLICT, → SUPERSEDED | Later provider evidence arrives (Section 7) | provider trade history / later STREAM / RECOVERY with trade_id | **NO** | NO | no — retains reconciliation queue position | NO (auto on evidence) / YES if evidence never found | NO (permanent quarantine possible) |
| `CONFLICT` | Same fill identity with irreconcilable content (e.g. contradictory quantities, same trade_id two different cumulative values with no correction semantics) | → RECONCILED (manual override with documented evidence) | Operator adjudication | operator decision + provider evidence | **NO** | NO | no | **YES** | YES |
| `SUPERSEDED` | Corrected/superseding row RECONCILED under same fill identity | (none) | — | — | NO | via superseding row | no | NO | YES |

### 6.2 Key properties

- `AMBIGUOUS` is **non-terminal**: it is a queue position, not a graveyard. Every subsequent provider payload for the same order re-runs the equivalence check against it.
- `AMBIGUOUS` never emits a canonical economic fill event (Invariant G).
- `CONFLICT` is terminal but operator-openable with documented evidence.
- The row is never deleted on transition — `SUPERSEDED`/`CONFLICT` rows are retained for audit (append-only ledger semantics).

---

## 7. Reconciliation authority — what can resolve an ambiguous fill

### A. Provider trade history (primary authority)

Yes. When a later authoritative provider response (trade history / RECOVERY) supplies `provider_trade_id`:

```
ambiguous observation:  order=O1, qty=5, price=100, timestamp=T   (composite C)
later trade history:    trade_id=T1, order=O1, qty=5, price=100, timestamp=T
```

**Matching procedure (composite → trade_id upgrade):**
1. Candidate set = provider history rows for the same `order_id` whose `(quantity, average_price, exchange_timestamp)` == the quarantine row's `(fill_quantity, fill_price, exchange_timestamp)`.
2. If exactly ONE candidate → upgrade: set `fill_eq_key = trade_id`, `fill_identity_type = 'TRADE_ID'`, `reconciliation_state = RECONCILED` → emit canonical fill event. New identity class is `TRADE_ID`; the composite key row content is preserved as the pre-upgrade evidence.
3. If ZERO candidates → the observation is not corroborated; stay `AMBIGUOUS` (or `CONFLICT` if a candidate contradicts it on a hard field such as cumulative).
4. If MULTIPLE candidates → each candidate is a genuinely distinct fill with indistinguishable attributes → do NOT merge. Split into one ledger row per trade_id after provider history confirms the fills; each `RECONCILED` and emitted. Until then, remain `AMBIGUOUS`.

### B. Later STREAM event with trade_id

Yes — same upgrade procedure as A. STREAM is not second-class; the trade_id from any authoritative provider source upgrades the identity.

### C. RECOVERY with stronger identity than the original observation

Yes — same procedure. This is exactly the STREAM→RECOVERY convergence case (Invariant D): whichever channel delivers first creates `PENDING`; whichever delivers the trade_id (or corroborates the composite with exactly one trade_id) produces `RECONCILED`. The second delivery of the same fact dedups via the ledger row (Section 9.3).

### D. No stronger identity ever arrives

The fill **stays `AMBIGUOUS` permanently.** The architecture must not imply self-resolution:

- No canonical fill event is ever auto-emitted for it (Invariant G).
- It remains in the reconciliation queue, queryable, re-evaluated on every subsequent provider payload for that order.
- It surfaces in an operator reconciliation view; an operator may (a) manually map it to a trade_id with documented evidence → `RECONCILED`, or (b) leave it quarantined.
- It is NEVER auto-merged into another row, NEVER auto-marked CONFLICT, NEVER deleted.
- Projection impact: the order's cumulative quantity still advances via order-observation events (Section 11); only the individual economic fill event is withheld. This is a documented, fail-closed undercount — a deliberate limitation (Section 17).

---

## 8. Canonical emission boundary

Pipeline (order observations and identifiable fills flow through the same stages):

```
Provider observation
    ↓
Normalization (provider payload → canonical fields + D1 + content_fingerprint)
    ↓
Fill ledger (fills only; order observations skip ledger) 
    ↓
Identity/equivalence evaluation E(x,y)
    ↓
Reconciliation state
    ↓
Canonical event emission
    ↓
Projection
```

Emission authority per state:

| State | Canonical fill event? | Canonical order-observation event? |
|---|---|---|
| `PENDING` | NO | n/a (order observations are not ledger-gated) |
| `AMBIGUOUS` | **NO** | n/a |
| `CONFLICT` | **NO** | n/a |
| `SUPERSEDED` | NO (superseding row emits) | n/a |
| `RECONCILED` | **YES** | n/a |

Exceptions: **none.** Order-observation events (`ORDER_PROCESSING`, `ORDER_ACCEPTED`, `ORDER_SUBMITTED`, …) carry projection content and provider status metadata; they are NOT economic-fill events and are not ledger-gated. Only economic fill events require `RECONCILED`.

---

## 9. Concurrency / race-condition contract

### 9.1 Identifiable fill, two workers (STREAM + RECOVERY simultaneously)

```
Worker A: STREAM   → trade_id=T1, qty=5
Worker B: RECOVERY → trade_id=T1, qty=5
Both: INSERT broker_fill_ledger (tenant, order, 'T1')
```

1. **Unique constraint:** `PRIMARY KEY (tenant_id, order_id, fill_eq_key)` — both rows target the same key.
2. **Atomic upsert:** `INSERT ... ON CONFLICT (tenant_id, order_id, fill_eq_key) DO UPDATE SET content_fingerprint=EXCLUDED.content_fingerprint, source_mode=..., reconciliation_state=..., updated_at=NOW()` inside ONE transaction — never application-level "check then insert".
3. **Lock ordering (fixed):** (a) ledger row upsert obtains the row lock; (b) with the row locked, re-evaluate equivalence against the current row content; (c) only then write the canonical event; (d) set `canonical_id` on the ledger row in the SAME transaction as (c) — giving an outbox pattern where the ledger row is the durable intent record.
4. **Duplicate handling:** the looser loses the upsert race; its payload becomes a re-check against the winning row → SAME → no-op.
5. **Exactly-once canonical emission:** even if both workers somehow emit, Task2 idempotency on `canonical_id` (SHA256 of D1 + content) makes the second an accepted `DUPLICATE_NOOP` — effectively-once at the application layer, enforced at the persistence layer.
6. **No deadlock path:** all fill writes take locks in order `ledger(PK) → canonical_event(canonical_id)` — no lock is ever taken in reverse order.

### 9.2 Two ambiguous no-ID fills, two workers

```
Worker A: O1 / no trade_id / T / 5 / 100
Worker B: O1 / no trade_id / T / 5 / 100
(provider actually executed TWO separate fills)
```

- Both compute the SAME composite fill_eq_key → both target the same PK → one upsert wins, the other re-checks.
- The key contract: the winning row is classified `AMBIGUOUS`, **NOT** `RECONCILED` — composite collisions never self-resolve as SAME (Section 5). No canonical fill event is emitted by either worker.
- The losers' payloads increment a collision counter on the row (e.g. `observed_count`), preserving evidence that multiple observations hit the same composite — this is the raw material for the Section 7 multi-candidate split once provider history arrives.
- Therefore two genuine fills are NOT merged into one applied economic fill: no fill is applied at all until provider evidence distinguishes them (Invariant C). Fail-closed is the design choice.

### 9.3 Channel convergence (Invariant D)

Whichever channel arrives first creates the row (PENDING→evaluated→RECONCILED if identifiable). The second channel's identical fact hits the PK, upserts the fingerprint (same → no-op), and re-verifies the identity. STREAM-then-RECOVERY and RECOVERY-then-STREAM are symmetric.

---

## 10. Corrected-fill semantics (append-only truth)

Example: `trade_id=T1, price=100` later corrected to `trade_id=T1, price=101`.

| Concept | Definition for this case |
|---|---|
| Changed observation | Same D1 (same trade_id), different `content_fingerprint` → `E = CHANGED_OBSERVATION` |
| Economic fill correction | The provider corrected a content field of the SAME fill (same identity) |
| Replacement/supersession | If the correction is material (e.g. a wrong-fill id, wrong quantity that changes the fill's economic size), the previous file-identity row is marked `SUPERSEDED` and a new row is created; never a silent in-place rewrite of the old row |
| Projection update | Projection derives current state by replaying the event stream — the new canonical event (same `canonical_id` identity prefix, new fingerprint) folds to updated cumulative/price; does NOT mutate prior events |
| Canonical event history | **Append-only.** A correction emits a NEW canonical event with the same D1 but a new `canonical_id` (content changed). Historical events are immutable. Replay folds events in sequence order; the later event wins for projection, but the earlier truth is never erased |

Rule: **canonical events are append-only; projection is a fold.** No `UPDATE` on already-persisted canonical events, ever.

---

## 11. Cumulative quantity vs individual fill

| Concept | Channel | Identity | Ledger? | Canonical event |
|---|---|---|---|---|
| Cumulative observation ("order cumulative filled quantity changed") | Order-update | `D1(order, ORDER_PROCESSING)` — order-observation class | NO (not a fill) | `ORDER_PROCESSING` order observation; projection field updated |
| Individual fill ("a new fill occurred") | Trade | `D1(order, PARTIAL_FILL, trade_id)` | YES — REQUIRED | only when `RECONCILED` |

Example:

```
t0: order created            cumulative = 0
t1: Fill A = +5              trade_id=T1      → ledger RECONCILED → PARTIAL_FILL(T1, qty=5, cum=5)
                             order update     → ORDER_PROCESSING (cumulative=5) — projection-only
t2: Fill B = +3              trade_id=T2      → ledger RECONCILED → PARTIAL_FILL(T2, qty=3, cum=8)
                             order update     → ORDER_PROCESSING (cumulative=8) — projection-only
t3: RECOVERY replays cum=8   order update     → same D1 as t2 order update → SAME → no-op
```

- The cumulative order observation **never becomes a synthetic fill** (Invariant H). The trade-channel fill event is the only source of economic fills.
- `cumulative=5 → 8 → 8(replay)`: order-observation identity is the same class `D1(order, ORDER_PROCESSING)`; content differs 5 vs 8 → `CHANGED_OBSERVATION` (projection advances); 8 vs 8 → `SAME` (no-op).
- **Interaction:** cumulative observations advance the order projection independently of fill reconciliation. A quarantined `AMBIGUOUS` fill does not block the cumulative count (which the provider reports authoritatively); it only withholds the individual fill event (Section 7D).

---

## 12. ORDER_PROCESSING naming correction

**Day40 §7.1 contains a typo** (line 345 of `2026-09-10-strikenova-day40-foundational-architecture-correction-memo.md`):

> "**Use `ORDER_PROCESSING` consistently.** Remove `ORDER_PROCESSING`."

The two clauses are self-contradictory. The intended decision, confirmed by the surrounding text (§7.2–7.4) and by the absence of `ORDER_OBSERVED` from the committed `BrokerEventType` enum:

```
USE    ORDER_PROCESSING
REMOVE ORDER_OBSERVED
```

Additionally: `ORDER_OBSERVED` as a distinct semantic is fully retired — the Day40 body text and the Day40.1 memo use `ORDER_PROCESSING` everywhere. Definition retained from Day40 §7.2:

```
ORDER_PROCESSING = provider order observation indicating the order is still
undergoing broker-side processing, validation, modification, cancellation,
or equivalent non-terminal, non-acceptance, non-fill processing state.
```

Task1 impact (unchanged, still additive, still NOT implemented):
- New `BrokerEventType.ORDER_PROCESSING` enum value (additive; existing 9 values untouched).
- New `_BROKER_TO_LIFECYCLE["ORDER_PROCESSING"] = None` — projection-only, following the committed `ORDER_ACCEPTED → None` precedent (`ingestion.py:144-176`).
- `ORDER_PROCESSING` minted by Task3 normalization only; consumed by the Task2 projection; Day38 unaffected (maps to `None`).
- No breaking change, no migration of existing rows, 7+ new Task1 tests (all SPEC, Section 16).

---

## 13. Provider-status preservation

- **Storage:** original provider status lives in the canonical event's `metadata["upstox"]["status"]` (raw string) plus all raw numeric fields under `metadata["upstox"]`; `OrderFacts.status` carries only the coarse projection.
- **Immutability:** provider metadata is **immutable audit content** — once a canonical observation is persisted, its metadata never changes. Corrections create a NEW canonical observation (new `canonical_id`, same D1); they never rewrite the old row.
- **Completeness:** ALL provider statuses are preserved verbatim — the full 17-row provider inventory (Section 14.2) round-trips through `metadata["upstox"]["status"]`. See Day40 §8.4 table: each of `validation pending / open pending / trigger pending / modify pending / modified / not modified / cancel pending / not cancelled / modify after market order req received` maps to `OrderFacts.status = SUBMITTED` but is fully distinguishable in metadata.
- **Normalization loss:** NONE by construction — the coarse projection is derived; the raw observation is stored alongside it. If a future consumer needs the exact provider wording, it reads metadata; projection never erases provider truth (Invariant F).

---

## 14. Adversarial scenario matrix

Legend: `LEI` = ledger fill identity; `E` = equivalence result. All 29 cases produce a row in `broker_fill_ledger` first (fills) or a canonical order observation (non-fills).

### 14.1 Order observations (1–9)

| # | Input | D1 | E | Ledger action | Canonical | Projection | Final state |
|---|---|---|---|---|---|---|---|
| 1 | Same order observation twice | same | SAME | n/a (not a fill) | no event (duplicate) | none | idempotent no-op |
| 2 | STREAM then RECOVERY, same fact | same | SAME | n/a | no event | none | channel-converged |
| 3 | RECOVERY then STREAM, same fact | same | SAME | n/a | no event | none | channel-converged |
| 4 | Changed average_price | same | CHANGED_OBS | n/a | emit updated observation | update avg price | new canonical_id, same D1 |
| 5 | Changed filled_quantity | same | CHANGED_OBS | n/a | emit updated observation | update cum | new canonical_id, same D1 |
| 6 | Changed provider status (e.g. `open pending` → `open`) | same | CHANGED_OBS | n/a | emit updated observation | status fold | new canonical_id, same D1 |
| 7 | Multiple lifecycle observations (submitted → processing → accepted) | distinct (event_type differs) | DISTINCT | n/a | all emitted | fold in order | full lifecycle stream |
| 8 | Processing → accepted → fill | distinct | DISTINCT | fill leg enters ledger | all emitted | SUBMITTED → OPEN → filled | correct transition |
| 9 | Processing chatter repeated (9 statuses × N deliveries) | same per class | SAME/CHANGED_OBS | n/a | no-op on repeats | only changed content folds | idempotent |

### 14.2 Identifiable fills (10–15)

| # | Input | D1 (fill) | LEI | E | Ledger | Canonical | Projection | Final state |
|---|---|---|---|---|---|---|---|---|
| 10 | Same `trade_id` twice | same | T1 | SAME | no-op | no event | none | RECONCILED (kept) |
| 11 | Same `trade_id`, changed price | same | T1 | CHANGED_OBS | row updated | emit corrected fill | avg price updated | RECONCILED |
| 12 | Same `trade_id`, changed quantity | same | T1 | CHANGED_OBS | row updated | emit corrected fill | cum updated | RECONCILED (or SUPERSEDED if economic size materially changed) |
| 13 | Different `trade_id` | distinct | T1 vs T2 | DISTINCT | both rows | both emitted | both counted | two RECONCILED |
| 14 | Three partial fills T1/T2/T3 | distinct | T1,T2,T3 | DISTINCT | 3 rows | 3 events | cum 3→7→10 | three RECONCILED |
| 15 | Final fill | distinct | T3 | DISTINCT | row | FULL_FILL | FILLED | RECONCILED |

### 14.3 Non-identifiable fills (16–22)

| # | Input | D1 | LEI | E | Ledger | Canonical | Projection | Final state |
|---|---|---|---|---|---|---|---|---|
| 16 | No trade ID, same composite | same (class) | composite C | **UNRESOLVED (NOT SAME)** | row exists | **NO** | none | AMBIGUOUS |
| 17 | No trade ID, different composite | same (class) | C1 vs C2 | DISTINCT* | 2 rows | *see note | update | AMBIGUOUS / RECONCILED |
| 18 | Two genuine fills, identical composite | same (class) | composite C (= both) | UNRESOLVED | collision counter++ | **NO** | none | AMBIGUOUS (never merged) |
| 19 | No ID, then later trade ID (history) | class→T1 | C→T1 | resolved | upgrade | emit after upgrade | count fill | AMBIGUOUS→RECONCILED |
| 20 | STREAM no-ID, then RECOVERY with trade ID | class→T1 | C→T1 | resolved | upgrade | emit | count fill | AMBIGUOUS→RECONCILED |
| 21 | RECOVERY no-ID, then STREAM with trade ID | class→T1 | C→T1 | resolved | upgrade | emit | count fill | AMBIGUOUS→RECONCILED |
| 22 | Ambiguous that never becomes identifiable | class | composite C | UNRESOLVED forever | stays | **never** | cumulative still advances via order obs | **AMBIGUOUS (permanent, fail-closed)** |

\* Case 17 note: "different composite" means the provider data distinguishes them (e.g. different timestamp or price); if the data distinguishes them, they are treated as DISTINCT candidate fills — but without trade IDs the system cannot prove they are the provider's authoritative executions either, so they enter as two separate `AMBIGUOUS`-evaluated rows and only reach `RECONCILED` if provider history corroborates (case 19–21 pattern). DISTINCT on composite is a **correlation** distinction, not an identity proof; emission follows corroboration. Cases 16–22 share the rule: no trade ID ⇒ no canonical economic fill event until corroborated.

### 14.4 Concurrency (23–25)

| # | Input | Result |
|---|---|---|
| 23 | Same identifiable fill, two workers | PK upsert; one wins; looser re-checks → SAME no-op; exactly-once via canonical_id idempotency (9.1) |
| 24 | Same ambiguous observation, two workers | PK upsert; winner stays AMBIGUOUS; loser's payload → collision counter; NO emission (9.2) |
| 25 | Two genuinely distinct no-ID fills concurrently | identical composite → both collide on PK → AMBIGUOUS with counter=2; provider history later splits into 2 trade_id rows (Sections 7A.4, 9.2) |

### 14.5 Corrections (26–29)

| # | Input | Result |
|---|---|---|
| 26 | Corrected price (same trade_id) | CHANGED_OBS; new canonical event; append-only history; projection folds (Section 10) |
| 27 | Corrected quantity (same trade_id, economically material) | row SUPERSEDED; new row; new canonical event; old event retained (Section 10) |
| 28 | Corrected provider status | order observation CHANGED_OBS; metadata immutable; new event with new status (Section 13) |
| 29 | Superseded observation | old row/event marked SUPERSEDED; never deleted; superseding row is the projection source (Section 6) |

---

## 15. Formal invariants

| Invariant | Statement | Defense |
|---|---|---|
| **A — no fabricated fill identity** | The system never manufactures deterministic economic identity where provider evidence cannot establish it | Composite collisions classify UNRESOLVED/AMBIGUOUS, never SAME (Sections 3.3, 5); no trade_id ⇒ no un-corroborated emission (Section 8) |
| **B — no duplicate economic fill** | The same economic fill must not produce two applied economic fills | PK `(tenant, order, fill_eq_key)` + atomic upsert + Task2 `canonical_id` idempotency (Sections 4, 9.1) |
| **C — no accidental merge** | Two genuinely distinct fills must not silently merge | Identical-composite case is AMBIGUOUS + collision counter; split on provider history; never auto-union (Sections 5, 7A.4, 9.2, case 18) |
| **D — channel convergence** | STREAM/RECOVERY of the same identifiable fact converge before duplicate business application | Same D1 across channels (source_mode excluded), PK convergence, symmetric ordering (Sections 3.2, 9.3, cases 2–3, 20–21) |
| **E — immutable identity** | Mutable provider fields must not change observation identity | Mutable fields live in content_fingerprint only (Section 3.2); average_price change ⇒ CHANGED_OBS, same D1 (Section 3.3) |
| **F — projection does not erase provider truth** | Coarse normalized state cannot replace the original provider observation | metadata["upstox"]["status"] immutable + full 17-status round-trip (Section 13) |
| **G — canonical emission follows ledger resolution** | An unresolved economic fill cannot enter the canonical fill stream | Emission table: only RECONCILED emits (Section 8); AMBIGUOUS/CONFLICT/PENDING/SUPERSEDED never emit (Invariant A + G) |
| **H — cumulative ≠ fill** | Cumulative order quantities cannot be treated as individual economic fills | Only the trade channel mint fills; order observations are projection-only (Sections 11, cases 15 vs 5) |

---

## 16. Test specification

**All items are `SPEC` (designed, not executed).** No tests were written or run in this session; the repository test suite was not modified. A test is `EXEC` only when it has run against the real implementation — the only pre-existing evidence is the committed Task1/Task2 test contracts (unchanged).

| Invariant / behavior | Test | Status |
|---|---|---|
| D1 determinism | Same inputs → same D1; different tenant/broker/order_id/event_type/trade_id → different D1 | SPEC |
| Mutable-field invariance | Different average_price / event_timestamp / filled_quantity / order_status → same D1, different fingerprint | SPEC |
| Source-mode invariance | STREAM vs RECOVERY, all else equal → same D1, same fingerprint → DUPLICATE_NOOP | SPEC |
| Trade-ID differentiation | T1 vs T2 → different D1 → both APPLIED | SPEC |
| No-trade-ID class identity | No trade_id → D1 equals the order-observation class D1 (degenerate) | SPEC |
| Ledger uniqueness | PK `(tenant, order, fill_eq_key)`; upsert returns existing row; concurrent double-insert yields one row | SPEC |
| Ambiguous-fill quarantine | Composite collision → AMBIGUOUS; **no** canonical event emitted; collision counter incremented | SPEC |
| Later reconciliation | Composite→trade_id upgrade via provider history (exactly-one candidate) → RECONCILED → event emitted | SPEC |
| Multi-candidate split | History yields 2 trade_ids for one composite → 2 rows, 2 events, projection counts both | SPEC |
| Never-resolved fill | No corroboration → stays AMBIGUOUS; canonical stream unchanged; cumulative still advances via order obs | SPEC |
| STREAM/RECOVERY convergence | Both orders (S→R, R→S) yield one ledger row, one canonical event | SPEC |
| Concurrent insertion | Two workers, same fill: one row; looser no-ops; canonical emitted exactly once (idempotency check) | SPEC |
| Corrected observation | Same trade_id, changed price → CHANGED_OBSERVATION; new canonical event; old event immutable | SPEC |
| Supersession | Material correction → old row SUPERSEDED, new row RECONCILED; projection folds | SPEC |
| Cumulative replay | cum 5 → 8 → 8(replay): second distinct, third no-op; no synthetic fill | SPEC |
| Projection preservation | Every provider status maps to coarse state AND survives verbatim in metadata | SPEC |
| Provider-status preservation | Full 17-row inventory round-trips `metadata["upstox"]["status"]` | SPEC |
| ORDER_PROCESSING | Enum value valid (Task1); maps to None in `_BROKER_TO_LIFECYCLE`; mints no Day38 event; updates projection; metadata preserved | SPEC |

---

## 17. Remaining limitations (explicit)

1. **Composite heuristic cannot prove SAME.** Two fills with identical `(order_id, exchange_timestamp, quantity, price)` and no trade_id are permanently indistinguishable from provider data alone. They are quarantined as AMBIGUOUS (fail-closed). This is a provider limitation, not a design gap — the architecture's response is to withhold, not to invent.
2. **If provider trade history itself lacks trade_id for a segment** (e.g. mutual fund rows show empty `trade_id`), fills for that segment can never reach `RECONCILED` via upgrade; they remain quarantined unless an operator maps them. Economic fill events for such segments are withheld by design; cumulative quantities still flow through order observations. Acknowledge a possible undercount in the fill ledger for those segments.
3. **AMBIGUOUS row is permanent without corroboration.** No timeout auto-resolves it; this is intentional (Invariant A/G) but means the reconciliation queue is bounded only by operator action or eventual provider evidence.
4. **CONFLICT requires operator adjudication** — no automatic winner is chosen when two records genuinely contradict on hard fields.
5. All tests in Section 16 are SPEC; none executed. The architecture is not independently verified until the next verification pass runs them against the implementation.

---

## 18. Final gate

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | Baseline `aa65e1e`; no Day38 change required; ORDER_PROCESSING maps to None (projection-only) |
| Task1 | 🟡 REVISION REQUIRED | `ORDER_PROCESSING` absent from committed enum (`__init__.py:21-35`); additive change required, NOT implemented |
| D1 | 🟢 APPROVED | Correlation identity only; boundary explicit; mutable/provenance fields correctly excluded |
| Fill Identity | 🟡 REVISION REQUIRED → YELLOW limitation | trade_id path deterministic; no-trade_id path fail-closed AMBIGUOUS; non-trivial provider limitation quarantined (Section 17.1–17.2) |
| Fill Ledger | 🟢 APPROVED | Full state machine, reconciliation authority, emission boundary, concurrency contract, append-only semantics |
| ORDER_PROCESSING | 🟢 APPROVED | Naming corrected (USE ORDER_PROCESSING / REMOVE ORDER_OBSERVED); Task1 impact acknowledged |
| Projection Semantics | 🟢 APPROVED | Coarse status derived; provider observation preserved; fold semantics confirmed |
| Status Preservation | 🟢 APPROVED | metadata["upstox"]["status"] immutable; 17-provider-status round-trip |
| Task3 Design | 🟡 YELLOW | Architecture consistent with explicit quarantined limitations — not green until independent verification |
| **Task3 Implementation** | **🔴 LOCKED** | **Authorization NOT GRANTED.** Requires: Task1 ORDER_PROCESSING enum, broker_fill_ledger migration, broker_order_lifecycle_state migration, lock ordering in `_do_ingest`, semantic fold fix, and an independent verification pass |
| Foundation | 🟡 YELLOW | Sound and internally consistent; provider limitation remains explicitly unresolved and safely quarantined → YELLOW per gate rules, **NOT GREEN** |

**Overall:** 🟡 YELLOW — architecture is complete and internally consistent for ambiguity, reconciliation, concurrency, and canonical emission, subject to two explicitly quarantined provider limitations. Red gate conditions (silent merge of distinct fills; unresolved fill entering the canonical stream) are both prevented by invariant C and G. **Green is not declared; the next stage is another independent verification pass.**

```
Task3 implementation authorization: NOT GRANTED
```

---

## Git / Safety verification

- **BASELINE:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09` (implementation authority), HEAD during session `c189105803c93aa9625a566eae2ca4c2c66e0018`
- **FILES CHANGED:** one memo added — `docs/superpowers/contracts/2026-09-10-strikenova-day40-1-ambiguous-fill-reconciliation-correction-memo.md`
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (all tests SPEC)
- **COMMIT:** single memo commit
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 YELLOW
- **TASK3 STATUS:** 🔴 LOCKED