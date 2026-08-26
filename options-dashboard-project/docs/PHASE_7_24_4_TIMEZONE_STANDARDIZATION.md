# Phase 7.24.4 — Timestamp and Timezone Standardization

## Status: ✅ COMPLETE

## Objective

Eliminate the inconsistency where `nifty_candles` used naive IST while `option_candles` used naive UTC. Both tables now store **naive IST (Asia/Kolkata)** timestamps consistently.

## Root Cause

The original `normalize_candle_timestamp()` in `candle_ingestion.py` converted Upstox IST timestamps to naive UTC before storage. However, NIFTY candles were stored through a different path (`record_candles`) that happened to preserve the IST local time. This inconsistency caused the Historical Greeks engine to fail with 90% `INSUFFICIENT_DATA/NO_SPOT` because option timestamps (UTC) were compared against NIFTY timestamps (IST).

A compensating UTC→IST conversion was added in `historical_greeks.py` as a workaround. Phase 7.24.4 fixes the root cause.

## Permanent Convention

> **All persisted market-data candle timestamps are naive IST (Asia/Kolkata).**

- `nifty_candles.open_time` → naive IST
- `option_candles.open_time` → naive IST
- `option_greeks.open_time` → naive IST (derived from option_candles)

## Architecture

```
Upstox API (IST timestamps with +05:30 offset)
              │
              ▼
    to_ist_naive()          ← app/utils/market_time.py
              │
              ▼
    naive IST datetime
              │
              ▼
    SQLite / database
              │
              ▼
    Greeks alignment        ← direct comparison, no conversion needed
```

## Files Created

| File | Purpose |
|------|---------|
| `app/utils/__init__.py` | Package init |
| `app/utils/market_time.py` | Centralized timestamp utility (`to_ist_naive`, `is_market_hours`, `is_post_close`, `ist_naive_to_string`) |
| `tests/test_phase724_4_timezone_standardization.py` | 42 comprehensive tests |
| `docs/PHASE_7_24_4_TIMEZONE_STANDARDIZATION.md` | This document |

## Files Modified

| File | Change |
|------|--------|
| `app/services/candle_ingestion.py` | `normalize_candle_timestamp()` now produces naive IST via `to_ist_naive()` instead of naive UTC |
| `app/services/option_candles.py` | `normalize_option_candle()` now produces naive IST timestamps (no Z suffix) |
| `app/services/nifty_candles.py` | `record_candles()` now uses `to_ist_naive()` for timestamp parsing |
| `app/services/historical_greeks.py` | Removed compensating UTC→IST conversion; timestamps now align directly |
| `app/services/candle_validation.py` | `_is_market_session()` accepts naive IST directly |
| `app/services/candle_coverage.py` | `_utc_to_ist_minute()` / `_utc_to_date_ist()` handle naive IST directly |

## Existing Data Migration

**Not required.** The database was empty when Phase 7.24.4 was implemented. All existing test fixtures and the production ingestion pipeline now use the new IST convention.

## Test Coverage (42 tests)

| Category | Tests |
|----------|------:|
| A. UTC → IST conversion | 4 |
| B. IST-aware → naive IST | 3 |
| C. Already-naive IST passthrough | 2 |
| D. ISO string handling | 7 |
| E. DST-independent behavior | 4 |
| F. Both pipelines same convention | 4 |
| G. Post-close alignment | 3 |
| H. No future spot leakage | 1 |
| I. Greeks engine direct comparison | 1 |
| J. Raw data immutability | 1 |
| K. Idempotency | 2 |
| L. Database persistence | 2 |
| M. Trading session helpers | 9 |

## Regression

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.4 | 42 | All pass |
| Phase 7.24.3 | 50 | All pass |
| Phase 7.24.2 | 50 | All pass |
| Phase 7.24.1 | 35 | All pass |
| Full backend | 2,005 | All pass (4 skipped) |
| Full frontend | 1,357 | All pass |

## Key Changes

### Before (broken)
```python
# candle_ingestion.py
IST timestamp → naive UTC → stored in DB

# option_candles.py  
IST timestamp → naive UTC → stored in DB

# nifty_candles.py (accidental)
IST timestamp → naive IST → stored in DB

# historical_greeks.py (compensating)
option UTC timestamp + 5:30h → IST → align with NIFTY IST
```

### After (correct)
```python
# candle_ingestion.py
IST timestamp → naive IST → stored in DB

# option_candles.py
IST timestamp → naive IST → stored in DB

# nifty_candles.py
IST timestamp → naive IST → stored in DB

# historical_greeks.py (direct)
option IST timestamp → align with NIFTY IST (no conversion needed)
```

## Metrics

| Metric | Value |
|--------|-------|
| Real Upstox API calls | **0** |
| Historical data downloaded | **0** |
| Market-data rows modified | **0** |
| Database tables modified | **0** |

## Acceptance Criteria

- [x] One canonical timezone utility (`to_ist_naive`)
- [x] Both candle pipelines use it
- [x] Greeks engine no longer contains compensating UTC→IST conversion
- [x] No future spot leakage
- [x] Post-close alignment passes
- [x] Raw data remains immutable
- [x] All tests pass
- [x] No unnecessary API calls
- [x] No deployment/commit/push

---

**No real Upstox API calls were made during Phase 7.24.4.**
