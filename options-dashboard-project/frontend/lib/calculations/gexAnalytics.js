/**
 * GEX Phase 7.4d — Analytics Coordinator & Strategy Builder Interface
 *
 * Orchestrates Phases 7.4a–7.4c into a single entry point.
 * Provides the interface through which future Strategy Builder (Phase 7.8+)
 * can consume GEX analytics without coupling to internal module structure.
 *
 * MATHEMATICAL CONTRACT:
 *
 *   This module computes NO new formulas. It aggregates results from:
 *     - Phase 7.1/7.2 (consumed indirectly via snapshots)
 *     - Phase 7.3 (snapshots, decomposition, migration, concentration)
 *     - Phase 7.4a (gexTimeSeries.js — rolling analytics)
 *     - Phase 7.4b (gexConcentration.js — percentile, expiry, call share)
 *     - Phase 7.4c (gexProfileLabel.js — structural classification)
 *
 *   Gamma source discipline:
 *     - All Layer 1 metrics: broker gamma (from Phase 7.3 snapshots)
 *     - All Layer 2 metrics: broker gamma (derived from Layer 1)
 *     - All Layer 3 metrics: broker gamma (derived from Layer 1–2)
 *     - BS model gamma is NEVER used in this module or any Phase 7.4 module
 *
 *   Data freshness:
 *     freshnesMs = Date.now() − new Date(latestSnapshot.capturedAt).getTime()
 *     Computed from capturedAt stored in the snapshot at capture time.
 *
 *   Strategy Builder interface:
 *     strategyBuilderInputs provides a flat, typed, stable interface.
 *     It is a DATA CONTRACT, not a signal generator.
 *
 * INTERPRETATION:
 *   All outputs are market-structure analytics, not trading signals.
 *   The Strategy Builder interface provides data, not decisions.
 *
 * Sign convention (inherited from Phase 7.1):
 *   Call GEX = + raw GEX    Put GEX = − raw GEX
 */

import { computeDeltaGex, computeGexMigration, computeConcentration } from "./gexHistory.js";
import {
  computeNetGexSma,
  computeDeltaGexSma,
  computeVelocity,
  computeAcceleration,
  computeDeltaGexVolatility,
} from "./gexTimeSeries.js";
import {
  computeConcentrationPercentile,
  computeGexPercentile,
  computeExpiryDecomposition,
  computeCallGexShare,
} from "./gexConcentration.js";
import { classifyGexProfile } from "./gexProfileLabel.js";

// ---- Constants ---------------------------------------------------------------

/** Freshness labels for display */
export const FRESHNESS = Object.freeze({
  FRESH: "fresh",         // < 5 min
  RECENT: "recent",       // 5–10 min
  STALE: "stale",         // 10–30 min
  OLD: "old",             // 30+ min
});

/** Strategy Builder interface version */
export const STRATEGY_BUILDER_VERSION = "strategyBuilderInputs_v1";

/** Freshness thresholds in milliseconds */
const FRESH_THRESHOLD_MS = 300_000;    // 5 min
const RECENT_THRESHOLD_MS = 600_000;   // 10 min
const STALE_THRESHOLD_MS = 1_800_000;  // 30 min

// ---- Helpers -----------------------------------------------------------------

/**
 * Get snapshots from a ring buffer or array.
 */
function toArray(source) {
  if (!source) return [];
  if (Array.isArray(source)) return [...source];
  if (typeof source.getAll === "function") return source.getAll();
  return [];
}

/**
 * Classify freshness from age in milliseconds.
 */
function classifyFreshness(ageMs) {
  if (ageMs == null || !Number.isFinite(ageMs)) return null;
  if (ageMs < FRESH_THRESHOLD_MS) return FRESHNESS.FRESH;
  if (ageMs < RECENT_THRESHOLD_MS) return FRESHNESS.RECENT;
  if (ageMs < STALE_THRESHOLD_MS) return FRESHNESS.STALE;
  return FRESHNESS.OLD;
}

// ---- Main Entry Point --------------------------------------------------------

/**
 * Compute all Phase 7.4 GEX analytics from a snapshot array or ring buffer.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {object} options
 * @param {string} options.valuationDate — ISO YYYY-MM-DD for DTE calculation
 * @param {object} [options.profileConfig] — override profile label thresholds
 * @param {number} [options.velocityWindow]
 * @param {number} [options.volatilityWindow]
 * @param {number} [options.netGexSmaWindow]
 * @param {number} [options.deltaGexSmaWindow]
 * @param {number} [options.percentileWindow] — for GEX percentile
 * @param {number} [options.concentrationPercentileWindow]
 * @returns {object} complete analytics result
 */
export function computeGexAnalytics(source, options = {}) {
  const snapshots = toArray(source);

  if (snapshots.length === 0) {
    return unavailableAnalytics("No snapshots available");
  }

  const {
    valuationDate,
    profileConfig = {},
    velocityWindow,
    volatilityWindow,
    netGexSmaWindow,
    deltaGexSmaWindow,
    percentileWindow,
    concentrationPercentileWindow,
  } = options;

  // ---- Latest snapshot (current state) ----
  const latest = snapshots[snapshots.length - 1];
  const earliest = snapshots[0];

  // ---- Methodology consistency ----
  const methodologyVersions = new Set();
  for (const s of snapshots) {
    const v = s.methodologyMetadata?.gexVersion;
    if (v) methodologyVersions.add(v);
  }
  const allSameMethodology = methodologyVersions.size <= 1;

  // ---- Data freshness ----
  const latestTs = latest.capturedAt ? new Date(latest.capturedAt).getTime() : null;
  const freshnessMs = latestTs != null && Number.isFinite(latestTs) ? Date.now() - latestTs : null;
  const freshnessLabel = classifyFreshness(freshnessMs);

  // ---- Layer 1: Raw measurements ----
  const current = {
    netGex: latest.netGex ?? null,
    callGex: latest.callGex ?? null,
    putGex: latest.putGex ?? null,
    callGexShare: _computeCallGexShare(latest),
    spot: latest.spot ?? null,
    expiry: latest.expiry ?? null,
  };

  // Decomposition (from previous snapshot if available)
  let decomposition = null;
  if (snapshots.length >= 2) {
    const prev = snapshots[snapshots.length - 2];
    decomposition = _safeDecompose(prev, latest);
  }

  // Migration
  let migration = null;
  if (snapshots.length >= 2) {
    const prev = snapshots[snapshots.length - 2];
    migration = _safeMigrate(prev, latest);
  }

  // Concentration
  const concentration = latest.strikeData?.length > 0
    ? _safeConcentration(latest.strikeData)
    : null;

  // Flip distance (from latest snapshot context — not stored in Phase 7.3 snapshots)
  const flipDistance = {
    distance: null,
    distancePct: null,
    direction: null,
  };

  // ---- Layer 2: Statistical context ----
  const timeSeries = {
    netGexSma: computeNetGexSma(snapshots, netGexSmaWindow),
    deltaGexSma: computeDeltaGexSma(snapshots, deltaGexSmaWindow),
    velocity: computeVelocity(snapshots, velocityWindow),
    acceleration: computeAcceleration(snapshots, velocityWindow),
    volatility: computeDeltaGexVolatility(snapshots, volatilityWindow),
  };

  const percentiles = {
    gexPercentile: computeGexPercentile(snapshots, percentileWindow),
    concentrationPercentile: computeConcentrationPercentile(snapshots, concentrationPercentileWindow),
  };

  const expiryDecomposition = valuationDate
    ? computeExpiryDecomposition(snapshots, valuationDate)
    : { history: [], current: null, status: "unavailable" };

  // Call GEX share history
  const callGexShareHistory = computeCallGexShare(snapshots);

  // ---- Layer 3: Structural classification ----
  const deltaGexDirection = _inferDeltaGexDirection(timeSeries.velocity);

  const profileLabel = classifyGexProfile(snapshots, profileConfig, {
    flipDistancePct: flipDistance.distancePct,
    flipDirection: flipDistance.direction,
    deltaGexDirection,
  });

  // ---- Determine overall status ----
  const statuses = [
    timeSeries.netGexSma.status,
    timeSeries.velocity.status,
    percentiles.gexPercentile.status,
    profileLabel.status,
  ];
  let status;
  if (statuses.every((s) => s === "available")) {
    status = "available";
  } else if (statuses.some((s) => s === "available" || s === "partial")) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  // ---- Strategy Builder interface ----
  const strategyBuilderInputs = {
    netGex: current.netGex,
    netGexSma: timeSeries.netGexSma.sma,
    deltaGexSma: timeSeries.deltaGexSma.sma,
    velocity: timeSeries.velocity.velocity,
    acceleration: timeSeries.acceleration.acceleration,
    volatility: timeSeries.volatility.volatility,
    gexPercentile: percentiles.gexPercentile.absolutePercentile,
    descriptiveZ: percentiles.gexPercentile.descriptiveZ,
    callGexShare: current.callGexShare,
    concentrationTop3: concentration?.top3Pct ?? null,
    profileLabels: profileLabel.labels,
    flipDistancePct: flipDistance.distancePct,
    normalizedNetGex: profileLabel.normalizedNetGex,
  };

  const strategyBuilderReady = _checkSBReady(strategyBuilderInputs, snapshots.length);

  return {
    // Metadata
    status,
    snapshotCount: snapshots.length,
    latestTimestamp: latest.capturedAt ?? null,
    earliestTimestamp: earliest?.capturedAt ?? null,
    dataFreshnessMs: freshnessMs,
    freshnessLabel,
    methodologyConsistency: {
      allSameMethodology,
      methodologyVersions: Array.from(methodologyVersions),
      versionCount: methodologyVersions.size,
    },

    // Layer 1: Raw measurements
    current,
    decomposition,
    migration,
    concentration,
    flipDistance,

    // Layer 2: Statistical context
    timeSeries,
    percentiles,
    expiryDecomposition,
    callGexShareHistory,

    // Layer 3: Structural classification
    profileLabel,

    // Strategy Builder interface
    strategyBuilderVersion: STRATEGY_BUILDER_VERSION,
    strategyBuilderReady,
    strategyBuilderInputs,
  };
}

// ---- Internal helpers --------------------------------------------------------

function _computeCallGexShare(snapshot) {
  const callGex = snapshot.callGex;
  const putGex = snapshot.putGex;
  if (callGex != null && putGex != null && Number.isFinite(callGex) && Number.isFinite(putGex)) {
    const totalAbs = Math.abs(callGex) + Math.abs(putGex);
    if (totalAbs > 0) return (Math.abs(callGex) / totalAbs) * 100;
  }
  return null;
}

function _safeDecompose(a, b) {
  try {
    return computeDeltaGex(a, b);
  } catch {
    return { total: null, deltaTimeMs: null, spotChange: null, status: "unavailable" };
  }
}

function _safeMigrate(a, b) {
  try {
    return computeGexMigration(a, b);
  } catch {
    return { centroidA: null, centroidB: null, migration: null, direction: "unavailable", status: "unavailable" };
  }
}

function _safeConcentration(strikeData) {
  try {
    return computeConcentration(strikeData);
  } catch {
    return null;
  }
}

function _inferDeltaGexDirection(velocityResult) {
  if (!velocityResult || velocityResult.velocity == null) return null;
  const v = velocityResult.velocity;
  if (v > 0) return "increasing";
  if (v < 0) return "decreasing";
  return "stable";
}

function _checkSBReady(inputs, snapshotCount) {
  // SB is ready when we have a minimum set of data
  return snapshotCount >= 3 && inputs.netGex != null;
}

function unavailableAnalytics(reason) {
  return {
    status: "unavailable",
    reason,
    snapshotCount: 0,
    latestTimestamp: null,
    earliestTimestamp: null,
    dataFreshnessMs: null,
    freshnessLabel: null,
    methodologyConsistency: { allSameMethodology: true, methodologyVersions: [], versionCount: 0 },
    current: { netGex: null, callGex: null, putGex: null, callGexShare: null, spot: null, expiry: null },
    decomposition: null,
    migration: null,
    concentration: null,
    flipDistance: { distance: null, distancePct: null, direction: null },
    timeSeries: {
      netGexSma: { sma: null, history: [], windowSize: 0, availablePoints: 0, status: "unavailable" },
      deltaGexSma: { sma: null, history: [], windowSize: 0, availablePoints: 0, status: "unavailable" },
      velocity: { velocity: null, history: [], status: "unavailable" },
      acceleration: { acceleration: null, history: [], status: "unavailable" },
      volatility: { volatility: null, history: [], windowSize: 0, availablePoints: 0, status: "unavailable" },
    },
    percentiles: {
      gexPercentile: { absolutePercentile: null, descriptiveZ: null, availablePoints: 0, status: "unavailable" },
      concentrationPercentile: { top3Percentile: null, top5Percentile: null, availablePoints: 0, status: "unavailable" },
    },
    expiryDecomposition: { history: [], current: null, status: "unavailable" },
    callGexShareHistory: { current: null, history: [], status: "unavailable" },
    profileLabel: { labels: ["UNAVAILABLE"], confidence: "experimental", status: "unavailable" },
    strategyBuilderVersion: STRATEGY_BUILDER_VERSION,
    strategyBuilderReady: false,
    strategyBuilderInputs: {
      netGex: null, netGexSma: null, deltaGexSma: null, velocity: null,
      acceleration: null, volatility: null, gexPercentile: null, descriptiveZ: null,
      callGexShare: null, concentrationTop3: null, profileLabels: ["UNAVAILABLE"],
      flipDistancePct: null, normalizedNetGex: null,
    },
  };
}
