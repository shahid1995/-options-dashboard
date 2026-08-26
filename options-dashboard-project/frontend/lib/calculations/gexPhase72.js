/**
 * GEX Phase 7.2 — Gamma Flip & Gamma Walls
 *
 * Spot-sweep / model-validation module that extends the Phase 7.1 GEX
 * foundation with hypothetical-spot analysis.
 *
 * Core capability:
 *   For a range of hypothetical underlying values S*, compute the total
 *   chain GEX at each S* and identify where NetGEX(S*) = 0 (the Gamma
 *   Flip / Zero Gamma level).
 *
 * Uses Black-Scholes model gamma at hypothetical spot values with frozen
 * (observed) IV from the chain data.  The IV is held constant across the
 * sweep — only spot varies.  Each expiry uses its own remaining time to
 * expiry (T_i), not a single global T.
 *
 * Mathematical contract:
 *   GEX_i(S*) = Gamma_BS(S*, K_i, T_i, σ_i, r, q) × OI_i × S*² × 0.01
 *
 * where:
 *   Gamma_BS = Black-Scholes gamma at hypothetical spot S*
 *   OI_i     = open interest in contracts (from Phase 7.1)
 *   σ_i      = frozen observed IV for option i
 *   T_i      = frozen time-to-expiry for option i (per-expiry, NOT global)
 *   r        = risk-free rate (annualized, decimal)
 *   q        = dividend yield (annualized, decimal)
 *
 * Sign convention (inherited from Phase 7.1):
 *   Call GEX = + raw GEX
 *   Put GEX  = - raw GEX
 *
 * Reference: GEX_V1_0_SPEC.md §16-17
 */

import { bsGreeks, timeToExpiry } from "./pricing";
import { rawGex, GEX_STATUS, GEX_METHOD_VERSION, GEX_SIGN_CONVENTION } from "./gex";

// ---- Constants ---------------------------------------------------------------

export const GEX_PHASE72_VERSION = "GEX_SWEEP_V1";

/** Default sweep: ±30% of current spot */
export const DEFAULT_SWEEP_RANGE_PCT = 0.30;

/** Number of spot points in the sweep grid */
export const DEFAULT_SWEEP_STEPS = 501;

/** Minimum time-to-expiry in years for BS gamma validity */
export const MIN_T_FOR_SWEEP = 1 / 365;

/** Default number of top-N wall candidates to return per wall type */
export const DEFAULT_WALL_TOP_N = 3;

// ---- Black-Scholes gamma helper ----------------------------------------------

/**
 * Compute Black-Scholes model gamma for an option at a hypothetical spot.
 *
 * @param {string} type      — "call" or "put"
 * @param {number} S         — hypothetical underlying spot
 * @param {number} K         — strike price
 * @param {number} T         — time-to-expiry in years (frozen)
 * @param {number} sigma     — frozen IV as decimal fraction (0.1824 = 18.24%)
 * @param {number} r         — risk-free rate (decimal, default 0)
 * @param {number} q         — dividend yield (decimal, default 0)
 * @returns {number|null}    — model gamma, or null if inputs are invalid
 */
export function modelGamma(type, S, K, T, sigma, r = 0, q = 0) {
  if (!type || !Number.isFinite(S) || S <= 0) return null;
  if (!Number.isFinite(K) || K <= 0) return null;
  if (!Number.isFinite(T) || T < 0) return null;
  if (!Number.isFinite(sigma) || sigma <= 0) return null;
  if (!Number.isFinite(r) || !Number.isFinite(q)) return null;

  const greeks = bsGreeks(type, S, K, T, sigma, r, q);
  if (!greeks || !Number.isFinite(greeks.gamma)) return null;
  return greeks.gamma;
}

// ---- Per-expiry time-to-expiry resolution ------------------------------------

/**
 * Resolve time-to-expiry for each expiry group.
 *
 * Priority:
 *   1. If options.expiryTMap is provided (Map or object), use it directly.
 *   2. If options.valuationDate is provided, compute T from valuationDate → expiry date.
 *   3. Fall back to options.T (single global T, backward-compatible).
 *
 * @param {Map|object|null} expiryTMap — explicit { expiry → T } mapping
 * @param {string|null} valuationDate — ISO YYYY-MM-DD
 * @param {string} expiryDate — ISO YYYY-MM-DD for this expiry
 * @param {number|null} globalT — fallback global T
 * @returns {number|null} T in years, or null if unresolvable
 */
function resolveT(expiryTMap, valuationDate, expiryDate, globalT) {
  // 1. Explicit map
  if (expiryTMap) {
    const t = expiryTMap instanceof Map ? expiryTMap.get(expiryDate) : expiryTMap[expiryDate];
    if (t != null && Number.isFinite(t) && t >= MIN_T_FOR_SWEEP) return t;
  }
  // 2. From dates
  if (valuationDate && expiryDate) {
    const t = timeToExpiry(valuationDate, expiryDate);
    if (t != null && Number.isFinite(t) && t >= MIN_T_FOR_SWEEP) return t;
  }
  // 3. Global fallback
  if (globalT != null && Number.isFinite(globalT) && globalT >= MIN_T_FOR_SWEEP) return globalT;
  return null;
}

// ---- Spot sweep --------------------------------------------------------------

/**
 * Compute net GEX at a single hypothetical spot value S* across an array of
 * chain rows, using Black-Scholes model gamma with frozen IV and per-expiry T.
 *
 * @param {Array}  rows  — canonical chain rows for ONE expiry
 * @param {number} S     — hypothetical spot value
 * @param {number} T     — time-to-expiry in years for THIS expiry
 * @param {number} r     — risk-free rate (decimal)
 * @param {number} q     — dividend yield (decimal)
 * @returns {{ callGex: number, putGex: number, netGex: number, validStrikeCount: number }}
 */
export function netGexAtSpot(rows, S, T, r, q) {
  let callGex = 0;
  let putGex = 0;
  let validCount = 0;

  for (const row of rows) {
    const strike = row.strike;
    const call = row.call || {};
    const put = row.put || {};

    const callOi = Number(call.oi);
    const callIv = Number(call.iv);
    const putOi = Number(put.oi);
    const putIv = Number(put.iv);

    // Call side
    if (callOi > 0 && callIv > 0 && T > 0) {
      const g = modelGamma("call", S, strike, T, callIv, r, q);
      if (g != null && Number.isFinite(g)) {
        callGex += g * callOi * S * S * 0.01;
      }
    }

    // Put side
    if (putOi > 0 && putIv > 0 && T > 0) {
      const g = modelGamma("put", S, strike, T, putIv, r, q);
      if (g != null && Number.isFinite(g)) {
        // Put GEX is negative under NAIVE_DEALER_CONVENTION
        putGex -= g * putOi * S * S * 0.01;
      }
    }

    // A strike is valid if at least one side contributed
    const callContributed =
      callOi > 0 && callIv > 0 && T > 0 && modelGamma("call", S, strike, T, callIv, r, q) != null;
    const putContributed =
      putOi > 0 && putIv > 0 && T > 0 && modelGamma("put", S, strike, T, putIv, r, q) != null;
    if (callContributed || putContributed) validCount++;
  }

  return {
    callGex,
    putGex,
    netGex: callGex + putGex,
    validStrikeCount: validCount,
  };
}

// ---- Zero-crossing detection -------------------------------------------------

/**
 * Detect zero crossings in an array of net GEX values using linear
 * interpolation between consecutive sweep points.
 *
 * @param {Array<{ spot: number, netGex: number }>} sweepPoints — sorted by spot ascending
 * @returns {Array<{ spotA, spotB, gexA, gexB, crossingSpot, transitionMagnitude }>}
 */
export function detectZeroCrossings(sweepPoints) {
  const crossings = [];

  for (let i = 0; i < sweepPoints.length - 1; i++) {
    const a = sweepPoints[i];
    const b = sweepPoints[i + 1];

    if (a.netGex == null || b.netGex == null) continue;
    if (!Number.isFinite(a.netGex) || !Number.isFinite(b.netGex)) continue;

    const signA = Math.sign(a.netGex);
    const signB = Math.sign(b.netGex);

    // Exact zero is a crossing
    if (a.netGex === 0) {
      crossings.push({
        spotA: a.spot,
        spotB: b.spot,
        gexA: a.netGex,
        gexB: b.netGex,
        crossingSpot: a.spot,
        transitionMagnitude: Math.abs(b.netGex),
      });
      continue;
    }

    // Sign change between consecutive points
    if (signA !== 0 && signB !== 0 && signA !== signB) {
      const t = a.netGex / (a.netGex - b.netGex);
      const crossingSpot = a.spot + t * (b.spot - a.spot);
      crossings.push({
        spotA: a.spot,
        spotB: b.spot,
        gexA: a.netGex,
        gexB: b.netGex,
        crossingSpot,
        transitionMagnitude: Math.abs(a.netGex) + Math.abs(b.netGex),
      });
    }
  }

  return crossings;
}

// ---- Gamma Walls — Directional -----------------------------------------------

/**
 * Find directional gamma wall candidates from per-strike GEX values.
 *
 * Wall semantics (CORRECTED for directional intent):
 *
 *   Call Wall:
 *     A strike with significant POSITIVE call-side GEX concentration.
 *     These represent areas where call gamma exposure is concentrated.
 *     Preferably located at or above the current spot (call-side structural level).
 *     Value = raw signed call GEX (positive).
 *
 *   Put Wall:
 *     A strike with significant NEGATIVE put-side GEX concentration.
 *     These represent areas where put gamma exposure is concentrated.
 *     Preferably located at or below the current spot (put-side structural level).
 *     Value = raw signed put GEX (negative).
 *
 *   Net Wall:
 *     A strike where the absolute net GEX is locally maximized.
 *     Value = absolute net GEX.
 *
 * A wall is a local maximum of the directional signal:
 *   - Strictly greater than both neighbors, OR
 *   - Equal to the higher neighbor and strictly greater than the other
 *
 * Returns top-N candidates ranked by magnitude, not all local maxima.
 *
 * @param {Array} strikeGexList — [{ strike, callGex, putGex, netGex }]
 * @param {number} spot         — current spot for positional preference
 * @param {number} topN         — max candidates per wall type (default 3)
 * @returns {{ callWalls: Array, putWalls: Array, netWalls: Array }}
 */
export function findGammaWalls(strikeGexList, spot = null, topN = DEFAULT_WALL_TOP_N) {
  if (!strikeGexList || strikeGexList.length === 0) {
    return { callWalls: [], putWalls: [], netWalls: [] };
  }

  const sorted = [...strikeGexList].sort((a, b) => a.strike - b.strike);

  // Call walls: positive call GEX concentration
  const callWalls = findDirectionalLocalMaxima(
    sorted.map((s) => ({ strike: s.strike, signedGex: s.callGex })),
    spot,
    "above",
  );

  // Put walls: negative put GEX concentration (use signed value, find maxima of magnitude)
  const putWalls = findDirectionalLocalMaxima(
    sorted.map((s) => ({ strike: s.strike, signedGex: s.putGex })),
    spot,
    "below",
  );

  // Net walls: absolute net GEX local maxima
  const netWalls = findNetLocalMaxima(
    sorted.map((s) => ({ strike: s.strike, netGex: s.netGex })),
  );

  return {
    callWalls: callWalls.slice(0, topN),
    putWalls: putWalls.slice(0, topN),
    netWalls: netWalls.slice(0, topN),
  };
}

/**
 * Find local maxima of a directional (signed) GEX signal.
 *
 * For call walls (direction="above"):
 *   We look for local maxima of the signed GEX (positive values).
 *   Walls at or above current spot are preferred (lower sort key).
 *
 * For put walls (direction="below"):
 *   We look for local maxima of |signed GEX| (absolute magnitude).
 *   Walls at or below current spot are preferred (lower sort key).
 *
 * @param {Array<{ strike: number, signedGex: number|null }>} points
 * @param {number|null} spot — current spot for positional preference
 * @param {string} direction — "above" (call) or "below" (put)
 * @returns {Array<{ strike, magnitude, signedGex, positionPreference, isGlobalMax }>}
 */
function findDirectionalLocalMaxima(points, spot, direction) {
  if (!points || points.length === 0) return [];

  // Find local maxima of absolute magnitude where signed GEX has correct sign
  const candidates = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (p.signedGex == null || !Number.isFinite(p.signedGex)) continue;

    const magnitude = Math.abs(p.signedGex);
    if (magnitude <= 0) continue;

    const prev = i > 0 ? points[i - 1] : null;
    const next = i < points.length - 1 ? points[i + 1] : null;

    const prevMag = prev?.signedGex != null ? Math.abs(prev.signedGex) : 0;
    const nextMag = next?.signedGex != null ? Math.abs(next.signedGex) : 0;

    // Local maximum of magnitude
    if (magnitude >= prevMag && magnitude >= nextMag) {
      const atBoundary = prev == null || next == null;
      if (atBoundary || magnitude > prevMag || magnitude > nextMag) {
        const positionPreference =
          spot != null
            ? direction === "above"
              ? p.strike >= spot
              : p.strike <= spot
            : null;

        candidates.push({
          strike: p.strike,
          magnitude,
          signedGex: p.signedGex,
          positionPreference,
          isGlobalMax: false,
        });
      }
    }
  }

  // Sort: prefer correct position, then by magnitude descending
  candidates.sort((a, b) => {
    // Prefer correctly positioned walls
    if (a.positionPreference !== b.positionPreference) {
      return a.positionPreference ? -1 : 1;
    }
    // Then by magnitude descending
    return b.magnitude - a.magnitude;
  });

  // Mark global max
  if (candidates.length > 0) {
    let maxIdx = 0;
    for (let i = 1; i < candidates.length; i++) {
      if (candidates[i].magnitude > candidates[maxIdx].magnitude) maxIdx = i;
    }
    candidates[maxIdx].isGlobalMax = true;
  }

  return candidates;
}

/**
 * Find local maxima of absolute net GEX.
 *
 * @param {Array<{ strike: number, netGex: number|null }>} points
 * @returns {Array<{ strike, magnitude, netGex, isGlobalMax }>}
 */
function findNetLocalMaxima(points) {
  if (!points || points.length === 0) return [];

  const walls = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (p.netGex == null || !Number.isFinite(p.netGex)) continue;

    const magnitude = Math.abs(p.netGex);
    if (magnitude <= 0) continue;

    const prev = i > 0 ? points[i - 1] : null;
    const next = i < points.length - 1 ? points[i + 1] : null;

    const prevMag = prev?.netGex != null ? Math.abs(prev.netGex) : 0;
    const nextMag = next?.netGex != null ? Math.abs(next.netGex) : 0;

    if (magnitude >= prevMag && magnitude >= nextMag) {
      const atBoundary = prev == null || next == null;
      if (atBoundary || magnitude > prevMag || magnitude > nextMag) {
        walls.push({
          strike: p.strike,
          magnitude,
          netGex: p.netGex,
          isGlobalMax: false,
        });
      }
    }
  }

  if (walls.length > 0) {
    let maxIdx = 0;
    for (let i = 1; i < walls.length; i++) {
      if (walls[i].magnitude > walls[maxIdx].magnitude) maxIdx = i;
    }
    walls[maxIdx].isGlobalMax = true;
  }

  return walls;
}

// ---- Broker vs model gamma comparison ----------------------------------------

/**
 * Compare broker-provided gamma with Black-Scholes model gamma at the current
 * spot for each option in the chain.
 *
 * @param {Array}  rows     — canonical chain rows
 * @param {number} spot     — current spot
 * @param {number} T        — time-to-expiry in years (frozen)
 * @param {number} r        — risk-free rate
 * @param {number} q        — dividend yield
 * @returns {{ comparisons: Array, summary: object }}
 */
export function brokerVsModelGamma(rows, spot, T, r, q) {
  if (!rows || rows.length === 0 || !Number.isFinite(spot) || spot <= 0) {
    return { comparisons: [], summary: { count: 0, meanAbsDiff: null, maxAbsDiff: null } };
  }

  const comparisons = [];

  for (const row of rows) {
    const strike = row.strike;
    const call = row.call || {};
    const put = row.put || {};

    // Call comparison
    if (call.gamma != null && call.iv != null && Number.isFinite(call.gamma) && Number.isFinite(call.iv) && call.iv > 0) {
      const mG = modelGamma("call", spot, strike, T, call.iv, r, q);
      if (mG != null) {
        comparisons.push({
          strike,
          side: "call",
          brokerGamma: call.gamma,
          modelGamma: mG,
          diff: call.gamma - mG,
          absDiff: Math.abs(call.gamma - mG),
          relativeDiff: mG !== 0 ? Math.abs((call.gamma - mG) / mG) : null,
        });
      }
    }

    // Put comparison
    if (put.gamma != null && put.iv != null && Number.isFinite(put.gamma) && Number.isFinite(put.iv) && put.iv > 0) {
      const mG = modelGamma("put", spot, strike, T, put.iv, r, q);
      if (mG != null) {
        comparisons.push({
          strike,
          side: "put",
          brokerGamma: put.gamma,
          modelGamma: mG,
          diff: put.gamma - mG,
          absDiff: Math.abs(put.gamma - mG),
          relativeDiff: mG !== 0 ? Math.abs((put.gamma - mG) / mG) : null,
        });
      }
    }
  }

  let sumAbsDiff = 0;
  let maxAbsDiff = 0;
  let sumRelDiff = 0;
  let relCount = 0;

  for (const c of comparisons) {
    sumAbsDiff += c.absDiff;
    if (c.absDiff > maxAbsDiff) maxAbsDiff = c.absDiff;
    if (c.relativeDiff != null) {
      sumRelDiff += c.relativeDiff;
      relCount++;
    }
  }

  return {
    comparisons,
    summary: {
      count: comparisons.length,
      meanAbsDiff: comparisons.length > 0 ? sumAbsDiff / comparisons.length : null,
      maxAbsDiff: comparisons.length > 0 ? maxAbsDiff : null,
      meanRelativeDiff: relCount > 0 ? sumRelDiff / relCount : null,
    },
  };
}

// ---- Data-quality diagnostics ------------------------------------------------

/**
 * Assess the quality and completeness of chain data for a spot sweep.
 */
export function sweepDataQuality(rows, spot) {
  if (!rows || rows.length === 0) {
    return {
      totalStrikes: 0,
      strikesWithCallGamma: 0,
      strikesWithPutGamma: 0,
      strikesWithBothGamma: 0,
      strikesWithCallIv: 0,
      strikesWithPutIv: 0,
      strikesWithCallOi: 0,
      strikesWithPutOi: 0,
      strikesReadyForSweep: 0,
      missingCallGamma: 0,
      missingPutGamma: 0,
      missingCallIv: 0,
      missingPutIv: 0,
      missingCallOi: 0,
      missingPutOi: 0,
      sweepReadiness: "unavailable",
      spotInRange: false,
      minStrike: null,
      maxStrike: null,
    };
  }

  let hasCallGamma = 0;
  let hasPutGamma = 0;
  let hasBothGamma = 0;
  let hasCallIv = 0;
  let hasPutIv = 0;
  let hasCallOi = 0;
  let hasPutOi = 0;
  let readyForSweep = 0;

  const strikes = rows.map((r) => r.strike).sort((a, b) => a - b);
  const minStrike = strikes[0];
  const maxStrike = strikes[strikes.length - 1];

  for (const row of rows) {
    const call = row.call || {};
    const put = row.put || {};

    const cgOk = call.gamma != null && Number.isFinite(call.gamma) && call.gamma > 0;
    const pgOk = put.gamma != null && Number.isFinite(put.gamma) && put.gamma > 0;
    const ciOk = call.iv != null && Number.isFinite(call.iv) && call.iv > 0;
    const piOk = put.iv != null && Number.isFinite(put.iv) && put.iv > 0;
    const coOk = call.oi != null && Number.isFinite(call.oi) && call.oi > 0;
    const poOk = put.oi != null && Number.isFinite(put.oi) && put.oi > 0;

    if (cgOk) hasCallGamma++;
    if (pgOk) hasPutGamma++;
    if (cgOk && pgOk) hasBothGamma++;
    if (ciOk) hasCallIv++;
    if (piOk) hasPutIv++;
    if (coOk) hasCallOi++;
    if (poOk) hasPutOi++;

    if ((cgOk && ciOk && coOk) || (pgOk && piOk && poOk)) readyForSweep++;
  }

  const spotInRange = Number.isFinite(spot) && spot >= minStrike && spot <= maxStrike;

  let sweepReadiness;
  if (readyForSweep === rows.length && readyForSweep > 0) {
    sweepReadiness = "available";
  } else if (readyForSweep > 0) {
    sweepReadiness = "partial";
  } else {
    sweepReadiness = "unavailable";
  }

  return {
    totalStrikes: rows.length,
    strikesWithCallGamma: hasCallGamma,
    strikesWithPutGamma: hasPutGamma,
    strikesWithBothGamma: hasBothGamma,
    strikesWithCallIv: hasCallIv,
    strikesWithPutIv: hasPutIv,
    strikesWithCallOi: hasCallOi,
    strikesWithPutOi: hasPutOi,
    strikesReadyForSweep: readyForSweep,
    missingCallGamma: rows.length - hasCallGamma,
    missingPutGamma: rows.length - hasPutGamma,
    missingCallIv: rows.length - hasCallIv,
    missingPutIv: rows.length - hasPutIv,
    missingCallOi: rows.length - hasCallOi,
    missingPutOi: rows.length - hasPutOi,
    sweepReadiness,
    spotInRange,
    minStrike,
    maxStrike,
  };
}

// ---- Crossing-strength computation -------------------------------------------

/**
 * Compute crossing strength from the GEX transition magnitude around a crossing.
 *
 * Strength is defined as: |gexA| + |gexB| (the total absolute GEX transition).
 * A stronger crossing means the GEX profile changes more sharply at that point,
 * making it a more structurally significant level.
 *
 * @param {object} crossing — { gexA, gexB, ... }
 * @returns {number} strength value (0 if invalid)
 */
export function crossingStrength(crossing) {
  if (!crossing) return 0;
  const a = Number(crossing.gexA);
  const b = Number(crossing.gexB);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0;
  return Math.abs(a) + Math.abs(b);
}

// ---- Primary flip selection --------------------------------------------------

/**
 * Select the primary gamma flip from detected crossings.
 *
 * DETERMINISTIC RANKING FORMULA:
 *
 * Each crossing is scored using a multi-factor composite:
 *
 *   score = w_proximity × proximityScore + w_strength × strengthScore + w_quality × qualityScore
 *
 * where:
 *
 *   proximityScore = 1 - (|crossingSpot - currentSpot| / sweepRange)
 *     Normalized: 1.0 = at current spot, 0.0 = at sweep boundary.
 *     Linear decay from spot to boundary.
 *
 *   strengthScore = transitionMagnitude / maxTransitionMagnitude
 *     Normalized: 1.0 = strongest crossing, 0.0 = weakest.
 *     Transition magnitude = |gexA| + |gexB|.
 *
 *   qualityScore = strikesReadyForSweep / totalStrikes
 *     Fraction of strikes with valid data for the sweep.
 *     Higher quality → more trustworthy flip detection.
 *
 * Weights (fixed, documented):
 *   w_proximity = 0.50  (proximity to current spot is most important)
 *   w_strength  = 0.30  (crossing sharpness matters)
 *   w_quality   = 0.20  (data quality adjusts confidence)
 *
 * Selection:
 *   - Highest composite score wins.
 *   - Ties broken by: lowest crossingSpot (deterministic).
 *   - If no crossings → null.
 *   - If single crossing → it is primary (score computed but not needed for selection).
 *
 * @param {number} currentSpot
 * @param {Array} crossings — from detectZeroCrossings
 * @param {object} dataQuality — from sweepDataQuality (optional, defaults to full quality)
 * @param {number} sweepRange — total sweep range for proximity normalization (optional)
 * @returns {object|null} the primary flip with crossingSpot, direction, score, etc.
 */
export function selectPrimaryFlip(currentSpot, crossings, dataQuality = null, sweepRange = null) {
  if (!crossings || crossings.length === 0) return null;

  const qualityFraction =
    dataQuality && dataQuality.totalStrikes > 0
      ? dataQuality.strikesReadyForSweep / dataQuality.totalStrikes
      : 1.0;

  const range = sweepRange || currentSpot; // fallback: use spot as range scale

  // Compute max transition magnitude for normalization
  let maxMagnitude = 0;
  for (const c of crossings) {
    const mag = crossingStrength(c);
    if (mag > maxMagnitude) maxMagnitude = mag;
  }

  // Score each crossing
  let best = null;
  let bestScore = -Infinity;

  for (const c of crossings) {
    const dist = Math.abs(c.crossingSpot - currentSpot);
    const proximityScore = Math.max(0, 1 - dist / range);
    const strengthScore = maxMagnitude > 0 ? crossingStrength(c) / maxMagnitude : 1;
    const qualityScore = qualityFraction;

    const score = 0.5 * proximityScore + 0.3 * strengthScore + 0.2 * qualityScore;

    if (
      score > bestScore ||
      (score === bestScore && (best == null || c.crossingSpot < best.crossingSpot))
    ) {
      best = c;
      bestScore = score;
    }
  }

  return {
    ...best,
    direction: best.gexA > 0 ? "positive_to_negative" : "negative_to_positive",
    crossingStrength: crossingStrength(best),
    compositeScore: bestScore,
    rankingFactors: {
      proximityWeight: 0.5,
      strengthWeight: 0.3,
      qualityWeight: 0.2,
      qualityFraction,
    },
  };
}

// ---- Main spot sweep function ------------------------------------------------

/**
 * Sweep a range of hypothetical spot values and compute chain-level net GEX
 * at each using Black-Scholes model gamma with frozen IV and per-expiry T.
 *
 * @param {Array}  chainRows — canonical chain rows (may include multiple expiries)
 * @param {object} options
 * @param {number} options.spot              — current underlying spot
 * @param {string} [options.symbol]          — underlying symbol (metadata)
 * @param {number} [options.T]               — fallback global time-to-expiry in years
 * @param {string} [options.valuationDate]   — ISO YYYY-MM-DD for per-expiry T computation
 * @param {Map|object} [options.expiryTMap]  — explicit { expiry → T } mapping (highest priority)
 * @param {number} [options.r=0]             — risk-free rate (decimal)
 * @param {number} [options.q=0]             — dividend yield (decimal)
 * @param {number} [options.sweepRangePct=0.30] — ±fraction of spot
 * @param {number} [options.sweepSteps=501]  — grid points
 * @param {number} [options.wallTopN=3]      — top-N wall candidates per type
 * @returns {object} sweep result
 */
export function spotSweep(chainRows, options = {}) {
  const {
    spot,
    symbol,
    T: globalT,
    valuationDate,
    expiryTMap,
    r = 0,
    q = 0,
    sweepRangePct = DEFAULT_SWEEP_RANGE_PCT,
    sweepSteps = DEFAULT_SWEEP_STEPS,
    wallTopN = DEFAULT_WALL_TOP_N,
  } = options;

  // ---- Input validation ----
  if (!Number.isFinite(spot) || spot <= 0) {
    return unavailableSweep("INVALID_SPOT", options);
  }
  if (!chainRows || chainRows.length === 0) {
    return unavailableSweep("NO_CHAIN_DATA", options);
  }

  // Group by expiry
  const expiryMap = new Map();
  for (const row of chainRows) {
    const expiry = row.expiry ?? row.expiry_date;
    if (!expiryMap.has(expiry)) expiryMap.set(expiry, []);
    expiryMap.get(expiry).push(row);
  }

  const expiryEntries = Array.from(expiryMap.entries());
  const sweepRange = spot * sweepRangePct;
  const spotMin = Math.max(spot - sweepRange, 1);
  const spotMax = spot + sweepRange;
  const spotStep = (spotMax - spotMin) / (sweepSteps - 1);

  // ---- Perform sweep across all expiries (each with its own T) ----
  const expirySweepResults = [];
  const allSweepPoints = new Array(sweepSteps);
  let anyValidT = false;

  for (let idx = 0; idx < sweepSteps; idx++) {
    allSweepPoints[idx] = { spot: spotMin + idx * spotStep, netGex: 0, callGex: 0, putGex: 0 };
  }

  for (const [expiry, rows] of expiryEntries) {
    // Resolve T for this specific expiry
    const T = resolveT(expiryTMap, valuationDate, expiry, globalT);

    if (T == null || !Number.isFinite(T) || T < MIN_T_FOR_SWEEP) {
      // This expiry has no valid T — skip it with unavailable status
      expirySweepResults.push({
        expiry,
        T: null,
        sweepPoints: [],
        crossings: [],
        walls: { callWalls: [], putWalls: [], netWalls: [] },
        status: GEX_STATUS.UNAVAILABLE,
        reason: "INVALID_T",
      });
      continue;
    }

    anyValidT = true;
    const expiryPoints = [];

    for (let idx = 0; idx < sweepSteps; idx++) {
      const S = spotMin + idx * spotStep;
      const result = netGexAtSpot(rows, S, T, r, q);
      expiryPoints.push({
        spot: S,
        callGex: result.callGex,
        putGex: result.putGex,
        netGex: result.netGex,
      });

      allSweepPoints[idx].callGex += result.callGex;
      allSweepPoints[idx].putGex += result.putGex;
      allSweepPoints[idx].netGex += result.netGex;
    }

    // Zero crossings for this expiry
    const expiryCrossings = detectZeroCrossings(expiryPoints);

    // Gamma walls for this expiry (using broker GEX at current spot, per-expiry T)
    const expiryBrokerStrikeGex = rows.map((row) => {
      const call = row.call || {};
      const put = row.put || {};
      const callOi = Number(call.oi) || 0;
      const putOi = Number(put.oi) || 0;
      const callGamma = Number(call.gamma) || 0;
      const putGamma = Number(put.gamma) || 0;

      return {
        strike: row.strike,
        callGex: callGamma > 0 && callOi > 0 ? rawGex(callGamma, callOi, spot) : null,
        putGex: putGamma > 0 && putOi > 0 ? -rawGex(putGamma, putOi, spot) : null,
        netGex:
          callGamma > 0 && callOi > 0 && putGamma > 0 && putOi > 0
            ? rawGex(callGamma, callOi, spot) - rawGex(putGamma, putOi, spot)
            : null,
      };
    });

    expirySweepResults.push({
      expiry,
      T,
      sweepPoints: expiryPoints,
      crossings: expiryCrossings,
      walls: findGammaWalls(expiryBrokerStrikeGex, spot, wallTopN),
      status: GEX_STATUS.AVAILABLE,
    });
  }

  if (!anyValidT) {
    return unavailableSweep("INVALID_T", options);
  }

  // ---- Chain-level crossings ----
  const chainCrossings = detectZeroCrossings(allSweepPoints);

  // ---- Chain-level gamma walls ----
  const brokerStrikeGex = chainRows.map((row) => {
    const call = row.call || {};
    const put = row.put || {};
    const callOi = Number(call.oi) || 0;
    const putOi = Number(put.oi) || 0;
    const callGamma = Number(call.gamma) || 0;
    const putGamma = Number(put.gamma) || 0;

    return {
      strike: row.strike,
      callGex: callGamma > 0 && callOi > 0 ? rawGex(callGamma, callOi, spot) : null,
      putGex: putGamma > 0 && putOi > 0 ? -rawGex(putGamma, putOi, spot) : null,
      netGex:
        callGamma > 0 && callOi > 0 && putGamma > 0 && putOi > 0
          ? rawGex(callGamma, callOi, spot) - rawGex(putGamma, putOi, spot)
          : null,
    };
  });
  const chainWalls = findGammaWalls(brokerStrikeGex, spot, wallTopN);

  // ---- Data quality ----
  const dataQuality = sweepDataQuality(chainRows, spot);

  // ---- Primary flip selection (multi-factor) ----
  const primaryFlip = selectPrimaryFlip(spot, chainCrossings, dataQuality, sweepRange * 2);

  // ---- Spot GEX at current spot ----
  // Use the first valid expiry T for current-spot GEX (or chain-level broker GEX)
  const currentResult = netGexAtSpot(chainRows, spot, globalT || 1 / 365, r, q);

  // ---- Broker vs model gamma comparison (use first valid T) ----
  const firstValidT = expirySweepResults.find((e) => e.T != null)?.T ?? globalT;
  const gammaComparison = firstValidT != null ? brokerVsModelGamma(chainRows, spot, firstValidT, r, q) : { comparisons: [], summary: { count: 0, meanAbsDiff: null, maxAbsDiff: null } };

  // ---- Sweep status ----
  let status;
  if (chainCrossings.length > 0) {
    status = GEX_STATUS.AVAILABLE;
  } else if (dataQuality.strikesReadyForSweep > 0) {
    status = GEX_STATUS.AVAILABLE;
  } else if (dataQuality.sweepReadiness === "partial") {
    status = GEX_STATUS.PARTIAL;
  } else {
    status = GEX_STATUS.UNAVAILABLE;
  }

  return {
    underlying: symbol ?? null,
    spot,
    r,
    q,
    methodology: GEX_PHASE72_VERSION,
    baseMethodology: GEX_METHOD_VERSION,
    signConvention: GEX_SIGN_CONVENTION,
    sweepConfig: {
      spotMin,
      spotMax,
      spotStep,
      sweepSteps,
      sweepRangePct,
    },
    currentGex: {
      callGex: currentResult.callGex,
      putGex: currentResult.putGex,
      netGex: currentResult.netGex,
      validStrikeCount: currentResult.validStrikeCount,
    },
    gammaFlip: {
      crossings: chainCrossings,
      primaryFlip,
      crossingCount: chainCrossings.length,
      distanceFromSpot: primaryFlip != null ? Math.abs(primaryFlip.crossingSpot - spot) : null,
      distanceFromSpotPct: primaryFlip != null ? Math.abs(primaryFlip.crossingSpot - spot) / spot : null,
      noCrossingFound: chainCrossings.length === 0,
    },
    gammaWalls: chainWalls,
    byExpiry: expirySweepResults,
    brokerVsModel: gammaComparison,
    dataQuality,
    status,
  };
}

// ---- Unavailable result helper -----------------------------------------------

function unavailableSweep(reason, options) {
  return {
    underlying: options.symbol ?? null,
    spot: options.spot ?? null,
    r: options.r ?? 0,
    q: options.q ?? 0,
    methodology: GEX_PHASE72_VERSION,
    baseMethodology: GEX_METHOD_VERSION,
    signConvention: GEX_SIGN_CONVENTION,
    sweepConfig: null,
    currentGex: { callGex: null, putGex: null, netGex: null, validStrikeCount: 0 },
    gammaFlip: {
      crossings: [],
      primaryFlip: null,
      crossingCount: 0,
      distanceFromSpot: null,
      distanceFromSpotPct: null,
      noCrossingFound: true,
    },
    gammaWalls: { callWalls: [], putWalls: [], netWalls: [] },
    byExpiry: [],
    brokerVsModel: { comparisons: [], summary: { count: 0, meanAbsDiff: null, maxAbsDiff: null } },
    dataQuality: sweepDataQuality(null, options.spot),
    status: GEX_STATUS.UNAVAILABLE,
    reason,
  };
}
