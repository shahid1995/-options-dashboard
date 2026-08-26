# Phase 7.19A — Historical Greeks Reconstruction Design

**Status:** DESIGN + SYNTHETIC VALIDATION  
**Scope:** Architecture document + synthetic test suite only  
**No production code modified**

---

## Pipeline Overview

```text
option_candles          (raw OHLCV + OI per expired contract)
      +
contract_specs          (lot_size, strike, CE/PE, expiry per instrument_key)
      +
nifty_candles           (NIFTY index OHLCV — spot proxy)
      ↓
timestamp alignment     (match option candle → NIFTY candle for spot)
      ↓
historical NIFTY spot   (close of matched index candle)
      ↓
time-to-expiry          (option candle time → expiry date, in year fraction)
      ↓
IV solver               (market price → implied volatility)
      ↓
Black-Scholes Greeks    (delta, gamma, vega, theta per unit)
      ↓
option_greeks           (persisted derived analytics)
      ↓
GEX / Vega / Delta / IV research
```

---

## A. Data Sources

### Raw Historical Option Market Data (`option_candles`)

| Field | Type | Source | Immutability |
|-------|------|--------|-------------|
| `instrument_key` | string | Upstox expired candle API | Identity |
| `interval` | string | Fixed ("3min") | Identity |
| `open_time` | datetime UTC | Upstox (IST → UTC normalized) | Identity |
| `open`, `high`, `low`, `close` | float | Upstox raw price | **Immutable** |
| `volume` | float | Upstox raw volume | **Immutable** |
| `open_interest` | float | Upstox raw OI | **Immutable** |

**This data is never overwritten by Greeks or GEX calculations.**

### Historical Contract Metadata (`contract_specs`)

| Field | Type | Source |
|-------|------|--------|
| `instrument_key` | string | Upstox expired contracts API (unique key) |
| `expiry` | string (YYYY-MM-DD) | Upstox |
| `strike_price` | float | Upstox |
| `instrument_type` | string ("CE"/"PE") | Upstox |
| `lot_size` | int or null | Upstox (historical, authoritative) |
| `underlying` | string | Upstox ("NIFTY") |
| `tick_size` | float | Upstox |

**Historical lot_size is preserved exactly as returned. Never substituted.**

### Underlying/Index Data (`nifty_candles`)

| Field | Type | Source |
|-------|------|--------|
| `symbol` | string | "NIFTY" |
| `interval` | string | "3min" |
| `open_time` | datetime UTC | Upstox V3 historical candle API |
| `open`, `high`, `low`, `close` | float | Upstox raw price |
| `volume` | float | Upstox raw volume |

**NIFTY index data is the ONLY source for historical spot price. The current NIFTY price is NEVER used for historical calculations.**

---

## B. Timestamp Alignment

### The Core Problem

Option candles and NIFTY index candles have **different trading sessions**:

| Session | Open (IST) | Close (IST) | Duration |
|---------|-----------|-------------|----------|
| NIFTY index | 09:15 | **15:27** | 6h 12min |
| NIFTY options | 09:15 | **15:40** | 6h 25min |

This means option candles after 15:27 IST have **no corresponding NIFTY index candle**.

### Alignment Strategy

1. **For each option candle timestamp, find the NIFTY index candle at the SAME timestamp.**
2. **If no exact match exists, find the most recent preceding NIFTY candle.**
3. **If no preceding NIFTY candle exists on the same trading day, the option candle has NO valid spot → mark as INVALID.**
4. **Never fabricate a spot value.**

### Implementation

```python
def align_spot(
    option_open_time_utc: datetime,
    nifty_candles: list[dict],  # sorted ascending by open_time
) -> float | None:
    """Return the NIFTY close price aligned to the option candle timestamp.
    
    Strategy: find the latest NIFTY candle whose open_time <= option_open_time.
    This correctly handles:
      - Exact matches (most option candles during trading hours)
      - Post-close option candles (15:27-15:40 IST) → use last index candle
      - Missing data → return None (INVALID)
    
    Returns None when no valid spot can be established.
    """
```

### Post-Close Option Candles (15:27–15:40 IST)

These candles ARE valid market data. They contain real option prices. The spot is the last available NIFTY close (from the 15:27 candle). The time-to-expiry calculation still works correctly because it uses the actual option candle timestamp.

**Do NOT discard post-close option candles.** They are valuable for:
- Closing auction analysis
- EOD Greeks calculation
- Research on settlement-price formation

### Invalid Cases

| Scenario | Handling |
|----------|----------|
| No NIFTY candle on same day | INVALID — return None |
| Option candle before any NIFTY candle on that day | INVALID |
| NIFTY close = 0 or null | INVALID |
| Option price = 0 or null | INVALID |

---

## C. Historical ATM / Spot

### NIFTY is an Index

NIFTY 50 is a stock-market index, not an option contract. The Upstox expired-option API provides NIFTY **option** contracts (CE/PE with strike prices), but NOT the NIFTY index value itself.

### Historical Spot Source

Historical NIFTY spot must come from `nifty_candles` (the NIFTY index candle table). This table is populated from the Upstox V3 Historical Candle API for the NIFTY 50 index (`NSE_INDEX|Nifty 50`).

### Critical Invariant

**The current NIFTY price is NEVER used for historical Greeks calculations.** All spot values come from historical index data corresponding to the exact date/time being calculated.

---

## D. Time to Expiry

### Convention

We use **calendar-time-to-expiry** (not trading-time), measured as a year fraction:

```python
T = max(0, (expiry_date - valuation_datetime).total_seconds() / (365.25 * 86400))
```

Where:
- `expiry_date` is the expiry date at market close (15:30 IST for the last trading session)
- `valuation_datetime` is the UTC datetime of the option candle

### Expiry Session Timing

For NIFTY options, expiry day is the last Thursday of the month (or the preceding Thursday if Thursday is a holiday). On expiry day:

- Options trade from 09:15 to 15:40 IST
- The last trading session ends at 15:40 IST
- Settlement is based on the closing value of NIFTY at 15:30 IST

### T = 0 Handling

When `T ≤ 0`, the option has expired or is at expiry. In this case:
- Gamma = 0, Vega = 0, Theta = 0
- Delta = intrinsic direction (1 for ITM CE, -1 for ITM PE, 0 for OTM)
- IV is undefined → return null

### Near-Expiry Behavior

For very small T (e.g., T < 1/365, less than 1 day):
- Greeks can become extreme (large gamma, large theta)
- The IV solver may have difficulty converging
- These cases must be handled gracefully, not silently discarded

---

## E. Black-Scholes Model

### Formulas

For a European option on a non-dividend-paying underlying (NIFTY index, q=0):

```text
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T

Call: C = S·N(d1) - K·e^(-rT)·N(d2)
Put:  P = K·e^(-rT)·N(-d2) - S·N(-d1)
```

### Greeks (per unit, per contract)

```text
Delta:
  CE: Δ = e^(-qT)·N(d1)
  PE: Δ = e^(-qT)·(N(d1) - 1) = -e^(-qT)·N(-d1)

Gamma:
  Γ = e^(-qT)·φ(d1) / (S·σ·√T)

Vega:
  ν = S·e^(-qT)·φ(d1)·√T   (per unit volatility change, i.e. per 1.00)

Theta (per year):
  Θ = -[S·e^(-qT)·φ(d1)·σ] / (2√T) - r·K·e^(-rT)·N(±d2) + q·S·e^(-qT)·N(±d1)
  (signs depend on CE/PE)
```

### Unit Convention

To match the existing frontend `greekAnalytics.js` canonical units:

| Greek | Model unit | Canonical unit | Conversion |
|-------|-----------|---------------|-----------|
| Delta | per 1 underlying point | per 1 underlying point | ×1 |
| Gamma | per 1 underlying point² | per 1 underlying point | ×1 |
| Vega | per 1.00 vol fraction | per 0.01 vol point (1% IV) | ×0.01 |
| Theta | per year | per calendar day | ÷365 |

### Assumptions and Limitations

1. **European exercise only** — NIFTY options on NSE are European
2. **No dividends** — NIFTY index does not pay dividends directly (q=0)
3. **Constant risk-free rate** — we use a fixed rate (e.g. 6.5% for India)
4. **Log-normal returns** — may understate tail risk
5. **No early exercise premium** — valid for European options
6. **No transaction costs or margins** in the Greeks themselves
7. **Continuously compounded** risk-free rate

---

## F. Implied Volatility Solver

### Algorithm: Brent's Method (Bounded Root-Finding)

We use Brent's method (via `scipy.optimize.brentq`) because:
- Guaranteed convergence for bracketed roots
- Faster than pure bisection
- Robust against oscillatory pricing functions
- Well-tested implementation in scipy

### Setup

We solve for σ in:

```text
f(σ) = BlackScholes(S, K, T, σ, r) - market_price = 0
```

### Bounds

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| σ_min | 0.001 (0.1%) | Minimum meaningful volatility |
| σ_max | 10.0 (1000%) | Extreme upper bound |
| Default bracket | [0.01, 5.0] | Normal range (1% to 500%) |

### Tolerance

- **Absolute tolerance:** 1e-8 (on price difference)
- **Relative tolerance:** 1e-8
- **Maximum iterations:** 100

### Convergence Criteria

The solver converges when:
```text
|BlackScholes(S, K, T, σ_test, r) - market_price| < tolerance
```

### Failure Behavior

The solver FAILS (returns null/NaN) when:

| Condition | Error Code |
|-----------|-----------|
| T ≤ 0 | `EXPIRED` |
| S ≤ 0 | `INVALID_SPOT` |
| K ≤ 0 | `INVALID_STRIKE` |
| market_price ≤ 0 | `INVALID_PRICE` |
| market_price < intrinsic value | `BELOW_INTRINSIC` |
| market_price > upper bound price | `ABOVE_THEORETICAL_MAX` |
| No bracket found (f(a)·f(b) > 0) | `NO_BRACKET` |
| Max iterations exceeded | `CONVERGENCE_FAILED` |
| Numerical exception | `NUMERICAL_ERROR` |

### Intrinsic Value Check

```text
CE intrinsic = max(S - K, 0)
PE intrinsic = max(K - S, 0)

if market_price < intrinsic:
    return INVALID  (price cannot be below intrinsic for European option)
```

### Price Bounds

```text
CE lower bound = max(S·e^(-qT) - K·e^(-rT), 0)
CE upper bound = S·e^(-qT)

PE lower bound = max(K·e^(-rT) - S·e^(-qT), 0)
PE upper bound = K·e^(-rT)
```

---

## G. Greeks — Per-Unit vs. Lot-Level

### Per-Unit Greeks

The Black-Scholes formulas produce **per-unit** Greeks — the change in option value per one-unit change in the underlying, per one-unit change in volatility, per one-unit change in time.

These are the same as the per-contract values stored in the frontend's `greekAnalytics.js` canonical unit contract.

### Lot-Level Exposure

To convert per-unit Greek to lot-level exposure:

```text
lot_delta     = per_unit_delta × lot_size
lot_gamma     = per_unit_gamma × lot_size
lot_vega      = per_unit_vega × lot_size
lot_theta     = per_unit_theta × lot_size
```

Where `lot_size` comes from `contract_specs.lot_size` for the specific `instrument_key`.

### Critical Distinction

```text
per-unit Greek  (Black-Scholes output)
        ×
historical lot_size  (from contract_specs)
        =
lot-level exposure  (used in GEX calculation)
```

**Never confuse lot_size with the mathematical per-unit Greek.** The per-unit Greek is a mathematical property of the option. The lot_size is a contract specification that scales it.

---

## H. Historical Lot Size

### Source of Truth

Historical lot_size MUST come from `contract_specs.lot_size` for the specific `instrument_key`.

### Never Use

- Current NIFTY lot size (currently 75)
- Hard-coded 75
- Hard-coded 25
- Hard-coded 50
- Inferred from current contract specification
- Any "effective date" table

### Verified Historical Values

From live Upstox API verification (Phase 7.9, 7.11, 7.18):

| Period | Lot Size | Verified Source |
|--------|----------|----------------|
| 2024-10 to 2024-12 | **25** | Upstox expired contracts API |
| 2025-01 to present | **75** | Upstox expired contracts API |

### Missing lot_size

If `contract_specs.lot_size` is NULL for an instrument_key:
- The Greeks calculation still produces per-unit values
- Lot-level exposure CANNOT be calculated
- The record must be marked `insufficient_metadata`
- NEVER substitute the current lot size

---

## I. Proposed `option_greeks` Table

### Schema Design

```sql
CREATE TABLE option_greeks (
    id INTEGER PRIMARY KEY,
    
    -- Identity (matches option_candles)
    instrument_key VARCHAR(64) NOT NULL,
    interval VARCHAR(8) NOT NULL DEFAULT '3min',
    open_time DATETIME NOT NULL,
    
    -- Market state at calculation time
    spot FLOAT NOT NULL,
    strike FLOAT NOT NULL,
    option_type VARCHAR(4) NOT NULL,  -- 'CE' or 'PE'
    option_price FLOAT NOT NULL,
    
    -- Calculation inputs
    time_to_expiry FLOAT NOT NULL,     -- year fraction
    risk_free_rate FLOAT NOT NULL,     -- decimal (0.065 = 6.5%)
    
    -- Output: implied volatility
    implied_volatility FLOAT,          -- decimal (0.1824 = 18.24%), NULL if solver failed
    
    -- Output: per-unit Greeks
    delta FLOAT,                       -- per 1 underlying point
    gamma FLOAT,                       -- per 1 underlying point²
    vega FLOAT,                        -- per 1.00 vol fraction (not per 1%)
    theta FLOAT,                       -- per year (annualized)
    
    -- Calculation metadata
    calculation_model VARCHAR(32) NOT NULL DEFAULT 'BLACK_SCHOLES_EUROPEAN',
    calculation_version VARCHAR(16) NOT NULL DEFAULT '1.0.0',
    calculated_at DATETIME NOT NULL,
    
    -- Quality
    status VARCHAR(16) NOT NULL DEFAULT 'VALID',  -- VALID | INVALID | INSUFFICIENT_DATA
    error_code VARCHAR(32),                         -- NULL when status=VALID
    
    -- Constraints
    UNIQUE(instrument_key, interval, open_time, calculation_version)
);
```

### Uniqueness Constraint Choice

**Unique on:** `(instrument_key, interval, open_time, calculation_version)`

**Rationale:**
- Same raw data can be recalculated with a different model version
- `calculation_version` allows reproducibility and model comparison
- One raw candle → one Greek record per version
- Prevents duplicates while allowing recalculation

### Why Not Just `(instrument_key, interval, open_time)`?

Because the research engine may later change:
- IV solver algorithm
- Risk-free rate
- Expiry convention
- Timestamp alignment strategy
- Numerical tolerances

Each change requires a new `calculation_version` and produces a different result for the same raw data.

---

## J. Raw Data Immutability

### Three-Layer Architecture

```text
RAW LAYER (immutable)
  option_candles          OHLCV + OI, never overwritten
  nifty_candles           Index OHLCV, never overwritten
  contract_specs          Contract metadata, lot_size immutable

MODEL LAYER (derived, reproducible)
  option_greeks           IV + Greeks, computed from raw layer

ANALYTICS LAYER (consumed by research)
  GEX                     Gamma exposure per strike
  Vega exposure           Vega exposure per strike
  Delta exposure          Delta exposure per strike
  IV analysis             Volatility surface, term structure
```

### Invariant

The Greeks engine MUST NEVER:
- Modify `option_candles` rows
- Modify `nifty_candles` rows
- Modify `contract_specs.lot_size`
- Overwrite raw market data with calculated values

---

## K. Calculation Versioning

### Why Versioning is Required

The Greek values depend on:
1. **IV solver algorithm** — Brent vs. Newton vs. bisection
2. **Risk-free rate** — 6.5% vs. 7.0% vs. dynamic
3. **Expiry convention** — calendar days vs. trading days
4. **Timestamp alignment** — exact match vs. nearest-preceding
5. **Numerical tolerances** — 1e-6 vs. 1e-8
6. **Time-to-expiry formula** — year fraction vs. trading-day fraction

If any of these change, the same raw data produces different Greeks. Versioning ensures:
- Reproducibility of past research results
- A/B comparison of model changes
- Audit trail for regulatory or analytical purposes

### Version Format

```text
MAJOR.MINOR.PATCH
```

- **MAJOR:** incompatible model change (different BS formula, different alignment)
- **MINOR:** compatible enhancement (better solver, new edge-case handling)
- **PATCH:** bug fix or tolerance adjustment

Initial version: `1.0.0`

---

## L. Risk-Free Rate

### Choice

For Indian market historical calculations, we use a **fixed risk-free rate** of 6.5% (approximate Indian government bond yield).

### Justification

- Simple, reproducible, auditable
- The impact on short-dated NIFTY options is small relative to IV uncertainty
- Can be refined in a future version without invalidating historical data

### Future Enhancement

A dynamic risk-free rate (from RBI data or bond yields) could be added as `calculation_version = "2.0.0"` without affecting existing records.

---

## M. Compatibility with Existing Frontend

### Existing Black-Scholes (`pricing.js`)

The frontend already has `bsGreeks(type, S, K, T, sigma, r, q)` which computes delta, gamma, theta, vega. The Python implementation must produce **identical results** for the same inputs.

### Existing Greek Convention (`greekAnalytics.js`)

The frontend defines canonical units:
- **Theta:** ₹ per calendar day (not per year)
- **Vega:** ₹ per 1 vol point = 0.01 (not per 1.00)

The Python `option_greeks` table stores:
- **Theta:** annualized (per year)
- **Vega:** per 1.00 vol fraction

The conversion happens in the query/API layer when serving data to the frontend, matching the existing `MODEL_THETA_PER_DAY_FACTOR = 1/365` and `MODEL_VEGA_PER_VOL_POINT_FACTOR = 0.01` conventions.

### GEX Snapshot Compatibility

The existing `GexSnapshot.strike_data` JSON contains per-strike gamma and OI. The historical Greeks engine provides the raw per-unit gamma; the GEX calculation scales by `lot_size × OI` as before.

---

## N. Edge Cases and Failure Modes

| Case | Spot | T | IV | Greeks | Status |
|------|------|---|----|---------|--------|
| Normal | valid | >0 | solved | computed | VALID |
| Expired (T=0) | valid | 0 | null | directional delta, rest=0 | VALID |
| Missing spot | null | any | null | null | INVALID |
| Missing price | any | any | null | null | INVALID |
| Price below intrinsic | valid | >0 | null | null | INVALID |
| Price = 0 | valid | any | null | null | INVALID |
| Solver fails | valid | >0 | null | null | INVALID |
| Near-expiry (T<1day) | valid | small | may fail | may be extreme | VALID/INVALID |
| Post-close option candle | valid (last index close) | >0 | solved | computed | VALID |

---

## O. Estimated Computational Cost

For 1 contract × 125 candles:
- 125 spot lookups (hash map, O(1) each)
- 125 T calculations
- 125 IV solver calls (~20 iterations each = ~2500 function evaluations)
- 125 Greek calculations

For 210 contracts × 125 candles = 26,250 candles:
- ~26,250 IV solver calls
- Estimated runtime: < 5 seconds on modern hardware
- Memory: negligible (one contract at a time)
