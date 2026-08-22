/**
 * GEX Phase 7.3 — Historical Snapshots, ΔGEX Decomposition & Migration
 *
 * Provides:
 *   1. Snapshot capture from canonical chain data (wraps Phase 7.1 chainGex)
 *   2. Ring buffer for recent-snapshot fast access
 *   3. Total ΔGEX between two snapshots
 *   4. Spot-only (mechanical) ΔGEX — frozen gamma/OI/IV, only S changes
 *   5. Structure ΔGEX — OI-driven + IV-driven, frozen spot
 *   6. Complete decomposition: total = spot + OI + IV + residual
 *   7. GEX migration — gamma-weighted strike centroid shift
 *   8. Concentration metrics — top-N share of total |GEX|
 *   9. Time-series assembly from ring buffer for charting
 *  10. Snapshot → canonical chain row reconstruction (reproducibility)
 *
 * MATHEMATICAL CONTRACT:
 *
 *   HISTORICAL GEX (always uses broker-observed gamma — no model substitution):
 *     GEX_i = γ_broker_i × OI_i × S² × 0.01
 *
 *   ΔGEX_total  = GEX(S_B, γ_broker_B, OI_B) − GEX(S_A, γ_broker_A, OI_A)
 *                  [observed chain-level change]
 *
 *   ΔGEX_spot   = Σ γ_broker_A(K) × OI_A(K) × (S_B² − S_A²) × 0.01
 *                  [mechanical: frozen BROKER gamma and OI from A, only spot changes]
 *
 *   ΔGEX_OI     = Σ [OI_B(K) − OI_A(K)] × γ_BS(S_A, K, T, IV_A) × S_A² × 0.01
 *                  [MODEL-BASED ATTRIBUTION: uses BS gamma, not broker gamma]
 *                  [frozen spot, old IV — isolates OI effect]
 *
 *   ΔGEX_IV     = Σ OI_B(K) × [γ_BS(S_A,K,T,IV_B) − γ_BS(S_A,K,T,IV_A)] × S_A² × 0.01
 *                  [MODEL-BASED ATTRIBUTION: uses BS gamma, not broker gamma]
 *                  [frozen spot, new OI — isolates IV effect]
 *
 *   ΔGEX_residual = ΔGEX_total − ΔGEX_spot − ΔGEX_OI − ΔGEX_IV
 *                  [EXPLICITLY CALCULATED — not forced to zero]
 *                  [absorbs: broker gamma drift not explained by IV, cross-terms,
 *                   missing data, methodology mismatch, rounding]
 *
 *   INVARIANT (always holds by construction — residual is defined as the gap):
 *     total = spot + OI + IV + residual
 *
 * IMPORTANT: The OI and IV attributions use BS MODEL gamma, not broker gamma.
 * This means the decomposition attributes changes to IV only insofar as the
 * BS model links IV → gamma. Broker gamma can change for reasons other than
 * IV (spot movement, time decay, market microstructure), and those changes
 * appear in the residual — NOT in the IV attribution.
 *
 * SIGN CONVENTION (inherited from Phase 7.1):
 *   Call GEX = + raw GEX    Put GEX = − raw GEX
 *
 * INTERPRETATION:
 *   ΔGEX positive/negative is NOT bullish/bearish.
 *   Migration "up"/"down" does NOT predict price direction.
 *   These are market-structure analytics, not trading signals.
 *
 * Reference: GEX_V1_0_SPEC.md §18-19
 */

import { chainGex, rawGex, GEX_STATUS, GEX_METHOD_VERSION } from "./gex";
import { modelGamma } from "./gexPhase72";
import { timeToExpiry } from "./pricing.js";

// ---- Constants ---------------------------------------------------------------

export const GEX_HISTORY_VERSION = "GEX_HISTORY_V1";

/** Canonical snapshot schema version */
export const GEX_SNAPSHOT_SCHEMA_VERSION = "GEXSnapshot_v1";

/** Default snapshot capture interval: 5 minutes */
export const DEFAULT_SNAPSHOT_INTERVAL_MS = 300_000;

/** Maximum ring-buffer capacity */
export const DEFAULT_MAX_SNAPSHOTS = 200;

/** Default migration threshold: 0.1% of spot (in fraction) */
export const DEFAULT_MIGRATION_THRESHOLD_PCT = 0.001;

/** Floating-point tolerance for invariant checks */
export const INVARIANT_TOLERANCE = 1e-6;

/** Minimum time-to-expiry in years for BS gamma validity */
const MIN_T_FOR_BS = 1 / 365;

// ---- Snapshot capture --------------------------------------------------------

/**
 * Capture a GEX snapshot from a canonical chain response.
 *
 * Internally calls Phase 7.1 chainGex() and packages the result with
 * per-strike broker-observed inputs for reproducibility.
 *
 * @param {object} chain — chain response: { symbol, underlying_spot_price, expiry_date, chain: [...] }
 * @param {number} spot  — underlying spot price
 * @param {string|number} timestamp — ISO 8601 or Date.now()
 * @param {object} [options]
 * @param {string} [options.symbol] — override symbol
 * @param {string[]} [options.scopeExpiries] — filter expiries
 * @param {string} [options.valuationDate] — ISO YYYY-MM-DD for DTE computation
 * @returns {object|null} snapshot object (GEXSnapshot_v1), or null if spot is invalid
 */
export function captureGexSnapshot(chain, spot, timestamp, options = {}) {
  if (!Number.isFinite(spot) || spot <= 0) return null;
  if (!chain || !chain.chain || chain.chain.length === 0) return null;

  const symbol = options.symbol ?? chain.symbol ?? null;
  const expiry = chain.expiry_date ?? null;

  // Run Phase 7.1 GEX computation
  const gexResult = chainGex(chain.chain, { spot, symbol, scopeExpiries: options.scopeExpiries });

  // Extract per-strike data with broker-observed inputs
  const strikeData = (chain.chain || []).map((row) => {
    const call = row.call || {};
    const put = row.put || {};
    const callGamma = call.gamma != null ? Number(call.gamma) : null;
    const callOi = call.oi != null ? Number(call.oi) : null;
    const callIv = call.iv != null ? Number(call.iv) : null;
    const putGamma = put.gamma != null ? Number(put.gamma) : null;
    const putOi = put.oi != null ? Number(put.oi) : null;
    const putIv = put.iv != null ? Number(put.iv) : null;

    // Find matching strike in GEX result
    const strikeGex = gexResult.byStrike?.find((s) => s.strike === row.strike) ?? {};

    return {
      strike: row.strike,
      callGamma,
      callOi,
      callIv,
      callGex: strikeGex.callGex ?? null,
      putGamma,
      putOi,
      putIv,
      putGex: strikeGex.putGex ?? null,
      netGex: strikeGex.netGex ?? null,
    };
  });

  // Extract expiry-level data
  const expiryData = (gexResult.byExpiry || []).map((e) => ({
    expiry: e.expiry,
    callGex: e.callGex,
    putGex: e.putGex,
    netGex: e.netGex,
    availabilityStatus: e.availabilityStatus,
    validStrikeCount: e.validStrikeCount,
    totalStrikeCount: e.totalStrikeCount,
  }));

  // Methodology metadata
  const methodologyMetadata = {
    gexVersion: GEX_METHOD_VERSION,
    formula: "gamma * oi * spot^2 * 0.01",
    oiUnit: "contracts",
    signConvention: "NAIVE_DEALER_CONVENTION",
    callSign: 1,
    putSign: -1,
    lotSizeFactorApplied: false,
  };

  // Capture timestamp
  let capturedAt;
  if (typeof timestamp === "number") {
    capturedAt = new Date(timestamp).toISOString();
  } else if (typeof timestamp === "string") {
    capturedAt = timestamp;
  } else {
    capturedAt = new Date().toISOString();
  }

  // Chain age (ms since earliest quote_timestamp in the chain)
  const chainAgeMs = _computeChainAge(chain.chain);

  // Compute DTE if valuationDate provided
  const valuationDate = options.valuationDate ?? null;
  let dte = null;
  if (valuationDate && expiry) {
    const tYears = timeToExpiry(valuationDate, expiry);
    if (tYears != null && Number.isFinite(tYears) && tYears >= 0) {
      dte = tYears * 365;
    }
  }

  return {
    // Schema version
    schemaVersion: GEX_SNAPSHOT_SCHEMA_VERSION,
    snapshotId: null, // populated by backend persistence

    // Temporal
    capturedAt,
    valuationDate,

    // Market identity
    symbol,
    underlying: symbol,
    spot,

    // Expiry
    expiry,
    dte,

    // Methodology
    methodology: GEX_METHOD_VERSION,
    signConvention: "NAIVE_DEALER_CONVENTION",

    // Chain-level GEX
    callGex: gexResult.callGex,
    putGex: gexResult.putGex,
    netGex: gexResult.netGex,

    // Chain quality
    availabilityStatus: gexResult.availabilityStatus,
    validStrikeCount: gexResult.validStrikeCount,
    totalStrikeCount: gexResult.totalOptionCount,
    chainAgeMs,

    // Strike and expiry data
    strikeData,
    expiryData,
    methodologyMetadata,
  };
}

// ---- Ring Buffer -------------------------------------------------------------

/**
 * In-memory FIFO ring buffer for GEX snapshots.
 * Stores up to maxSize snapshots; oldest are evicted when full.
 */
export class GexRingBuffer {
  constructor(maxSize = DEFAULT_MAX_SNAPSHOTS, intervalMs = DEFAULT_SNAPSHOT_INTERVAL_MS) {
    this.maxSize = maxSize;
    this.intervalMs = intervalMs;
    this.snapshots = [];
    this.lastCaptureAt = 0;
  }

  /**
   * Whether enough time has elapsed since the last capture.
   * @param {number} [now] — current time in ms (for testing)
   * @returns {boolean}
   */
  shouldCapture(now = Date.now()) {
    return now - this.lastCaptureAt >= this.intervalMs;
  }

  /**
   * Add a snapshot to the buffer. Evicts oldest if at capacity.
   * @param {object} snapshot
   */
  push(snapshot) {
    if (!snapshot) return;
    this.snapshots.push(snapshot);
    if (this.snapshots.length > this.maxSize) {
      this.snapshots.shift();
    }
    const ts = new Date(snapshot.capturedAt).getTime();
    if (Number.isFinite(ts) && ts > this.lastCaptureAt) {
      this.lastCaptureAt = ts;
    }
  }

  /** Get all snapshots in chronological order. */
  getAll() {
    return [...this.snapshots];
  }

  /** Get the last N snapshots (most recent at end). */
  recent(n = 10) {
    return this.snapshots.slice(-n);
  }

  /** Get the snapshot closest to a target timestamp. */
  closest(timestamp) {
    if (!this.snapshots.length) return null;
    const target = typeof timestamp === "number" ? timestamp : new Date(timestamp).getTime();
    let best = null;
    let bestDist = Infinity;
    for (const s of this.snapshots) {
      const t = new Date(s.capturedAt).getTime();
      const dist = Math.abs(t - target);
      if (dist < bestDist) {
        bestDist = dist;
        best = s;
      }
    }
    return best;
  }

  /** Current buffer size. */
  size() {
    return this.snapshots.length;
  }

  /** Clear all snapshots. */
  clear() {
    this.snapshots = [];
    this.lastCaptureAt = 0;
  }

  /**
   * Load snapshots from an array (e.g., fetched from backend).
   * Replaces existing content. Snapshots should be oldest-first.
   * @param {Array} snapshots
   */
  load(snapshots = []) {
    this.snapshots = snapshots.slice(-this.maxSize);
    if (this.snapshots.length > 0) {
      const ts = new Date(this.snapshots[this.snapshots.length - 1].capturedAt).getTime();
      this.lastCaptureAt = Number.isFinite(ts) ? ts : 0;
    } else {
      this.lastCaptureAt = 0;
    }
  }
}

// ---- Total ΔGEX --------------------------------------------------------------

/**
 * Compute total ΔGEX between two snapshots.
 *
 * @param {object} a — earlier snapshot
 * @param {object} b — later snapshot
 * @returns {{ total, deltaTimeMs, spotChange, status }}
 */
export function computeDeltaGex(a, b) {
  if (!a || !b) return { total: null, deltaTimeMs: null, spotChange: null, status: "unavailable" };

  const totalA = a.netGex;
  const totalB = b.netGex;
  if (totalA == null || totalB == null || !Number.isFinite(totalA) || !Number.isFinite(totalB)) {
    return { total: null, deltaTimeMs: _deltaTime(a, b), spotChange: b.spot - a.spot, status: "unavailable" };
  }

  return {
    total: totalB - totalA,
    deltaTimeMs: _deltaTime(a, b),
    spotChange: b.spot - a.spot,
    status: "available",
  };
}

// ---- Spot-only ΔGEX (Mechanical) --------------------------------------------

/**
 * Compute spot-only (mechanical) ΔGEX.
 * "What would GEX be if only spot moved, with frozen gamma/OI/IV from snapshot A?"
 *
 * Uses broker gamma from snapshot A — no BS recomputation needed.
 * Formula per strike: γ_A(K) × OI_A(K) × (S_B² − S_A²) × 0.01
 *
 * @param {object} a — earlier snapshot
 * @param {object} b — later snapshot
 * @returns {{ spotDelta, perStrike, status }}
 */
export function computeSpotDeltaGex(a, b) {
  if (!a || !b) return { spotDelta: null, perStrike: [], status: "unavailable" };

  const s2Diff = b.spot * b.spot - a.spot * a.spot;
  const perStrike = [];
  let total = 0;
  let hasAny = false;

  const strikesA = _indexByStrike(a.strikeData || []);
  const strikesB = new Set((b.strikeData || []).map((s) => s.strike));

  for (const s of a.strikeData || []) {
    // Only include strikes present in both snapshots
    if (!strikesB.has(s.strike)) continue;

    const callGamma = s.callGamma;
    const callOi = s.callOi;
    const putGamma = s.putGamma;
    const putOi = s.putOi;

    let callContrib = 0;
    let putContrib = 0;
    let valid = false;

    if (callGamma != null && callOi != null && Number.isFinite(callGamma) && callOi > 0) {
      callContrib = callGamma * callOi * s2Diff * 0.01;
      valid = true;
    }
    if (putGamma != null && putOi != null && Number.isFinite(putGamma) && putOi > 0) {
      // Put GEX is negative under convention: raw GEX * -1
      putContrib = -putGamma * putOi * s2Diff * 0.01;
      valid = true;
    }

    if (valid) {
      total += callContrib + putContrib;
      hasAny = true;
      perStrike.push({
        strike: s.strike,
        callContrib,
        putContrib,
        netContrib: callContrib + putContrib,
      });
    }
  }

  return {
    spotDelta: hasAny ? total : null,
    perStrike,
    status: hasAny ? "available" : "unavailable",
  };
}

// ---- Structure ΔGEX (OI/IV-driven) ------------------------------------------

/**
 * Compute structure (OI/IV-driven) ΔGEX.
 *
 * THIS IS MODEL-BASED ATTRIBUTION. It uses Black-Scholes model gamma
 * (not broker gamma) to decompose changes into OI and IV components.
 *
 * Why BS model gamma? Broker gamma changes cannot be decomposed into
 * OI vs IV contributions because broker gamma is a direct market observation
 * that may differ from BS gamma due to time decay, spot movement effects,
 * market microstructure, or model limitations. By using BS gamma, we can
 * hold the gamma function constant and isolate the OI and IV effects.
 *
 * IMPORTANT: The IV attribution captures only the gamma change that the
 * BS model attributes to IV. Broker gamma can change for reasons other
 * than IV — those changes appear in the decomposition RESIDUAL, not in
 * the IV attribution.
 *
 * For each strike K:
 *   γ_old = BS_gamma(type, S_A, K, T, IV_A(K))  [NOT broker gamma]
 *   γ_new = BS_gamma(type, S_A, K, T, IV_B(K))  [NOT broker gamma]
 *
 *   ΔGEX_OI(K) = [OI_B(K) − OI_A(K)] × γ_old × S_A² × 0.01
 *   ΔGEX_IV(K) = OI_B(K) × [γ_new − γ_old] × S_A² × 0.01
 *
 * The OI attribution uses old gamma (holding IV constant).
 * The IV attribution uses new OI (holding OI at its updated level).
 *
 * @param {object} a — earlier snapshot
 * @param {object} b — later snapshot
 * @param {object} options — { T, r, q } for BS model
 * @returns {{ oiDelta, ivDelta, structureDelta, perStrike, status }}
 */
export function computeStructureDeltaGex(a, b, options = {}) {
  if (!a || !b) return { oiDelta: null, ivDelta: null, structureDelta: null, perStrike: [], status: "unavailable" };

  const { T = 1 / 52, r = 0, q = 0 } = options;
  const sA2 = a.spot * a.spot;
  const strikesA = _indexByStrike(a.strikeData || []);
  const strikesB = _indexByStrike(b.strikeData || []);

  // Find common strikes
  const commonStrikes = [];
  for (const key of Object.keys(strikesA)) {
    if (strikesB[key]) commonStrikes.push(Number(key));
  }
  commonStrikes.sort((x, y) => x - y);

  const perStrike = [];
  let oiTotal = 0;
  let ivTotal = 0;
  let hasAny = false;

  for (const K of commonStrikes) {
    const sA = strikesA[K];
    const sB = strikesB[K];

    const oiA_call = sA.callOi;
    const oiB_call = sB.callOi;
    const ivA_call = sA.callIv;
    const ivB_call = sB.callIv;
    const oiA_put = sA.putOi;
    const oiB_put = sB.putOi;
    const ivA_put = sA.putIv;
    const ivB_put = sB.putIv;

    let callOiContrib = 0;
    let callIvContrib = 0;
    let putOiContrib = 0;
    let putIvContrib = 0;
    let valid = false;

    // Call side
    if (ivA_call != null && ivA_call > 0 && T > MIN_T_FOR_BS && a.spot > 0) {
      const gammaOld = modelGamma("call", a.spot, K, T, ivA_call, r, q);
      const gammaNew = ivB_call != null && ivB_call > 0
        ? modelGamma("call", a.spot, K, T, ivB_call, r, q)
        : gammaOld;

      if (gammaOld != null && Number.isFinite(gammaOld)) {
        // OI change with old gamma
        const oiChange = (oiB_call != null ? oiB_call : 0) - (oiA_call != null ? oiA_call : 0);
        if (oiChange !== 0) {
          callOiContrib = oiChange * gammaOld * sA2 * 0.01;
        }
        // IV change with new OI
        const newOi = oiB_call != null ? oiB_call : 0;
        if (gammaNew != null && Number.isFinite(gammaNew) && newOi > 0) {
          const gammaDiff = gammaNew - gammaOld;
          if (gammaDiff !== 0) {
            callIvContrib = newOi * gammaDiff * sA2 * 0.01;
          }
        }
        valid = true;
      }
    }

    // Put side
    if (ivA_put != null && ivA_put > 0 && T > MIN_T_FOR_BS && a.spot > 0) {
      const gammaOld = modelGamma("put", a.spot, K, T, ivA_put, r, q);
      const gammaNew = ivB_put != null && ivB_put > 0
        ? modelGamma("put", a.spot, K, T, ivB_put, r, q)
        : gammaOld;

      if (gammaOld != null && Number.isFinite(gammaOld)) {
        const oiChange = (oiB_put != null ? oiB_put : 0) - (oiA_put != null ? oiA_put : 0);
        if (oiChange !== 0) {
          // Put GEX is negative under convention
          putOiContrib = -oiChange * gammaOld * sA2 * 0.01;
        }
        const newOi = oiB_put != null ? oiB_put : 0;
        if (gammaNew != null && Number.isFinite(gammaNew) && newOi > 0) {
          const gammaDiff = gammaNew - gammaOld;
          if (gammaDiff !== 0) {
            putIvContrib = -newOi * gammaDiff * sA2 * 0.01;
          }
        }
        valid = true;
      }
    }

    if (valid) {
      const oiContrib = callOiContrib + putOiContrib;
      const ivContrib = callIvContrib + putIvContrib;
      oiTotal += oiContrib;
      ivTotal += ivContrib;
      hasAny = true;
      perStrike.push({
        strike: K,
        callOiContrib,
        callIvContrib,
        putOiContrib,
        putIvContrib,
        oiContrib,
        ivContrib,
      });
    }
  }

  return {
    oiDelta: hasAny ? oiTotal : null,
    ivDelta: hasAny ? ivTotal : null,
    structureDelta: hasAny ? oiTotal + ivTotal : null,
    perStrike,
    status: hasAny ? "available" : "unavailable",
  };
}

// ---- Complete Decomposition --------------------------------------------------

/**
 * Complete ΔGEX decomposition: total = spot + OI + IV + residual.
 *
 * The residual captures cross-terms (interaction between spot movement and
 * OI/IV changes). It is calculated, not forced to zero.
 *
 * @param {object} a — earlier snapshot
 * @param {object} b — later snapshot
 * @param {object} options — { T, r, q } for BS model
 * @returns {object} decomposition result
 */
export function decomposeDeltaGex(a, b, options = {}) {
  const total = computeDeltaGex(a, b);
  const spot = computeSpotDeltaGex(a, b);
  const structure = computeStructureDeltaGex(a, b, options);

  const totalVal = total.total;
  const spotVal = spot.spotDelta;
  const oiVal = structure.oiDelta;
  const ivVal = structure.ivDelta;

  // Residual = total − spot − OI − IV (calculated, not forced)
  let residual = null;
  if (totalVal != null && spotVal != null && oiVal != null && ivVal != null) {
    residual = totalVal - spotVal - oiVal - ivVal;
  }

  // Invariant check
  let invariantOk = null;
  if (totalVal != null && spotVal != null && oiVal != null && ivVal != null && residual != null) {
    const reconstructed = spotVal + oiVal + ivVal + residual;
    invariantOk = Math.abs(totalVal - reconstructed) <= Math.max(Math.abs(totalVal) * INVARIANT_TOLERANCE, INVARIANT_TOLERANCE);
  }

  // Percentage breakdown (relative to |total|)
  const absTotal = totalVal != null ? Math.abs(totalVal) : 0;
  const pct = (val) => (val != null && absTotal > 0 ? (val / absTotal) * 100 : null);

  // Resolve status
  let status = "unavailable";
  if (total.status === "available" && spot.status === "available") {
    status = structure.status === "available" ? "available" : "partial";
  } else if (total.status === "available" || spot.status === "available") {
    status = "partial";
  }

  // Expiry change detection
  const expiryChanged = a.expiry !== b.expiry;

  return {
    // Components
    total: totalVal,
    spot: spotVal,
    oi: oiVal,
    iv: ivVal,
    residual,
    // Percentages
    spotPct: pct(spotVal),
    oiPct: pct(oiVal),
    ivPct: pct(ivVal),
    residualPct: pct(residual),
    // Invariant
    invariantOk,
    // Metadata
    deltaTimeMs: total.deltaTimeMs,
    spotChange: total.spotChange,
    expiryChanged,
    status,
    // Sub-results for debugging
    _totalDetail: total,
    _spotDetail: spot,
    _structureDetail: structure,
  };
}

// ---- GEX Migration -----------------------------------------------------------

/**
 * Compute GEX migration: spatial shift of gamma concentration across strikes.
 *
 * Uses the gamma-weighted strike centroid:
 *   centroid = Σ (|netGex(K)| × K) / Σ |netGex(K)|
 *
 * Migration direction is independent of ΔGEX magnitude:
 *   - GEX can increase without migration
 *   - Migration can occur without magnitude change
 *
 * @param {object} a — earlier snapshot
 * @param {object} b — later snapshot
 * @param {number} [thresholdPct=0.001] — migration threshold as fraction of spot
 * @returns {object} migration result
 */
export function computeGexMigration(a, b, thresholdPct = DEFAULT_MIGRATION_THRESHOLD_PCT) {
  if (!a || !b) {
    return {
      centroidA: null, centroidB: null, migration: null,
      direction: "unavailable", threshold: null,
      concentrationA: null, concentrationB: null,
      expiryMigrations: [], status: "unavailable",
    };
  }

  const centroidA = computeStrikeCentroid(a.strikeData || []);
  const centroidB = computeStrikeCentroid(b.strikeData || []);

  let migration = null;
  let direction = "unavailable";
  const threshold = Math.max(a.spot * thresholdPct, 1); // at least 1 point

  if (centroidA != null && centroidB != null) {
    migration = centroidB - centroidA;
    if (Math.abs(migration) <= threshold) {
      direction = "stable";
    } else {
      direction = migration > 0 ? "up" : "down";
    }
  }

  const concentrationA = computeConcentration(a.strikeData || []);
  const concentrationB = computeConcentration(b.strikeData || []);

  // Per-expiry migrations
  const expiryMigrations = _computeExpiryMigrations(a, b, thresholdPct);

  const status = (centroidA != null && centroidB != null) ? "available" : "unavailable";

  return {
    centroidA,
    centroidB,
    migration,
    direction,
    threshold,
    concentrationA,
    concentrationB,
    expiryMigrations,
    status,
  };
}

/**
 * Compute gamma-weighted strike centroid.
 * centroid = Σ (|netGex(K)| × K) / Σ |netGex(K)|
 *
 * @param {Array} strikeData — [{ strike, netGex, ... }]
 * @returns {number|null} centroid strike, or null if unresolvable
 */
export function computeStrikeCentroid(strikeData) {
  if (!strikeData || strikeData.length === 0) return null;

  let weightedSum = 0;
  let weightSum = 0;

  for (const s of strikeData) {
    const ng = s.netGex;
    if (ng == null || !Number.isFinite(ng)) continue;
    const absNg = Math.abs(ng);
    if (absNg <= 0) continue;
    weightedSum += absNg * s.strike;
    weightSum += absNg;
  }

  return weightSum > 0 ? weightedSum / weightSum : null;
}

/**
 * Compute gamma concentration metrics.
 *
 * @param {Array} strikeData — [{ strike, netGex, ... }]
 * @returns {{ top3Pct, top5Pct, top10Pct, totalAbsoluteGex, strikeCount }}
 */
export function computeConcentration(strikeData) {
  if (!strikeData || strikeData.length === 0) {
    return { top3Pct: null, top5Pct: null, top10Pct: null, totalAbsoluteGex: 0, strikeCount: 0 };
  }

  const absGex = strikeData
    .map((s) => (s.netGex != null && Number.isFinite(s.netGex) ? Math.abs(s.netGex) : 0))
    .filter((v) => v > 0)
    .sort((a, b) => b - a);

  const total = absGex.reduce((sum, v) => sum + v, 0);
  if (total <= 0) {
    return { top3Pct: 0, top5Pct: 0, top10Pct: 0, totalAbsoluteGex: 0, strikeCount: absGex.length };
  }

  const topN = (n) => {
    const sum = absGex.slice(0, n).reduce((s, v) => s + v, 0);
    return (sum / total) * 100;
  };

  return {
    top3Pct: topN(3),
    top5Pct: topN(5),
    top10Pct: topN(10),
    totalAbsoluteGex: total,
    strikeCount: absGex.length,
  };
}

// ---- Time-series assembly ----------------------------------------------------

/**
 * Assemble time-series data from a ring buffer or snapshot array.
 *
 * @param {GexRingBuffer|Array} source — ring buffer or array of snapshots
 * @param {object} [options]
 * @param {string} [options.expiry] — filter by expiry
 * @returns {object} time-series for charting
 */
export function assembleGexTimeSeries(source, options = {}) {
  const snapshots = Array.isArray(source) ? source : source.getAll();
  if (!snapshots.length) {
    return {
      points: [],
      deltaGexSeries: [],
      migrationSeries: [],
      summary: { start: null, end: null, dataPoints: 0, timeRangeMs: 0 },
    };
  }

  // Filter by expiry if specified
  let filtered = snapshots;
  if (options.expiry) {
    filtered = snapshots.filter((s) => s.expiry === options.expiry);
  }

  // Sort by timestamp
  filtered.sort((a, b) => new Date(a.capturedAt).getTime() - new Date(b.capturedAt).getTime());

  // Assemble points
  const points = filtered.map((s) => ({
    timestamp: s.capturedAt,
    spot: s.spot,
    netGex: s.netGex,
    callGex: s.callGex,
    putGex: s.putGex,
    dataQuality: s.availabilityStatus,
    expiry: s.expiry,
  }));

  // Delta GEX series (sequential pairs)
  const deltaGexSeries = [];
  for (let i = 1; i < filtered.length; i++) {
    const delta = computeDeltaGex(filtered[i - 1], filtered[i]);
    const decomposed = decomposeDeltaGex(filtered[i - 1], filtered[i]);
    deltaGexSeries.push({
      timestamp: filtered[i].capturedAt,
      totalDelta: delta.total,
      spotDelta: decomposed.spot,
      oiDelta: decomposed.oi,
      ivDelta: decomposed.iv,
      residualDelta: decomposed.residual,
      deltaTimeMs: delta.deltaTimeMs,
      status: delta.status,
    });
  }

  // Migration series
  const migrationSeries = [];
  for (let i = 1; i < filtered.length; i++) {
    const mig = computeGexMigration(filtered[i - 1], filtered[i]);
    if (mig.status === "available") {
      migrationSeries.push({
        timestamp: filtered[i].capturedAt,
        centroid: mig.centroidB,
        direction: mig.direction,
        migration: mig.migration,
      });
    }
  }

  const first = filtered[0];
  const last = filtered[filtered.length - 1];

  return {
    points,
    deltaGexSeries,
    migrationSeries,
    summary: {
      start: first?.capturedAt ?? null,
      end: last?.capturedAt ?? null,
      dataPoints: filtered.length,
      timeRangeMs: first && last
        ? new Date(last.capturedAt).getTime() - new Date(first.capturedAt).getTime()
        : 0,
    },
  };
}

// ---- Reproducibility ---------------------------------------------------------

/**
 * Reconstruct canonical chain rows from a snapshot.
 * Enables running Phase 7.1 chainGex() against historical data.
 *
 * @param {object} snapshot
 * @returns {Array} — [{ strike, expiry, call: { gamma, oi, iv }, put: { gamma, oi, iv } }]
 */
export function reconstructChainRows(snapshot) {
  if (!snapshot || !snapshot.strikeData) return [];
  return snapshot.strikeData.map((s) => ({
    strike: s.strike,
    expiry: snapshot.expiry,
    call: {
      gamma: s.callGamma,
      oi: s.callOi,
      iv: s.callIv,
    },
    put: {
      gamma: s.putGamma,
      oi: s.putOi,
      iv: s.putIv,
    },
  }));
}

// ---- Data quality ------------------------------------------------------------

/**
 * Assess the data quality of a snapshot.
 * @param {object} snapshot
 * @returns {object}
 */
export function snapshotDataQuality(snapshot) {
  if (!snapshot) {
    return { status: "unavailable", strikeCount: 0, validStrikeCount: 0, chainAgeMs: null };
  }
  return {
    status: snapshot.availabilityStatus ?? "unavailable",
    strikeCount: snapshot.totalStrikeCount ?? 0,
    validStrikeCount: snapshot.validStrikeCount ?? 0,
    chainAgeMs: snapshot.chainAgeMs ?? null,
    expiry: snapshot.expiry ?? null,
    methodology: snapshot.methodology ?? null,
  };
}

// ---- Snapshot validation ----------------------------------------------------

/**
 * Validate a GEX snapshot and report data-quality issues.
 *
 * Returns a deterministic validation result without modifying the snapshot.
 * Null means unavailable; never silently converts null to zero.
 *
 * @param {object} snapshot — candidate snapshot
 * @returns {{ valid: boolean, issues: string[], warnings: string[], snapshotVersion: string|null }}
 */
export function validateGexSnapshot(snapshot) {
  const issues = [];
  const warnings = [];

  if (!snapshot || typeof snapshot !== "object") {
    return { valid: false, issues: ["NOT_OBJECT"], warnings: [], snapshotVersion: null };
  }

  // Schema version
  const sv = snapshot.schemaVersion ?? null;
  if (sv === null) {
    warnings.push("MISSING_SCHEMA_VERSION");
  } else if (sv !== GEX_SNAPSHOT_SCHEMA_VERSION) {
    issues.push("UNKNOWN_SCHEMA_VERSION:" + sv);
  }

  // CapturedAt
  const cat = snapshot.capturedAt;
  if (cat == null) {
    issues.push("MISSING_CAPTURED_AT");
  } else {
    const ms = new Date(cat).getTime();
    if (!Number.isFinite(ms)) {
      issues.push("INVALID_CAPTURED_AT");
    } else if (ms < 0) {
      issues.push("NEGATIVE_TIMESTAMP");
    }
  }

  // Spot
  const spot = snapshot.spot;
  if (spot == null || !Number.isFinite(spot)) {
    issues.push("MISSING_OR_INVALID_SPOT");
  } else if (spot <= 0) {
    issues.push("NON_POSITIVE_SPOT");
  }

  // Net GEX
  const netGex = snapshot.netGex;
  if (netGex != null && !Number.isFinite(netGex)) {
    issues.push("INVALID_NET_GEX");
  }

  // Call / Put GEX
  const callGex = snapshot.callGex;
  const putGex = snapshot.putGex;
  if (callGex != null && !Number.isFinite(callGex)) {
    issues.push("INVALID_CALL_GEX");
  }
  if (putGex != null && !Number.isFinite(putGex)) {
    issues.push("INVALID_PUT_GEX");
  }

  // Symbol
  const symbol = snapshot.symbol ?? snapshot.underlying;
  if (!symbol || typeof symbol !== "string" || symbol.trim().length === 0) {
    issues.push("MISSING_SYMBOL");
  }

  // Expiry
  if (snapshot.expiry != null && typeof snapshot.expiry !== "string") {
    issues.push("INVALID_EXPIRY_TYPE");
  }

  // Methodology
  if (snapshot.methodology == null) {
    warnings.push("MISSING_METHODOLOGY");
  }

  // Strike data
  const sd = snapshot.strikeData;
  if (sd != null) {
    if (!Array.isArray(sd)) {
      issues.push("STRIKE_DATA_NOT_ARRAY");
    } else {
      for (let i = 0; i < sd.length; i++) {
        const s = sd[i];
        if (s == null || typeof s !== "object") {
          issues.push("INVALID_STRIKE_ENTRY:" + i);
          continue;
        }
        if (s.strike == null || !Number.isFinite(s.strike)) {
          issues.push("INVALID_STRIKE_VALUE:" + i);
        }
        // Check for NaN/Infinity in key fields
        for (const field of ["callGamma", "callOi", "putGamma", "putOi", "callGex", "putGex", "netGex"]) {
          const v = s[field];
          if (v != null && !Number.isFinite(v)) {
            warnings.push("NON_FINITE_" + field.toUpperCase() + "_AT_STRIKE_" + s.strike);
          }
        }
      }
    }
  }

  // Expiry data
  const ed = snapshot.expiryData;
  if (ed != null && !Array.isArray(ed)) {
    issues.push("EXPIRY_DATA_NOT_ARRAY");
  }

  // Duplicate detection (informational)
  // Cannot detect duplicates from a single snapshot; this is for batch validation

  // DTE
  const dte = snapshot.dte;
  if (dte != null && (!Number.isFinite(dte) || dte < 0)) {
    warnings.push("INVALID_DTE");
  }

  return {
    valid: issues.length === 0,
    issues,
    warnings,
    snapshotVersion: sv,
  };
}

// ---- Internal helpers --------------------------------------------------------

/**
 * Index strike data by strike value for O(1) lookup.
 */
function _indexByStrike(strikeData) {
  const map = {};
  for (const s of strikeData) {
    map[s.strike] = s;
  }
  return map;
}

/**
 * Compute time difference between two snapshots in ms.
 */
function _deltaTime(a, b) {
  if (!a?.capturedAt || !b?.capturedAt) return null;
  const tA = new Date(a.capturedAt).getTime();
  const tB = new Date(b.capturedAt).getTime();
  return Number.isFinite(tA) && Number.isFinite(tB) ? tB - tA : null;
}

/**
 * Compute chain age (ms since earliest quote_timestamp in chain rows).
 */
function _computeChainAge(chainRows) {
  if (!chainRows || chainRows.length === 0) return null;
  let earliest = Infinity;
  for (const row of chainRows) {
    const ts = row.call?.quote_timestamp || row.put?.quote_timestamp;
    if (ts) {
      const t = new Date(ts).getTime();
      if (Number.isFinite(t) && t < earliest) earliest = t;
    }
  }
  if (!Number.isFinite(earliest)) return null;
  return Date.now() - earliest;
}

/**
 * Compute per-expiry migration.
 */
function _computeExpiryMigrations(a, b, thresholdPct) {
  const expiriesA = new Map();
  const expiriesB = new Map();

  // Group by expiry using expiryData if available, otherwise use strikeData
  for (const e of a.expiryData || []) {
    expiriesA.set(e.expiry, e);
  }
  for (const e of b.expiryData || []) {
    expiriesB.set(e.expiry, e);
  }

  const migrations = [];
  for (const [expiry, dataA] of expiriesA) {
    const dataB = expiriesB.get(expiry);
    if (!dataB) continue;
    // Use expiry-level netGex for basic comparison
    migrations.push({
      expiry,
      netGexA: dataA.netGex,
      netGexB: dataB.netGex,
      change: dataB.netGex != null && dataA.netGex != null ? dataB.netGex - dataA.netGex : null,
    });
  }

  return migrations;
}
