/**
 * GEX Phase 7.7 — Research Observation Builder & Forward Outcomes
 *
 * Constructs canonical ResearchObservations by joining GEX snapshots
 * with NIFTY candle data.  Computes forward outcomes retrospectively.
 *
 * Strict rules:
 *   - Features come from data at or before capturedAt only
 *   - Forward outcomes come from candles strictly after capturedAt
 *   - No look-ahead bias permitted
 *   - null means unavailable; never silently convert to zero
 */

// ---- Constants -----------------------------------------------------------

/** Forward horizons in number of candles (3-min each) */
export const HORIZONS = [1, 3, 5, 10, 15, 30];

/** Minimum candles needed after observation for each horizon */
export const MIN_FORWARD_CANDLES = Math.max(...HORIZONS);

/** Day-of-week names for time-of-day classification */
const MARKET_OPEN_HOUR = 9;  // 09:15 IST
const MARKET_OPEN_MIN = 15;
const MARKET_CLOSE_HOUR = 15;
const MARKET_CLOSE_MIN = 30;

// ---- Time-of-day classification ------------------------------------------

/**
 * Classify a timestamp into a market session bucket.
 * Uses IST (UTC+5:30) for NSE trading hours.
 *
 * @param {string|Date} ts — ISO-8601 timestamp
 * @returns {string} "pre_market" | "morning" | "midday" | "afternoon" | "post_market"
 */
export function classifyTimeOfDay(ts) {
  const d = typeof ts === "string" ? new Date(ts) : ts;
  if (!d || !Number.isFinite(d.getTime())) return "unknown";

  // Convert to IST (UTC+5:30)
  const istMs = d.getTime() + (5.5 * 60 * 60 * 1000);
  const istDate = new Date(istMs);
  const hour = istDate.getUTCHours();
  const min = istDate.getUTCMinutes();
  const timeMin = hour * 60 + min;

  const openMin = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN;  // 555
  const midStart = 11 * 60;  // 660
  const midEnd = 13 * 60;    // 780
  const closeMin = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MIN;  // 930

  if (timeMin < openMin) return "pre_market";
  if (timeMin < midStart) return "morning";
  if (timeMin < midEnd) return "midday";
  if (timeMin <= closeMin) return "afternoon";
  return "post_market";
}

// ---- Forward outcome computation ------------------------------------------

/**
 * Compute a CandleSummary from reference price and an array of forward candles.
 *
 * @param {number} referenceClose — price at observation time
 * @param {Array} candles — forward candles (chronological, after reference)
 * @returns {object|null} CandleSummary or null if no candles
 */
export function computeCandleSummary(referenceClose, candles) {
  if (!Number.isFinite(referenceClose) || referenceClose <= 0) return null;
  if (!Array.isArray(candles) || candles.length === 0) return null;

  let high = -Infinity;
  let low = Infinity;
  const returns = [];
  let lastClose = referenceClose;

  for (const c of candles) {
    const h = c.high ?? c.close;
    const l = c.low ?? c.close;
    const cl = c.close;

    if (Number.isFinite(h) && h > high) high = h;
    if (Number.isFinite(l) && l < low) low = l;
    if (Number.isFinite(cl)) {
      returns.push((cl - lastClose) / lastClose);
      lastClose = cl;
    }
  }

  if (!Number.isFinite(high) || !Number.isFinite(low)) return null;

  const finalClose = lastClose;
  const direction = finalClose > referenceClose ? 1 : finalClose < referenceClose ? -1 : 0;
  const returnPct = (finalClose - referenceClose) / referenceClose;

  // MFE/MAE: max excursion in direction of final move vs against
  let maxFavorableExcursion = 0;
  let maxAdverseExcursion = 0;
  let runningHigh = referenceClose;
  let runningLow = referenceClose;

  for (const c of candles) {
    const h = c.high ?? c.close;
    const l = c.low ?? c.close;
    if (Number.isFinite(h) && h > runningHigh) runningHigh = h;
    if (Number.isFinite(l) && l < runningLow) runningLow = l;

    if (direction >= 0) {
      // Up or flat: favorable = high, adverse = low
      const fav = (runningHigh - referenceClose) / referenceClose;
      const adv = (referenceClose - runningLow) / referenceClose;
      if (fav > maxFavorableExcursion) maxFavorableExcursion = fav;
      if (adv > maxAdverseExcursion) maxAdverseExcursion = adv;
    } else {
      // Down: favorable = low, adverse = high
      const fav = (referenceClose - runningLow) / referenceClose;
      const adv = (runningHigh - referenceClose) / referenceClose;
      if (fav > maxFavorableExcursion) maxFavorableExcursion = fav;
      if (adv > maxAdverseExcursion) maxAdverseExcursion = adv;
    }
  }

  // Realized volatility: stddev of per-candle returns
  const realizedVolatility = _stddev(returns);

  return {
    return: returnPct,
    maxFavorableExcursion,
    maxAdverseExcursion,
    realizedVolatility,
    high,
    low,
    highExcursion: (high - referenceClose) / referenceClose,
    lowExcursion: (low - referenceClose) / referenceClose,
    direction,
  };
}

/**
 * Compute all forward outcomes for an observation.
 *
 * @param {number} referenceClose — price at observation time
 * @param {Array} allCandles — ALL candles in chronological order
 * @param {number} referenceIndex — index of the reference candle in allCandles
 * @returns {object} ForwardOutcomes keyed by horizon
 */
export function computeForwardOutcomes(referenceClose, allCandles, referenceIndex) {
  if (!Number.isFinite(referenceClose) || referenceClose <= 0) return {};
  if (!Array.isArray(allCandles)) return {};

  const outcomes = {};
  for (const h of HORIZONS) {
    const forwardCandles = allCandles.slice(referenceIndex + 1, referenceIndex + 1 + h);
    outcomes[`candles${h}`] = computeCandleSummary(referenceClose, forwardCandles);
  }
  return outcomes;
}

// ---- Baseline price features ---------------------------------------------

/**
 * Compute price-only baseline features from candles available at or before
 * the reference candle.  Uses ONLY candles[0..candleIndex] — never future candles.
 *
 * @param {number} referenceClose — spot price at observation time
 * @param {Array} allCandles — all candles in chronological order
 * @param {number} referenceIndex — index of the reference candle
 * @param {number} lookback — how many candles before reference to use (default: 20)
 * @returns {object} baseline features
 */
function computeBaselineFeatures(referenceClose, allCandles, referenceIndex, lookback = 20) {
  if (!Number.isFinite(referenceClose) || referenceClose <= 0) return {};
  if (!Array.isArray(allCandles) || referenceIndex < 0) return {};

  // Lookback window: candles strictly before reference (indices 0..referenceIndex-1)
  const lookbackStart = Math.max(0, referenceIndex - lookback);
  const lookbackCandles = allCandles.slice(lookbackStart, referenceIndex);

  // Reference candle itself
  const refCandle = allCandles[referenceIndex];
  if (!refCandle) return {};

  const result = {};

  // previousReturn: return from previous candle close to reference close
  if (lookbackCandles.length > 0) {
    const prevClose = lookbackCandles[lookbackCandles.length - 1].close;
    if (Number.isFinite(prevClose) && prevClose > 0) {
      result.previousReturn = (referenceClose - prevClose) / prevClose;
    }
  }

  // realizedVolatility: stddev of per-candle returns in lookback window
  const returns = [];
  for (let i = 1; i < lookbackCandles.length; i++) {
    const prev = lookbackCandles[i - 1].close;
    const curr = lookbackCandles[i].close;
    if (Number.isFinite(prev) && prev > 0 && Number.isFinite(curr)) {
      returns.push((curr - prev) / prev);
    }
  }
  if (returns.length >= 2) {
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
    result.realizedVolatility = Math.sqrt(variance);
  }

  // intradayRange: (high - low) / close of reference candle
  if (Number.isFinite(refCandle.high) && Number.isFinite(refCandle.low) &&
      Number.isFinite(refCandle.close) && refCandle.close > 0) {
    result.intradayRange = (refCandle.high - refCandle.low) / refCandle.close;
  }

  // momentum: return over the lookback window
  if (lookbackCandles.length > 0) {
    const oldestClose = lookbackCandles[0].close;
    if (Number.isFinite(oldestClose) && oldestClose > 0) {
      result.momentum = (referenceClose - oldestClose) / oldestClose;
    }
  }

  // distFromHigh: distance from lookback high
  const lookbackHighs = lookbackCandles.map(c => c.high).filter(v => Number.isFinite(v));
  if (lookbackHighs.length > 0) {
    const maxHigh = Math.max(...lookbackHighs);
    if (maxHigh > 0) {
      result.distFromHigh = (referenceClose - maxHigh) / maxHigh;
    }
  }

  // distFromLow: distance from lookback low
  const lookbackLows = lookbackCandles.map(c => c.low).filter(v => Number.isFinite(v));
  if (lookbackLows.length > 0) {
    const minLow = Math.min(...lookbackLows);
    if (minLow > 0) {
      result.distFromLow = (referenceClose - minLow) / minLow;
    }
  }

  return result;
}

// ---- Observation builder --------------------------------------------------

/**
 * Build a ResearchObservation from a GEX snapshot and candle context.
 *
 * @param {object} snapshot — GEX snapshot (Phase 7.3/7.5 schema)
 * @param {object} options
 * @param {Array} options.allCandles — all candles in chronological order
 * @param {number} options.candleIndex — index of the snapshot's reference candle
 * @param {object|null} options.analytics — output of computeGexAnalytics (optional enrichment)
 * @param {object|null} options.sweepResult — output of spotSweep (optional enrichment)
 * @param {number} options.lookbackCandles — candles before reference for baselines (default: 20)
 * @returns {object|null} ResearchObservation or null if data is insufficient
 */
export function buildResearchObservation(snapshot, options = {}) {
  if (!snapshot) return null;

  const { allCandles = [], candleIndex = -1, analytics = null, sweepResult = null, lookbackCandles = 20 } = options;

  // Reference candle: the candle at or before capturedAt
  const refCandle = candleIndex >= 0 && candleIndex < allCandles.length
    ? allCandles[candleIndex]
    : null;

  const spot = snapshot.spot ?? refCandle?.close ?? null;
  if (!Number.isFinite(spot) || spot <= 0) return null;

  const capturedAt = snapshot.capturedAt ?? null;
  if (!capturedAt) return null;

  // GEX features (from snapshot — authoritative, no look-ahead)
  const netGex = snapshot.netGex ?? null;
  const callGex = snapshot.callGex ?? null;
  const putGex = snapshot.putGex ?? null;
  const normalizedNetGex = (netGex != null && Number.isFinite(netGex) && spot > 0)
    ? netGex / (spot * spot * 0.01)
    : null;

  // Analytics-enriched features (from pre-computed analytics — no look-ahead)
  const velocity = analytics?.timeSeries?.velocity?.velocity ?? null;
  const acceleration = analytics?.timeSeries?.acceleration?.acceleration ?? null;
  const volatility = analytics?.timeSeries?.volatility?.volatility ?? null;
  const gexPercentile = analytics?.percentiles?.gexPercentile?.absolutePercentile ?? null;
  const descriptiveZ = analytics?.percentiles?.gexPercentile?.descriptiveZ ?? null;
  const callGexShare = analytics?.current?.callGexShare ?? _computeCallGexShare(callGex, putGex);
  const concentrationTop3 = analytics?.concentration?.top3Pct ?? null;

  // DeltaGex (from decomposition if available)
  const deltaGex = analytics?.decomposition?.total ?? null;

  // Gamma flip (from sweep or analytics)
  const gammaFlipSpot = sweepResult?.gammaFlip?.primaryFlip?.crossingSpot
    ?? analytics?.flipDistance?.distance ?? null;
  const gammaFlipDistancePct = sweepResult?.gammaFlip?.distanceFromSpotPct
    ?? analytics?.flipDistance?.distancePct ?? null;
  const gammaFlipDirection = sweepResult?.gammaFlip?.primaryFlip?.direction
    ?? analytics?.flipDistance?.direction ?? null;

  // Gamma walls
  const callWallStrikes = sweepResult?.gammaWalls?.callWalls?.map(w => w.strike) ?? [];
  const putWallStrikes = sweepResult?.gammaWalls?.putWalls?.map(w => w.strike) ?? [];

  // Wall distances
  const callWallDistancePct = callWallStrikes.length > 0
    ? Math.abs(Math.min(...callWallStrikes) - spot) / spot * 100
    : null;
  const putWallDistancePct = putWallStrikes.length > 0
    ? Math.abs(Math.max(...putWallStrikes) - spot) / spot * 100
    : null;

  // Expiry context
  const expiry = snapshot.expiry ?? null;
  const dte = snapshot.dte ?? null;

  // Data quality
  const totalStrikes = snapshot.totalStrikeCount ?? 0;
  const validStrikes = snapshot.validStrikeCount ?? 0;
  const strikeCoverage = totalStrikes > 0 ? validStrikes / totalStrikes : null;

  // Time classification
  const dayOfWeek = capturedAt ? new Date(capturedAt).getUTCDay() : null;
  const isExpiryDay = expiry != null && capturedAt != null
    ? capturedAt.slice(0, 10) === expiry
    : false;

  // Baseline price features (only candles at or before capturedAt — no look-ahead)
  const baselines = (refCandle != null && candleIndex >= 0)
    ? computeBaselineFeatures(spot, allCandles, candleIndex, lookbackCandles)
    : {};

  // Forward outcomes
  const forward = (refCandle != null && candleIndex >= 0)
    ? computeForwardOutcomes(spot, allCandles, candleIndex)
    : {};

  return {
    // Identity
    capturedAt,

    // Market state
    spot,
    symbol: snapshot.symbol ?? snapshot.underlying ?? "NIFTY",

    // GEX features
    netGex,
    callGex,
    putGex,
    normalizedNetGex,
    deltaGex,
    velocity,
    acceleration,
    volatility,
    concentrationTop3,
    gexPercentile,
    descriptiveZ,
    callGexShare,

    // Gamma flip
    gammaFlipSpot,
    gammaFlipDistancePct,
    gammaFlipDirection,

    // Walls
    callWallStrikes,
    putWallStrikes,
    callWallDistancePct,
    putWallDistancePct,

    // Expiry context
    expiry,
    dte,

    // Data quality
    strikeCoverage,
    freshnessMs: null, // filled in by caller if needed
    methodologyVersion: snapshot.methodologyMetadata?.gexVersion ?? snapshot.methodology ?? null,
    schemaVersion: snapshot.schemaVersion ?? null,

    // Context
    timeOfDay: classifyTimeOfDay(capturedAt),
    dayOfWeek,
    isExpiryDay,

    // Baseline price features
    previousReturn: baselines.previousReturn ?? null,
    realizedVolatility: baselines.realizedVolatility ?? null,
    intradayRange: baselines.intradayRange ?? null,
    momentum: baselines.momentum ?? null,
    distFromHigh: baselines.distFromHigh ?? null,
    distFromLow: baselines.distFromLow ?? null,

    // Forward outcomes
    forward,
  };
}

// ---- Dataset builder -----------------------------------------------------

/**
 * Build a complete research dataset from GEX snapshots and candles.
 *
 * @param {Array} snapshots — GEX snapshots (chronological, oldest-first)
 * @param {Array} candles — NIFTY candles (chronological, oldest-first)
 * @param {object} options
 * @param {Array|null} options.analytics — pre-computed analytics per snapshot (optional)
 * @returns {Array} ResearchObservations with forward outcomes
 */
export function buildResearchDataset(snapshots, candles, options = {}) {
  if (!Array.isArray(snapshots) || !Array.isArray(candles)) return [];

  const { analytics = null } = options;
  const observations = [];

  for (let i = 0; i < snapshots.length; i++) {
    const snap = snapshots[i];
    const capturedAt = snap.capturedAt;
    if (!capturedAt) continue;

    const snapTime = new Date(capturedAt).getTime();
    if (!Number.isFinite(snapTime)) continue;

    // Find the reference candle: last candle whose openTime <= capturedAt
    let candleIdx = -1;
    for (let j = candles.length - 1; j >= 0; j--) {
      const ct = new Date(candles[j].openTime).getTime();
      if (Number.isFinite(ct) && ct <= snapTime) {
        candleIdx = j;
        break;
      }
    }

    const snapAnalytics = analytics?.[i] ?? null;

    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: candleIdx,
      analytics: snapAnalytics,
    });

    if (obs) {
      // Check forward data availability
      const hasForward = HORIZONS.every(
        h => obs.forward[`candles${h}`] != null
      );
      obs._hasCompleteForward = hasForward;
      observations.push(obs);
    }
  }

  return observations;
}

// ---- Internal helpers ----------------------------------------------------

function _computeCallGexShare(callGex, putGex) {
  if (callGex == null || putGex == null) return null;
  if (!Number.isFinite(callGex) || !Number.isFinite(putGex)) return null;
  const total = Math.abs(callGex) + Math.abs(putGex);
  if (total === 0) return null;
  return (Math.abs(callGex) / total) * 100;
}

function _stddev(values) {
  if (!Array.isArray(values) || values.length < 2) return null;
  const clean = values.filter(v => Number.isFinite(v));
  if (clean.length < 2) return null;
  const mean = clean.reduce((a, b) => a + b, 0) / clean.length;
  const variance = clean.reduce((a, b) => a + (b - mean) ** 2, 0) / clean.length;
  return Math.sqrt(variance);
}
