/**
 * GEX Phase 7.4b — Concentration, Percentile, Expiry Decomposition
 *
 * Provides:
 *   1. Concentration history — time-series of top-N strike |GEX| share
 *   2. Concentration percentile — where current concentration ranks in history
 *   3. GEX percentile — where current |Net GEX| ranks in history
 *   4. Descriptive z-score — how unusual current |Net GEX| is (NOT significant)
 *   5. Expiry decomposition — NEAR/MID/FAR bucket breakdown
 *   6. Call GEX Share — call fraction of total absolute GEX
 *
 * MATHEMATICAL CONTRACT:
 *
 *   All metrics consume broker-gamma-derived values from Phase 7.3 snapshots.
 *   BS model gamma is NOT used in this module.
 *
 *   Concentration(topN) = Σ |netGex(K)|_topN / Σ |netGex(K)|_all × 100
 *
 *   GEX percentile = percentileRank(|netGex_current|, [|netGex_{t-w}|, ..., |netGex_current|])
 *   descriptiveZ   = (|netGex_current| − mean) / stddev   [NOT statistically significant]
 *
 *   callGexShare = callGex / (callGex + |putGex|) × 100
 *
 *   DTE(expiryDate, referenceDate) = timeToExpiry(referenceDate, expiryDate)
 *   Bucket: NEAR = 0 < DTE ≤ 7, MID = 7 < DTE ≤ 30, FAR = DTE > 30
 *
 * IMPORTANT: descriptiveZ at ±2 or ±3 does NOT mean statistical significance.
 * These are descriptive labels only. Empirical validation is required before
 * these z-scores can inform any trading decision (deferred to Phase 7.7).
 *
 * INTERPRETATION:
 *   These are DESCRIPTIVE STATISTICS of GEX structure and history.
 *   They do NOT predict market direction.
 *
 * Sign convention (inherited from Phase 7.1):
 *   Call GEX = + raw GEX    Put GEX = − raw GEX
 */

import { percentileRank, zScore, cleanNumbers } from "./statistics.js";
import { computeConcentration } from "./gexHistory.js";
import { timeToExpiry } from "./pricing.js";

// ---- Constants ---------------------------------------------------------------

/** Minimum observations for percentile / z-score (from statistics.js) */
export const MIN_STAT_SAMPLE = 5;

/** Expiry bucket boundaries (DTE in calendar days, inclusive at lower bound) */
export const DTE_NEAR_MAX = 7;
export const DTE_MID_MAX = 30;

/** Bucket labels */
export const BUCKET_NEAR = "NEAR";
export const BUCKET_MID = "MID";
export const BUCKET_FAR = "FAR";

// ---- Snapshot helpers --------------------------------------------------------

/**
 * Extract netGEX absolute value from a snapshot.
 * @param {object} snapshot
 * @returns {number|null}
 */
function absNetGexOf(snapshot) {
  if (!snapshot) return null;
  const v = snapshot.netGex;
  return v != null && Number.isFinite(v) ? Math.abs(v) : null;
}

/**
 * Get snapshots from a ring buffer or array.
 * @param {GexRingBuffer|Array} source
 * @returns {Array}
 */
function toArray(source) {
  if (!source) return [];
  if (Array.isArray(source)) return [...source];
  if (typeof source.getAll === "function") return source.getAll();
  return [];
}

// ---- DTE Calculation ---------------------------------------------------------

/**
 * Compute days-to-expiry for an expiry date.
 *
 * Uses timeToExpiry() from pricing.js which returns fractional years.
 * Converts to calendar days for bucket classification.
 *
 * @param {string} expiryDate — ISO YYYY-MM-DD
 * @param {string} referenceDate — ISO YYYY-MM-DD (valuation date)
 * @returns {number|null} DTE in calendar days, or null if unresolvable
 */
export function computeDte(expiryDate, referenceDate) {
  if (!expiryDate || !referenceDate) return null;
  const tYears = timeToExpiry(referenceDate, expiryDate);
  if (tYears == null || !Number.isFinite(tYears) || tYears < 0) return null;
  return tYears * 365;
}

/**
 * Classify a DTE value into an expiry bucket.
 * @param {number} dteDays — DTE in calendar days
 * @returns {string} BUCKET_NEAR, BUCKET_MID, or BUCKET_FAR
 */
export function classifyDteBucket(dteDays) {
  if (dteDays <= DTE_NEAR_MAX) return BUCKET_NEAR;
  if (dteDays <= DTE_MID_MAX) return BUCKET_MID;
  return BUCKET_FAR;
}

// ---- Concentration History ---------------------------------------------------

/**
 * Compute time-series of top-N strike concentration from snapshots.
 *
 * Formula: Concentration(topN) = Σ |netGex(K)|_topN / Σ |netGex(K)|_all × 100
 *
 * Uses computeConcentration() from Phase 7.3 at each snapshot point.
 * Gamma source: broker (concentration operates on broker-gamma-derived netGex).
 *
 * @param {GexRingBuffer|Array} source — snapshots
 * @returns {{ history: Array, currentTop3Pct: number|null, status: string }}
 */
export function computeConcentrationHistory(source) {
  const snapshots = toArray(source);
  if (snapshots.length === 0) {
    return { history: [], currentTop3Pct: null, status: "unavailable" };
  }

  const history = [];
  for (const s of snapshots) {
    const conc = computeConcentration(s.strikeData || []);
    history.push({
      timestamp: s.capturedAt ?? null,
      top3Pct: conc.top3Pct,
      top5Pct: conc.top5Pct,
      top10Pct: conc.top10Pct,
      totalAbsoluteGex: conc.totalAbsoluteGex,
      strikeCount: conc.strikeCount,
    });
  }

  const last = history[history.length - 1];
  const hasData = last && last.top3Pct != null;

  return {
    history,
    currentTop3Pct: last?.top3Pct ?? null,
    status: hasData ? "available" : "unavailable",
  };
}

// ---- Concentration Percentile ------------------------------------------------

/**
 * Compute where the current top-3 concentration ranks within recent history.
 *
 * Uses percentileRank() from statistics.js on the top3Pct time-series.
 * Formula: percentileRank(top3Pct_current, [top3Pct_{t-window}, ..., top3Pct_current])
 *
 * @param {GexRingBuffer|Array} source — snapshots
 * @param {number} [window=10] — number of historical observations for context
 * @returns {{ top3Percentile: number|null, top5Percentile: number|null, availablePoints: number, status: string }}
 */
export function computeConcentrationPercentile(source, window = 10) {
  const snapshots = toArray(source);
  if (snapshots.length === 0) {
    return { top3Percentile: null, top5Percentile: null, availablePoints: 0, status: "unavailable" };
  }

  const concResult = computeConcentrationHistory(snapshots);
  const top3Values = concResult.history.map((h) => h.top3Pct);
  const top5Values = concResult.history.map((h) => h.top5Pct);

  const recentTop3 = top3Values.slice(-window);
  const recentTop5 = top5Values.slice(-window);

  const currentTop3 = recentTop3[recentTop3.length - 1];
  const currentTop5 = recentTop5[recentTop5.length - 1];

  const top3Pct = percentileRank(currentTop3, recentTop3);
  const top5Pct = percentileRank(currentTop5, recentTop5);

  const cleanTop3 = cleanNumbers(recentTop3);

  let status;
  if (cleanTop3.length >= MIN_STAT_SAMPLE) {
    status = "available";
  } else if (cleanTop3.length > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    top3Percentile: top3Pct,
    top5Percentile: top5Pct,
    availablePoints: cleanTop3.length,
    status,
  };
}

// ---- GEX Percentile ----------------------------------------------------------

/**
 * Compute where the current absolute Net GEX ranks within recent history.
 *
 * Formula: percentileRank(|netGex_current|, [|netGex_{t-window}|, ..., |netGex_current|])
 *
 * Also computes descriptive z-score (NOT statistically significant).
 *
 * HISTORICAL COMPARABILITY RULE:
 *   Percentile is computed over raw absolute NetGEX values.
 *   No normalization for spot level is applied.
 *   Values are comparable only within sessions where spot stays in a similar range.
 *
 * @param {GexRingBuffer|Array} source — snapshots
 * @param {number} [window=10] — number of historical observations for context
 * @returns {{ absolutePercentile: number|null, descriptiveZ: number|null, availablePoints: number, status: string }}
 */
export function computeGexPercentile(source, window = 10) {
  const snapshots = toArray(source);
  if (snapshots.length === 0) {
    return { absolutePercentile: null, descriptiveZ: null, availablePoints: 0, status: "unavailable" };
  }

  const values = snapshots.map(absNetGexOf);
  const recentValues = values.slice(-window);
  const currentValue = recentValues[recentValues.length - 1];

  const absPct = percentileRank(currentValue, recentValues);
  const dZ = zScore(currentValue, recentValues);

  const clean = cleanNumbers(recentValues);

  let status;
  if (clean.length >= MIN_STAT_SAMPLE) {
    status = "available";
  } else if (clean.length > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    absolutePercentile: absPct,
    descriptiveZ: dZ,
    availablePoints: clean.length,
    status,
  };
}

// ---- Expiry Decomposition ----------------------------------------------------

/**
 * Break down aggregate GEX into NEAR/MID/FAR expiry buckets.
 *
 * DTE calculated via timeToExpiry() from pricing.js.
 * Buckets: NEAR (0 < DTE ≤ 7), MID (7 < DTE ≤ 30), FAR (DTE > 30).
 *
 * Gamma source: broker (netGex from Phase 7.1 byExpiry).
 *
 * @param {GexRingBuffer|Array} source — snapshots
 * @param {string} valuationDate — ISO YYYY-MM-DD for DTE calculation
 * @returns {{ history: Array, current: object, status: string }}
 */
export function computeExpiryDecomposition(source, valuationDate) {
  const snapshots = toArray(source);
  if (snapshots.length === 0 || !valuationDate) {
    return { history: [], current: null, status: "unavailable" };
  }

  const history = [];
  let anyData = false;

  for (const s of snapshots) {
    const expiryData = s.expiryData || [];
    const buckets = { [BUCKET_NEAR]: [], [BUCKET_MID]: [], [BUCKET_FAR]: [] };

    for (const e of expiryData) {
      const expiryDate = e.expiry;
      if (!expiryDate) continue;
      const dte = computeDte(expiryDate, valuationDate);
      if (dte == null) continue;
      const bucket = classifyDteBucket(dte);
      buckets[bucket].push(e);
    }

    const summarize = (entries) => {
      if (entries.length === 0) return { netGex: null, expiryCount: 0, totalDte: 0 };
      let netGex = 0;
      let hasAny = false;
      let totalDte = 0;
      for (const e of entries) {
        if (e.netGex != null && Number.isFinite(e.netGex)) {
          netGex += e.netGex;
          hasAny = true;
        }
        const dte = computeDte(e.expiry, valuationDate);
        if (dte != null) totalDte += dte;
      }
      return { netGex: hasAny ? netGex : null, expiryCount: entries.length, totalDte };
    };

    const near = summarize(buckets[BUCKET_NEAR]);
    const mid = summarize(buckets[BUCKET_MID]);
    const far = summarize(buckets[BUCKET_FAR]);

    // Call GEX share from snapshot totals
    const callGex = s.callGex;
    const putGex = s.putGex;
    let callGexShare = null;
    if (callGex != null && putGex != null && Number.isFinite(callGex) && Number.isFinite(putGex)) {
      const totalAbs = Math.abs(callGex) + Math.abs(putGex);
      if (totalAbs > 0) {
        callGexShare = (Math.abs(callGex) / totalAbs) * 100;
      }
    }

    const total = near.netGex != null || mid.netGex != null || far.netGex != null
      ? (near.netGex ?? 0) + (mid.netGex ?? 0) + (far.netGex ?? 0)
      : null;

    anyData = true;
    history.push({
      timestamp: s.capturedAt ?? null,
      spot: s.spot ?? null,
      near,
      mid,
      far,
      total,
      callGexShare,
    });
  }

  const current = history.length > 0 ? history[history.length - 1] : null;

  return {
    history,
    current,
    status: anyData ? "available" : "unavailable",
  };
}

// ---- Call GEX Share ----------------------------------------------------------

/**
 * Compute call GEX as a fraction of total absolute GEX over time.
 *
 * Formula: callGexShare = |callGex| / (|callGex| + |putGex|) × 100
 *
 * Gamma source: broker.
 *
 * @param {GexRingBuffer|Array} source — snapshots
 * @returns {{ current: number|null, history: Array, status: string }}
 */
export function computeCallGexShare(source) {
  const snapshots = toArray(source);
  if (snapshots.length === 0) {
    return { current: null, history: [], status: "unavailable" };
  }

  const history = [];
  let anyValid = false;

  for (const s of snapshots) {
    const callGex = s.callGex;
    const putGex = s.putGex;
    let share = null;

    if (callGex != null && putGex != null && Number.isFinite(callGex) && Number.isFinite(putGex)) {
      const totalAbs = Math.abs(callGex) + Math.abs(putGex);
      if (totalAbs > 0) {
        share = (Math.abs(callGex) / totalAbs) * 100;
        anyValid = true;
      }
    }

    history.push({
      timestamp: s.capturedAt ?? null,
      value: share,
    });
  }

  const last = history[history.length - 1];

  return {
    current: last?.value ?? null,
    history,
    status: anyValid ? "available" : "unavailable",
  };
}
