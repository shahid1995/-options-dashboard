# Phase 7.21 — Persistent Database Foundation and Recovery

**Date:** 2026-08-24
**Status:** PASS
**Scope:** Fix database persistence, remove temp endpoints, add health check

---

## 1. Root Cause

The production SQLite database used a relative file path:

```python
# BEFORE (db.py)
url = settings.DATABASE_URL or "sqlite:///./paper_journal.db"
```

This resolved to `paper_journal.db` in the **current working directory**. When the server, backfill tools, or CLI ran from different directories (e.g. `backend/` vs project root vs Freebuff restart), they created **separate empty databases** — silently destroying previously ingested data.

**Evidence:** The production `paper_journal.db` file was 2MB (schema/index overhead only) with zero rows in all 19 tables, despite Phase 7.15/7.18 having verified 4,127 contract specs and 750 option candles.

---

## 2. Architectural Fix

Replaced the relative path with a deterministic absolute path derived from the source file location:

```python
# AFTER (db.py)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "paper_journal.db")

def _engine():
    if settings.DATABASE_URL:
        url = settings.DATABASE_URL
    else:
        url = f"sqlite:///{_DEFAULT_DB_PATH}"
    ...
```

The `__file__` in `app/db.py` always resolves to `backend/app/db.py`, so `dirname(dirname(__file__))` always resolves to `backend/` — regardless of CWD.

---

## 3. Database Path Before/After

| Aspect | Before | After |
|--------|--------|-------|
| Path | `sqlite:///./paper_journal.db` | `sqlite:///C:\...\backend\paper_journal.db` |
| CWD-dependent | YES | NO |
| Consistent across processes | NO | YES |
| Consistent across CWDs | NO | YES |

---

## 4. Files Changed

### 4.1 Modified (4 tracked files)

| File | Change |
|------|--------|
| `backend/app/db.py` | Absolute path resolution + `get_database_path()` + `check_database_health()` |
| `backend/app/main.py` | Removed temporary phase718_audit router (−4 lines) |
| `backend/app/tools/candle_backfill.py` | Import `_DEFAULT_DB_PATH` from `db.py` instead of hardcoded relative path |
| `backend/app/tools/option_candle_backfill.py` | Same — import centralized path |
| `backend/app/tools/contract_metadata_backfill.py` | Same — import centralized path (was `options_candles.db`) |

### 4.2 Deleted

| File | Reason |
|------|--------|
| `backend/app/routers/phase718_audit.py` | Temporary Phase 7.18 dev endpoint, no longer needed |

### 4.3 Created (2 files)

| File | Purpose |
|------|---------|
| `backend/tests/test_phase721_persistence.py` | 27 persistence proof tests |
| `docs/PHASE_7_21_PERSISTENT_DATABASE_FOUNDATION.md` | This report |

---

## 5. Persistence Test Results

All 27 tests pass:

| Test Category | Tests | Result |
|---------------|------:|--------|
| Path determinism | 7 | All pass |
| Two sessions same data | 1 | Pass |
| Two engines same data | 1 | Pass |
| Engine recreation | 2 | All pass |
| Backfill tool paths | 4 | All pass |
| Health check | 6 | All pass |
| Temp endpoint removed | 3 | All pass |
| Production DB file | 3 | All pass |
| **Total** | **27** | **All pass** |

Key proofs:

- `test_path_independent_of_cwd` — changing CWD to `tempfile.gettempdir()` does not change the database path
- `test_path_from_project_root` — launching from project root still resolves to `backend/paper_journal.db`
- `test_independent_engines_same_file` — two separately created engines see the same data
- `test_dispose_recreate_read` — dispose engine, recreate, data survives
- `test_cwd_change_engine_recreation` — change CWD + recreate engine, data survives
- `test_backfill_tools_all_use_same_path` — all 3 backfill tools resolve to the same URL

---

## 6. Database Health Check

The `check_database_health()` function reports:

```json
{
  "database_path": "C:\\...\\backend\\paper_journal.db",
  "file_exists": true,
  "file_size_bytes": 2097152,
  "accessible": true,
  "tables_present": ["contract_specs", "nifty_candles", "option_candles", "option_greeks"],
  "tables_missing": [],
  "row_counts": {
    "nifty_candles": 0,
    "contract_specs": 0,
    "option_candles": 0,
    "option_greeks": 0
  },
  "oldest_record": null,
  "newest_record": null
}
```

All 4 historical tables are present. Row counts are 0 (data was lost before the fix — Phase 7.22 will re-populate).

---

## 7. Temporary Endpoint Cleanup

| Item | Status |
|------|--------|
| `phase718_audit.py` | DELETED |
| Router registration in `main.py` | REMOVED |
| `/dev/phase718-audit` route | GONE |
| Import test | Confirmed not importable |
| Reusable services preserved | `strike_selection.py`, `option_candles.py`, `option_candle_backfill.py`, `historical_greeks.py` — all untouched |

---

## 8. Other Path Fixes Discovered

The audit found **three** different hardcoded database paths:

| File | Old Path | Issue |
|------|----------|-------|
| `db.py` | `sqlite:///./paper_journal.db` | Relative to CWD |
| `candle_backfill.py` | `sqlite:///./paper_journal.db` | Same relative path |
| `option_candle_backfill.py` | `sqlite:///./paper_journal.db` | Same relative path |
| `contract_metadata_backfill.py` | `sqlite:///options_candles.db` | **Different filename entirely!** |

All three backfill tools now import `_DEFAULT_DB_PATH` from `db.py` and use the same absolute path.

---

## 9. Regression Test Results

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.21 persistence | 27 | All pass |
| Phase 7.20 architecture | 16 | All pass |
| Full backend | 1,736 | All pass |
| Full frontend | 1,357 | All pass |
| **Total** | **3,093** | **All pass** |

---

## 10. Protected-File Scope Audit

| Area | Status |
|------|--------|
| Frontend (`frontend/`) | **ZERO diff** |
| GEX calculations | **Untouched** |
| IV calculations | **Untouched** |
| Research engine | **Untouched** |
| Auth/OAuth | **Untouched** |
| Broker integrations | **Untouched** |
| Phase 7.1–7.19B logic | **Untouched** |

The only tracked files modified are:
- `db.py` (database path fix + health check)
- `main.py` (removed temp endpoint)
- `config.py` (from Phase 7.8, no new changes)
- `models.py` (from Phase 7.19B, no new changes)
- `upstox.py` (from Phase 7.8A, no new changes)
- `nifty_candles.py` (cosmetic, no logic change)
- 3 backfill tools (path import change only)

---

## 11. Deployment Status

- **Commit:** NO
- **Push:** NO
- **Deploy:** NO
- **Large backfill:** NO

---

## 12. Phase 7.22 Readiness

With the database path fix in place, Phase 7.22 can now safely:

1. Re-populate `contract_specs` from live Upstox API
2. Re-populate `nifty_candles` for 6 months
3. Verify data survives server restart
4. Proceed with Tier 1 option candle backfill

The database will persist across server restarts, CLI invocations, and CWD changes.

---

*No commits, pushes, or deployments were performed.*
