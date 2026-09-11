# StrikeNova — CockroachDB Compatibility Fix Design

**Design Report ID:** CRDB-FIX-DESIGN-001  
**Date:** 2026-09-12  
**Status:** DESIGN ONLY — NO IMPLEMENTATION  
**Based on:**  
- `options-dashboard-project/docs/architecture/NORTHFLANK_COCKROACH_MIGRATION_AUDIT.md`  
- `options-dashboard-project/docs/architecture/COCKROACH_COMPATIBILITY_EXPERIMENT.md`  

---

## 1. Executive Summary

This report designs the exact code changes required to make StrikeNova compatible with CockroachDB, and the test plan to validate those changes. It is a **design-only checkpoint** — no implementation has been performed.

**Three compatibility gaps were confirmed:**

| Gap | File | Severity | Nature |
|-----|------|----------|--------|
| A | `app/utils/db_dialect.py:dialect_insert()` | HIGH | Dialect dispatch misses `cockroachdb`; falls to generic insert without ON CONFLICT support |
| B | `app/broker_sync/fill_ledger.py:_upsert_trade_fill()` | HIGH | Hard-bifurcates PostgreSQL vs SQLite; CockroachDB falls into SQLite path |
| C | `app/broker_sync/ingestion.py:_advance_broker_sequence()` | HIGH | OCC pattern has no serialization-failure retry; CockroachDB SERIALIZABLE would abort the transaction under contention |

**Key design decisions:**

1. **Dialect abstraction:** Group PostgreSQL and CockroachDB as "PostgreSQL-compatible dialects" — they share the same insert API, type system, and ON CONFLICT syntax. The correct fix is to recognize `cockroachdb` alongside `postgresql`, not to create separate branches.

2. **Retry architecture:** The retry unit must be the **entire caller-owned transaction**, not individual statements or SAVEPOINTs. This is because CockroachDB's SERIALIZABLE isolation can abort the entire transaction on contention, and StrikeNova's transaction functions are designed as atomic units (execute_strategy, exit_position, ingest_canonical_event).

3. **Implementation sequence:** Fix dialect dispatch first (gaps A and B), then implement retry architecture (gap C), then add tests, then validate against live CockroachDB.

4. **Implementation-design status:** READY — the design is sufficiently understood to begin implementation. **Live CockroachDB validation is still required** before production migration approval.

---

## 2. Current Baseline

### 2.1 Git State

```
Branch:       feat/strikenova-day35-portfolio-intelligence
HEAD:        ef3f494a0fd29d51901df9f8f42d29df542a774b (docs(experiment): add CockroachDB compatibility experiment report)
Remote:      origin = shahid1995/-options-dashboard
Modified:    6 files (pre-existing Day41 work: .gitignore, adapter.py, mapper.py, paper_execution.py, upstox.py, test_upstox_adapter.py)
Untracked:   106 files (pre-existing exploration artifacts)
```

**Working tree is NOT clean** due to pre-existing Day41 broker-sync changes. These are NOT part of this design task and must not be touched.

### 2.2 Python Environment

```
Python:               3.11.16
SQLAlchemy:           2.0.52
Alembic:              1.19.2
psycopg:              3.3.5 (psycopg-binary)
sqlalchemy-cockroachdb: 2.0.4
FastAPI:              0.141.1
pytest:               9.1.1
```

### 2.3 Files Read for This Design

| File | Purpose |
|------|---------|
| `app/utils/db_dialect.py` | Dialect-aware insert dispatch (36 lines) |
| `app/db.py` | Engine + session creation (402 lines) |
| `app/broker_sync/fill_ledger.py` | Fill ledger + arbitration (1052 lines) |
| `app/broker_sync/ingestion.py` | Event ingestion pipeline (1239 lines) |
| `app/trade_lifecycle/persistence.py` | Lifecycle event persistence (400 lines) |
| `app/services/paper_execution.py` | Paper trading engine (1489 lines) |
| `app/broker_sync/models.py` | Broker sync ORM models (125 lines) |
| `app/models.py` | Core SQLAlchemy models (936 lines) |
| `alembic/env.py` | Alembic environment (114 lines) |
| `alembic.ini` | Alembic configuration (120 lines) |
| `NORTHFLANK_COCKROACH_MIGRATION_AUDIT.md` | Previous audit (3506 lines) |
| `COCKROACH_COMPATIBILITY_EXPERIMENT.md` | Previous experiment (1287 lines) |

---

## 3. Evidence Reviewed

### 3.1 Audit Conclusions Verified

The migration audit (`NORTHFLANK_COCKROACH_MIGRATION_AUDIT.md`) identified three blockers. The experiment (`COCKROACH_COMPATIBILITY_EXPERIMENT.md`) confirmed all three through code analysis and SQL compilation tests:

1. **Dialect branching gaps (A, B):** Confirmed by reading `db_dialect.py:15-36` and `fill_ledger.py:518-579`. The CRDB dialect name is `"cockroachdb"`, not `"postgresql"`, so both functions fall to the wrong branch.

2. **Missing retry handling (C):** Confirmed by reading `ingestion.py:364-418`. The `_advance_broker_sequence` function uses an OCC pattern with `rowcount` checking, but has no handling for serialization failures (SQLSTATE 40001).

3. **SQL compilation correctness:** The experiment verified that the CRDB dialect compiles correct SQL for all StrikeNova patterns (ON CONFLICT DO NOTHING RETURNING, FOR UPDATE, FOR UPDATE SKIP LOCKED, partial indexes, BYTEA, JSON, etc.).

### 3.2 What Was NOT Verified

Live CockroachDB execution was blocked by infrastructure limitations. The following remain **REQUIRES LIVE CRDB VERIFICATION**:

- Actual serialization failure exception type and SQLSTATE from psycopg + CRDB
- Whether SAVEPOINT isolation survives CRDB transaction aborts
- Whether `ON CONFLICT DO NOTHING RETURNING` returns rows correctly under CRDB concurrency
- Whether partial index `WHERE is_default = true` works on CRDB
- Whether Alembic migrations apply cleanly against CRDB

---

## 4. Three Confirmed Compatibility Gaps

### Gap A: `db_dialect.py:dialect_insert()` — Missing CRDB Dialect Recognition

**File:** `options-dashboard-project/backend/app/utils/db_dialect.py`  
**Lines:** 15-36  
**Function:** `dialect_insert(engine: Engine, table: Table) -> Insert`

**Current behavior:**

```python
def dialect_insert(engine: Engine, table: Table):
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        # Fallback: generic insert (no on_conflict_do_update)
        from sqlalchemy import insert
        return insert(table)
```

**Problem:** When `engine.dialect.name == "cockroachdb"`, the function returns a generic `insert()` from `sqlalchemy import insert` that does NOT support `.on_conflict_do_update()` or `.on_conflict_do_nothing()`.

**Callers of `dialect_insert()`:**

The function is used wherever StrikeNova needs a dialect-aware insert that supports ON CONFLICT. Searching the codebase shows usage in `models.py` and potentially in service layers. The exact call sites need to be traced — but the function's purpose is to provide the correct insert construct, and it currently doesn't handle CRDB.

**SQLAlchemy compatibility evidence:**

The CRDB dialect (via `sqlalchemy-cockroachdb`) registers as `CockroachDBDialect_psycopg` with name `"cockroachdb"`. The `CockroachCompiler` (in `sqlalchemy_cockroachdb.stmt_compiler`) compiles PostgreSQL-style INSERT statements with ON CONFLICT clauses correctly. The SQL compilation test in the experiment confirmed:

```sql
INSERT INTO test_table (id, name, payload) 
VALUES (%(id)s::INTEGER, %(name)s::VARCHAR, %(payload)s) 
ON CONFLICT (id) DO NOTHING 
RETURNING test_table.id, test_table.name
```

This is byte-identical to what PostgreSQL's insert would generate.

**Recommended design:**

```python
def dialect_insert(engine: Engine, table: Table):
    dialect_name = engine.dialect.name
    if dialect_name in ("postgresql", "cockroachdb"):
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        from sqlalchemy import insert
        return insert(table)
```

**Rationale:** PostgreSQL and CockroachDB share the same SQLAlchemy insert API (`on_conflict_do_update`, `on_conflict_do_nothing`, `returning`). The CRDB dialect compiles the same SQL. There is no behavioral difference that would require separate branches. This is the minimal change — a one-line modification to the condition.

**Affected callers:** All callers of `dialect_insert()` that chain `.on_conflict_...()` after it. These callers will now work correctly on CRDB without any changes to the callers themselves.

**Risk:** LOW. The change is purely additive — it adds a dialect name to an existing condition. PostgreSQL and SQLite behavior is unchanged. The only new path is CRDB, which uses the same PostgreSQL insert implementation.

**Test coverage required:**
- Unit test: `dialect_insert` with a mock CRDB engine returns a PostgreSQL insert construct
- Unit test: the returned construct supports `.on_conflict_do_update()` and `.on_conflict_do_nothing()`
- Integration test: actual INSERT with ON CONFLICT DO NOTHING RETURNING on CRDB

---

### Gap B: `fill_ledger.py:_upsert_trade_fill()` — Missing CRDB Dialect Branch

**File:** `options-dashboard-project/backend/app/broker_sync/fill_ledger.py`  
**Lines:** 518-579  
**Function:** `_upsert_trade_fill(db: Session, ...) -> BrokerFillLedgerFill | None`

**Current behavior:**

```python
def _upsert_trade_fill(db: Session, ...):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = dict(...)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = pg_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    else:
        stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    result = db.execute(stmt)
    created = result.first() is not None
    if created:
        return db.execute(
            select(BrokerFillLedgerFill).where(...)
        ).scalar_one()
    return None
```

**Problem:** When `bind.dialect.name == "cockroachdb"`, the function uses the SQLite insert path. This generates SQLite-specific SQL syntax which may not work correctly on CockroachDB.

**SQL generated by each path:**

PostgreSQL path:
```sql
INSERT INTO broker_fill_ledger_fill (tenant_id, provider_order_id, fill_eq_key, ...)
VALUES (%(tenant_id)s::VARCHAR, %(provider_order_id)s::VARCHAR, ...)
ON CONFLICT (tenant_id, provider_order_id, fill_eq_key) DO NOTHING
RETURNING broker_fill_ledger_fill.tenant_id
```

SQLite path:
```sql
INSERT INTO broker_fill_ledger_fill (tenant_id, provider_order_id, fill_eq_key, ...)
VALUES (?, ?, ?, ...)
ON CONFLICT (tenant_id, provider_order_id, fill_eq_key) DO NOTHING
RETURNING broker_fill_ledger_fill.tenant_id
```

On CockroachDB, the SQLite path would either fail (if CRDB doesn't accept SQLite parameter style) or generate suboptimal SQL.

**Callers:**

`_upsert_trade_fill` is called by `apply_lane_b_fill` (line 380 in fill_ledger.py), which is the Lane B economic fill arbitration path. `apply_lane_b_fill` is called during broker-sync event ingestion when a fill event with a trade_id arrives.

**Transaction boundary:**

`_upsert_trade_fill` performs NO commit. It flushes the INSERT and returns either the created row or None. The caller (`apply_lane_b_fill`) is responsible for the transaction boundary. The caller-owned transaction contract is explicit in the Day41.1 design (lines 22-36 of fill_ledger.py).

**CRDB compatibility of the PostgreSQL path:**

The PostgreSQL insert path is semantically correct for CockroachDB. The CRDB dialect compiles the same SQL: `INSERT ... ON CONFLICT (tenant_id, provider_order_id, fill_eq_key) DO NOTHING RETURNING tenant_id`. The CRDB experiment confirmed this compilation works.

**RETURNING semantics:**

The `RETURNING` clause is critical for the "did we create the row?" determination. On PostgreSQL, `result.first() is not None` correctly indicates whether THIS transaction inserted the row. On CockroachDB, the same semantics should hold — the experiment's compilation test showed the RETURNING clause is included in the generated SQL.

**Conflict handling and idempotency:**

The `_upsert_trade_fill` function is the atomic arbitration point for Lane B fills. The unique constraint on `(tenant_id, provider_order_id, fill_eq_key)` ensures that only one transaction can create a given fill row. The ON CONFLICT DO NOTHING makes the arbitration deterministic: exactly one transaction gets a returned row (the winner), all others get zero rows (the losers).

This design is **correct for CockroachDB** — the unique constraint and ON CONFLICT behavior are standard SQL features that CRDB supports.

**Retry behavior around the upsert:**

**No retry is needed around the upsert itself.** The upsert is a single atomic statement. If it fails with a serialization error, the entire transaction must be retried (see Gap C design). The upsert itself does not need special retry logic — it relies on the database's ON CONFLICT mechanism for concurrency safety.

**Fill-ledger invariants under retry:**

If the entire transaction containing `_upsert_trade_fill` is retried (due to a serialization failure), the following invariants must hold:

1. **No duplicate fills:** The unique constraint on `(tenant_id, provider_order_id, fill_eq_key)` prevents duplicate fill rows even if the transaction is retried.
2. **No duplicate observations:** The observation creation in `apply_lane_b_fill` is part of the same transaction. If the transaction is retried, the observation is created again — but the observation_id is a new UUID each time. Wait — this is a problem. Let me re-examine.

Actually, looking at `apply_lane_b_fill` (lines 313-496), the observation is created with a NEW UUID (`observation_id=str(uuid.uuid4())`) each time the function is called. If the transaction is retried, a new observation row would be created with a new UUID. This could result in duplicate observations for the same fill event.

**However**, the caller of `apply_lane_b_fill` is the ingestion pipeline (`ingestion.py`). The ingestion pipeline's idempotency is handled at a higher level — by `BrokerSyncIdempotency` (canonical_id primary key) and `BrokerSyncSequenceAnchor` (sequence advancement). If the same event is processed twice, the idempotency layer rejects the duplicate BEFORE `apply_lane_b_fill` is called.

So the retry scenario is:
1. Transaction T1 starts, processes event E, calls `apply_lane_b_fill`, creates fill row F and observation O1, then fails with serialization error
2. Transaction T1 is rolled back (fill row F and observation O1 are gone)
3. Transaction T2 starts (retry), processes event E again, calls `apply_lane_b_fill`, creates fill row F (same unique key, ON CONFLICT DO NOTHING — but wait, F was rolled back, so the key is free) and observation O2 (new UUID)

In this scenario, T2 would successfully create the fill row (since T1's row was rolled back) and a new observation O2. This is correct — the fill is created once (by the winning transaction), and the observation is a new record.

But there's a subtlety: `apply_lane_b_fill` returns `"APPLIED"` only if `_upsert_trade_fill` returns a row (i.e., THIS transaction created the fill). If the transaction is retried and the fill row was already created by a concurrent transaction that won the race, `_upsert_trade_fill` returns None, and `apply_lane_b_fill` classifies the result as `"DUPLICATE_FILL"` or `"CONFLICT"`.

This is the correct behavior. The retry architecture must ensure that:
- The retry happens at the transaction level (the entire `ingest_canonical_event` call is retried)
- The idempotency layer (`BrokerSyncIdempotency`) ensures the same event is not processed twice across retries
- The `_upsert_trade_fill` arbitration ensures only one transaction creates the fill row

**Conclusion:** No fill-ledger invariant is violated by retrying the transaction, provided the idempotency layer and the unique constraints work correctly. This is REQUIRES LIVE CRDB VERIFICATION — we need to confirm that:
1. The unique constraint on `broker_fill_ledger_fill` works on CRDB
2. ON CONFLICT DO NOTHING RETURNING returns the correct result on CRDB
3. The transaction retry does not create duplicate observations

**Recommended design:**

```python
def _upsert_trade_fill(db: Session, ...):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = dict(...)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name in ("postgresql", "cockroachdb"):
        stmt = pg_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    else:
        stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    result = db.execute(stmt)
    created = result.first() is not None
    if created:
        return db.execute(
            select(BrokerFillLedgerFill).where(...)
        ).scalar_one()
    return None
```

**Rationale:** Same as Gap A — CRDB shares the PostgreSQL insert API. The change is a one-line modification to the condition. No changes to the RETURNING logic, no changes to the caller contract.

**Risk:** LOW. The change is purely additive. The PostgreSQL and SQLite paths are unchanged. The CRDB path uses the same PostgreSQL implementation that was verified to compile correct SQL.

**Test coverage required:**
- Unit test: `_upsert_trade_fill` with a mock CRDB bind returns a PostgreSQL insert construct
- Unit test: the returned construct's SQL compiles correctly for CRDB
- Integration test: concurrent fills on CRDB produce exactly one APPLIED result and one DUPLICATE_FILL/CONFLICT result
- Integration test: retrying a failed transaction does not create duplicate fill rows or observations

---

### Gap C: `ingestion.py:_advance_broker_sequence()` — Missing Serialization Retry

**File:** `options-dashboard-project/backend/app/broker_sync/ingestion.py`  
**Lines:** 364-418  
**Function:** `_advance_broker_sequence(db: Session, event: BrokerSyncEvent, position_info: dict | None) -> None`

**Current behavior:**

```python
def _advance_broker_sequence(db: Session, event: BrokerSyncEvent, position_info: dict | None) -> None:
    if position_info is None:
        return
    if position_info["is_duplicate"]:
        return

    incoming = position_info["incoming"]
    expected = position_info["last_sequence"]
    broker_order_id = position_info["broker_order_id"]

    result = db.execute(text("""
        UPDATE broker_sync_sequence_anchor
        SET last_sequence = :advance_to,
            updated_at = :now
        WHERE tenant_id = :tenant_id
          AND broker = :broker
          AND broker_order_id = :broker_order_id
          AND last_sequence = :expected
    """), {
        "advance_to": incoming,
        "expected": expected,
        "tenant_id": event.tenant_id,
        "broker": event.broker,
        "broker_order_id": broker_order_id,
        "now": datetime.now(timezone.utc),
    })
    db.flush()

    if result.rowcount == 1:
        return

    raise IngestionError(
        f"concurrent worker advanced broker sequence past {incoming}",
        action="CONFLICT",
    )
```

**Problem:** The OCC pattern checks `rowcount == 0` to detect concurrent advancement. On PostgreSQL (READ COMMITTED), this works because:
- If another transaction holds the row lock, the UPDATE waits
- When the lock is released, the UPDATE either succeeds (rowcount=1) or fails to match (rowcount=0)
- Serialization failures are rare in READ COMMITTED

On CockroachDB (SERIALIZABLE), the behavior is different:
- Two concurrent transactions that both read the same `last_sequence` and try to UPDATE may both be serializable
- CRDB detects the conflict and aborts one of the transactions with SQLSTATE 40001 (serialization failure)
- The aborted transaction's `db.flush()` would raise an exception BEFORE `rowcount` is checked
- The exception would propagate up, potentially aborting the entire outer transaction

**Complete call graph around `_advance_broker_sequence`:**

Let me trace the full flow:

1. **`ingest_canonical_event`** (the main entry point, approximately lines 600+ in ingestion.py) — this is the caller that owns the session and transaction.

2. Inside `ingest_canonical_event`:
   - Validates event identity
   - Checks `BrokerSyncIdempotency` (canonical_id PK) — if duplicate, returns early
   - Calls `_validate_broker_sequence_position` (line 259) — reads the anchor, validates sequence position
   - Calls `_ensure_broker_sequence_anchor` (line 324) — creates anchor if missing (inside SAVEPOINT)
   - Builds projection via `_build_projection` (line 516)
   - Inserts `BrokerOrderProjection` row
   - Inserts `BrokerSyncIdempotency` row
   - Calls `append_lifecycle_event` (from trade_lifecycle/persistence.py) — inserts lifecycle event
   - Calls `_advance_broker_sequence` (line 364) — advances the sequence anchor
   - All of the above happen inside a SAVEPOINT (nested transaction)
   - On success, the SAVEPOINT is committed (implicitly, when the with block exits)
   - The caller's outer transaction is committed separately

3. **Who owns the Session?**

   The session is owned by the caller of `ingest_canonical_event`. The function signature takes a `db: Session` parameter. The caller is responsible for creating the session, beginning the transaction, and committing/rolling back.

   Looking at the broader codebase, the session is typically created in the router layer or service layer, and the transaction is managed there. For example, in `paper_execution.py:execute_strategy`, the session is passed in and the function calls `db.commit()` at the end.

   For broker-sync ingestion, the session ownership depends on the caller. If the caller is a background task or a sync process, it may manage the session and transaction explicitly.

4. **Where does the transaction begin and end?**

   Based on the code structure:
   - The transaction begins when the caller creates a session and performs the first write (or explicitly begins a transaction)
   - The transaction is nested via `db.begin_nested()` (SAVEPOINT) for the ingestion operations
   - The outer transaction commits when the caller calls `db.commit()`
   - The outer transaction rolls back if the caller calls `db.rollback()` or if an exception propagates

   The key insight: `_advance_broker_sequence` is called INSIDE the SAVEPOINT. If it raises an exception (serialization failure), the SAVEPOINT is rolled back, but the outer transaction may or may not be affected, depending on how SQLAlchemy/CRDB handle the error.

**What other writes occur in the same transaction?**

Within the same SAVEPOINT (and thus the same logical unit of work):
- `BrokerOrderProjection` insert (normalized order state)
- `BrokerSyncIdempotency` insert (durable idempotency record)
- `TradeLifecycleEvent` insert (via `append_lifecycle_event`, which uses its own SAVEPOINT)
- `BrokerSyncSequenceAnchor` UPDATE (via `_advance_broker_sequence`)

Within the same outer transaction (but potentially different SAVEPOINTs):
- Possibly other broker events being processed in batch
- Possibly raw observation commits (from `raw_ingress.py`)

**External side effects:**

The ingestion pipeline does NOT perform external side effects within the transaction. All operations are database writes. The broker API calls (fetching events) happen BEFORE the transaction. The only external effect is the database state change.

**Can `_advance_broker_sequence` be safely retried?**

**No, not in isolation.** Retrying only the UPDATE statement would not be safe because:
1. The UPDATE is part of a larger transaction that includes projection, idempotency, and lifecycle event inserts
2. If the UPDATE fails with a serialization error, the entire transaction state is suspect
3. Retrying just the UPDATE would leave the projection and idempotency inserts in an inconsistent state (they may or may not have been committed depending on SAVEPOINT behavior)

**Can the entire transaction be retried?**

**Yes, with caveats.** The entire `ingest_canonical_event` operation can be retried IF:
1. The idempotency layer (`BrokerSyncIdempotency`) ensures the same event is not processed twice
2. The sequence anchor advancement is idempotent (the UPDATE uses `last_sequence = :expected`, so a retry with the same expected value is safe)
3. The lifecycle event insertion is idempotent (the `event_id` unique constraint prevents duplicates)

However, there's a critical issue: **caller-owned sessions make generic retry wrappers unsafe.**

If the caller creates a session and passes it to `ingest_canonical_event`, a generic retry wrapper cannot simply retry the function call because:
1. The session may be in an invalid state after a serialization failure
2. The session's identity map may have stale objects
3. The caller may have performed other operations in the same session before calling `ingest_canonical_event`

**Where should retry happen?**

The retry should happen at the **service boundary** that owns the session and transaction. This is the layer that:
1. Creates the session
2. Begins the transaction
3. Calls `ingest_canonical_event` (or equivalent)
4. Commits or rolls back

For broker-sync ingestion, this is likely a background task or a sync manager that processes events in a loop. The retry wrapper should:
1. Catch serialization failures (SQLSTATE 40001)
2. Roll back the current transaction
3. Create a NEW session
4. Retry the entire operation from the beginning
5. Use exponential backoff between retries

**Why not inside `_advance_broker_sequence`?**

Because `_advance_broker_sequence` is a helper function that operates on a caller-provided session. It does not own the transaction. Retrying inside this function would require:
1. Rolling back the SAVEPOINT (possible via `db.rollback()`)
2. Re-executing the UPDATE (but the outer transaction state is unclear)
3. Potentially leaving the caller's session in an inconsistent state

This is too fragile. The retry must be at a level that owns the transaction.

**Why not at the ingestion service boundary?**

Actually, this IS the correct place. The "ingestion service boundary" is the code that calls `ingest_canonical_event` with a fresh session and manages the transaction. This is where the retry wrapper should be placed.

**The correct retry boundary:**

```
Service/Task Layer (owns session + transaction)
    ↓
    with Session() as db:
        try:
            db.begin()  # or rely on autocommit=False + first write
            ingest_canonical_event(db, event)
            db.commit()
        except SerializationFailure:
            db.rollback()
            # retry with new session
```

This is the safest boundary because:
1. The service layer owns the session lifecycle
2. A serialization failure rolls back the entire transaction
3. A new session is created for the retry
4. The idempotency layer ensures the retry is safe (same event, same canonical_id)

---

## 5. Complete Transaction-Boundary Map

### 5.1 Core Trading Transactions

#### `execute_strategy` (paper_execution.py:328-587)

```
Transaction boundary: Caller owns session; execute_strategy calls db.commit() at line 585
Entry:         db.scalar(select(StrategyExecution).where(client_order_id=...)) — line 363
               (SELECT, no lock)
Idempotency:   UniqueConstraint("user_id", "client_order_id") on strategy_executions — line 134 of models.py
               If duplicate INSERT attempted, IntegrityError raised
Writes:        StrategyExecution (line 446), Trade (line 463), PaperOrder (line 485),
               Position (line 509), PaperTransaction (line 544), Leg (line 557),
               StrategyLegExposure (line 581)
Commit:        db.commit() at line 585
Flush points:  db.flush() at lines 459, 474, 503, 524, 570 (after each object creation)
```

**CRDB implications:**
- The idempotency check is a simple SELECT — no lock, no serialization guarantee
- Under CRDB SERIALIZABLE, two concurrent `execute_strategy` calls with the same `client_order_id` could both pass the SELECT, then one fails on INSERT with a unique constraint violation
- The unique constraint provides correctness (no duplicate executions), but the failing transaction would raise IntegrityError, not a clean retry
- Under CRDB SERIALIZABLE, a serialization failure (40001) could also occur if the two transactions read overlapping data
- **Retry needed:** YES — at the caller level, catching both IntegrityError (unique constraint) and serialization failures (40001)

#### `exit_position` (paper_execution.py:615-798)

```
Transaction boundary: Caller owns session; exit_position calls db.commit() at line 797 (if commit=True)
Entry:         db.execute(select(Position).where(id=...).with_for_update()) — line 645-647
               (SELECT FOR UPDATE — row lock acquired)
Idempotency:   find_exit_replay() checks for existing exit order by client_order_id — line 651
               UniqueConstraint("user_id", "client_order_id") on paper_orders — line 175 of models.py
Lock:          FOR UPDATE on Position row — serializes concurrent exits on same position
Writes:        PaperOrder (line 684), Position update (line 695-707), PaperTransaction (line 716),
               Leg updates (via _close_journal_legs, line 767-831)
Commit:        db.commit() at line 797 (if commit=True), or caller commits (if commit=False for bulk)
```

**CRDB implications:**
- FOR UPDATE serializes concurrent exits on the same position — this is correct and works on CRDB
- Under CRDB SERIALIZABLE, two concurrent exits on DIFFERENT positions could still conflict if they read overlapping data (e.g., the same Trade row for journal leg updates)
- The bulk exit path (commit=False) is a long-running transaction touching many positions — higher serialization risk
- **Retry needed:** YES — at the caller level for bulk exits; individual exits have FOR UPDATE protection but may still hit serialization failures

#### `bulk_exit` (paper_execution.py:837-1043)

```
Transaction boundary: Single transaction for entire bulk operation
                   exit_position called with commit=False (line 981)
                   _record_bulk_exit calls db.commit() at line 1107
Pre-validation:  All positions checked for open status + market prices (lines 910-930)
                 NO writes before validation — atomicity preserved
Writes:         Multiple exit_position calls (each modifies Position, PaperOrder, PaperTransaction, Leg)
                 BulkExitRecord insert (line 1090-1106)
Commit:        db.commit() at line 1107 (in _record_bulk_exit)
```

**CRDB implications:**
- This is the HIGHEST RISK transaction for CRDB migration
- Long-running, touches many rows, many positions, many journal legs
- Under CRDB SERIALIZABLE, the probability of serialization failure increases with transaction length and row count
- **Retry needed:** YES — bulk_exit MUST have retry handling. The entire operation should be retried on serialization failure.

### 5.2 Lifecycle Event Transactions

#### `append_lifecycle_event` (trade_lifecycle/persistence.py:249-385)

```
Transaction boundary: Caller owns session; this function NEVER commits
                    Uses db.begin_nested() (SAVEPOINT) for insert — lines 367-384
Idempotency:   event_id unique constraint (primary key) — line 86 of persistence.py
               (tenant_id, aggregate_type, aggregate_id, sequence) unique constraint — lines 122-128
SAVEPOINT:    db.begin_nested() creates savepoint; db.flush() triggers INSERT
              On SAIntegrityError: savepoint rolled back, outer transaction intact — lines 370-384
              Re-reads event by event_id to determine if duplicate or conflict
```

**CRDB implications:**
- The SAVEPOINT pattern is designed for PostgreSQL IntegrityError handling
- On CRDB, a serialization failure during db.flush() inside the SAVEPOINT may:
  1. Roll back only the SAVEPOINT (desired behavior)
  2. Abort the entire outer transaction (CRDB-specific behavior, unverified)
- If the outer transaction is aborted, the caller's subsequent operations fail
- **This is REQUIRES LIVE CRDB VERIFICATION** — we need to confirm SAVEPOINT behavior under CRDB serialization failures

#### `allocate_position_sequence` (trade_lifecycle/persistence.py:195-242)

```
Transaction boundary: Caller owns session; no commit in this function
Idempotency:   INSERT ... ON CONFLICT DO UPDATE ... RETURNING — lines 215-239
               Atomic upsert on position_sequence_anchor unique key
Lock:         Implicit via ON CONFLICT — serializes concurrent sequence allocation
Returns:      last_position_sequence (from RETURNING)
```

**CRDB implications:**
- The ON CONFLICT DO UPDATE pattern is correct for CRDB
- The RETURNING clause returns the new sequence value
- This is a single atomic statement — low serialization risk
- **Retry needed:** NO — the atomic upsert handles concurrency correctly. If a serialization failure occurs, it would be at the transaction level, not the statement level.

### 5.3 Broker-Sync Transactions

#### `ingest_canonical_event` (ingestion.py, main entry point ~lines 600+)

```
Transaction boundary: Caller owns session
                     All operations inside a SAVEPOINT (nested transaction)
                     CALLER commits/rolls back outer transaction
Idempotency:   BrokerSyncIdempotency.canonical_id (primary key) — prevents duplicate event processing
               BrokerSyncSequenceAnchor.last_sequence (OCC via _advance_broker_sequence)
Operations:    _validate_broker_sequence_position (read-only, line 259)
               _ensure_broker_sequence_anchor (INSERT ON CONFLICT DO NOTHING, line 324)
               _build_projection + insert BrokerOrderProjection (line 516+)
               insert BrokerSyncIdempotency (line ~650+)
               append_lifecycle_event (line ~680+, uses its own SAVEPOINT)
               _advance_broker_sequence (UPDATE with rowcount check, line 364)
Lock:         None explicitly — relies on unique constraints + OCC
Commit:       Caller's responsibility
```

**CRDB implications:**
- The SAVEPOINT pattern is used for the entire ingestion operation
- If any operation inside the SAVEPOINT fails (including `_advance_broker_sequence`), the SAVEPOINT is rolled back
- The outer transaction may or may not be affected (REQUIRES LIVE CRDB VERIFICATION)
- **Retry needed:** YES — at the service/task level that owns the session. The entire `ingest_canonical_event` call should be retried on serialization failure.

#### `apply_lane_b_fill` (fill_ledger.py:313-496)

```
Transaction boundary: Caller owns session; NO commit in this function
                     Part of the larger ingestion transaction (Phase-2 contract)
Idempotency:   _upsert_trade_fill uses INSERT ON CONFLICT DO NOTHING RETURNING — line 518
               UniqueConstraint on (tenant_id, provider_order_id, fill_eq_key) — implicit from PK
Arbitration:  DATABASE decides winner via ON CONFLICT — exactly one APPLIED, rest DUPLICATE_FILL/CONFLICT
Writes:       BrokerFillLedgerFill (via _upsert_trade_fill), BrokerFillLedgerObservation (line 477),
              BrokerFillIdentityLineage (via _append_lineage)
Commit:       Caller's responsibility (the ingestion transaction)
```

**CRDB implications:**
- The ON CONFLICT DO NOTHING RETURNING arbitration is correct for CRDB
- The unique constraint prevents duplicate fills
- The RETURNING clause determines the winner
- **Retry needed:** NO at this level — the arbitration is atomic. Retry is at the ingestion transaction level (see `ingest_canonical_event` above).

#### `_advance_broker_sequence` (ingestion.py:364-418)

```
Transaction boundary: Called within SAVEPOINT of ingest_canonical_event
                     db.flush() only — no commit
Pattern:        Optimistic concurrency control (OCC)
                UPDATE with WHERE last_sequence = :expected — line 391-398
                If rowcount == 1: success (this worker advanced)
                If rowcount == 0: conflict (another worker advanced) → IngestionError(CONFLICT)
No retry:        On any failure, IngestionError is raised, caller handles
```

**CRDB implications:**
- The OCC pattern relies on rowcount checking, which works on PostgreSQL READ COMMITTED
- On CRDB SERIALIZABLE, a serialization failure would raise an exception BEFORE rowcount is checked
- The exception would propagate, potentially aborting the SAVEPOINT and possibly the outer transaction
- **Retry needed:** YES — but at the transaction level (ingest_canonical_event), not inside this function

### 5.4 Other Transaction Helpers

#### `raw_ingress.commit_raw_observation` (raw_ingress.py)

```
Transaction boundary: Owns its own commit (Phase-1 raw ingest)
                     Independent from Phase-2 broker-sync transaction
Purpose:        Persist raw broker observation before normalization
```

**CRDB implications:** This is a separate transaction from the broker-sync pipeline. It would need its own retry handling if it performs writes that could conflict.

#### Background GEX capture loop (main.py:40+)

```
Transaction boundary: Each iteration creates its own SessionLocal() — line 142 of main.py
                     db operations in try/finally for cleanup
                     No explicit transaction management visible — relies on SQLAlchemy defaults
```

**CRDB implications:** The GEX capture loop creates short-lived sessions for each capture. Each capture is a separate transaction. Serialization risk is low (single-row inserts/updates). Retry handling may not be critical for this path, but should be evaluated.

---

## 6. Recommended Dialect Abstraction

### 6.1 Problem Statement

StrikeNova currently has scattered dialect checks:

```python
if dialect_name == "postgresql":
    ...
elif dialect_name == "sqlite":
    ...
else:
    ...
```

This pattern appears in:
- `db_dialect.py:dialect_insert()` — lines 27-36
- `fill_ledger.py:_upsert_trade_fill()` — lines 557-566
- `db.py:_engine()` — lines 48-67 (sqlite vs non-sqlite)
- `db.py:init_db()` — line 305 (sqlite-only index creation)
- `alembic/env.py:_render_as_batch()` — line 58-60 (sqlite-only batch mode)
- `alembic/env.py:run_migrations_online()` — lines 86-98 (sqlite vs non-sqlite engine creation)
- Migration `125e1807df8d` — lines 84-96 (postgresql vs else for partial index)

### 6.2 Recommended Abstraction

**Concept:** Introduce a PostgreSQL-compatible dialect grouping. PostgreSQL and CockroachDB share the same SQLAlchemy insert API, type system, ON CONFLICT syntax, and transaction semantics (at the SQLAlchemy level). They should be treated as one group.

**Implementation approach:** The minimal change is to update the existing dialect checks to include `"cockroachdb"` alongside `"postgresql"` where the PostgreSQL path is semantically correct for CRDB.

**Where to group:**

| Location | Current check | Recommended check | Reason |
|----------|--------------|-------------------|--------|
| `db_dialect.py:dialect_insert()` | `== "postgresql"` | `in ("postgresql", "cockroachdb")` | CRDB uses same insert API |
| `fill_ledger.py:_upsert_trade_fill()` | `== "postgresql"` | `in ("postgresql", "cockroachdb")` | CRDB uses same insert API |
| `db.py:_engine()` | `startswith("sqlite")` vs else | Keep as-is (sqlite vs non-sqlite) | Engine config is same for PG and CRDB |
| `db.py:init_db()` | `== "sqlite"` | Keep as-is | SQLite-only indexes |
| `alembic/env.py:_render_as_batch()` | `startswith("sqlite")` | Keep as-is | Batch mode is SQLite-only |
| `alembic/env.py:run_migrations_online()` | `startswith("sqlite")` | Keep as-is | Engine creation is same for PG and CRDB |
| Migration `125e1807df8d` | `== "postgresql"` | `in ("postgresql", "cockroachdb")` | CRDB supports partial indexes with boolean WHERE |

**Where NOT to group (genuine differences):**

- SQLite vs non-SQLite engine configuration (PRAGMA settings, check_same_thread)
- Batch mode for Alembic (SQLite only)
- SQLite-only index creation in init_db()

These are genuine differences and should remain separate.

**Do not over-abstract:**

Do NOT introduce a new abstraction layer like:

```python
class DialectGroup:
    POSTGRESQL_COMPATIBLE = {"postgresql", "cockroachdb"}
    SQLITE = {"sqlite"}
```

This adds complexity without benefit. The existing `if/elif/else` pattern with the added `"cockroachdb"` membership is sufficient.

**Rationale:** The groupings are simple (two dialects per group), and the checks are localized to a few functions. A formal abstraction would add indirection without solving a real maintenance problem.

### 6.3 Migration Dialect Handling

The migration `125e1807df8d` (lines 84-96) uses a runtime dialect check:

```python
dialect = op.get_bind().dialect.name
if dialect == "postgresql":
    op.execute("CREATE UNIQUE INDEX ... WHERE is_default = true")
else:
    op.execute("CREATE UNIQUE INDEX ... WHERE is_default = 1")
```

**Recommended change:** Add a `cockroachdb` branch:

```python
if dialect in ("postgresql", "cockroachdb"):
    op.execute("CREATE UNIQUE INDEX ... WHERE is_default = true")
elif dialect == "sqlite":
    op.execute("CREATE UNIQUE INDEX ... WHERE is_default = 1")
```

**Wait — is this the right approach?**

Actually, the migration uses `op.get_bind().dialect.name` at migration execution time. This means the dialect is determined by the database the migration is running against. If we run the migration against CockroachDB, `dialect` would be `"cockroachdb"`, and it would fall into the `else` branch (SQLite path), using `WHERE is_default = 1`.

The fix is to add `"cockroachdb"` to the PostgreSQL branch. This ensures the migration creates the partial index with the correct boolean literal for CRDB.

**Alternative approach:** Use SQLAlchemy's `op.create_index()` with a `postgresql_where` parameter. But `postgresql_where` is PostgreSQL-specific and may not work on CRDB. The raw SQL approach with dialect branching is more explicit and verifiable.

**Actually, the cleanest approach:** Use a single raw SQL statement that works on all three dialects. CRDB supports both `true` and `1` as boolean expressions? Let me think...

CRDB supports `true` and `false` as boolean literals. It also supports integer comparisons. The column `is_default` is defined as `Boolean()`. On CRDB, `is_default = true` is the correct comparison. `is_default = 1` might work (CRDB may coerce `1` to `true`), but it's not guaranteed.

The safest approach is the dialect-specific branch with `true` for both PostgreSQL and CockroachDB.

---

## 7. Recommended DB URL/Engine Approach

### 7.1 Current State

`db.py:normalize_database_url()` handles:
- `postgres://` → `postgresql+psycopg://`
- `postgresql://` → `postgresql+psycopg://`
- Everything else (including `cockroachdb://`) passes through unchanged

`db.py:_engine()` handles:
- SQLite URLs: special connect_args + PRAGMA hooks
- Non-SQLite URLs: pool_size=5, max_overflow=10, pool_timeout=30, pool_recycle=1800, pool_pre_ping=True

### 7.2 Recommended URL Format

**Use `cockroachdb+psycopg://` for CockroachDB connections.**

This is the standard SQLAlchemy URL format for CockroachDB via psycopg. The `sqlalchemy-cockroachdb` package registers the `cockroachdb` dialect, and the `psycopg` driver provides the DBAPI connection.

**Why not `postgresql+psycopg://`?**

CockroachDB Cloud CAN accept `postgresql://` URLs (it's PostgreSQL-compatible at the protocol level). However, using `cockroachdb+psycopg://` explicitly signals that the target is CockroachDB, which:
1. Makes the configuration self-documenting
2. Ensures the SQLAlchemy dialect is correctly identified as `cockroachdb`
3. Allows the dialect branching to work correctly

**But wait — would `postgresql+psycopg://` work?**

If we use `postgresql+psycopg://` for a CockroachDB connection, SQLAlchemy would use the PostgreSQL dialect (`dialect.name == "postgresql"`). This would actually WORK for the dialect branching fixes proposed above (since we're grouping `postgresql` and `cockroachdb` together). However, it would be misleading — the application would think it's connected to PostgreSQL when it's actually connected to CockroachDB.

**Recommendation:** Use `cockroachdb+psycopg://` for clarity and correctness. The dialect branching fixes should handle both `postgresql` and `cockroachdb` names for robustness.

### 7.3 normalize_database_url Changes

**Current function:**
```python
def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
```

**Recommended addition:**
```python
def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("cockroachdb://"):
        return "cockroachdb+psycopg://" + url[len("cockroachdb://"):]
    return url
```

**Rationale:** CockroachDB Cloud may provide URLs with the `cockroachdb://` scheme. Normalizing to `cockroachdb+psycopg://` ensures the correct dialect is used.

### 7.4 Engine Configuration

The current non-SQLite engine configuration is appropriate for CockroachDB:

```python
eng = create_engine(
    url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
```

**pool_pre_ping:** This is appropriate for CockroachDB. It helps detect stale connections (e.g., if the CRDB cluster restarts or connection is dropped). Keep it.

**pool_recycle=1800 (30 minutes):** This is reasonable. CockroachDB does not have a specific connection timeout that requires more frequent recycling. Keep it.

**SSL configuration:** CockroachDB Cloud requires SSL/TLS. The connection URL should include `sslmode=verify-full` (or `sslmode=verify-ca` with the CA certificate). The `sqlalchemy-cockroachdb` package may provide a helper for this, but the standard psycopg SSL parameters should work.

**No CockroachDB-specific connection options needed.** The `cockroachdb+psycopg://` URL format with standard psycopg connection parameters is sufficient.

### 7.5 Summary of DB URL/Engine Recommendations

| Aspect | Current | Recommended |
|--------|---------|-------------|
| URL format for CRDB | N/A (not configured) | `cockroachdb+psycopg://user:pass@host:26257/db?sslmode=verify-full` |
| normalize_database_url | Handles postgres:// and postgresql:// | Also handle cockroachdb:// |
| Engine config | Pool size 5, overflow 10, recycle 1800, pre_ping | Same — appropriate for CRDB |
| SSL | Not explicitly configured (PostgreSQL uses env var or cert path) | Add sslmode to URL or rely on psycopg default |
| pool_pre_ping | True | Keep True — helps with stale connections |

---

## 8. Recommended Retry Architecture

### 8.1 Exception to Detect

**REQUIRES LIVE CRDB VERIFICATION** — The exact exception type and SQLSTATE for CockroachDB serialization failures must be confirmed against a live CRDB instance.

**Expected exception hierarchy (based on SQLAlchemy + psycopg documentation):**

```
SerializationFailure (custom exception)
  └── sqlalchemy.exc.OperationalError
        └── psycopg.errors.SerializationFailure (psycopg 3.x)
              └── SQLSTATE 40001 (serialization_failure)
```

**What we know from documentation:**

- CockroachDB returns SQLSTATE `40001` for serialization failures
- The error message typically contains "retry transaction" or "SerializationFailure"
- psycopg 3.x maps this to `psycopg.errors.SerializationFailure`
- SQLAlchemy wraps DBAPI errors in `sqlalchemy.exc.OperationalError`

**What we need to verify:**

1. Does psycopg 3.3.5 raise `psycopg.errors.SerializationFailure` for CRDB SQLSTATE 40001?
2. Does SQLAlchemy wrap it in `OperationalError`?
3. Can we detect the serialization failure by checking `ex.orig` (the original psycopg error)?
4. Does the error include the SQLSTATE code?

**Runtime experiment required:**

```python
# Pseudo-code for the runtime experiment
from sqlalchemy.exc import OperationalError
import psycopg.errors

try:
    # Cause a serialization conflict with two concurrent transactions
    pass
except OperationalError as e:
    print(f"Exception type: {type(e)}")
    print(f"Exception: {e}")
    if hasattr(e, 'orig'):
        print(f"Original exception: {type(e.orig)}")
        print(f"Original: {e.orig}")
        if isinstance(e.orig, psycopg.errors.SerializationFailure):
            print("CONFIRMED: SerializationFailure detected")
        print(f"SQLSTATE: {getattr(e.orig, 'sqlstate', 'N/A')}")
```

This experiment must be run against a live CRDB instance with two concurrent transactions that conflict.

### 8.2 Retry Unit

**Recommended retry unit: The entire caller-owned transaction.**

Not statement retry, not SAVEPOINT retry, not individual function retry.

**Rationale:**

1. **CRDB SERIALIZABLE aborts entire transactions.** When CRDB detects a serialization conflict, it aborts the entire transaction, not just the conflicting statement. A SAVEPOINT rollback may not be sufficient — the outer transaction may be marked as invalid.

2. **StrikeNova transactions are atomic units.** `execute_strategy`, `exit_position`, `ingest_canonical_event` are designed as atomic operations. All writes within them are part of a single logical unit. Retrying the entire transaction preserves atomicity.

3. **Idempotency layers make retry safe.** Each transaction function has idempotency protection:
   - `execute_strategy`: `client_order_id` unique constraint
   - `exit_position`: `client_order_id` unique constraint + `find_exit_replay()`
   - `ingest_canonical_event`: `canonical_id` primary key on `BrokerSyncIdempotency`
   - `apply_lane_b_fill`: `ON CONFLICT DO NOTHING` on fill row unique constraint
   
   These ensure that retrying a transaction does not create duplicate effects.

4. **Caller-owned sessions require new sessions for retry.** After a serialization failure, the session may be in an invalid state. The retry should create a NEW session and retry the entire operation.

**Why not statement retry?**

Statement-level retry (e.g., retrying just the UPDATE in `_advance_broker_sequence`) is insufficient because:
1. The UPDATE is part of a larger transaction with other writes
2. If the UPDATE fails, the transaction state is suspect
3. Retrying just the UPDATE leaves other writes in an uncertain state

**Why not SAVEPOINT retry?**

SAVEPOINT retry (rolling back to the SAVEPOINT and re-executing) might work on PostgreSQL, but on CRDB:
1. The serialization failure may abort the entire transaction, not just the SAVEPOINT
2. Even if the SAVEPOINT is intact, the outer transaction state is unclear
3. The SQLAlchemy `begin_nested()` SAVEPOINT may not provide the isolation guarantees needed for CRDB retry

**Why not function-level retry?**

Retrying just `ingest_canonical_event` (or `execute_strategy`) without creating a new session is unsafe because:
1. The session may be in an invalid state after the serialization failure
2. The session's identity map may have stale objects
3. The caller may have performed other operations in the same session

**The correct pattern:**

```python
# At the service/task level that owns the session
def run_with_retry(operation, max_attempts=3, base_delay=0.1):
    """
    Execute a database operation with CockroachDB serialization retry.
    
    Creates a new session for each attempt. Rolls back on failure.
    """
    last_error = None
    for attempt in range(max_attempts):
        db = SessionLocal()  # New session for each attempt
        try:
            result = operation(db)
            db.commit()
            return result
        except OperationalError as e:
            db.rollback()
            if _is_serialization_failure(e):
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(base_delay * (2 ** attempt))  # Exponential backoff
                    continue
            raise  # Not a serialization failure, or max attempts exhausted
        finally:
            db.close()
    raise last_error
```

### 8.3 Retry Policy

**Recommended initial policy:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max attempts | 3 | Sufficient for transient serialization conflicts; prevents infinite retry loops |
| Base delay | 100ms | Short initial delay; serialization conflicts are typically transient |
| Backoff | Exponential (2^attempt) | 100ms, 200ms, 400ms for attempts 1, 2, 3 |
| Jitter | None initially | Simple implementation; can add jitter if needed |
| Configurable | Yes | Max attempts and base delay should be configurable via settings |

**Why 3 attempts?**

- Most serialization conflicts are transient and resolve quickly
- 3 attempts with exponential backoff covers the common case
- More attempts increase the risk of retry storms under high contention
- If 3 attempts fail, the conflict is likely persistent (e.g., long-running transaction blocking)

**Why exponential backoff?**

- Prevents retry storms (multiple clients retrying simultaneously)
- Gives the conflicting transaction time to complete
- Standard pattern for CRDB retry handling

**Jitter:**

Not required initially. Can be added if retry storms are observed. Jitter would be a random fraction of the backoff delay (e.g., `delay * (0.5 + random.random())`).

### 8.4 Configurable Retry Settings

Add to `app/config.py`:

```python
# CockroachDB serialization retry configuration
CRDB_RETRY_MAX_ATTEMPTS: int = 3
CRDB_RETRY_BASE_DELAY_SECONDS: float = 0.1
```

These should be configurable via environment variables:

```bash
CRDB_RETRY_MAX_ATTEMPTS=3
CRDB_RETRY_BASE_DELAY_SECONDS=0.1
```

**Why configurable?** Different deployment environments may have different contention characteristics. A high-contention production environment may need more attempts; a low-contention staging environment may need fewer.

### 8.5 Where to Apply Retry

| Operation | Retry Location | Retry Unit | Notes |
|-----------|---------------|------------|-------|
| `execute_strategy` | Service/router layer | Entire transaction (new session) | Idempotent via client_order_id |
| `exit_position` (single) | Service/router layer | Entire transaction (new session) | FOR UPDATE provides some protection; retry for serialization failures |
| `bulk_exit` | Service/router layer | Entire transaction (new session) | HIGHEST priority for retry — long transaction, many rows |
| `ingest_canonical_event` | Broker-sync task layer | Entire transaction (new session) | Idempotent via canonical_id; OCC sequence advancement |
| `apply_lane_b_fill` | NOT directly | N/A | Part of ingest_canonical_event transaction |
| `append_lifecycle_event` | NOT directly | N/A | Part of ingest_canonical_event transaction; SAVEPOINT handles IntegrityError |
| `allocate_position_sequence` | NOT directly | N/A | Atomic upsert; low conflict risk |
| Raw observation commit | Task layer | Entire transaction (new session) | Separate Phase-1 transaction |

**Key principle:** Retry at the layer that owns the session and transaction. Do not add retry logic inside the transaction functions themselves.

---

## 9. Operation-by-Operation Retry Safety Matrix

### 9.1 Classification

| Operation | Retry Safety | Rationale | Required Action |
|-----------|-------------|-----------|-----------------|
| `execute_strategy` | SAFE TO RETRY | Idempotent via `client_order_id` unique constraint. All writes are within one transaction. Retry creates a new session and re-executes; the unique constraint prevents duplicate execution. | Add retry wrapper at service/router layer |
| `exit_position` (single) | SAFE TO RETRY | FOR UPDATE on Position row serializes concurrent exits. Idempotent via `client_order_id`. Retry is safe because the unique constraint prevents duplicate exit orders. | Add retry wrapper at service/router layer |
| `bulk_exit` | SAFE TO RETRY (with caution) | Idempotent via `client_order_id` on `BulkExitRecord`. All exits use `exit_position` with `commit=False`. The entire operation is one transaction. Retry is safe but may be expensive (re-validates all positions, re-executes all exits). | Add retry wrapper at service/router layer. Monitor for long-running transaction issues. |
| `ingest_canonical_event` | SAFE TO RETRY | Idempotent via `canonical_id` primary key on `BrokerSyncIdempotency`. The sequence anchor advancement is OCC-based and safe to retry (UPDATE with `last_sequence = :expected`). Lifecycle events are idempotent via `event_id`. | Add retry wrapper at broker-sync task layer |
| `apply_lane_b_fill` | RETRY ONLY AT OUTER TRANSACTION | Part of `ingest_canonical_event` transaction. The `_upsert_trade_fill` arbitration is atomic (ON CONFLICT DO NOTHING). The function itself does not need retry — the outer transaction retry handles it. | No separate retry needed |
| `_upsert_trade_fill` | RETRY ONLY AT OUTER TRANSACTION | Atomic INSERT ON CONFLICT DO NOTHING. The function is a single statement. If it fails, it's due to transaction-level serialization, not statement-level. | No separate retry needed |
| `append_lifecycle_event` | REQUIRES LIVE VALIDATION | Uses SAVEPOINT for IntegrityError handling. On CRDB, a serialization failure during the SAVEPOINT flush may or may not invalidate the outer transaction. Needs live testing to determine if outer transaction retry is sufficient or if SAVEPOINT behavior requires changes. | Run live CRDB test: cause serialization failure during SAVEPOINT flush, observe whether outer transaction is valid |
| `allocate_position_sequence` | SAFE TO RETRY | Atomic INSERT ON CONFLICT DO UPDATE RETURNING. Single statement, low conflict risk. The unique constraint prevents duplicate sequence allocation. | No separate retry needed; covered by outer transaction retry if needed |
| Raw observation ingestion (`raw_ingress.commit_raw_observation`) | REQUIRES LIVE VALIDATION | Separate Phase-1 transaction. Need to trace exact operations and determine if serialization failures are possible. | Trace code, then evaluate |
| GEX capture loop (main.py) | LOW PRIORITY | Short-lived transactions, single operations per capture. Serialization risk is low. | Evaluate after core trading/broker-sync paths are handled |

### 9.2 Detailed Analysis of Key Operations

#### `execute_strategy` — SAFE TO RETRY

**Why safe:**
1. Idempotency check at the start (line 363-368): reads `StrategyExecution` by `client_order_id`. If found, returns immediately. This is a read-only operation, no lock.
2. All writes are within one transaction (lines 446-585).
3. The `client_order_id` unique constraint (models.py:134) prevents duplicate executions even if two concurrent transactions both pass the SELECT check.
4. On retry, the idempotency check will find the already-created execution and return it.

**What happens on retry:**
1. T1 starts, passes idempotency check (no existing execution), creates execution E1, commits
2. T1 experiences serialization failure BEFORE commit (e.g., during PaperOrder insert)
3. T1 is retried: creates new session, passes idempotency check (E1 now exists from step 1? No — T1's writes were rolled back, so E1 does not exist)
4. Wait — if T1's writes were rolled back, the retry would create a NEW execution with a new `execution_id`. This is a problem.

**Issue:** If the serialization failure occurs after some writes but before commit, the rollback discards all writes. The retry would create a new execution with a new ID. This is correct for correctness (no duplicate execution), but the `execution_id` would be different from what the caller expected.

**Actually, this is fine.** The caller receives the `ExecutionOut` with the new `execution_id`. The `client_order_id` is the same. The frontend can use `client_order_id` for idempotency, not `execution_id`.

But wait — there's a subtlety. If T1's writes were rolled back, and T2 (a concurrent request with the same `client_order_id`) created the execution, then T1's retry would find T2's execution and return it. This is correct.

If T1 is the ONLY request with that `client_order_id`, the retry creates a new execution. The `execution_id` changes, but the `client_order_id` is the same. This is acceptable.

**Conclusion:** `execute_strategy` is safe to retry. The idempotency layer ensures correctness. The only "cost" is a new `execution_id` if the original transaction's writes were rolled back.

#### `exit_position` — SAFE TO RETRY

**Why safe:**
1. FOR UPDATE on Position row (line 645-647) serializes concurrent exits on the same position.
2. `find_exit_replay()` checks for existing exit order by `client_order_id` (line 651).
3. The `client_order_id` unique constraint on `paper_orders` prevents duplicate exit orders.
4. On retry, `find_exit_replay()` will find the already-created exit order (if the original transaction committed) or the position will be in its pre-transaction state (if the original transaction rolled back).

**What happens on retry:**
1. T1 starts, acquires FOR UPDATE on position P, creates exit order O1, updates position, commits
2. T1 experiences serialization failure BEFORE commit
3. T1 is retried: creates new session, acquires FOR UPDATE on position P (which is now in pre-T1 state, since T1 was rolled back), creates exit order O2 (new `client_order_id`? No — same `client_order_id`), commits

Wait — if T1 used the same `client_order_id`, the unique constraint on `paper_orders` would prevent O2 from being created (O1 was rolled back, so the key is free). Actually, O1 was rolled back, so the key IS free. T1's retry would create O2 with the same `client_order_id` but a different `id` (primary key).

This is fine — the `client_order_id` is the idempotency key, not the `id`. The frontend uses `client_order_id` to check for duplicate exits.

**But wait — what about the position update?** If T1 updated the position (changed `net_quantity`, `realized_pnl`, etc.) and then rolled back, the position is back to its pre-T1 state. T1's retry would re-apply the exit, which is correct.

**What if T2 concurrently exited the same position?** T1's retry would acquire FOR UPDATE on the position, see that it's already closed (or has less quantity), and raise `INSUFFICIENT_POSITION`. This is correct — T1's exit is no longer valid because T2 closed the position.

**Conclusion:** `exit_position` is safe to retry. The FOR UPDATE lock and idempotency layer ensure correctness.

#### `bulk_exit` — SAFE TO RETRY (with caution)

**Why safe:**
1. All exits use `exit_position` with `commit=False`, so each exit is part of the larger bulk transaction.
2. The `client_order_id` on `BulkExitRecord` provides idempotency for the entire bulk operation.
3. Pre-validation (lines 910-930) ensures all positions are open and have market prices before any writes.

**What happens on retry:**
1. T1 starts, pre-validates 10 positions, exits 10 positions (each with `commit=False`), creates `BulkExitRecord`, commits
2. T1 experiences serialization failure BEFORE commit (e.g., during the 5th exit)
3. T1 is retried: creates new session, pre-validates 10 positions again (some may now be closed by concurrent exits), exits the remaining open positions, creates `BulkExitRecord` (same `client_order_id`), commits

**Issue:** If some positions were closed by concurrent exits between T1's rollback and retry, the bulk exit would exit fewer positions. The `BulkExitRecord` would reflect the actual number of exited positions. This is correct — the bulk exit is idempotent but not guaranteed to exit the same number of positions on retry.

**The `BulkExitRecord` stores the result of the bulk exit, including `exited_count`, `failed_count`, etc. On retry, the record is created with the new result. If the original `BulkExitRecord` was rolled back, the retry creates a new one. If the original committed, the retry finds it via `client_order_id` and returns the original result.**

Wait — this depends on when the serialization failure occurs. If it occurs before `BulkExitRecord` is created, the retry creates a new record. If it occurs after `BulkExitRecord` is created but before commit, the record is rolled back, and the retry creates a new one.

**The `_record_bulk_exit` function (lines 1085-1107) creates the `BulkExitRecord` and then calls `db.commit()`. If the commit fails, the record is rolled back.**

**Conclusion:** `bulk_exit` is safe to retry, but the retry may produce a different result (fewer positions exited) if concurrent exits closed some positions. This is acceptable — the bulk exit is idempotent in terms of `client_order_id`, but the result may vary.

**Caution:** The bulk exit transaction is long-running. Under CRDB SERIALIZABLE, long transactions have a higher probability of serialization failures. The retry policy should use a higher `max_attempts` for bulk exits (e.g., 5 instead of 3) and a longer base delay.

#### `ingest_canonical_event` — SAFE TO RETRY

**Why safe:**
1. `BrokerSyncIdempotency.canonical_id` is the primary key — duplicate event processing is prevented at the database level.
2. The `_advance_broker_sequence` OCC pattern uses `UPDATE ... WHERE last_sequence = :expected` — a retry with the same expected value is safe (if the expected value is still current).
3. `append_lifecycle_event` uses `event_id` unique constraint — duplicate lifecycle events are prevented.
4. All operations are within one SAVEPOINT (nested transaction) inside the caller's outer transaction.

**What happens on retry:**
1. T1 starts, processes event E (canonical_id = C1), inserts `BrokerSyncIdempotency` row for C1, inserts `BrokerOrderProjection`, inserts lifecycle event, advances sequence anchor, commits
2. T1 experiences serialization failure BEFORE commit
3. T1 is retried: creates new session, processes event E again
   - `BrokerSyncIdempotency` insert for C1: if T1's row was rolled back, the key is free, and the retry inserts a new row. If T2 (concurrent) inserted a row for C1, the retry's insert fails with unique constraint violation, which is caught by the idempotency layer (returns DUPLICATE_NOOP).
   - `BrokerOrderProjection` insert: if T1's row was rolled back, the retry inserts a new row. The projection is determined by the event content, so the new row has the same content.
   - Lifecycle event insert: if T1's event was rolled back, the retry inserts a new event with the same `event_id`. The unique constraint prevents duplicate `event_id`.
   - Sequence anchor advancement: the retry uses the same `expected` value. If the anchor was advanced by T2 (concurrent), the retry's UPDATE matches 0 rows, and `_advance_broker_sequence` raises `IngestionError(CONFLICT)`. This is correct — the retry detects that another worker advanced the sequence.

**Issue:** The sequence anchor advancement is the tricky part. If T1's retry uses the same `expected` value (the `last_sequence` at the time of T1's original read), and T2 has advanced the anchor, the retry's UPDATE matches 0 rows, and `_advance_broker_sequence` raises `IngestionError(CONFLICT)`.

This is actually CORRECT behavior. The `IngestionError(CONFLICT)` signals that the event was already processed by another worker. The retry should handle this by returning the appropriate result (the event was processed, no need to retry further).

But wait — the retry wrapper at the service level would see `IngestionError(CONFLICT)` as an exception and might retry again. This is wrong — `IngestionError(CONFLICT)` is not a serialization failure; it's a legitimate conflict that should not be retried.

**The retry wrapper must distinguish between:**
1. Serialization failures (SQLSTATE 40001) — retryable
2. `IngestionError(CONFLICT)` — NOT retryable; the event was already processed

**The retry wrapper should catch `OperationalError` (which includes serialization failures) and retry. It should NOT catch `IngestionError` (which includes CONFLICT and other non-retryable errors).**

**Conclusion:** `ingest_canonical_event` is safe to retry for serialization failures. The retry wrapper must be careful to only retry on serialization failures, not on `IngestionError`.

---

## 10. Alembic Compatibility Matrix

### 10.1 Migration-by-Migration Analysis

| Migration | File | CRDB Compatibility | Notes |
|-----------|------|-------------------|-------|
| Baseline schema | `d3eb45a2e046` | 🟢 Likely compatible | Standard CREATE TABLE, ADD COLUMN, CREATE INDEX. No PostgreSQL-specific constructs. Uses standard SQLAlchemy types. |
| Password hash | `a0deb75ad22f` | 🟢 Likely compatible | ADD COLUMN (password_hash). Simple operation. |
| Broker connection foundation | `125e1807df8d` | 🟡 Requires dialect handling | Partial index uses dialect-conditional WHERE (postgresql vs else). Needs `cockroachdb` branch. See Section 6.3. |
| Google sub | `b8c9f1d2e34a` | 🟢 Likely compatible | ADD COLUMN, CREATE INDEX. Simple operations. |
| Trading status backfill | `a1b2c3d4e5f6` | 🟢 Likely compatible | UPDATE statement. Dialect-agnostic. |
| Capability separation | `f7a3c2d1e94b` | 🟢 Likely compatible | ADD COLUMN. Simple operation. |
| GEX provenance | `b2c3d4e5f6a7` | 🟢 Likely compatible | ADD COLUMN. Simple operation. |
| Trade lifecycle tables | `e8f9a0b1c2d3` | 🟢 Likely compatible | CREATE TABLE with standard types, UNIQUE constraints. No PostgreSQL-specific constructs. |
| Broker sync idempotency | `9b675f8a3af0` | 🟢 Likely compatible | CREATE TABLE with standard types, UNIQUE constraints. Uses `String(64)` for primary key, `DateTime(timezone=True)` for timestamps. |
| Merge Day39/Day38 GEX heads | `f7aa24156f6d_merge_day39...` | 🟢 Likely compatible | Merge migration. No DDL. |
| Day38 GEX merge | `merge_day38_gex.py` | 🟢 Likely compatible | Merge migration. No DDL. |
| Day41 fill ledger tables | `b3e5f8a1c7d2` | 🟢 Likely compatible | CREATE TABLE with standard types. Uses `String`, `Integer`, `DateTime(timezone=True)`, `Boolean`. No PostgreSQL-specific constructs. |
| Day41 broker raw observation | `a7c1d9e4f2b8` | 🟢 Likely compatible | CREATE TABLE with standard types. No PostgreSQL-specific constructs. |
| Day41 merge | `f7aa24156f6d` | 🟢 Likely compatible | Merge migration. No DDL. |
| Day39 merge | `a0deb75ad22f` | 🟢 Likely compatible | Merge migration. No DDL. |

### 10.2 Alembic Environment Compatibility

| Aspect | Current | CRDB Compatibility |
|--------|---------|-------------------|
| `alembic/env.py:_render_as_batch()` | `url.startswith("sqlite")` | 🟢 Correct — batch mode is SQLite-only |
| `alembic/env.py:run_migrations_online()` | `url.startswith("sqlite")` for engine creation | 🟢 Correct — CRDB uses standard engine creation |
| `alembic/env.py:context.configure()` | `render_as_batch=connection.dialect.name == "sqlite"` | 🟢 Correct — CRDB dialect name is "cockroachdb", not "sqlite" |
| `alembic.ini` | No hardcoded `sqlalchemy.url` | 🟢 Correct — URL is set dynamically in env.py |

### 10.3 Types Used in Migrations

| Type | Migrations Using It | CRDB Support |
|------|---------------------|-------------|
| `String(N)` | All migrations | ✅ VARCHAR(N) |
| `Integer` | All migrations | ✅ INTEGER |
| `DateTime()` | `125e1807df8d`, `b8c9f1d2e34a`, `9b675f8a3af0` | ✅ TIMESTAMP (without timezone) |
| `DateTime(timezone=True)` | `9b675f8a3af0`, `b3e5f8a1c7d2`, `a7c1d9e4f2b8` | ✅ TIMESTAMP WITH TIME ZONE |
| `Boolean()` | `125e1807df8d` | ✅ BOOLEAN |
| `Text()` | `125e1807df8d`, `b8c9f1d2e34a`, `9b675f8a3af0` | ✅ TEXT |
| `Float` | Not used in migrations (used in models) | ✅ DOUBLE PRECISION |
| `JSON` | Not used (Text used for JSON storage) | ✅ JSON (if needed) |

### 10.4 Constraints Used in Migrations

| Constraint | Migrations Using It | CRDB Support |
|-----------|---------------------|-------------|
| PRIMARY KEY | All table-creation migrations | ✅ |
| FOREIGN KEY | `125e1807df8d` (broker_connections.user_id → users.id, broker_tokens.connection_id → broker_connections.id) | ✅ |
| UNIQUE | `125e1807df8d` (uq_broker_connection, uq_broker_token_per_session), `9b675f8a3af0` (uq_broker_sync_idempotency_canonical_id) | ✅ |
| Partial UNIQUE | `125e1807df8d` (uq_one_default_per_user_broker WHERE is_default = true) | 🟡 Requires `cockroachdb` branch (see Section 6.3) |

### 10.5 Summary

**Only one migration requires modification:** `125e1807df8d` (partial index dialect branching).

**All other migrations are likely compatible with CockroachDB.** They use standard SQLAlchemy types and constructs that CRDB supports.

**Alembic environment is compatible.** The env.py correctly handles CRDB as a non-SQLite dialect.

**REQUIRES LIVE CRDB VERIFICATION:** Run `alembic upgrade head` against a fresh CRDB instance and verify all migrations apply without error and the resulting schema matches the expected PostgreSQL schema.

---

## 11. Test Plan

### 11.1 Dialect Tests

#### Test 1: `dialect_insert` with CRDB engine

```
Purpose: Verify that dialect_insert returns a PostgreSQL insert construct for CRDB dialect
Setup: Create a mock engine with dialect.name = "cockroachdb"
Assertion: Returned object is an instance of postgresql.insert
          Returned object supports .on_conflict_do_update()
          Returned object supports .on_conflict_do_nothing()
          Returned object supports .returning()
File: tests/test_db_dialect.py (new)
```

#### Test 2: SQL compilation for CRDB insert

```
Purpose: Verify that the SQL generated by dialect_insert for CRDB is correct
Setup: Use sqlalchemy-cockroachdb dialect to compile an insert with ON CONFLICT
Assertion: Compiled SQL contains "ON CONFLICT" clause
          Compiled SQL contains "RETURNING" clause (if .returning() was called)
          Compiled SQL is valid CRDB SQL (no SQLite-specific syntax)
File: tests/test_db_dialect.py (new)
```

#### Test 3: `_upsert_trade_fill` with CRDB bind

```
Purpose: Verify that _upsert_trade_fill uses PostgreSQL insert for CRDB dialect
Setup: Create a mock Session with bind.dialect.name = "cockroachdb"
Assertion: The insert construct uses pg_insert (not sqlite_insert)
          The generated SQL compiles correctly for CRDB
File: tests/test_fill_ledger.py (extend existing)
```

### 11.2 Fill-Ledger Tests

#### Test 4: Insert fill on CRDB

```
Purpose: Verify that a new fill row is created correctly on CRDB
Setup: CRDB database with broker_fill_ledger_fill table
Action: Call _upsert_trade_fill with new (tenant_id, provider_order_id, fill_eq_key)
Assertion: Row is created with correct values
          Function returns the created row
File: tests/test_fill_ledger_crdb.py (new)
```

#### Test 5: Duplicate fill on CRDB

```
Purpose: Verify that a duplicate fill returns None (ON CONFLICT DO NOTHING)
Setup: CRDB database with existing fill row
Action: Call _upsert_trade_fill with same (tenant_id, provider_order_id, fill_eq_key)
Assertion: Function returns None
          No new row is created
          Existing row is unchanged
File: tests/test_fill_ledger_crdb.py (new)
```

#### Test 6: Concurrent fill on CRDB

```
Purpose: Verify that concurrent fills produce exactly one APPLIED and one DUPLICATE_FILL/CONFLICT
Setup: CRDB database, two concurrent transactions
Action: Both transactions call _upsert_trade_fill with same key simultaneously
Assertion: Exactly one transaction gets APPLIED (created row)
          The other gets DUPLICATE_FILL or CONFLICT
          No duplicate fill rows exist
File: tests/test_fill_ledger_concurrency_crdb.py (new)
```

#### Test 7: Idempotent fill on CRDB

```
Purpose: Verify that retrying a fill operation is idempotent
Setup: CRDB database
Action: Call apply_lane_b_fill, then call it again with same parameters
Assertion: First call: APPLIED
          Second call: DUPLICATE_FILL (same fingerprint) or CONFLICT (different fingerprint)
          Exactly one fill row exists
File: tests/test_fill_ledger_idempotency_crdb.py (new)
```

### 11.3 Lifecycle Tests

#### Test 8: Append lifecycle event on CRDB

```
Purpose: Verify that append_lifecycle_event works on CRDB
Setup: CRDB database with trade_lifecycle_events table
Action: Call append_lifecycle_event with new event
Assertion: Event is created with correct event_id
          All fields are persisted correctly
File: tests/test_lifecycle_crdb.py (new)
```

#### Test 9: Duplicate lifecycle event on CRDB

```
Purpose: Verify idempotent handling of duplicate lifecycle events
Setup: CRDB database with existing lifecycle event
Action: Call append_lifecycle_event with same event_id and same content
Assertion: Function returns existing event (idempotent)
          No new row is created
File: tests/test_lifecycle_idempotency_crdb.py (new)
```

#### Test 10: Conflicting lifecycle event on CRDB

```
Purpose: Verify that conflicting events raise IntegrityError
Setup: CRDB database with existing lifecycle event
Action: Call append_lifecycle_event with same event_id but different content
Assertion: IntegrityError is raised
          No new row is created
File: tests/test_lifecycle_conflict_crdb.py (new)
```

#### Test 11: SAVEPOINT behavior on CRDB

```
Purpose: REQUIRES LIVE CRDB VERIFICATION — determine if SAVEPOINT survives serialization failure
Setup: CRDB database, two concurrent transactions
Action: T1: begin_nested (SAVEPOINT), insert lifecycle event, flush
         T2: insert conflicting event, commit
         T1: flush (should get serialization failure or IntegrityError)
Assertion: Determine if T1's outer transaction is still valid after the failure
           Determine if T1 can continue using the session after the SAVEPOINT rollback
File: tests/test_lifecycle_savepoint_crdb.py (new)
```

### 11.4 Position Tests

#### Test 12: Concurrent exit on CRDB

```
Purpose: Verify that concurrent exits on the same position are serialized correctly
Setup: CRDB database with open position
Action: T1: exit_position on position P
         T2: exit_position on position P (concurrent)
Assertion: One exit succeeds, the other gets INSUFFICIENT_POSITION (or waits and then fails)
           Position net_quantity is correctly updated
           Exactly one exit order is created per successful exit
           No double-close occurs
File: tests/test_position_concurrency_crdb.py (new)
```

#### Test 13: Position locking on CRDB

```
Purpose: Verify FOR UPDATE locking behavior on CRDB
Setup: CRDB database with open position
Action: T1: SELECT ... FOR UPDATE on position P (hold lock)
         T2: SELECT ... FOR UPDATE on position P (should block)
         T1: commit
         T2: should now acquire lock
Assertion: T2 blocks until T1 commits
           T2 sees the updated position state after T1's commit
File: tests/test_position_locking_crdb.py (new)
```

#### Test 14: Cash integrity on CRDB

```
Purpose: Verify that cash ledger is consistent after exits on CRDB
Setup: CRDB database with account and position
Action: Execute entry, then exit position
Assertion: SUM(PaperTransaction.amount) + starting_capital = available cash
           No cash duplication or loss
File: tests/test_cash_integrity_crdb.py (new)
```

#### Test 15: Realized P&L integrity on CRDB

```
Purpose: Verify that realized P&L is correctly calculated on CRDB
Setup: CRDB database with position
Action: Exit position partially, then fully
Assertion: Realized P&L matches expected value (calculated independently)
           No P&L distortion from CRDB behavior
File: tests/test_pnl_integrity_crdb.py (new)
```

### 11.5 Broker-Sync Tests

#### Test 16: Sequence advancement on CRDB

```
Purpose: Verify that broker sequence advancement works on CRDB
Setup: CRDB database with broker_sync_sequence_anchor table
Action: Call _advance_broker_sequence with new sequence
Assertion: last_sequence is updated correctly
          Subsequent calls with stale sequence fail with IngestionError
File: tests/test_broker_sequence_crdb.py (new)
```

#### Test 17: Duplicate event on CRDB

```
Purpose: Verify idempotent handling of duplicate broker events
Setup: CRDB database with broker_sync_idempotency table
Action: Call ingest_canonical_event with event E, then call again with same event
Assertion: First call: event processed
          Second call: DUPLICATE_NOOP (idempotent)
          No duplicate projection or lifecycle events
File: tests/test_broker_idempotency_crdb.py (new)
```

#### Test 18: Concurrent event on CRDB

```
Purpose: Verify that concurrent event processing is safe on CRDB
Setup: CRDB database
Action: T1 and T2 call ingest_canonical_event with different events for same order concurrently
Assertion: Both events are processed (if they are different canonical_ids)
           Sequence anchor is advanced correctly
           No events are lost
File: tests/test_broker_concurrency_crdb.py (new)
```

#### Test 19: Serialization conflict on CRDB

```
Purpose: REQUIRES LIVE CRDB VERIFICATION — verify serialization failure behavior
Setup: CRDB database, two concurrent ingest_canonical_event calls for same order
Action: T1 and T2 process events for same order concurrently, causing serialization conflict
Assertion: One transaction succeeds, the other gets serialization failure
           The failing transaction can be retried (if retry wrapper is in place)
           No events are lost or duplicated
File: tests/test_broker_serialization_crdb.py (new)
```

#### Test 20: Retry on CRDB

```
Purpose: REQUIRES LIVE CRDB VERIFICATION — verify retry mechanism works
Setup: CRDB database with retry wrapper implemented
Action: Cause serialization failure, verify retry succeeds
Assertion: Retry attempt 1: serialization failure, retry
          Retry attempt 2: success (or another failure, retry again)
          Final result: event processed correctly
          No duplicate events or fills
File: tests/test_broker_retry_crdb.py (new)
```

#### Test 21: Failed retry exhaustion on CRDB

```
Purpose: Verify that retry exhaustion fails gracefully
Setup: CRDB database with retry wrapper (max_attempts=3)
Action: Cause persistent serialization failure (e.g., long-running blocking transaction)
Assertion: After 3 attempts, the operation fails with the original error
           No partial state is left (transaction rolled back)
           Error is propagated to caller
File: tests/test_broker_retry_exhaustion_crdb.py (new)
```

### 11.6 Migration Tests

#### Test 22: Fresh CRDB alembic upgrade

```
Purpose: Verify that Alembic migrations apply cleanly to CRDB
Setup: Fresh CRDB database (no tables)
Action: Run alembic upgrade head
Assertion: All 15 migrations apply without error
          alembic_version table contains the head revision
          All expected tables exist
File: tests/test_migration_crdb.py (new)
```

#### Test 23: CRDB schema comparison

```
Purpose: Verify that CRDB schema matches PostgreSQL schema
Setup: Fresh CRDB database after alembic upgrade head
         Fresh PostgreSQL database after alembic upgrade head
Action: Compare table lists, column lists, constraint lists, index lists
Assertion: Same tables exist on both databases
           Same columns (name, type, nullable) on both databases
           Same constraints (PK, FK, UNIQUE) on both databases
           Same indexes on both databases
           Partial index uq_one_default_per_user_broker exists on both
File: tests/test_schema_comparison.py (new)
```

### 11.7 Economic Correctness Tests

These tests verify that the migration does not alter economic behavior. They should run against both PostgreSQL and CockroachDB and produce identical results.

#### Test 24: Position quantity integrity

```
Purpose: Verify that position quantities are not lost or duplicated
Setup: CRDB database
Action: Execute strategy (entry), exit position partially, exit position fully
Assertion: Position net_quantity starts at entry quantity
           After partial exit: net_quantity = entry - partial_exit
           After full exit: net_quantity = 0
           No negative quantities (unless short position)
File: tests/test_economic_position_quantity.py (extend existing)
```

#### Test 25: Average price integrity

```
Purpose: Verify that average entry price is correctly calculated
Setup: CRDB database
Action: Execute strategy with multiple legs at different prices
Assertion: Average entry price = weighted average of fill prices
           No price distortion from CRDB behavior
File: tests/test_economic_average_price.py (extend existing)
```

#### Test 26: Realized P&L integrity

```
Purpose: Verify that realized P&L is correct
Setup: CRDB database
Action: Enter position, exit at different price
Assertion: Realized P&L = (exit_price - entry_price) * quantity * lot_size (for long)
           Matches independent calculation
File: tests/test_economic_pnl.py (extend existing)
```

#### Test 27: Cash integrity

```
Purpose: Verify that cash is not duplicated or lost
Setup: CRDB database
Action: Execute multiple strategies, exit positions
Assertion: SUM(PaperTransaction.amount) + starting_capital = available cash
           Cash changes match expected values
File: tests/test_economic_cash.py (extend existing)
```

#### Test 28: Order count integrity

```
Purpose: Verify that order counts are correct
Setup: CRDB database
Action: Execute strategy with N legs
Assertion: N PaperOrder rows created
           N Leg rows created (legacy journal)
           No duplicate orders
File: tests/test_economic_order_count.py (extend existing)
```

#### Test 29: Fill count integrity

```
Purpose: Verify that fill counts are correct
Setup: CRDB database
Action: Process broker fill events
Assertion: Fill count matches number of fill events processed
           No duplicate fills
File: tests/test_economic_fill_count.py (extend existing)
```

#### Test 30: Lifecycle event count integrity

```
Purpose: Verify that lifecycle event counts are correct
Setup: CRDB database
Action: Process broker events that map to lifecycle events
Assertion: Lifecycle event count matches expected number
           No duplicate lifecycle events
File: tests/test_economic_lifecycle_count.py (extend existing)
```

---

## 12. Live CRDB Validation Matrix

Because the previous experiment could not obtain a live CRDB instance, the following tests MUST be run against a real CockroachDB database before production migration approval.

| Test | PostgreSQL | CockroachDB | Expected | Command/Test Required |
|------|-----------|-------------|----------|----------------------|
| Alembic upgrade | Required | Required | Identical schema | `alembic upgrade head` against fresh CRDB; compare with PostgreSQL schema |
| Partial index | Required | Required | Equivalent enforcement | Create `broker_connections` with two default connections for same (user, broker); verify second INSERT fails on both databases |
| ON CONFLICT DO NOTHING RETURNING | Required | Required | Equivalent row-return behavior | Insert a row with unique key, then insert duplicate with RETURNING; verify first returns row, second returns zero rows on both databases |
| ON CONFLICT DO UPDATE RETURNING | Required | Required | Equivalent update behavior | Insert a row, then insert duplicate with DO UPDATE; verify row is updated and RETURNING returns new values on both databases |
| FOR UPDATE | Required | Required | Expected locking behavior | T1: SELECT FOR UPDATE (hold), T2: SELECT FOR UPDATE (block), T1: commit, T2: proceed. Verify T2 blocks on both databases. |
| SKIP LOCKED | Required | Required | Expected skip behavior | T1: SELECT FOR UPDATE (hold), T2: SELECT FOR UPDATE SKIP LOCKED (should skip locked row). Verify on both databases. |
| BYTEA | Required | Required | Equivalent storage/retrieval | Insert binary data, retrieve, compare. Verify round-trip equality on both databases. |
| JSON | Required | Required | Equivalent storage/retrieval | Insert JSON data, retrieve, compare. Verify on both databases. |
| Concurrent lifecycle append | Required | Required | No duplicates | Two concurrent append_lifecycle_event calls with same event_id; verify only one succeeds on both databases. |
| Concurrent exit | Required | Required | Economic integrity | Two concurrent exit_position calls on same position; verify one succeeds, one fails, position is correct on both databases. |
| Broker sequence contention | Required | Required | Successful retry | Two concurrent _advance_broker_sequence calls; verify one succeeds, one gets CONFLICT, retry succeeds on CRDB. |
| Ingestion contention | Required | Required | No lost events | Two concurrent ingest_canonical_event calls for different events on same order; verify both succeed on both databases. |
| Fill-ledger contention | Required | Required | Idempotent | Two concurrent apply_lane_b_fill calls for same fill; verify one APPLIED, one DUPLICATE_FILL on both databases. |
| Serialization failure detection | Required | Required | Correct exception type | Cause serialization failure; verify exception type, SQLSTATE, and that it's catchable on CRDB. |
| SAVEPOINT survival | Required | Required | Outer transaction valid/invalid | Cause serialization failure inside SAVEPOINT; verify whether outer transaction is still usable on CRDB. |
| Transaction retry | Required | Required | Successful retry | Implement retry wrapper, cause serialization failure, verify retry succeeds on CRDB. |
| Bulk exit atomicity | Required | Required | All-or-nothing | Cause failure during bulk_exit; verify all writes rolled back on both databases. |
| GEX capture loop | Required | Optional | No errors | Run GEX capture loop against CRDB; verify no database errors (low priority). |

---

## 13. Northflank Implications

### 13.1 Application Changes Required for Northflank

The application changes for CockroachDB compatibility (dialect branching, retry handling) are independent of Northflank. They are required for any CockroachDB deployment, including Northflank.

### 13.2 Northflank-Specific Configuration

| Aspect | Current (Railway) | Northflank Target | Change Required |
|--------|------------------|-------------------|-----------------|
| DATABASE_URL | `postgresql+psycopg://...` (Railway PostgreSQL) | `cockroachdb+psycopg://...` (Northflank CockroachDB) | Yes — change DATABASE_URL format |
| SSL | Railway manages SSL | CockroachDB Cloud requires SSL | Yes — ensure `sslmode=verify-full` or `sslmode=verify-ca` in URL |
| Health check | Railway health checks | Northflank health checks | Evaluate — Northflank may require a health endpoint |
| Environment variables | RAILWAY_ENVIRONMENT, RAILWAY_SERVICE_NAME | Northflank equivalents | Yes — `IS_PRODUCTION` detection in config.py may need updating |
| Secrets | Railway secrets | Northflank secrets | Yes — migrate secrets to Northflank |
| Connection pool | Pool size 5, overflow 10 | Same or adjusted | Evaluate — Northflank resource sizing may affect pool settings |

### 13.3 config.py IS_PRODUCTION Detection

Current code (config.py:77-89):

```python
@property
def IS_PRODUCTION(self) -> bool:
    import os as _os
    return bool(
        _os.environ.get("RAILWAY_ENVIRONMENT")
        or _os.environ.get("RAILWAY_SERVICE_NAME")
        or _os.environ.get("PRODUCTION")
    )
```

**Issue:** This detects Railway production via `RAILWAY_ENVIRONMENT` and `RAILWAY_SERVICE_NAME`. On Northflank, these variables are not set. The `PRODUCTION` variable may or may not be set depending on Northflank configuration.

**Recommended change:** Add Northflank detection:

```python
@property
def IS_PRODUCTION(self) -> bool:
    import os as _os
    return bool(
        _os.environ.get("RAILWAY_ENVIRONMENT")
        or _os.environ.get("RAILWAY_SERVICE_NAME")
        or _os.environ.get("NORTHFLANK_ENVIRONMENT")
        or _os.environ.get("PRODUCTION")
    )
```

**Wait — is this needed for the compatibility fix?**

No. The `IS_PRODUCTION` detection is used to enforce that production uses PostgreSQL (not SQLite). On Northflank with CockroachDB, the `DATABASE_URL` would be set to a `cockroachdb+psycopg://` URL, which is not SQLite. The `validate_production_config()` check would pass.

However, the warning message says "Set DATABASE_URL to a PostgreSQL connection string" — this would be misleading on CockroachDB. The message could be updated to say "Set DATABASE_URL to a PostgreSQL or CockroachDB connection string."

**This is a minor documentation change, not a critical compatibility issue.**

### 13.4 Health Checks

The current application does not have an explicit health endpoint that Northflank can probe. Northflank typically uses HTTP health checks (e.g., GET /health).

**Recommended:** Add a `/health` endpoint that returns 200 OK when the application is healthy (database accessible, migrations applied). This is a separate concern from CockroachDB compatibility.

### 13.5 Worker/Background Task Configuration

The broker-sync ingestion and GEX capture loop are background tasks that run within the FastAPI application (via lifespan handler). On Northflank, these would continue to run in the same process.

**If Northflank uses a separate worker service:** The worker would need to run the broker-sync ingestion task. This would require:
1. A separate entry point for the worker
2. The worker's own DATABASE_URL configuration
3. The worker's own retry handling (since it owns the session for ingestion)

**This is a deployment architecture decision, not a compatibility issue.**

### 13.6 Summary

Northflank deployment requires:
1. DATABASE_URL set to `cockroachdb+psycopg://...` with SSL
2. Environment variable changes for production detection (optional)
3. Health endpoint (recommended)
4. Secrets migration
5. Connection pool evaluation

None of these affect the CockroachDB compatibility fix design. They are separate deployment concerns.

---

## 14. Implementation Sequence

The recommended implementation order, based on the evidence gathered:

### Phase 1: Dialect Fixes (Low Risk, High Impact)

**Step 1: Fix `db_dialect.py:dialect_insert()`**
- Change `if dialect_name == "postgresql":` to `if dialect_name in ("postgresql", "cockroachdb"):`
- Add test: `dialect_insert` with CRDB engine returns PostgreSQL insert construct
- Add test: SQL compilation for CRDB insert produces correct SQL

**Step 2: Fix `fill_ledger.py:_upsert_trade_fill()`**
- Change `if bind.dialect.name == "postgresql":` to `if bind.dialect.name in ("postgresql", "cockroachdb"):`
- Add test: `_upsert_trade_fill` with CRDB bind uses PostgreSQL insert
- Add test: SQL compilation for CRDB fill insert produces correct SQL

**Step 3: Fix migration `125e1807df8d`**
- Change `if dialect == "postgresql":` to `if dialect in ("postgresql", "cockroachdb"):`
- Add test: migration creates partial index with correct WHERE clause on CRDB

**Verification:** Run existing PostgreSQL test suite to ensure no regressions. Run SQLite tests to ensure no regressions.

### Phase 2: Retry Architecture (Medium Risk, High Impact)

**Step 4: Determine exact exception type for CRDB serialization failures**
- This REQUIRES LIVE CRDB VERIFICATION
- Run experiment: cause serialization failure, capture exception type, SQLSTATE, and whether SQLAlchemy wraps it

**Step 5: Implement serialization failure detection**

```python
def is_serialization_failure(exc: Exception) -> bool:
    """Detect CockroachDB serialization failure from SQLAlchemy exception."""
    from sqlalchemy.exc import OperationalError
    if isinstance(exc, OperationalError):
        if hasattr(exc, 'orig') and hasattr(exc.orig, 'sqlstate'):
            return exc.orig.sqlstate == '40001'
    return False
```

**Step 6: Implement retry wrapper at service/router layer**

```python
def retry_on_serialization(max_attempts=3, base_delay=0.1):
    """Decorator/wrapper for CRDB serialization retry."""
    def wrapper(operation):
        def wrapped(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                db = SessionLocal()  # New session per attempt
                try:
                    result = operation(db, *args, **kwargs)
                    db.commit()
                    return result
                except OperationalError as e:
                    db.rollback()
                    if is_serialization_failure(e):
                        last_error = e
                        if attempt < max_attempts - 1:
                            time.sleep(base_delay * (2 ** attempt))
                            continue
                    raise
                finally:
                    db.close()
            raise last_error
        return wrapped
    return wrapper
```

**Step 7: Apply retry to high-priority operations**

Apply retry wrapper to:
1. `bulk_exit` (highest priority — long transaction)
2. `ingest_canonical_event` (via broker-sync task layer)
3. `execute_strategy` (medium priority)
4. `exit_position` (medium priority)

**Step 8: Add retry configuration to config.py**

```python
CRDB_RETRY_MAX_ATTEMPTS: int = 3
CRDB_RETRY_BASE_DELAY_SECONDS: float = 0.1
```

### Phase 3: Testing (Medium Risk, High Impact)

**Step 9: Add unit tests for dialect fixes**
- Test `dialect_insert` with CRDB dialect
- Test `_upsert_trade_fill` with CRDB bind
- Test migration partial index with CRDB dialect

**Step 10: Add unit tests for retry handling**
- Test retry wrapper catches serialization failures
- Test retry wrapper does NOT catch non-serialization errors
- Test retry wrapper exhausts after max_attempts
- Test retry wrapper creates new session per attempt

**Step 11: Add concurrency tests**
- Test concurrent fills on CRDB (APPLIED + DUPLICATE_FILL)
- Test concurrent lifecycle events on CRDB (idempotent)
- Test concurrent exits on CRDB (serialized)

### Phase 4: Live CRDB Validation (High Risk, High Impact)

**Step 12: Obtain disposable CockroachDB instance**

This is the blocking step. Options:
1. CockroachDB Cloud free tier (if network access becomes available)
2. Local CockroachDB via Docker (if Docker becomes available)
3. CI/CD pipeline with CRDB service (if GitHub Actions supports it)

**Step 13: Run Alembic migrations against CRDB**

```
cd options-dashboard-project/backend
DATABASE_URL="cockroachdb+psycopg://user:pass@host:26257/testdb?sslmode=verify-full" alembic upgrade head
```

Verify:
- All migrations apply without error
- Schema matches PostgreSQL schema

**Step 14: Run full test suite against CRDB**

```
DATABASE_URL="cockroachdb+psycopg://..." pytest backend/tests/
```

Verify:
- All existing tests pass on CRDB
- New CRDB-specific tests pass

**Step 15: Run concurrency tests against CRDB**

Focus on:
- Concurrent fills (APPLIED + DUPLICATE_FILL)
- Concurrent lifecycle events (idempotent)
- Concurrent exits (serialized)
- Broker sequence contention (retry)
- Ingestion contention (no lost events)

**Step 16: Fix any runtime-specific issues**

Based on live CRDB testing results:
- Adjust retry policy if needed
- Fix any SAVEPOINT behavior issues
- Fix any unexpected CRDB behavior

### Phase 5: Deployment Preparation (Low Risk)

**Step 17: Northflank staging setup**

- Create Northflank project
- Configure DATABASE_URL for CockroachDB
- Configure secrets
- Set up health endpoint
- Deploy to staging

**Step 18: Full staging regression**

- Run full test suite against staging CRDB
- Run API integration tests
- Run broker-sync end-to-end tests
- Run economic correctness tests

**Step 19: Migration decision**

After all validation passes, re-evaluate the migration decision:
- GO WITH CHANGES (if all tests pass and no issues found)
- HOLD (if issues found that require further investigation)

---

## 15. Risk Register

### 15.1 Blocking Issues

| Risk | Description | Mitigation |
|------|-------------|------------|
| No live CRDB instance available | Cannot validate retry behavior, SAVEPOINT survival, or actual CRDB runtime behavior | Obtain disposable CRDB instance (Cloud free tier, Docker, or CI) before implementation Phase 4 |
| Network restrictions | Cannot access CockroachDB Cloud for free tier signup | Explore alternative provisioning methods (Docker, self-hosted, CI service) |

### 15.2 High-Risk Issues

| Risk | Description | Mitigation |
|------|-------------|------------|
| SAVEPOINT behavior on CRDB unknown | `append_lifecycle_event` uses SAVEPOINT for IntegrityError handling; CRDB may abort outer transaction on serialization failure inside SAVEPOINT | Live CRDB test required; if outer transaction is aborted, the retry architecture must be at a higher level (service layer) |
| Bulk exit transaction too long | `bulk_exit` touches many positions, orders, transactions, legs; under CRDB SERIALIZABLE, long transactions have higher serialization failure probability | Implement retry for bulk_exit; consider breaking into smaller transactions if serialization failures are frequent |
| Retry storm risk | Multiple clients retrying simultaneously after serialization failures could create a storm | Use exponential backoff with jitter; limit max_attempts; consider client-side rate limiting |
| Retry non-idempotent operations | If any operation performs external side effects before commit, retry could duplicate them | Audit all operations for external side effects; ensure none exist within transaction boundaries |

### 15.3 Medium-Risk Issues

| Risk | Description | Mitigation |
|------|-------------|------------|
| Exception type detection fragile | `is_serialization_failure` relies on `exc.orig.sqlstate == '40001'`; if psycopg version changes or SQLAlchemy wraps differently, detection may fail | Test against actual CRDB + psycopg combination; add fallback detection (e.g., check error message for "serialization" or "retry") |
| Migration `125e1807df8d` partial index | If the `cockroachdb` branch is not added, the migration creates the index with `WHERE is_default = 1`, which may not work correctly on CRDB's Boolean column | Add `cockroachdb` branch before running migration against CRDB |
| config.py IS_PRODUCTION detection | Northflank may not set RAILWAY_* variables; production detection may fail | Add Northflank environment variable detection; or use explicit `PRODUCTION=true` variable |
| Connection pool settings | pool_size=5, max_overflow=10 may not be optimal for CRDB | Evaluate based on Northflank resource sizing and expected concurrency; adjust if needed |

### 15.4 Low-Risk Issues

| Risk | Description | Mitigation |
|------|-------------|------------|
| Health endpoint missing | Northflank may require a health endpoint for load balancing | Add `/health` endpoint (separate from compatibility fix) |
| Documentation updates | Warning messages refer to "PostgreSQL" but CRDB is also valid | Update messages to say "PostgreSQL or CockroachDB" |
| URL normalization | `normalize_database_url` doesn't handle `cockroachdb://` scheme | Add `cockroachdb://` handling |

---

## 16. Explicit Unresolved Questions

### REQUIRES LIVE CRDB VERIFICATION

1. **What is the exact SQLAlchemy exception type for CRDB serialization failures?**
   - Expected: `sqlalchemy.exc.OperationalError` with `orig` being `psycopg.errors.SerializationFailure`
   - Needs verification: Run experiment against live CRDB, capture actual exception

2. **Does SAVEPOINT survive CRDB serialization failures?**
   - Question: If a serialization failure occurs inside a `begin_nested()` SAVEPOINT, is the outer transaction still valid?
   - Expected: On PostgreSQL, the SAVEPOINT is rolled back but the outer transaction is intact. On CRDB, the outer transaction MAY be aborted.
   - Needs verification: Run experiment with two concurrent transactions, one inside a SAVEPOINT, cause serialization conflict, check outer transaction state.

3. **Does `ON CONFLICT DO NOTHING RETURNING` return rows correctly under CRDB concurrency?**
   - Question: Under concurrent INSERTs with the same unique key, does CRDB correctly return a row to exactly one transaction?
   - Expected: Yes — CRDB supports ON CONFLICT with RETURNING.
   - Needs verification: Run concurrent insert experiment, verify exactly one transaction gets a returned row.

4. **Does the partial index `WHERE is_default = true` work on CRDB?**
   - Question: Does CRDB enforce the partial unique index correctly?
   - Expected: Yes — CRDB supports partial indexes with boolean WHERE clauses.
   - Needs verification: Create the index on CRDB, attempt to insert two default connections for same (user, broker), verify second insert fails.

5. **Does `pool_pre_ping` work correctly with CRDB?**
   - Question: Does `pool_pre_ping` correctly detect stale connections to CRDB?
   - Expected: Yes — `pool_pre_ping` runs a simple SELECT 1 before each connection checkout.
   - Needs verification: Simulate CRDB connection drop, verify `pool_pre_ping` detects it and creates a new connection.

6. **What is the optimal connection pool configuration for CRDB on Northflank?**
   - Question: Should pool_size, max_overflow, pool_recycle be adjusted for CRDB?
   - Expected: Current settings (5, 10, 1800) are reasonable starting points.
   - Needs verification: Monitor connection usage under load on Northflank staging.

7. **Does the `sqlalchemy-cockroachdb` `run_transaction` helper provide benefits over custom retry?**
   - Question: The `sqlalchemy-cockroachdb` package provides `run_transaction()` which handles serialization retry automatically. Should StrikeNova use this instead of custom retry?
   - Expected: Custom retry gives more control and integrates better with StrikeNova's existing transaction model. `run_transaction` would require restructuring.
   - Needs evaluation: Compare custom retry vs `run_transaction` for StrikeNova's use cases.

---

## 17. Definition of Done for Implementation Phase

The implementation phase is complete when:

### Code Changes
- [ ] `db_dialect.py:dialect_insert()` recognizes `"cockroachdb"` dialect
- [ ] `fill_ledger.py:_upsert_trade_fill()` recognizes `"cockroachdb"` dialect
- [ ] Migration `125e1807df8d` recognizes `"cockroachdb"` dialect
- [ ] `db.py:normalize_database_url()` handles `cockroachdb://` scheme (optional, for clarity)
- [ ] Serialization failure detection function implemented and tested
- [ ] Retry wrapper implemented and applied to `bulk_exit`, `ingest_canonical_event`, `execute_strategy`, `exit_position`
- [ ] Retry configuration added to `config.py`

### Tests
- [ ] Unit test for `dialect_insert` with CRDB dialect
- [ ] Unit test for `_upsert_trade_fill` with CRDB bind
- [ ] Unit test for migration partial index with CRDB dialect
- [ ] Unit test for serialization failure detection
- [ ] Unit test for retry wrapper (catches serialization, doesn't catch other errors, exhausts after max_attempts)
- [ ] Unit test for concurrent fills on CRDB (requires live CRDB or mocked concurrency)
- [ ] Unit test for concurrent lifecycle events on CRDB
- [ ] Unit test for concurrent exits on CRDB
- [ ] All existing PostgreSQL tests pass (no regressions)
- [ ] All existing SQLite tests pass (no regressions)

### Live CRDB Validation
- [ ] Disposable CRDB instance obtained
- [ ] `alembic upgrade head` runs successfully against CRDB
- [ ] Schema matches PostgreSQL schema
- [ ] All existing tests pass against CRDB
- [ ] Concurrency tests pass against CRDB
- [ ] Serialization failure experiment completed (exception type confirmed)
- [ ] SAVEPOINT survival experiment completed (outer transaction behavior confirmed)
- [ ] Retry mechanism verified against live CRDB

### Documentation
- [ ] This design report is updated with findings from live CRDB validation
- [ ] Migration audit is updated with implementation status
- [ ] Northflank staging plan is documented (separate from compatibility fix)

---

## 18. Final Implementation-Design Decision

### IMPLEMENTATION DESIGN STATUS: READY

The design is sufficiently understood to begin implementation. The three compatibility gaps have been analyzed in detail, and the recommended fixes are clear:

1. **Gap A (db_dialect.py):** Add `"cockroachdb"` to the PostgreSQL group in `dialect_insert()`. Trivial one-line change.

2. **Gap B (fill_ledger.py):** Add `"cockroachdb"` to the PostgreSQL group in `_upsert_trade_fill()`. Trivial one-line change.

3. **Gap C (ingestion.py):** Implement transaction-level retry for serialization failures at the service/task layer. This is the most complex change, but the design is clear: catch `OperationalError` with SQLSTATE 40001, roll back, create new session, retry with exponential backoff.

### Critical Blockers

- **No live CRDB instance available.** The implementation Phase 4 (live CRDB validation) cannot proceed without a disposable CRDB instance. This blocks final validation but does not block the initial implementation phases (dialect fixes, retry architecture design).

- **SAVEPOINT behavior on CRDB unknown.** The `append_lifecycle_event` SAVEPOINT pattern may or may not survive CRDB serialization failures. This needs live verification before the retry architecture can be finalized for lifecycle event operations.

### Most Important Unresolved Live-CRDB Validations

1. **Exact exception type for CRDB serialization failures** — determines how to detect retryable errors
2. **SAVEPOINT survival under CRDB serialization failures** — determines the retry boundary for lifecycle event operations
3. **ON CONFLICT DO NOTHING RETURNING behavior under CRDB concurrency** — confirms the fill-ledger arbitration works correctly
4. **Partial index enforcement on CRDB** — confirms the broker connection default constraint works
5. **Alembic migration success on CRDB** — confirms the schema can be created

### Next Steps

1. **Implement Phase 1 (dialect fixes)** — can proceed without live CRDB. These are low-risk, high-impact changes.
2. **Implement Phase 2 (retry architecture)** — can proceed with the current design, but the exception detection function should be marked as requiring live CRDB verification.
3. **Obtain disposable CRDB instance** — this is the critical path for Phase 4 validation.
4. **Run live CRDB validation** — verify all assumptions and fix any runtime-specific issues.
5. **Re-evaluate migration decision** — after live CRDB validation passes, decide GO WITH CHANGES vs HOLD.

---

## 19. Verification

```
Application source modified: NO
Tests modified: NO
Migrations modified: NO
Configuration modified: NO
Dependencies modified: NO
Deployment performed: NO
Railway modified: NO
Vercel modified: NO
Northflank modified: NO
Production database modified: NO
Secrets exposed: NO
```

This design report is the only artifact created. No implementation has been performed.

---

*End of design report.*
