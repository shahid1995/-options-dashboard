# Day40.2 — Final Architecture Correction Memo

**Session type:** DESIGN CORRECTION ONLY  
**Status:** Correction — supersedes Day40.1 `ae67ec1` on canonical identity, identity upgrade, concurrency, and governance  
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`  
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`  
**Day40 correction memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-foundational-architecture-correction-memo.md`  
**Day40.1 correction memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-1-ambiguous-fill-reconciliation-correction-memo.md`  
**Previous corrections (rejected at gate):** `cab3211e1b7f60e73ca92e593c16b3ba45027bd2`, `c189105803c93aa9625a566eae2ca4c2c66e0018`

---

## 0. Baseline verification (repository evidence)

Read-only verification against committed baseline `aa65e1e` and current HEAD `ae67ec1`:

| Symbol | Committed state | Evidence |
|---|---|---|
| `BrokerEventType` | 9 values; no `ORDER_PROCESSING`, no `ORDER_OBSERVED` | `backend/app/broker_sync/__init__.py:21-35` |
| `BrokerSyncEvent.canonical_id` | `SHA256(tenant \x1f broker \x1f provider_event_id \x1f event_type)` when `provider_event_id` present; `SHA256(tenant \x1f broker \x1f event_type \x1f broker_order_id [\x1f canonical_sequence] [\x1f fill_digest])` otherwise — **content participates in canonical identity** (fill_digest includes quantity/price/cumulative) | `__init__.py:183-210` |
| `canonical_id` excludes | `received_at`, `source_mode`, user metadata — provenance excluded | `__init__.py:183-210` |
| `CanonicalOrderState` | PENDING..UNKNOWN (no SUBMITTED→processing distinction) | `__init__.py:44-55` |
| Day39 spec §8 example | `broker order accepted -> normalized OrderSubmitted` | `specs/2026-09-08-...design.md:159` |
| Day39 spec §7.12 (sequence rules) | no provider sequence → use deterministic event identity, do not invent sequences | `design.md:148` |
| Day39 spec §7 conflict | "same event identity with conflicting canonical content → reject as conflict" | `design.md:131` |
| Day39 spec §9 | broker truth authoritative; local projection must never override | `design.md:170-188` |
| Day40.1 §3.3 internal contradiction | §3.3 says `same D1 → same canonical_id → CHANGED_OBS`; §10 says "new canonical_id (content changed)" | `day40-1-memo.md:91` vs `:268-269` |
| Day40.1 §14.2 exists | Section 14.2 IS the identifiable-fills adversarial table (10–15) — the "provider-status inventory at §14.2" cross-reference in §13 is a **wrong cross-reference** (the inventory is at Day40 §8.4, not Day40.1 §14.2) | `day40-1-memo.md:332` vs `:355` |
| Day40.1 `observed_count` | Referenced in §9.2/§14.4 but **absent from the §4.2 ledger schema** | `day40-1-memo.md` §4.2 |
| Day40.1 §9.1 generic upsert | `ON CONFLICT DO UPDATE SET content_fingerprint=..., source_mode=..., reconciliation_state=...` — can overwrite state/fingerprint before equivalence evaluation | `day40-1-memo.md` §9.1 |

No source, test, migration, or protected file was modified in this session.

---

## 1. Executive decision

Four findings resolved:

1. **Canonical-id semantics are made definitive** (§2). D1 is the stable correlation identity; `content_fingerprint` is the immutable content representation; `canonical_id` = deterministic function of D1 + fingerprint. Same D1 + same fp → same canonical_id → DUPLICATE_NOOP; same D1 + different fp → different canonical_id → CHANGED_OBSERVATION; different D1 → DISTINCT. Day39's "same event identity + conflicting content → CONFLICT" is formally superseded for the D1-based identity (the Task1 `canonical_id` with literal `provider_event_id` retains the Day39 conflict rule; see §2.4).
2. **Composite→trade_id upgrade gets an explicit identity-lineage model** (§3): immutable observation record + identity alias, never a bare PK mutation.
3. **Concurrency becomes a strict LOCK→READ→CLASSIFY→AUTHORIZE→WRITE→EMIT→COMMIT contract** with forbidden transitions explicitly enumerated (§4).
4. **Collision evidence is formalized**: `observed_count` added to the design schema (§5).
5. **Source-of-truth governance is defined** (§6): Day40.1 supersedes exactly Day39 §8's `accepted → OrderSubmitted` example; a single implementation-authority file is declared.
6. **The 17-row provider inventory is included explicitly** (§6.3) with the full status→canonical→projection→metadata mapping.
7. **Seven formal definitions** (§7) and the extended adversarial cases 30–42 (§8) and invariants I–M (§9) are specified.
8. **All tests remain SPEC** (§10).

**Task3 implementation authorization: NOT GRANTED.** Task3 implementation remains 🔴 LOCKED.

---

## 2. Canonical-ID semantics — definitive

### 2.1 Three distinct identifiers

```
D1                  = observation CORRELATION identity
                        D1(order)  = SHA256("D1v1:" \x1f tenant \x1f broker \x1f order_id \x1f event_type)
                        D1(fill)   = SHA256("D1v1:" \x1f tenant \x1f broker \x1f order_id \x1f event_type \x1f trade_id)
                        (trade_id empty ⇒ fill formula degenerates to order formula ⇒ class-level identity only)

content_fingerprint  = SHA256 of the OBSERVED CONTENT (mutable content fields:
                        order_status, filled_quantity, cumulative, average_price, reject_reason,
                        event_timestamp, cancel_quantity — exactly what the provider reported)

canonical_id         = SHA256( D1 \x1f content_fingerprint )
```

### 2.2 The decision table (no alternative interpretations)

| D1 | fingerprint | canonical_id | Classification | Ledger / canonical action |
|---|---|---|---|---|
| same | same | **SAME** | DUPLICATE_NOOP | no-op (idempotent) |
| same | **different** | **DIFFERENT** | CHANGED_OBSERVATION | emit NEW canonical event (new canonical_id, same D1) |
| **different** | — | different | DISTINCT | both applied / separate ledger rows |
| same | irreconcilable with provider authority | — | CONFLICT | REJECTED, operator adjudication |

**This is the single definition.** Day40.1 §3.3's phrase `same D1 → same canonical_id → different fingerprint → CHANGED_OBSERVATION` is corrected: with a different fingerprint the canonical_id is necessarily DIFFERENT (it is a hash of D1 + fingerprint). The corrected-fill section's "new canonical_id (content changed)" was right; the §3.3 shorthand was wrong. The authoritative chain is:

- same D1 + same fp → **SAME canonical_id** → DUPLICATE_NOOP
- same D1 + different fp → **DIFFERENT canonical_id** → CHANGED_OBSERVATION (new immutable event, supersedes projection-wise on replay fold)
- different D1 → **DIFFERENT canonical_id** → DISTINCT observation

### 2.3 Why this is consistent with Task1's committed canonical_id

The committed `BrokerSyncEvent.canonical_id` (`__init__.py:183-210`) is a DIFFERENT function: it hashes `(tenant, broker, provider_event_id, event_type)` and treats a missing `provider_event_id` by folding content (fill_digest) into identity — that is the Day40 F1 defect source. Day40.2 does NOT change Task1 code; it defines the D1/fingerprint/canonical_id decomposition that Task3's normalization will USE when constructing Task1 events. Specifically:

- For order observations with no provider event id, Task1's fallback still requires `canonical_sequence` or `fill_facts` as discriminator (`__init__.py:176-181`). Task3 must therefore ensure every sequence-less order observation carries a deterministic discriminator — either a provider-supplied event id/sequence when it exists, or a StrikeNova-derived observation discriminator (e.g. `broker_order_id + provider status token` when the provider stream provides one, or, failing that, the order of arrival safeguarded by broker-order state). This is already flagged in Task1's fail-closed validation and is a Task1/Task3 contract prerequisite, not a Day40.2 decision.

### 2.4 Reconcile with Day39's conflict rule

Day39 §7: "same event identity with conflicting canonical content → reject as conflict" (`design.md:131`).

- That rule is written against the **Task1 literal event identity** (provider_event_id or canonical_sequence as the event identity). Under Task1's identity, same event id + different content is a genuine contradiction → CONFLICT. **This rule remains authoritative for Task1 events with a literal provider event id / canonical sequence.**
- Day40.2's D1 is a **different, weaker identity**: it is the observation correlation key, not the Task1 event identity. Two D1-equal observations are NOT the same Task1 event — they are the same provider fact observed at different points, and differing content is an expected correction, not a contradiction.
- Therefore Day40.2 **supersedes Day39 §7's conflict rule only in the D1/canonical_id path**: same D1 + different content ⇒ CHANGED_OBSERVATION, NOT CONFLICT. For the Task1 `canonical_id` path (provider event id present), Day39's conflict rule continues to apply unchanged.

**Formal statement:** D1 is defined as observation-correlation identity. The Day39 "same event identity + conflicting content → CONFLICT" rule binds only when the event identity is a Task1 canonical event identity (same `canonical_id` / same provider event id + different fingerprint). Day40.2 does not redefine Task1 canonical identity; it defines what D1 means, and D1 is not the Task1 canonical identity.

---

## 3. Composite → trade_id identity upgrade (lineage contract)

### 3.1 Model: immutable observation record + identity alias + lineage row

The ledger is **append-only**; a PK is never mutated in place for an upgrade. The model:

```
broker_fill_ledger_observation   (immutable — one row per RAW provider fill observation)
  tenant_id, observation_id (surrogate, UUID), order_id,
  fill_eq_key (composite C or trade_id T), fill_identity_type ('COMPOSITE'|'TRADE_ID'),
  fill_quantity, fill_price, cumulative_after, exchange_timestamp,
  source_mode, received_at, content_fingerprint,
  reconcile_state, observed_count,
  PRIMARY KEY (tenant_id, observation_id),
  UNIQUE (tenant_id, order_id, fill_eq_key, content_fingerprint, source_mode, received_at)

broker_fill_ledger_fill         (the economic-fill identity — the actual fill row)
  tenant_id, order_id, fill_eq_key (= trade_id when known, else composite C),
  fill_identity_type, reconciliation_state, canonical_id, observed_count,
  PRIMARY KEY (tenant_id, order_id, fill_eq_key)

broker_fill_identity_lineage    (audit — how an observation mapped to a fill)
  tenant_id, observation_id (FK observation),
  from_identity (COMPOSITE C), to_identity (TRADE_ID T1),
  upgrade_trigger (PROVIDER_HISTORY | STREAM | RECOVERY | OPERATOR),
  candidate_count, list trade_ids, outcome (UPGRADED|SPLIT|NO_CANDIDATE|CONTRADICTED),
  observed_at (of the mapping), upgraded_at, evidence_ref
```

Every raw observation is permanently preserved (its fingerprint, provenance, content). The fill row's `fill_eq_key` may be upgraded from `C` to `T1`; the observation row still holds `fill_eq_key=C` and the lineage row records the mapping `observation_i → fill(T1)`. **Nothing is lost, nothing is mutated in place.**

### 3.2 Decision cases

| Case | Procedure | Result |
|---|---|---|
| A. Exactly one trade_id candidate | Lineage: `observation(C) → fill(T1)`, outcome=UPGRADED; fill row `fill_eq_key=C→T1`, `fill_identity_type=TRADE_ID`, state=RECONCILED | Canonical fill event emitted (new canonical_id under D1(fill, T1)) |
| B. Zero candidates | Lineage outcome=NO_CANDIDATE; fill row stays COMPOSITE/AMBIGUOUS | No emission; remains quarantined; re-checked on every provider payload |
| C. Multiple candidates | Lineage: `observation(C) → fill(T1), fill(T2)`, outcome=SPLIT; new fill rows `fill_eq_key=T1`, `fill_eq_key=T2` (both RECONCILED) | Each emits its own canonical fill event; the original observation is linked to both fills; cumulative==sum enforced as a consistency check |
| D. Candidate later contradicted (history says T1 is a DIFFERENT qty/price than the observation) | Lineage outcome=CONTRADICTED; fill row `C` stays AMBIGUOUS; T1 row (if created) not linked to this observation; operator review flag set | No auto-emission of the mismatched mapping |
| E. Same composite already associated with trade_id T2 (a different observation already upgraded to T2) | The new observation is compared against T2's content: identical content → SAME fill (dedup, no new fill); different content → new observation row, lineage tries matching; if no candidate → AMBIGUOUS | Never silently re-uses T2 as the upgrade target for a content-different observation |
| F. Two workers simultaneously upgrading C → T1 | Fill row PK `(tenant, order, fill_eq_key)` — both target `T1`; unique constraint + atomic upsert (with the §4 algorithm) → one wins; looser re-reads, sees RECONCILED T1, lineage already recorded → its upgrade is a no-op with lineage evidence of the race | Single upgrade applied; both lineage rows recorded (audit) |

The original **provisional evidence** (the no-trade-id observation row) is never deleted and never modified on upgrade — it is only linked. This satisfies the Day40.2 preservation list (original observation, content fingerprint, provenance, later trade_id evidence, exact mapping, audit history).

---

## 4. Concurrency / state-machine transaction contract

### 4.1 Transactional algorithm (authoritative — replaces Day40.1 §9.1's generic upsert)

Every ledger mutation runs ONE PostgreSQL transaction per logical operation:

```
BEGIN
  LOCK broker_fill_ledger_fill  (or observation) ROW             -- lock first
  READ CURRENT row (or determine none exists)                    -- read the existing state
  CLASSIFY equivalence E(x,y) against current content            -- classify
  AUTHORIZE TRANSITION: check the state machine (§4.2)            -- validate the move
  WRITE EVIDENCE: insert/update ledger rows + lineage rows        -- record
  IF TRANSITION AUTHORIZES EMISSION:
      EMIT canonical event in the SAME transaction               -- outbox pattern
      (canonical_event insert keyed on canonical_id; idempotency handled by PK)
      UPDATE fill row canonical_id = emitted event's canonical_id
  ELSE: no canonical emission
  COMMIT
```

Properties:
- **Atomicity:** the ledger authorization and the canonical event commit or roll back together (Invariant M). A canonical fill event can never be committed without the corresponding RECONCILED ledger row in the same transaction.
- **Lock ordering (fixed, global):** `broker_fill_ledger_observation → broker_fill_ledger_fill → broker_fill_identity_lineage → canonical_event`. Every worker takes locks in exactly this order; no reverse-order lock is ever taken ⇒ no deadlock path.
- **Exactly-once/effectively-once emission:** the canonical event's PK is `canonical_id`. If a crash happens after COMMIT but before the worker acknowledges, the retry re-runs the algorithm: it reads the already-RECONCILED row, sees the canonical_id already set, classifies SAME → no second event (idempotency at the persistence layer). A crash before COMMIT rolls everything back — nothing was emitted.
- **Projection update:** the projection is a fold over the canonical event stream (Day38 replay). Within the same transaction the event is appended; projection readers see it only after COMMIT. No separate projection write is inside this transaction — projection derives from committed events (fold semantics, §2 of Day40.1 retained).

### 4.2 State machine — allowed and forbidden transitions

| From | To | Allowed? | Condition / trigger |
|---|---|---|---|
| PENDING | RECONCILED | ✅ | equivalence proven (trade_id match, or history exactly-one upgrade) |
| PENDING | AMBIGUOUS | ✅ | composite collision / no identity proof |
| PENDING | CONFLICT | ✅ | irreconcilable content under same identity |
| RECONCILED | PENDING | **🚫 FORBIDDEN** | a normal replay must never regress state (Invariant K) |
| RECONCILED | AMBIGUOUS | **🚫 FORBIDDEN** | same |
| RECONCILED | SUPERSEDED | ✅ | provider correction/supersession (new row created; superseded row frozen) |
| RECONCILED | (content update) | ✅ | CHANGED_OBSERVATION on same fill identity; fingerprint updated; row stays RECONCILED; new canonical event emitted (new canonical_id) — this is a correction, not a regression |
| AMBIGUOUS | RECONCILED | ✅ | later trade_id / history upgrade (§3) |
| AMBIGUOUS | CONFLICT | ✅ | evidence proves irreconcilable |
| AMBIGUOUS | PENDING | **🚫 FORBIDDEN** | regression |
| CONFLICT | RECONCILED | ✅ only with explicit operator adjudication | operator decision + documented evidence; audit row |
| CONFLICT | PENDING / AMBIGUOUS | **🚫 FORBIDDEN** | requires adjudication path |
| SUPERSEDED | active | **🚫 FORBIDDEN** | replay of the superseded row is a no-op (**case 40**) |
| SUPERSEDED | (none) | terminal | |

Every transition writes an audit row (who/what triggered, evidence ref, from→to, timestamp).

### 4.3 Two-workers matrix

| Scenario | Result |
|---|---|
| A. Same identifiable fill | Both target PK `(tenant, order, T1)`; first wins (PENDING→RECONCILED + emission); second re-reads → RECONCILED + canonical_id set → SAME no-op (exactly-once) |
| B. Same ambiguous observation | Both target composite PK; first wins (AMBIGUOUS, no emission); second re-reads → AMBIGUOUS → increments `observed_count` (collision evidence); no emission from either |
| C. Two genuinely distinct no-ID fills | Identical composite → same PK → race → one row AMBIGUOUS with observed_count=2 (evidence both observations hit the same composite); provider history later segregates into T1/T2 (case C of §3.2) — never merged into one applied fill, never auto-emitted |
| D. Composite → trade_id upgrade race | Both target PK `(tenant, order, T1)`; one applies the upgrade; loser re-reads RECONCILED → no-op; both lineage rows recorded |
| E. Correction of already-RECONCILED fill | Both classify CHANGED_OBSERVATION; same D1, new canonical_id for the corrected content; first emits, second re-reads → fingerprint already the corrected one → SAME no-op. No duplicate correction event |

---

## 5. Collision evidence (observed_count)

Day40.1's `observed_count` is **formally added** to the design schema (it was missing from the §4.2 schema):

- `broker_fill_ledger_fill.observed_count INTEGER NOT NULL DEFAULT 1` — number of raw observations that mapped to this fill identity (or collided on this composite).
- Every additional observation resolving to an existing row (SAME-classified-but-unproven, or duplicate composite) increments it **inside the same LOCK→READ→CLASSIFY→WRITE transaction**.
- `observed_count > 1` on an AMBIGUOUS row is the durable evidence that multiple payloads hit the same composite — the raw material for the §3.2C split and for operator review.
- Additionally the per-observation rows (immutable, §3.1) each preserve their own fingerprint/provenance, so `observed_count` plus the observation rows together give full collision evidence.

---

## 6. Source-of-truth governance

### 6.1 Supersession (explicit)

| Day39 section | Verdict | Rationale |
|---|---|---|
| §8 example line: `broker order accepted -> normalized OrderSubmitted` (`design.md:159`) | **SUPERSEDED by Day40/Day40.1/Day40.2** | Post-dates Day38 finalization; Day38 §13.7/§4.rule-4 say OrderSubmitted is an audit record of submission attempt and does not mean broker accepted; the committed `_BROKER_TO_LIFECYCLE[ORDER_ACCEPTED] = None` (`ingestion.py:144-176`) implements the projection-only interpretation. Day40.2's mapping: `broker order accepted → ORDER_ACCEPTED → projection-only` |
| §7 conflict rule (`design.md:131`) | **PARTIALLY SUPERSEDED** | Retained for Task1 literal event identity (provider_event_id); superseded for the D1 correlation path (§2.4) |
| §8 remaining lines (partial fill → fill + projection, cancellation → OrderCancelled, rejection → OrderRejected) | **AUTHORITATIVE** | Consistent with committed mapping |
| §9 authoritative-state rule | **AUTHORITATIVE** | broker truth authoritative; projection never overrides |
| §7 sequence rules | **AUTHORITATIVE** | no-provider-sequence → deterministic identity without inventing sequence guarantees |
| everything else | **AUTHORITATIVE** | unchanged |

### 6.2 Implementation-authority chain (one unambiguous file)

```
Implementation authority (single file):
    backend/app/broker_sync/  (Task1: __init__.py; Task2: ingestion.py)
    backend/app/trade_lifecycle/ (Day38)
Contract chain precedence:
    1. Day40.2 (this memo) — resolves all open identity/fill/concurrency questions
    2. Day40.1 — fill state machine, equivalence model, adversarial cases (where not contradicted here)
    3. Day40 — D1 formulas, provider-status preservation, ORDER_PROCESSING naming
    4. Approved Day39 design §7, §9, remainder of §8 (as per §6.1 table)
    5. Contract v8 — design draft only, NOT authoritative
Contract files are DESIGN; committed code in backend/ is the runtime authority.
```

**The Day39 document itself must be amended before implementation** (a follow-up docs edit, not code): the §8 example line `broker order accepted -> normalized OrderSubmitted` must be corrected to the Day40.2 mapping, and §7's conflict rule annotated with the §2.4 D1 carve-out. This is a documentation amendment pending approval — not part of this session's deliverable.

### 6.3 Provider status inventory — authoritative mapping (17 rows)

| # | Provider status (Upstox, verbatim) | Canonical event type | OrderFacts projection | Preserved raw metadata |
|---|---|---|---|---|
| 1 | `put order req received` | ORDER_SUBMITTED | SUBMITTED | `metadata["upstox"]["status"]` |
| 2 | `after market order req received` | ORDER_SUBMITTED | SUBMITTED | same |
| 3 | `validation pending` | ORDER_PROCESSING | SUBMITTED | same |
| 4 | `open pending` | ORDER_PROCESSING | SUBMITTED | same |
| 5 | `trigger pending` | ORDER_PROCESSING | SUBMITTED | same |
| 6 | `modify pending` | ORDER_PROCESSING | SUBMITTED | same |
| 7 | `modified` | ORDER_PROCESSING | SUBMITTED | same |
| 8 | `not modified` | ORDER_PROCESSING | SUBMITTED | same |
| 9 | `cancel pending` | ORDER_PROCESSING | SUBMITTED | same |
| 10 | `not cancelled` | ORDER_PROCESSING | SUBMITTED | same |
| 11 | `modify after market order req received` | ORDER_PROCESSING | SUBMITTED | same |
| 12 | `rejected` | ORDER_REJECTED | REJECTED | same |
| 13 | `complete` | FULL_FILL | FILLED | same |
| 14 | `open` | ORDER_ACCEPTED | OPEN | same |
| 15 | `partial fill` | PARTIAL_FILL | PARTIALLY_FILLED | same |
| 16 | `cancelled` | ORDER_CANCELLED | CANCELLED | same |
| 17 | `expired` | ORDER_EXPIRED | EXPIRED | same |

(Plus the documented `rejected by rms` — Upstox documents it under the same order-status appendix; it maps like `rejected` → ORDER_REJECTED → REJECTED. The 17-row inventory is the canonical set; the appendix's exact count was verified in Day40 from the official Upstox order-status page. Every row round-trips verbatim through `metadata["upstox"]["status"]`; the coarse projection never erases provider truth (Invariant F).)

---

## 7. Final formal definitions

| Term | Definition | Uniqueness guarantee | Mutable? | Source | Purpose | Authoritative? |
|---|---|---|---|---|---|---|
| Observation Correlation ID (D1) | Hash of observation-class fields: `(tenant, broker, order_id, event_type[, trade_id])` | Deterministic; NOT necessarily unique per fill when trade_id absent (degenerates to class) | NO (on construct) | Derived by normalization (Task3) | Correlate observations of the same provider fact | Correlation-level only — NOT economic identity |
| Economic Fill Identity | Ledger fill row `fill_eq_key` = `trade_id` (TRADE_ID) or quarantined composite (COMPOSITE) | Unique per `(tenant, order, fill_eq_key)` — when TRADE_ID, per provider trade; when COMPOSITE, provisional only | NO (upgrade = new lineage, not in-place mutation) | `broker_fill_ledger_fill` | Identify which economic fill | YES — the authoritative fill-identity boundary |
| Content Fingerprint | SHA256 of mutable observation content (status, qty, price, cumulative, reject_reason, event_timestamp, ...) | Deterministic per content; collisions cryptographically negligible | N/A — immutable representation of a snapshot | Derived (Task3) | Detect content change; idempotency discriminator | Content truth at that observation |
| Canonical Event ID (canonical_id) | `SHA256(D1 \x1f content_fingerprint)` per Day40.2 | Deterministic; same D1+fp ⇒ same id; different fp ⇒ different id | Immutable once persisted | Derived (Task3 → Task1 event) | Event identity PK | YES (event identity) |
| Provider Event ID | Provider-supplied event identifier (`provider_event_id`) when present | Only as strong as the provider | NO | Upstox stream/history | Task1 literal identity (when present); provenance-ish but provider-sourced | When present — treated as identity in Task1 canonical_id (`__init__.py:183`); when absent → fallback discriminator rules apply |
| Delivery Provenance | `source_mode` + `received_at` | Per delivery | NO | Our pipeline | Audit; channel convergence | NOT identity — never affects D1/canonical_id |

---

## 8. Adversarial cases 30–42

Legend columns: `I` = identity (D1), `FP` = content fingerprint, `CID` = canonical_id, `LS` = ledger state, `T` = allowed transition? , `CE` = canonical emission, `P` = projection, `A` = audit result.

| # | Input | I | FP | CID | LS | T | CE | P | A |
|---|---|---|---|---|---|---|---|---|---|
| 30 | same D1 + same fingerprint | same | same | SAME | RECONCILED | no-op (SAME) | none | none | duplicate observed, count++ |
| 31 | same D1 + changed fingerprint | same | different | DIFFERENT | RECONCILED | CHANGED_OBS | NEW event | fold update | correction recorded, append-only |
| 32 | canonical-id derivation for corrected content | same | different | different (prove: hash differs) | — | — | new CID → new event | updated | both events retained; replay folds; later wins |
| 33 | composite C → exactly one T1 | class → T1 | same content | changes to D1(fill,T1)+fp | AMBIGUOUS→RECONCILED | upgrade (allowed) | emit | fill counted | lineage UPGRADED |
| 34 | composite C → T1/T2 split | class → T1,T2 | per-row | two fill CIDs | →RECONCILED×2 | split (allowed) | emit ×2 | both counted; cumulative check | lineage SPLIT |
| 35 | composite C → no candidate | class | same | class-only | AMBIGUOUS stays | none | NO | none | lineage NO_CANDIDATE; quarantine persists |
| 36 | composite C → candidate later contradicted | class | mismatched | class-only | AMBIGUOUS stays | none | NO | none | lineage CONTRADICTED; operator flag |
| 37 | two workers upgrading C → T1 | same T1 | same | same | one RECONCILED | winner; loser no-op | emit once | once | both lineage rows; race recorded |
| 38 | upgrade racing with second ambiguous observation | C obs1; C obs2 | same | class | C row; obs2 collides | — | NO | none | observed_count=2; both observations preserved |
| 39 | RECONCILED row receives stale PENDING observation | same D1 | older content | different (older fp) | RECONCILED | **reject regression** (K) | NO | none (out-of-order; quarantined for review) | stale superseded observation flagged |
| 40 | SUPERSEDED row receives replay | same D1 | same as superseded | SAME-as-superseded | SUPERSEDED | no-op | NO | none | replay of superseded row ignored |
| 41 | CONFLICT row receives normal delivery | same D1 | same | same | CONFLICT | no-op (no adjudication) | NO | none | redelivery ignored until operator |
| 42 | canonical-event idempotency during crash/retry | same D1 | same | same | RECONCILED + canonical_id set | SAME | NO (already emitted) | none | retry re-reads; exactly-once |
| 43 | stale PENDING with **changed** content (newer truth) | same D1 | different | different | RECONCILED | CHANGED_OBS on current identity | NEW event | fold update | correction accepted; fingerprint updated; stays RECONCILED (correction ≠ regression) |

*Case 43 added to distinguish "stale content" (39, rejected) from "legitimate provider correction" (31/43, accepted) — the discriminator is provider authority/recency rules, not mere arrival order. Exact recency authority: provider-supplied `exchange_timestamp`/sequence when present; otherwise the broker-order state snapshot (latest provider observation wins, quarantining out-of-order arrivals that lack authority).*

---

## 9. Invariants I–M (added to Day40.1's A–H)

| # | Invariant | Defense |
|---|---|---|
| I — canonical identity consistency | Same D1 + same content always ⇒ same canonical_id | canonical_id defined as `SHA256(D1 \x1f fingerprint)` (§2); determinism by construction; SPEC test (CAN-01) |
| J — correction identity separation | Same D1 + different content ⇒ different canonical_id while retaining same D1 | fingerprint participates in canonical_id but D1 doesn't change; SPEC (CAN-02) |
| K — no unauthorized state regression | A normal replay cannot move a ledger row backward in the reconciliation state machine | §4.2 forbidden-transition table; blocked by the AUTHORIZE step before WRITE; SPEC (CON-04) |
| L — identity-upgrade lineage | A provisional COMPOSITE observation must retain auditable lineage when upgraded to TRADE_ID | immutable observation rows + `broker_fill_identity_lineage` (§3.1); SPEC (UPG-01/02) |
| M — canonical emission atomicity | A canonical fill event cannot be committed without the corresponding ledger authorization in the same transaction | LOCK→…→WRITE→EMIT→COMMIT single transaction (§4.1); outbox pattern; SPEC (TX-01) |

---

## 10. Test specification — SPEC only

No tests executed. All entries below are designed specifications for the implementation phase.

| Area | Test | Status |
|---|---|---|
| canonical_id determinism | CAN-01: same D1+fp ⇒ same CID; CAN-02: same D1, different fp ⇒ different CID, same D1; CAN-03: different D1 ⇒ different CID | SPEC |
| D1/canonical_id separation | CAN-04: mutable-field change ⇒ fingerprint changes, D1 unchanged, CID changes | SPEC |
| correction event identity | CAN-05: corrected content emits new immutable event; old event retained; replay folds latest | SPEC |
| composite→trade_id upgrade | UPG-01: exactly-one candidate ⇒ UPGRADED + RECONCILED + emission | SPEC |
| multi-candidate split | UPG-02: T1/T2 ⇒ SPLIT, 2 fills, cumulative consistency | SPEC |
| lineage preservation | UPG-03: observation row + lineage rows immutable after upgrade; audit complete | SPEC |
| state-regression prevention | CON-04: RECONCILED→PENDING/AMBIGUOUS and SUPERSEDED→active rejected | SPEC |
| concurrency | CON-05: two workers same fill ⇒ one row, one emission; CON-06: ambiguity race ⇒ observed_count=2 | SPEC |
| crash/retry idempotency | TX-01: crash after commit ⇒ retry no-ops (exactly-once); crash before commit ⇒ nothing persisted | SPEC |
| source-of-truth mapping | GOV-01: 17 provider statuses ⇒ canonical/projection/metadata mapping (Table §6.3) | SPEC |
| collision evidence | LED-01: observed_count increments atomically; observation rows retained | SPEC |

---

## 11. Remaining limitations (explicit)

1. **Composite heuristic still cannot prove SAME** (unchanged from Day40.1): identical `(order_id, ts, qty, price)` without trade ids remain indistinguishable at the provider level; they are quarantined AMBIGUOUS (fail-closed). No emission without corroboration.
2. **Segments whose trade history lacks trade_id** (e.g. MF rows with empty trade_id) can never reach RECONCILED via upgrade; possible fill-ledger undercount persists for those segments (cumulative still flows; individual fill events withheld unless operator-mapped).
3. **Task1 literal canonical_id (provider_event_id path) keeps Day39's CONFLICT rule** — a provider that mints a new event id per content change can still trigger CONFLICT at the Task1 layer until Task3 normalization maps events consistently. This is a documented interface prerequisite, not silent.
4. **Out-of-order authority** (case 39/43) requires provider timestamp/sequence authority; where Upstox provides neither, the broker-order state snapshot is the recency authority and ordering anomalies are quarantined for review.
5. All tests are SPEC; none executed. Foundation is NOT independently verified until a dedicated verification pass runs SPECs against implementation.

---

## 12. Final gate

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | No Day38 change; ORDER_PROCESSING maps to None; projection fold semantics |
| Task1 | 🟡 REVISION REQUIRED | ORDER_PROCESSING absent from enum (`__init__.py:21-35`); additive change + D1 decomposition documented, NOT implemented |
| D1 | 🟢 APPROVED | Correlation identity; boundary explicit; class-level when trade_id absent |
| Canonical ID | 🟢 APPROVED | Definitive: `SHA256(D1 \x1f fp)`; same → SAME, diff fp → CHANGED_OBS; Day39 conflict rule carve-out formalized (§2) |
| Fill Identity | 🟡 YELLOW | TRADE_ID path deterministic; COMPOSITE path fail-closed AMBIGUOUS (provider limitation, quarantined) |
| Fill Ledger | 🟢 APPROVED | State machine + forbidden transitions + collision evidence (observed_count) formalized |
| Identity Upgrade | 🟢 APPROVED | Immutable observation + lineage + alias model for C→T1/T2 (§3) |
| Concurrency | 🟢 APPROVED | LOCK→READ→CLASSIFY→AUTHORIZE→WRITE→EMIT→COMMIT; global lock order; exactly-once (§4) |
| Projection Semantics | 🟢 APPROVED | Coarse projection + immutable metadata; fold semantics |
| Status Preservation | 🟢 APPROVED | 17-row inventory mapped explicitly (§6.3) |
| Source-of-Truth Governance | 🟢 APPROVED | Supersession table + implementation-authority chain + required Day39 amendment (pending approval) |
| Task3 Design | 🟡 YELLOW | Internally consistent; quarantined limitations documented; not independently verified |
| **Task3 Implementation** | **🔴 LOCKED** | **Authorization NOT GRANTED** — requires Task1 enum + ledger migrations + `_do_ingest` lock ordering + fold fix + independent verification pass |
| Foundation | 🟡 YELLOW | Architecture sound, consistent, and gap-free within documented provider limits — YELLOW per gate rules; **NOT GREEN** until independent verification |

**Overall: 🟡 YELLOW.** Red conditions (silent merge, unresolved fill in canonical stream, unauthorized regression) are all prevented (Invariants A, C, G, K, M). Green is not declared; the next stage is an independent verification pass of this memo.

```
Task3 implementation authorization: NOT GRANTED
```

---

## 13. Safety report

- **BASELINE:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09` (implementation authority); HEAD at session start `ae67ec17dd9cf9efaae1462dc153e94917f668d4`
- **DAY40.2 MEMO:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-2-final-architecture-correction-memo.md`
- **FILES CHANGED:** one memo added (this file)
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (all SPEC)
- **COMMIT:** single memo commit (see git output)
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 YELLOW
- **TASK3 STATUS:** 🔴 LOCKED