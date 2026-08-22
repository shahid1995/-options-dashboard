/**
 * GEX Phase 7.4a — Rolling ΔGEX Analytics (Time-Series Layer)
 *
 * Provides rolling statistical context over the Phase 7.3 snapshot history:
 *   1. NetGexSma — SMA of cumulative Net GEX values (smoothed level)
 *   2. DeltaGexSma — SMA of sequential ΔGEX values (smoothed change rate)
 *   3. Velocity — ΔGEX per unit time (actual timestamps, not assumed intervals)
 *   4. Acceleration — rate of change of velocity
 *   5. ΔGEX Volatility — stddev of sequential ΔGEX values
 *
 * MATHEMATICAL CONTRACT:
 *
 *   All metrics consume broker-gamma-derived values from Phase 7.3 snapshots.
 *   BS model gamma is NEVER used in this module.
 *
 *   NetGexSma_i  = (1/w) × Σ NetGex(t_j)          for j ∈ [i−w+1, i]
 *   DeltaGexSma_i = (1/w) × Σ ΔGEX_j              for j ∈ [i−w+1, i]
 *   velocity_i     = ΔGEX_i / Δt_i                  [GEX units per second]
 *   acceleration_i = (v_i − v_{i−1}) / Δt_i        [GEX units per second²]
 *   volatility_i   = stddev({ΔGEX_j})               over window
 *
 *   where ΔGEX_i = NetGex(t_i) − NetGex(t_{i−1})   [Phase 7.3 computeDeltaGex]
 *         Δt_i   = (capturedAt_i − capturedAt_{i−1}) / 1000  [seconds]
 *
 * IMPORTANT: Velocity and acceleration use ACTUAL capturedAt timestamps
 * from snapshots. They do NOT assume fixed intervals. Two consecutive
 * snapshots 300 seconds apart and another pair 600 seconds apart will
 * produce correctly scaled derivatives.
 *
 * INTERPRETATION:
 *   These are DESCRIPTIVE STATISTICS of GEX change patterns.
 *   They do NOT predict market direction.
 *   Velocity/acceleration are not validated trading signals.
 *
 * Sign convention (inherited from Phase 7.1):
 *   Call GEX = + raw GEX    Put GEX = − raw GEX
 */

import { rollingMean, rollingStdDev } from "./statistics.js";

// ---- Constants ---------------------------------------------------------------

/** Default window size for NetGexSma (number of snapshots) */
export const DEFAULT_NET_GEX_SMA_WINDOW = 10;

/** Default window size for DeltaGexSma (number of ΔGEX observations) */
export const DEFAULT_DELTA_GEX_SMA_WINDOW = 10;

/** Default window size for velocity rolling average */
export const DEFAULT_VELOCITY_WINDOW = 6;

/** Default window size for ΔGEX volatility (stddev) */
export const DEFAULT_VOLATILITY_WINDOW = 10;

/** Minimum Δt in seconds to compute velocity (avoid division by near-zero) */
export const MIN_VELOCITY_DT_SEC = 1;

// ---- Snapshot helpers --------------------------------------------------------

/**
 * Extract NetGEX value from a snapshot, returning null if unavailable.
 * @param {object} snapshot
 * @returns {number|null}
 */
function netGexOf(snapshot) {
  if (!snapshot) return null;
  const v = snapshot.netGex;
  return v != null && Number.isFinite(v) ? v : null;
}

/**
 * Extract capturedAt as milliseconds from a snapshot.
 * @param {object} snapshot
 * @returns {number|null}
 */
function timestampMsOf(snapshot) {
  if (!snapshot || !snapshot.capturedAt) return null;
  const ms = new Date(snapshot.capturedAt).getTime();
  return Number.isFinite(ms) ? ms : null;
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

// ---- NetGexSma ---------------------------------------------------------------

/**
 * Compute rolling Simple Moving Average of cumulative Net GEX values.
 *
 * Formula: NetGexSma_i = (1/window) × Σ NetGex(t_j) for j ∈ [i−window+1, i]
 *
 * Uses broker-gamma-derived netGex from Phase 7.3 snapshots.
 * Averages the LEVEL, not the change.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {number} [window=DEFAULT_NET_GEX_SMA_WINDOW]
 * @returns {{ sma: number|null, history: Array, windowSize: number, availablePoints: number, status: string }}
 */
export function computeNetGexSma(source, window = DEFAULT_NET_GEX_SMA_WINDOW) {
  const snapshots = toArray(source);
  if (snapshots.length === 0 || window < 1) {
    return { sma: null, history: [], windowSize: window, availablePoints: 0, status: "unavailable" };
  }

  const values = snapshots.map(netGexOf);
  const history = [];

  for (let i = 0; i < values.length; i++) {
    const start = Math.max(0, i - window + 1);
    const windowValues = values.slice(start, i + 1);
    const sma = rollingMean(windowValues);
    history.push({
      timestamp: snapshots[i].capturedAt ?? null,
      value: sma,
      pointsUsed: windowValues.filter((v) => v != null).length,
    });
  }

  const last = history[history.length - 1];
  const availablePoints = last?.pointsUsed ?? 0;

  let status;
  if (availablePoints >= window) {
    status = "available";
  } else if (availablePoints > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    sma: last?.value ?? null,
    history,
    windowSize: window,
    availablePoints,
    status,
  };
}

// ---- DeltaGexSma -------------------------------------------------------------

/**
 * Compute rolling SMA of sequential ΔGEX values.
 *
 * Formula: DeltaGexSma_i = (1/window) × Σ ΔGEX_j for j ∈ [i−window+1, i]
 *
 * Where ΔGEX_j = NetGex(t_j) − NetGex(t_{j−1}).
 *
 * DIFFERENT FROM NetGexSma:
 *   NetGexSma smooths the cumulative GEX level.
 *   DeltaGexSma smooths the sequential GEX change.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {number} [window=DEFAULT_DELTA_GEX_SMA_WINDOW]
 * @returns {{ sma: number|null, history: Array, windowSize: number, availablePoints: number, status: string }}
 */
export function computeDeltaGexSma(source, window = DEFAULT_DELTA_GEX_SMA_WINDOW) {
  const snapshots = toArray(source);
  if (snapshots.length < 2 || window < 1) {
    return { sma: null, history: [], windowSize: window, availablePoints: 0, status: "unavailable" };
  }

  // Compute sequential ΔGEX values
  const deltas = [];
  const deltaTimestamps = [];
  for (let i = 1; i < snapshots.length; i++) {
    const prev = netGexOf(snapshots[i - 1]);
    const curr = netGexOf(snapshots[i]);
    if (prev != null && curr != null) {
      deltas.push(curr - prev);
      deltaTimestamps.push(snapshots[i].capturedAt ?? null);
    } else {
      deltas.push(null);
      deltaTimestamps.push(snapshots[i].capturedAt ?? null);
    }
  }

  // Compute rolling SMA over ΔGEX values
  const history = [];
  for (let i = 0; i < deltas.length; i++) {
    const start = Math.max(0, i - window + 1);
    const windowValues = deltas.slice(start, i + 1);
    const sma = rollingMean(windowValues);
    history.push({
      timestamp: deltaTimestamps[i],
      value: sma,
      pointsUsed: windowValues.filter((v) => v != null).length,
    });
  }

  const last = history[history.length - 1];
  const availablePoints = last?.pointsUsed ?? 0;

  let status;
  if (availablePoints >= window) {
    status = "available";
  } else if (availablePoints > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    sma: last?.value ?? null,
    history,
    windowSize: window,
    availablePoints,
    status,
  };
}

// ---- Velocity ----------------------------------------------------------------

/**
 * Compute velocity (rate of GEX change per unit time).
 *
 * Formula: velocity_i = ΔGEX_i / Δt_i
 *   where ΔGEX_i = NetGex(t_i) − NetGex(t_{i−1})
 *         Δt_i   = (capturedAt_i − capturedAt_{i−1}) / 1000  [seconds]
 *
 * Uses ACTUAL capturedAt timestamps — does NOT assume fixed intervals.
 * Unit: GEX units per second.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {number} [window=DEFAULT_VELOCITY_WINDOW] — rolling average window for velocity
 * @returns {{ velocity: number|null, history: Array, status: string }}
 */
export function computeVelocity(source, window = DEFAULT_VELOCITY_WINDOW) {
  const snapshots = toArray(source);
  if (snapshots.length < 2) {
    return { velocity: null, history: [], status: "unavailable" };
  }

  const history = [];

  for (let i = 1; i < snapshots.length; i++) {
    const prevGex = netGexOf(snapshots[i - 1]);
    const currGex = netGexOf(snapshots[i]);
    const prevTs = timestampMsOf(snapshots[i - 1]);
    const currTs = timestampMsOf(snapshots[i]);

    let velocity = null;
    let deltaTimeSec = null;

    if (prevGex != null && currGex != null && prevTs != null && currTs != null) {
      const deltaMs = currTs - prevTs;
      deltaTimeSec = deltaMs / 1000;

      if (deltaTimeSec >= MIN_VELOCITY_DT_SEC) {
        velocity = (currGex - prevGex) / deltaTimeSec;
      }
      // If deltaTimeSec < MIN_VELOCITY_DT_SEC or negative, velocity = null
    }

    history.push({
      timestamp: snapshots[i].capturedAt ?? null,
      value: velocity,
      deltaTimeSec,
      deltaGex: prevGex != null && currGex != null ? currGex - prevGex : null,
    });
  }

  // Compute rolling average of velocity for the current value
  const recentVelocities = history.slice(-window).map((h) => h.value);
  const smoothedVelocity = rollingMean(recentVelocities);

  const availableCount = recentVelocities.filter((v) => v != null).length;

  let status;
  if (availableCount >= Math.min(window, history.length)) {
    status = "available";
  } else if (availableCount > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    velocity: smoothedVelocity,
    history,
    windowSize: window,
    availablePoints: availableCount,
    status,
  };
}

// ---- Acceleration ------------------------------------------------------------

/**
 * Compute acceleration (rate of change of velocity).
 *
 * Formula: acceleration_i = (velocity_i − velocity_{i−1}) / Δt_i
 *   where velocity is computed with the given window
 *         Δt_i = (capturedAt_i − capturedAt_{i−1}) / 1000  [seconds]
 *
 * Uses ACTUAL capturedAt timestamps.
 * Unit: GEX units per second².
 *
 * Requires at least 3 snapshots (2 velocity points).
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {number} [velocityWindow=DEFAULT_VELOCITY_WINDOW]
 * @returns {{ acceleration: number|null, history: Array, status: string }}
 */
export function computeAcceleration(source, velocityWindow = DEFAULT_VELOCITY_WINDOW) {
  const snapshots = toArray(source);
  if (snapshots.length < 3) {
    return { acceleration: null, history: [], status: "unavailable" };
  }

  // First compute velocity at each point
  const velResult = computeVelocity(snapshots, velocityWindow);
  const velHistory = velResult.history;

  if (velHistory.length < 2) {
    return { acceleration: null, history: [], status: "unavailable" };
  }

  // velHistory[j] represents velocity between snapshot (j) and snapshot (j+1)
  // velHistory[j].timestamp === snapshots[j+1].capturedAt
  // For acceleration at index i (in velHistory), compare velHistory[i-1] and velHistory[i]:
  //   prev timestamp = snapshots[i].capturedAt
  //   curr timestamp = snapshots[i+1].capturedAt
  const history = [];

  for (let i = 1; i < velHistory.length; i++) {
    const prevVel = velHistory[i - 1].value;
    const currVel = velHistory[i].value;
    const prevTs = timestampMsOf(snapshots[i]);
    const currTs = timestampMsOf(snapshots[i + 1]);

    let accel = null;
    let deltaTimeSec = null;

    if (prevVel != null && currVel != null && prevTs != null && currTs != null) {
      const deltaMs = currTs - prevTs;
      deltaTimeSec = deltaMs / 1000;

      if (deltaTimeSec >= MIN_VELOCITY_DT_SEC) {
        accel = (currVel - prevVel) / deltaTimeSec;
      }
    }

    history.push({
      timestamp: velHistory[i].timestamp ?? null,
      value: accel,
      deltaTimeSec,
    });
  }

  // Current acceleration (most recent)
  const recentAccels = history.slice(-velocityWindow).map((h) => h.value);
  const smoothedAccel = rollingMean(recentAccels);

  const availableCount = recentAccels.filter((v) => v != null).length;

  let status;
  if (availableCount >= Math.min(velocityWindow, history.length)) {
    status = "available";
  } else if (availableCount > 0) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    acceleration: smoothedAccel,
    history,
    windowSize: velocityWindow,
    availablePoints: availableCount,
    status,
  };
}

// ---- ΔGEX Volatility ---------------------------------------------------------

/**
 * Compute ΔGEX volatility (rolling standard deviation of sequential ΔGEX).
 *
 * Formula: ΔGEXVolatility_i = stddev({ΔGEX_j}) for j ∈ [i−window+1, i]
 *
 * Uses population stddev from statistics.js.
 * Measures how VARIABLE the GEX changes are — NOT price volatility.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {number} [window=DEFAULT_VOLATILITY_WINDOW]
 * @returns {{ volatility: number|null, history: Array, windowSize: number, status: string }}
 */
export function computeDeltaGexVolatility(source, window = DEFAULT_VOLATILITY_WINDOW) {
  const snapshots = toArray(source);
  if (snapshots.length < 2 || window < 2) {
    return { volatility: null, history: [], windowSize: window, status: "unavailable" };
  }

  // Compute sequential ΔGEX values
  const deltas = [];
  for (let i = 1; i < snapshots.length; i++) {
    const prev = netGexOf(snapshots[i - 1]);
    const curr = netGexOf(snapshots[i]);
    if (prev != null && curr != null) {
      deltas.push(curr - prev);
    } else {
      deltas.push(null);
    }
  }

  const history = [];
  for (let i = 0; i < deltas.length; i++) {
    const start = Math.max(0, i - window + 1);
    const windowValues = deltas.slice(start, i + 1);
    const stddev = rollingStdDev(windowValues);
    history.push({
      timestamp: snapshots[i + 1].capturedAt ?? null,
      value: stddev,
      pointsUsed: windowValues.filter((v) => v != null).length,
    });
  }

  const last = history[history.length - 1];
  const availablePoints = last?.pointsUsed ?? 0;

  let status;
  if (availablePoints >= window) {
    status = "available";
  } else if (availablePoints >= 2) {
    status = "partial";
  } else {
    status = "unavailable";
  }

  return {
    volatility: last?.value ?? null,
    history,
    windowSize: window,
    availablePoints,
    status,
  };
}

// ---- Convenience: all time-series stats --------------------------------------

/**
 * Compute all rolling analytics from a snapshot array.
 *
 * @param {GexRingBuffer|Array} source — snapshots (chronological)
 * @param {object} [config]
 * @param {number} [config.velocityWindow]
 * @param {number} [config.volatilityWindow]
 * @param {number} [config.netGexSmaWindow]
 * @param {number} [config.deltaGexSmaWindow]
 * @returns {object} aggregated time-series statistics
 */
export function computeTimeSeriesStats(source, config = {}) {
  const {
    velocityWindow = DEFAULT_VELOCITY_WINDOW,
    volatilityWindow = DEFAULT_VOLATILITY_WINDOW,
    netGexSmaWindow = DEFAULT_NET_GEX_SMA_WINDOW,
    deltaGexSmaWindow = DEFAULT_DELTA_GEX_SMA_WINDOW,
  } = config;

  return {
    netGexSma: computeNetGexSma(source, netGexSmaWindow),
    deltaGexSma: computeDeltaGexSma(source, deltaGexSmaWindow),
    velocity: computeVelocity(source, velocityWindow),
    acceleration: computeAcceleration(source, velocityWindow),
    volatility: computeDeltaGexVolatility(source, volatilityWindow),
  };
}
