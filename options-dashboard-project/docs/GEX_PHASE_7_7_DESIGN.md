# Options Dashboard — GEX Phase 7.7: Validation & Research Engine

**Date:** 2026-08-23  
**Status:** Design proposal — awaiting approval  
**Predecessors:** Phase 7.1–7.6  
**Scope:** Empirical validation of GEX-derived measurements against subsequent NIFTY price behavior  
**Boundaries:** Research/analytics only — no trading signals, no strategy execution, no UI changes

---

## 1. Objective

Phase 7.1–7.6 established the GEX calculation pipeline: gamma exposure, gamma flip/walls, historical snapshots, time-series analytics, snapshot contracts, validation, and live persistence.

Phase 7.7 determines **empirically** whether GEX-derived measurements contain statistically useful information about subsequent NIFTY price behavior.

This is a **research/validation** phase. It does not:
- Generate BUY/SELL signals
- Create entry/exit rules
- Optimize thresholds for profitability
- Claim predictive power without evidence
- Introduce machine learning

The output is a research dataset and a set of validated statistical relationships, classified by robustness.

---

## 2. Existing Infrastructure Audit

### 2.1 Phase 7.1 — GEX Calculation (`gex.js`)

**Exports:** `rawGex`, `signedGex`, `strikeGex`, `expiryGex`, `chainGex`, `formatGex`  
**Formula:** `GEX = γ × OI × S² × 0.01`  
**Units:** gamma = per 1 underlying point, OI = contracts, S = index points  
**Convention:** Calls positive, puts negative (NAIVE_DEALER_CONVENTION)  
**Input:** Canonical chain rows with broker-observed gamma, OI, IV per strike

### 2.2 Phase 7.2 — Gamma Flip/Walls (`gexPhase72.js`)

**Exports:** `modelGamma`, `netGexAtSpot`, `detectZeroCrossings`, `findGammaWalls`, `spotSweep`, `brokerVsModelGamma`, `crossingStrength`, `selectPrimaryFlip`  
**Model:** Black-Scholes gamma at hypothetical spot levels  
**Output:** Gamma flip spot, flip direction, call/put walls (top-N), crossing strength  
**Key:** Uses BS model gamma for sweep; broker gamma preserved for historical GEX

### 2.3 Phase 7.3 — Historical GEX (`gexHistory.js`)

**Exports:** `captureGexSnapshot`, `GexRingBuffer`, `computeDeltaGex`, `computeSpotDeltaGex`, `computeStructureDeltaGex`, `decomposeDeltaGex`, `computeGexMigration`, `computeStrikeCentroid`, `computeConcentration`, `assembleGexTimeSeries`, `reconstructChainRows`, `validateGexSnapshot`  
**Decomposition:** `ΔGEX_total = ΔGEX_spot + ΔGEX_OI + ΔGEX_IV + ΔGEX_residual`  
**Ring buffer:** 200 snapshots, 5-min interval, ~16.7 hours  
**Backend:** `gex_snapshots` table, 90-day retention, idempotent POST

### 2.4 Phase 7.4 — Analytics (`gexTimeSeries.js`, `gexConcentration.js`, `gexProfileLabel.js`, `gexAnalytics.js`)

**Time-series:** `computeNetGexSma`, `computeDeltaGexSma`, `computeVelocity`, `computeAcceleration`, `computeDeltaGexVolatility`  
**Concentration:** `computeConcentrationHistory`, `computeConcentrationPercentile`, `computeGexPercentile`, `computeExpiryDecomposition`, `computeCallGexShare`  
**Profile:** `classifyGexProfile` — structural geometry labels (not trading signals)  
**Coordinator:** `computeGexAnalytics` — 3-layer architecture (Raw → Statistical → Classification)  
**SB interface:** 13 nullable fields, read-only, facts/statistics only

### 2.5 Phase 7.5 — Contracts/Validation (`gexHistory.js`, `gexAnalytics.js`, `gexContract.test.js`)

**Schema:** `GEX_SNAPSHOT_SCHEMA_VERSION = "GEXSnapshot_v1"`  
**SB version:** `STRATEGY_BUILDER_VERSION = "strategyBuilderInputs_v1"`  
**Validation:** `validateGexSnapshot()` — comprehensive issues/warnings

### 2.6 Phase 7.6 — Live Capture (`useGexCapture.js`, `gexPersistence.js`, `routers/gex.py`)

**Capture:** Frontend hook captures from `useChainFeed`, validates, pushes to ring buffer, persists  
**API:** `POST /gex/snapshots`, `GET /gex/snapshots`, `GET /gex/snapshots/latest`, `GET /gex/snapshots/count`  
**Persistence:** Idempotent POST, 90-day retention, user-scoped session auth

### 2.7 Existing Statistics/Utilities

| Module | Key Functions |
|---|---|
| `statistics.js` | `rollingMean`, `rollingMedian`, `rollingStdDev`, `zScore`, `percentileRank`, `anomalyMeasurement` |
| `pricing.js` | `bsGreeks`, `bsCall`, `bsPut`, `timeToExpiry`, `normalPdf`, `normalCdf` |
| `marketAnalytics.js` | `pearsonCorrelation`, `normalizeSide`, `directionOfChange`, `cePeComparison` |
| `options.js` | `putCallRatio`, `maxPainStrike`, `maxOI`, `oiTotals` |
| `marketStatus.js` | NSE trading calendar, holidays, market hours |

### 2.8 Historical Candle Data — **NOT YET AVAILABLE**

The existing Upstox adapter provides only live option chain data. There is **no historical NIFTY candle (OHLCV) storage** in the current system.

**Phase 7.7 must design:**  
- A historical candle data collection and storage mechanism  
- OR a research-time fetch approach using the Upstox historical candle API  

The Upstox API does support historical candle data (intraday and daily), but no infrastructure exists to store or query it.

### 2.9 Candle Ingestion Prerequisite — CRITICAL GAP

> **Phase 7.7 implementation status:** The `NiftyCandle` model and `nifty_candles.py` persistence service have been implemented.  However, **there is no production data ingestion path** — no Upstox historical-candle adapter method, no backend ingestion endpoint, and no import workflow.
>
> **Impact:** The research engine is structurally complete but **cannot run on real data** until candles are populated in the `nifty_candles` table.
>
> **Recommended next step (before research can begin):**
> 1. Add a `get_historical_candles()` method to the Upstox adapter (`backend/app/services/upstox.py`)
> 2. Create an authenticated backend endpoint or import script to populate `nifty_candles`
> 3. Candle ingestion must be **idempotent** (the `record_candles()` upsert already supports this)
> 4. Preserve **UTC timestamps** throughout — no timezone conversion
> 5. Handle rate limits from the Upstox API gracefully
>
> **This is a data-engineering prerequisite, not a research-engineering change.**

---

## 3. Research Dataset Design

### 3.1 Research Observation

A **research observation** is a point-in-time record pairing GEX state with forward price outcomes. It is created retrospectively from historical data, not in real-time.

```
ResearchObservation {
  // Identity
  observationId: string,           // unique ID
  capturedAt: string,              // ISO-8601 UTC — when GEX was computed
  
  // Market state at capture
  spot: number,                    // NIFTY closing/last price at capturedAt
  symbol: string,                  // "NIFTY"
  
  // GEX features (from snapshot)
  netGex: number | null,
  callGex: number | null,
  putGex: number | null,
  normalizedNetGex: number | null, // netGex / (spot² × 0.01)
  deltaGex: number | null,         // change from previous observation
  velocity: number | null,         // ΔGEX / Δt
  acceleration: number | null,     // Δvelocity / Δt
  volatility: number | null,       // stddev of recent ΔGEX
  concentrationTop3: number | null, // top 3 strikes' share of total |GEX|
  gexPercentile: number | null,    // percentile rank within history
  descriptiveZ: number | null,     // z-score within history
  callGexShare: number | null,     // |call| / (|call|+|put|) × 100
  
  // Gamma flip (from Phase 7.2 sweep, if available)
  gammaFlipSpot: number | null,
  gammaFlipDistancePct: number | null,  // |spot - flip| / spot × 100
  gammaFlipDirection: string | null,    // "above" | "below"
  
  // Gamma walls
  callWallStrikes: number[],
  putWallStrikes: number[],
  callWallDistancePct: number | null,   // distance from spot to nearest call wall
  putWallDistancePct: number | null,    // distance from spot to nearest put wall
  
  // Expiry context
  expiry: string | null,
  dte: number | null,              // days to expiry
  
  // Data quality
  strikeCoverage: number | null,   // validStrikeCount / totalStrikeCount
  freshnessMs: number | null,      // age of snapshot at observation time
  methodologyVersion: string | null,
  schemaVersion: string | null,
  
  // Context
  timeOfDay: string,               // "pre_market" | "morning" | "midday" | "afternoon" | "post_market"
  dayOfWeek: number,               // 0=Sun..6=Sat
  isExpiryDay: boolean,
  
  // Forward outcomes (computed retrospectively)
  forward: ForwardOutcomes
}
```

### 3.2 Forward Outcomes

Forward outcomes are computed from NIFTY candle data AFTER the observation timestamp. They are **not** available at observation time (this is the prediction target).

```
ForwardOutcomes {
  // Reference candle (the candle at capturedAt)
  referenceClose: number,
  
  // Forward candles
  candles1: CandleSummary,    // next 1 candle
  candles3: CandleSummary,    // next 3 candles
  candles5: CandleSummary,    // next 5 candles
  candles10: CandleSummary,   // next 10 candles
  candles15: CandleSummary,   // next 15 candles
  candles30: CandleSummary,   // next 30 candles
}

CandleSummary {
  return: number,              // (close - referenceClose) / referenceClose
  maxFavorableExcursion: number, // best point in direction of final move
  maxAdverseExcursion: number,   // worst point against direction of final move
  realizedVolatility: number,    // stddev of returns over the window
  high: number,                  // highest price in window
  low: number,                   // lowest price in window
  highExcursion: number,         // (high - referenceClose) / referenceClose
  lowExcursion: number,          // (low - referenceClose) / referenceClose
  direction: number,             // +1 (up) | -1 (down) | 0 (flat)
}
```

**Horizon selection rationale:**
- **1 candle (3 min):** Very short-term — tests microstructure/flow effects
- **3 candles (9 min):** Short-term — tests immediate reaction persistence
- **5 candles (15 min):** Intraday momentum
- **10 candles (30 min):** Half-hour horizon — common intraday trading window
- **15 candles (45 min):** Tests medium-term intraday persistence
- **30 candles (90 min):** Longer intraday — tests whether GEX informs broader intraday trajectory

**Why not daily candles?** NIFTY option-chain GEX is captured at 5-minute intervals, making intraday analysis natural. Daily aggregation would destroy the temporal resolution.

### 3.3 Candle Data Requirements

Each candle must contain:
```
Candle {
  timestamp: string,    // ISO-8601 UTC
  open: number,
  high: number,
  low: number,
  close: number,
  volume: number,       // informational, not used in GEX research
}
```

**Interval:** 3-minute candles (matching NIFTY F&O tick resolution)  
**Source:** Upstox historical candle API (`GET /market-quote/quotes`, historical endpoint)  
**Storage:** Backend `nifty_candles` table (new, Phase 7.7)

---

## 4. Market-Respected Level Detection — DEFERRED TO PHASE 7.7B

> **Implementation note (Phase 7.7):** The market-respected level detection system described in this section has been formally deferred to **Phase 7.7B**.  The core GEX→forward-outcome research engine (§5–§13) does not depend on this component and can produce meaningful conclusions about whether GEX features predict forward price outcomes without support/resistance level analysis.
>
> **Why deferred:**
> - The core engine answers the fundamental question: "Does GEX predict forward returns?"
> - §4 answers a refinement question: "Does GEX predict behavior *at* support/resistance levels?"
> - §4 depends on historical candle data being available AND on the core engine's results to know what to test at levels
> - Separating allows the core engine to be validated independently
>
> **Phase 7.7B will implement:**
> - N-bar fractal swing detection (lookback=3, confirmation=3)
> - Support/resistance classification with bounce reaction
> - Level clustering by tolerance
> - Failed-level handling (broken support → resistance, and vice versa)
> - Strict look-ahead prevention (level "known" only after confirmation window)
> - Integration with the core research engine for GEX→level behavior testing
>
> **Phase 7.7B rules:** Must use the same strict look-ahead and chronological-validation rules as the core engine.

### 4.1 Objective

Identify objectively measurable support/resistance levels using historical NIFTY candles, then test whether GEX features provide information about these levels.

### 4.2 Swing High / Swing Low Detection

A **swing high** at candle `i` is defined as:

```
swingHigh(i) := high(i) > high(j)  ∀ j ∈ [i - lookback, i + lookback]
```

Similarly for swing lows using `low`. This is the standard N-bar fractal pattern.

**Parameters:**
| Parameter | Value | Rationale |
|---|---|---|
| `lookback` | 3 candles (9 min) | Captures meaningful intraday turning points |
| `confirmationWindow` | 3 candles after | Level only "known" after 3 subsequent candles confirm it |

**Look-ahead prevention:** A swing high at candle `i` is not "detected" until candle `i + confirmationWindow` has closed. The level is assigned to timestamp of candle `i + confirmationWindow`.

### 4.3 Support / Resistance Classification

A swing low becomes **support** if the subsequent price action reacts upward from it:

```
isSupport(level, candles_after, tolerance=0.001) :=
  pricetouches(level, tolerance) ≥ 1 within confirmationWindow
  AND price bounces ≥ 0.05% from level after touch
```

A swing high becomes **resistance** if subsequent price action reacts downward.

**Tolerance:** 0.1% of the level price (NIFTY ~25,000 → tolerance ±25 points)

### 4.4 Level Clustering

Overlapping levels are clustered when within `tolerance` of each other:

```
cluster(levels, tolerance) :=
  group levels where |level_a - level_b| / level_a < tolerance
  clusterStrength = sum(significance_weight of each level in cluster)
```

**Significance weight:** Each level weighted by:
1. Number of touches/reactions
2. Recency (more recent = higher weight)
3. Distance from current price (closer = more relevant)

### 4.5 Failed Level Handling

A level that is broken (price closes beyond it) is classified as:
- **Broken support** → becomes resistance
- **Broken resistance** → becomes support

The failed level is retained with `status: "broken"` and `brokenAt: timestamp`.

### 4.6 Mathematical Classification

All level classifications are:

| Classification | Method | Type |
|---|---|---|
| Swing detection | N-bar fractal | Mathematically derived |
| Support/Resistance | Bounce reaction | Descriptive |
| Clustering | Distance-based grouping | Descriptive |
| Level strength | Touch count × recency weight | Descriptive |
| Failed level | Price close beyond level | Empirically defined |

**None of these are predictive claims.** They are historical pattern labels.

---

## 5. GEX → Forward Outcome Research

### 5.1 Test Design

For each GEX feature, the research procedure is:

1. **Rank observations** by the feature value
2. **Partition into quintiles** (Q1 = lowest, Q5 = highest)
3. **Compute forward outcomes** for each quintile
4. **Compare extreme quintiles** (Q1 vs Q5) against the full-sample baseline
5. **Compute effect size** (Cohen's d or rank-biserial correlation)
6. **Compute confidence intervals** (block bootstrap for time-series)
7. **Report statistical significance** (with corrections for multiple testing)

### 5.2 Feature Test Matrix

For each feature × horizon combination:

| Feature | Source | Unit | Null Hypothesis |
|---|---|---|---|
| `netGex` | Phase 7.1 | GEX units | No difference in forward returns across quintiles |
| `normalizedNetGex` | Phase 7.4 | dimensionless | Same as above |
| `deltaGex` | Phase 7.3 | GEX units | Same as above |
| `velocity` | Phase 7.4 | GEX/second | Same as above |
| `acceleration` | Phase 7.4 | GEX/second² | Same as above |
| `volatility` | Phase 7.4 | GEX units | Same as above |
| `concentrationTop3` | Phase 7.4 | percentage | Same as above |
| `gexPercentile` | Phase 7.4 | percentile (0–100) | Same as above |
| `descriptiveZ` | Phase 7.4 | z-score | Same as above |
| `callGexShare` | Phase 7.4 | percentage | Same as above |
| `gammaFlipDistancePct` | Phase 7.2 | percentage | Same as above |
| `callWallDistancePct` | Phase 7.2 | percentage | Same as above |
| `putWallDistancePct` | Phase 7.2 | percentage | Same as above |
| `dte` | Phase 7.3 | days | Same as above |

**Total tests:** 14 features × 6 horizons = 84 primary tests

### 5.3 Quintile Analysis Protocol

For feature `F` and horizon `H`:

1. Collect all observations where `F` is non-null
2. Sort by `F` ascending
3. Divide into 5 equal quintiles
4. For each quintile `q`:
   - Compute mean, median, std of `H.return`
   - Compute mean `H.maxFavorableExcursion`
   - Compute mean `H.maxAdverseExcursion`
   - Compute hit rate: `mean(H.direction == +1)`
5. Compute baseline: same statistics over all observations
6. Compute **lift**: `(quintile_mean - baseline_mean) / |baseline_mean|` (or absolute difference if baseline ≈ 0)
7. Compute **Cohen's d**: `(mean_Q5 - mean_Q1) / pooled_stddev`

### 5.4 Effect Size Interpretation

| Cohen's d | Interpretation |
|---|---|
| \|d\| < 0.2 | Negligible |
| 0.2 ≤ \|d\| < 0.5 | Small |
| 0.5 ≤ \|d\| < 0.8 | Medium |
| \|d\| ≥ 0.8 | Large |

**These are descriptive labels, not claims of practical significance.** A "large" effect in a noisy market may not be tradeable.

---

## 6. Conditional / Interaction Analysis

### 6.1 Interaction Pairs

| Pair | Research Question |
|---|---|
| `netGex × velocity` | Does the direction of GEX change matter more at extreme GEX levels? |
| `netGex × concentration` | Is concentrated GEX more informative than diffuse GEX? |
| `velocity × acceleration` | Does accelerating GEX change have different forward behavior? |
| `gammaFlipDistancePct × netGex` | Is proximity to flip more meaningful when GEX is extreme? |
| `concentration × volatility` | Is concentrated GEX in a volatile environment more significant? |
| `callGexShare × netGex` | Does the call/put balance matter at different GEX magnitudes? |
| `dte × netGex` | Is GEX more informative closer to expiry? |
| `dte × concentration` | Is concentrated near-term GEX different from concentrated far-term? |

### 6.2 Interaction Test Design

For each pair `(A, B)`:
1. Partition `A` into terciles (Low/Medium/High)
2. Partition `B` into terciles (Low/Medium/High)
3. Create 9 cells (3×3 grid)
4. Compute forward outcomes for each cell
5. Test for interaction: does the effect of `A` on forward returns **depend on** `B`?

**Statistical method:** Two-way ANOVA (for normally distributed outcomes) or Kruskal-Wallis (non-parametric alternative). Report interaction p-value.

### 6.3 Correlation vs Causation

The design explicitly classifies findings:

| Classification | Definition |
|---|---|
| **Correlation** | Feature and outcome co-move statistically |
| **Conditional association** | Feature-outcome relationship changes conditional on another variable |
| **Predictive information** | Feature adds incremental information beyond baseline (Section 9) |

**Causation is never claimed.** GEX is a derived options-positioning metric. Any observed relationship with price may be:
- A direct mechanical effect (gamma hedging by dealers)
- A confound (both driven by a third factor, e.g., realized volatility)
- A statistical artifact

---

## 7. Regime Analysis

### 7.1 Regime Definitions

Regimes are **observable structural labels**, not predictive claims.

| Regime | Definition | Method | Type |
|---|---|---|---|
| GEX sign | netGex > 0 (positive) vs < 0 (negative) | Direct observation | Mathematically derived |
| GEX magnitude | \|netGex\| relative to historical distribution | Rolling percentile | Data-driven |
| Concentration | concentrationTop3 relative to history | Rolling percentile | Data-driven |
| GEX volatility | ΔGEX volatility relative to history | Rolling percentile | Data-driven |
| Flip proximity | gammaFlipDistancePct relative to history | Rolling percentile | Data-driven |
| Expiry proximity | DTE buckets: NEAR(≤7), MID(≤30), FAR(>30) | Direct from DTE | Mathematically derived |

### 7.2 Threshold Method

**No hard-coded thresholds.** All magnitude-based regimes use **rolling percentiles**:

```
regime(value, history) :=
  if percentileRank(value, history) ≥ 80 → "high"
  if percentileRank(value, history) ≤ 20 → "low"
  else → "neutral"
```

**Window:** 50 observations (approximately 4 hours at 5-min intervals)

**Why rolling percentiles?**
- Adapt to changing market conditions (no fixed thresholds that become stale)
- Naturally handle non-stationary distributions
- Allow comparison across different spot levels and volatility environments

### 7.3 Regime Transition Analysis

Track how regimes change over time:
- How often does GEX sign flip?
- How long do extreme concentration regimes persist?
- Do regime transitions predict anything about forward outcomes?

**This is descriptive only.** Regime persistence is measured, not assumed.

---

## 8. Statistical Integrity

### 8.1 Look-Ahead Bias Prevention

| Risk | Mitigation |
|---|---|
| Using future GEX values | GEX features are time-stamped; only data available at `capturedAt` is used |
| Using future candles for outcomes | Forward outcomes computed strictly from candles AFTER `capturedAt` |
| Using future option-chain data | GEX snapshot uses chain data from capture time only |
| Using future level detection | Levels confirmed AFTER confirmation window; observation timestamp = confirmation time |

### 8.2 Data Leakage Prevention

| Risk | Mitigation |
|---|---|
| Training/test overlap | Strict chronological split (Section 10) |
| Parameter tuning on test set | Parameters frozen on training set; validation set for final check |
| Feature selection leakage | Feature list fixed before any testing; no data-driven feature selection |
| Multiple testing leakage | Holm-Bonferroni correction applied to all p-values |

### 8.3 Survivorship Bias

**No survivorship bias possible** because:
- All observations are from a single, continuously traded instrument (NIFTY)
- No observations are dropped based on outcomes
- No filtering based on "interesting" patterns
- Missing data is handled by exclusion with documentation

### 8.4 Overlapping Forward Windows

Forward windows overlap because consecutive observations share candles. This violates i.i.d. assumptions.

**Mitigation:** Block bootstrap with block size = average observation interval / candle interval. For 5-minute GEX with 3-minute candles, blocks of 2 candles.

### 8.5 Autocorrelation

GEX observations are serially correlated (each snapshot is related to the previous one). Ordinary t-tests are invalid.

**Mitigation:**
1. **Newey-West (HAC) standard errors** for regression-based tests
2. **Block bootstrap** for confidence intervals
3. **Permutation tests** with block shuffling (preserve autocorrelation structure)

> **Phase 7.7 implementation note:** Block bootstrap (item 2) has been implemented with configurable block size (default: 2).  **Newey-West HAC standard errors (item 1) have NOT been implemented.**  The current baseline comparison uses a simplified max-correlation R² approach rather than full OLS with HAC standard errors.  This is acceptable for the current research foundation — the block bootstrap provides valid confidence intervals for the quintile analysis.  However, **HAC/Newey-West should be added before relying on regression-based inferential conclusions** in future phases.  This is a documented limitation, not something silently claimed as implemented.

### 8.6 Multiple Hypothesis Testing

84 primary tests (14 features × 6 horizons) plus interaction tests. Family-wise error rate inflates.

**Mitigation:**
1. **Holm-Bonferroni** correction within each family (feature group or horizon group)
2. **Benjamini-Hochberg** FDR control for exploratory analysis
3. Report both raw and adjusted p-values

### 8.7 Sample Size Requirements

| Minimum | Rationale |
|---|---|
| 200 observations | For stable quintile means (Central Limit Theorem) |
| 50 observations per quintile | For stable within-quintile statistics |
| 500+ observations | For reliable block bootstrap confidence intervals |
| 1000+ observations | For interaction effects (9 cells, ~110 per cell) |

**Data collection plan:** At 5-minute intervals during NSE market hours (9:15–15:30 IST = ~125 candles/day), 200 snapshots/day, ~4000 snapshots/month. A 6-month collection yields ~12,000 observations.

### 8.8 Missing Snapshots / Irregular Timestamps

- Observations with missing GEX features are excluded from tests using that feature
- No interpolation of missing GEX values
- Irregular timestamps are handled naturally by time-difference-based velocity/acceleration
- Missing candle data (holidays, market closures) creates natural gaps

### 8.9 Expiry Transitions / Strike-Set Changes

- Expiry transitions are flagged in metadata; regime analysis includes DTE as a feature
- Strike-set changes affect concentration calculations; the intersection-based decomposition in Phase 7.3 already handles this
- Methodology-version mismatches are flagged and excluded from cross-version comparisons

### 8.10 Changing Market Volatility / Spot Levels

- **Non-stationarity addressed by:** rolling windows, percentile-based normalization, regime-conditional analysis
- **Spot-level effects:** `normalizedNetGex` is dimensionless; additional tests control for `spot` level
- **Volatility regime:** `realizedVolatility` computed for each observation; included as a control variable

---

## 9. In-Sample / Out-of-Sample Framework

### 9.1 Chronological Split

```
|---- Training ----|---- Validation ----|---- Test (held out) ----|
      60%                20%                    20%
```

**No random shuffling.** Time-series order is preserved.

### 9.2 Walk-Forward Validation

For robustness, use walk-forward:

```
Window 1: [train: months 1-3] [val: month 4] [test: month 5]
Window 2: [train: months 2-4] [val: month 5] [test: month 6]
Window 3: [train: months 3-5] [val: month 6] [test: month 7]
...
```

Each window:
1. Parameters (window sizes, thresholds) are frozen on training data
2. Forward outcomes are computed on the test period
3. Results are aggregated across windows

### 9.3 Minimum History Requirements

| Requirement | Value | Rationale |
|---|---|---|
| Minimum observations for feature | 5 | For percentile/z-score computation |
| Minimum observations per quintile | 50 | For stable quintile statistics |
| Minimum training window | 500 observations | For reliable parameter estimation |
| Minimum total observations | 1000 | For meaningful train/val/test splits |
| Walk-forward minimum train | 300 observations | For stable in-window estimates |

### 9.4 Parameter Freezing

Parameters determined during training (e.g., SMA window sizes, percentile thresholds) are **frozen** before validation/test evaluation. The test set is never consulted during parameter selection.

---

## 10. Null / Baseline Models

GEX must prove incremental information beyond what price alone provides.

### 10.1 Baseline Features

| Baseline | Formula | Rationale |
|---|---|---|
| Previous return | (close_t - close_{t-1}) / close_{t-1} | Momentum |
| Realized volatility | stddev(returns, window=20) | Volatility clustering |
| ATR/range | (high - low) / close | Intraday range |
| Distance from 20-period high | (close - rolling_max(high, 20)) / close | Proximity to recent extreme |
| Distance from 20-period low | (close - rolling_min(low, 20)) / close | Proximity to recent extreme |
| Simple momentum | (close - close_{n}) / close_{n} | N-candle return |
| Time-of-day | Normalized market session position | Intraday patterns |

### 10.2 Incremental Information Test

For each GEX feature, test:

```
Model 1 (baseline): forward_return ~ baseline_features
Model 2 (GEX):      forward_return ~ baseline_features + gex_feature
Model 3 (full):     forward_return ~ baseline_features + all_gex_features
```

**Comparison:** Adjusted R², AIC, BIC. If GEX features do not improve Model 2 over Model 1, GEX adds no incremental information.

**Method:** OLS regression with Newey-West standard errors (HAC).

### 10.3 Non-Linear Baseline

If linear regression is insufficient, also test:
- **Random forest feature importance** (out-of-bag permutation importance)
- **Spearman rank correlation** between each feature and forward returns

These are **descriptive only** — they measure association strength, not predictive power.

---

## 11. Feature Leakage Audit

### 11.1 Information Availability Timeline

| Feature | Available At | Uses Future Data? |
|---|---|---|
| `netGex` | `capturedAt` (snapshot time) | No — uses option chain at capture |
| `normalizedNetGex` | `capturedAt` | No — derived from `netGex` and `spot` |
| `deltaGex` | `capturedAt` (needs previous snapshot) | No — uses two snapshots both before `capturedAt` |
| `velocity` | `capturedAt` (needs ≥2 previous snapshots) | No — uses only historical snapshots |
| `acceleration` | `capturedAt` (needs ≥3 previous snapshots) | No — uses only historical snapshots |
| `volatility` | `capturedAt` (needs ≥2 previous snapshots) | No — uses only historical snapshots |
| `concentrationTop3` | `capturedAt` | No — uses strike data at capture |
| `gexPercentile` | `capturedAt` (needs history) | No — uses only historical snapshots |
| `descriptiveZ` | `capturedAt` (needs history) | No — uses only historical snapshots |
| `callGexShare` | `capturedAt` | No — uses call/put GEX at capture |
| `gammaFlipSpot` | `capturedAt` | No — uses chain at capture for BS sweep |
| `gammaFlipDistancePct` | `capturedAt` | No — derived from `gammaFlipSpot` and `spot` |
| `callWallDistancePct` | `capturedAt` | No — uses chain at capture |
| `putWallDistancePct` | `capturedAt` | No — uses chain at capture |
| `dte` | `capturedAt` | No — uses `valuationDate` and `expiry` |
| `swingHigh/Low` | `confirmationWindow` after formation | No — uses historical candles only |
| `support/resistance` | After bounce confirmed | No — uses historical candles only |

### 11.2 Forward Outcomes

| Outcome | Available At | Uses Future Data? |
|---|---|---|
| `return` | After forward candles close | Yes — this IS the prediction target |
| `maxFavorableExcursion` | After forward candles close | Yes — this IS the prediction target |
| `maxAdverseExcursion` | After forward candles close | Yes — this IS the prediction target |
| `realizedVolatility` | After forward candles close | Yes — this IS the prediction target |

**Key rule:** Features and outcomes are **never** computed from overlapping candle windows. Features use data at or before `capturedAt`; outcomes use data strictly after `capturedAt`.

---

## 12. Research Output Schema

### 12.1 Research Result

```
ResearchResult {
  // Identity
  feature: string,                // e.g., "netGex", "velocity"
  condition: string | null,       // e.g., "quintile_Q5", "regime_positive_high"
  horizon: string,                // e.g., "candles10"
  
  // Sample
  sampleCount: number,
  dateRange: { start: string, end: string },
  
  // Outcome statistics
  meanOutcome: number,
  medianOutcome: number,
  stdOutcome: number,
  
  // Comparison
  effectSize: number | null,      // Cohen's d or equivalent
  confidenceInterval: { lower: number, upper: number } | null,
  pValue: number | null,
  adjustedPValue: number | null,  // after multiple testing correction
  
  // Baseline comparison
  baselineOutcome: number,
  incrementalImprovement: number | null,
  
  // Validation
  inSampleResult: ResearchResult | null,
  outOfSampleResult: ResearchResult | null,
  
  // Classification
  status: "INSUFFICIENT_DATA" | "NO_EVIDENCE" | "WEAK_ASSOCIATION" | "PROMISING" | "ROBUST_ASSOCIATION",
  
  // Metadata
  methodology: string,           // "quintile_analysis" | "regression" | "interaction"
  blockBootstrapUsed: boolean,
  autocorrelationAdjusted: boolean,
  multipleTestingCorrected: boolean,
}
```

### 12.2 Status Classification Rules

| Status | Criteria |
|---|---|
| `INSUFFICIENT_DATA` | sampleCount < 200 or per-quintile n < 30 |
| `NO_EVIDENCE` | adjusted p-value > 0.05 AND \|d\| < 0.2 |
| `WEAK_ASSOCIATION` | adjusted p-value ≤ 0.05 OR 0.2 ≤ \|d\| < 0.5 |
| `PROMISING` | adjusted p-value ≤ 0.01 AND 0.5 ≤ \|d\| < 0.8 AND survives OOS |
| `ROBUST_ASSOCIATION` | adjusted p-value ≤ 0.001 AND \|d\| ≥ 0.8 AND survives OOS AND replicates in walk-forward |

**These are research classifications, not trading signals.** A `ROBUST_ASSOCIATION` status means "this feature has a statistically strong relationship with forward outcomes in the data examined." It does NOT mean "trade on this."

---

## 13. Self-Learning Foundation

### 13.1 Architecture for Future Adaptation

```
Raw Market Data (candles + option chains)
        ↓
GEX Observations (Phase 7.1–7.6)
        ↓
Forward Outcomes (Phase 7.7 — retrospective)
        ↓
Research Experiments (Phase 7.7 — statistical tests)
        ↓
Validated Relationships (Phase 7.7 — robust associations)
        ↓
Feature Registry (Phase 7.7 — machine-readable feature catalog)
        ↓
[FUTURE] Adaptive Models
        ↓
[FUTURE] Strategy Signals
```

### 13.2 Feature Registry

A machine-readable catalog of validated features:

```
FeatureRegistry {
  version: string,
  features: [
    {
      name: string,
      source: string,           // "gex" | "price" | "combined"
      computation: string,      // function reference or formula
      validationStatus: string, // from ResearchResult.status
      validationDate: string,
      knownLimitations: string[],
      dataRequirements: {
        minObservations: number,
        minHistoryWindow: number,
      },
    }
  ]
}
```

### 13.3 What Phase 7.7 Does NOT Implement

- Machine learning models
- Adaptive thresholds
- Real-time signal generation
- Strategy execution
- Portfolio allocation
- Risk management

Phase 7.7 establishes the **evidence base** that future phases can build on.

---

## 14. Mathematical Audit

### 14.1 All Proposed Methods — Classification

| Method | Classification | Status |
|---|---|---|
| GEX formula (γ × OI × S² × 0.01) | Mathematically derived | Phase 7.1 — validated |
| Normalized GEX (netGex / S² × 0.01) | Mathematically derived | Dimensionless normalization |
| Quintile analysis | Descriptive | Standard non-parametric method |
| Cohen's d effect size | Descriptive | Standard effect size measure |
| Block bootstrap | Statistical | Appropriate for serially dependent data |
| Newey-West (HAC) | Statistical | Corrects for autocorrelation + heteroskedasticity |
| Holm-Bonferroni | Statistical | Conservative multiple testing correction |
| Benjamini-Hochberg | Statistical | FDR control, less conservative |
| Swing high/low detection | Descriptive | N-bar fractal — standard TA |
| Level clustering | Descriptive | Distance-based grouping |
| Regime classification | Descriptive | Rolling percentile — data-driven |
| OLS regression (HAC) | Statistical | Standard with autocorrelation correction |
| Walk-forward validation | Statistical | Appropriate for time-series |
| Kruskal-Wallis | Statistical | Non-parametric alternative to ANOVA |
| Feature importance (RF) | Descriptive | Out-of-bag permutation importance |

### 14.2 Assumptions

| Assumption | Validity | Risk |
|---|---|---|
| GEX reflects dealer positioning | Hypothesized, not proven | May be wrong — dealers may not hedge dynamically |
| 5-min GEX captures meaningful state | Assumed | May be too frequent (noise) or too infrequent (miss moves) |
| 3-min candles are sufficient resolution | Assumed | May need 1-min for microstructure effects |
| N-bar fractal captures support/resistance | Standard TA assumption | Not universally accepted |
| Block bootstrap validity | Valid for weakly dependent sequences | May break down for regime-switching data |
| Normal distribution of forward returns | Approximate for intraday | Fat tails common in options markets |

### 14.3 Unvalidated Claims

**No claims are made until empirically validated.** The entire Phase 7.7 output is:
- Statistical measurements
- Effect sizes
- Confidence intervals
- Classification labels (INSUFFICIENT_DATA through ROBUST_ASSOCIATION)

None of these constitute:
- Predictive claims
- Causal claims
- Trading recommendations
- Probability of profit estimates

---

## 15. Architecture

### 15.1 Module Design

**4 focused modules** (following the Phase 7.4 pattern):

| Module | Lines (est.) | Responsibility |
|---|---|---|
| `gexResearchData.js` | ~350 | Observation construction, forward outcomes, candle data interface |
| `gexResearchTests.js` | ~400 | Quintile analysis, effect sizes, regression, interaction tests |
| `gexResearchValidation.js` | ~300 | Walk-forward, in/out-of-sample, robustness checks |
| `gexResearchRegistry.js` | ~200 | Feature registry, research output schema, status classification |

**Backend (1 new module):**

| Module | Lines (est.) | Responsibility |
|---|---|---|
| `services/nifty_candles.py` | ~150 | Candle storage, querying, retention |

### 15.2 Data Flow

```
Upstox Historical Candle API
        ↓ (backend collection job)
nifty_candles table (backend)
        ↓ (GET /candles)
gexResearchData.js
  - constructObservation(snapshot, candles)
  - computeForwardOutcomes(observation, candles)
  - buildResearchDataset(snapshots, candles)
        ↓
gexResearchTests.js
  - quintileAnalysis(feature, horizon, dataset)
  - regressionTest(features, horizon, dataset)
  - interactionTest(pair, horizon, dataset)
  - regimeConditionalAnalysis(regime, feature, dataset)
        ↓
gexResearchValidation.js
  - walkForward(dataset, config)
  - inSampleOutOfSample(dataset, config)
  - robustnessCheck(results)
        ↓
gexResearchRegistry.js
  - classifyResult(testResult)
  - registerFeature(name, validation)
  - exportRegistry()
```

### 15.3 Separation of Concerns

| Concern | Owner | NOT in |
|---|---|---|
| GEX calculation | Phase 7.1–7.6 (untouched) | Research modules |
| Candle data storage | Backend `nifty_candles.py` | Frontend research |
| Observation construction | `gexResearchData.js` | Backend |
| Statistical testing | `gexResearchTests.js` | Backend, dashboard |
| Validation framework | `gexResearchValidation.js` | Backend |
| Feature registry | `gexResearchRegistry.js` | Backend, dashboard |

**No coupling to the dashboard.** Research modules are pure calculation.

---

## 16. Implementation Plan

### 16.1 Files to Create

| File | Purpose | Est. Lines |
|---|---|---|
| `docs/GEX_PHASE_7_7_DESIGN.md` | This document | ~800 |
| `frontend/lib/calculations/gexResearchData.js` | Observation + outcome construction | ~350 |
| `frontend/lib/calculations/gexResearchData.test.js` | Data construction tests | ~300 |
| `frontend/lib/calculations/gexResearchTests.js` | Statistical tests | ~400 |
| `frontend/lib/calculations/gexResearchTests.test.js` | Statistical test tests | ~350 |
| `frontend/lib/calculations/gexResearchValidation.js` | Walk-forward, OOS | ~300 |
| `frontend/lib/calculations/gexResearchValidation.test.js` | Validation tests | ~250 |
| `frontend/lib/calculations/gexResearchRegistry.js` | Feature registry | ~200 |
| `frontend/lib/calculations/gexResearchRegistry.test.js` | Registry tests | ~150 |
| `backend/app/services/nifty_candles.py` | Candle persistence | ~150 |
| `backend/app/models.py` | NiftyCandle model (additive) | +15 |
| `backend/tests/test_nifty_candles.py` | Candle service tests | ~150 |

**Total estimated:** ~3,415 lines (production + tests)

### 16.2 Files to Modify

| File | Change | Lines |
|---|---|---|
| `backend/app/models.py` | Add `NiftyCandle` model | +15 |
| `backend/app/db.py` | Add `ensure_column` if needed | +1 |
| `backend/app/main.py` | Register candle router (if API needed) | +2 |

### 16.3 Database Changes

New table: `nifty_candles`

```
NiftyCandle {
  id: INTEGER PRIMARY KEY
  symbol: VARCHAR(16)           -- "NIFTY"
  interval: VARCHAR(8)          -- "3min" | "5min" | "15min" | "1day"
  timestamp: DATETIME           -- candle open time (UTC), indexed
  open: FLOAT
  high: FLOAT
  low: FLOAT
  close: FLOAT
  volume: FLOAT                 -- informational
  
  UNIQUE(symbol, interval, timestamp)
}
```

**Retention:** 365 days (configurable)  
**Expected volume:** ~125 candles/day × 365 = ~45,625 rows per symbol  
**Storage:** ~3 MB per year per symbol (negligible)

### 16.4 Tests

| Test Category | Count (est.) | What |
|---|---|---|
| Data construction | 25 | Observation building, forward outcomes, edge cases |
| Quintile analysis | 20 | Feature ranking, quintile statistics, effect sizes |
| Regression | 15 | OLS with HAC, baseline comparison |
| Interaction | 10 | Two-way analysis, conditional effects |
| Walk-forward | 10 | Parameter freezing, window sliding, OOS |
| Robustness | 10 | Bootstrap, permutation, multiple testing |
| Edge cases | 15 | Missing data, insufficient history, constant values |
| Registry | 10 | Feature catalog, status classification |
| **Total** | **~115** | |

### 16.5 Computational Complexity

| Operation | Complexity | Frequency |
|---|---|---|
| Observation construction | O(n_strikes) per snapshot | Once per observation |
| Forward outcome computation | O(n_candles) per observation | Once per observation |
| Quintile analysis | O(n log n) per feature | Once per experiment |
| Regression (OLS) | O(n × k²) for k features | Once per experiment |
| Block bootstrap | O(B × n) for B resamples | Once per test |
| Walk-forward | O(n_windows × single_run) | Once per validation |

**At 12,000 observations:** All computations complete in <10 seconds on modern hardware. No performance optimization needed.

### 16.6 Data Volume Expectations

| Data | Volume | Growth Rate |
|---|---|---|
| GEX snapshots (5-min, 90-day) | ~21,600 rows | 200/day |
| NIFTY candles (3-min, 365-day) | ~45,625 rows | 125/day |
| Research observations | ~21,600 rows | 200/day |
| Research results | ~200 rows per experiment | Fixed per experiment |
| Feature registry | ~20 rows | Static |

**Total database growth:** ~70,000 rows/year — negligible.

### 16.7 Validation Strategy

Phase 7.7 implementation is validated by:

1. **Unit tests:** Every function has independent tests with known inputs/outputs
2. **Mathematical tests:** Synthetic data with known relationships validates statistical methods
3. **Integration tests:** End-to-end from observation construction to research result
4. **Regression tests:** Existing Phase 7.1–7.6 tests must remain passing
5. **Manual inspection:** Research results reviewed for obvious anomalies

---

## 17. Explicit Non-Goals

| Non-Goal | Why Excluded |
|---|---|
| Machine learning | Evidence must come first; ML without evidence overfits |
| Trading signals | Phase 7.7 is research, not strategy |
| Real-time research dashboard | premature until relationships validated |
| Automated strategy generation | Requires validated evidence first |
| Multi-asset research | Start with NIFTY; generalize later |
| Options strategy optimization | Separate concern from GEX validation |
| Backtesting engine | Different from forward-outcome research |
| Portfolio construction | Different concern from GEX validation |

---

## 18. Risks and Open Questions

### 18.1 Open Questions

| Question | Impact | Resolution |
|---|---|---|
| Does Upstox provide historical intraday candles? | Must verify API availability | Check Upstox docs; fallback to daily candles |
| Is 3-minute the right candle interval? | Affects granularity of forward outcomes | Default to 3-min; make configurable |
| Is 5-minute GEX capture frequency sufficient? | Affects feature resolution | Existing 5-min default; configurable |
| How many months of data are needed? | Affects statistical power | Minimum 3 months; 6+ preferred |
| Do dealer hedging patterns exist in Indian markets? | Fundamental validity | Empirical test — Phase 7.7's purpose |

### 18.2 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Insufficient candle data from Upstox | Medium | Cannot compute forward outcomes | Fallback to daily candles; request data |
| GEX shows no relationship with forward outcomes | Medium | Research confirms null result | Valid and valuable finding |
| Relationships found are spurious | Medium | Misleading conclusions | OOS validation, walk-forward, baselines |
| Statistical methods inappropriate for data | Low | Invalid conclusions | Multiple methods, robustness checks |
| Look-ahead bias despite prevention | Low | Inflated results | Formal information-availability audit |

---

## 19. Appendix: Data Pipeline Summary

```
Phase 7.1–7.6 (existing, untouched):
  Upstox option chain → chainGex() → GEX snapshots
  
Phase 7.7 (new):
  Upstox historical candles → nifty_candles table
  GEX snapshots + candles → Research observations
  Research observations → Forward outcomes
  Forward outcomes → Statistical tests
  Statistical tests → Research results
  Research results → Feature registry
```

---

*End of Phase 7.7 Design Document*
