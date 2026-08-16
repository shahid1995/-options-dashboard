// Generic market analytics domain (Phase 4.2) — neutral, strategy-agnostic
// measurements over normalized observations.
//
// This module deliberately contains NO trading methodology:
//   - no absorption / convexity-build / turn-release / dealer-flip logic
//   - no institutional-trap or gamma-anomaly *interpretation*
//   - no delta-dominance, CE/PE buy-sell, or VIX trading rules
//   - no bullish / bearish / buy / sell language anywhere
//
// It measures relationships and changes between price, IV, delta, gamma,
// theta, vega, CE vs PE, OI, volume and (where a valid source exists) VIX,
// and returns DATA + MEASUREMENTS only. A future user-defined rule layer may
// interpret these measurements; this phase does not.
//
// ============================================================================
// UNIT CONTRACT (reused from the canonical foundations — nothing re-derived)
// ============================================================================
//   price        ₹ per unit contract (broker LTP, passthrough)
//   iv           canonical DECIMAL fraction (0.1824 = 18.24%) — normalized via
//                ivAnalytics.normalizeIv from the broker's percent feed
//   delta, gamma per 1 underlying point (per unit contract)
//   thetaPerDay  ₹ per calendar day (per unit contract)   [live convention: ×1]
//   vegaPerVolPoint ₹ per 1 volatility point (per unit)   [live convention: ×1]
//   1 vol point  = 0.01 volatility (VOL_POINT from ivAnalytics)
//   oi, volume   raw broker counts (0 is a valid zero; null is unavailable)
//
// Observation identity = symbol + expiry + strike (option type is per side).
// Change/relationship helpers REJECT comparisons across different identities —
// near-expiry data is never mixed with far-expiry data (§25/§26).

import { normalizeIv, VOL_POINT, decimalToVolPoints } from "./ivAnalytics";
import {
  cleanNumber,
  rollingMean,
  rollingMedian,
  rollingStdDev,
  rollingMin,
  rollingMax,
  zScore,
  percentileRank,
  anomalyMeasurement,
  MIN_STAT_SAMPLE,
} from "./statistics";

// ---- Metric inventories -----------------------------------------------------

// All per-side metrics an observation can carry (null = unavailable,
// 0 = valid zero — never conflated).
export const OBSERVATION_METRICS = [
  "price",
  "iv",
  "delta",
  "gamma",
  "thetaPerDay",
  "vegaPerVolPoint",
  "oi",
  "volume",
];
export const GREEK_METRICS = ["delta", "gamma", "thetaPerDay", "vegaPerVolPoint"];
export const CE_PE_METRICS = OBSERVATION_METRICS;

export const MIN_CORRELATION_SAMPLES = 3; // Pearson needs ≥ 3 aligned pairs
export const FLAT_EPSILON = 1e-9; // |difference| ≤ this ⇒ direction "flat"

// ---- Observation model --------------------------------------------------------

// Normalize ONE broker side (call or put) into canonical per-unit metrics.
// Broker chain fields → canonical: ltp → price, iv (percent) → canonical
// decimal, theta → thetaPerDay (live convention is already ₹/day), vega →
// vegaPerVolPoint (live convention is already ₹/1 vol point), delta/gamma
// pass through per 1 underlying point, oi/volume pass through raw.
export function normalizeSide(side) {
  if (!side) return null;
  const num = (v) => {
    if (v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return {
    price: num(side.ltp ?? side.price),
    iv: normalizeIv(side.iv), // broker percent → canonical decimal
    delta: num(side.delta),
    gamma: num(side.gamma),
    thetaPerDay: num(side.theta),
    vegaPerVolPoint: num(side.vega),
    oi: num(side.oi),
    volume: num(side.volume),
  };
}

// Build a generic observation (§5). Every field is optional; nothing is
// fabricated. `call` / `put` are normalized side objects; `vix` is
// { value } (a raw VIX point value — NEVER substituted by ATM/average IV).
export function makeObservation({ timestamp, symbol, expiry, strike, spot, call, put, vix } = {}) {
  const s = Number(strike);
  return {
    timestamp: timestamp ?? null,
    symbol: symbol ? String(symbol).toUpperCase() : null,
    expiry: expiry ?? null,
    strike: strike != null && Number.isFinite(s) ? s : null,
    spot: spot != null && Number.isFinite(Number(spot)) ? Number(spot) : null,
    call: normalizeSide(call),
    put: normalizeSide(put),
    vix: vix && vix.value != null && Number.isFinite(Number(vix.value)) ? { value: Number(vix.value) } : null,
  };
}

// Convenience: observation from a backend chain row
// ({ strike, call: {...}, put: {...} }) — the shape transform_chain emits.
export function observationFromChainRow({ symbol, expiry, row, spot, timestamp } = {}) {
  if (!row) return null;
  return makeObservation({ timestamp, symbol, expiry, strike: row.strike, spot, call: row.call, put: row.put });
}

// Observation identity: symbol + expiry + strike. Two observations with
// different identities must NEVER be compared as a change/relationship.
export function observationKey(o) {
  if (!o) return null;
  return `${o.symbol ?? ""}|${o.expiry ?? ""}|${o.strike ?? ""}`;
}

export function sameObservation(a, b) {
  const ka = observationKey(a);
  const kb = observationKey(b);
  return ka !== null && ka === kb;
}

// Count which canonical metrics are present across both sides + vix.
export function observationDataQuality(observation) {
  const expected = OBSERVATION_METRICS.length * 2 + 1; // both sides + vix
  let available = 0;
  OBSERVATION_METRICS.forEach((m) => {
    if (observation?.call?.[m] != null) available += 1;
    if (observation?.put?.[m] != null) available += 1;
  });
  if (observation?.vix?.value != null) available += 1;
  return dataQuality(available, expected);
}

// ---- Data quality --------------------------------------------------------------

// Structured availability: "available" (all), "partial" (some), "unavailable"
// (none). Missing data is never hidden and never converted to zero.
export function dataQuality(availableCount, expectedCount) {
  const available = Number(availableCount) || 0;
  const expected = Number(expectedCount) || 0;
  let status = "unavailable";
  if (expected > 0 && available === expected) status = "available";
  else if (available > 0) status = "partial";
  return { status, availableCount: available, expectedCount: expected };
}

// ---- Safe change helpers -------------------------------------------------------

// absoluteChange / percentChange / volPointChange / difference / ratio all
// return null when either input is invalid or (for percent/ratio) the
// denominator is zero. Infinity/NaN never leak into normal UI output.
export function absoluteChange(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null) return null;
  return Math.abs(c - p);
}

// (current − previous) / previous × 100. null when previous is 0 (a change vs
// a zero baseline is undefined, not 0%).
export function percentChange(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null || p === 0) return null;
  return ((c - p) / p) * 100;
}

// Canonical-decimal difference expressed in volatility points (0.01 each).
// Inputs are canonical decimals (0.19 vs 0.1824 → +0.76 vol points).
export function volPointChange(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null) return null;
  return decimalToVolPoints(c - p);
}

// a − b (signed).
export function difference(a, b) {
  const x = cleanNumber(a);
  const y = cleanNumber(b);
  if (x === null || y === null) return null;
  return x - y;
}

// a / b when b is valid and non-zero; null otherwise (no Infinity).
export function ratio(a, b) {
  const x = cleanNumber(a);
  const y = cleanNumber(b);
  if (x === null || y === null || y === 0) return null;
  return x / y;
}

// Convenience bundle for one metric's current-vs-previous change.
export function change(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null) {
    return { absolute: null, percent: null, available: false };
  }
  return {
    absolute: absoluteChange(c, p),
    percent: percentChange(c, p),
    available: true,
  };
}

// ---- Direction (purely mathematical, never bullish/bearish) --------------------

// "up" | "down" | "flat" | "unavailable".
export function directionOfChange(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null) return "unavailable";
  if (Math.abs(c - p) <= FLAT_EPSILON) return "flat";
  return c > p ? "up" : "down";
}

// ---- Magnitude normalization -----------------------------------------------------

// Deterministic 0–1 magnitude of a change: |change| / (|previous| + |change|).
//   flat        → 0
//   change dominating previous → approaches 1 (never reaches it)
//   missing input → null
// No hard-coded multipliers; documented above. NOT a probability of anything.
export function normalizedMagnitude(current, previous) {
  const c = cleanNumber(current);
  const p = cleanNumber(previous);
  if (c === null || p === null) return null;
  const changeAbs = Math.abs(c - p);
  const denom = Math.abs(p) + changeAbs;
  if (denom === 0) return 0; // both zero → flat
  return changeAbs / denom;
}

// ---- Pairwise comparison ----------------------------------------------------------

// Generic two-value comparison with no interpretation. dominantSide is purely
// numeric: "first" | "second" | "equal" | "unavailable".
export function pairwiseComparison(a, b) {
  const x = cleanNumber(a);
  const y = cleanNumber(b);
  const base = {
    first: x,
    second: y,
    difference: null,
    absoluteDifference: null,
    ratio: null,
    relativeDifference: null,
    normalizedDifference: null,
    dominantSide: x === null && y === null ? "unavailable" : "unavailable",
  };
  if (x === null || y === null) return base;
  const absMax = Math.max(Math.abs(x), Math.abs(y));
  return {
    first: x,
    second: y,
    difference: x - y,
    absoluteDifference: Math.abs(x - y),
    ratio: y !== 0 ? x / y : null,
    relativeDifference: y !== 0 ? ((x - y) / y) * 100 : null,
    normalizedDifference: absMax > 0 ? Math.abs(x - y) / absMax : null,
    dominantSide: x === y ? "equal" : x > y ? "first" : "second",
  };
}

// CE vs PE for one metric (price, iv, delta, gamma, thetaPerDay,
// vegaPerVolPoint, oi, volume). `dominantSide` means only the side with the
// greater numeric value — it implies nothing about bullishness or bearishness.
export function cePeComparison(observation, metric) {
  const ce = observation?.call?.[metric] ?? null;
  const pe = observation?.put?.[metric] ?? null;
  const cmp = pairwiseComparison(ce, pe);
  return { metric, ce, pe, ...cmp };
}

// All CE/PE comparisons for an observation.
export function cePeComparisons(observation) {
  return OBSERVATION_METRICS.map((m) => cePeComparison(observation, m));
}

// ---- Relationships ---------------------------------------------------------------

// Price vs IV relationship (mathematical only):
//   { priceChange, ivChange, ivChangeVolPoints, priceDirection, ivDirection,
//     sameDirection, oppositeDirection }
// Identities must match — otherwise the whole result is marked unavailable.
export function priceIvRelationship(current, previous) {
  const unavailable = {
    priceChange: null,
    ivChange: null,
    ivChangeVolPoints: null,
    priceDirection: "unavailable",
    ivDirection: "unavailable",
    sameDirection: false,
    oppositeDirection: false,
    aligned: false,
  };
  if (!current || !previous || !sameObservation(current, previous)) return unavailable;

  const p0 = current.call?.price ?? current.put?.price;
  const p1 = previous.call?.price ?? previous.put?.price;
  const i0 = current.call?.iv ?? current.put?.iv;
  const i1 = previous.call?.iv ?? previous.put?.iv;

  const priceDir = directionOfChange(p0, p1);
  const ivDir = directionOfChange(i0, i1);
  return {
    priceChange: difference(p0, p1),
    ivChange: difference(i0, i1),
    ivChangeVolPoints: volPointChange(i0, i1),
    priceDirection: priceDir,
    ivDirection: ivDir,
    sameDirection: priceDir !== "unavailable" && priceDir === ivDir,
    oppositeDirection: (priceDir === "up" && ivDir === "down") || (priceDir === "down" && ivDir === "up"),
    aligned: true,
  };
}

// Generic price vs one Greek metric (delta | gamma | thetaPerDay |
// vegaPerVolPoint). Measurements only — no signal meaning.
export function greekPriceRelationship(current, previous, greek) {
  const unavailable = {
    priceChange: null,
    metricChange: null,
    priceDirection: "unavailable",
    metricDirection: "unavailable",
    sameDirection: false,
    oppositeDirection: false,
    normalizedMagnitude: null,
    aligned: false,
  };
  if (!current || !previous || !sameObservation(current, previous)) return unavailable;

  const p0 = current.call?.price ?? current.put?.price;
  const p1 = previous.call?.price ?? previous.put?.price;
  const m0 = current.call?.[greek] ?? current.put?.[greek];
  const m1 = previous.call?.[greek] ?? previous.put?.[greek];

  const priceDir = directionOfChange(p0, p1);
  const metricDir = directionOfChange(m0, m1);
  return {
    priceChange: difference(p0, p1),
    metricChange: difference(m0, m1),
    priceDirection: priceDir,
    metricDirection: metricDir,
    sameDirection: priceDir !== "unavailable" && priceDir === metricDir,
    oppositeDirection: (priceDir === "up" && metricDir === "down") || (priceDir === "down" && metricDir === "up"),
    normalizedMagnitude: normalizedMagnitude(m0, m1),
    aligned: true,
  };
}

// Combined neutral data snapshot (§17) — a DATA SNAPSHOT, never a signal.
export function crossMetricSnapshot(current, previous) {
  const rel = (greek) => greekPriceRelationship(current, previous, greek);
  const d = rel("delta");
  const g = rel("gamma");
  const t = rel("thetaPerDay");
  const v = rel("vegaPerVolPoint");
  return {
    priceChange: d.priceChange,
    ivChangeVolPoints: priceIvRelationship(current, previous).ivChangeVolPoints,
    deltaChange: d.metricChange,
    gammaChange: g.metricChange,
    thetaChange: t.metricChange,
    vegaChange: v.metricChange,
    aligned: d.aligned,
  };
}

// ---- Correlation ----------------------------------------------------------------

// Pearson correlation between two aligned series. Pairs whose position does
// not contain two finite numbers are dropped (aligned by index); null when
// fewer than MIN_CORRELATION_SAMPLES pairs remain or either series has zero
// variance. Correlation is descriptive — never interpreted causally.
export function pearsonCorrelation(x, y) {
  if (!Array.isArray(x) || !Array.isArray(y) || x.length !== y.length) return null;
  const pairs = [];
  for (let i = 0; i < x.length; i++) {
    const a = cleanNumber(x[i]);
    const b = cleanNumber(y[i]);
    if (a !== null && b !== null) pairs.push([a, b]);
  }
  if (pairs.length < MIN_CORRELATION_SAMPLES) return null;
  const n = pairs.length;
  const meanX = pairs.reduce((s, p) => s + p[0], 0) / n;
  const meanY = pairs.reduce((s, p) => s + p[1], 0) / n;
  let cov = 0;
  let varX = 0;
  let varY = 0;
  pairs.forEach(([a, b]) => {
    const dx = a - meanX;
    const dy = b - meanY;
    cov += dx * dy;
    varX += dx * dx;
    varY += dy * dy;
  });
  if (!(varX > 0) || !(varY > 0)) return null; // zero-variance series → null
  return cov / Math.sqrt(varX * varY);
}

// ---- VIX -------------------------------------------------------------------------

// Generic VIX measurements. VIX is only ever the supplied VIX value — ATM IV,
// index IV or average IV are NEVER substituted. Without a value → status
// "unavailable"; with history ≥ MIN_STAT_SAMPLE → z-score/percentile included.
export function vixAnalytics(vixValue, history = []) {
  const current = cleanNumber(vixValue);
  if (current === null) {
    return {
      current: null,
      previous: null,
      change: null,
      changePercent: null,
      zScore: null,
      percentileRank: null,
      status: "unavailable",
      availableCount: 0,
      expectedCount: history.length,
    };
  }
  const prev = history.length ? cleanNumber(history[history.length - 1]) : null;
  const z = zScore(current, history);
  const pct = percentileRank(current, history);
  return {
    current,
    previous: prev,
    change: prev !== null ? current - prev : null,
    changePercent: prev !== null && prev !== 0 ? ((current - prev) / prev) * 100 : null,
    zScore: z,
    percentileRank: pct,
    status: z !== null ? "available" : history.length > 0 ? "partial" : "available",
    availableCount: history.length,
    expectedCount: history.length,
  };
}

// ---- Condition framework (neutral) ------------------------------------------------

// A generic condition is a neutral observation that something measurable
// happened. `magnitude` (0–100) is the size of the measured effect; `status`
// is data completeness. Neither is a probability of a price move or profit.
//   { id, detected, status, magnitude, evidence }
export function condition({ id, detected, status = "available", magnitude = null, evidence = {} }) {
  return { id, detected: Boolean(detected), status, magnitude, evidence };
}

// Strength and confidence stay STRICTLY SEPARATE (spec §22):
//   strength   — magnitude of the measured effect (0–100)
//   confidence — data completeness / statistical reliability (0–100)
// Both are derived from the analytics result; neither means "probability of
// price increase" nor "probability of profit".
export function strengthAndConfidence({ magnitude = null, availableCount = null, expectedCount = null } = {}) {
  const strength = magnitude != null ? Math.max(0, Math.min(100, magnitude)) : null;
  let confidence = null;
  if (expectedCount != null && expectedCount > 0) {
    confidence = Math.round(((availableCount ?? 0) / expectedCount) * 100);
  }
  return { strength, confidence };
}

// ---- Authoritative entry point ----------------------------------------------------

// One generic analytics result for a symbol/expiry/strike observation:
//   {
//     timestamp, status, identity: { symbol, expiry, strike },
//     price:    { current, previous, absoluteChange, percentChange, direction },
//     iv:       { current, previous, changeVolPoints, changePercent, direction,
//                 rollingMean, rollingMedian, rollingStdDev, zScore,
//                 percentileRank, anomaly },
//     greeks:   per-Greek { current, previous, change, direction } (+ anomaly),
//     cePe:     cePeComparisons (all metrics),
//     relationships: { priceIv, greek: { delta, gamma, thetaPerDay, vegaPerVolPoint } },
//     statistics: { anomaly },
//     anomalies: per-metric anomalyMeasurement,
//     vix:      vixAnalytics result,
//     warnings: structured warnings,
//   }
// `history` supplies the rolling baseline for IV/Greek statistics; without
// real historical data every statistic is null with an INSUFFICIENT_HISTORY
// warning (no fabricated rank/percentile). Multi-expiry safety: `current` and
// `previous` must share the same observation identity.
export function calculateMarketAnalytics({
  current = null,
  previous = null,
  history = [],
  vix = null,
  vixHistory = [],
  timestamp = null,
} = {}) {
  const warnings = [];

  const aligned = sameObservation(current, previous);
  if (current && previous && !aligned) {
    warnings.push({
      code: "OBSERVATION_MISMATCH",
      message: "Current and previous observations do not share the same symbol/expiry/strike — comparisons are unavailable.",
    });
  }

  const metricLine = (metric) => {
    const c = current?.call?.[metric] ?? current?.put?.[metric] ?? null;
    const p = previous?.call?.[metric] ?? previous?.put?.[metric] ?? null;
    const hist = (history ?? [])
      .map((o) => (o?.call?.[metric] ?? o?.put?.[metric]) ?? null)
      .filter((v) => v !== null);
    return {
      current: c,
      previous: p,
      change: difference(c, p),
      direction: directionOfChange(c, p),
      anomaly: anomalyMeasurement(c, hist),
    };
  };

  const ivHistory = (history ?? [])
    .map((o) => (o?.call?.iv ?? o?.put?.iv) ?? null)
    .filter((v) => v !== null);
  const ivAnomaly = anomalyMeasurement(current?.call?.iv ?? current?.put?.iv ?? null, ivHistory);

  if (ivHistory.length > 0 && ivHistory.length < MIN_STAT_SAMPLE) {
    warnings.push({
      code: "INSUFFICIENT_HISTORY",
      message: `IV statistics need ≥ ${MIN_STAT_SAMPLE} historical observations (${ivHistory.length} supplied) — z-score/percentile are null.`,
    });
  }

  const greeks = {};
  GREEK_METRICS.forEach((m) => {
    greeks[m] = metricLine(m);
  });

  const price = metricLine("price");

  return {
    timestamp: timestamp ?? current?.timestamp ?? null,
    status: observationDataQuality(current).status,
    identity: current
      ? { symbol: current.symbol, expiry: current.expiry, strike: current.strike }
      : { symbol: null, expiry: null, strike: null },
    price,
    iv: {
      current: current?.call?.iv ?? current?.put?.iv ?? null,
      previous: previous?.call?.iv ?? previous?.put?.iv ?? null,
      changeVolPoints: volPointChange(
        current?.call?.iv ?? current?.put?.iv ?? null,
        previous?.call?.iv ?? previous?.put?.iv ?? null
      ),
      changePercent: percentChange(
        current?.call?.iv ?? current?.put?.iv ?? null,
        previous?.call?.iv ?? previous?.put?.iv ?? null
      ),
      direction: directionOfChange(current?.call?.iv ?? current?.put?.iv ?? null, previous?.call?.iv ?? previous?.put?.iv ?? null),
      rollingMean: rollingMean(ivHistory),
      rollingMedian: rollingMedian(ivHistory),
      rollingStdDev: rollingStdDev(ivHistory),
      rollingMin: rollingMin(ivHistory),
      rollingMax: rollingMax(ivHistory),
      zScore: zScore(current?.call?.iv ?? current?.put?.iv ?? null, ivHistory),
      percentileRank: percentileRank(current?.call?.iv ?? current?.put?.iv ?? null, ivHistory),
      anomaly: ivAnomaly,
    },
    greeks,
    cePe: cePeComparisons(current),
    relationships: {
      priceIv: priceIvRelationship(current, previous),
      greek: {
        delta: greekPriceRelationship(current, previous, "delta"),
        gamma: greekPriceRelationship(current, previous, "gamma"),
        thetaPerDay: greekPriceRelationship(current, previous, "thetaPerDay"),
        vegaPerVolPoint: greekPriceRelationship(current, previous, "vegaPerVolPoint"),
      },
    },
    statistics: {
      ivAnomaly,
      minSample: MIN_STAT_SAMPLE,
    },
    anomalies: {
      iv: ivAnomaly,
      delta: metricLine("delta").anomaly,
      gamma: metricLine("gamma").anomaly,
      thetaPerDay: metricLine("thetaPerDay").anomaly,
      vegaPerVolPoint: metricLine("vegaPerVolPoint").anomaly,
    },
    vix: vixAnalytics(vix, vixHistory),
    warnings,
  };
}
