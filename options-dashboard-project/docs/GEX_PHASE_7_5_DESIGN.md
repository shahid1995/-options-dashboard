# Options Dashboard — GEX Phase 7.5: Integration & Data Contract

**Date:** 2026-08-22
**Status:** Design proposal — awaiting approval
**Predecessors:** Phase 7.1 (foundation), 7.2 (flip/walls), 7.3 (history/ΔGEX), 7.4 (analytics/classification)
**Scope:** Canonical data contracts, integration architecture, Strategy Builder interface
**Boundaries:** Design only — no code changes, no deployment

---

## 1. Objective

Design the integration/data-contract layer that connects Phase 7.1 → 7.2 → 7.3 → 7.4 → future Dashboard/Strategy Builder. Establish canonical schemas before any future implementation.

---

## 2. Current Architecture Audit

### 2.1 Complete Export Map

#### Phase 7.1 (`gex.js`)

| Export | Type | Input | Output | Gamma |
|---|---|---|---|---|
| `rawGex(gamma, oi, spot)` | function | 3 numbers | number | Caller |
| `signedGex(type, gamma, oi, spot)` | function | type + 3 numbers | number | Caller |
| `strikeGex(row, spot)` | function | canonical row + spot | `{ strike, callGex, putGex, netGex, status }` | Broker |
| `expiryGex(rows, spot)` | function | rows[] + spot | `{ expiry, callGex, putGex, netGex, status, strikes[] }` | Broker |
| `chainGex(chainRows, options)` | function | rows[] + `{ spot, symbol }` | Full chain result (see below) | Broker |
| `formatGex(value)` | function | number | string | — |
| `GEX_METHOD_VERSION` | const | — | `"GEX_STANDARD_V1"` | — |
| `GEX_SIGN_CONVENTION` | const | — | frozen object | — |
| `GEX_INPUT_UNITS` | const | — | frozen object | — |
| `GEX_STATUS` | const | — | `{ AVAILABLE, PARTIAL, UNAVAILABLE, INVALID }` | — |

**`chainGex` output shape:**
```js
{
  underlying, spot, scope, methodology, signConvention, inputUnits,
  callGex, putGex, netGex,           // chain-level totals (number|null)
  availabilityStatus,                 // string
  validOptionCount, totalOptionCount, // numbers
  lotSize,                            // metadata only
  byExpiry: [{ expiry, callGex, putGex, netGex, availabilityStatus, validStrikeCount, totalStrikeCount }],
  byStrike: [{ strike, callGex, putGex, netGex, callOi, putOi }],
}
```

#### Phase 7.2 (`gexPhase72.js`)

| Export | Type | Input | Output | Gamma |
|---|---|---|---|---|
| `modelGamma(type, S, K, T, sigma, r, q)` | function | 7 numbers | number\|null | **BS model** |
| `netGexAtSpot(rows, S, T, r, q)` | function | rows + 4 numbers | `{ callGex, putGex, netGex, validStrikeCount }` | **BS model** |
| `detectZeroCrossings(sweepPoints)` | function | array | `[{ spotA, spotB, gexA, gexB, crossingSpot, transitionMagnitude }]` | — |
| `findGammaWalls(strikeGexList, spot, topN)` | function | list + spot + int | `{ callWalls[], putWalls[], netWalls[] }` | Broker |
| `selectPrimaryFlip(spot, crossings, quality, range)` | function | 4 inputs | object\|null | — |
| `spotSweep(chainRows, options)` | function | rows + options | Full sweep result (see below) | **BS model** |
| `brokerVsModelGamma(rows, spot, T, r, q)` | function | rows + 4 numbers | `{ comparisons[], summary }` | Both |
| `sweepDataQuality(rows, spot)` | function | rows + spot | quality object | — |
| `crossingStrength(crossing)` | function | crossing | number | — |
| `GEX_PHASE72_VERSION` | const | — | `"GEX_SWEEP_V1"` | — |

**`spotSweep` output shape:**
```js
{
  underlying, spot, r, q, methodology, baseMethodology, signConvention,
  sweepConfig: { spotMin, spotMax, spotStep, sweepSteps, sweepRangePct },
  currentGex: { callGex, putGex, netGex, validStrikeCount },
  gammaFlip: { crossings[], primaryFlip, crossingCount, distanceFromSpot, distanceFromSpotPct, noCrossingFound },
  gammaWalls: { callWalls[], putWalls[], netWalls[] },
  byExpiry: [{ expiry, T, sweepPoints[], crossings[], walls, status }],
  brokerVsModel: { comparisons[], summary },
  dataQuality,
  status,
}
```

#### Phase 7.3 (`gexHistory.js`)

| Export | Type | Input | Output | Gamma |
|---|---|---|---|---|
| `captureGexSnapshot(chain, spot, ts, opts)` | function | chain + spot + timestamp | **Snapshot** (see §3) | Broker |
| `GexRingBuffer` | class | — | FIFO buffer of snapshots | — |
| `computeDeltaGex(a, b)` | function | 2 snapshots | `{ total, deltaTimeMs, spotChange, status }` | Broker |
| `computeSpotDeltaGex(a, b)` | function | 2 snapshots | `{ spotDelta, perStrike[], status }` | Broker (frozen A) |
| `computeStructureDeltaGex(a, b, opts)` | function | 2 snapshots + opts | `{ oiDelta, ivDelta, structureDelta, perStrike[], status }` | **BS model** |
| `decomposeDeltaGex(a, b, opts)` | function | 2 snapshots + opts | Full decomposition (see below) | Both |
| `computeGexMigration(a, b, threshold)` | function | 2 snapshots + threshold | Migration result | Broker |
| `computeStrikeCentroid(strikeData)` | function | strikeData[] | number\|null | Broker |
| `computeConcentration(strikeData)` | function | strikeData[] | `{ top3Pct, top5Pct, top10Pct, totalAbsoluteGex, strikeCount }` | Broker |
| `assembleGexTimeSeries(source, opts)` | function | ring buffer/array | `{ points[], deltaGexSeries[], migrationSeries[], summary }` | Broker |
| `reconstructChainRows(snapshot)` | function | snapshot | canonical rows[] | — |
| `snapshotDataQuality(snapshot)` | function | snapshot | quality object | — |
| `GEX_HISTORY_VERSION` | const | — | `"GEX_HISTORY_V1"` | — |

**`decomposeDeltaGex` output shape:**
```js
{
  total, spot, oi, iv, residual,                    // component values (number|null)
  spotPct, oiPct, ivPct, residualPct,               // percentage breakdown
  invariantOk,                                       // boolean|null
  deltaTimeMs, spotChange, expiryChanged,            // metadata
  status,                                            // string
  _totalDetail, _spotDetail, _structureDetail,        // sub-results
}
```

#### Phase 7.4a (`gexTimeSeries.js`)

| Export | Type | Input | Output |
|---|---|---|---|
| `computeNetGexSma(source, window)` | function | snapshots + window | `{ sma, history[], windowSize, availablePoints, status }` |
| `computeDeltaGexSma(source, window)` | function | snapshots + window | `{ sma, history[], windowSize, availablePoints, status }` |
| `computeVelocity(source, window)` | function | snapshots + window | `{ velocity, history[], windowSize, availablePoints, status }` |
| `computeAcceleration(source, window)` | function | snapshots + window | `{ acceleration, history[], windowSize, availablePoints, status }` |
| `computeDeltaGexVolatility(source, window)` | function | snapshots + window | `{ volatility, history[], windowSize, availablePoints, status }` |
| `computeTimeSeriesStats(source, config)` | function | snapshots + config | Aggregated object |

#### Phase 7.4b (`gexConcentration.js`)

| Export | Type | Input | Output |
|---|---|---|---|
| `computeDte(expiryDate, referenceDate)` | function | 2 ISO dates | number\|null (days) |
| `classifyDteBucket(dteDays)` | function | number | `"NEAR"` \| `"MID"` \| `"FAR"` |
| `computeConcentrationHistory(source)` | function | snapshots | `{ history[], currentTop3Pct, status }` |
| `computeConcentrationPercentile(source, window)` | function | snapshots + window | `{ top3Percentile, top5Percentile, availablePoints, status }` |
| `computeGexPercentile(source, window)` | function | snapshots + window | `{ absolutePercentile, descriptiveZ, availablePoints, status }` |
| `computeExpiryDecomposition(source, valuationDate)` | function | snapshots + date | `{ history[], current, status }` |
| `computeCallGexShare(source)` | function | snapshots | `{ current, history[], status }` |

#### Phase 7.4c (`gexProfileLabel.js`)

| Export | Type | Input | Output |
|---|---|---|---|
| `classifyGexProfile(source, configOverride, context)` | function | snapshots + config + context | Classification result |
| `LABEL` | const | — | 9 label strings |
| `DEFAULT_PROFILE_CONFIG` | const | — | Threshold config |
| `PROFILE_CONFIDENCE` | const | — | `"experimental"` |

#### Phase 7.4d (`gexAnalytics.js`)

| Export | Type | Input | Output |
|---|---|---|---|
| `computeGexAnalytics(source, options)` | function | snapshots + options | Full analytics (see §10) |
| `FRESHNESS` | const | — | `{ FRESH, RECENT, STALE, OLD }` |

### 2.2 Dependency Map

```
                          pricing.js
                         (timeToExpiry, bsGreeks)
                              |
               +--------------+--------------+
               |              |              |
          gex.js (7.1)   statistics.js   greekAnalytics.js
               |              |
               v              |
       gexPhase72.js (7.2)    |
          |    |              |
          |    +--- bsGreeks -+
          |    |
          v    v
     gexHistory.js (7.3)
          |
     +----+----+----+
     |    |    |    |
     v    v    v    v
  gexTimeSeries  gexConcentration  gexProfileLabel
     (7.4a)         (7.4b)           (7.4c)
          |              |              |
          +------+-------+------+-------+
                 |              |
                 v              v
          gexAnalytics.js (7.4d)
                 |
                 v
          Strategy Builder (future)
```

### 2.3 Missing Canonical Contracts

| Gap | Description |
|---|---|
| **No canonical snapshot schema** | `captureGexSnapshot` returns a specific object shape but it is not formally versioned or documented as a contract |
| **No snapshot versioning** | Snapshot shape may change across phases without consumers knowing |
| **No historical schema** | Backend `GexSnapshot` model stores data; frontend `GexRingBuffer` stores data; no single canonical shape |
| **No SB contract version** | `strategyBuilderInputs` is defined inline in `gexAnalytics.js` without a separate versioned contract |
| **No units document** | Each module documents units in comments but no single source of truth |
| **No data-quality rules document** | Each module handles nulls/missing differently; no unified matrix |
| **No integration flow document** | No single diagram showing live → snapshot → ring buffer → analytics → SB |
| **No replay/backtest contract** | `computeGexAnalytics` works on any snapshot array but the replay path is not formalized |

---

## 3. Canonical GEXSnapshot Schema

### 3.1 Design Principles

1. **Separate raw measurements from derived analytics.** The snapshot stores what was observed, not what was computed from history.
2. **Authoritative fields vs derived fields.** Authoritative = captured at snapshot time. Derived = computed from multiple snapshots.
3. **Version the schema.** Consumers must know which version they are reading.
4. **Preserve reproducibility.** Every snapshot must contain enough data to reproduce its GEX calculation.

### 3.2 Snapshot Schema (`GEXSnapshot_v1`)

```
GEXSnapshot_v1 {
  // ---- Identity ----
  schemaVersion: "GEXSnapshot_v1"        // Schema version
  snapshotId: string | null              // Unique ID (backend-generated when persisted)

  // ---- Temporal ----
  capturedAt: string                     // ISO-8601, authoritative capture timestamp
  valuationDate: string | null           // Reference date for DTE calculation (ISO YYYY-MM-DD)

  // ---- Market Identity ----
  underlying: string                     // e.g. "NIFTY"
  symbol: string | null                  // Trading symbol (may differ from underlying)
  spot: number                           // Underlying spot/index price (index points)

  // ---- Expiry ----
  expiry: string | null                  // Primary expiry ISO YYYY-MM-DD
  dte: number | null                     // Days to expiry (computed from valuationDate + expiry)

  // ---- Methodology ----
  methodology: string                    // "GEX_STANDARD_V1" — versioned formula identifier
  methodologyMetadata: {                 // Detailed methodology contract
    gexVersion: string,
    formula: string,                     // e.g. "gamma * oi * spot^2 * 0.01"
    oiUnit: string,                      // "contracts"
    signConvention: string,              // "NAIVE_DEALER_CONVENTION"
    callSign: number,                    // +1
    putSign: number,                     // -1
    lotSizeFactorApplied: false,         // Always false
  }

  // ---- Chain-Level GEX (Authoritative) ----
  callGex: number | null                 // Aggregate call-side GEX (positive)
  putGex: number | null                  // Aggregate put-side GEX (negative)
  netGex: number | null                  // callGex + putGex

  // ---- Chain Quality ----
  availabilityStatus: string             // "available" | "partial" | "unavailable" | "invalid"
  validStrikeCount: number               // Strikes with valid data
  totalStrikeCount: number               // Total strikes in chain
  chainAgeMs: number | null              // ms since earliest quote_timestamp

  // ---- Strike-Level Data (Authoritative) ----
  strikeData: Array<{
    strike: number,                      // Strike price
    callGamma: number | null,            // Broker-observed gamma
    callOi: number | null,               // Open interest in contracts
    callIv: number | null,               // Implied volatility (decimal)
    callGex: number | null,              // Computed call GEX
    putGamma: number | null,             // Broker-observed gamma
    putOi: number | null,                // Open interest in contracts
    putIv: number | null,                // Implied volatility (decimal)
    putGex: number | null,               // Computed put GEX
    netGex: number | null,               // Computed net GEX
  }>,

  // ---- Expiry-Level Data (Authoritative) ----
  expiryData: Array<{
    expiry: string,                      // ISO YYYY-MM-DD
    callGex: number | null,
    putGex: number | null,
    netGex: number | null,
    availabilityStatus: string,
    validStrikeCount: number,
    totalStrikeCount: number,
  }>,
}
```

### 3.3 Derived Analytics (NOT part of snapshot)

These are computed from snapshots, not stored in them:

| Derived Metric | Source | Requires |
|---|---|---|
| `normalizedNetGex` | `netGex / (spot² × 0.01)` | Current snapshot only |
| `callGexShare` | `|callGex| / (|callGex| + |putGex|) × 100` | Current snapshot only |
| `concentration` | `computeConcentration(strikeData)` | Current snapshot only |
| `dte` | `timeToExpiry(valuationDate, expiry)` | Current snapshot + valuationDate |
| `expiryBucket` | `classifyDteBucket(dte)` | dte value |
| `deltaGex` | `computeDeltaGex(a, b)` | Two consecutive snapshots |
| `spotDelta` | `computeSpotDeltaGex(a, b)` | Two consecutive snapshots |
| `oiDelta / ivDelta` | `computeStructureDeltaGex(a, b)` | Two consecutive snapshots + BS model |
| `decomposition` | `decomposeDeltaGex(a, b)` | Two consecutive snapshots + BS model |
| `migration` | `computeGexMigration(a, b)` | Two consecutive snapshots |
| `centroid` | `computeStrikeCentroid(strikeData)` | One snapshot |
| `netGexSma` | `computeNetGexSma(buffer, window)` | Ring buffer |
| `deltaGexSma` | `computeDeltaGexSma(buffer, window)` | Ring buffer |
| `velocity` | `computeVelocity(buffer, window)` | Ring buffer |
| `acceleration` | `computeAcceleration(buffer, window)` | Ring buffer |
| `volatility` | `computeDeltaGexVolatility(buffer, window)` | Ring buffer |
| `gexPercentile` | `computeGexPercentile(buffer, window)` | Ring buffer |
| `concentrationPercentile` | `computeConcentrationPercentile(buffer, window)` | Ring buffer |
| `expiryDecomposition` | `computeExpiryDecomposition(buffer, valuationDate)` | Ring buffer + date |
| `profileLabel` | `classifyGexProfile(buffer, config, context)` | Ring buffer + config |
| `freshness` | `Date.now() - new Date(capturedAt).getTime()` | Current snapshot |

### 3.4 Why Separation Matters

- Snapshots are **immutable records** of what was observed at one instant
- Derived analytics are **functions of one or more snapshots**
- The snapshot schema can evolve independently of the analytics
- Historical replay requires only snapshots — analytics are recomputed
- Backend persistence stores snapshots — frontend computes analytics on top

---

## 4. Historical Time-Series Contract

### 4.1 Ring Buffer (Frontend, In-Memory)

```
GexRingBuffer_v1 {
  maxSize: number (default 200)
  intervalMs: number (default 300,000 = 5 min)
  snapshots: GEXSnapshot_v1[]          // chronological, oldest first
  lastCaptureAt: number                // Date.now() ms of last push
}
```

**Ordering:** Snapshots MUST be stored in chronological order (oldest first).

**Duplicate handling:** If two snapshots have the same `capturedAt`, both are stored (no dedup). The consumer is responsible for detecting duplicates if needed.

**Out-of-order:** The ring buffer does NOT sort. Snapshots must be pushed in order. If the caller pushes out-of-order, the ring buffer stores them in push order.

### 4.2 Persistent Storage (Backend)

```
gex_snapshots (database table) {
  id: integer (primary key)
  symbol: string (indexed)
  expiry: string
  spot: float
  methodology: string
  sign_convention: string
  call_gex: float (nullable)
  put_gex: float (nullable)
  net_gex: float (nullable)
  availability_status: string
  valid_strike_count: integer
  total_strike_count: integer
  chain_age_ms: float (nullable)
  captured_at: datetime (ISO-8601, UTC)
  strike_data: JSON text
  expiry_data: JSON text
  methodology_metadata: JSON text
}
```

**Query contract:** `get_gex_snapshots(db, symbol, expiry?, limit?, since?)` returns snapshots oldest-first.

**Retention:** Configurable via `GEX_HISTORY_RETENTION_DAYS` (default 90). Pruning via `prune_gex_snapshots()`.

### 4.3 Missing Snapshots

- **Never interpolate missing GEX snapshots.** A gap in the snapshot sequence means a gap in history.
- The analytics functions handle gaps by operating on whatever snapshots are available.
- Velocity/acceleration compute `Δt` from actual `capturedAt` timestamps, so gaps naturally produce larger Δt values.
- The ring buffer does not fill gaps.

### 4.4 Expiry Transitions

When an expiry rolls (e.g., weekly expiry expires, next weekly becomes active):
- The snapshot's `expiry` field changes to the new expiry
- The `expiryChanged` flag is surfaced in decomposition metadata
- Rolling windows continue uninterrupted — they operate on continuous timestamps
- No automatic reset of historical context

### 4.5 Strike-Set Changes

When new strikes appear or old strikes disappear:
- Only strikes present in **both** snapshots participate in decomposition
- Missing strikes in one snapshot are treated as having OI=0 in that snapshot
- The strike-set delta is surfaced in decomposition metadata
- Concentration metrics operate on whatever strikes are in the current snapshot

### 4.6 Maximum History Required

| Metric | Maximum Window | Default |
|---|---|---|
| NetGexSma | configurable | 10 snapshots (50 min) |
| DeltaGexSma | configurable | 10 snapshots (50 min) |
| Velocity | configurable | 6 snapshots (30 min) |
| Acceleration | configurable | 6 snapshots (30 min) |
| Volatility | configurable | 10 snapshots (50 min) |
| GEX Percentile | configurable | 10 snapshots (50 min) |
| Concentration Percentile | configurable | 10 snapshots (50 min) |

At 5-minute intervals, 200 snapshots = ~16.7 hours of history. This is sufficient for all current Phase 7.4 metrics.

---

## 5. Live + Historical Integration

### 5.1 Canonical Flow

```
Broker Option Chain (Upstox)
         |
         v
Backend chains router → Normalized chain response
         |
         v
captureGexSnapshot(chain, spot, timestamp)  ← Phase 7.3
         |
         v
GexRingBuffer.push(snapshot)               ← Phase 7.3
         |
         v
computeGexAnalytics(buffer, options)        ← Phase 7.4d
         |
         +--→ Layer 1: Raw measurements (from snapshot)
         +--→ Layer 2: Statistical context (from buffer)
         +--→ Layer 3: Structural classification (from buffer + config)
         |
         v
strategyBuilderInputs (flat interface)      ← Phase 7.4d
```

### 5.2 Live Path

```
Every 5 seconds (polling) or on WebSocket tick:
  1. Backend fetches chain from Upstox
  2. Frontend receives normalized chain via useChainFeed
  3. captureGexSnapshot() creates snapshot from chain
  4. Ring buffer pushes snapshot (if interval elapsed)
  5. computeGexAnalytics() re-runs on updated buffer
  6. Dashboard renders analytics
```

**Capture gating:** `GexRingBuffer.shouldCapture()` checks whether the configured interval has elapsed since the last capture. Chain data arriving between captures is discarded for GEX purposes (but may be used by other dashboard components).

### 5.3 Historical Path

```
On page load or symbol change:
  1. Backend serves stored snapshots via get_gex_snapshots()
  2. Frontend loads snapshots into ring buffer via buffer.load()
  3. computeGexAnalytics() runs on loaded history
  4. Analytics are immediately available with historical context
```

### 5.4 Replay / Backtest Path

```
For historical analysis or backtesting:
  1. Provide an array of GEXSnapshot_v1 objects (any source)
  2. Pass to computeGexAnalytics(snapshotArray, options)
  3. Analytics are computed identically to live path
  4. No separate calculation path exists
```

**Key insight:** `computeGexAnalytics` accepts any array of snapshots. It does not care whether they came from a ring buffer, a database query, or a backtest fixture. This is the single canonical interface.

### 5.5 Where Each Phase Operates

| Phase | Input | Operation | Output |
|---|---|---|---|
| 7.1 | Chain rows + spot | `chainGex()` | Chain-level GEX |
| 7.2 | Chain rows + spot + T | `spotSweep()` | Flip, walls, sweep |
| 7.3 | Chain + spot + timestamp | `captureGexSnapshot()` | Snapshot |
| 7.3 | Two snapshots | `decomposeDeltaGex()` | Decomposition |
| 7.3 | Two snapshots | `computeGexMigration()` | Migration |
| 7.3 | Snapshot | `computeConcentration()` | Concentration |
| 7.4a | Ring buffer | Rolling analytics | SMA, velocity, etc. |
| 7.4b | Ring buffer | Statistical context | Percentiles, expiry decomp |
| 7.4c | Ring buffer + config | Classification | Profile labels |
| 7.4d | Ring buffer + options | Aggregation | Full analytics + SB interface |

---

## 6. Strategy Builder Read-Only Contract

### 6.1 Interface Definition

```
StrategyBuilderGexInputs_v1 {
  // ---- Current State ----
  netGex: number | null                  // Cumulative Net GEX (GEX units)
  normalizedNetGex: number | null        // Dimensionless: netGex / (spot² × 0.01)
  callGexShare: number | null            // 0–100 (%)

  // ---- Smoothed Levels ----
  netGexSma: number | null               // SMA of cumulative Net GEX (GEX units)
  deltaGexSma: number | null             // SMA of sequential ΔGEX (GEX units)

  // ---- Rate of Change ----
  velocity: number | null                // GEX units per second
  acceleration: number | null            // GEX units per second²
  volatility: number | null              // Stddev of ΔGEX (GEX units)

  // ---- Historical Context ----
  gexPercentile: number | null           // 0–100, where |NetGEX| ranks in history
  descriptiveZ: number | null            // σ units, how unusual current |NetGEX| is

  // ---- Structural ----
  concentrationTop3: number | null       // 0–100 (%), top-3 strike share
  profileLabels: string[]                // Array of structural labels
  flipDistancePct: number | null          // Distance from gamma flip as % of spot
}
```

### 6.2 Readiness Criteria

```js
strategyBuilderReady = snapshotCount >= 3 && netGex != null
```

### 6.3 Contract Rules

1. **All fields are nullable.** Absence means "insufficient data," not "zero."
2. **No field is a trading signal.** Every field is a fact or derived statistic.
3. **No temporal interpretation.** The contract does not say "if velocity > X, then Y."
4. **No threshold logic.** Thresholds are the Strategy Builder's concern, not this contract's.
5. **Version the contract.** If fields change, increment the version suffix (e.g., `_v2`).
6. **Backward compatible additions.** New fields may be added without breaking existing consumers.
7. **Never remove fields.** Deprecate with null return, then remove in a major version.

### 6.4 Explicitly NOT in This Contract

| Excluded | Reason |
|---|---|
| Entry conditions | Trading logic, not analytics |
| Exit conditions | Trading logic, not analytics |
| BUY / SELL / LONG / SHORT | Trading signals |
| Stop loss / targets | Trading logic |
| Position sizing | Risk management, not analytics |
| Trade execution | Broker interaction |
| Profit targets | Trading logic |
| Win rate / expectancy | Requires backtesting framework |

---

## 7. Data-Quality Rules

### 7.1 Null Semantics

| Condition | Behavior | Rationale |
|---|---|---|
| Missing gamma | Strike excluded from GEX | Cannot compute exposure without gamma |
| Missing OI | Strike excluded from GEX | Cannot compute exposure without OI |
| Missing IV | OI/IV attribution unavailable | BS model needs IV for structure decomposition |
| Missing spot | Snapshot rejected at capture | GEX formula requires spot |
| Null netGex | Excluded from rolling windows | Treated as missing, not zero |
| Null callGex/putGex | callGexShare = null | Cannot compute share without both sides |
| Empty ring buffer | All analytics = unavailable | No data to compute from |
| Null valuationDate | Expiry decomposition = unavailable | Cannot compute DTE without reference date |

### 7.2 Invalid Values

| Condition | Behavior |
|---|---|
| NaN netGex | Treated as null (missing) |
| Infinity netGex | Treated as null (missing) |
| Negative spot | Snapshot rejected |
| Zero spot | Snapshot rejected |
| Negative OI | Treated as null (invalid) |
| Zero OI | Treated as null (no exposure) |

### 7.3 Temporal Edge Cases

| Condition | Behavior |
|---|---|
| deltaTimeSec = 0 | velocity = null (avoid division by zero) |
| deltaTimeSec < 0 | velocity = null (time reversal = data quality issue) |
| Duplicate timestamps | Both stored; velocity between them = null (dt=0) |
| Very large deltaTime | velocity computed normally (correct for large gaps) |
| Expiry changed between snapshots | `expiryChanged: true` flagged; no history reset |

### 7.4 Statistical Edge Cases

| Condition | Behavior |
|---|---|
| Fewer than minSample (5) | percentileRank / zScore = null |
| Constant history (σ=0) | zScore = null; percentileRank = 50 |
| Window > data length | Compute with available points; status = "partial" |
| All null values in window | metric = null; status = "unavailable" |

### 7.5 Methodology Version Changes

| Condition | Behavior |
|---|---|
| All snapshots same version | `allSameMethodology: true` |
| Mixed versions | `allSameMethodology: false`; analytics still computed |
| Unknown version | Snapshot still stored; analytics computed if data is valid |

### 7.6 Strike-Set Changes

| Condition | Behavior |
|---|---|
| New strikes appear in B | Excluded from OI/IV attribution (contribute to residual) |
| Strikes disappear from B | Treated as OI=0 in B for decomposition |
| Completely different strike sets | Intersection may be empty → decomposition unavailable |

---

## 8. Units & Mathematical Conventions

### 8.1 Complete Unit Table

| Field | Unit | Source | Phase |
|---|---|---|---|
| `spot` | Index points | Broker chain | 7.1 |
| `strike` | Index points | Broker chain | 7.1 |
| `gamma` | Per 1 underlying point | Upstox option_greeks.gamma | 7.1 |
| `oi` | Number of contracts | Upstox market_data.oi | 7.1 |
| `iv` | Decimal fraction (0.18 = 18%) | Broker-computed | 7.1 |
| `rawGex` | Gamma × contracts × points² × 0.01 | Computed | 7.1 |
| `callGex` | Positive GEX units | Computed (signed) | 7.1 |
| `putGex` | Negative GEX units | Computed (signed) | 7.1 |
| `netGex` | GEX units (signed) | Computed | 7.1 |
| `normalizedNetGex` | Dimensionless | netGex / (spot² × 0.01) | 7.4 |
| `callGexShare` | Percentage (0–100) | |call| / (|call| + |put|) × 100 | 7.4 |
| `concentration` | Percentage (0–100) | top-N \|GEX\| / total \|GEX\| × 100 | 7.3 |
| `deltaGex` | GEX units | B.netGex − A.netGex | 7.3 |
| `spotDelta` | GEX units | γ_A × OI_A × (S_B² − S_A²) × 0.01 | 7.3 |
| `velocity` | GEX units per second | ΔGEX / Δt | 7.4a |
| `acceleration` | GEX units per second² | Δvelocity / Δt | 7.4a |
| `volatility` | GEX units (stddev) | stddev(ΔGEX window) | 7.4a |
| `netGexSma` | GEX units | Rolling mean of netGex | 7.4a |
| `deltaGexSma` | GEX units | Rolling mean of ΔGEX | 7.4a |
| `dte` | Calendar days | timeToExpiry() × 365 | 7.4b |
| `gexPercentile` | Percentage (0–100) | percentileRank(|netGex|) | 7.4b |
| `descriptiveZ` | σ units | (value − mean) / σ | 7.4b |
| `flipDistancePct` | Percentage of spot | |spot − flip| / spot × 100 | 7.2 |
| `capturedAt` | ISO-8601 UTC | Broker timestamp | 7.3 |
| `deltaTimeMs` | Milliseconds | capturedAt_B − capturedAt_A | 7.3 |
| `deltaTimeSec` | Seconds | deltaTimeMs / 1000 | 7.4a |
| `chainAgeMs` | Milliseconds | Date.now() − earliest quote_timestamp | 7.3 |
| `freshnessMs` | Milliseconds | Date.now() − capturedAt | 7.4d |
| `migration` | Index points (strike) | centroid_B − centroid_A | 7.3 |

### 8.2 Critical Unit Distinctions

| Distinction | Convention |
|---|---|
| OI is contracts, NOT lots | Upstox `market_data.oi` = contracts (verified) |
| Lot size is metadata only | Never used in GEX formula |
| IV is decimal, NOT percentage | 0.18 = 18%, not 18 |
| GEX sign: call=+, put=− | NAIVE_DEALER_CONVENTION |
| Percentages are 0–100, NOT 0–1 | callGexShare, concentration, percentile |
| Velocity uses seconds, NOT minutes | GEX/second, not GEX/minute |
| DTE uses calendar days | Not business days |
| Spot is index points | Not rupees |

### 8.3 No Implicit Unit Conversions

Every function boundary preserves units. No function silently converts between:
- Lots and contracts
- Percentage and decimal IV
- Minutes and seconds
- Business days and calendar days

The only explicit conversions are:
- `capturedAt` string → milliseconds (for Δt computation)
- `timeToExpiry()` returns fractional years → multiplied by 365 for DTE days

---

## 9. Performance Architecture

### 9.1 Current Performance Profile

| Operation | Complexity | Frequency | Notes |
|---|---|---|---|
| `captureGexSnapshot` | O(n) in strikes | Every 5 min | Runs Phase 7.1 chainGex |
| `RingBuffer.push` | O(1) amortized | Every 5 min | Array push + possible shift |
| `computeDeltaGex` | O(1) | Every analytics run | Simple subtraction |
| `computeSpotDeltaGex` | O(n) in strikes | Every analytics run | Strike intersection |
| `computeStructureDeltaGex` | O(n × BS) in strikes | Every analytics run | BS gamma per strike |
| `computeGexMigration` | O(n) in strikes | Every analytics run | Centroid computation |
| `computeConcentration` | O(n log n) in strikes | Every analytics run | Sort by |GEX| |
| Rolling analytics | O(n) in snapshots | Every analytics run | Windowed computation |
| `computeGexAnalytics` | O(n² × BS) worst case | Every analytics run | Aggregates all above |

### 9.2 Snapshot Budget

At 5-minute intervals with 200 snapshots:
- 200 × ~10 strikes = ~2,000 strike records in memory
- Each snapshot ≈ 2–5 KB (strikeData JSON)
- Total ring buffer ≈ 400 KB – 1 MB
- Backend storage ≈ 20 MB per quarter

### 9.3 Incremental vs Full Recomputation

| Operation | Currently | Could Be Incremental? |
|---|---|---|
| NetGexSma | Full recompute | Yes (sliding window) |
| Velocity | Full recompute | Yes (append new, drop old) |
| Acceleration | Full recompute | Yes (depends on velocity) |
| Volatility | Full recompute | Yes (Welford's algorithm) |
| Percentile | Full recompute | Yes (order-statistic tree) |
| Decomposition | Per-pair only | Already incremental |
| Migration | Per-pair only | Already incremental |

**Recommendation:** Do NOT optimize prematurely. The current full-recompute approach handles 200 snapshots in < 1ms. Incremental optimization is warranted only if profiling shows a bottleneck.

### 9.4 Memoization Opportunities

| What | When to Memoize |
|---|---|
| `computeConcentration(strikeData)` | Same snapshot used multiple times |
| `normalizedNetGex` | Same snapshot queried repeatedly |
| `callGexShare` | Same snapshot queried repeatedly |
| Rolling analytics | Repeated calls with same buffer + window |

**Recommendation:** Memoize at the `computeGexAnalytics` level (return cached result if buffer hasn't changed). Do not memoize individual functions — the overhead is negligible.

### 9.5 Multi-Symbol Considerations

Currently the system tracks one symbol (NIFTY) at a time. For multi-symbol support:
- Each symbol needs its own ring buffer
- `computeGexAnalytics` is already symbol-agnostic (operates on any snapshot array)
- Backend queries are already filtered by symbol
- No architectural changes needed for multi-symbol — just multiple ring buffer instances

---

## 10. Error/Edge-Case Matrix

| Condition | Snapshot Capture | Decomposition | Rolling Analytics | Profile Label | SB Interface |
|---|---|---|---|---|---|
| Empty chain | Returns null | N/A | N/A | UNAVAILABLE | All null |
| Invalid spot | Returns null | N/A | N/A | UNAVAILABLE | All null |
| Null netGex | Stored as null | Excluded | Skipped | UNAVAILABLE | null |
| NaN netGex | Stored as null | Excluded | Skipped | UNAVAILABLE | null |
| Missing gamma | Strike excluded | Strike excluded | — | — | — |
| Missing OI | Strike excluded | Strike excluded | — | — | — |
| Missing IV | Strike stored | OI/IV attribution unavailable | — | — | — |
| deltaTime = 0 | — | — | velocity = null | — | velocity = null |
| deltaTime < 0 | — | — | velocity = null | — | velocity = null |
| Expiry changed | `expiryChanged: true` | Flagged | Continues | Uses current expiry | expiry = current |
| New strikes in B | — | Excluded from attribution | — | Uses current strikes | — |
| Strikes gone from B | — | Treated as OI=0 | — | — | — |
| σ = 0 | — | — | zScore = null | — | descriptiveZ = null |
| < minSample points | — | — | percentile = null | — | gexPercentile = null |
| Constant history | — | — | zScore = null, percentile = 50 | — | descriptiveZ = null |
| Mixed methodology | Stored | Computed | Computed | Computed | `allSameMethodology: false` |
| Stale data | — | — | Computed | Computed | `freshnessLabel: "stale"/"old"` |
| Duplicate timestamps | Both stored | velocity = null (dt=0) | — | — | velocity = null |
| Window > data | — | — | Partial status | Partial status | Partial |

---

## 11. Versioning Rules

### 11.1 Schema Versioning

| Schema | Version Field | Current | Location |
|---|---|---|---|
| GEXSnapshot | `schemaVersion` | `"GEXSnapshot_v1"` | Snapshot object |
| Ring Buffer | Class name | `GexRingBuffer` | gexHistory.js |
| SB Interface | Object shape | `strategyBuilderInputs` | gexAnalytics.js |
| Backend model | Table version | `gex_snapshots` | models.py |

### 11.2 Version Evolution Rules

1. **Additive changes:** New nullable fields may be added without version bump
2. **Breaking changes:** Renaming/removing fields requires version bump
3. **Consumers must handle missing fields:** Use `field ?? null` or `field ?? defaultValue`
4. **Deprecation cycle:** Mark field deprecated → return null → remove in next major version
5. **Cross-phase compatibility:** Phase 7.4 must consume Phase 7.3 snapshots without requiring both to be updated simultaneously

### 11.3 Methodology Versioning

| Version | Formula | Status |
|---|---|---|
| `GEX_STANDARD_V1` | gamma × OI × spot² × 0.01 | Active |
| `GEX_SWEEP_V1` | Phase 7.2 sweep methodology | Active |
| `GEX_HISTORY_V1` | Phase 7.3 snapshot methodology | Active |

New methodologies receive new version strings. Historical records retain their original methodology version.

---

## 12. Compatibility Rules

### 12.1 Phase Cross-Compatibility

| Phases | Compatible? | Notes |
|---|---|---|
| 7.1 alone | ✅ | Standalone chain GEX |
| 7.2 consuming 7.1 output | ✅ | Chain rows → sweep |
| 7.3 consuming 7.1 output | ✅ | Chain → snapshot |
| 7.4 consuming 7.3 snapshots | ✅ | Snapshots → analytics |
| 7.4 without 7.3 ring buffer | ✅ | Can accept any snapshot array |
| 7.4 without 7.2 flip data | ✅ | Flip distance defaults to null |
| Backend persisted → Frontend ring buffer | ✅ | Same snapshot shape |

### 12.2 Backward Compatibility

- Phase 7.4 functions accept any array of objects matching the snapshot shape
- The ring buffer is optional — `computeGexAnalytics` works with plain arrays
- Missing fields in snapshots are handled gracefully (null propagation)
- No hard dependency on backend persistence — frontend works standalone

---

## 13. Non-Goals

This design document explicitly does NOT define:

1. **Trading signals** — No BUY/SELL/LONG/SHORT conditions
2. **Strategy execution** — No order placement or management
3. **UI components** — No React components or dashboard layout
4. **API endpoints** — No REST/WS API design
5. **Backend capture wiring** — No changes to the chain router
6. **Database migrations** — No schema changes
7. **Authentication** — No auth changes
8. **Broker integration** — No adapter changes
9. **Performance optimization** — No premature optimization
10. **Backtesting framework** — No backtest infrastructure

---

## 14. Future Implementation Plan

### Phase 7.5 Implementation (when approved)

| Step | Description | Files |
|---|---|---|
| 1 | Add `schemaVersion` field to `captureGexSnapshot` output | gexHistory.js |
| 2 | Add `valuationDate` parameter to snapshot capture | gexHistory.js |
| 3 | Add `dte` field to snapshot (computed at capture time) | gexHistory.js |
| 4 | Create `docs/GEX_UNITS.md` unit reference document | docs/ |
| 5 | Create `docs/GEX_DATA_QUALITY.md` edge-case matrix | docs/ |
| 6 | Version the SB interface (`strategyBuilderInputs_v1`) | gexAnalytics.js |
| 7 | Add snapshot validation function | gexHistory.js |
| 8 | Add snapshot schema documentation to code | gexHistory.js |

### Phase 7.6+ (future, not designed here)

- Dashboard GEX panel integration
- Strategy Builder condition framework
- Historical snapshot persistence wiring (live capture → backend)
- Backtesting integration
- Multi-symbol support
- Incremental analytics optimization

---

## 15. Testing Strategy

### 15.1 Schema Validation Tests

- Snapshot roundtrip: create → serialize → deserialize → verify all fields
- Missing field tolerance: snapshot with null optional fields → analytics still work
- Schema version check: v1 snapshot consumed by v1 functions

### 15.2 Integration Tests

- Live path: chain → snapshot → ring buffer → analytics → SB interface
- Historical path: stored snapshots → ring buffer → analytics
- Replay path: fixture array → analytics (same results as live path)

### 15.3 Contract Tests

- SB interface has all required fields
- All fields are number|null or string[] (no unexpected types)
- `strategyBuilderReady` reflects actual data availability

### 15.4 Data-Quality Tests

- Every condition in the edge-case matrix has a test
- Null propagation verified end-to-end
- No silent data modification

---

## 16. Mathematical Audit

### 16.1 Verified Against Implementation

| Check | Result |
|---|---|
| No contradictory formulas across phases | ✅ All use gamma × OI × spot² × 0.01 |
| No duplicate authoritative fields | ✅ Snapshots store raw; analytics derive |
| No unit mismatch | ✅ All units documented and consistent |
| No timestamp ambiguity | ✅ capturedAt is the single authoritative timestamp |
| No accidental BS gamma in 7.4 | ✅ Confirmed via code search |
| No hidden interpolation | ✅ Missing snapshots are gaps, not filled |
| No accidental signal generation | ✅ Confirmed via code search |
| No UI coupling | ✅ All modules are pure functions |
| No backend assumptions | ✅ Frontend modules are self-contained |

### 16.2 Uncertain Items

| Item | Status | Resolution |
|---|---|---|
| Acceleration uses end-of-interval timestamps | Documented convention | Not midpoint — defensible for regular intervals |
| `computeGexAnalytics` recomputes everything on each call | Performance OK at 200 snapshots | Optimize only if profiling shows need |
| Backend capture not wired to live chain | Intentionally deferred | Phase 7.6+ |
| `flipDistance` always null in current analytics | Phase 7.3 snapshots don't store sweep results | Phase 7.6+ may add sweep-to-snapshot |

---

## 17. Recommendation

**Phase 7.5 is ready for implementation.** The design:

1. Establishes a versioned canonical snapshot schema
2. Separates raw measurements from derived analytics
3. Defines a single integration path for live/historical/replay
4. Provides a read-only SB contract with explicit exclusions
5. Documents complete data-quality rules and edge cases
6. Audits all units and mathematical conventions
7. Profiles performance without premature optimization

**Recommended implementation scope:**
- Add `schemaVersion` to snapshot output
- Create unit reference document
- Create data-quality matrix document
- Version the SB interface
- Add snapshot validation function
- Total: ~300 lines of code changes + documentation
