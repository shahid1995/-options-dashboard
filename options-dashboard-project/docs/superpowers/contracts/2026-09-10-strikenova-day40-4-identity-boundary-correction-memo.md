# Day40.4 — Identity Boundary and Channel-Convergence Correction Memo

**Session type:** DESIGN CORRECTION ONLY
**Status:** Correction — supersedes Day40.3 `f0bad40` on CEID constructor admissibility, pre-Task2 channel convergence, legacy/CEID coexistence, status/fill edge cases, and FPv2 byte-level vectors
**Baseline implementation authority:** `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`
**HEAD at session start:** `f0bad40` (Day40.3)
**Day40.3 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-3-final-identity-contract-correction-memo.md`
**Day40.2 memo:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-2-final-architecture-correction-memo.md`
**Approved Day39 design:** `docs/superpowers/specs/2026-09-08-strikenova-day39-order-state-synchronization-design.md`
**Deliverable:** this memo ONLY. No production code, no tests, no migrations were modified in this session.

---

## 0. Baseline verification (re-read this session, at HEAD `f0bad40`)

| Symbol | Committed state | Evidence |
|---|---|---|
| `__post_init__` fail-closed identity block | `if not self.provider_event_id:` → requires `broker_order_id`; then requires (`canonical_sequence` OR `fill_facts`). **There is NO `canonical_event_id` field at all.** | `backend/app/broker_sync/__init__.py:168-181` |
| `BrokerSyncEvent` fields | 14 committed fields, ending at `metadata` — no CEID parameter exists | `__init__.py:123-137` |
| `canonical_id` property | computes from `(tenant, broker, provider_event_id, event_type)` or fallback tuple — no override short-circuit | `__init__.py:183-210` |
| Task2 `_content_fingerprint` | includes `source_mode`, `canonical_sequence`, `event_version`, `provider_event_id` — provenance-bearing | `ingestion.py:67-107` |
| Task2 idempotency | same `canonical_id` + same fingerprint ⇒ `DUPLICATE_NOOP`; same id + different fingerprint ⇒ `CONFLICT` | `ingestion.py:853-885` |
| `BrokerSyncIdempotency` | PK = `canonical_id`; UNIQUE(`canonical_id`); `provider_event_id` column | `models.py:33,42,51` |

The audit's Issue 1 is confirmed against source: Day40.3 §2.5's proposed `__post_init__` change was specified but **not applied**, so a CEID event omitting all legacy discriminators raises `ValueError` today. Day40.3 §2.5 was an unimplemented specification; §2.6-2 claimed an exemption that no committed code grants. Corrected here.

---

## 1. Executive decision

1. **Issue 1 — Option A chosen.** `canonical_event_id`, when present, is sufficient deterministic identity and is checked **before** all legacy identity validation. Exact validation order, constructor behavior, compatibility guarantees, and constructor admissibility matrix (Invariants S) are specified in §2.
2. **Issue 2 — Convergence is a hard architectural boundary.** A `broker_sync_observation` dedup gate stands **before** Task2 conflict logic. `DUPLICATE DELIVERY` collapses at that gate and never constructs a second `BrokerSyncEvent`. PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` + `RETURNING` + `SELECT ... FOR UPDATE` + single-transaction commit guarantees exactly-one construction under two simultaneous workers (§3).
3. **Issue 3 — Option B chosen.** Cross-family semantic dedup via a unique `(tenant_id, broker, d1, content_fingerprint)` gate index. The first arrival binds `legacy_id` or `ceid` to the observation permanently; the same semantic observation cannot occupy two idempotency keys (Invariant U, §4).
4. **Issue 4 — status/fill separation made deterministic.** `complete + filled_quantity < quantity` ⇒ REJECTED/QUARANTINED. `open + filled_quantity > 0` ⇒ option **C**: two explicitly distinct normalized observations (order-state status observation + economic fill observation), never an implicit synthetic fill (Invariant V, §5).
5. **Issue 5 — FPv2 byte-level vectors published** (computed and cross-checked by an actual reference implementation this session, §6). Invariant W is now testable to the byte.
6. Adversarial cases 59–73 (§7), Invariants S–W (§8), SPEC tests (§9). Final gate (§10): **Foundation 🟡 NOT CLEARED**; **Task3 implementation authorization: NOT GRANTED; Task3 🔴 LOCKED.**

---

## 2. Issue 1 — CEID constructor contract (Option A)

### 2.1 Rule

**If `canonical_event_id is not None`, the fail-closed identity block (`__init__.py:168-181`) is skipped entirely and unconditionally.** The supplied 64-hex CEID is itself the deterministic identity — no legacy discriminator is required. If `canonical_event_id is None`, existing validation runs byte-for-byte unchanged.

### 2.2 Exact validation order (planned `__post_init__`, executable against committed code)

```
1.  non-empty-string checks: tenant_id, broker, event_type, event_version      # __init__.py:141-144 UNCHANGED
2.  enum coercion of event_type                                                 # :145-146 UNCHANGED
3.  timezone-aware checks: received_at, event_timestamp                         # :148-152 UNCHANGED
4.  provider_sequence positive-int check                                        # :154-157 UNCHANGED
5.  canonical_sequence positive-int check                                       # :159-162 UNCHANGED
6.  metadata Mapping check + deep-freeze                                        # :164-166 UNCHANGED
7.  [NEW] canonical_event_id admissibility:
        if canonical_event_id is not None:
            if not isinstance(str) or not re.fullmatch(r"[0-9a-f]{64}", ...):
                raise ValueError("canonical_event_id must be a 64-character lowercase hex string")
            -> SKIP the entire fail-closed identity block (step 8)
        else:
            -> run step 8 unchanged
8.  [GATED] fail-closed legacy identity validation                              # :168-181 UNCHANGED for canonical_event_id=None
```

Steps 1–6 run for every event regardless of CEID. A CEID does not excuse malformed timestamps or bad metadata — only identity discrimination.

### 2.3 Exact constructor behavior (planned)

- Field appended **last**: `canonical_event_id: Optional[str] = None`.
- Immutable after construction (frozen dataclass; no setter; `object.__setattr__` is used nowhere for it after validation).
- `canonical_id` property short-circuit: `if self.canonical_event_id is not None: return self.canonical_event_id` — placed at the **top** of the property (`__init__.py:183`), before any legacy computation.
- `event_id` alias returns `canonical_id` (thus the CEID) — unchanged.
- **A CEID event may have no `broker_order_id`** — yes, explicitly (the Day40.3 §2.6-2 exemption now actually holds). It may also lack `provider_event_id`, `canonical_sequence`, and `fill_facts` in any combination. Such an event is legal: D1 and FPv2 are bound via the `metadata["strikenova"]` block and verified at Task2 (§3.4); the event itself requires no further identity inputs.
- **`canonical_event_id` is authoritative before legacy identity validation** — yes, categorically (§2.2 step 7 precedes step 8). There is no ordering in which the legacy block can reject a well-formed CEID event.
- No `__eq__`/`__hash__` changes; no serialization changes.

### 2.4 Exact compatibility guarantee

For every constructor invocation expressible against the committed signature, output `canonical_id` and validation outcome are **bit-identical** before and after the change, because:

1. `canonical_event_id` defaults to `None` — existing call sites never pass it;
2. when `None`, steps 7–8 reduce exactly to the committed code path;
3. the CEID short-circuit is pure (no side effects).

Existing suites (e.g. `test_day39_task1_canonical_contract.py`) must pass **unmodified**. That is the acceptance criterion for the future Task1 change.

### 2.5 CEID + legacy discriminator interactions (all legal combinations)

| Combination | Legal? | canonical_id | Notes |
|---|---|---|---|
| CEID only (no order id, no seq, no fills) | ✅ | CEID | §2.3; metadata block binds D1/FPv2 |
| CEID + `broker_order_id` | ✅ | CEID | common Task3 case |
| CEID + `canonical_sequence` | ✅ | CEID | case 60; seq is ordering evidence, not identity |
| CEID + `provider_event_id` | ✅ | CEID | case 61; provider id is provenance + Day39-conflict scope |
| CEID + `fill_facts` | ✅ | CEID | fill events |
| no CEID, legacy-required discriminators | ✅ | legacy computed | today's behavior, unchanged |
| no CEID, no discriminators | ❌ raise | — | unchanged fail-closed |
| malformed CEID (length/charset) | ❌ raise | — | §2.2 step 7 |

### 2.6 Governance

Day40.3 §2.6-2's exemption claim is **corrected** from "already legal" to "legal under the planned Option A change (this memo §2)". The exemption is a constructor-contract clause of the planned change, not current behavior. Day40.3 §2.5 remains the specification; §2.2/§2.3 here pin its validation order and admissibility matrix. No other Day40.3 text is modified; §2.6-2 of that memo is superseded by this section.

---

## 3. Issue 2 — Channel convergence as a pre-Task2 boundary (Invariant T)

### 3.1 The defect, stated exactly

Task2's `_content_fingerprint` (`ingestion.py:67-107`) includes `source_mode` and `canonical_sequence`. STREAM and RECOVERY deliveries of the same semantic observation therefore differ in Task2 fingerprint. Under Day40.3 alone, "reconstruct the first delivery's fields" was an informal sentence in a Task3 contract paragraph — no boundary enforced it, so STREAM+RECOVERY would reach `ingestion.py:853-885` with same `canonical_id` + different fingerprint ⇒ `CONFLICT`. Corrected: the pipeline is split into two stages with a hard gate between them.

### 3.2 Pipeline boundary

```
provider observation (STREAM | RECOVERY | POLL)
   │
   ▼
Task3 observation correlation (D1 + FPv2 derivation)          # no Task2 interaction
   │
   ▼
DEDUP GATE  broker_sync_observation                            # PostgreSQL, §3.3
   │   UNIQUE (tenant_id, broker, d1, content_fingerprint)
   │   classification:
   │     NEW_OBSERVATION       — no row for (d1, fpv2): insert, proceed
   │     DUPLICATE_DELIVERY    — row exists, same (d1, fpv2): STOP. No Task2 event. Ever.
   │     CONTENT_CORRECTION    — row(s) exist for d1, none with this fpv2,
   │                             authoritative newer per Day40.3 §5 ladder: insert, proceed
   │     STALE_OBSERVATION     — correction test fails (authoritative older): record, STOP
   │     UNRESOLVED            — no authoritative ordering (Day40.3 §5.3): record
   │                             resolution=UNRESOLVED, STOP
   ▼
ONLY NEW_OBSERVATION / CONTENT_CORRECTION constructs a BrokerSyncEvent
   │  (identity-bearing fields bound at first authorized construction, §3.5)
   ▼
Task2 ingest_canonical_event (idempotency PK = canonical_id)
```

**Deliveries that reach Task2:** exactly `NEW_OBSERVATION` and `CONTENT_CORRECTION`.
**Deliveries that never reach Task2:** `DUPLICATE_DELIVERY` (the STREAM/RECOVERY redelivery case), `STALE_OBSERVATION`, `UNRESOLVED`. Task2's conflict rule is therefore only ever invoked with a genuinely new-or-corrected observation — a duplicate STREAM/RECOVERY delivery of an already-known `(D1, FPv2)` observation **cannot** generate a second `BrokerSyncEvent`, by construction.

### 3.3 Gate table and transaction contract (design)

```
broker_sync_observation
  tenant_id, broker,
  d1                  CHAR(64),
  content_fingerprint CHAR(64),
  first_source_mode, first_canonical_sequence (nullable), first_received_at,
  first_provider_event_id (nullable),
  bind_family         ('LEGACY' | 'CEID'),          -- §4
  bound_canonical_id  CHAR(64),                     -- §4
  resolution          ('APPLIED' | 'STALE' | 'UNRESOLVED'),
  delivery_count      BIGINT DEFAULT 1,
  first_seen_at, last_delivery_at,
  PRIMARY KEY (tenant_id, observation_id UUID),
  UNIQUE (tenant_id, broker, d1, content_fingerprint)   -- the dedup invariant
```

Every delivery executes in **one PostgreSQL transaction** (the same session Task2 later uses, so gate + Task2 commit/rollback atomically):

```
BEGIN
  iv := INSERT INTO broker_sync_observation
          (tenant_id, broker, d1, content_fingerprint, first_source_mode, ..., delivery_count=1)
        VALUES (..., now())
        ON CONFLICT (tenant_id, broker, d1, content_fingerprint) DO NOTHING
        RETURNING observation_id;

  IF iv IS NULL:                                  -- lost the insert race: row exists
     SELECT resolution, bind_family, bound_canonical_id,
            first_source_mode, first_canonical_sequence, first_provider_event_id,
            delivery_count
       INTO r
       FROM broker_sync_observation
       WHERE tenant_id=... AND broker=... AND d1=... AND content_fingerprint=...
       FOR UPDATE;                                -- row lock: serialize concurrent deliveries

     -- DUPLICATE_DELIVERY: no classification needed, (d1, fpv2) matches the bound row
     UPDATE ... SET delivery_count = delivery_count + 1, last_delivery_at = now();
     ROLLBACK-OR-COMMIT with NO Task2 call; return DUPLICATE_NOOP
     -- (commit only the counter bump; the single-tx design makes even a rollback harmless:
     --  a lost counter bump can never resurrect a duplicate event)

  ELSE:                                           -- we own the NEW row (or correction row)
     classify correction/stale/unresolved per Day40.3 §5 ladder (if a prior d1 row exists)
     IF proceeding:
        bind_family/bound_canonical_id := §4 binding (below)
        construct BrokerSyncEvent (fields per §3.5, from THIS row's bound values)
        result := Task2 ingest_canonical_event(event, db)     -- same session/tx
        -- Task2's own PK arbitration still applies inside the tx:
        --   same canonical_id + same Task2 fingerprint -> DUPLICATE_NOOP (defensive no-op)
        --   same canonical_id + different Task2 fingerprint -> CONFLICT (genuine contradiction)
        COMMIT
```

**Concurrent-channel guarantees:**

- **Two workers, same `(D1, FPv2)`, any channels, truly simultaneous:** the UNIQUE index admits exactly one insert; the loser's `ON CONFLICT DO NOTHING` returns no row ⇒ it takes the `FOR UPDATE` path, reads the bound row, increments `delivery_count`, and **never calls Task2**. Exactly one `BrokerSyncEvent` is constructed. No application-level lock is needed; the index + row lock are the mechanism.
- **STREAM and RECOVERY arriving concurrently (case 64):** whichever wins the insert binds the observation (§3.5) and is the authorized construction; the other is a `DUPLICATE_DELIVERY` regardless of channel. `first_source_mode` records the winner's channel for audit; channel is never a truth signal (Day40.3 §5.2 — provenance only).
- **`CONTENT_CORRECTION` under concurrency:** corrections insert a NEW row (different fpv2 ⇒ no UNIQUE collision), so two distinct corrections never race on the same row; their Task2 events have distinct CEIDs (different fingerprints) and are ordered by the §5 authority ladder, not by insert order.
- **Crash windows:** crash before COMMIT ⇒ gate row and Task2 effects roll back together (retry re-runs cleanly); crash after COMMIT ⇒ the gate row exists, so the retry is a `DUPLICATE_DELIVERY` no-op. Exactly-once construction holds in both windows.

### 3.4 Task2 verification hook (unchanged from Day40.3, restated for this boundary)

When `event.metadata["strikenova"]` carries `d1` + `content_fingerprint`, Task2 MUST verify `SHA256("CEIDv1:" ‖ d1 ‖ content_fingerprint) == event.canonical_id` and reject on mismatch (`REJECTED`, reason `canonical identity mismatch`) before the idempotency check. Events without the metadata block skip verification. The gate binds `bound_canonical_id` at first construction; the hook guarantees the constructed event's identity actually derives from the gate's `(d1, fpv2)` — together they close the loop.

### 3.5 Identity-bearing field binding (formal — replaces the informal sentence)

The first authorized construction (`NEW_OBSERVATION`, or a correction's first construction of that new content) records on the gate row: `first_source_mode`, `first_canonical_sequence`, `first_provider_event_id`, `first_received_at` — and the constructed `BrokerSyncEvent` uses exactly these values for every provenance-sensitive Task2 fingerprint input (`source_mode`, `canonical_sequence`, `provider_event_id`, and delivery `received_at` for logging only). These bound values are **never rewritten** by later deliveries of the same `(D1, FPv2)`. Consequence: any redelivery, reconstructed in any implementation, must be classified at the gate (it is a `DUPLICATE_DELIVERY` and never reconstructs an event at all). Task2 fingerprint divergence between channels becomes structurally impossible because only one construction exists per `(D1, FPv2)`.

---

## 4. Issue 3 — Legacy/CEID coexistence (Option B, Invariant U)

### 4.1 The overlap defect

Day40.3 permitted two identity families without a cross-family gate. The same semantic observation could then apply twice: once as a legacy-computed event (e.g. a legacy adapter or replay of old rows), once as a Task3 CEID event — two idempotency PKs, two applied business effects. Corrected with a deterministic mechanism.

### 4.2 Mechanism: binding at the same gate

The §3 gate row is the single binding record. On the first authorized construction of an observation, `bind_family` ∈ {`LEGACY`, `CEID`} is set and never changes:

- **Task3 path** (metadata `strikenova` block present, CEID verified per §3.4): `bind_family=CEID`, `bound_canonical_id=CEID`.
- **Legacy path** (no metadata block): `bind_family=LEGACY`, `bound_canonical_id=` the legacy computed `canonical_id`.

The gate's UNIQUE `(tenant_id, broker, d1, content_fingerprint)` is evaluated **before any construction**. A second arrival of the same semantic observation with the *other* identity family is a `DUPLICATE_DELIVERY` at the gate — it never constructs an event, so it can never take a second idempotency key. Cross-family duplicate business effects become structurally impossible (Invariant U).

Cases 67/68 (legacy event then equivalent CEID event, and vice versa): the second arrival is classified `DUPLICATE_DELIVERY`; `delivery_count` increments; `bind_family` retains the first family; no second event; the projection folds once.

### 4.3 Interaction with historical legacy rows

- Historical `BrokerSyncIdempotency` rows have no gate rows (the gate table is new). On activation, the gate starts empty: the first post-activation arrival of a semantic observation that already has a legacy idempotency row will bind `LEGACY` (or `CEID`) and proceed to Task2, where Task2's own idempotency check resolves it: same `canonical_id` + same Task2 fingerprint ⇒ `DUPLICATE_NOOP` (if the legacy row matches); same id + different fingerprint ⇒ `CONFLICT` (genuine contradiction, adjudicated); different id ⇒ genuinely new event, applied.
- No migration, backfill, or rewrite of historical rows is required or permitted. The gate binds forward only.
- **Production coexistence:** allowed, but only under this binding — both families may process different observations concurrently; the same semantic observation is processed by exactly one family (whichever bound it first), permanently.

### 4.4 What this rules out

- Day40.3 §8 case 44's "fold sees both; Task3 path authoritative for its scopes" — **superseded**: there is no "both" anymore; one semantic observation, one binding, one event.
- Any "first-writer-wins across families with later reconciliation" idea — rejected: binding is permanent and evaluated before construction, not reconciled after.

---

## 5. Issue 4 — Status/fill edge cases (Invariant V)

### 5.1 `status=complete + filled_quantity < quantity`

**REJECTED / QUARANTINED INVALID OBSERVATION.** Not reinterpreted as `PARTIAL_FILL`, not reinterpreted as `FULL_FILL`, not normalized by analogy:

- classification: `INVALID_OBSERVATION`;
- the raw payload is stored verbatim under `metadata["upstox"]` (preservation rules, Day40.3 §3.3);
- resolution is `UNRESOLVED`-scoped for review, per the gate (§3.2) — it never reaches Task2;
- escape only via authoritative provider evidence establishing otherwise (e.g. a corrected history row or a documented provider correction token): the corrected observation is a distinct observation with its own `(D1, FPv2)` and follows the normal gate flow;
- no emission, no projection change, operator review flag set.

### 5.2 `status=open + filled_quantity > 0` — answer: **C (both, as two explicitly distinct observations)**

One provider payload legitimately carries two independent facts; each is normalized explicitly, never implicitly:

1. **Order-state observation:** `status=open` ⇒ `ORDER_ACCEPTED` ⇒ projection `OPEN` (projection-only; `_BROKER_TO_LIFECYCLE[ORDER_ACCEPTED] = None`, `ingestion.py:124-147`). D1 = order-observation class for `ORDER_ACCEPTED`; FPv2 over the status snapshot.
2. **Economic fill observation:** `filled_quantity > 0` ⇒ `PARTIAL_FILL` (`0 < filled_quantity < quantity`) ⇒ `PARTIALLY_FILLED` projection; D1 = fill class; FPv2 over the fill content (`filled_quantity`, `average_price`, `trade_id` when present). With a provider `trade_id` this is a fill identity; without one it joins the composite-quarantine flow (Day40.3 §4).

**The fill observation exists only when a fill-bearing field set is explicitly present and internally consistent** (`filled_quantity`, `average_price` reported). A status snapshot never becomes a synthetic fill by itself: an `open` with `filled_quantity` absent/null produces only observation (1) — no fill observation is manufactured from absence of data. The two observations have independent `(D1, FPv2)` identities, independent gate rows, and may apply independently; neither borrows the other's identity (Invariant V).

### 5.3 Inventory retained

The corrected 17-row official inventory (Day40.3 §3.2) is retained verbatim; this section adds edge rules, it does not alter the mapping.

---

## 6. Issue 5 — FPv2 byte-level contract (Invariant W)

Rules are Day40.3 §6.2, unchanged. This section publishes the **shared vectors** (V1–V12). Byte-identical Python/TypeScript implementations must reproduce every canonical byte string and digest below. Field names in vectors are canonical FPv2 field names; standalone vectors show single-field objects for clarity. Reference implementation note: vectors were produced by a Python reference implementation of the FPv2 rules this session, including cross-variant equivalence asserts (multiple input spellings ⇒ one digest) and fail-closed checks (non-integral quantity raises; `-0` ⇒ `0`).

**Serializer recap (normative for the vectors):** NFC-normalize keys and string values; omit `null`/absent keys; preserve `""`; quantities via Decimal integral-check (`20.0`/`20.00`/`-0` ⇒ `20`/`0`); prices via Decimal with trailing-zero stripping (`0.10` ⇒ `0.1`); timestamps to UTC ms-truncated RFC 3339; `json.dumps(sort_keys=True, ensure_ascii=True, separators=(",", ":"))`; SHA256 hex lowercase.

| # | Vector | Input variant(s) | Canonical bytes (UTF-8) | SHA256 |
|---|---|---|---|---|
| V1 | integer quantity | `filled_quantity` = `20`, `20.0`, `20.00`, `20` (int) | `{"filled_quantity":"20"}` | `414f7729adf5105661c4fa05efe999e3fc81957c14858b132d24e0fbb09683bb` |
| V2 | price integral | `average_price` = `100`, `100.0`, `100.00`, `100` (int) | `{"average_price":"100"}` | `d12b30fc1bc36633df131df31111a49e17c0b31f136e96c87387c5fac09e5de5` |
| V3 | price 0.10 | `average_price` = `0.10` | `{"average_price":"0.1"}` | `69de99a626dea86f8eefcb0a4b0a602ae466b6143d60287d94ded3ed31f66bb5` |
| V4 | price 100.100 | `average_price` = `100.100` | `{"average_price":"100.1"}` | `9ca751a858e253d1826f6808a5592fd96241a5698bc0fb3537ae6db09b427f6e` |
| V5 | null | `reject_reason` = `null` | `{}` | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| V6 | absent field | (no `reject_reason` key) | `{}` | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| V7 | empty string | `reject_reason` = `""` | `{"reject_reason":""}` | `b8c789135e4fba4060491bff5848482d03a581355181b6f1862ca2b735ffa515` |
| V8 | Unicode NFC/NFD | `tag` = `I`+U+0303 (NFD) and `Ĩ` U+0128 (NFC) | `{"tag":"\u0128"}` | `cc886e0b90341419be5ded03c2a9425ed70de2510484a083ab72f30edab41c17` |
| V9 | timestamp 6-digit frac | `event_timestamp` = `2026-09-10T13:25:13.123456Z` | `{"event_timestamp":"2026-09-10T13:25:13.123Z"}` | `61a6ad850b4d0a54339b6fefec9f335494dfae99061ac068388a6d42bb7c2fa2` |
| V10 | timestamp no-fraction | `event_timestamp` = `2026-09-10T13:25:13Z` | `{"event_timestamp":"2026-09-10T13:25:13.000Z"}` | `08382c3aa66efecef40f359bfc7176cf10c1e811a1ddd07fb4b039a609564ce9` |
| V11 | negative zero | `filled_quantity` = `-0` and `0` | `{"filled_quantity":"0"}` | `92d9bedc7075ffd69b424658076bdc2fc444b7cfd5b7a775ee57021d8ccbe0bd` |
| V12 | large integer | `total_quantity` = `123456789012345678901234567890` | `{"total_quantity":"123456789012345678901234567890"}` | `b37ad8f9c024e7c85a781c31c37d46ccb29b0eca40bf9b8ff296d377a3603983` |

**V13 — composed full observation (all rules together):**

```
inputs: tenant_id="tenant-1", broker="UPSTOX", provider_order_id="240108010445130",
        event_type="FULL_FILL", provider_status="complete", total_quantity="100",
        filled_quantity="100.00", average_price="570.950", reject_reason=null,
        trade_id="", event_timestamp="2026-09-10T13:25:13.123456Z"

canonical bytes:
{"average_price":"570.95","broker":"UPSTOX","event_timestamp":"2026-09-10T13:25:13.123Z","event_type":"FULL_FILL","filled_quantity":"100","provider_order_id":"240108010445130","provider_status":"complete","tenant_id":"tenant-1","total_quantity":"100","trade_id":""}

sha256: bdca679d564b097e557f3869229e72a2a2701bca5d5b55e6ec1dc54d81bdcdcd
```

Cross-vector facts (all machine-verified): V1's four spellings and V2's four spellings each collapse to one digest; V5 ≡ V6; V7 ≠ V5; V8 collapses NFD/NFC; V9's four equivalent spellings (`…123456Z`, `…123Z`, `…123456+00:00`, `18:55:13.123+05:30`) collapse to one digest while V10 (no fraction ⇒ `.000`) is a distinct instant and a distinct digest; V11 collapses `-0`/`0`; non-integral `filled_quantity` (e.g. `20.5`) raises (fail-closed). Timestamp equivalence note: `+05:30` input `18:55:13.123` ⇒ UTC `13:25:13.123` (offset normalization verified).

---

## 7. Adversarial cases 59–73

Columns: Provider input · D1 · FPv2 · CEID · Task1 `canonical_id` · Task3 observation state · Task2 submission? · Task2 fingerprint · Ledger · Projection · Final result. Gate = `broker_sync_observation` (§3). Case 54's 17-status traversal and cases 1–58 remain in force.

| # | Provider input | D1 | FPv2 | CEID | Task1 canonical_id | Task3 observation state | Task2 submission? | Task2 fingerprint | Ledger | Projection | Final result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 59 | CEID event, no `broker_order_id`, no `fill_facts`, no seq | order D1 | content hash | `SHA256("CEIDv1:"‖D1‖FPv2)` | = CEID | gate NEW; bind CEID | **YES** (legal per §2.5) | computed (no seq/source ambiguity — fields bound §3.5) | gate row + idempotency row | per event class | constructible under Option A (Invariant S); metadata digest verified |
| 60 | CEID + `canonical_sequence` | order D1 | content hash | CEID | = CEID | gate NEW; bind CEID | YES | computed (seq is ordering evidence) | gate + idempotency | per class | seq excluded from CEID; participates in Task2 fp only via bound value |
| 61 | CEID + `provider_event_id` | order D1 | content hash | CEID | = CEID | gate NEW; bind CEID | YES | computed | gate + idempotency | per class | provider id = provenance + Day39 conflict scope; identity is CEID |
| 62 | STREAM first, RECOVERY second (same semantic observation) | same | same | same | same | NEW → DUPLICATE_DELIVERY | 1st YES; 2nd **NO** | 1st computed; 2nd none | 1 row, delivery_count=2 | applied once | collapse before Task2 (Invariant T) |
| 63 | RECOVERY first, STREAM second | same | same | same | same | NEW → DUPLICATE_DELIVERY | 1st YES; 2nd NO | as 62 | 1 row, delivery_count=2 | applied once | channel order irrelevant |
| 64 | STREAM + RECOVERY truly simultaneous | same | same | same | same | one NEW; loser DUPLICATE | winner YES; loser NO | winner's only | 1 row; `first_source_mode` = winner | applied once | UNIQUE + FOR UPDATE serialize; exactly one construction |
| 65 | duplicate semantic observation reaches gate twice (any channels) | same | same | same | same | DUPLICATE_DELIVERY | NO (2nd+) | none | delivery_count++ | unchanged | no second BrokerSyncEvent — structural |
| 66 | correction arrives at gate before Task2 (authoritative newer) | same | different | new CEID | new | CONTENT_CORRECTION | YES | computed for new content | new gate row + new idempotency row | folds to correction | Day40.3 §5 ladder decides; arrival order irrelevant |
| 67 | legacy event bound first; equivalent CEID event arrives | same | same | same CEID | 1st: legacy computed; 2nd: would-be CEID | 1st NEW (bind LEGACY); 2nd DUPLICATE_DELIVERY | 1st YES; 2nd NO | 1st computed | 1 gate row (bind_family=LEGACY) + idempotency row | applied once | cross-family duplication impossible (Invariant U) |
| 68 | CEID event bound first; equivalent legacy event arrives | same | same | same | 1st: CEID; 2nd: would-be legacy | 1st NEW (bind CEID); 2nd DUPLICATE_DELIVERY | 1st YES; 2nd NO | as 67 | 1 gate row (bind_family=CEID) | applied once | mirror of 67 |
| 69 | `complete` + `filled_quantity < quantity` | order D1 | status+qty content | none emitted | none | INVALID_OBSERVATION | **NO** | none | raw payload preserved; UNRESOLVED-scope | unchanged | REJECTED/QUARANTINED (§5.1); never silently partial |
| 70 | `open` + `filled_quantity > 0` | two D1s (order + fill) | two FPv2s | two (when fill construction authorized) | two distinct | two gate rows: NEW×2 | YES (both, explicitly) | two fingerprints | order-state row + fill row | OPEN + PARTIALLY_FILLED | option C: two distinct observations (§5.2); no synthetic implicit fill |
| 71 | identical FPv2, `source_mode` differs (STREAM vs RECOVERY) | same | same | same | same | DUPLICATE_DELIVERY (2nd) | 1st only | bound | 1 row, delivery_count=2 | applied once | provenance never re-identifies (Q/T) |
| 72 | identical FPv2, `canonical_sequence` differs | same | same | same | same | DUPLICATE_DELIVERY (2nd) | 1st only | bound | 1 row | applied once | seq excluded from FPv2/CEID; only first-bound value enters Task2 fp |
| 73 | FPv2 shared-vector suite (§6) run on Python + TS | n/a | V1–V13 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | byte-identical digests required (Invariant W) |

---

## 8. Invariants S–W (added to Day40.1 A–H, Day40.2 I–M, Day40.3 N–R)

| # | Invariant | Defense | SPEC tests |
|---|---|---|---|
| **S** — constructor admissibility | Every CEID state described by these memos is constructible by the planned Task1 contract: the §2.5 matrix is total — every row is either constructible or raises with a named reason | §2.2 validation order; §2.5 admissibility matrix | CON-01..03, T1ID-* |
| **T** — pre-Task2 convergence | Duplicate STREAM/RECOVERY observations are collapsed before Task2 when Task2's provenance-sensitive fingerprint would otherwise conflict; a duplicate never constructs a second event | §3 gate UNIQUE + single-transaction INSERT..ON CONFLICT..RETURNING + FOR UPDATE; §3.5 binding | CVG-01..05 |
| **U** — legacy/CEID non-duplication | The same semantic provider observation cannot produce two applied business events merely because identity family differs | §4 binding at the gate evaluated before construction; UNIQUE `(tenant, broker, d1, fpv2)` | OVL-01..03 |
| **V** — status/fill separation | An order-status observation cannot implicitly create a synthetic economic fill; `complete`+short-fill is quarantined; `open`+partial is two explicit observations | §5.1/§5.2; fill observation only from explicit fill-bearing fields | SF-01..03 |
| **W** — byte-level fingerprint determinism | The same semantic observation produces identical FPv2 bytes across supported implementations | §6 vectors V1–V13 as shared fixtures | FPV-01..05 |

---

## 9. Test specification — SPEC only

No tests executed. All entries are design specifications. Existing suites must pass unmodified (§2.4 acceptance criterion).

| Area | Test | Status |
|---|---|---|
| CEID constructor acceptance/rejection | CON-01: CEID-only event constructs (no order id/seq/fills); CON-02: malformed CEID (length, uppercase, non-hex) raises; CON-03: non-CEID event without discriminators still raises (unchanged); CON-04: all §2.5 combinations construct and vend `canonical_id == canonical_event_id` | SPEC |
| channel convergence before Task2 | CVG-01: STREAM→RECOVERY redelivery ⇒ one event, delivery_count=2; CVG-02: RECOVERY→STREAM mirror; CVG-03: correction ⇒ new CEID event, folds; CVG-04: stale ⇒ recorded, no submission; CVG-05: unresolved ⇒ quarantined, no submission | SPEC |
| concurrent channel dedup | CVG-06: two workers same (D1, FPv2) simultaneously ⇒ exactly one construction (UNIQUE + FOR UPDATE); CVG-07: crash-before-commit retry re-runs; crash-after-commit retry is duplicate no-op | SPEC |
| legacy/CEID overlap | OVL-01: legacy-then-CEID equivalent ⇒ single applied event (case 67); OVL-02: CEID-then-legacy mirror (case 68); OVL-03: binding is permanent — no rebind on later deliveries | SPEC |
| complete/open quantity inconsistency | SF-01: `complete` + short fill ⇒ REJECTED/QUARANTINED, raw preserved, no projection change; SF-02: `open` + partial ⇒ two distinct observations, both applied, no synthetic fill; SF-03: `open` + absent `filled_quantity` ⇒ order-state observation only | SPEC |
| FPv2 byte-level vectors | FPV-01: V1–V13 reproduce canonical bytes + digests exactly (Python); FPV-02: same in TypeScript; FPV-03: V5≡V6, V7≠V5; FPV-04: V9 four-spelling collapse, V10 distinct; FPV-05: provenance changes (`source_mode`, `canonical_sequence`) and key reordering leave FPv2/CEID unchanged (cases 71/72) | SPEC |
| provenance changes without CEID changes | (folded into FPV-05 and CVG-01..03) | SPEC |
| canonical_sequence changes without CEID changes | (folded into FPV-05 and case 72) | SPEC |

---

## 10. Final gate

| Area | Gate | Evidence |
|---|---|---|
| Day38 | 🟢 APPROVED | No Day38 change; projection fold semantics untouched; `ORDER_ACCEPTED → None` retained |
| D1 | 🟢 APPROVED | Correlation-only identity; gate key component; never an idempotency PK |
| Canonical ID | 🟡 SINGLE CONTRACT (mechanism pending) | One evaluator + CEID derivation (Day40.3 §2); Task1 additive change still unimplemented |
| **CEID Constructor Contract** | 🟡 DEFINED (Option A) | §2: validation order, admissibility matrix, compatibility guarantee; NOT implemented; audit Issue 1 resolved |
| **Channel Convergence** | 🟡 DEFINED (hard boundary) | §3: gate before Task2; duplicate never constructs; concurrency guaranteed by UNIQUE + FOR UPDATE; audit Issue 2 resolved |
| **Legacy/CEID Coexistence** | 🟡 DEFINED (Option B binding) | §4: pre-construction binding; cross-family duplication structurally impossible; audit Issue 3 resolved |
| Fill Identity | 🟡 YELLOW | TRADE_ID path deterministic; composite path fail-closed (Day40.3 §4) |
| Identity Upgrade | 🟢 APPROVED | Alias model, no PK mutation (Day40.3 §4) |
| Ordering Authority | 🟡 DEFINED | Day40.3 §5 ladder; receipt order excluded |
| **FPv2** | 🟡 SPECIFIED + VECTORED | §6: V1–V13 byte-level vectors published from a reference implementation; TS vectors pending implementation |
| **Status Inventory** | 🟢 APPROVED + EDGE RULES | 17-row inventory retained; `complete`+short-fill and `open`+partial made deterministic (§5) |
| Task3 Design | 🟡 YELLOW | Internally consistent, boundary-complete; not independently verified |
| **Task3 Implementation** | **🔴 LOCKED** | **Task3 implementation authorization: NOT GRANTED** |
| Foundation | 🟡 **NOT CLEARED** | Requires: Task1 additive change (§2) + gate table migration + Task2 verification hook + ORDER_PROCESSING + SPEC implementation + independent verification. **NOT GREEN.** |

Green requires all five audit conditions: (1) CEID constructible under the actual Task1 contract — specified, not implemented; (2) channel convergence guaranteed before Task2 conflict logic — specified as a structural boundary; (3) legacy/CEID overlap cannot duplicate business events — specified via binding; (4) status/fill distinction deterministic — specified; (5) FPv2 byte-level deterministic — vectors published, cross-implementation verification pending. None of the five is yet implemented or independently verified.

```
Task3 implementation authorization: NOT GRANTED
```

---

## 11. Safety report

- **BASELINE:** implementation authority `aa65e1e1202491d71a204bb5cf6578cd56bf3e09`; HEAD at session start `f0bad40` (Day40.3)
- **DAY40.4 MEMO:** `docs/superpowers/contracts/2026-09-10-strikenova-day40-4-identity-boundary-correction-memo.md` (this file)
- **FILES CHANGED:** one memo added (this file); no other file created, modified, or deleted
- **CODE CHANGED:** none
- **TESTS EXECUTED:** none (design only; FPv2 vectors were computed with a temporary reference implementation outside the repository, removed after use — no repository test was executed)
- **COMMIT:** single memo commit (see git output); only this memo staged — no code, tests, migrations, or other docs included
- **PUSH:** to `origin/feat/strikenova-day35-portfolio-intelligence`
- **FINAL GATE:** 🟡 NOT CLEARED (Foundation) — NOT GREEN
- **TASK3 STATUS:** 🔴 LOCKED — Task3 implementation authorization: NOT GRANTED
