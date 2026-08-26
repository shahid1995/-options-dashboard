# Phase 7.13 — Option Candle Persistence Layer

**Date:** 2025-08-23
**Status:** Complete

---

## What Was Implemented

### 1. OptionCandle Model (`models.py`)

New SQLAlchemy model for historical expired option/future contract candles:

- **Table:** `option_candles`
- **Unique key:** `(instrument_key, interval, open_time)`
- **Fields:** instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at
- **Identity:** `instrument_key` is the canonical Upstox identity linking to `contract_specs`

### 2. Persistence Service (`services/option_candles.py`)

Complete persistence layer with:

| Function | Purpose |
|---|---|
| `normalize_option_candle()` | Convert raw Upstox candle array to dict (preserves OI) |
| `normalize_option_candles()` | Batch normalization |
| `record_option_candles()` | Idempotent upsert with transaction safety |
| `count_option_candles()` | Count with optional instrument_key filter |
| `get_option_candles()` | Retrieve ordered by time |
| `get_distinct_instruments()` | List all instruments with data |

### 3. Tests (`tests/test_option_candles.py`)

27 comprehensive tests covering:

- Basic insert and read-back
- Idempotent insert (no duplicates)
- Same batch twice (no duplicates)
- Different instruments at same timestamp
- Different intervals
- CE/PE coexistence
- Lot-size independence
- Empty batches
- Malformed records
- Timestamp normalization (IST→UTC)
- Z-suffix handling
- OI preservation
- Volume preservation
- Query helpers
- Transaction safety

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Separate `option_candles` table | Clean separation from `nifty_candles`; different lifecycle and fields |
| OI preserved (unlike index candles) | Critical for option analytics (GEX, exposure) |
| lot_size NOT in candle table | lot_size lives in `contract_specs`; looked up by instrument_key |
| `instrument_key` as identity | Canonical Upstox identifier; handles all contract dimensions |
| SQLite upsert for idempotency | Same as `nifty_candles.record_candles()` pattern |
| Raw data immutable | Derived analytics (Greeks) computed separately |

---

## Test Results

| Suite | Tests | Result |
|---|---|---|
| Phase 7.13 option candles | 27 | All pass |
| Phase 7.8/7.9/7.12 tests | 352 | All pass |
| Full backend | 1,489 | All pass |
| Full frontend | 1,357 | All pass |

## Protected Files

All untouched: frontend, GEX, IV, auth, brokers, candle pipeline.
