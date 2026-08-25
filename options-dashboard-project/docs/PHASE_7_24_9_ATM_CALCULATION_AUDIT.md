# Phase 7.24.9 — ATM Calculation & Universe Selection Audit

**Date:** 2026-08-25
**Scope:** Audit of `_calculate_historical_atm()`, `_filter_by_universe()`, and the ATM_10 universe selection pipeline
**Status:** AUDIT ONLY — no production code modified

---

## Executive Summary

The ATM_10 universe selection has **two critical bugs** that together silently corrupt the entire historical backfill universe:

1. **Wrong reference price (P0):** `_calculate_historical_atm()` uses the last NIFTY candle *before* the expiry date (typically the previous trading day's close) instead of the first candle *on* the expiry date (the day's opening price). This produces the **wrong ATM strike for 23 of 25 expiries** (92% error rate).

2. **Incomplete NIFTY candle coverage (P0):** NIFTY 3-minute candles only exist for 2026-02-26 through 2026-08-24 (15,000 candles). The contract registry spans 2024-10-03 through 2026-08-18 (99 expiries). **74 of 99 expiries (74.7%) have no NIFTY candle data at all**, making ATM calculation impossible for them.

**Impact:** The 1,050 instruments selected by `run_backfill.py --dry-run --options --universe ATM_10` are drawn from the 25 expiries with NIFTY coverage, but the ATM reference for 23 of those 25 expiries is wrong. This means the selected strikes are offset from the true ATM — in some cases by 500+ points (10+ strike increments for NIFTY's 50-point spacing).

**Good news:** Zero option candles have been downloaded. No data has been corrupted. The fix is purely algorithmic.

---

## Current Architecture

### ATM Calculation Flow

```
BackfillOrchestrator._filter_by_universe(specs, "ATM_10")
  │
  ├── Group specs by expiry
  │
  ├── For each expiry:
  │     │
  │     └── _calculate_historical_atm(expiry)
  │           │
  │           ├── Find NIFTY candle with open_time <= expiry_date  ← BUG #1
  │           │   (uses LAST candle BEFORE expiry = prev day's close)
  │           │
  │           ├── ref_price = candle.open
  │           │
  │           ├── Find all strikes in contract_specs for this expiry
  │           │
  │           └── return strike closest to ref_price
  │
  ├── ATM ± 10 strikes from the strike list
  │
  └── Select all CE + PE instruments at those strikes
```

### Data Flow

```
NIFTY Candle Storage:
  - Table: nifty_candles
  - Timestamps: naive IST (Asia/Kolkata)
  - Interval: 3min only
  - Range: 2026-02-26 09:15:00 to 2026-08-24 15:27:00
  - Count: 15,000 candles

Contract Registry:
  - Table: contract_specs
  - Count: 20,584 instruments
  - Expiries: 99 (2024-10-03 to 2026-08-18)
  - Underlying: NIFTY only

Option Candles:
  - Table: option_candles
  - Count: 0 (none downloaded yet)
```

---

## Bug #1: Wrong Reference Price for ATM Calculation

### The Code

File: `app/services/backfill_orchestrator.py`, method `_calculate_historical_atm()`:

```python
nifty_row = self.db.execute(
    select(NiftyCandle.open_time, NiftyCandle.open)
    .where(NiftyCandle.symbol == NIFTY_SYMBOL)
    .where(NiftyCandle.interval == DEFAULT_INTERVAL_STR)  # "3min"
    .where(NiftyCandle.open_time <= datetime.combine(exp_date, datetime.min.time()))
    .order_by(NiftyCandle.open_time.desc())
    .limit(1)
).first()
```

### What This Does

For expiry `2026-03-02`, this query finds the last 3-minute candle with `open_time <= 2026-03-02 00:00:00`. Since trading starts at 09:15, this returns the **last candle of the previous trading day** (2026-02-27 15:27:00, open=25169.8), not the first candle of the expiry day.

### What It Should Do

The ATM strike for an expired option contract should be determined by the NIFTY opening price **on the expiry date itself** — the first 3-minute candle at 09:15:00 on 2026-03-02, which has open=24659.25.

### Empirical Evidence

| Expiry     | Current Ref (prev close) | Correct Ref (day open) | Price Diff | ATM (current) | ATM (correct) | Wrong? |
|------------|------------------------:|-----------------------:|-----------:|---------------:|---------------:|:------:|
| 2026-03-02 |              25,169.80 |             24,659.25 |      510.5 |         25,150 |         24,650 | **YES** |
| 2026-03-10 |              24,008.20 |             24,280.80 |      272.6 |         24,000 |         24,300 | **YES** |
| 2026-03-17 |              23,346.10 |             23,493.20 |      147.1 |         23,350 |         23,500 | **YES** |
| 2026-03-24 |              22,490.00 |             22,878.50 |      388.5 |         22,500 |         22,900 | **YES** |
| 2026-03-30 |              22,812.70 |             22,549.70 |      263.0 |         22,800 |         22,550 | **YES** |
| 2026-04-07 |              22,967.50 |             22,838.70 |      128.8 |         22,950 |         22,850 | **YES** |
| 2026-04-13 |              24,055.10 |             23,589.60 |      465.5 |         24,050 |         23,600 | **YES** |
| 2026-04-21 |              24,335.20 |             24,374.50 |       39.3 |         24,350 |         24,350 | no     |
| 2026-04-28 |              24,089.30 |             24,049.90 |       39.4 |         24,100 |         24,050 | **YES** |
| 2026-05-05 |              24,127.90 |             24,052.60 |       75.3 |         24,150 |         24,050 | **YES** |
| 2026-05-12 |              23,812.60 |             23,722.60 |       90.0 |         23,800 |         23,700 | **YES** |
| 2026-05-19 |              23,648.20 |             23,675.30 |       27.0 |         23,650 |         23,700 | **YES** |
| 2026-05-26 |              24,042.90 |             24,004.10 |       38.8 |         24,050 |         24,000 | **YES** |
| 2026-06-02 |              23,374.70 |             23,229.20 |      145.5 |         23,350 |         23,250 | **YES** |
| 2026-06-09 |              23,093.50 |             23,259.00 |      165.5 |         23,100 |         23,250 | **YES** |
| 2026-06-16 |              23,847.00 |             23,923.90 |       77.0 |         23,850 |         23,900 | **YES** |
| 2026-06-23 |              24,085.70 |             24,071.30 |       14.4 |         24,100 |         24,050 | **YES** |
| 2026-06-30 |              23,958.80 |             24,032.00 |       73.3 |         23,950 |         24,050 | **YES** |
| 2026-07-07 |              24,436.40 |             24,464.50 |       28.0 |         24,450 |         24,450 | no     |
| 2026-07-14 |              24,204.00 |             24,068.00 |      136.0 |         24,200 |         24,050 | **YES** |
| 2026-07-21 |              24,244.50 |             24,216.00 |       28.5 |         24,250 |         24,200 | **YES** |
| 2026-07-28 |              24,001.10 |             23,971.20 |       29.8 |         24,000 |         23,950 | **YES** |
| 2026-08-04 |              24,573.30 |             24,703.90 |      130.6 |         24,550 |         24,700 | **YES** |
| 2026-08-11 |              24,560.20 |             24,575.10 |       14.9 |         24,550 |         24,600 | **YES** |
| 2026-08-18 |              24,339.80 |             24,223.85 |      116.0 |         24,350 |         24,200 | **YES** |

**Result: 23 of 25 expiries (92%) have the wrong ATM strike.**

### Impact on ATM_10 Universe

For NIFTY's 50-point strike spacing, a wrong ATM means the entire ±10 strike window shifts:

- ATM wrong by 1 strike (50 points): 2 of 21 selected strikes are wrong
- ATM wrong by 2 strikes (100 points): 4 of 21 selected strikes are wrong
- ATM wrong by 3+ strikes (150+ points): 6+ of 21 selected strikes are wrong

In the worst case (2026-03-02, 510-point difference = ~10 strikes), the entire selected window is offset. The backfill would download candles for strikes 24,650–25,650 when it should download 24,150–25,150.

---

## Bug #2: Incomplete NIFTY Candle Coverage

### The Gap

| Metric | Value |
|--------|-------|
| Contract registry expiries | 99 (2024-10-03 to 2026-08-18) |
| NIFTY candle range | 2026-02-26 to 2026-08-24 |
| Expiries with NIFTY data | 25 (2026-03-02 to 2026-08-18) |
| Expiries without NIFTY data | **74 (74.7%)** |
| Missing date range | 2024-10-03 to 2026-02-25 (~16 months) |

### Why It Matters

For the 74 expiries without NIFTY candle data, `_calculate_historical_atm()` returns `None`, and `_filter_by_universe()` silently skips the entire expiry. The dry-run logs 74 "Cannot determine ATM" warnings but proceeds with only the 25 working expiries.

This means:
- **7,657 instruments** (from 74 skipped expiries) are excluded from the ATM_10 universe
- These instruments **cannot be downloaded** without first backfilling NIFTY candles for the missing period
- The historical analytical coverage is limited to ~6 months instead of the full ~22 months of contract history

### NIFTY Candle Storage Details

- All 15,000 candles are 3-minute interval
- No daily, weekly, or other interval candles are stored
- Timestamps are naive IST (correctly normalized via `to_ist_naive()`)
- Each trading day has exactly 125 candles (09:15 to 15:27, 3-min intervals)
- Storage convention is correct per Phase 7.24.4

---

## Root Cause Analysis

### Bug #1: Wrong `<=` Comparison

The query uses `NiftyCandle.open_time <= datetime.combine(exp_date, datetime.min.time())` which evaluates to `open_time <= 2026-03-02 00:00:00`. Since the earliest candle on 2026-03-02 is at 09:15:00, this always returns the **last candle of the previous trading day**.

**Fix:** Change the comparison to find the first candle **on** the expiry date:

```python
# Find the first NIFTY candle on the expiry date
nifty_row = self.db.execute(
    select(NiftyCandle.open_time, NiftyCandle.open)
    .where(NiftyCandle.symbol == NIFTY_SYMBOL)
    .where(NiftyCandle.interval == DEFAULT_INTERVAL_STR)
    .where(NiftyCandle.open_time >= datetime.combine(exp_date, datetime.min.time()))
    .where(NiftyCandle.open_time < datetime.combine(exp_date + timedelta(days=1), datetime.min.time()))
    .order_by(NiftyCandle.open_time.asc())
    .limit(1)
).first()
```

### Bug #2: Missing NIFTY Historical Data

The NIFTY backfill (`run_nifty()`) defaults to 180 days lookback, and only the most recent period was backfilled. The Upstox historical candle API supports going back much further.

**Fix:** Backfill NIFTY candles for the full contract history range (2024-10-01 to present) before re-running the ATM universe selection.

---

## Quantified Impact

### Current ATM_10 Universe (with bugs)

| Metric | Value |
|--------|-------|
| Total contract specs | 20,584 |
| Expiries in registry | 99 |
| Expiries with NIFTY data | 25 |
| Expiries skipped | 74 (74.7%) |
| Instruments selected | 1,050 |
| Instruments with wrong ATM | ~966 (from 23 wrong expiries) |
| Instruments with correct ATM | ~84 (from 2 correct expiries) |

### Projected ATM_10 Universe (after fix)

| Metric | Value |
|--------|-------|
| Total contract specs | 20,584 |
| Expiries in registry | 99 |
| Expiries with NIFTY data (after NIFTY backfill) | 99 |
| Expiries skipped | 0 |
| Expected instruments selected | ~4,158 |
| Instruments with correct ATM | ~4,158 (100%) |

---

## What Is NOT Broken

The following components are **correctly implemented** and should not be changed:

1. **`market_time.py` / `to_ist_naive()`** — The IST timestamp conversion is correct. All NIFTY and option candle timestamps are properly stored as naive IST.

2. **`candle_ingestion.py` / `normalize_candles()`** — The Upstox API response parsing and normalization is correct.

3. **`nifty_candles.py` / `record_candles()`** — The idempotent upsert logic is correct. No duplicates are created.

4. **`option_candles.py` / `record_option_candles()`** — The option candle persistence is correct. OHLCV/OI immutability is maintained.

5. **`ContractSpec` model** — The complete contract metadata is correctly stored and preserved.

6. **`OptionCandle` model** — The unique constraint on `(instrument_key, interval, open_time)` prevents duplicates correctly.

7. **`IngestionCheckpoint` model** — The checkpoint/resume mechanism is correctly implemented.

8. **The ATM ± N strike selection logic** — Once the reference price is correct, the strike selection (find closest strike, take ±N strikes from that index) is correct.

9. **CE/PE symmetry** — The selection correctly picks both CE and PE for each selected strike.

10. **The `_filter_by_universe()` grouping** — Grouping by expiry and processing each independently is the correct approach.

---

## Files Involved

| File | Role | Bug? |
|------|------|:----:|
| `app/services/backfill_orchestrator.py` | `_calculate_historical_atm()` — lines ~340-375 | **BUG #1** |
| `app/services/backfill_orchestrator.py` | `_filter_by_universe()` — lines ~300-340 | OK (depends on ATM) |
| `app/services/backfill_orchestrator.py` | `run_nifty()` — NIFTY backfill defaults | **BUG #2** (insufficient lookback) |
| `run_backfill.py` | CLI entry point | OK |
| `app/services/candle_ingestion.py` | NIFTY candle normalization | OK |
| `app/services/nifty_candles.py` | NIFTY candle persistence | OK |
| `app/services/option_candles.py` | Option candle persistence | OK |
| `app/models.py` | Database models | OK |
| `app/utils/market_time.py` | Timestamp utilities | OK |

---

## Recommended Fix Sequence

### Step 1: Backfill NIFTY candles for full history

```bash
# Backfill NIFTY candles from 2024-10-01 to present
python run_backfill.py --index --start-date 2024-10-01
```

This fills the 16-month gap and enables ATM calculation for all 99 expiries.

### Step 2: Fix `_calculate_historical_atm()` reference price

Change the query from `open_time <= expiry_date` to `open_time >= expiry_date AND open_time < expiry_date + 1 day`, ordered ascending, limit 1.

### Step 3: Verify ATM_10 universe selection

```bash
# Should now select ~4,158 instruments from all 99 expiries
python run_backfill.py --dry-run --options --universe ATM_10
```

### Step 4: Run the backfill

```bash
python run_backfill.py --options --universe ATM_10 --concurrency 3
```

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Wrong ATM causes wrong strike selection | **P0** | Fix reference price query |
| 74 expiries silently skipped | **P0** | Backfill NIFTY candles for full history |
| Existing data corrupted | None | Zero option candles exist; no data to corrupt |
| NIFTY backfill takes too long | Low | NIFTY is a single instrument; even daily candles for 22 months = ~480 requests |
| API rate limiting during NIFTY backfill | Low | Single instrument; use existing chunk logic |

---

## Acceptance Criteria

This audit is complete when:

- [x] ATM calculation algorithm documented and traced
- [x] Wrong reference price identified and quantified (23/25 expiries wrong)
- [x] Missing NIFTY coverage identified and quantified (74/99 expiries missing)
- [x] Impact on universe selection measured (1,050 vs expected 4,158)
- [x] No existing data has been modified
- [x] Fix sequence documented
- [x] No production code changed in this audit
