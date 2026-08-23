# Options Dashboard — GEX Phase 7.6: Data Continuity Infrastructure

**Date:** 2026-08-23
**Status:** Design proposal — awaiting approval
**Predecessors:** Phase 7.1–7.5
**Scope:** Live capture, persistence, historical replay, Phase 7.2 sweep integration
**Boundaries:** Infrastructure only — no trading signals, no UI redesign

---

## 1. Objective

Connect the existing Phase 7.1–7.5 GEX calculation architecture to live and historical data. Establish the data-continuity pipeline so that:

1. Snapshots are captured from live chain data at configurable intervals
2. Snapshots are persisted durably in the backend
3. Historical snapshots are loaded into the frontend ring buffer on startup
4. Phase 7.2 sweep (flip/walls) can optionally enrich snapshots
5. Historical replay produces identical analytics to live capture
6. All three paths (live, historical, replay) use the same calculation contracts

Phase 7.6 does NOT introduce trading signals, strategy execution, or UI redesign.

---

## 2. Current Architecture Audit

### 2.1 Data Flow (Current)

```
Upstox WebSocket/HTTP
        |
        v
Backend chains router (routers/chains.py)
  - get_chain() → HTTP GET /chains/{symbol}?expiry_date=...
  - chain_ws()  → WebSocket /chains/ws/{symbol}?expiry_date=...
  - Calls Upstox adapter.get_option_chain(symbol, expiry)
  - Returns canonical chain: { symbol, underlying_spot_price, expiry_date, chain: [...] }
        |
        v
Frontend useChainFeed hook
  - Tries WebSocket first (3s push interval)
  - Falls back to HTTP polling (5s interval)
  - Stores chain in React state (useState)
  - Chain data is LOST on page close
        |
        v
Dashboard page.js
  - Computes PCR, Max Pain, OI totals on-the-fly
  - GEX is NOT computed from live chain data currently
```

### 2.2 Existing GEX Infrastructure

| Component | Location | Status |
|---|---|---|
| GEX calculation (7.1) | `gex.js` | ✅ Complete, tested |
| Spot sweep/flip/walls (7.2) | `gexPhase72.js` | ✅ Complete, tested |
| Snapshot capture (7.3) | `gexHistory.js` `captureGexSnapshot()` | ✅ Complete, tested |
| Ring buffer (7.3) | `gexHistory.js` `GexRingBuffer` | ✅ Complete, tested |
| Decomposition/migration (7.3) | `gexHistory.js` | ✅ Complete, tested |
| Analytics (7.4) | `gexTimeSeries.js`, `gexConcentration.js`, `gexProfileLabel.js` | ✅ Complete, tested |
| Coordinator (7.4d) | `gexAnalytics.js` `computeGexAnalytics()` | ✅ Complete, tested |
| Schema/validation (7.5) | `gexHistory.js` `validateGexSnapshot()` | ✅ Complete, tested |
| Backend persistence | `gex_history.py` + `GexSnapshot` model | ✅ Complete, NOT wired |
| Backend config | `GEX_HISTORY_ENABLED=False`, `GEX_HISTORY_SAMPLE_SECONDS=300` | ✅ Defaults set |

### 2.3 What Is Missing

| Gap | Description |
|---|---|
| **No live capture wiring** | `captureGexSnapshot()` is never called from the live chain feed |
| **No backend GEX endpoint** | No API endpoint serves stored snapshots to the frontend |
| **No frontend→backend persistence** | Frontend ring buffer is ephemeral; not persisted |
| **No Phase 7.2 sweep integration** | flipDistance is always null in analytics output |
| **No startup historical load** | Frontend doesn't load past snapshots on page load |
| **No capture scheduling** | No timer/interval triggers snapshot capture |

---

## 3. Design Principles

1. **One canonical calculation path.** Live, historical, and replay all call `computeGexAnalytics()` on a ring buffer of snapshots. No duplicated logic.
2. **Backend owns persistence. Frontend owns analytics.** Backend stores snapshots; frontend computes analytics.
3. **Snapshot capture is opt-in.** Controlled by `GEX_HISTORY_ENABLED` config. When disabled, GEX analytics work on in-memory snapshots only.
4. **Missing snapshots are gaps.** Never interpolate. The ring buffer stores what was captured.
5. **No premature optimization.** Capture every 5 minutes, store 90 days, load 200 snapshots on startup. These defaults are sufficient.
6. **No trading signals.** This phase makes data reliable; it does not interpret it.

---

## 4. Live Snapshot Capture Architecture

### 4.1 Capture Origin

Snapshots originate from the **frontend** because:

- The frontend already has the canonical chain data via `useChainFeed`
- The frontend has access to `captureGexSnapshot()` (Phase 7.3)
- The frontend has the ring buffer (Phase 7.3)
- Persisting from the frontend avoids duplicating the chain-fetch logic in the backend

### 4.2 Capture Flow

```
useChainFeed delivers chain data (every 3–5s)
        |
        v
useGexCapture hook (NEW — Phase 7.6)
  - Receives chain from useChainFeed
  - Calls captureGexSnapshot(chain, spot, Date.now(), { valuationDate })
  - Validates snapshot via validateGexSnapshot()
  - Pushes to GexRingBuffer (if interval elapsed)
  - Optionally persists to backend via POST /gex/snapshots
        |
        v
GexRingBuffer (in-memory, frontend)
  - 200 snapshots max (default)
  - 5-minute capture interval (default)
  - computeGexAnalytics() runs on this buffer
```

### 4.3 Capture Timing

| Parameter | Default | Configurable | Notes |
|---|---|---|---|
| Capture interval | 300,000 ms (5 min) | Yes (`GEX_HISTORY_SAMPLE_SECONDS`) | Matches backend config |
| Ring buffer size | 200 snapshots | Yes (`DEFAULT_MAX_SNAPSHOTS`) | ~16.7 hours at 5-min intervals |
| Chain arrives | Every 3s (WS) or 5s (poll) | No | Broker-determined |
| Snapshot created | When interval elapsed AND chain available | No | Gated by `shouldCapture()` |

### 4.4 Snapshot Fields at Capture Time

| Field | Source | Value |
|---|---|---|
| `schemaVersion` | Constant | `"GEXSnapshot_v1"` |
| `snapshotId` | null (frontend) | Populated by backend on persist |
| `capturedAt` | `Date.now()` at capture | ISO-8601 UTC |
| `valuationDate` | Configurable (default: today) | ISO YYYY-MM-DD |
| `underlying` / `symbol` | From chain response | `"NIFTY"` |
| `spot` | `chain.underlying_spot_price` | Number |
| `expiry` | `chain.expiry_date` | ISO YYYY-MM-DD |
| `dte` | Computed from valuationDate + expiry | Number (days) |
| `methodology` | Constant | `"GEX_STANDARD_V1"` |
| `callGex`, `putGex`, `netGex` | From `chainGex()` | Numbers |
| `strikeData` | Per-strike broker-observed inputs | Array |
| `expiryData` | Per-expiry GEX totals | Array |
| `methodologyMetadata` | Formula, units, convention | Object |

### 4.5 Duplicate Handling

- The ring buffer does NOT deduplicate. Two snapshots with the same `capturedAt` are both stored.
- Backend persistence deduplicates by checking `captured_at` within a configurable tolerance (default: same minute).
- The analytics functions operate on whatever snapshots are in the buffer — duplicates produce zero-velocity points (dt=0 → velocity=null).

### 4.6 Missing Snapshot Handling

- If the chain feed is interrupted, no snapshot is created for that interval.
- The ring buffer simply has a gap. Analytics functions handle gaps naturally (larger Δt values).
- On reconnection, capture resumes normally.

---

## 5. Persistence Architecture

### 5.1 Backend Persistence

The backend `gex_history.py` service already provides:

| Function | Purpose |
|---|---|
| `record_gex_snapshot(db, snapshot)` | Persist one snapshot |
| `get_gex_snapshots(db, symbol, expiry?, limit?, since?)` | Query snapshots oldest-first |
| `get_latest_snapshot(db, symbol, expiry?)` | Get most recent snapshot |
| `prune_gex_snapshots(db, retention_days)` | Delete old snapshots |
| `count_gex_snapshots(db, symbol?)` | Count stored snapshots |

**This infrastructure is complete and tested.** It needs only:
1. A new API endpoint to receive snapshots from the frontend
2. A new API endpoint to serve snapshots to the frontend
3. A capture scheduler (optional — can be frontend-initiated)

### 5.2 Frontend Persistence (New)

The frontend needs a persistence adapter that:

1. **On capture:** Sends the snapshot to `POST /gex/snapshots` (backend persists it)
2. **On startup:** Loads recent snapshots from `GET /gex/snapshots?symbol=NIFTY&limit=200` (backend serves them)
3. **On failure:** Silently degrades to in-memory-only mode

### 5.3 Canonical Source of Truth

| Source | Role | Durability |
|---|---|---|
| Backend `gex_snapshots` table | **Primary** — durable record | Disk (SQLite/Postgres) |
| Frontend `GexRingBuffer` | **Cache** — fast access for analytics | Memory (lost on page close) |
| Both use the same snapshot schema | Consistent | — |

### 5.4 Retention

| Setting | Default | Source |
|---|---|---|
| Backend retention | 90 days | `GEX_HISTORY_RETENTION_DAYS` |
| Frontend ring buffer | 200 snapshots (~16.7 hours) | `DEFAULT_MAX_SNAPSHOTS` |
| Pruning | On backend startup or cron | `prune_gex_snapshots()` |

### 5.5 Ordering

- Backend returns snapshots **oldest-first** (`.order_by(captured_at.asc())`)
- Frontend ring buffer stores **chronologically** (oldest at index 0)
- Analytics functions expect chronological order

### 5.6 Idempotency

- `record_gex_snapshot()` stores every call — no dedup by default
- Backend can add idempotency by checking `captured_at` within tolerance before insert
- Frontend ring buffer does not deduplicate — consumers handle duplicates

### 5.7 Recovery After Restart

1. Frontend page loads
2. `useGexCapture` hook initializes empty ring buffer
3. Hook calls `GET /gex/snapshots?symbol=NIFTY&limit=200`
4. Backend returns stored snapshots oldest-first
5. Ring buffer is populated via `buffer.load(snapshots)`
6. `computeGexAnalytics()` runs immediately with historical context
7. Live capture resumes from the most recent snapshot's `capturedAt`

---

## 6. Phase 7.2 Sweep Integration

### 6.1 Problem

Phase 7.4's `computeGexAnalytics()` currently sets `flipDistance` to `{ distance: null, distancePct: null, direction: null }` because it doesn't run `spotSweep()`. This means:
- `FLIP_ADJACENT` / `FLIP_DISTANT` profile labels are never triggered
- The SB interface `flipDistancePct` is always null

### 6.2 Solution: Optional Sweep Enrichment

Add an optional sweep step to the capture pipeline:

```
captureGexSnapshot(chain, spot, timestamp)
        |
        v
optional: spotSweep(chainRows, { spot, valuationDate })
        |
        v
enrich snapshot with sweep metadata
        |
        v
push to ring buffer
```

### 6.3 Snapshot Schema Extension (Additive, Versioned)

Add optional sweep fields to the snapshot. These are **derived** (computed from the chain), not **authoritative** (observed from the broker).

```
// Additive extension to GEXSnapshot_v1
{
  // ... existing v1 fields ...

  // Phase 7.2 sweep enrichment (optional)
  sweepData: {
    gammaFlipSpot: number | null,      // Zero-GEX level from sweep
    gammaFlipDistancePct: number | null, // |spot − flip| / spot × 100
    gammaFlipDirection: string | null,   // "above" | "below"
    callWallStrikes: number[],           // Top-N call wall strikes
    putWallStrikes: number[],            // Top-N put wall strikes
    sweepStatus: string,                 // "available" | "partial" | "unavailable"
  } | null,
}
```

**Key decisions:**
- `sweepData` is nullable — snapshots without sweep data are still valid v1 snapshots
- The sweep uses **BS model gamma** (correct — sweep is a model-based analysis)
- The broker/model gamma separation is preserved: sweep uses BS gamma, snapshot GEX uses broker gamma
- Sweep is computationally expensive (~501 grid points × BS calculations) — make it optional and configurable
- Default: sweep is **disabled** in the capture pipeline (can be enabled via config)

### 6.4 Sweep Configuration

| Parameter | Default | Notes |
|---|---|---|
| `GEX_SWEEP_ENABLED` | `false` | Opt-in due to CPU cost |
| `GEX_SWEEP_STEPS` | 501 | Grid resolution |
| `GEX_SWEEP_RANGE_PCT` | 0.30 | ±30% of spot |
| `GEX_SWEEP_WALL_TOP_N` | 3 | Top-N walls per type |

### 6.5 Integration with Analytics

`computeGexAnalytics()` would check for `snapshot.sweepData`:
- If present and recent: use `sweepData.gammaFlipDistancePct` for flip distance
- If absent or stale: set `flipDistance` to null (current behavior)
- No re-computation of sweep in the analytics layer — sweep happens at capture time

---

## 7. Live → Historical → Replay Architecture

### 7.1 Single Calculation Interface

All three paths converge on the same function:

```js
computeGexAnalytics(snapshotArrayOrBuffer, options)
```

| Path | Input | How snapshots arrive |
|---|---|---|
| **Live** | Ring buffer | `useGexCapture` pushes periodically |
| **Historical** | Ring buffer (loaded) | `buffer.load(backendSnapshots)` on startup |
| **Replay** | Plain array | Passed directly (fixture, database export, test) |

### 7.2 Deterministic Processing

- `computeGexAnalytics()` is a pure function of its input snapshots
- Same snapshots → same analytics, regardless of path
- No hidden state, no side effects, no network calls inside analytics

### 7.3 Replay Contract

To replay historical analytics:

1. Load snapshots from backend: `GET /gex/snapshots?symbol=NIFTY&limit=200`
2. Convert to canonical snapshot shape (backend `_row_to_dict` already does this)
3. Pass to `computeGexAnalytics(snapshots, { valuationDate })`
4. Result is identical to what the live path would produce

**Reproducibility guarantee:** If the same snapshots are loaded, the same analytics are produced. This holds because:
- All inputs are in the snapshot (broker gamma, OI, IV, spot, strike, expiry)
- All functions are deterministic (no randomness, no wall-clock dependency inside calculations)
- `Date.now()` is only used for freshness labels, not for calculations

### 7.4 Expiry Transitions in Replay

When replaying across an expiry roll:
- Snapshots before roll: `expiry = "2026-08-28"`
- Snapshots after roll: `expiry = "2026-09-04"`
- `expiryChanged` flag is surfaced in decomposition metadata
- Rolling windows continue uninterrupted
- No special handling needed — the ring buffer stores both

### 7.5 Strike-Set Changes in Replay

When strike sets change across snapshots:
- Only common strikes participate in decomposition
- Missing strikes contribute to residual
- Metadata surfaces the strike-set delta
- No special handling needed — Phase 7.3 already handles this

---

## 8. Data-Quality Monitoring

### 8.1 Capture-Time Checks

| Condition | Behavior | Severity |
|---|---|---|
| Chain data unavailable | No snapshot created | Normal — gap in history |
| Spot invalid (null, ≤0, NaN) | `captureGexSnapshot` returns null | Rejected |
| Snapshot fails `validateGexSnapshot` | Logged, not persisted | Warning |
| Capture interval not elapsed | Snapshot not created | Normal — throttled |
| Backend unavailable | Snapshot stored in ring buffer only | Graceful degradation |
| Duplicate `capturedAt` | Both stored (frontend); backend may dedup | Informational |

### 8.2 Historical Data Checks

| Condition | Behavior |
|---|---|
| Stale snapshots (age > 30 min) | `freshnessLabel: "stale"/"old"` surfaced in analytics |
| Timestamps out of order | Ring buffer stores in push order; analytics may produce incorrect velocity |
| Missing snapshots | Gaps produce larger Δt; velocity/acceleration still correct |
| Schema version mismatch | `validateGexSnapshot` flags unknown versions; analytics still compute |
| Methodology version mismatch | `methodologyConsistency.allSameMethodology = false` |
| NaN/Infinity in stored data | `validateGexSnapshot` flags; analytics exclude those values |

### 8.3 Abnormal Capture Intervals

| Scenario | Effect on Analytics |
|---|---|
| Capture too frequent (< 1 min) | Velocity/acceleration may be noisy; smoothing window helps |
| Capture too infrequent (> 15 min) | Velocity/acceleration have larger Δt; still correct |
| Long gap (> 1 hour) | Large Δt; velocity still correct but represents longer window |
| Capture stopped for hours | `freshnessLabel: "old"`; analytics computed on stale data |

---

## 9. Backend/Frontend Contract

### 9.1 New Backend Endpoints

| Endpoint | Method | Purpose | Auth |
|---|---|---|---|
| `POST /gex/snapshots` | POST | Store a GEX snapshot | Session required |
| `GET /gex/snapshots` | GET | Query stored snapshots | Session required |
| `GET /gex/snapshots/latest` | GET | Get most recent snapshot | Session required |
| `GET /gex/snapshots/count` | GET | Count stored snapshots | Session required |

### 9.2 POST /gex/snapshots

**Request:**
```json
{
  "symbol": "NIFTY",
  "expiry": "2026-08-28",
  "spot": 25512.0,
  "methodology": "GEX_STANDARD_V1",
  "signConvention": "NAIVE_DEALER_CONVENTION",
  "callGex": 125000000.0,
  "putGex": -98000000.0,
  "netGex": 27000000.0,
  "availabilityStatus": "available",
  "validStrikeCount": 20,
  "totalStrikeCount": 20,
  "chainAgeMs": 1200.0,
  "capturedAt": "2026-08-22T09:05:00Z",
  "strikeData": [...],
  "expiryData": [...],
  "methodologyMetadata": {...},
  "sweepData": null
}
```

**Response:**
```json
{ "ok": true, "id": 42, "duplicate": false }
```

**Behavior:**
- Validates snapshot via server-side validation
- Rejects invalid snapshots (returns 400)
- Stores in `gex_snapshots` table
- Returns the database ID
- `duplicate: true` when an existing snapshot within 1-minute tolerance is returned instead of inserting a new one
- Idempotent within 1-minute tolerance (same `captured_at` + `symbol` → skip)

### 9.3 GET /gex/snapshots

**Query parameters:**
- `symbol` (required): e.g., `"NIFTY"`
- `expiry` (optional): filter by expiry
- `limit` (optional, default 200): max snapshots
- `since` (optional): ISO-8601 timestamp filter

**Response:**
```json
{
  "snapshots": [
    { "schemaVersion": "GEXSnapshot_v1", "capturedAt": "...", ... },
    ...
  ],
  "count": 150,
  "symbol": "NIFTY"
}
```

**Behavior:**
- Returns snapshots oldest-first (for sequential ΔGEX computation)
- Limited to `limit` (max 500)
- No authentication bypass — session required

### 9.4 What Belongs in Backend vs Frontend

| Concern | Owner | Reason |
|---|---|---|
| Snapshot persistence | Backend | Durability, cross-device access |
| Snapshot validation (store-time) | Backend | Reject bad data at boundary |
| Ring buffer | Frontend | Fast access for analytics |
| Analytics computation | Frontend | No API roundtrip needed |
| Sweep computation | Frontend (at capture time) | Uses existing Phase 7.2 functions |
| Historical loading | Frontend (on startup) | Populate ring buffer |
| Pruning | Backend (on startup/cron) | Maintain retention |
| Freshness computation | Frontend | Uses `Date.now()` — must be local |

### 9.5 No Unnecessary API Changes

- Existing chain endpoints remain unchanged
- No new WebSocket channels
- No new authentication mechanisms
- GEX endpoints follow the same session-based auth pattern
- Backend GEX endpoints are read/write for snapshot data only

---

## 10. Performance Architecture

### 10.1 Capture Performance

| Operation | Cost | Frequency |
|---|---|---|
| `captureGexSnapshot` | ~1ms (10 strikes) | Every 5 min |
| `validateGexSnapshot` | <0.1ms | Every capture |
| Ring buffer push | O(1) | Every 5 min |
| Backend POST | ~10ms (network) | Every 5 min (if enabled) |

### 10.2 Analytics Performance

| Operation | Cost | Trigger |
|---|---|---|
| `computeGexAnalytics` | <5ms (200 snapshots) | Every ring buffer change |
| Spot sweep (if enabled) | ~50ms (501 steps × 10 strikes) | Every capture (optional) |

### 10.3 Startup Performance

| Operation | Cost | Trigger |
|---|---|---|
| Backend query (200 snapshots) | ~50ms | Page load |
| Ring buffer load | <1ms | Page load |
| Initial analytics computation | <5ms | Page load |

### 10.4 Database Query Strategy

- Primary query: `WHERE symbol = ? ORDER BY captured_at ASC LIMIT ?`
- Index on `(symbol, captured_at)` — already exists in model
- Optional filter: `WHERE expiry = ?` — no separate index needed (low cardinality)
- Retention pruning: `WHERE captured_at < ?` — uses the same index

### 10.5 Ring Buffer Limits

| Setting | Default | Rationale |
|---|---|---|
| Max snapshots | 200 | ~16.7 hours at 5-min intervals |
| Max snapshot size | ~5 KB | 10 strikes × ~50 bytes each |
| Max buffer memory | ~1 MB | 200 × 5 KB |
| Max backend storage | ~20 MB/quarter | 200/day × 90 days × ~1 KB avg |

### 10.6 Avoid Premature Optimization

- Current implementation recomputes all analytics on every buffer change
- At 200 snapshots, this takes <5ms — no bottleneck
- Incremental optimization (sliding windows, Welford's algorithm) is warranted only if profiling shows >50ms
- Multi-symbol support needs separate ring buffers per symbol — no architecture change

---

## 11. Failure/Recovery Behavior

### 11.1 Backend Unavailable

| Scenario | Behavior |
|---|---|
| Backend down during capture | Snapshot stored in ring buffer only; not persisted |
| Backend down during startup load | Ring buffer starts empty; analytics compute on whatever is captured live |
| Backend recovers | Subsequent captures are persisted; gap in history remains |

### 11.2 Frontend Restart

| Scenario | Behavior |
|---|---|
| Page refresh | Ring buffer cleared; historical snapshots reloaded from backend |
| Browser crash | Same as page refresh |
| Tab backgrounded | Chain feed paused; no captures; analytics stale |

### 11.3 Duplicate Capture

| Scenario | Behavior |
|---|---|
| Two captures at same timestamp | Both stored in ring buffer; velocity = null (dt=0) |
| Backend receives duplicate | Idempotent within tolerance; may skip or store both |
| Analytics with duplicates | Zero-velocity point;不影响 other metrics |

### 11.4 Partial Snapshot

| Scenario | Behavior |
|---|---|
| Chain data missing some strikes | Snapshot captured with partial strikeData |
| GEX computation partial | `availabilityStatus: "partial"` |
| Analytics on partial data | Metrics computed on available data; status flagged |

### 11.5 Persistence Failure

| Scenario | Behavior |
|---|---|
| Backend DB write fails | Frontend operates in memory-only mode |
| Backend DB corrupted | Backend returns error; frontend degrades gracefully |
| Backend DB full | Pruning runs; old snapshots deleted |

### 11.6 Malformed Historical Snapshot

| Scenario | Behavior |
|---|---|
| Missing required fields | `validateGexSnapshot` flags; analytics may compute with nulls |
| NaN/Infinity in data | Excluded from rolling windows; other metrics unaffected |
| Unknown schema version | Warning logged; analytics still compute if data is parseable |

---

## 12. Security and Data Ownership

### 12.1 Credential Safety

- No broker credentials in snapshots — snapshots contain market data only
- No API tokens in snapshot fields
- Backend GEX endpoints use same session auth as chain endpoints
- Snapshot data is user-scoped (per session)

### 12.2 Data Redistribution

- Snapshots are stored per-user, not shared across users
- No public GEX API
- No cross-user data access
- Free-data architecture preserved (all data from user's Upstox connection)

### 12.3 No New Security Surface

- GEX endpoints follow existing auth patterns
- No new CORS rules
- No new middleware
- No new authentication mechanisms

---

## 13. Mathematical and Data Integrity

### 13.1 Complete Field Audit

| Field | Source | Unit | Type | Nullable | Authoritative | Persisted | Derived |
|---|---|---|---|---|---|---|---|
| `schemaVersion` | Constant | — | string | No | Yes | Yes | No |
| `snapshotId` | Backend | — | string\|null | Yes | Yes | Yes | No |
| `capturedAt` | `Date.now()` | ISO-8601 | string | No | Yes | Yes | No |
| `valuationDate` | Config | ISO YYYY-MM-DD | string\|null | Yes | Yes | Yes | No |
| `underlying` / `symbol` | Chain | — | string | No | Yes | Yes | No |
| `spot` | Chain | Index points | number | No | Yes | Yes | No |
| `expiry` | Chain | ISO YYYY-MM-DD | string\|null | Yes | Yes | Yes | No |
| `dte` | Computed | Calendar days | number\|null | Yes | No | Yes | Yes |
| `methodology` | Constant | — | string | No | Yes | Yes | No |
| `callGex` | `chainGex()` | GEX units | number\|null | Yes | Yes | Yes | Yes |
| `putGex` | `chainGex()` | GEX units | number\|null | Yes | Yes | Yes | Yes |
| `netGex` | `chainGex()` | GEX units | number\|null | Yes | Yes | Yes | Yes |
| `availabilityStatus` | `chainGex()` | — | string | No | Yes | Yes | Yes |
| `validStrikeCount` | `chainGex()` | count | number | No | Yes | Yes | Yes |
| `totalStrikeCount` | `chainGex()` | count | number | No | Yes | Yes | Yes |
| `chainAgeMs` | Computed | Milliseconds | number\|null | Yes | Yes | Yes | Yes |
| `strikeData` | Chain + GEX | Per-strike | Array | No | Yes | Yes | Partial |
| `expiryData` | `chainGex()` | Per-expiry | Array | No | Yes | Yes | Yes |
| `methodologyMetadata` | Constant | — | Object | No | Yes | Yes | No |
| `sweepData` (optional) | `spotSweep()` | Mixed | Object\|null | Yes | No | Yes | Yes |

### 13.2 Timestamp Assumptions

- `capturedAt` is always UTC (ISO-8601 with Z suffix)
- Backend stores as `DateTime` (timezone-aware)
- Frontend computes Δt in milliseconds (timezone-agnostic)
- No timezone conversion needed — all timestamps are UTC

### 13.3 DTE Convention

- `dte = timeToExpiry(valuationDate, expiry) × 365`
- Uses calendar days (not business days)
- `valuationDate` is configurable (default: today)
- `dte` is computed at capture time and stored in the snapshot

### 13.4 OI/IV/GEX Units

| Field | Unit | Source |
|---|---|---|
| OI | Contracts (NOT lots) | Upstox `market_data.oi` |
| IV | Decimal fraction (0.18 = 18%) | Broker-computed |
| GEX | Gamma × contracts × points² × 0.01 | Phase 7.1 formula |
| Lot size | Contracts per lot — metadata only | NOT used in GEX formula |

### 13.5 Null vs Zero Semantics

| Value | Meaning |
|---|---|
| `null` | Data unavailable — not computed, missing, or invalid |
| `0` | Data computed; value is zero (valid) |
| `NaN` | Invalid computation — treated as null by analytics |
| `Infinity` | Invalid computation — treated as null by analytics |

---

## 14. Version Compatibility Rules

### 14.1 Schema Evolution

| Change Type | Action |
|---|---|
| Add nullable field | Minor version bump (backward compatible) |
| Rename field | Major version bump (breaking) |
| Remove field | Major version bump (breaking) |
| Change field type | Major version bump (breaking) |

### 14.2 Cross-Version Compatibility

- Phase 7.4 analytics consume any v1 snapshot (with nulls for missing optional fields)
- Backend can store v1 and future v2 snapshots in the same table
- Frontend ring buffer stores mixed versions — analytics handle gracefully
- `validateGexSnapshot` flags unknown versions as warnings, not errors

### 14.3 Methodology Version Independence

- Snapshots store their methodology version
- Analytics compute regardless of methodology version
- `methodologyConsistency` metadata flags mixed versions
- No methodology migration needed — old snapshots remain valid

---

## 15. Error/Edge-Case Matrix

| Condition | Capture | Persistence | Analytics | Profile Label |
|---|---|---|---|---|
| Chain unavailable | No snapshot | N/A | Gap | — |
| Spot invalid | Rejected (null) | N/A | — | UNAVAILABLE |
| Backend down | Buffer only | Skipped | Works on buffer | Works |
| Duplicate timestamp | Both stored | May dedup | velocity=null | Works |
| Out of order | Stored as-is | Stored | Incorrect velocity | Works |
| Schema version mismatch | Warning | Stored | Works | Works |
| Methodology mismatch | Warning | Stored | `allSameMethodology=false` | Works |
| Expiry transition | `expiryChanged` | Stored | Flagged | Uses current expiry |
| Strike set change | Stored | Stored | Intersection-based | Uses current strikes |
| NaN in data | Rejected by validate | May store | Excluded | Works |
| Backend restart | N/A | Table persists | Reloads from backend | — |
| Frontend restart | N/A | N/A | Reloads from backend | — |
| Long gap (>1hr) | N/A | N/A | Large Δt; correct | Works |
| Ring buffer full | Evicts oldest | N/A | Works on 200 most recent | Works |

---

## 16. Non-Goals

This design document explicitly does NOT define:

1. **Trading signals** — No BUY/SELL/LONG/SHORT
2. **Strategy execution** — No order management
3. **UI components** — No React component changes (future phase)
4. **Performance optimization** — No premature optimization
5. **Backtesting framework** — No backtest infrastructure
6. **Multi-user sharing** — Snapshots are per-user
7. **Real-time push of analytics** — Analytics computed on-demand
8. **Predictive claims** — GEX is descriptive, not predictive

---

## 17. Implementation Plan (When Approved)

### Step 1: Backend GEX API endpoints

| File | Change |
|---|---|
| `backend/app/routers/gex.py` | **NEW** — `POST /gex/snapshots`, `GET /gex/snapshots`, `GET /gex/snapshots/latest`, `GET /gex/snapshots/count` |
| `backend/app/main.py` | Add `gex.router` |
| `backend/tests/test_gex_api.py` | **NEW** — API endpoint tests |

### Step 2: Frontend persistence adapter

| File | Change |
|---|---|
| `frontend/lib/gexPersistence.js` | **NEW** — `saveSnapshot()`, `loadSnapshots()`, `loadLatestSnapshot()` |

### Step 3: Frontend capture hook

| File | Change |
|---|---|
| `frontend/lib/useGexCapture.js` | **NEW** — Integrates `useChainFeed` → `captureGexSnapshot` → ring buffer → persistence |

### Step 4: Optional sweep enrichment

| File | Change |
|---|---|
| `frontend/lib/calculations/gexHistory.js` | Add `sweepData` field to snapshot output |
| `frontend/lib/gexPersistence.js` | Include sweep data in persistence |

### Step 5: Integration with dashboard

| File | Change |
|---|---|
| `frontend/app/(app)/dashboard/page.js` | Use `useGexCapture` hook |

### Estimated scope: ~500 lines new code + ~200 lines tests

---

## 18. Testing Strategy

### 18.1 Unit Tests

- `captureGexSnapshot` with valuationDate → dte computed
- `validateGexSnapshot` with sweepData field
- Backend API endpoint tests (POST, GET, idempotency)
- Frontend persistence adapter (mock fetch)

### 18.2 Integration Tests

- Capture → persist → load → analytics roundtrip
- Live capture produces valid snapshots
- Historical load populates ring buffer correctly
- Replay produces identical analytics to live

### 18.3 Edge-Case Tests

- Backend unavailable → graceful degradation
- Duplicate capture → no corruption
- Schema version mismatch → warning, not error
- Long gap → correct velocity/acceleration

---

## 19. Recommendations

**Phase 7.6 is ready for implementation.** The design:

1. Establishes a clean capture → persist → load → compute pipeline
2. Uses existing Phase 7.1–7.5 functions without modification
3. Adds optional Phase 7.2 sweep enrichment
4. Preserves all mathematical guarantees
5. Handles all failure modes gracefully
6. Adds ~500 lines of new code (not counting tests)
7. No trading signals, no UI redesign, no architecture changes

**Recommended implementation order:**
1. Backend API endpoints (most independent)
2. Frontend persistence adapter
3. Frontend capture hook
4. Optional sweep enrichment
5. Dashboard integration
