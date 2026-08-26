# Phase 7.20 — Historical Data Architecture Audit

**Date:** 2026-08-24
**Status:** Read-Only Audit (no production logic changes)
**Scope:** Complete architecture review through Phase 7.19B

---

## Executive Summary

This document audits the complete historical data architecture built through Phases 7.8–7.19B. The audit identifies **one critical infrastructure issue**, **two significant design gaps**, and **several minor concerns** that must be resolved before any large-scale historical backfill is attempted.

**Critical Finding:** The production SQLite database (`paper_journal.db`) currently contains all expected tables but zero rows. The 2MB file size reflects only schema/index overhead. Data was lost — most likely because the database uses a relative file path (`sqlite:///./paper_journal.db`) that resolves differently depending on the process working directory. When the server or backfill tools run from different directories, they create separate empty databases.

**Bottom Line:** The architectural design is sound. The three-layer data model (RAW → MODEL → ANALYTICS), lot-size immutability rules, and Greeks versioning are all correct. However, **no large backfill can safely proceed** until the database persistence issue is resolved.

---

## 1. Current Architecture Overview

### 1.1 Three-Layer Data Model

```
Layer 1: RAW (Immutable Source-of-Truth)
  ├── nifty_candles        — NIFTY 50 index OHLCV
  ├── option_candles       — Historical expired option OHLCV
  └── contract_specs       — Per-instrument historical metadata

Layer 2: MODEL (Derived, Recalculable)
  └── option_greeks        — IV + Black-Scholes Greeks

Layer 3: ANALYTICS (Consumed by UI/Research)
  ├── GEX calculation
  ├── Vega/Delta exposure
  └── IV research
```

**Status: VERIFIED — Correctly implemented.**

### 1.2 Data Flow

```
Upstox API
    ↓
Normalization (IST → UTC, array → dict)
    ↓
Validation (hard errors reject, soft warnings store)
    ↓
Idempotent Upsert (SQLite INSERT ON CONFLICT DO UPDATE)
    ↓
Persistent Raw Database
    ↓
Greek Reconstruction (IV solver + BS)
    ↓
Research / GEX / Analytics
    ↓
Website
```

**Status: VERIFIED — Correctly implemented.**

### 1.3 Service Inventory

| Service | File | Status | Lines |
|---------|------|--------|-------|
| Candle config | `candle_config.py` | ✅ Complete | 52 |
| Candle ingestion | `candle_ingestion.py` | ✅ Complete | ~200 |
| Candle validation | `candle_validation.py` | ✅ Complete | ~250 |
| Candle retry | `candle_retry.py` | ✅ Complete | ~100 |
| Candle coverage | `candle_coverage.py` | ✅ Complete | ~400 |
| Nifty candles | `nifty_candles.py` | ✅ Complete | ~180 |
| Option candles | `option_candles.py` | ✅ Complete | ~220 |
| Contract metadata | `contract_metadata.py` | ✅ Complete | ~280 |
| Strike selection | `strike_selection.py` | ✅ Complete | ~320 |
| Historical Greeks | `historical_greeks.py` | ✅ Complete | ~780 |
| Upstox adapter | `upstox.py` | ✅ Phase 7.8A | +172 |
| Candle backfill | `candle_backfill.py` | ✅ Complete | ~280 |
| Option candle backfill | `option_candle_backfill.py` | ✅ Complete | ~280 |
| Contract metadata backfill | `contract_metadata_backfill.py` | ✅ Complete | ~200 |
| Candles router | `candles.py` | ✅ Complete | ~100 |
| Live verification | `live_verification.py` | ✅ Temp tool | ~700 |
| Phase 7.18 audit | `phase718_audit.py` | ⚠️ TEMP — needs removal | ~350 |

---

## 2. Critical Persistence Audit

### 2.1 Root Cause of Data Loss

**Finding:** The `paper_journal.db` file exists (2,097,152 bytes = exactly 2MB, a SQLite default page allocation) but contains **zero rows in every table**.

**Evidence:**
```
Tables: ['contract_specs', 'nifty_candles', 'option_candles', 'option_greeks', ...]
All tables: 0 rows
File size: 2,097,152 bytes (schema only)
Database path: backend/paper_journal.db
```

**Root cause analysis:**

The database URL is configured as:

```python
# config.py
DATABASE_URL: str | None = None  # NOT SET in .env

# db.py
url = settings.DATABASE_URL or "sqlite:///./paper_journal.db"
```

The path `./paper_journal.db` is **relative to the current working directory**. This means:

| Process | CWD | Database File Created |
|---------|-----|----------------------|
| Server (`uvicorn`) | `backend/` | `backend/paper_journal.db` |
| Backfill CLI | `backend/` | `backend/paper_journal.db` |
| Backfill CLI | project root | `paper_journal.db` (different file!) |
| Test | temp in-memory | `sqlite://` (separate, dropped after test) |

When Freebuff restarts, the CWD may reset. If the server previously ran from `backend/` and created data in `backend/paper_journal.db`, but a subsequent process runs from a different directory, it creates a **different** `paper_journal.db` — an empty one.

Additionally, each backfill tool creates its **own** engine instance:

```python
# option_candle_backfill.py
def _make_db_session():
    url = settings.DATABASE_URL or "sqlite:///./paper_journal.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()
```

While multiple engines pointing to the same file should work for SQLite (single-writer), the relative path makes this fragile.

### 2.2 Stale Test Table

**Finding:** The database contains an `option_candles_test` table that is NOT in any model definition.

This indicates a test or debugging session wrote to the production database file. While not harmful, it indicates the production/test database boundary is not enforced.

### 2.3 Token Store Persistence

**Finding:** The Upstox access token is stored in-memory only:

```python
# token_store.py
_state = {"access_token": None, "session_id": None}
```

Every server restart requires re-authentication. This is acceptable for development but must be documented.

### 2.4 Persistence Verdict

| Aspect | Status | Risk |
|--------|--------|------|
| Database file path | ❌ Relative, fragile | **CRITICAL** |
| Multiple engine instances | ⚠️ Works but fragile | Medium |
| Token persistence | ⚠️ In-memory only | Low (dev only) |
| Test/production separation | ❌ Not enforced | Medium |
| Schema management | ✅ `create_all` + `ensure_column` | Low |
| Backup strategy | ❌ None | High for production |

---

## 3. Required Changes Before Backfill

### 3.1 PRIORITY 1: Absolute Database Path (CRITICAL)

**Problem:** Relative path resolves differently per CWD.
**Fix:** Either:
- (a) Set `DATABASE_URL` to an absolute path in `.env`, or
- (b) Change `db.py` to resolve relative to the `backend/` directory:
  ```python
  import os
  _BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
  url = settings.DATABASE_URL or f"sqlite:///{os.path.join(_BACKEND_DIR, 'paper_journal.db')}"
  ```

**Recommendation:** Option (b) — always resolve relative to `backend/` so all tools and the server use the same file regardless of CWD.

### 3.2 PRIORITY 2: Single Engine Pattern

**Problem:** Each backfill tool creates its own engine. While this works for SQLite, it's fragile and wastes connection pool resources.
**Fix:** Backfill tools should import and use the module-level `engine` from `db.py` instead of creating new ones. Or accept the separate-engine pattern but ensure all paths are absolute (per 3.1).

### 3.3 PRIORITY 3: Remove Temporary Development Endpoints

**Problem:** `phase718_audit.py` is still registered in `main.py`:
```python
# DEV ONLY -- REMOVE AFTER PHASE 7.18
from app.routers import phase718_audit
app.include_router(phase718_audit.router, prefix="/dev", tags=["dev-phase718"])
```

**Fix:** Remove the router registration and delete `phase718_audit.py` before committing Phase 7.20.

---

## 4. NIFTY Index Data Assessment

### 4.1 Index vs Option Distinction

| Concept | Source | Treatment |
|---------|--------|-----------|
| NIFTY 50 index candles | Upstox V3 Historical Candle API | Stored in `nifty_candles` |
| NIFTY option contracts | Upstox V2 Expired Option Contracts API | Stored in `contract_specs` |
| NIFTY option candles | Upstox V2 Expired Historical Candle API | Stored in `option_candles` |

**Status: VERIFIED — Correctly separated.**

### 4.2 Trading Hours

| Session | Close Time (IST) | Candles/Day (3-min) |
|---------|------------------|---------------------|
| NIFTY index | 15:27 | 124 |
| NIFTY options | 15:40 | 128 |

The candle_config.py was updated in Phase 7.18 to reflect the extended options session.

**Status: VERIFIED.**

### 4.3 Post-Close Option Candles

Option candles between 15:27–15:40 IST use the last NIFTY index close (15:27) as the spot price for Greek calculations. This is correct — the index has closed but options continue trading.

**Status: VERIFIED in `historical_greeks.py` `align_spot()` function.**

---

## 5. Raw vs Derived Data Architecture

### 5.1 Immutability Verification

| Table | Classification | Immutability Rule |
|-------|---------------|-------------------|
| `nifty_candles` | RAW | Never modified after insert |
| `option_candles` | RAW | Never modified after insert |
| `contract_specs` | RAW | lot_size NEVER overwritten once set |
| `option_greeks` | MODEL | Recalculable from raw data |

**Verification from code:**
- `record_candles()` — upserts OHLCV, never deletes historical data
- `record_option_candles()` — same pattern
- `upsert_contract_spec()` — immutability rules enforced (4 cases: insert, idempotent, fill NULL, conflict)
- `persist_results()` — upserts on `(instrument_key, interval, open_time, calc_version)`

**Status: VERIFIED — All immutability rules correctly implemented.**

### 5.2 Derived Data Regeneration

The Greeks engine can regenerate all derived data from raw tables:
1. Read `option_candles` (raw OHLCV)
2. Join with `contract_specs` (strike, type, expiry, lot_size)
3. Read `nifty_candles` (spot price)
4. Calculate IV + Greeks
5. Write to `option_greeks`

If Greeks methodology changes, only step 4-5 need re-running. Raw data is never touched.

**Status: VERIFIED.**

---

## 6. Historical Lot-Size Architecture

### 6.1 Verified Historical Lot Sizes

From live Phase 7.15/7.18 verification:

| Expiry | Lot Size | Source | Status |
|--------|----------|--------|--------|
| 2024-10-31 | 25 | Upstox API | VERIFIED |
| 2024-11-28 | 25 | Upstox API | VERIFIED |
| 2024-12-26 | 25 | Upstox API | VERIFIED |
| 2025-01-30 | 25 | Upstox API | VERIFIED |
| 2025-02-13 | 75 | Upstox API | VERIFIED |
| 2025-04-17 | 75 | Upstox API | VERIFIED |

### 6.2 Immutability Rules

From `contract_metadata.py`:
- **New row:** Insert with whatever lot_size the API returned
- **Existing row, same lot_size:** Idempotent no-op
- **Existing row, NULL lot_size + valid API lot_size:** Fill it
- **Existing row, valid lot_size + DIFFERENT API lot_size:** CONFLICT — preserve existing

**Status: VERIFIED — Rules correctly implemented and tested.**

### 6.3 Lot-Size Independence of Candle Pipeline

The following modules have **zero** dependency on lot_size:
- `candle_ingestion.py` — pure OHLCV normalization
- `candle_validation.py` — structural validation only
- `candle_coverage.py` — coverage statistics only
- `candle_backfill.py` — index candle backfill
- `option_candles.py` — option candle persistence
- `nifty_candles.py` — index candle persistence

Lot_size enters the pipeline **only** at the Greek calculation layer via `contract_specs`.

**Status: VERIFIED — Confirmed by code audit.**

---

## 7. Daily Incremental Ingestion Design

### 7.1 Current State

The existing backfill tools are **batch-oriented**, not incremental:
- `candle_backfill.py` — downloads 28-day chunks
- `option_candle_backfill.py` — downloads one contract at a time

### 7.2 Proposed Daily Ingestion Architecture

```
Daily Scheduler (cron / manual trigger)
    ↓
1. Check latest stored timestamps per table
2. Determine what's missing
3. Fetch only new data from Upstox
4. Normalize + validate + persist
5. Record ingestion status
6. Log any failures for retry
```

### 7.3 Key Requirements

| Requirement | Implementation |
|-------------|---------------|
| Latest timestamp query | `SELECT MAX(open_time) FROM option_candles WHERE instrument_key = ?` |
| Incremental fetch | `from_date = latest_stored + interval` |
| New contract discovery | Check contract_specs for new instrument_keys |
| Expiry handling | Newly expired contracts need backfill |
| Duplicate protection | SQLite upsert on unique constraint |
| Resume after interruption | Already implemented via skip-existing logic |
| Failure recording | Log failed contracts, retry later |
| Progress tracking | Elapsed time + contracts processed |

### 7.4 Checkpoint Strategy

The existing backfill already supports checkpoint/resume:
- `get_completed_instruments()` returns instrument_keys that have candle data
- `skip_existing=True` skips already-fetched contracts
- `_has_candles_for_date_range()` skips chunks with existing data

**Status: DESIGN COMPLETE — Implementation needed.**

---

## 8. Restart and Crash Recovery

### 8.1 Current Recovery Behavior

| Scenario | Current Behavior | Safe? |
|----------|-----------------|-------|
| Normal server restart | DB file persists (if CWD same), token lost | ⚠️ Partial |
| Unexpected process termination | DB commits are atomic per batch | ✅ Yes |
| Interrupted ingestion | Skip-existing logic resumes correctly | ✅ Yes |
| API timeout mid-fetch | Current contract failed, next one proceeds | ✅ Yes |
| API rate limit (429) | Exponential backoff retries | ✅ Yes |
| Network failure | Error logged, next contract attempted | ✅ Yes |
| CWD change between runs | Different DB file created | ❌ **No** |

### 8.2 Required Fixes

1. **Absolute database path** (Priority 1 from Section 3)
2. **Ingestion status table** — record per-contract fetch status with timestamps
3. **Failure queue** — store failed contracts for later retry

---

## 9. Backfill Safety Gates

Before any large historical backfill is allowed, ALL of these must be proven:

| Gate | Status | Required Action |
|------|--------|----------------|
| Database survives restart | ❌ NOT PROVEN | Fix absolute path, verify |
| Database survives server reload | ❌ NOT PROVEN | Same as above |
| Data survives process termination | ✅ Atomic commits | Already works |
| Duplicate protection works | ✅ Upsert verified | Already works |
| Checkpoint/resume works | ✅ Skip-existing verified | Already works |
| Raw data is immutable | ✅ Code verified | Already works |
| NIFTY index candles available | ⚠️ Empty DB | Re-populate after fix |
| Option candles available | ⚠️ Empty DB | Re-populate after fix |
| Contract metadata historically correct | ⚠️ Empty DB | Re-populate after fix |
| Lot sizes historically preserved | ✅ Live verified | Works correctly |
| Derived calculations regenerable | ✅ Engine exists | Already works |
| API not repeatedly queried | ✅ Skip-existing logic | Already works |

**Verdict: 2 of 12 gates FAILED. Backfill cannot safely proceed.**

---

## 10. Storage Architecture Evaluation

### 10.1 Current: SQLite

| Aspect | Assessment |
|--------|-----------|
| Setup complexity | ✅ Zero — just a file |
| Cost | ✅ Free |
| Performance (reads) | ✅ Excellent for <10GB |
| Performance (writes) | ⚠️ Single-writer, fine for batch |
| Concurrent access | ⚠️ Writers block readers |
| Backup | ⚠️ File copy (need VACUUM for compact) |
| Scalability | ⚠️ Practical limit ~10GB |
| Migration | ❌ No migration framework |

### 10.2 Alternative: PostgreSQL

| Aspect | Assessment |
|--------|-----------|
| Setup complexity | ⚠️ Requires server |
| Cost | Free tier available (Railway, Supabase) |
| Performance | ✅ Excellent at any scale |
| Concurrent access | ✅ Full MVCC |
| Migration | ✅ Alembic |
| Complexity | ⚠️ More operational overhead |

### 10.3 Recommendation

**For Phase 7.20–7.21:** Stay with SQLite. The estimated Tier 1 dataset (~4M candles, ~1GB) fits comfortably in SQLite. The simplicity advantage is significant for a solo developer.

**When to migrate to PostgreSQL:**
- Database exceeds 5GB
- Concurrent read/write becomes a bottleneck
- Multi-user deployment is needed
- Cloud deployment requires shared state

**Do NOT introduce a paid database service.** SQLite is sufficient for the current architecture.

---

## 11. API Usage Policy

### 11.1 Historical API (Batch)

| Use Case | Permitted | Notes |
|----------|-----------|-------|
| Initial historical backfill | ✅ | Controlled, rate-limited |
| Filling verified gaps | ✅ | After coverage audit |
| Data repair | ✅ | After identified corruption |
| Recalculation | ❌ | Use stored raw data |

### 11.2 Daily API (Incremental)

| Use Case | Permitted | Notes |
|----------|-----------|-------|
| New market data (today) | ✅ | After market close |
| Newly discovered contracts | ✅ | After expiry |
| Incremental updates | ✅ | Only missing data |
| Re-downloading existing data | ❌ | Use stored data |

### 11.3 Website / Application

| Use Case | Permitted | Notes |
|----------|-----------|-------|
| Read historical from DB | ✅ | Primary data source |
| Query Upstox for historical display | ❌ | Must read from DB |
| Live chain data | ✅ | Real-time from broker |
| Historical chart data | ✅ | From stored candles |

---

## 12. Phase 7.12–7.19B Decision Audit

### 12.1 Decisions That Remain Correct

| Decision | Phase | Verdict |
|----------|-------|---------|
| 3-minute resolution | 7.12 | ✅ Correct — matches GEX granularity needs |
| ATM ±20 strikes | 7.16 | ✅ Correct — captures meaningful GEX contribution |
| Monthly expiry selection | 7.17 | ✅ Correct — weekly adds complexity without proportional value |
| Fixed ATM per expiry | 7.17 | ✅ Correct — NIFTY rarely moves >500 pts in a week |
| Option candle schema | 7.13 | ✅ Correct — instrument_key identity, no lot_size column |
| Greeks versioning | 7.19A | ✅ Correct — allows model comparison |
| Calendar-day T | 7.19A | ✅ Correct — standard convention, auditable |
| Bisection IV solver | 7.19A | ✅ Correct — guaranteed convergence |
| lot_size immutability | 7.8F | ✅ Correct — preserves historical truth |

### 12.2 Decisions That Need Review

| Decision | Phase | Issue | Recommendation |
|----------|-------|-------|----------------|
| SQLite for production | 7.12 | Scaling limit | Accept for now; plan PostgreSQL migration |
| No ingestion status table | 7.14 | No failure tracking | Add `ingestion_log` table |
| Phase 7.18 temp endpoint | 7.18 | Still in main.py | Remove before committing |
| Trading hours in candle_config | 7.18 | Hardcoded, not from API | Accept — NSE hours rarely change |

---

## 13. Recommended Architecture

### 13.1 Database Layer

```
paper_journal.db (SQLite)
├── RAW tables (existing):
│   ├── nifty_candles
│   ├── option_candles
│   └── contract_specs
├── MODEL tables (existing):
│   └── option_greeks
├── META tables (NEW):
│   ├── ingestion_log       — per-batch ingestion status
│   └── ingestion_failures  — failed contracts for retry
└── EXISTING tables (untouched):
    ├── trades, legs, positions, ...
    └── gex_snapshots, iv_observations
```

### 13.2 Ingestion Pipeline

```
Daily Scheduler
    ↓
1. Ingestion Planner
   - Query latest timestamps per table
   - Determine missing data
   - Generate fetch tasks
    ↓
2. Index Candle Ingestion
   - Fetch from V3 Historical Candle API
   - 28-day chunks
   - ~30 API calls for full history
    ↓
3. Contract Metadata Ingestion
   - Fetch from V2 Expired Option Contracts API
   - ~99 API calls (one per expiry)
   - Idempotent upsert with lot_size immutability
    ↓
4. Option Candle Ingestion
   - Fetch from V2 Expired Historical Candle API
   - One API call per contract
   - ~500-2000 calls depending on strike universe
   - Rate-limited: 5 req/sec
    ↓
5. Greeks Reconstruction (optional, can be deferred)
   - Read raw data from DB
   - Calculate IV + Greeks
   - Persist to option_greeks
    ↓
6. Coverage Verification
   - Verify completeness
   - Log gaps
   - Report research-readiness
```

### 13.3 Recommended Tier 1 Dataset (from Phase 7.16)

| Parameter | Value |
|-----------|-------|
| Resolution | 3-minute |
| Historical depth | 6 months |
| Expiries | Monthly (6 expiries) |
| Strikes | ATM ± 20 (82 contracts/expiry) |
| Total contracts | ~492 |
| Total candles | ~4.0M |
| Storage | ~1 GB |
| API calls | ~500 |
| Runtime | ~100 seconds at 5 req/sec |

---

## 14. Files Changed (This Phase)

### 14.1 Files Created

| File | Purpose |
|------|---------|
| `docs/PHASE_7_20_HISTORICAL_DATA_ARCHITECTURE_AUDIT.md` | This document |

### 14.2 Files Modified

**None.** This is a read-only audit.

### 14.3 Files That Need Modification (Recommended)

| File | Change | Priority |
|------|--------|----------|
| `backend/app/db.py` | Absolute DB path resolution | **CRITICAL** |
| `backend/app/main.py` | Remove phase718_audit router | Medium |
| `backend/app/routers/phase718_audit.py` | Delete file | Medium |
| `backend/app/config.py` | Add INGESTION_LOGGING config | Low |

---

## 15. Test Results

| Suite | Tests | Result |
|-------|------:|--------|
| Full backend | 1,693 | All pass |
| Full frontend | 1,357 | All pass |
| **Total** | **3,050** | **All pass** |

### Protected Files — Zero Diff

- Frontend: **ZERO changes**
- GEX calculations: **Untouched**
- IV calculations: **Untouched**
- Research engine: **Untouched**
- Auth/OAuth: **Untouched**
- Phase 7.1–7.19B: **Untouched**

---

## 16. Scope Audit

### Modified Tracked Files (from `git diff --stat HEAD`)

```
backend/app/config.py    |   1 +
backend/app/main.py      |   7 +-
backend/app/models.py    | 175 +++
backend/app/services/nifty_candles.py | 2 +-
backend/app/services/upstox.py        | 172 +++
```

### Untracked New Files (79 total)

Backend services: 12 new files
Backend tests: 16 new files
Backend tools: 6 new files
Docs: 12 new files
Screenshots: 33 files

### Protected Areas

| Area | Status |
|------|--------|
| Frontend code | Zero diff |
| GEX calculations | Untouched |
| IV calculations | Untouched |
| Research engine | Untouched |
| Auth/OAuth | Untouched |
| Broker integrations | Untouched |

---

## 17. Deployment Status

- **Commit:** NO
- **Push:** NO
- **Deploy:** NO
- **Large backfill:** NO
- **Live API calls during audit:** NO

---

## 18. Recommended Phase 7.21 Plan

Based on this audit, Phase 7.21 should:

1. **Fix the absolute database path** (Priority 1)
2. **Remove the temporary phase718_audit endpoint**
3. **Add an `ingestion_log` table** for tracking backfill status
4. **Re-populate contract_specs** from live Upstox API (small, fast)
5. **Re-populate NIFTY index candles** for 6 months (small, fast)
6. **Verify data survives server restart**
7. **Then** proceed with Tier 1 backfill

Estimated Phase 7.21 effort: Small (1-2 hours of implementation + testing).

---

*This document is a read-only architecture audit. No production logic was modified. No commits, pushes, or deployments were performed.*
