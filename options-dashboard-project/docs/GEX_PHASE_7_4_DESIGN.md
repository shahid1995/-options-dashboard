# Options Dashboard — GEX Phase 7.4: Advanced Time-Series Analytics

**Date:** 2026-08-22
**Status:** Revised design — awaiting approval
**Predecessors:** Phase 7.1 (foundation), 7.2 (flip/walls), 7.3 (history/ΔGEX)
**Scope:** Advanced time-series analytics, regime classification, concentration analysis
**Boundaries:** Analytics only — no trading signals, no UI, no API, no deployment

---

## 0. Revision Notes — Addressing All 12 Audit Points

| # | Audit Point | Resolution |
|---|---|---|
| 1 | Rename Net GEX SMA vs ΔGEX SMA confusion | All rolling averages applied to **cumulative Net GEX** are renamed `NetGex` + suffix (e.g., `NetGexSma`). All rolling averages applied to **sequential ΔGEX** are renamed `DeltaGex` + suffix (e.g., `DeltaGexSma`). No shared "GEX SMA" label exists. |
| 2 | Expiry continuity vs composition changes | Expiry transitions are **detected and flagged** (`expiryChanged: true`) but **not used as reset triggers** for historical context. A composition change simply means subsequent metrics carry a metadata flag. The ring buffer and rolling windows continue operating on continuous timestamps. |
| 3 | Changing strike coverage affecting decomposition | Strike coverage changes are **explicitly documented** per snapshot (`strikeSet: { count, min, max }`). Only strikes present in **both** snapshots participate in decomposition. Missing strikes in one snapshot contribute to the residual. The strike-set delta is surfaced in the decomposition metadata. |
| 4 | Regime thresholds experimental/configurable | All thresholds are passed as a **config object** with documented defaults. Defaults are labeled `EXPERIMENTAL_DEFAULT`. The regime function returns `{ label, confidence: "experimental" }`. No threshold is treated as a universal constant. |
| 5 | Regime as structural label, not market regime | The classification is called **GEX Profile Label** throughout. Documentation states it is a "structural description of the current GEX geometry, not a validated market regime." No forward-looking interpretation is attached. |
| 6 | Call/put ratio → Call GEX Share | The metric is `callGexShare = callGex / (callGex + |putGex|) × 100`. Label is "Call GEX Share (%)". No claim about directional positioning. |
| 7 | Z-scores as descriptive statistics only | Z-scores are labeled `descriptiveZ`. Documentation states: "A descriptive z-score measures how many standard deviations the current value is from the rolling mean. It does NOT claim statistical significance. ±2 or ±3 thresholds are descriptive labels, not validated signals." |
| 8 | Velocity/acceleration with actual timestamps | Velocity is defined as **ΔGEX / Δt** using the actual `deltaTimeMs` between captured snapshots. Acceleration is **Δvelocity / Δt** over successive pairs. No fixed-interval assumption. |
| 9 | Freshness using snapshot timestamps | Freshness = `now - latestSnapshot.capturedAt`. The timestamp is the one **recorded in the snapshot at capture time**, not the current wall clock. Stale data is explicitly surfaced. |
| 10 | DTE calculation and expiry bucket boundaries | DTE is computed from `expiry_date` in the snapshot using `timeToExpiry()` from `pricing.js`. Buckets are: `NEAR` (DTE ≤ 7), `MID` (8 ≤ DTE ≤ 30), `FAR` (DTE > 30). Boundary values are inclusive at the lower bound. |
| 11 | Avoid monolithic module | Split into **4 focused modules** (~200–350 lines each), each with its own test file. |
| 12 | Separate measurements from context from classification | Three-layer architecture: **Raw Measurements → Statistical Context → Structural Classification**. |

---

## 1. Purpose

Phase 7.4 builds on the Phase 7.1–7.3 GEX foundation to produce higher-level
market-structure analytics. Every metric remains an analytical measurement — none
become trading signals in this phase.

The objectives are:

1. Provide rolling ΔGEX analytics (moving average, velocity, acceleration, volatility)
2. Enhance migration analysis (sustained trends, direction history)
3. Add concentration percentile (historical context)
4. Add GEX percentile/rank (historical distribution context)
5. Implement GEX Profile Label classification (transparent structural geometry label)
6. Track gamma flip and gamma wall history over time
7. Decompose analytics by expiry bucket (NEAR/MID/FAR)
8. Establish data-quality and methodology-consistency metrics
9. Define the interface through which future Strategy Builder can consume analytics

---

## 2. Existing Implementation Audit

### 2.1 Phase 7.1 (`gex.js` — untouched, consumed)

Core GEX calculation engine. Pure functions, no state.

| Function | Formula | Gamma Source |
|---|---|---|
| `rawGex(gamma, oi, spot)` | gamma × oi × spot² × 0.01 | Caller-provided |
| `signedGex(type, gamma, oi, spot)` | +rawGex (call) / −rawGex (put) | Caller-provided |
| `strikeGex(row, spot)` | Per-strike CE/PE/Net | Broker gamma |
| `expiryGex(rows, spot)` | Per-expiry aggregation | Broker gamma |
| `chainGex(rows, options)` | Full chain with by-expiry/by-strike | Broker gamma |

**Formula:** `GEX_i = γ_broker_i × OI_i × S² × 0.01`
**OI unit:** Contracts (verified — no lot-size multiplication)
**Sign convention:** NAIVE_DEALER_CONVENTION (call=+, put=−)

### 2.2 Phase 7.2 (`gexPhase72.js` — untouched, consumed)

Spot-sweep and model-validation module.

| Function | Purpose | Gamma Source |
|---|---|---|
| `modelGamma(type, S, K, T, sigma, r, q)` | BS gamma at hypothetical spot | **BS model** |
| `detectZeroCrossings(sweepPoints)` | Gamma flip detection | N/A (input) |
| `findGammaWalls(strikeGexList, spot, topN)` | Directional wall detection | Broker gamma |
| `selectPrimaryFlip(spot, crossings, quality, range)` | Multi-factor flip ranking | N/A (input) |
| `spotSweep(chainRows, options)` | Full sweep with per-expiry T | **BS model** |
| `brokerVsModelGamma(rows, spot, T, r, q)` | Comparison at current spot | Both |

### 2.3 Phase 7.3 (`gexHistory.js` — untouched, consumed)

Historical snapshots, ΔGEX decomposition, migration, concentration, ring buffer.

| Function | Purpose | Gamma Source |
|---|---|---|
| `captureGexSnapshot(chain, spot, ts, opts)` | Snapshot from chain | Broker gamma |
| `computeDeltaGex(a, b)` | Total ΔGEX | Broker gamma (from snapshots) |
| `computeSpotDeltaGex(a, b)` | Mechanical spot ΔGEX | **Broker gamma** (frozen from A) |
| `computeStructureDeltaGex(a, b, opts)` | OI/IV attribution | **BS model gamma** |
| `decomposeDeltaGex(a, b, opts)` | Full decomposition | Both (see docstring) |
| `computeGexMigration(a, b, threshold)` | Centroid shift | Broker gamma |
| `computeStrikeCentroid(strikeData)` | Gamma-weighted centroid | Broker gamma |
| `computeConcentration(strikeData)` | Top-N share | Broker gamma |
| `assembleGexTimeSeries(source, opts)` | Charting data | Broker gamma |
| `reconstructChainRows(snapshot)` | Reproducibility | N/A |
| `GexRingBuffer` | FIFO ring buffer | N/A |

### 2.4 Existing Statistics Module (`statistics.js` — reusable, untouched)

| Function | Purpose | Reuse in 7.4 |
|---|---|---|
| `rollingMean(values)` | Arithmetic mean | ΔGEX SMA |
| `rollingStdDev(values)` | Population σ | ΔGEX volatility, z-scores |
| `rollingMedian(values)` | Median | Robust baseline |
| `rollingMin(values)` / `rollingMax(values)` | Range | Min/max history |
| `zScore(value, history, opts)` | Descriptive z-score | Descriptive context |
| `percentileRank(value, history, opts)` | Mean-rank percentile | GEX percentile |
| `anomalyMeasurement(value, history, opts)` | 0–100 unusualness | Descriptive anomaly |
| `cleanNumber(v)` / `cleanNumbers(arr)` | Safe filtering | Universal |

---

## 3. Gamma Source Discipline (Persistent Across All 7.4 Metrics)

**Every metric explicitly documents which gamma source it uses:**

| Label | Source | What It Measures |
|---|---|---|
| **Broker gamma** | Upstox `option_greeks.gamma` as observed at capture time | Actual market-observed gamma; used for GEX history, migration, walls, concentration, velocity, acceleration |
| **BS model gamma** | Black-Scholes `modelGamma()` with frozen IV | Deterministic model function; used only for OI/IV attribution in decomposition and spot-sweep |

**Rule:** Phase 7.4 metrics operating on **snapshot time-series** (velocity, acceleration, volatility, percentile, regime) always consume **broker-gamma-derived** values from Phase 7.1/7.3. BS model gamma is never silently substituted.

---

## 4. Architecture — Three Layers

```
Layer 1: RAW MEASUREMENTS (from Phase 7.1–7.3, consumed directly)
    Net GEX, ΔGEX, migration, concentration, flip, walls
         ↓
Layer 2: STATISTICAL CONTEXT (rolling windows, z-scores, percentiles)
    ΔGEX SMA, velocity, acceleration, volatility,
    concentration percentile, GEX percentile, freshness
         ↓
Layer 3: STRUCTURAL CLASSIFICATION (composite label from Layer 1+2)
    GEX Profile Label (geometric description only)
         ↓
Future: EMPIRICAL VALIDATION (Phase 7.7+)
    Backtesting, predictive testing, Strategy Builder conditions
```

**No metric in Layers 1–3 generates trading signals.** The GEX Profile Label is a structural description, not a market prediction.

---

## 5. Module Structure (4 files, ~200–350 lines each)

```
frontend/lib/calculations/
├── gex.js                    (Phase 7.1 — untouched)
├── gexPhase72.js             (Phase 7.2 — untouched)
├── gexHistory.js             (Phase 7.3 — untouched)
├── gexTimeSeries.js          (Phase 7.4a — rolling analytics, velocity, acceleration)
├── gexTimeSeries.test.js
├── gexConcentration.js       (Phase 7.4b — concentration, percentile, expiry decomposition)
├── gexConcentration.test.js
├── gexProfileLabel.js        (Phase 7.4c — structural classification)
├── gexProfileLabel.test.js
└── gexAnalytics.js           (Phase 7.4d — coordinator, time-series assembly, SB interface)
    gexAnalytics.test.js
```

**Why split:** Each module is independently testable, conceptually focused, and stays under 350 lines. No single 800+ line file.

---

## 6. Phase 7.4a — `gexTimeSeries.js` — Rolling ΔGEX Analytics

### 6.1 Dependencies

- Phase 7.3: `computeDeltaGex()`, `computeSpotDeltaGex()`, `decomposeDeltaGex()`, `computeGexMigration()`, `GexRingBuffer`
- `statistics.js`: `rollingMean`, `rollingStdDev`, `rollingMin`, `rollingMax`
- Phase 7.1/7.2: consumed indirectly through snapshots

### 6.2 Constants (Configurable)

```js
export const DEFAULT_VELOCITY_WINDOW = 6;       // snapshots (not time — actual count)
export const DEFAULT_VOLATILITY_WINDOW = 10;     // snapshots
export const DEFAULT_SMA_WINDOW = 10;            // snapshots for NetGexSma and DeltaGexSma
```

### 6.3 Exports

#### `computeNetGexSma(snapshots, window)`

**Purpose:** Rolling simple moving average of cumulative Net GEX values.

**Formula:**
```
NetGexSma_i = (1/window) × Σ NetGex(t_j)  for j ∈ [i − window + 1, i]
```

Where `NetGex(t_j)` is the `netGex` field from snapshot at index j.

**Gamma source:** Broker (snapshots contain broker-gamma-derived GEX).

**Inputs:** Array of snapshots (chronologically sorted), window size.

**Output:**
```js
{
  sma: number | null,        // current SMA value
  history: Array<{ timestamp, value }>,  // SMA at each point
  windowSize: number,
  availablePoints: number,   // how many points contributed
  status: "available" | "partial" | "unavailable"
}
```

**Edge cases:**
- Fewer points than window → compute with available points (partial status)
- All null netGex → status: unavailable, sma: null
- Single point → sma = that point's netGex (partial)

**What it does NOT prove:** That Net GEX is trending in any direction. An SMA is a lagged average, not a trend indicator.

---

#### `computeDeltaGexSma(snapshots, window)`

**Purpose:** Rolling SMA of sequential ΔGEX values.

**Formula:**
```
ΔGEX_i = NetGex(t_i) − NetGex(t_{i−1})          [from Phase 7.3 computeDeltaGex]
DeltaGexSma_i = (1/window) × Σ ΔGEX_j  for j ∈ [i − window + 1, i]
```

**Gamma source:** Broker.

**Output:** Same structure as `computeNetGexSma`.

**Distinction from NetGexSma:** NetGexSma smooths the cumulative level. DeltaGexSma smooths the sequential change. These answer different questions.

---

#### `computeVelocity(snapshots, window)`

**Purpose:** Rate of GEX change per unit time.

**Formula:**
```
velocity_i = ΔGEX_i / Δt_i

where:
  ΔGEX_i  = NetGex(t_i) − NetGex(t_{i−1})           [Phase 7.3]
  Δt_i    = (capturedAt_i − capturedAt_{i−1}) / 1000   [seconds, from snapshot timestamps]
```

**Unit:** GEX units per second.

**IMPORTANT:** Uses actual `capturedAt` timestamps from snapshots, NOT assumed fixed intervals. If two snapshots are 300 seconds apart and ΔGEX is 5,000,000, velocity = 16,667 GEX/sec. If the next pair is 600 seconds apart with ΔGEX of 10,000,000, velocity = 16,667 GEX/sec (same rate).

**Gamma source:** Broker.

**Output:**
```js
{
  velocity: number | null,           // current velocity
  history: Array<{ timestamp, value, deltaTimeSec }>,
  status: "available" | "partial" | "unavailable"
}
```

**Edge cases:**
- deltaTimeSec = 0 → velocity = null (division by zero avoided)
- deltaTimeSec < 0 → velocity = null (time went backwards — data quality issue)
- Only 1 pair available → single velocity point (partial)

**What it does NOT prove:** That GEX is "accelerating" or "decelerating" based on a single velocity measurement. Velocity must be compared across time to observe acceleration.

---

#### `computeAcceleration(snapshots, velocityWindow)`

**Purpose:** Rate of change of velocity.

**Formula:**
```
acceleration_i = (velocity_i − velocity_{i−1}) / Δt_i

where:
  velocity is computed with the given window
  Δt_i = (capturedAt_i − capturedAt_{i−1}) / 1000
```

**Unit:** GEX units per second².

**Gamma source:** Broker.

**Output:**
```js
{
  acceleration: number | null,
  history: Array<{ timestamp, value, deltaTimeSec }>,
  status: "available" | "partial" | "unavailable"
}
```

**Edge cases:** Same as velocity. Requires at least 2 velocity points (i.e., at least 3 snapshots).

**What it does NOT prove:** That market dynamics are changing. Acceleration is a second derivative of GEX, which is itself a model-derived quantity. Interpretation requires empirical validation (Phase 7.7).

---

#### `computeDeltaGexVolatility(snapshots, window)`

**Purpose:** Rolling standard deviation of sequential ΔGEX values — measures how variable the GEX changes are.

**Formula:**
```
ΔGEXVolatility_i = stddev({ ΔGEX_j })  for j ∈ [i − window + 1, i]
```

Uses `rollingStdDev` from `statistics.js`.

**Gamma source:** Broker.

**Output:**
```js
{
  volatility: number | null,
  history: Array<{ timestamp, value }>,
  windowSize: number,
  status: "available" | "partial" | "unavailable"
}
```

**Edge cases:**
- window < 2 → null (need at least 2 for stddev)
- All ΔGEX equal → null (zero stddev, division by zero avoided by statistics.js)

**What it does NOT prove:** That the market is volatile or calm. ΔGEX volatility measures GEX-change variability, not price volatility.

---

#### `computeTimeSeriesStats(snapshots, config)`

**Purpose:** Convenience function computing all rolling analytics from a snapshot array.

**Config object:**
```js
{
  velocityWindow: number,       // default 6
  volatilityWindow: number,     // default 10
  netGexSmaWindow: number,      // default 10
  deltaGexSmaWindow: number,    // default 10
}
```

**Output:** Aggregated object with all of the above.

---

## 7. Phase 7.4b — `gexConcentration.js` — Concentration, Percentile, Expiry Decomposition

### 7.1 Expiry Bucket Definitions

**Standardized DTE calculation:**
```
DTE(expiryDate, referenceDate) = timeToExpiry(referenceDate, expiryDate)
```

Uses `timeToExpiry()` from `pricing.js` (which computes business-day-adjusted or calendar-day fractional years).

**Bucket boundaries (inclusive at lower bound):**

| Bucket | DTE Range | Meaning |
|---|---|---|
| `NEAR` | 0 < DTE ≤ 7 | Current week / weekly expiry |
| `MID` | 7 < DTE ≤ 30 | Next 1–4 weeks |
| `FAR` | DTE > 30 | Monthly / LEAPS |

**Expiry continuity:** The ring buffer and rolling windows operate on **continuous capturedAt timestamps**, not on expiry identity. When an expiry rolls (e.g., Thursday's weekly expires, next Thursday becomes NEAR), subsequent snapshots naturally carry the new expiry. The expiry bucket of each snapshot is determined at computation time from its `expiry` field. No reset, no special transition logic. The `expiryChanged` flag from Phase 7.3 decomposition is surfaced in metadata but does not interrupt continuity.

### 7.2 Strike Coverage Tracking

Each snapshot records its strike set. When computing decomposition or cross-snapshot metrics, the **strike intersection** is used. Metrics explicitly report:

```js
{
  strikeSetA: { count: 30, min: 24000, max: 26000 },
  strikeSetB: { count: 32, min: 23800, max: 26200 },
  commonStrikes: 28,
  strikeSetDelta: 2  // |B| − |A|
}
```

**Impact on decomposition:** Strikes present in A but not in B are treated as having OI=0 in B (reducing OI attribution). Strikes present in B but not in A are excluded from OI/IV attribution (their contribution appears in the residual). This is documented, not hidden.

### 7.3 Exports

#### `computeConcentrationHistory(snapshots)`

**Purpose:** Time-series of top-N strike concentration from Phase 7.3 snapshots.

Uses `computeConcentration()` from Phase 7.3 at each snapshot point.

**Output:**
```js
{
  history: Array<{
    timestamp: string,
    top3Pct: number,
    top5Pct: number,
    top10Pct: number,
    totalAbsoluteGex: number,
    strikeCount: number
  }>,
  currentTop3Pct: number | null,
  status: "available" | "partial" | "unavailable"
}
```

**Gamma source:** Broker (concentration operates on broker-gamma-derived netGex).

---

#### `computeConcentrationPercentile(snapshots, window)`

**Purpose:** Where does the current concentration rank within the recent history?

Uses `percentileRank()` from `statistics.js` on the `top3Pct` time-series.

**Formula:**
```
percentileRank(top3Pct_current, [top3Pct_{t-window}, ..., top3Pct_current])
```

**Output:**
```js
{
  top3Percentile: number | null,   // 0–100
  top5Percentile: number | null,
  availablePoints: number,
  status: "available" | "partial" | "unavailable"
}
```

**Edge cases:**
- Fewer than `MIN_STAT_SAMPLE` (5) points → null
- Constant history → percentile = 50 (exact mean-rank)

**What it does NOT prove:** That concentration is "high" or "low" in a trading-significant sense. It measures statistical position relative to recent history only.

---

#### `computeGexPercentile(snapshots, window)`

**Purpose:** Where does the current absolute Net GEX rank within the recent history?

**Formula:**
```
percentileRank(|netGex_current|, [|netGex_{t-window}|, ..., |netGex_current|])
```

Uses `percentileRank()` from `statistics.js`.

**Historical comparability rule:** Percentile is computed over the raw absolute NetGEX values in the ring buffer. No normalization for spot level is applied in this phase. This means percentile values are **comparable only within sessions where spot stays in a similar range**. Future phases may add spot-normalized percentiles.

**Output:**
```js
{
  absolutePercentile: number | null,  // 0–100 of |netGex|
  descriptiveZ: number | null,        // z-score of |netGex| relative to history
  availablePoints: number,
  status: "available" | "partial" | "unavailable"
}
```

**What `descriptiveZ` means:** How many standard deviations the current |NetGEX| is from the rolling mean. z = 2.5 means the current level is 2.5σ above the mean. This is a **descriptive statistic**, NOT a statistically significant signal. ±2 or ±3 thresholds are informational labels, not validated trading thresholds.

**What it does NOT prove:** That current GEX is statistically abnormally high/low in a predictive sense. Empirical validation is required before these z-scores can inform any trading decision (deferred to Phase 7.7).

---

#### `computeExpiryDecomposition(snapshots, valuationDate)`

**Purpose:** Break down aggregate GEX into NEAR/MID/FAR buckets.

**Formula:** For each snapshot, group its `expiryData` by DTE bucket and sum netGex within each bucket.

**DTE calculation:** `DTE = timeToExpiry(valuationDate, expiry_date)` for each expiry.

**Output:**
```js
{
  history: Array<{
    timestamp: string,
    spot: number,
    near: { netGex: number | null, expiryCount: number, totalDte: number },
    mid:  { netGex: number | null, expiryCount: number, totalDte: number },
    far:  { netGex: number | null, expiryCount: number, totalDte: number },
    total: number | null,
    callGexShare: number | null   // call / (call + |put|) × 100
  }>,
  current: { near, mid, far, callGexShare },
  status: "available" | "partial" | "unavailable"
}
```

---

#### `computeCallGexShare(snapshots)`

**Purpose:** What fraction of total absolute GEX is call-side?

**Formula:**
```
callGexShare = callGex / (callGex + |putGex|) × 100
```

When both are zero or null, share is null.

**Label:** "Call GEX Share (%)" — NOT "call/put ratio" (which implies a different mathematical meaning).

**Gamma source:** Broker.

**Output:**
```js
{
  current: number | null,       // 0–100
  history: Array<{ timestamp, value }>,
  status: "available" | "partial" | "unavailable"
}
```

**What it does NOT prove:** That calls are "dominant" or that dealers are "net long calls." It is a geometric measurement of the GEX profile shape.

---

## 8. Phase 7.4c — `gexProfileLabel.js` — Structural Classification

### 8.1 Design Principle

The GEX Profile Label is a **transparent structural description** of the current GEX geometry. It is NOT a market regime in the traditional sense (e.g., "risk-on" or "risk-off"). It classifies the shape and structure of the GEX profile, not the market direction.

### 8.2 Classification Inputs

| Input | Source | Description |
|---|---|---|
| Net GEX sign | Phase 7.1 `chainGex().netGex` | Positive (call-dominant) vs negative (put-dominant) |
| Gamma flip distance | Phase 7.2 `spotSweep().gammaFlip` | Spot relative to zero-GEX level |
| Concentration | Phase 7.3 `computeConcentration()` | Top-3 strike share |
| ΔGEX direction | Phase 7.3 `computeDeltaGex()` | Increasing or decreasing total GEX |
| Spot/GEX relationship | Phase 7.1/7.3 | Whether spot is above/below high-GEX strikes |

### 8.3 Configurable Thresholds

**ALL thresholds are configurable. Defaults are labeled `EXPERIMENTAL_DEFAULT`.**

```js
export const DEFAULT_PROFILE_CONFIG = {
  // Net GEX thresholds (as fraction of |spot² × 0.01| for rough normalization)
  netGexStrongThreshold: 0.5,    // EXPERIMENTAL_DEFAULT
  netGexWeakThreshold: 0.1,      // EXPERIMENTAL_DEFAULT

  // Flip distance (as % of spot)
  flipNearThresholdPct: 1.0,     // EXPERIMENTAL_DEFAULT: within 1% of spot
  flipFarThresholdPct: 5.0,      // EXPERIMENTAL_DEFAULT: beyond 5% of spot

  // Concentration (top-3 share %)
  highConcentrationPct: 70,      // EXPERIMENTAL_DEFAULT
  lowConcentrationPct: 40,       // EXPERIMENTAL_DEFAULT

  // ΔGEX velocity (qualitative direction thresholds handled by sign only)
};
```

**Documentation note:** These defaults are starting points for structurally labeling the GEX profile. They have NOT been empirically validated against market outcomes. They are explicitly experimental and will be adjusted after historical analysis in Phase 7.7.

### 8.4 Profile Labels

| Label | Structural Meaning | Required Evidence |
|---|---|---|
| `POSITIVE_DOMINANT` | Net GEX strongly positive; call-side geometry dominates | NetGex > strongThreshold |
| `POSITIVE_MODERATE` | Net GEX mildly positive | weakThreshold < NetGex ≤ strongThreshold |
| `BALANCED` | Net GEX near zero; call/put GEX roughly symmetric | |NetGex| ≤ weakThreshold |
| `NEGATIVE_MODERATE` | Net GEX mildly negative | −strongThreshold ≤ NetGex < −weakThreshold |
| `NEGATIVE_DOMINANT` | Net GEX strongly negative; put-side geometry dominates | NetGex < −strongThreshold |
| `HIGH_CONCENTRATION` | GEX heavily concentrated in few strikes | top3Pct > highConcentrationPct |
| `DIFFUSE` | GEX spread across many strikes | top3Pct < lowConcentrationPct |
| `FLIP_ADJACENT` | Spot is near the gamma flip level | flipDistance < flipNearThresholdPct |
| `FLIP_DISTANT` | Spot is far from the gamma flip level | flipDistance > flipFarThresholdPct |
| `UNAVAILABLE` | Insufficient data | status === "unavailable" |

**Multiple labels can be active simultaneously.** For example: `["POSITIVE_DOMINANT", "HIGH_CONCENTRATION", "FLIP_ADJACENT"]`. The label set is an array of structural descriptors, not a single exclusive enum.

### 8.5 Exports

#### `classifyGexProfile(snapshots, config)`

**Input:** Array of recent snapshots (for rolling context) + optional config overrides.

**Output:**
```js
{
  labels: string[],                    // array of active labels
  netGex: number | null,               // current net GEX
  normalizedNetGex: number | null,     // netGex / (spot² × 0.01) — dimensionless
  concentration: object | null,        // from computeConcentration
  flipDistancePct: number | null,      // distance from gamma flip as % of spot
  deltaGexDirection: string | null,    // "increasing" | "decreasing" | "stable" | null
  callGexShare: number | null,         // 0–100
  confidence: "experimental",          // ALWAYS experimental in Phase 7.4
  configUsed: object,                  // the threshold config that was applied
  metadata: {
    snapshotCount: number,
    latestTimestamp: string,
    methodology: string,
  },
  status: "available" | "partial" | "unavailable"
}
```

**`normalizedNetGex` formula:**
```
normalizedNetGex = netGex / (spot² × 0.01)
```

This removes the spot² scaling factor to make Net GEX more comparable across different spot levels. It represents the "effective gamma × OI" product, dimensionless.

**What the classification does NOT do:**
- It does NOT predict market direction
- It does NOT generate BUY/SELL signals
- It does NOT claim the labels are predictive
- It does NOT attach confidence levels beyond "experimental"
- It is a geometric description, not a market forecast

---

## 9. Phase 7.4d — `gexAnalytics.js` — Coordinator & Strategy Builder Interface

### 9.1 Purpose

Orchestrates Phases 7.4a–7.4c into a single entry point. Provides the interface through which future Strategy Builder (Phase 7.8+) can consume GEX analytics without coupling to internal module structure.

### 9.2 Exports

#### `computeGexAnalytics(snapshots, options)`

**The main entry point.** Consumes a ring buffer or snapshot array and produces all Phase 7.4 analytics.

**Input:**
```js
snapshots: GexRingBuffer | Array  // from Phase 7.3
options: {
  valuationDate: string,          // ISO YYYY-MM-DD
  profileConfig?: object,         // override thresholds (Phase 7.4c)
  velocityWindow?: number,        // override (Phase 7.4a)
  volatilityWindow?: number,
  netGexSmaWindow?: number,
  deltaGexSmaWindow?: number,
  percentileWindow?: number,      // for GEX percentile (Phase 7.4b)
  concentrationPercentileWindow?: number,
}
```

**Output:**
```js
{
  // Metadata
  status: "available" | "partial" | "unavailable",
  snapshotCount: number,
  latestTimestamp: string | null,
  earliestTimestamp: string | null,
  dataFreshnessMs: number | null,      // now − latest capturedAt
  methodologyConsistency: {
    allSameMethodology: boolean,
    methodologyVersions: string[],     // unique versions in the window
    versionCount: number,
  },

  // Layer 1: Raw measurements (from Phase 7.1–7.3)
  current: {
    netGex: number | null,
    callGex: number | null,
    putGex: number | null,
    callGexShare: number | null,
    spot: number | null,
    expiry: string | null,
  },
  decomposition: object | null,        // from Phase 7.3 decomposeDeltaGex
  migration: object | null,            // from Phase 7.3 computeGexMigration
  concentration: object | null,        // from Phase 7.3 computeConcentration
  flipDistance: {
    distance: number | null,           // absolute
    distancePct: number | null,        // as % of spot
    direction: string | null,          // "above" | "below"
  },

  // Layer 2: Statistical context (Phase 7.4a)
  timeSeries: {
    netGexSma: object,                 // from computeNetGexSma
    deltaGexSma: object,               // from computeDeltaGexSma
    velocity: object,                  // from computeVelocity
    acceleration: object,              // from computeAcceleration
    volatility: object,                // from computeDeltaGexVolatility
  },

  // Layer 2: Statistical context (Phase 7.4b)
  percentiles: {
    gexPercentile: object,             // from computeGexPercentile
    concentrationPercentile: object,   // from computeConcentrationPercentile
  },

  // Layer 2: Expiry decomposition (Phase 7.4b)
  expiryDecomposition: object,         // from computeExpiryDecomposition

  // Layer 3: Structural classification (Phase 7.4c)
  profileLabel: object,                // from classifyGexProfile

  // Strategy Builder interface (future consumption point)
  strategyBuilderReady: boolean,       // true when enough data exists
  strategyBuilderInputs: {
    netGex: number | null,
    netGexSma: number | null,
    deltaGexSma: number | null,
    velocity: number | null,
    acceleration: number | null,
    volatility: number | null,
    gexPercentile: number | null,
    descriptiveZ: number | null,
    callGexShare: number | null,
    concentrationTop3: number | null,
    profileLabels: string[],
    flipDistancePct: number | null,
    normalizedNetGex: number | null,
  },
}
```

### 9.3 Data Freshness

```js
dataFreshnessMs = Date.now() - new Date(latestSnapshot.capturedAt).getTime()
```

Freshness is computed from the `capturedAt` timestamp **stored in the snapshot at capture time**, not from the current wall clock minus some assumed interval. If the ring buffer hasn't been updated in 20 minutes, `dataFreshnessMs` will be ~1,200,000.

**Freshness labels (informational only):**
- `< 300,000 ms` (5 min): "fresh"
- `300,000–600,000 ms` (5–10 min): "recent"
- `600,000–1,800,000 ms` (10–30 min): "stale"
- `> 1,800,000 ms` (30+ min): "old"

These are informational labels for display, not thresholds that change calculation behavior.

### 9.4 Strategy Builder Interface Contract

The `strategyBuilderInputs` object provides a **flat, typed, stable interface** that future Strategy Builder conditions can consume. Each field is documented:

| Field | Type | Unit | Source Layer | Description |
|---|---|---|---|---|
| `netGex` | number \| null | GEX units | Layer 1 | Current cumulative Net GEX |
| `netGexSma` | number \| null | GEX units | Layer 2 | Smoothed Net GEX level |
| `deltaGexSma` | number \| null | GEX units | Layer 2 | Smoothed ΔGEX rate |
| `velocity` | number \| null | GEX/sec | Layer 2 | Rate of GEX change |
| `acceleration` | number \| null | GEX/sec² | Layer 2 | Rate of velocity change |
| `volatility` | number \| null | GEX units | Layer 2 | Stddev of ΔGEX |
| `gexPercentile` | number \| null | 0–100 | Layer 2 | Where |NetGEX| ranks in history |
| `descriptiveZ` | number \| null | σ units | Layer 2 | How unusual current |NetGEX| is |
| `callGexShare` | number \| null | % (0–100) | Layer 1 | Call fraction of total |
| `concentrationTop3` | number \| null | % (0–100) | Layer 1 | Top-3 strike share |
| `profileLabels` | string[] | — | Layer 3 | Active structural labels |
| `flipDistancePct` | number \| null | % of spot | Layer 1 | Distance from gamma flip |
| `normalizedNetGex` | number \| null | dimensionless | Layer 1 | NetGEX / (spot² × 0.01) |

**IMPORTANT:** Providing this interface does NOT embed trading rules. It is a data contract for future consumption. No condition, threshold, or signal logic is defined here.

---

## 10. S² Observation — Precise Clarification

The S² factor in the GEX formula means:

```
GEX_i = γ × OI × S² × 0.01
```

**Mathematical observation (FACT):** For a fixed strike with frozen γ and OI, the mechanical change in GEX due to a spot change from S_A to S_B is:

```
ΔGEX_mechanical = γ × OI × (S_B² − S_A²) × 0.01
```

For small spot changes (ΔS ≪ S), this approximates:

```
ΔGEX_mechanical ≈ γ × OI × 2 × S × ΔS × 0.01 = (2 × ΔS / S) × GEX_A
```

**This means:** With gamma and OI frozen, a 1% spot increase produces approximately a 2% increase in the mechanical GEX component. The "2×" is the local derivative of S² at S.

**What this does NOT mean:**
- It does NOT mean observed total GEX changes by 2% for a 1% spot move (because gamma and OI are not frozen in reality)
- It does NOT mean GEX is always 2× leveraged to spot
- It does NOT imply that the observed ΔGEX is dominated by the spot component (the OI, IV, and residual components can be larger)
- It is a local linear approximation that degrades for large spot moves

**This observation is useful only for:** Understanding the magnitude of the spot-only attribution in the decomposition. When the spot component is small relative to the total, it means OI/IV/structural changes are the dominant drivers.

---

## 11. Handling Changing Strikes, Expiries, and Missing Data

### 11.1 Changing Strike Sets

**Between-snapshot decomposition** (Phase 7.3) already handles strike-set differences by computing on the intersection. Phase 7.4 metrics that consume decomposition results inherit this behavior.

**New in 7.4:** The `computeExpiryDecomposition` function explicitly tracks which expiries are present in each snapshot and surfaces the strike-set delta in metadata.

**Rule:** Missing strikes do NOT invalidate a snapshot. They contribute to the residual. The strike-set delta is metadata, not an error.

### 11.2 Expiry Transitions

When the observed expiry changes between snapshots (e.g., weekly expiry rolls):

- `expiryChanged: true` is flagged in decomposition metadata (Phase 7.3)
- The expiry bucket (NEAR/MID/FAR) is recomputed for the new expiry
- Rolling windows (velocity, acceleration, volatility) continue uninterrupted — they operate on continuous timestamps, not on expiry identity
- Net GEX level may shift discontinuously; this is expected and documented, not treated as an anomaly

**Rule:** Expiry transitions are structural events that affect interpretation. They are flagged but do not reset historical context.

### 11.3 Missing Data

| Scenario | Handling |
|---|---|
| Missing gamma in one strike | That strike excluded from GEX; contributes nothing |
| Missing OI in one strike | That strike excluded from GEX |
| Missing IV (BS model) | OI/IV attribution unavailable for that strike |
| Missing spot | Snapshot invalid; rejected at capture time (Phase 7.3) |
| Null netGex in a snapshot | Excluded from rolling windows; treated as missing |
| Empty ring buffer | All metrics return unavailable |
| Gap in snapshot sequence | ΔGEX computed across the gap; deltaTimeMs reflects actual elapsed time |

### 11.4 Methodology Version Consistency

Phase 7.4 reports methodology version metadata. If snapshots in the rolling window have different methodology versions (e.g., `GEX_STANDARD_V1` and a future version), the analytics report:

```js
methodologyConsistency: {
  allSameMethodology: false,
  methodologyVersions: ["GEX_STANDARD_V1", "GEX_STANDARD_V2"],
  versionCount: 2
}
```

**Rule:** Mixed-methodology analytics are NOT rejected. They are flagged so consumers can decide whether to trust the result. In Phase 7.4, all snapshots use `GEX_STANDARD_V1`, so consistency is always true.

### 11.5 Broker Gamma vs Model Gamma in Decomposition Residual

**The residual absorbs:**
1. Cross-terms between spot movement and OI/IV changes (mathematical)
2. Broker gamma changes not attributable to IV (market microstructure, time decay, model differences)
3. Missing data at specific strikes
4. Strike-set differences
5. Rounding

**The residual is explicitly calculated, never forced to zero.** The invariant `total = spot + OI + IV + residual` always holds.

---

## 12. Gamma Flip & Wall Historical Tracking

### 12.1 Flip History

From the ring buffer, track the primary gamma flip level over time:

```js
computeFlipHistory(snapshots) → {
  history: Array<{
    timestamp: string,
    flipSpot: number | null,         // the crossing spot from spotSweep
    direction: string | null,        // "positive_to_negative" | "negative_to_positive"
    distanceFromSpot: number | null, // |flipSpot − currentSpot|
    distanceFromSpotPct: number | null,
    compositeScore: number | null,   // from selectPrimaryFlip
  }>,
  flipCount: number,                 // how many flips detected in history
  currentFlip: object | null,
  status: "available" | "partial" | "unavailable"
}
```

**Note:** This requires running `spotSweep` at each historical snapshot. Since Phase 7.3 snapshots store enough data to reconstruct chain rows, and `reconstructChainRows()` can reproduce them, Phase 7.4 can re-run the sweep. However, this is computationally expensive. Two options:

**Option A (recommended for Phase 7.4):** Compute flip history only for the **current snapshot** (one sweep) and report the flip distance. Historical flip tracking requires storing sweep results per snapshot, which is deferred to Phase 7.5.

**Option B (future):** Store flip results in the snapshot metadata during capture. This adds to snapshot size but enables O(1) historical flip queries.

**Decision:** Phase 7.4 uses Option A. Flip history is computed on-demand from reconstructed snapshots only when explicitly requested.

### 12.2 Wall History

Same approach as flip. Walls are computed from the current snapshot's chain data. Historical wall migration (how walls shift across strikes over time) requires either stored wall results or on-demand recomputation.

**Phase 7.4 scope:** Current walls from current snapshot + centroid migration from Phase 7.3. Full wall history is deferred to Phase 7.5.

---

## 13. Data Flow Diagram

```
Phase 7.3 Ring Buffer (snapshots)
         |
         ├──→ gexTimeSeries.js     (Layer 2: rolling analytics)
         ├──→ gexConcentration.js  (Layer 2: percentile, expiry decomposition, call share)
         └──→ gexProfileLabel.js   (Layer 3: structural classification)
                  |
                  v
          gexAnalytics.js          (Coordinator: assembles all layers)
                  |
                  +--> strategyBuilderInputs  (flat interface for Phase 7.8+)
                  +--> profileLabels          (for future UI display)
                  +--> metadata              (freshness, methodology, status)
```

---

## 14. Test Strategy

### 14.1 Module-Level Tests

Each module has its own test file.

#### `gexTimeSeries.test.js` (~100–120 tests)

| Level | Tests | What |
|---|---|---|
| **A — Hand-calculated** | 8 | NetGexSma with known values, velocity with known timestamps, acceleration, volatility |
| **B — Algebraic** | 6 | Doubling ΔGEX doubles velocity, zero ΔGEX → zero velocity, etc. |
| **C — Edge cases** | 8 | Empty input, single snapshot, null values, zero deltaTime, negative deltaTime |
| **D — Timestamp-based** | 4 | Verify actual timestamps used (not assumed intervals) |
| **E — Window behavior** | 4 | Partial windows, window=1, window > data length |

#### `gexConcentration.test.js` (~80–100 tests)

| Level | Tests | What |
|---|---|---|
| **A — Hand-calculated** | 6 | Known concentration values, percentileRank calculation |
| **B — Expiry buckets** | 6 | DTE calculation, bucket boundaries, multi-expiry decomposition |
| **C — Call GEX Share** | 4 | Known call/put distributions, all-call, all-put, equal |
| **D — Percentile** | 5 | Ranking within history, edge cases, constant history → 50 |
| **E — Expiry continuity** | 4 | Expiry transition doesn't reset continuity |

#### `gexProfileLabel.test.js` (~50–60 tests)

| Level | Tests | What |
|---|---|---|
| **A — Label classification** | 8 | Each label with hand-crafted inputs |
| **B — Multi-label** | 4 | Combinations (e.g., POSITIVE_DOMINANT + HIGH_CONCENTRATION) |
| **C — Config override** | 4 | Custom thresholds produce different labels |
| **D — Edge cases** | 4 | Empty data, partial data, unavailable |
| **E — Normalized GEX** | 3 | Normalization removes spot² factor |

#### `gexAnalytics.test.js` (~40–50 tests)

| Level | Tests | What |
|---|---|---|
| **A — Integration** | 5 | Full pipeline from snapshots to complete output |
| **B — SB interface** | 4 | strategyBuilderInputs has all required fields |
| **C — Freshness** | 3 | Correct freshness computation from capturedAt |
| **D — Methodology** | 3 | Consistency detection, version tracking |
| **E — Status propagation** | 3 | Unavailable/partial propagation from sub-modules |

### 14.2 Independent Reference Calculations

For key metrics, provide hand-calculated expected values independent of production code:

```js
// Velocity reference
// Snapshots at t=0 and t=300s with NetGex 1000 and 4000
// velocity = (4000 - 1000) / 300 = 10 GEX/sec

// NetGexSma reference
// Values: [100, 200, 300, 400, 500], window=3
// SMA at last point = (300 + 400 + 500) / 3 = 400

// CallGexShare reference
// callGex = 7000, putGex = -3000
// share = 7000 / (7000 + 3000) × 100 = 70%

// NormalizedNetGex reference
// netGex = 3,125,000, spot = 25000
// normalized = 3125000 / (25000² × 0.01) = 3125000 / 6250000 = 0.5
```

### 14.3 Regression Tests

- Verify Phase 7.1/7.2/7.3 functions are NOT imported incorrectly
- Verify no BS model gamma appears in time-series metrics
- Verify velocity uses actual timestamps
- Verify no fixed-interval assumptions

---

## 15. Files That Would Eventually Be Changed

### New Files (Phase 7.4 implementation)

| File | Lines (est.) | Purpose |
|---|---|---|
| `frontend/lib/calculations/gexTimeSeries.js` | ~250 | Rolling ΔGEX analytics |
| `frontend/lib/calculations/gexTimeSeries.test.js` | ~300 | Tests |
| `frontend/lib/calculations/gexConcentration.js` | ~250 | Concentration, percentile, expiry decomposition |
| `frontend/lib/calculations/gexConcentration.test.js` | ~280 | Tests |
| `frontend/lib/calculations/gexProfileLabel.js` | ~180 | Structural classification |
| `frontend/lib/calculations/gexProfileLabel.test.js` | ~200 | Tests |
| `frontend/lib/calculations/gexAnalytics.js` | ~200 | Coordinator & SB interface |
| `frontend/lib/calculations/gexAnalytics.test.js` | ~180 | Tests |
| `docs/GEX_PHASE_7_4_DESIGN.md` | ~500 | This document |

### Files NOT Changed (explicitly preserved)

| File | Status |
|---|---|
| `frontend/lib/calculations/gex.js` | Untouched |
| `frontend/lib/calculations/gex.test.js` | Untouched |
| `frontend/lib/calculations/gexPhase72.js` | Untouched |
| `frontend/lib/calculations/gexPhase72.test.js` | Untouched |
| `frontend/lib/calculations/gexHistory.js` | Untouched |
| `frontend/lib/calculations/gexHistory.test.js` | Untouched |
| `frontend/lib/calculations/statistics.js` | Untouched (consumed, not modified) |
| All backend files | Untouched |
| All API endpoints | Untouched |
| All UI/frontend components | Untouched |
| Database schema | Untouched |
| Authentication | Untouched |
| Broker integrations | Untouched |

---

## 16. Risks and Open Questions

### 16.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Rolling windows sensitive to snapshot gaps | Medium | Report `availablePoints`; do not interpolate missing |
| Velocity/acceleration noisy with 5-min intervals | Medium | Windowed smoothing (SMA) applied before display |
| Expiry roll causes discontinuity in Net GEX | Low | Flagged as `expiryChanged`; interpretation caveat documented |
| Profile label thresholds unvalidated | Low | Marked EXPERIMENTAL; not used for trading |
| On-demand flip recomputation expensive | Low | Only on explicit request; not in default analytics |
| Concentration percentile not spot-normalized | Low | Documented comparability limitation |

### 16.2 Open Questions (deferred to Phase 7.7)

1. What rolling window sizes produce the most informative velocity/acceleration signals?
2. Do concentration percentiles add predictive value?
3. Are the EXPERIMENTAL_DEFAULT profile thresholds structurally meaningful?
4. Does GEX percentile improve upon raw Net GEX for market classification?
5. Should flip distance be normalized by ATM gamma?
6. Can GEX velocity/acceleration detect regime transitions before price does?

---

## 17. Statistical Validation Requirements (Phase 7.7 — not implemented here)

Before any Phase 7.4 metric informs trading decisions:

1. Collect ≥ 60 days of 5-minute snapshots
2. Test each metric's distribution properties (stationarity, autocorrelation)
3. Test predictive power against realized outcomes (out-of-sample)
4. Document which metrics are informative and which are noise
5. Define validated thresholds (replacing EXPERIMENTAL_DEFAULT)
6. Backtest Strategy Builder conditions that consume GEX analytics
7. Never claim statistical significance from descriptive z-scores alone

---

## 18. Free-Data Constraint

**CONFIRMED:** Phase 7.4 introduces zero paid data dependencies.

| Input | Source | Cost |
|---|---|---|
| Option chain data | User's Upstox connection (free tier) | Free |
| Spot price | Included in chain response | Free |
| Gamma/OI/IV | From chain response (broker-provided Greeks) | Free |
| Expiry dates | From chain metadata | Free |
| Time-to-expiry | Computed from dates | Free |
| Statistical functions | `statistics.js` (existing, pure math) | Free |

No external data vendor, no paid API, no data redistribution.

---

## 19. Security Confirmation

| Concern | Status |
|---|---|
| API secrets in analytics? | NO — analytics consume chain data only |
| Broker credentials in snapshots? | NO — snapshots contain market data, not auth data |
| Authentication flow changed? | NO |
| New frontend storage of secrets? | NO |
| Backend changes required? | NO |

---

## 20. Backward Compatibility Confirmation

| System | Status | Evidence |
|---|---|---|
| Phase 7.1 GEX formula | UNCHANGED | `gex.js` not modified |
| Phase 7.2 sweep/flip/walls | UNCHANGED | `gexPhase72.js` not modified |
| Phase 7.3 snapshots/decomposition | UNCHANGED | `gexHistory.js` not modified |
| Backend API | UNCHANGED | No router or endpoint changes |
| Database schema | UNCHANGED | No model changes |
| Authentication | UNCHANGED | No session/auth changes |
| Broker integrations | UNCHANGED | No adapter changes |
| Paper trading | UNCHANGED | No execution changes |
| Existing tests | UNCHANGED | All 1124/1124 frontend + 16/16 backend expected to pass |

---

## 21. Definition of Done — Phase 7.4

- [ ] All 4 new modules implemented with documented formulas
- [ ] Every metric explicitly labels gamma source (broker vs BS model)
- [ ] Every metric has Level A–E tests with independent reference calculations
- [ ] Every assumption/heuristic/inference flagged in code and documentation
- [ ] GEX Profile Labels are structural descriptions only (not market predictions)
- [ ] No metric generates trading signals
- [ ] No existing files modified (Phase 7.1/7.2/7.3 untouched)
- [ ] No backend/API/database/auth/broker changes
- [ ] Full test suite passes (expected 1124+ frontend, 16+ backend)
- [ ] Production build succeeds
- [ ] Strategy Builder interface defined but not implemented
- [ ] Statistical validation requirements documented for Phase 7.7
- [ ] S² observation documented with precise clarification
- [ ] Expiry continuity vs composition changes documented
- [ ] Strike coverage impact on residual documented
- [ ] All thresholds labeled EXPERIMENTAL_DEFAULT
- [ ] z-scores labeled descriptiveZ (not "significant")
- [ ] Velocity/acceleration use actual timestamps
- [ ] Freshness uses capturedAt from snapshots
- [ ] DTE calculation standardized via pricing.js timeToExpiry
