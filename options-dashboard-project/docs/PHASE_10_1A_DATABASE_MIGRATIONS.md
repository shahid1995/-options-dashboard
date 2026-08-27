# Phase 10.1A — Database Migration Foundation

_Last updated: 2026-08-27_

## Status

**CONDITIONALLY APPROVED — Architecture hardening pass complete**

## 1. Problem

Phase 10.1 (identity foundation) introduced `User` and `UserSession` tables via a
runtime `ensure_identity_schema()` function called on every authentication request
(`/callback`, `/me`, `/logout`). This pattern:

1. **Executes DDL on every request path** — a performance and reliability risk
2. **Has no version tracking** — no way to know which schema version a database is at
3. **Cannot handle schema evolution** — no mechanism for column additions, renames, or data migrations
4. **Inconsistent with future plans** — the project needs proper schema management for growth

The existing `init_db()` / `create_all()` / `ensure_column()` pattern was also
reaching its limits — it creates tables on startup but cannot alter existing ones.

## 2. Solution

Establish Alembic as the migration framework. Phase 10.1A implements:

1. **Alembic infrastructure** — `alembic.ini`, `alembic/env.py`, baseline migration
2. **Baseline migration** — captures the complete current schema (24 tables: 23 from `models.py` + `users`/`user_sessions` from `identity.py`)
3. **Startup integration** — `init_db()` runs Alembic migrations, then `create_all()` as safety net
4. **Auth path cleanup** — `ensure_identity_schema()` removed from all request handlers
5. **Identity module cleanup** — `ensure_identity_schema()` removed from `identity.py`
6. **Regression tests** — 7 new tests validating migration infrastructure

## 3. Transitional Architecture (CRITICAL)

**The current startup sequence is a TRANSITIONAL architecture, NOT the final state.**

### Current (Phase 10.1A)

```
Application startup (init_db)
    |
    v
Step 1: Alembic upgrade head         <-- Authoritative, versioned
    |
    v
Step 2: Base.metadata.create_all()   <-- Safety net (TRANSITIONAL)
    |
    v
Step 3: ensure_column() x15          <-- Legacy column additions (TRANSITIONAL)
    |
    v
Step 4: backfill + indexes           <-- Data migrations
```

### Target (Phase 10.1B+)

```
Application start
    |
    v
Alembic upgrade head                 <-- Sole schema management mechanism
    |
    v
No request-path DDL.
No create_all().
No ensure_column().
```

### Why the transition exists

- Alembic was just introduced; all existing tables ARE captured in the baseline
- `create_all()` is a safety net during the transition period
- `ensure_column()` calls cover columns from Phases 5.0-8F that predate Alembic
- Production databases may not yet be stamped with the Alembic baseline
- Removing `create_all()` prematurely would risk startup failures on unstamped databases

### What will change in Phase 10.1B

- Convert `ensure_column()` calls to Alembic migrations (they are all no-ops since columns are in baseline)
- Remove `create_all()` from `init_db()`
- Remove `ensure_column()` function entirely
- Production databases must be stamped before this change

### Alembic logging fix (Phase 10.1A hardening)

Alembic's default `env.py` uses `fileConfig()` which modifies the root logger
 globally (adds `StreamHandler`, changes level). This interferes with pytest's
 `caplog` fixture, causing flaky test failures in `test_strike_selection.py`.

**Fix**: Replaced `fileConfig()` with targeted `logging.getLogger()` calls
 that configure only `alembic` and `sqlalchemy.engine` loggers without touching
 the root logger. This preserves Alembic CLI output while avoiding test
 interference.

## 4. create_all() Status

### Current behavior

`Base.metadata.create_all(bind=engine)` runs in `init_db()` after Alembic migrations.

### What it does

Creates any tables in `Base.metadata` that do not yet exist in the database. Does NOT alter existing tables.

### Remaining dependency

**All 24 Base.metadata tables are already in the Alembic baseline migration.** (`greeks_checkpoint` is NOT in Base.metadata — it is a CLI-only table created via raw SQL.) `create_all()` is effectively a no-op for new databases. It exists as a safety net for:

1. Edge cases where Alembic migration fails silently
2. Tables added to `Base.metadata` but not yet in a migration
3. Pre-existing databases that haven't been stamped yet

### Safety properties

- ✅ Only runs during application startup (in `init_db()`, called from FastAPI lifespan)
- ✅ NEVER runs during request handling
- ✅ NEVER modifies existing tables (only creates missing ones)
- ✅ Cannot silently modify production schema without the application being in bootstrap mode

### Phase 10.1B action

Remove `create_all()` once:
1. All production databases are stamped with `alembic stamp head`
2. All `ensure_column()` calls are converted to Alembic migrations
3. The baseline migration is confirmed to cover all tables

## 5. ensure_column() Inventory

### Complete catalog of all 15 ensure_column() calls

All 15 calls add columns to tables that are in the Alembic baseline. The columns
themselves are also in the baseline (verified by autogenerate).

| # | Table | Column | DDL | Phase | In Alembic Baseline | Migration Needed | Risk of Removing |
|---|-------|--------|-----|-------|--------------------|--------------------|------------------|
| 1 | strategy_template_legs | strike_mode | VARCHAR(20) DEFAULT 'fixed' | 6.8B | YES | NO | NONE |
| 2 | strategy_template_legs | strike_offset | INTEGER NULL | 6.8B | YES | NO | NONE |
| 3 | strategy_template_legs | strike_offset_pct | FLOAT NULL | 6.8B | YES | NO | NONE |
| 4 | strategy_template_legs | target_delta | FLOAT NULL | 6.8B | YES | NO | NONE |
| 5 | strategy_template_legs | expiry_mode | VARCHAR(20) DEFAULT 'fixed' | 6.8B | YES | NO | NONE |
| 6 | strategy_template_legs | expiry_dte_min | INTEGER NULL | 6.8B | YES | NO | NONE |
| 7 | strategy_template_legs | expiry_dte_max | INTEGER NULL | 6.8B | YES | NO | NONE |
| 8 | strategy_template_legs | formula_version | INTEGER DEFAULT 1 | 6.8B | YES | NO | NONE |
| 9 | strategy_executions | execution_metadata | TEXT NULL | 6.10 | YES | NO | NONE |
| 10 | strategy_executions | tags | TEXT NULL | 7.0 | YES | NO | NONE |
| 11 | strategy_executions | notes | TEXT NULL | 7.0 | YES | NO | NONE |
| 12 | trades | strategy_execution_id | VARCHAR(40) NULL | 5.0 | YES | NO | NONE |
| 13 | trades | client_order_id | VARCHAR(64) NULL | 5.0 | YES | NO | NONE |
| 14 | gex_snapshots | sweep_data | TEXT NULL | 7.6 | YES | NO | NONE |
| 15 | gex_snapshots | owner_id | VARCHAR(128) NULL | 8F | YES | NO | NONE |

### Analysis

**ALL 15 columns are already represented in the Alembic baseline migration (d3eb45a2e046).**

The `ensure_column()` calls are:
- **Redundant** for new databases (Alembic baseline creates them)
- **Redundant** for stamped databases (Alembic baseline already applied)
- **Necessary only** for pre-existing databases that haven't been stamped yet
- **All nullable with defaults** — idempotent and safe on existing rows
- **All use standard SQL** — work on both SQLite and PostgreSQL

### Phase 10.1B action

1. Create a no-op Alembic migration that documents these columns
2. Remove all 15 `ensure_column()` calls from `init_db()`
3. Remove the `ensure_column()` function from `db.py`
4. Remove the `_existing_columns()` helper function
5. Risk: NONE — all columns are in the baseline

## 6. greeks_checkpoint Decision

### Schema

```sql
CREATE TABLE greeks_checkpoint (
    instrument_key TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'PENDING',
    candle_count   INTEGER DEFAULT 0,
    success_count  INTEGER DEFAULT 0,
    failure_count  INTEGER DEFAULT 0,
    rows_persisted INTEGER DEFAULT 0,
    error_message  TEXT,
    run_id         TEXT,
    started_at     TEXT,
    completed_at   TEXT,
    calc_version   TEXT DEFAULT '1.0.0'
)
```

### Usage analysis

| Location | Purpose | Production-used? |
|----------|---------|-----------------|
| `run_greeks_pilot.py` | CLI tool for historical Greeks reconstruction | CLI only, not web server |
| `tests/test_historical_greeks.py` | Test fixtures | Test only |
| `tools/safe_backup.py` | Backup utility | Operational tool |
| `app/main.py` | **NOT referenced** | No |
| `app/routers/` | **NOT referenced** | No |
| `app/services/` | **NOT referenced** | No |
| `app/models.py` | Referenced in comment only | Documentation |

### Decision

**`greeks_checkpoint` should remain as-is temporarily.** Rationale:

1. **CLI-only table** — Created on-demand by `run_greeks_pilot.py`, not by the web application
2. **Not in web application schema** — `init_db()` does not create it; the web server never touches it
3. **Raw SQL is acceptable** for a CLI tool's own checkpoint table
4. **Converting to SQLAlchemy model + Alembic migration** would be premature — the table is not part of the production web application
5. **Future action**: If `greeks_checkpoint` is ever integrated into the web application (e.g., for background job monitoring), it should become a SQLAlchemy model and be added to Alembic at that time

### Risk assessment

- **Current risk**: LOW — table is created on-demand, idempotent (`CREATE TABLE IF NOT EXISTS`)
- **Production impact**: NONE — web server never touches this table
- **Recommendation**: Do not convert until the table is needed by the web application

## 7. Production Migration Safety Procedure

**DO NOT blindly run `alembic stamp head` against production.**

### Pre-migration checklist

Before migrating a production database:

1. **BACKUP** — Create a full database backup
   ```bash
   # SQLite
   cp paper_journal.db paper_journal.db.pre-migration-backup
   
   # PostgreSQL
   pg_dump $DATABASE_URL > pre_migration_backup.sql
   ```

2. **INSPECT current schema** — Document what tables and columns exist
   ```bash
   # SQLite
   sqlite3 paper_journal.db ".schema" > current_schema.sql
   
   # PostgreSQL
   pg_dump --schema-only $DATABASE_URL > current_schema.sql
   ```

3. **COMPARE against Alembic baseline** — Verify the production schema matches
   ```bash
   # Generate Alembic's expected schema
   python -m alembic upgrade head --sql > expected_schema.sql
   
   # Diff (manual review — ignore ordering, focus on tables/columns/constraints)
   diff current_schema.sql expected_schema.sql
   ```

4. **RESOLVE discrepancies** — If production has tables/columns not in Alembic:
   - Do NOT stamp until discrepancies are resolved
   - Create additional Alembic migrations to cover them
   - Or manually add missing tables to the baseline

5. **STAMP only when verified** — The production schema must be equivalent to the Alembic baseline
   ```bash
   # This marks the database as "up to date" WITHOUT modifying schema
   python -m alembic stamp head
   ```

6. **VERIFY stamp** — Confirm the version was recorded
   ```bash
   python -m alembic current
   # Should show: d3eb45a2e046 (head)
   ```

7. **VERIFY critical tables** — Spot-check that key tables exist and have correct columns
   ```bash
   # SQLite
   sqlite3 paper_journal.db "PRAGMA table_info(users);"
   sqlite3 paper_journal.db "PRAGMA table_info(user_sessions);"
   sqlite3 paper_journal.db "PRAGMA table_info(strategy_executions);"
   ```

8. **VERIFY application startup** — Deploy the new code and confirm the app starts
   ```bash
   # Check logs for:
   # "Alembic migrations applied successfully"
   # No errors from create_all() or ensure_column()
   ```

9. **ROLLBACK procedure** — If migration fails:
   ```bash
   # SQLite: restore from backup
   cp paper_journal.db.pre-migration-backup paper_journal.db
   
   # PostgreSQL: restore from backup
   psql $DATABASE_URL < pre_migration_backup.sql
   ```

### Important: `stamp` does NOT modify schema

`alembic stamp head` ONLY writes a row to the `alembic_version` table. It does NOT:
- Create tables
- Add columns
- Modify data
- Drop anything

It is a metadata operation that tells Alembic "this database already has the schema defined by this migration."

## 8. Multi-Instance Migration Architecture

### Current: Startup-time migration (transitional)

```
Application start
    |
    v
init_db() runs Alembic upgrade head
    |
    v
Application serves traffic
```

**Why it exists**: The current single-instance deployment (Railway) runs one backend process. Startup-time migration is simple and works.

**Concurrency considerations**:
- If multiple instances start simultaneously, they all run `alembic upgrade head`
- Alembic uses a database-level lock (alembic_version table) to serialize migrations
- On SQLite: Only one process can write at a time (WAL mode helps reads)
- On PostgreSQL: Alembic acquires an advisory lock
- **Risk**: LOW for current single-instance deployment
- **Risk**: MEDIUM for future multi-instance deployment (migration runs N times, but is idempotent)

### Preferred: Deployment-time migration (target)

```
deployment/release migration step
        |
        v
successful migration
        |
        v
application instances start (no DDL at startup)
```

**When to adopt**:
- When deploying multiple application instances simultaneously
- When using a container orchestrator (Kubernetes, ECS)
- When zero-downtime deploys are required
- Phase 10.1B or later

**How to implement**:
- Add a deployment step that runs `alembic upgrade head` before rolling out new instances
- Remove `init_db()` DDL from application startup
- Application instances start with schema already at correct version

### Recommendations

| Concern | Current | Target |
|---------|---------|--------|
| Migration runs at | Startup | Deployment |
| Multiple instances | All run migrations (idempotent) | Migration runs once before deploy |
| DDL during traffic | No (startup only) | No (pre-deploy) |
| Rollback | Restore backup + downgrade | Deployment rollback + downgrade |
| Complexity | Low | Medium (deployment pipeline) |

### Do NOT introduce

- A migration microservice
- A paid migration service
- Complex distributed locking
- A separate migration database

Alembic's built-in locking is sufficient for the current and near-term architecture.

## 9. Files Changed

| File | Action | Lines Changed |
|------|--------|---------------|
| `backend/requirements.txt` | Modified | +1 (alembic==1.15.2) |
| `backend/alembic.ini` | **New** | ~80 |
| `backend/alembic/env.py` | **New** | ~110 |
| `backend/alembic/script.py.mako` | **New** | ~25 |
| `backend/alembic/versions/d3eb45a2e046_...py` | **New** | ~1000+ |
| `backend/app/db.py` | Modified | +80 (transitional docs, inventory, improved init_db) |
| `backend/app/identity.py` | Modified | -13 (removed ensure_identity_schema + engine) |
| `backend/app/routers/auth.py` | Modified | +3/-3 (removed ensure_identity_schema calls) |
| `backend/tests/test_alembic_migrations.py` | **New** | ~190 |
| `backend/tests/test_identity_foundation.py` | Modified | +10/-5 (added metadata + TTL tests) |
| `docs/PHASE_10_1A_DATABASE_MIGRATIONS.md` | **New/Updated** | ~400 |

## 10. Test Results

### New tests (Phase 10.1A)

```
tests/test_alembic_migrations.py — 7 passed
  test_alembic_baseline_creates_all_model_tables
  test_init_db_uses_alembic_when_available
  test_init_db_is_idempotent
  test_no_ensure_identity_schema_in_auth_router
  test_identity_module_has_no_engine_dependency
  test_alembic_stamped_database_is_upgradeable
  test_auth_callback_does_not_call_ensure_identity_schema

tests/test_identity_foundation.py — 4 passed (updated)
tests/test_db_migration.py — 7 passed (unchanged, no regressions)
```

### Full regression test results (31 test suites, 897 tests)

```
889 passed, 1 pre-existing failure, 7 skipped

Suites executed:
  test_alembic_migrations.py         — 7 passed
  test_identity_foundation.py        — 4 passed
  test_db_migration.py               — 7 passed
  test_auth_router.py                — 11 passed, 1 pre-existing failure
  test_cors.py                       — 11 passed
  test_token_store.py                — passed
  test_market_status.py              — passed
  test_phase9_security.py            — passed
  test_paper_router.py               — 19 passed
  test_execution_intent.py           — 93 passed
  test_paper_execution.py            — passed
  test_bulk_exit.py                  — passed
  test_strategy_templates.py         — passed
  test_gex_api.py                    — passed
  test_gex_security.py               — passed
  test_broker_domain.py              — passed
  test_broker_profile.py             — passed
  test_broker_margin.py              — passed
  test_chains_router.py              — 44 passed
  test_orders_api.py                 — 22 passed
  test_positions_routing.py          — 17 passed
  test_capital.py                    — 12 passed
  test_exit_attribution.py           — passed
  test_leg_exposure.py               — passed
  test_performance.py                — passed
  test_iv_history.py                 — passed
  test_pricing.py                    — passed
  test_valuation.py                  — passed
  test_strike_selection.py           — passed (flaky in suite, passes individually)
  test_historical_greeks.py          — passed
  test_historical_gex.py             — passed
```

### Pre-existing failure (NOT caused by Phase 10.1A)

```
tests/test_auth_router.py::test_callback_with_code_sets_session_cookie_and_redirects
```

This test fails on the Phase 10.1 identity branch because the callback now calls
`get_profile()` after token exchange, but the test only mocks `exchange_code_for_token`.
Verified by running the same test on the unmodified Phase 10.1 branch — same failure.

## 11. Deployment Instructions

### New deployment

No special steps — `init_db()` runs `alembic upgrade head` on first startup.

### Existing production database

1. Follow the safety procedure in §7 above
2. Backup → Inspect → Compare → Resolve → Stamp → Verify → Deploy
3. One-time operation; future migrations apply automatically

## 12. Remaining Risks

1. **`create_all()` safety net** — Still runs after Alembic. Will be removed in Phase 10.1B.
2. **`ensure_column()` calls** — 15 legacy calls remain. All redundant with baseline. Will be removed in Phase 10.1B.
3. **`greeks_checkpoint` table** — CLI-only, not in web schema. Documented decision to leave as-is.
4. **Pre-existing auth callback test failure** — Needs mock for `get_profile()` on Phase 10.1 identity branch.
5. **Production stamp procedure** — Must be followed carefully. See §7.

## 13. Phase 10.1B Prerequisites

Before Phase 10.1B can begin:

1. ✅ Alembic infrastructure established (Phase 10.1A)
2. ✅ Baseline migration covers all tables (Phase 10.1A)
3. ✅ Auth path cleaned of DDL (Phase 10.1A)
4. ⬜ All production databases stamped with `alembic stamp head`
5. ⬜ Production schema verified equivalent to Alembic baseline
6. ⬜ Pre-existing auth callback test fixed (Phase 10.1 prerequisite)

Phase 10.1B will:
- Convert `ensure_column()` calls to Alembic migrations (no-op migrations documenting the columns)
- Remove `create_all()` from `init_db()`
- Remove `ensure_column()` and `_existing_columns()` functions
- Result: Alembic as sole schema management mechanism
