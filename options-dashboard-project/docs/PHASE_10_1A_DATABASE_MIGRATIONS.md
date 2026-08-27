# Phase 10.1A — Database Migration Foundation

_Last updated: 2026-08-27_

## Status

**COMPLETE — READY FOR PRINCIPAL ARCHITECT REVIEW**

## Problem

Phase 10.1 (identity foundation) introduced `User` and `UserSession` tables via a
runtime `ensure_identity_schema()` function called on every authentication request
(`/callback`, `/me`, `/logout`). This pattern:

1. **Executes DDL on every request path** — a performance and reliability risk
2. **Has no version tracking** — no way to know which schema version a database is at
3. **Cannot handle schema evolution** — no mechanism for column additions, renames, or data migrations
4. **Inconsistent with future plans** — the project needs proper schema management for growth

The existing `init_db()` / `create_all()` / `ensure_column()` pattern was also
reaching its limits — it creates tables on startup but cannot alter existing ones.

## Solution

Establish Alembic as the migration framework. Phase 10.1A implements:

1. **Alembic infrastructure** — `alembic.ini`, `alembic/env.py`, baseline migration
2. **Baseline migration** — captures the complete current schema (25 tables)
3. **Startup integration** — `init_db()` runs Alembic migrations, then `create_all()` as safety net
4. **Auth path cleanup** — `ensure_identity_schema()` removed from all request handlers
5. **Identity module cleanup** — `ensure_identity_schema()` removed from `identity.py`
6. **Regression tests** — 7 new tests validating migration infrastructure

## Architecture

### Migration Strategy

```
Application startup (init_db)
    |
    v
Alembic upgrade head    <-- Versioned schema management
    |
    v
create_all()            <-- Safety net for tables not yet in migrations
    |
    v
ensure_column()         <-- Legacy idempotent column additions (deprecated, will migrate to Alembic)
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Keep `create_all()` as safety net | Ensures fresh databases work even if a migration is missed |
| Keep `ensure_column()` for now | Existing columns are already managed; migrating them is a separate task |
| `render_as_batch=True` in env.py | Required for SQLite ALTER TABLE support |
| Programmatic Alembic in `init_db()` | Uses `alembic.config.Config` + `command.upgrade()` for startup |
| Config URL precedence | `set_main_option("sqlalchemy.url", ...)` in `_run_alembic_migrations()` ensures tests work |

### Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Added `alembic==1.15.2` |
| `backend/alembic.ini` | **NEW** — Alembic configuration |
| `backend/alembic/env.py` | **NEW** — Alembic environment with project model imports |
| `backend/alembic/script.py.mako` | **NEW** — Migration template |
| `backend/alembic/versions/d3eb45a2e046_baseline_initial_schema_with_all_tables.py` | **NEW** — Baseline migration |
| `backend/app/db.py` | Added `_run_alembic_migrations()`, updated `init_db()` |
| `backend/app/identity.py` | Removed `ensure_identity_schema()` and `engine` import |
| `backend/app/routers/auth.py` | Removed `ensure_identity_schema()` calls from all endpoints |
| `backend/tests/test_alembic_migrations.py` | **NEW** — 7 migration regression tests |
| `backend/tests/test_identity_foundation.py` | Updated for Phase 10.1A |

## Migration Operations

### New database (fresh deployment)

```bash
cd backend
python -m alembic upgrade head
# or just start the app — init_db() runs migrations automatically
```

### Existing database (pre-existing create_all schema)

```bash
cd backend
python -m alembic stamp head    # Mark current state as up-to-date
# Then start the app — future migrations will apply automatically
```

### Generate new migration

```bash
cd backend
python -m alembic revision --autogenerate -m "description of change"
```

### Check current version

```bash
cd backend
python -m alembic current
```

### Downgrade (emergency only)

```bash
cd backend
python -m alembic downgrade -1
```

## Test Results

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

### Regression test results

```
tests/test_auth_router.py — 11 passed, 1 pre-existing failure
tests/test_cors.py — 11 passed
tests/test_token_store.py — passed
tests/test_market_status.py — passed
tests/test_paper_router.py — 19 passed
tests/test_chains_router.py — 44 passed
tests/test_execution_intent.py — 93 passed
tests/test_orders_api.py — 22 passed
tests/test_positions_routing.py — 17 passed
tests/test_capital.py — 12 passed
tests/test_paper_execution.py — passed
tests/test_bulk_exit.py — passed
tests/test_exit_attribution.py — passed
tests/test_leg_exposure.py — passed
tests/test_strategy_templates.py — passed
tests/test_template_execution.py — passed
tests/test_broker_domain.py — passed
tests/test_broker_profile.py — passed
tests/test_broker_margin.py — passed
tests/test_gex_api.py — passed
tests/test_gex_capture.py — passed
tests/test_pricing.py — passed
tests/test_valuation.py — passed
tests/test_strike_selection.py — passed
tests/test_phase9_security.py — passed
```

**Total verified: ~800+ tests, 0 regressions from Phase 10.1A changes**

### Pre-existing failure (NOT caused by this phase)

```
tests/test_auth_router.py::test_callback_with_code_sets_session_cookie_and_redirects
```

This test fails on the Phase 10.1 identity branch because the callback now calls
`get_profile()` after token exchange, but the test only mocks `exchange_code_for_token`.
This is a pre-existing issue in the `feat/phase-10-identity-foundation` branch.

## Deployment Instructions

### Production (existing database)

1. Deploy the code with Alembic infrastructure
2. Run `alembic stamp head` on the production database BEFORE the first app startup
3. Subsequent deployments will apply migrations automatically via `init_db()`

### New deployment

No special steps — `init_db()` runs `alembic upgrade head` on first startup.

## Remaining Risks

1. **Existing `ensure_column()` calls in `init_db()`** — These should eventually be
   converted to Alembic migrations. They remain for backward compatibility.
2. **`create_all()` safety net** — Still runs after Alembic. Once all tables are in
   migrations, this can be removed.
3. **Pre-existing auth callback test failure** — Needs mock for `get_profile()` on
   the Phase 10.1 identity branch.

## Next Steps

- Phase 10.1B: Convert existing `ensure_column()` calls to Alembic migrations
- Phase 10.2: User roles and permissions (RBAC)
- Phase 10.3: Subscription management
- Phase 10.4: Admin portal
