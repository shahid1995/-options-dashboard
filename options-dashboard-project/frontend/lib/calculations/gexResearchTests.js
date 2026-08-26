/**
 * GEX Phase 7.7 — Statistical Research Engine
 *
 * Quintile analysis, effect sizes, block bootstrap, regression,
 * interaction analysis, regime analysis, baseline comparison.
 *
 * All methods are descriptive/statistical — no predictive claims.
 */

import { HORIZONS } from "./gexResearchData.js";

// ---- Constants -----------------------------------------------------------

export const MIN_OBSERVATIONS = 200;
export const MIN_QUINTILE_SIZE = 30;
export const BOOTSTRAP_REPLICATES = 2000;
export const DEFAULT_BLOCK_SIZE = 2;
export const CONFIDENCE_LEVEL = 0.95;

// ---- Feature extraction --------------------------------------------------

/** All GEX feature names that can be tested */
export const GEX_FEATURES = [
  "netGex",
  "normalizedNetGex",
  "deltaGex",
  "velocity",
  "acceleration",
  "volatility",
  "concentrationTop3",
  "gexPercentile",
  "descriptiveZ",
  "callGexShare",
  "gammaFlipDistancePct",
  "callWallDistancePct",
  "putWallDistancePct",
  "dte",
];

/** Baseline price features for incremental information tests */
export const BASELINE_FEATURES = [
  "previousReturn",
  "realizedVolatility",
  "intradayRange",
  "momentum",
  "distFromHigh",
  "distFromLow",
];

// ---- Quintile analysis ---------------------------------------------------

/**
 * Rank observations by a feature and partition into quintiles.
 *
 * @param {Array} observations — research observations
 * @param {string} featureName — feature to rank by
 * @param {string} outcomeKey — e.g. "forward.candles10.return"
 * @returns {object|null} quintile results or null if insufficient data
 */
export function quintileAnalysis(observations, featureName, outcomeKey) {
  // Extract valid (feature, outcome) pairs
  const pairs = [];
  for (const obs of observations) {
    const feature = _getNestedValue(obs, featureName);
    const outcome = _getNestedValue(obs, outcomeKey);
    if (Number.isFinite(feature) && Number.isFinite(outcome)) {
      pairs.push({ feature, outcome });
    }
  }

  if (pairs.length < MIN_OBSERVATIONS) {
    return { status: "INSUFFICIENT_DATA", sampleCount: pairs.length };
  }

  // Sort by feature ascending
  pairs.sort((a, b) => a.feature - b.feature);

  // Partition into 5 quintiles
  const quintileSize = Math.floor(pairs.length / 5);
  const quintiles = [];
  for (let q = 0; q < 5; q++) {
    const start = q * quintileSize;
    const end = q === 4 ? pairs.length : start + quintileSize;
    const slice = pairs.slice(start, end);
    quintiles.push({
      quintile: q + 1,
      count: slice.length,
      outcomes: slice.map(p => p.outcome),
    });
  }

  // Compute statistics per quintile
  const quintileStats = quintiles.map(q => ({
    quintile: q.quintile,
    count: q.count,
    mean: _mean(q.outcomes),
    median: _median(q.outcomes),
    std: _stddev(q.outcomes),
    hitRate: _hitRate(q.outcomes),
  }));

  // Baseline (all observations)
  const allOutcomes = pairs.map(p => p.outcome);
  const baseline = {
    count: allOutcomes.length,
    mean: _mean(allOutcomes),
    median: _median(allOutcomes),
    std: _stddev(allOutcomes),
    hitRate: _hitRate(allOutcomes),
  };

  // Effect size: Cohen's d between Q5 and Q1
  const q1Outcomes = quintiles[0].outcomes;
  const q5Outcomes = quintiles[4].outcomes;
  const effectSize = _cohensD(q1Outcomes, q5Outcomes);

  // Lift: how much Q5 mean differs from baseline
  const lift = baseline.mean !== 0
    ? (quintileStats[4].mean - baseline.mean) / Math.abs(baseline.mean)
    : null;

  return {
    status: pairs.length >= MIN_OBSERVATIONS ? "COMPUTED" : "INSUFFICIENT_DATA",
    feature: featureName,
    outcome: outcomeKey,
    sampleCount: pairs.length,
    quintiles: quintileStats,
    baseline,
    effectSize,
    lift,
    q5MinusQ1: quintileStats[4].mean - quintileStats[0].mean,
  };
}

// ---- Effect sizes --------------------------------------------------------

/**
 * Cohen's d between two independent samples.
 * Positive d means group2 mean > group1 mean.
 */
export function cohensD(group1, group2) {
  return _cohensD(group1, group2);
}

// ---- Block bootstrap confidence intervals ---------------------------------

/**
 * Block bootstrap confidence interval for the mean.
 *
 * Preserves serial dependence by resampling contiguous blocks.
 *
 * @param {Array} values — time-ordered values (may contain nulls)
 * @param {object} options
 * @param {number} options.blockSize — block size (default: 2)
 * @param {number} options.replicates — number of bootstrap samples
 * @param {number} options.confidenceLevel — e.g. 0.95
 * @returns {object} { mean, ciLower, ciUpper, se }
 */
export function blockBootstrapMean(values, options = {}) {
  const {
    blockSize = DEFAULT_BLOCK_SIZE,
    replicates = BOOTSTRAP_REPLICATES,
    confidenceLevel = CONFIDENCE_LEVEL,
  } = options;

  const clean = values.filter(v => Number.isFinite(v));
  if (clean.length < blockSize * 2) {
    return { mean: _mean(clean), ciLower: null, ciUpper: null, se: null };
  }

  const n = clean.length;
  const blockCount = Math.ceil(n / blockSize);

  // Generate bootstrap means
  const bootMeans = [];
  for (let r = 0; r < replicates; r++) {
    const sample = [];
    for (let b = 0; b < blockCount; b++) {
      const startIdx = Math.floor(Math.random() * (n - blockSize + 1));
      for (let i = 0; i < blockSize; i++) {
        sample.push(clean[startIdx + i]);
      }
    }
    bootMeans.push(_mean(sample.slice(0, n)));
  }

  bootMeans.sort((a, b) => a - b);

  const alpha = (1 - confidenceLevel) / 2;
  const loIdx = Math.floor(alpha * replicates);
  const hiIdx = Math.floor((1 - alpha) * replicates) - 1;

  const mean = _mean(clean);
  const se = _stddev(bootMeans);

  return {
    mean,
    ciLower: bootMeans[loIdx],
    ciUpper: bootMeans[hiIdx],
    se,
  };
}

// ---- Multiple testing correction ------------------------------------------

/**
 * Holm-Bonferroni correction for family of p-values.
 * Returns adjusted p-values (always >= raw p-values).
 *
 * @param {Array} pValues — raw p-values
 * @returns {Array} adjusted p-values in same order
 */
export function holmBonferroni(pValues) {
  const indexed = pValues
    .map((p, i) => ({ p, i }))
    .filter(x => Number.isFinite(x.p))
    .sort((a, b) => a.p - b.p);

  const m = indexed.length;
  const adjusted = new Array(pValues.length).fill(null);

  let runningMax = 0;
  for (let rank = 0; rank < m; rank++) {
    const { p, i } = indexed[rank];
    const adjustedP = Math.min(1, p * (m - rank));
    runningMax = Math.max(runningMax, adjustedP);
    adjusted[i] = runningMax;
  }

  return adjusted;
}

/**
 * Benjamini-Hochberg FDR correction.
 * Less conservative than Holm-Bonferroni.
 */
export function benjaminiHochberg(pValues) {
  const indexed = pValues
    .map((p, i) => ({ p, i }))
    .filter(x => Number.isFinite(x.p))
    .sort((a, b) => a.p - b.p);

  const m = indexed.length;
  const adjusted = new Array(pValues.length).fill(null);

  let runningMin = 1;
  for (let rank = m - 1; rank >= 0; rank--) {
    const { p, i } = indexed[rank];
    const adjustedP = Math.min(1, p * m / (rank + 1));
    runningMin = Math.min(runningMin, adjustedP);
    adjusted[i] = runningMin;
  }

  return adjusted;
}

// ---- Interaction analysis ------------------------------------------------

/**
 * Two-way analysis: test whether the effect of feature A on outcomes
 * depends on the level of feature B.
 *
 * @param {Array} observations
 * @param {string} featureA
 * @param {string} featureB
 * @param {string} outcomeKey
 * @returns {object} interaction result
 */
export function interactionAnalysis(observations, featureA, featureB, outcomeKey) {
  // Build valid pairs
  const pairs = [];
  for (const obs of observations) {
    const a = _getNestedValue(obs, featureA);
    const b = _getNestedValue(obs, featureB);
    const y = _getNestedValue(obs, outcomeKey);
    if (Number.isFinite(a) && Number.isFinite(b) && Number.isFinite(y)) {
      pairs.push({ a, b, y });
    }
  }

  if (pairs.length < 50) {
    return { status: "INSUFFICIENT_DATA", sampleCount: pairs.length };
  }

  // Tercile boundaries
  const sortA = pairs.map(p => p.a).sort((a, b) => a - b);
  const sortB = pairs.map(p => p.b).sort((a, b) => a - b);
  const t1A = sortA[Math.floor(sortA.length / 3)];
  const t2A = sortA[Math.floor(2 * sortA.length / 3)];
  const t1B = sortB[Math.floor(sortB.length / 3)];
  const t2B = sortB[Math.floor(2 * sortB.length / 3)];

  // Classify each pair
  const cells = {};
  for (const p of pairs) {
    const cellA = p.a <= t1A ? "L" : p.a >= t2A ? "H" : "M";
    const cellB = p.b <= t1B ? "L" : p.b >= t2B ? "H" : "M";
    const key = `${cellA}_${cellB}`;
    if (!cells[key]) cells[key] = [];
    cells[key].push(p.y);
  }

  // Compute cell means
  const cellMeans = {};
  for (const [key, values] of Object.entries(cells)) {
    cellMeans[key] = {
      count: values.length,
      mean: _mean(values),
    };
  }

  // Interaction effect: is the A-effect different across B levels?
  const aEffectAtLowB = (cellMeans["M_L"]?.mean ?? 0) - (cellMeans["L_L"]?.mean ?? 0);
  const aEffectAtHighB = (cellMeans["M_H"]?.mean ?? 0) - (cellMeans["L_H"]?.mean ?? 0);
  const interactionMagnitude = Math.abs(aEffectAtHighB - aEffectAtLowB);

  return {
    status: "COMPUTED",
    featureA,
    featureB,
    outcome: outcomeKey,
    sampleCount: pairs.length,
    cellMeans,
    aEffectAtLowB,
    aEffectAtHighB,
    interactionMagnitude,
    terciles: { t1A, t2A, t1B, t2B },
  };
}

// ---- Regime analysis -----------------------------------------------------

/**
 * Classify observations into regimes and compute forward outcomes per regime.
 *
 * @param {Array} observations
 * @param {string} regimeFeature — feature to classify by
 * @param {string} outcomeKey
 * @param {object} options
 * @param {number} options.highThreshold — percentile for "high" (default: 80)
 * @param {number} options.lowThreshold — percentile for "low" (default: 20)
 * @returns {object} regime analysis results
 */
export function regimeAnalysis(observations, regimeFeature, outcomeKey, options = {}) {
  const { highThreshold = 80, lowThreshold = 20 } = options;

  // Extract valid pairs
  const pairs = [];
  for (const obs of observations) {
    const feature = _getNestedValue(obs, regimeFeature);
    const outcome = _getNestedValue(obs, outcomeKey);
    if (Number.isFinite(feature) && Number.isFinite(outcome)) {
      pairs.push({ feature, outcome });
    }
  }

  if (pairs.length < MIN_OBSERVATIONS) {
    return { status: "INSUFFICIENT_DATA", sampleCount: pairs.length };
  }

  // Compute percentile thresholds from the data
  const sortedFeatures = pairs.map(p => p.feature).sort((a, b) => a - b);
  const lowVal = _percentile(sortedFeatures, lowThreshold);
  const highVal = _percentile(sortedFeatures, highThreshold);

  // Classify into regimes
  const regimes = { low: [], neutral: [], high: [] };
  for (const p of pairs) {
    if (p.feature <= lowVal) regimes.low.push(p.outcome);
    else if (p.feature >= highVal) regimes.high.push(p.outcome);
    else regimes.neutral.push(p.outcome);
  }

  return {
    status: "COMPUTED",
    feature: regimeFeature,
    outcome: outcomeKey,
    sampleCount: pairs.length,
    thresholds: { low: lowVal, high: highVal },
    regimes: {
      low: { count: regimes.low.length, mean: _mean(regimes.low), median: _median(regimes.low) },
      neutral: { count: regimes.neutral.length, mean: _mean(regimes.neutral), median: _median(regimes.neutral) },
      high: { count: regimes.high.length, mean: _mean(regimes.high), median: _median(regimes.high) },
    },
  };
}

// ---- Baseline comparison -------------------------------------------------

/**
 * Test whether GEX features add incremental information beyond price baselines.
 *
 * @param {Array} observations — must have baseline features pre-computed
 * @param {string} gexFeature — GEX feature to test
 * @param {string} outcomeKey
 * @returns {object} incremental information test result
 */
export function baselineComparison(observations, gexFeature, outcomeKey) {
  // Collect (baseline_vector, gex_value, outcome) triples
  const triples = [];
  for (const obs of observations) {
    const gexVal = _getNestedValue(obs, gexFeature);
    const outcome = _getNestedValue(obs, outcomeKey);
    if (!Number.isFinite(gexVal) || !Number.isFinite(outcome)) continue;

    // Build baseline vector from available price features
    const baseline = [];
    for (const bf of BASELINE_FEATURES) {
      const v = obs[bf];
      baseline.push(Number.isFinite(v) ? v : 0);
    }
    triples.push({ baseline, gex: gexVal, outcome });
  }

  if (triples.length < MIN_OBSERVATIONS) {
    return { status: "INSUFFICIENT_DATA", sampleCount: triples.length };
  }

  // Simple R² comparison (descriptive, not rigorous OLS)
  const baselineR2 = _simpleR2(triples.map(t => t.baseline), triples.map(t => t.outcome));
  const combinedFeatures = triples.map(t => [...t.baseline, t.gex]);
  const combinedR2 = _simpleR2(combinedFeatures, triples.map(t => t.outcome));

  const incrementalR2 = combinedR2 - baselineR2;

  return {
    status: "COMPUTED",
    gexFeature,
    outcome: outcomeKey,
    sampleCount: triples.length,
    baselineR2,
    combinedR2,
    incrementalR2,
    gexAddsInformation: incrementalR2 > 0.001, // >0.1% R² improvement
  };
}

// ---- Internal helpers ----------------------------------------------------

function _getNestedValue(obj, path) {
  if (!obj || !path) return undefined;
  const parts = path.split(".");
  let current = obj;
  for (const part of parts) {
    if (current == null) return undefined;
    current = current[part];
  }
  return current;
}

function _mean(values) {
  const clean = values.filter(v => Number.isFinite(v));
  if (clean.length === 0) return null;
  return clean.reduce((a, b) => a + b, 0) / clean.length;
}

function _median(values) {
  const clean = values.filter(v => Number.isFinite(v)).sort((a, b) => a - b);
  if (clean.length === 0) return null;
  const mid = Math.floor(clean.length / 2);
  return clean.length % 2 === 1 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2;
}

function _stddev(values) {
  const clean = values.filter(v => Number.isFinite(v));
  if (clean.length < 2) return null;
  const mean = clean.reduce((a, b) => a + b, 0) / clean.length;
  const variance = clean.reduce((a, b) => a + (b - mean) ** 2, 0) / clean.length;
  return Math.sqrt(variance);
}

function _cohensD(g1, g2) {
  const a = g1.filter(v => Number.isFinite(v));
  const b = g2.filter(v => Number.isFinite(v));
  if (a.length < 2 || b.length < 2) return null;
  const meanA = _mean(a);
  const meanB = _mean(b);
  if (meanA == null || meanB == null) return null;
  const varA = a.reduce((s, v) => s + (v - meanA) ** 2, 0) / (a.length - 1);
  const varB = b.reduce((s, v) => s + (v - meanB) ** 2, 0) / (b.length - 1);
  const pooledStd = Math.sqrt(((a.length - 1) * varA + (b.length - 1) * varB) / (a.length + b.length - 2));
  if (pooledStd === 0) return null;
  return (meanB - meanA) / pooledStd;
}

function _hitRate(outcomes) {
  const clean = outcomes.filter(v => Number.isFinite(v));
  if (clean.length === 0) return null;
  return clean.filter(v => v > 0).length / clean.length;
}

function _percentile(sorted, p) {
  if (sorted.length === 0) return null;
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function _simpleR2(featuresMatrix, outcomes) {
  // Simplified R²: correlation-based (not full OLS)
  // For each feature, compute correlation with outcome, take max |r|²
  if (!Array.isArray(featuresMatrix) || featuresMatrix.length < 3) return 0;
  if (!Array.isArray(outcomes) || outcomes.length !== featuresMatrix.length) return 0;

  let maxR2 = 0;
  const nFeatures = featuresMatrix[0]?.length ?? 0;

  for (let f = 0; f < nFeatures; f++) {
    const x = featuresMatrix.map(row => row[f]);
    const r = _pearsonR(x, outcomes);
    if (r != null) {
      const r2 = r * r;
      if (r2 > maxR2) maxR2 = r2;
    }
  }
  return maxR2;
}

function _pearsonR(x, y) {
  const n = Math.min(x.length, y.length);
  if (n < 3) return null;

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0;
  let count = 0;
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) continue;
    sumX += x[i];
    sumY += y[i];
    sumXY += x[i] * y[i];
    sumX2 += x[i] * x[i];
    sumY2 += y[i] * y[i];
    count++;
  }
  if (count < 3) return null;

  const denom = Math.sqrt((count * sumX2 - sumX * sumX) * (count * sumY2 - sumY * sumY));
  if (denom === 0) return null;
  return (count * sumXY - sumX * sumY) / denom;
}
