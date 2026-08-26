# Phase 7.12 — Historical Data Schema & Backfill Engine Design

**Date:** 2025-08-23
**Status:** Design Complete (no implementation)
**Predecessors:** Phase 7.8 (pipeline), 7.9 (live verification), 7.10 (coverage analysis), 7.11 (POC)

---

## Executive Summary

This document designs the production-grade architecture for storing, backfilling, and consuming historical NIFTY option data. It covers database schema, backfill engine, data quality, Greeks reconstruction, and storage estimation.

**Key design principles:**
1. Raw Upstox market data is **immutable** — never overwritten after initial persistence
2. Derived analytics (Greeks, GEX) are **separate** from raw data
3. `instrument_key` is the identity — not today's contract specifications
4. The system must be **idempotent** and **resumable**
5. Historical lot_size is preserved exactly from the authoritative source

---

## 1. Database Schema Design

### 1.1 New Table: `option_candles`

Stores historical OHLCV candles for individual expired option/future contracts.

```sql
CREATE TABLE option_candles (
    id              INTEGER PRIMARY KEY,

    -- Identity — instrument_key links to contract_specs
    instrument_key  VARCHAR(64)  NOT NULL,
    interval        VARCHAR(8)   NOT NULL DEFAULT '3min',
    open_time       DATETIME     NOT NULL,

    -- OHLCV from Upstox
    open            FLOAT        NOT NULL,
    high            FLOAT        NOT NULL,
    low             FLOAT        NOT NULL,
    close           FLOAT        NOT NULL,
    volume          FLOAT        NOT NULL DEFAULT 0.0,
    open_interest   FLOAT        NOT NULL DEFAULT 0.0,

    -- Provenance
    source          VARCHAR(32)  NOT NULL DEFAULT 'UPSTOX_EXPIRED_CANDLE',
    fetched_at      DATETIME     NOT NULL,

    -- Uniqueness
    UNIQUE(instrument_key, interval, open_time)
);
```

**Index recommendations:**
- `instrument_key` (primary lookup for option chain reconstruction)
- `open_time` (temporal queries, coverage analysis)
- `(instrument_key, open_time)` composite (most common query pattern)

### 1.2 Relationship to Existing Tables

```
contract_specs                     option_candles
  instrument_key (PK) ◄────────── instrument_key (FK logical)
  underlying                       interval
  expiry                           open_time
  strike_price                     open, high, low, close
  instrument_type (CE/PE)          volume
  lot_size                         open_interest
  minimum_lot
  freeze_quantity
  ...

nifty_candles                      option_candles
  symbol (NIFTY)                   instrument_key
  interval                         interval
  open_time                        open_time
  open, high, low, close           open, high, low, close
  volume                           volume
                                   open_interest (NEW)
```

**Key relationships:**
- `option_candles.instrument_key` → `contract_specs.instrument_key` (metadata lookup)
- `nifty_candles.open_time` ↔ `option_candles.open_time` (underlying price alignment)
- **No foreign key constraint** — the two candle tables are independent pipelines

### 1.3 Why NOT Extend NiftyCandle

| Reason | Explanation |
|---|---|
| NiftyCandle has no `instrument_key` | It uses `symbol` (e.g., "NIFTY") which is the index, not individual options |
| NiftyCandle has no `open_interest` | Index candles don't have OI |
| Different lifecycle | Index candles are independently useful; option candles depend on contract metadata |
| Different volume semantics | Index candle volume ≠ option contract volume |
| Query patterns differ | Index: temporal; Option: by instrument + temporal |

**Decision:** Separate table. Clean separation of concerns.

---

## 2. Identity & Uniqueness

### 2.1 Unique Key

```
(instrument_key, interval, open_time)
```

**Why this works:**

| Dimension | Handled by |
|---|---|
| Different expiries | Different `instrument_key` (includes expiry in key) |
| Different strikes | Different `instrument_key` (includes strike in key) |
| CE vs PE | Different `instrument_key` (different instrument) |
| Different intervals | `interval` column |
| Different timestamps | `open_time` column |

**Example instrument_keys (from live verification):**
- `NSE_FO|48891|31-10-2024` — NIFTY 22250 PE, expiry 2024-10-31
- `NSE_FO|47983|17-04-2025` — NIFTY 20400 PE, expiry 2025-04-17

Each instrument_key uniquely identifies a specific historical contract. The same strike on a different expiry has a different instrument_key.

### 2.2 Why NOT Use (strike, expiry, type, interval, open_time)

The `instrument_key` is superior because:
- It's the Upstox canonical identifier
- It's what the Expired Historical Candle API accepts
- It's what `contract_specs` uses
- It avoids ambiguity (e.g., weekly vs monthly expiry with same strike)

---

## 3. Backfill Architecture

### 3.1 Pipeline Overview

```
┌─────────────────────────────────────────────────┐
│  Layer 0: Index Candle Backfill (NIFTY 50)       │
│  Already implemented (candle_backfill.py)        │
│  ~30 API calls for 3-year coverage               │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│  Layer 1: Contract Metadata Backfill             │
│  Already implemented (contract_metadata_backfill) │
│  ~99 API calls (one per expiry)                  │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│  Layer 2: Option Candle Backfill (NEW)           │
│  Expired Historical Candle API                   │
│  ~19,800 API calls (one per contract)            │
│  THIS IS THE PRIMARY FUTURE WORK                │
└─────────────────────────────────────────────────┘
```

### 3.2 Layer 2 Backfill Engine Design

#### Phase 2a: Expiry Discovery
```python
# Get all available expired expiries
expiries = await get_expired_expiries(token, NIFTY_INDEX_KEY)
# Returns: ["2024-10-03", "2024-10-10", ..., "2025-04-17"]
```

#### Phase 2b: Contract Discovery (per expiry)
```python
for expiry in expiries:
    contracts = await get_expired_option_contracts(token, NIFTY_INDEX_KEY, expiry)
    # Store metadata via upsert_contract_spec()
    # Filter: CE/PE, strikes around ATM, weekly/monthly
```

#### Phase 2c: Candle Retrieval (per contract)
```python
for contract in filtered_contracts:
    candles = await get_expired_historical_candles(
        token,
        expired_instrument_key=contract.instrument_key,
        interval="3minute",
        to_date=contract.expiry,
        from_date=contract.expiry,  # single day initially
    )
    # Normalize, validate, persist
```

#### Phase 2d: Checkpoint & Resume
```python
# Check which contracts already have candle data
completed = db.query(OptionCandle.instrument_key).distinct().all()
remaining = [c for c in all_contracts if c.instrument_key not in completed]
```

### 3.3 Rate-Limit Strategy

| Parameter | Value | Rationale |
|---|---|---|
| Requests per second | 5 | Well under 50/sec limit |
| Delay between requests | 200ms | Conservative, measured in POC |
| Delay after 429 | 2s minimum | Rate-limit recovery |
| Max retries | 3 | Bounded retry |
| Backoff multiplier | 2.0 | Exponential: 2s, 4s, 8s |
| Max backoff | 30s | Cap |

**Estimated throughput:** ~5 contracts/second × 3600 seconds/hour = ~18,000 contracts/hour.

### 3.4 Idempotency

The `record_option_candles()` function (to be implemented) uses SQLite upsert:

```sql
INSERT INTO option_candles (instrument_key, interval, open_time, ...)
VALUES (...)
ON CONFLICT(instrument_key, interval, open_time)
DO UPDATE SET open=excluded.open, high=excluded.high, ...
```

**Same candle ingested twice → no duplicate, existing row updated.**

### 3.5 Failure Recording

```sql
CREATE TABLE backfill_errors (
    id              INTEGER PRIMARY KEY,
    instrument_key  VARCHAR(64)  NOT NULL,
    error_type      VARCHAR(32)  NOT NULL,  -- 'API_ERROR', 'VALIDATION', 'TIMEOUT'
    error_message   TEXT         NOT NULL,
    http_status     INTEGER,
    attempt         INTEGER      NOT NULL DEFAULT 1,
    occurred_at     DATETIME     NOT NULL
);
```

Errors are recorded but do NOT block the backfill. Failed contracts are retried on the next backfill run.

---

## 4. Data-Quality Framework

### 4.1 Validation Rules

| Rule | Severity | Action |
|---|---|---|
| `open > 0` | HARD | Reject candle |
| `high >= max(open, close)` | HARD | Reject candle |
| `low <= min(open, close)` | HARD | Reject candle |
| `high >= low` | HARD | Reject candle |
| `volume >= 0` | HARD | Reject candle |
| `open_interest >= 0` | HARD | Reject candle |
| `timestamp is valid ISO 8601` | HARD | Reject candle |
| `volume == 0` | SOFT | Warn (valid for some contracts) |
| `open_interest == 0` | SOFT | Warn (possible data gap) |
| `range > 5% of close` | SOFT | Warn (abnormal but possible) |
| `timestamp out of order` | INFO | Log (API returns descending) |
| `duplicate timestamp` | SOFT | Deduplicate via upsert |

### 4.2 Coverage Analysis

Per-expiry coverage should track:
- Total contracts expected (from contract_specs)
- Contracts with candle data
- Contracts missing candle data
- Missing trading sessions per contract
- Incomplete sessions per contract

### 4.3 Research Readiness

| Status | Criteria |
|---|---|
| READY | >90% of contracts have complete candle data for the expiry |
| PARTIAL | 50–90% of contracts have candle data |
| NOT_READY | <50% or critical strikes missing |

---

## 5. Historical Resolution Analysis

### 5.1 Available Intervals

From the Upstox Expired Historical Candle API:
- 1minute, 3minute, 5minute, 15minute, 30minute, day

### 5.2 Storage Impact

| Interval | Candles/Day | Candles/Contract/Month | Total (19,800 contracts) | Storage |
|---|---|---|---|---|
| 1min | 375 | ~7,500 | ~148M | ~15 GB |
| **3min** | **125** | **~2,500** | **~49.5M** | **~5 GB** |
| 5min | 75 | ~1,500 | ~29.7M | ~3 GB |
| 15min | 25 | ~500 | ~9.9M | ~1 GB |
| 30min | 13 | ~260 | ~5.1M | ~0.5 GB |
| daily | 1 | ~20 | ~0.4M | ~0.04 GB |

### 5.3 Research Requirement Analysis

| Use Case | Minimum Interval | Preferred Interval | Reason |
|---|---|---|---|
| **GEX calculation** | daily | 3min | GEX is a snapshot; daily sufficient for EOD, intraday for dynamics |
| **IV reconstruction** | 3min | 3min | Need sufficient price resolution for IV fitting |
| **Delta/Gamma/Vega** | 3min | 3min | Derived from IV + price; 3min captures intraday dynamics |
| **Option-chain analytics** | 3min | 3min | Balance of resolution vs storage |
| **Backtesting** | 3min | 3min | Standard for NIFTY intraday strategies |
| **Market-maker positioning** | 1min | 3min | 1min preferred but 3min acceptable |

### 5.4 Recommendation

**Primary resolution: 3-minute candles**

**Rationale:**
1. The existing NIFTY index candle pipeline uses 3-minute — aligns for synchronization
2. Storage is manageable (~5 GB for full history)
3. Sufficient for IV reconstruction (Black-Scholes fitting works well with 3-min price samples)
4. GEX can be computed at any resolution from 3-min data
5. API request count is 3× less than 1-minute
6. The POC proved 3-minute data is available for expired contracts

**Secondary resolution: daily** (for long-range analysis, ~40 MB additional)

**NOT recommended for initial backfill:** 1-minute (15 GB, 3× API calls, marginal quality improvement over 3-min)

---

## 6. Historical Greeks Architecture

### 6.1 Design Principle: Raw Data ≠ Derived Analytics

```
Raw Market Data (IMMUTABLE)          Derived Analytics (RECOMPUTABLE)
─────────────────────────            ────────────────────────────────
option_candles                       option_greeks (FUTURE TABLE)
  instrument_key                       instrument_key
  open_time                            computed_at
  open, high, low, close               iv, delta, gamma, vega, theta
  volume                               gex, vega_exposure, delta_exposure
  open_interest

contract_specs                       gex_snapshots (EXISTING)
  lot_size                             spot
  strike_price                         net_gex
  instrument_type                      call_gex, put_gex
                                       strike_data (JSON)
```

### 6.2 Required Inputs for Greeks Reconstruction

| Greek | Required Inputs | Source |
|---|---|---|
| **IV** | option price, strike, spot, time-to-expiry, risk-free rate | option_candles + nifty_candles + config |
| **Delta** | IV, strike, spot, time-to-expiry | Black-Scholes formula |
| **Gamma** | IV, strike, spot, time-to-expiry | Black-Scholes formula |
| **Vega** | IV, strike, spot, time-to-expiry | Black-Scholes formula |
| **Theta** | IV, strike, spot, time-to-expiry | Black-Scholes formula |
| **GEX** | gamma, OI, spot | `gamma × OI × spot² × 0.01` (existing formula) |
| **Vega exposure** | vega, OI, lot_size | `vega × OI × lot_size` |
| **Delta exposure** | delta, OI, lot_size | `delta × OI × lot_size` |

### 6.3 IV Reconstruction Strategy

For each option candle at time `t`:

```
Inputs:
  S = underlying price at time t (from nifty_candles)
  K = strike price (from contract_specs)
  T = time to expiry in years (from contract_specs.expiry - t)
  r = risk-free rate (configurable, ~6.5% for India)
  market_price = option_candles.close at time t
  option_type = contract_specs.instrument_type (CE/PE)

Process:
  1. Use Black-Scholes inversion to find IV
  2. IV is the σ that makes BS_price(S, K, T, r, σ) = market_price
  3. Use scipy.optimize.brentq or similar root-finding
  4. Validate: IV must be in reasonable range (1%–200%)

Output:
  iv = implied_volatility
  delta = BS_delta(S, K, T, r, iv, option_type)
  gamma = BS_gamma(S, K, T, r, iv)
  vega = BS_vega(S, K, T, r, iv)
  theta = BS_theta(S, K, T, r, iv, option_type)
```

### 6.4 Assumptions for Greeks Reconstruction

| Assumption | Risk | Mitigation |
|---|---|---|
| Black-Scholes model | Model risk | Standard for NIFTY; accept model error |
| Constant risk-free rate | Low impact | Use 6.5% (India 10Y G-sec); configurable |
| No dividends | Low for index | NIFTY 50 is an index, not a stock |
| European exercise | Correct for NIFTY | NIFTY options are European |
| Sufficient price resolution | 3-min adequate | Verified in POC |
| Time-to-expiry calculated from UTC timestamps | Precision | Use exact expiry date, not approximate |

### 6.5 What NOT to Persist

**Do not persist Greeks in the raw data pipeline.** They are:
- Derived (recomputable from raw data)
- Model-dependent (Black-Scholes assumption)
- Useful only for research, not for data integrity

Store Greeks in a separate `option_greeks` table (future phase) or compute on-the-fly.

---

## 7. Historical Underlying Price

### 7.1 Source

The NIFTY 50 index price is stored in `nifty_candles` (Phase 7.7).

### 7.2 Synchronization Strategy

For IV/Greek reconstruction, we need the underlying price at the same timestamp as each option candle.

```
option_candle.open_time  →  nifty_candle.open_time (exact match)
```

**Since both use 3-minute intervals and both are normalized to UTC, timestamps align naturally.**

If exact alignment fails (e.g., option candle exists but index candle doesn't):
- Use the nearest preceding index candle (forward fill)
- Maximum tolerance: 3 minutes (one candle interval)
- If no match within tolerance: mark as `insufficient_underlying_price`

### 7.3 Underlying Price Requirements

| Requirement | Status |
|---|---|
| Index candles from Jan 2022 | VERIFIED (V3 API, Phase 7.9) |
| 3-minute resolution | VERIFIED |
| Timestamp alignment with option candles | DESIGNED (exact match) |
| Coverage for all option expiry dates | ASSUMED (index has longer history than options) |

---

## 8. Storage Estimates (Recalculated)

### 8.1 Per-Candle Storage

Based on Phase 7.11 actual response (7 fields) + schema overhead:

| Field | Bytes (est.) |
|---|---|
| id (integer PK) | 8 |
| instrument_key (varchar 64) | 64 |
| interval (varchar 8) | 8 |
| open_time (datetime) | 8 |
| open, high, low, close (4 × float) | 32 |
| volume, open_interest (2 × float) | 16 |
| source, fetched_at | 40 |
| **Total per row** | **~176 bytes** |

SQLite overhead: ~1.5× → **~264 bytes per candle**

### 8.2 Scaling Table

| Horizon | Trading Days | Contracts | Candles | Storage |
|---|---|---|---|---|
| 1 month | ~22 | ~200 | ~550K | ~145 MB |
| 6 months | ~130 | ~1,200 | ~3.3M | ~870 MB |
| 1 year | ~250 | ~2,400 | ~6.3M | ~1.7 GB |
| 3 years (2022–2025) | ~750 | ~7,200 | ~18.8M | ~5 GB |
| **Full available** | ~750 | ~19,800 | ~49.5M | **~13 GB** |

### 8.3 Combined Storage

| Component | 1 Year | 3 Years | Full |
|---|---|---|---|
| Index candles (3min) | ~3 MB | ~10 MB | ~10 MB |
| Contract metadata | ~1.2 MB | ~3 MB | ~5 MB |
| **Option candles (3min)** | **~1.7 GB** | **~5 GB** | **~13 GB** |
| Greeks (if computed) | ~1.7 GB | ~5 GB | ~13 GB |
| **Total** | **~3.4 GB** | **~10 GB** | **~26 GB** |

### 8.4 Recommended Initial Backfill

**Start with 6 months** (~870 MB for option candles, ~1.7 GB total).

This provides:
- Sufficient data for strategy backtesting
- Manageable storage
- ~1,200 contracts to validate the pipeline
- Enough historical depth for lot-size variation analysis

---

## 9. Confirmed vs Assumed vs Unknown

### 9.1 VERIFIED (from Phase 7.9/7.11)

| Item | Source |
|---|---|
| Expired Historical Candle API provides 7 fields | Phase 7.11 live POC |
| Volume is non-zero for expired options | Phase 7.11 live POC |
| Open interest is available and non-zero | Phase 7.11 live POC |
| Historical lot_size=25 (Oct 2024) preserved | Phase 7.9/7.11 live |
| Historical lot_size=75 (Apr 2025) preserved | Phase 7.9/7.11 live |
| Different lot sizes coexist by instrument_key | Phase 7.11 live |
| Timestamp format: IST (+05:30), normalized to UTC | Phase 7.9/7.11 |
| Idempotent candle insertion works | Phase 7.11 POC |
| CE and PE contracts both work | Phase 7.11 POC |
| 3-minute candles available for expired contracts | Phase 7.11 POC |
| ~99 expiry dates available | Phase 7.9 live |
| Upstox Plus plan required for expired data | Phase 7.9 live |
| No bid/ask fields in API response | Phase 7.11 POC |
| GEX formula: gamma × OI × spot² × 0.01 | Existing frontend code |
| lot_size NOT used in GEX formula | Existing frontend code/tests |

### 9.2 DESIGN DECISIONS

| Decision | Rationale |
|---|---|
| Separate `option_candles` table | Clean separation from `nifty_candles` |
| Unique key: (instrument_key, interval, open_time) | instrument_key is the canonical Upstox identity |
| 3-minute primary resolution | Aligns with index candles, sufficient for Greeks, manageable storage |
| Raw data immutable, Greeks computed separately | Data integrity + flexibility |
| Black-Scholes for IV reconstruction | Standard model for European index options |
| 200ms delay between API calls | Measured safe in POC |
| Checkpoint via distinct instrument_keys | Simple, effective resume strategy |

### 9.3 ASSUMPTIONS

| Assumption | Risk | Validation Plan |
|---|---|---|
| 3-min candles available for all strikes | Medium | Test with far OTM strikes |
| Daily candles available for full history | Low | Test with 2022 data |
| Index candles align with option candles | Low | Both use same 3-min grid |
| Black-Scholes IV is accurate for NIFTY | Low | Standard model; validate against published IV |
| ~19,800 contracts need candle data | Low | Based on 99 expiries × 200 contracts |
| Upstox Plus remains available | Low | User has active subscription |

### 9.4 STILL UNKNOWN

| Item | How to Verify |
|---|---|
| Exact earliest available expired candle date | Test with 2022-01-01 |
| Whether weekly expiries have candle data | Query weekly expiry dates |
| Far OTM strike data availability | Test with strikes >5% OTM |
| Rate-limit under sustained load | Controlled 1000-request test |
| Maximum daily candle count per contract | Compare with index candle count |
| Whether futures have candle data | Test with FUT contracts |

---

## 10. Implementation Roadmap

### Phase 7.13 (Recommended Next)
- Create `OptionCandle` model and migration
- Implement `record_option_candles()` persistence function
- Write comprehensive unit tests with synthetic data
- **No live API calls**

### Phase 7.14
- Implement Layer 2 backfill engine
- Controlled backfill of one expiry (2024-10-31)
- Rate-limit validation
- Storage measurement

### Phase 7.15
- Greeks reconstruction engine
- IV calculation from historical prices
- Delta/Gamma/Vega/Theta computation
- GEX historical reconstruction

### Phase 8+
- Full historical backfill
- Research engine integration
- Frontend coverage dashboard

---

*This document is a design artifact. No code was modified, no backfill was performed, nothing was committed or deployed.*
