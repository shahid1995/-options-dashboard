# Phase 7.24.7 — Production Readiness, Persistence & No-Redownload Validation

## Status: PASS

## Objective

Prove that the Permanent Data Pipeline architecture behaves as intended:

> Historical data is downloaded explicitly once, stored locally, and becomes the local source of truth. The application must never redownload historical data merely because the server starts, restarts, reloads, or a user opens the website.

## Bugs Fixed

### Token expiry default (Phase 7.24.3)

**Root cause:** `UpstoxTokenManager.save(expires_at=None)` defaulted to today at 03:30 UTC. When the process ran after 03:30 UTC, the token was immediately expired.

**Fix:** Changed default to `now + 24 hours`, which is always in the future.

### NIFTY backfill `start_date` (Phase 7.24.5)

**Root cause:** `BackfillOrchestrator.run_nifty(force=True)` skipped the `start_date` initialization block entirely, leaving `start_date=None` and causing a `TypeError` on comparison.

**Fix:** Always default `start_date` to `today - 180 days` when not provided, regardless of the `force` flag.

## Architecture Audit

### Startup Path

```
FastAPI lifespan
  └→ init_db()
       ├→ Base.metadata.create_all()  ← safe, schema only
       ├→ ensure_column()             ← safe, schema only
       ├→ backfill_all_exposures()    ← safe, paper-trading only
       └→ CREATE INDEX IF NOT EXISTS  ← safe, schema only
```

**Zero historical API calls on startup.**

### Confirmed Safe Paths

| Path | API Calls |
|------|-----------|
| Server startup | 0 |
| Server restart | 0 |
| `init_db()` | 0 |
| Database creation | 0 |
| Frontend page load | 0 |
| Normal API request | 0 |

### Dangerous Paths Found and Audited

- `backfill_all_exposures()` — paper-trading only, no market data API calls
- `phase723b_endpoint.py` — dev-only endpoint (not in production startup path)

## Test Results

### Phase 7.24.7 Production-Readiness Tests: 40/40 PASS

| Category | Tests | Result |
|----------|------:|--------|
| Zero automatic ingestion | 5 | All pass |
| Backfill dry-run | 2 | All pass |
| Daily dry-run | 1 | All pass |
| Database persistence | 2 | All pass |
| Token persistence | 3 | All pass |
| No-redownload | 3 | All pass |
| Partial-data / resume | 2 | All pass |
| Checkpoint / crash recovery | 2 | All pass |
| Failure isolation | 1 | All pass |
| Daily idempotency | 2 | All pass |
| Raw data immutability | 3 | All pass |
| Timezone validation | 2 | All pass |
| Greeks separation | 3 | All pass |
| No token leakage | 3 | All pass |
| CLI entry points | 4 | All pass |
| Date chunks | 2 | All pass |

### Full Regression

| Suite | Tests | Result |
|-------|------:|--------|
| Full backend | 2,104 | **All pass** |
| Full frontend | 1,357 | **All pass** |
| **Total** | **3,461** | **0 failures** |

### Previous Regression Failure

`test_phase724_3_token_manager.py::TestSaveLoad::test_no_expiry_defaults_to_expiring_soon`

- **Exact reason:** Token default expiry (today 03:30 UTC) was in the past when test ran after 03:30 UTC
- **Phase affected:** 7.24.3 introduced the bug; all subsequent phases inherited it
- **Fix:** Changed default to `now + 24 hours`
- **Status:** FIXED — all 2,104 backend tests now pass

## Proof Summary

| Gate | Result |
|------|--------|
| Zero startup API calls | ✅ PASS |
| Zero `init_db()` API calls | ✅ PASS |
| Zero dry-run API calls | ✅ PASS |
| Database persistence | ✅ PASS |
| CWD-independent DB path | ✅ PASS |
| Token persistence | ✅ PASS |
| No-redownload | ✅ PASS |
| Partial-range ingestion | ✅ PASS |
| Checkpoint resume | ✅ PASS |
| Failure isolation | ✅ PASS |
| Daily incremental idempotency | ✅ PASS |
| Raw data immutability | ✅ PASS |
| IST timestamp convention | ✅ PASS |
| No automatic Greeks | ✅ PASS |
| No token leakage | ✅ PASS |
| Backend: 0 failures | ✅ PASS |
| Frontend: 0 failures | ✅ PASS |

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_phase724_7_production_readiness.py` | 40 comprehensive production-readiness tests |
| `docs/PHASE_7_24_7_PRODUCTION_READINESS.md` | This document |

## Files Modified

| File | Change |
|------|--------|
| `app/services/upstox_token_manager.py` | Fixed default token expiry (now+24h instead of today 03:30 UTC) |
| `app/services/backfill_orchestrator.py` | Fixed `run_nifty()` `start_date` initialization when `force=True` |

## Protected Files — Scope Audit

The following were **NOT modified** by Phase 7.24.7 (beyond the two fixes above):

- Frontend
- GEX calculations
- IV calculations
- Greeks mathematics
- Research engine
- OAuth/authentication flow
- Trading/order execution
- Database schema
- Existing raw market data

## Real Upstox API Calls

**0** — all tests use mocked HTTP responses.

## No Large Data Operations

**0** — no historical backfill performed during this phase.

## Acceptance

**PHASE 7.24.7 ACCEPTANCE: PASS**

All mandatory gates pass. The architecture is ready for the controlled one-time historical population using `run_backfill.py`.
