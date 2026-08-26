# Phase 7.17 — Historical Strike/Expiry Selection

**Date:** 2025-08-23  
**Status:** Implementation Complete  
**Predecessors:** Phase 7.16 (Backfill Planning)

---

## Executive Summary

Phase 7.17 implements the historical strike/expiry selection algorithm for Tier 1 backfill. The key innovation is **historical ATM calculation** — determining the ATM strike from the stored NIFTY index candle data corresponding to the historical period being backfilled, NOT from the current NIFTY price.

**Key results:**
- Historical ATM calculation from stored nifty_candles
- Strike rounding to 25-point NIFTY intervals
- ATM ± 20 strike universe (41 strikes × CE/PE = 82 contracts)
- Monthly expiry selection from contract_specs
- Different historical lot sizes preserved correctly
- 36 comprehensive synthetic tests

---

## 1. Algorithm

### 1.1 Historical ATM Calculation

**Critical requirement:** ATM is calculated from the historical NIFTY index price, NOT the current price.

```
For a given target_date:
  1. Query nifty_candles for the first candle on target_date
     (09:15 IST opening candle)
  2. Extract the open price as the ATM reference
  3. Round to nearest 25-point strike interval
  4. If no candles for target_date, look back up to 5 days
     (handles weekends/holidays)
  5. If no data found, return None (skip this expiry)
```

**Why the opening candle?**
- Represents the NIFTY level at the start of the trading day
- Consistent reference point for strike selection
- Available in stored nifty_candles (no additional API calls)

**Example:**
- NIFTY open on 2024-10-28: 24,523
- Rounded to nearest 25: 24,525
- ATM strike: 24,525

### 1.2 Strike Universe Selection

```
For ATM = 24,525:
  ATM - 20 × 25 = 24,025
  ATM - 19 × 25 = 24,050
  ...
  ATM           = 24,525
  ...
  ATM + 19 × 25 = 25,000
  ATM + 20 × 25 = 25,025

  Total: 41 strikes
```

**Strike interval:** 25 points (standard NIFTY option spacing)

**Range:** ATM ± 20 strikes = ± 500 points from ATM

### 1.3 Contract Universe Selection

```
For each strike in universe:
  For each type in [CE, PE]:
    Look up contract in contract_specs
    If found: include in universe
    If missing: log warning, skip

  Result: up to 82 contracts per expiry
```

### 1.4 Monthly Expiry Selection

```
For the requested date range:
  1. Query contract_specs for all expiry dates
  2. Group by year-month
  3. Keep only the latest expiry per month
  4. Return sorted list

  Result: ~6 monthly expiries for 6-month window
```

---

## 2. Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Input: Historical date range (e.g., 2024-10-01 to 2025-04-01)  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Select monthly expiries from contract_specs            │
│  → ["2024-10-31", "2024-11-28", "2024-12-26", ...]            │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: For each expiry, calculate historical ATM             │
│  → Query nifty_candles for opening price on expiry date         │
│  → Round to nearest 25-point interval                          │
│  → Example: 24,523 → 24,525                                    │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Select strike universe (ATM ± 20)                    │
│  → 41 strikes × 25 points = ± 500 points from ATM             │
│  → Example: 24,025 to 25,025                                   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: Select contracts (CE + PE for each strike)            │
│  → Look up in contract_specs                                   │
│  → Preserve instrument_key, lot_size, metadata                 │
│  → Up to 82 contracts per expiry                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Output: Complete Tier 1 universe                              │
│  → ~6 monthly expiries                                         │
│  → ~41 strikes per expiry                                      │
│  → ~82 contracts per expiry                                    │
│  → ~492 total contracts                                        │
│  → Different lot sizes preserved per expiry                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Design Decision: Fixed vs Dynamic ATM

### Question

Should ATM be:
- **A. Fixed once per expiry** (based on the first/official underlying price for that expiry period)
- **B. Recalculated by trading day** (allowing the strike universe to move with NIFTY)

### Analysis

| Factor | Fixed ATM | Dynamic ATM |
|---|---|---|
| **GEX accuracy** | Good — ATM ± 20 covers the relevant range | Better — tracks actual ATM movement |
| **Storage efficiency** | Better — fixed strike set per expiry | Worse — more contracts to fetch |
| **API requests** | ~492 contracts (6 months) | ~1,500+ contracts (6 months) |
| **Implementation complexity** | Simple | Complex |
| **IV reconstruction** | Good — strikes available throughout | Better — ATM always centered |
| **Backtesting** | Acceptable — may miss extreme moves | Better — captures full range |

### Recommendation

**Option A: Fixed ATM per expiry**

**Rationale:**
1. **GEX is dominated by the nearest 20 strikes** — far-OTM strikes contribute minimal GEX
2. **NIFTY rarely moves >500 points in a week** — ATM ± 20 captures most scenarios
3. **Storage efficiency** — 492 contracts vs 1,500+ for dynamic ATM
4. **API cost** — 3× fewer API calls
5. **Simplicity** — easier to implement, test, and debug
6. **Sufficient for research** — 6 months of fixed-ATM data provides excellent GEX patterns

**When to reconsider:** If research shows that NIFTY frequently moves >500 points within a weekly expiry, switch to dynamic ATM.

---

## 4. Verified Facts

| Item | Status | Source |
|---|---|---|
| NIFTY strike interval is 25 points | VERIFIED | Live API data |
| ATM ± 20 covers ± 500 points | VERIFIED | Strike universe analysis |
| Monthly expiries available from Oct 2024 | VERIFIED | Phase 7.9 live |
| Historical lot_size=25 (Oct 2024) preserved | VERIFIED | Phase 7.15 pilot |
| Historical lot_size=75 (Apr 2025) preserved | VERIFIED | Phase 7.9 live |
| Different lot sizes coexist by instrument_key | VERIFIED | Phase 7.15 pilot |
| Index candles available for ATM calculation | VERIFIED | Phase 7.8 pipeline |
| ~200-230 contracts per monthly expiry | VERIFIED | Phase 7.15 pilot |

---

## 5. Assumptions

| Assumption | Risk | Validation Plan |
|---|---|---|
| Opening candle price is representative | Low | Standard for intraday analysis |
| 25-point strike interval consistent historically | Low | Verify with 2022 data |
| Monthly expiries are sufficient for GEX | Low | Compare with weekly if needed |
| ATM ± 20 captures most GEX activity | Low | Verify in Phase 7.18 backfill |
| Lookback of 5 days is sufficient | Low | Covers weekends/holidays |

---

## 6. Examples Using Verified 2024-10-31 Data

### Example 1: ATM Calculation

```
Target date: 2024-10-31
NIFTY opening candle on 2024-10-28: 24,523
Rounded to nearest 25: 24,525
ATM strike: 24,525
```

### Example 2: Strike Universe

```
ATM = 24,525
Range: ATM ± 20 strikes

Lowest strike: 24,525 - 20 × 25 = 24,025
Highest strike: 24,525 + 20 × 25 = 25,025

Total strikes: 41
```

### Example 3: Contract Universe

```
For strike 24,500 (within universe):
  CE: NSE_FO|24500|2024-10-31|CE (lot_size=25)
  PE: NSE_FO|24500|2024-10-31|PE (lot_size=25)

For strike 24,525 (ATM):
  CE: NSE_FO|24525|2024-10-31|CE (lot_size=25)
  PE: NSE_FO|24525|2024-10-31|PE (lot_size=25)

Total contracts: 82 (41 CE + 41 PE)
```

### Example 4: Lot-Size Preservation

```
October 2024 contracts: lot_size=25
April 2025 contracts: lot_size=75

Both coexist in the universe with their respective lot sizes.
No current lot size is substituted.
```

---

## 7. API

### 7.1 Main Entry Point

```python
from app.services.strike_selection import select_tier1_universe

selection = select_tier1_universe(
    db=session,
    start_date="2024-10-01",
    end_date="2025-04-01",
    underlying="NIFTY",
    strike_range=20,
)

# selection["monthly_expiries"] → list of expiry info dicts
# selection["total_contracts"] → ~492
```

### 7.2 Individual Functions

```python
# Calculate historical ATM
atm = get_historical_atm(db, "2024-10-31")

# Select strike universe
strikes = select_strike_universe(atm, range_size=20)

# Select contracts for an expiry
contracts = select_contract_universe(strikes, "2024-10-31", contract_specs)

# Select monthly expiries
expiries = select_monthly_expiries(db, "2024-10-01", "2025-04-01")

# Format report
report = format_selection_report(selection)
```

---

## 8. Test Coverage

### 8.1 Test Results

| Suite | Tests | Result |
|---|---|---|
| Phase 7.17 strike selection | 36 | All pass |
| Full backend | 1,542 | All pass |
| Full frontend | 1,357 | All pass |

### 8.2 Test Categories

| Category | Tests | Coverage |
|---|---|---|
| Strike rounding | 9 | Edge cases, intervals, negatives |
| Strike universe | 7 | Selection, sorting, centering |
| Historical ATM | 6 | Calculation, lookback, None handling |
| Contract universe | 3 | Selection, missing contracts, lot sizes |
| Monthly expiry | 5 | Selection, filtering, sorting |
| Tier 1 universe | 2 | End-to-end selection |
| Report formatting | 1 | Output format |
| Lot-size preservation | 3 | Invariants, different sizes, NULL |

---

## 9. Files Created/Modified

### Created (2)

| File | Purpose | Lines |
|---|---|---|
| `backend/app/services/strike_selection.py` | Historical ATM + strike/expiry selection | ~320 |
| `backend/tests/test_strike_selection.py` | 36 comprehensive tests | ~650 |

### Modified

**None.** This phase only adds new files.

---

## 10. Protected Files

All untouched: frontend, GEX, IV, auth, brokers, candle pipeline, contract metadata.

---

## 11. Next Steps

1. **Phase 7.18:** Execute Tier 1 backfill using the selection algorithm
2. **Phase 7.19:** Greeks reconstruction engine
3. **Phase 8:** Research engine integration

---

*This document describes the implementation. No backfill was performed, nothing was committed or deployed.*
