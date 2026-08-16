// Generic statistics domain (Phase 4.2) — pure, strategy-agnostic measurements.
//
// This module contains NO options logic and NO trading interpretation. It
// computes descriptive statistics over plain number arrays:
//
//   rollingMean / rollingMedian / rollingStdDev / rollingMin / rollingMax
//   zScore / percentileRank / anomalyMeasurement
//
// Conventions (documented, deterministic, never fabricated):
//   - Invalid entries (null, undefined, NaN, ±Infinity) are ignored safely.
//   - Empty history → null everywhere (never 0, never a fake percentile).
//   - Insufficient history → null where a result would be statistically
//     fragile: rollingStdDev and zScore need ≥ 2 observations; zScore and
//     percentileRank need ≥ MIN_STAT_SAMPLE (5) by default.
//   - Constant (all-equal) history → zScore is null (division by zero σ is
//     meaningless); percentileRank returns the exact mean-rank value (50 for
//     a value equal to the constant), never an invented number.
//   - anomalyMeasurement.magnitude is a 0–100 "statistical unusualness" score
//     derived deterministically from |z| (|z| = 3 maps to 100, linear below).
//     It is NOT a probability, NOT bullish/bearish, NOT a buy/sell signal.
//
// Everything here is independent of options, expiries and strikes so future
// phases (scanner, backtesting, alerts) can reuse it unchanged.

export const MIN_STAT_SAMPLE = 5; // minimum sample for z-score / percentileRank
export const MIN_STDDEV_SAMPLE = 2; // minimum sample for rollingStdDev / zScore maths
export const MAX_ANOMALY_Z = 3; // |z| at which anomaly magnitude saturates at 100

// ---- Safe number handling ---------------------------------------------------

// Finite number or null. 0 is a VALID value (never conflated with missing).
export function cleanNumber(v) {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// Keep only finite entries (null / NaN / ±Infinity dropped).
export function cleanNumbers(values) {
  if (!Array.isArray(values)) return [];
  return values.map(cleanNumber).filter((v) => v !== null);
}

// ---- Rolling statistics ------------------------------------------------------

// Arithmetic mean of the valid entries. null when nothing valid is present.
export function rollingMean(values) {
  const clean = cleanNumbers(values);
  if (clean.length === 0) return null;
  return clean.reduce((a, b) => a + b, 0) / clean.length;
}

// Median of the valid entries (standard midpoint rule for even counts).
export function rollingMedian(values) {
  const clean = cleanNumbers(values).slice().sort((a, b) => a - b);
  if (clean.length === 0) return null;
  const mid = Math.floor(clean.length / 2);
  if (clean.length % 2 === 1) return clean[mid];
  return (clean[mid - 1] + clean[mid]) / 2;
}

// Population standard deviation of the valid entries. null when fewer than
// MIN_STDDEV_SAMPLE observations exist (a 1-point sample has no spread).
export function rollingStdDev(values) {
  const clean = cleanNumbers(values);
  if (clean.length < MIN_STDDEV_SAMPLE) return null;
  const mean = clean.reduce((a, b) => a + b, 0) / clean.length;
  const variance = clean.reduce((a, b) => a + (b - mean) ** 2, 0) / clean.length;
  return Math.sqrt(variance);
}

// Minimum of the valid entries.
export function rollingMin(values) {
  const clean = cleanNumbers(values);
  return clean.length ? Math.min(...clean) : null;
}

// Maximum of the valid entries.
export function rollingMax(values) {
  const clean = cleanNumbers(values);
  return clean.length ? Math.max(...clean) : null;
}

// ---- Z-score / percentile ----------------------------------------------------

// (value − mean) / σ over the valid history. null when the value is invalid,
// the history has fewer than minSample valid entries, or the history is
// constant (σ = 0 — a z-score would be undefined / meaningless).
export function zScore(value, history, { minSample = MIN_STAT_SAMPLE } = {}) {
  const v = cleanNumber(value);
  if (v === null) return null;
  const clean = cleanNumbers(history);
  if (clean.length < Math.max(minSample, MIN_STDDEV_SAMPLE)) return null;
  const mean = clean.reduce((a, b) => a + b, 0) / clean.length;
  const variance = clean.reduce((a, b) => a + (b - mean) ** 2, 0) / clean.length;
  const std = Math.sqrt(variance);
  if (!(std > 0)) return null; // constant history → null (documented safe result)
  return (v - mean) / std;
}

// Mean-rank percentile of `value` within the valid history (0..100).
//
// percentileRank = (count strictly below + 0.5 × count equal) / n × 100
//
// Exact and deterministic: a value at the minimum → 0, at the maximum →
// (n − 0.5)/n × 100, equal to an all-equal constant history → 50. null when
// the value is invalid or the history has fewer than minSample valid entries
// (never a fabricated 0% / 100% from a tiny sample).
export function percentileRank(value, history, { minSample = MIN_STAT_SAMPLE } = {}) {
  const v = cleanNumber(value);
  if (v === null) return null;
  const clean = cleanNumbers(history);
  if (clean.length < minSample) return null;
  let below = 0;
  let equal = 0;
  clean.forEach((x) => {
    if (x < v) below += 1;
    else if (x === v) equal += 1;
  });
  return ((below + 0.5 * equal) / clean.length) * 100;
}

// ---- Generic anomaly measurement ---------------------------------------------

// Neutral anomaly measurement:
//   {
//     value,            // the current value being measured
//     baseline,         // rolling mean of the supplied history
//     zScore,           // |z| relative to the history (null when unavailable)
//     percentileRank,   // mean-rank percentile 0..100 (null when unavailable)
//     magnitude,        // 0–100 statistical unusualness (null when unavailable)
//     status,           // "available" | "partial" | "unavailable"
//     availableCount,   // valid observations in the history
//     expectedCount,    // total entries supplied
//   }
//
// magnitude = min(100, |z| / MAX_ANOMALY_Z × 100) — deterministic, documented,
// saturating. It measures STATISTICAL UNUSUALNESS only. 82 does NOT mean
// "bullish" or "buy"; it means "this value is unusual relative to the
// baseline". Strength and confidence are strictly separate (see
// strengthAndConfidence in marketAnalytics.js): magnitude is neither a
// probability of a price move nor a probability of profit.
export function anomalyMeasurement(value, history, { minSample = MIN_STAT_SAMPLE } = {}) {
  const v = cleanNumber(value);
  const clean = cleanNumbers(history);
  const expectedCount = Array.isArray(history) ? history.length : 0;
  const availableCount = clean.length;

  const z = zScore(v, history, { minSample });
  const pct = percentileRank(v, history, { minSample });

  let magnitude = null;
  let status = "unavailable";
  if (z !== null) {
    magnitude = Math.min(100, (Math.abs(z) / MAX_ANOMALY_Z) * 100);
    status = "available";
  } else if (availableCount > 0) {
    status = "partial"; // some history, but not enough for a reliable z-score
  }

  return {
    value: v,
    baseline: rollingMean(clean),
    zScore: z,
    percentileRank: pct,
    magnitude,
    status,
    availableCount,
    expectedCount,
  };
}
