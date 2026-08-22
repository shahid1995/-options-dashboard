/**
 * GEX Phase 7.4c — GEX Profile Label (Structural Classification)
 *
 * Classifies the current GEX geometry into structural labels.
 *
 * IMPORTANT: The GEX Profile Label is a TRANSPARENT STRUCTURAL DESCRIPTION
 * of the current GEX geometry. It is NOT a market regime in the traditional
 * sense (e.g., "risk-on" or "risk-off"). It classifies the shape and structure
 * of the GEX profile, not the market direction.
 *
 * Labels are arrays — multiple can be active simultaneously.
 * Example: ["POSITIVE_DOMINANT", "HIGH_CONCENTRATION", "FLIP_ADJACENT"]
 *
 * ALL thresholds are configurable. Defaults are labeled EXPERIMENTAL_DEFAULT.
 * They have NOT been empirically validated against market outcomes.
 *
 * Gamma source: broker (snapshots contain broker-gamma-derived GEX).
 * BS model gamma is NOT used in this module.
 *
 * INTERPRETATION:
 *   These labels describe GEX geometry, not market prediction.
 *   They do NOT generate BUY/SELL signals.
 *   They are explicitly experimental.
 *
 * Sign convention (inherited from Phase 7.1):
 *   Call GEX = + raw GEX    Put GEX = − raw GEX
 */

import { computeConcentration } from "./gexHistory.js";

// ---- Constants & Defaults ----------------------------------------------------

/**
 * DEFAULT PROFILE CONFIGURATION
 *
 * ALL thresholds are EXPERIMENTAL_DEFAULT values.
 * They should be adjusted after empirical validation (Phase 7.7).
 * These are starting points for structurally labeling the GEX profile.
 */
export const DEFAULT_PROFILE_CONFIG = {
  /**
   * Net GEX thresholds (as fraction of |spot² × 0.01| for normalization).
   * normalizedNetGex = netGex / (spot² × 0.01)
   *
   * Values above netGexStrongThreshold → POSITIVE_DOMINANT or NEGATIVE_DOMINANT
   * Values between weak and strong → POSITIVE_MODERATE or NEGATIVE_MODERATE
   * Values below weak → BALANCED
   */
  netGexStrongThreshold: 0.5,   // EXPERIMENTAL_DEFAULT
  netGexWeakThreshold: 0.1,     // EXPERIMENTAL_DEFAULT

  /**
   * Flip distance thresholds (as % of spot).
   * flipDistancePct = |spot − gammaFlip| / spot × 100
   *
   * Within flipNearThresholdPct → FLIP_ADJACENT
   * Beyond flipFarThresholdPct → FLIP_DISTANT
   */
  flipNearThresholdPct: 1.0,    // EXPERIMENTAL_DEFAULT
  flipFarThresholdPct: 5.0,     // EXPERIMENTAL_DEFAULT

  /**
   * Concentration thresholds (top-3 share %).
   * From computeConcentration().top3Pct
   *
   * Above highConcentrationPct → HIGH_CONCENTRATION
   * Below lowConcentrationPct → DIFFUSE
   */
  highConcentrationPct: 70,     // EXPERIMENTAL_DEFAULT
  lowConcentrationPct: 40,      // EXPERIMENTAL_DEFAULT
};

/** Confidence label — always experimental in Phase 7.4 */
export const PROFILE_CONFIDENCE = "experimental";

// ---- Profile Labels ----------------------------------------------------------

export const LABEL = Object.freeze({
  POSITIVE_DOMINANT: "POSITIVE_DOMINANT",
  POSITIVE_MODERATE: "POSITIVE_MODERATE",
  BALANCED: "BALANCED",
  NEGATIVE_MODERATE: "NEGATIVE_MODERATE",
  NEGATIVE_DOMINANT: "NEGATIVE_DOMINANT",
  HIGH_CONCENTRATION: "HIGH_CONCENTRATION",
  DIFFUSE: "DIFFUSE",
  FLIP_ADJACENT: "FLIP_ADJACENT",
  FLIP_DISTANT: "FLIP_DISTANT",
  UNAVAILABLE: "UNAVAILABLE",
});

// ---- Snapshot helpers --------------------------------------------------------

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

/**
 * Extract NetGEX value from a snapshot.
 */
function netGexOf(snapshot) {
  if (!snapshot) return null;
  const v = snapshot.netGex;
  return v != null && Number.isFinite(v) ? v : null;
}

/**
 * Compute normalized Net GEX: netGex / (spot² × 0.01).
 * Removes the spot² scaling factor for cross-spot comparability.
 */
function normalizedNetGex(netGex, spot) {
  if (netGex == null || spot == null || !Number.isFinite(spot) || spot <= 0) return null;
  const denom = spot * spot * 0.01;
  if (denom <= 0) return null;
  return netGex / denom;
}

// ---- Main Classification Function --------------------------------------------

/**
 * Classify the current GEX profile into structural labels.
 *
 * @param {GexRingBuffer|Array} source — recent snapshots (for rolling context)
 * @param {object} [configOverride] — override DEFAULT_PROFILE_CONFIG thresholds
 * @param {object} [context] — optional external context
 * @param {number|null} [context.flipDistancePct] — distance from gamma flip as % of spot
 * @param {string|null} [context.flipDirection] — "above" | "below"
 * @param {string|null} [context.deltaGexDirection] — "increasing" | "decreasing" | "stable"
 * @returns {object} classification result
 */
export function classifyGexProfile(source, configOverride = {}, context = {}) {
  const snapshots = toArray(source);
  const config = { ...DEFAULT_PROFILE_CONFIG, ...configOverride };

  // Use the latest snapshot as the current state
  const latest = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;

  if (!latest) {
    return unavailableResult("No snapshots available");
  }

  const netGex = netGexOf(latest);
  const spot = latest.spot;
  const normNetGex = normalizedNetGex(netGex, spot);

  // Compute concentration from latest strike data
  const concentration = computeConcentration(latest.strikeData || []);

  // Extract flip distance from context
  const flipDistancePct = context.flipDistancePct ?? null;

  // Extract delta GEX direction from context
  const deltaGexDirection = context.deltaGexDirection ?? null;

  // Extract call GEX share
  const callGex = latest.callGex;
  const putGex = latest.putGex;
  let callGexShare = null;
  if (callGex != null && putGex != null && Number.isFinite(callGex) && Number.isFinite(putGex)) {
    const totalAbs = Math.abs(callGex) + Math.abs(putGex);
    if (totalAbs > 0) {
      callGexShare = (Math.abs(callGex) / totalAbs) * 100;
    }
  }

  // ---- Classify labels ----
  const labels = [];

  if (normNetGex == null) {
    labels.push(LABEL.UNAVAILABLE);
  } else {
    // Net GEX magnitude classification
    if (normNetGex > config.netGexStrongThreshold) {
      labels.push(LABEL.POSITIVE_DOMINANT);
    } else if (normNetGex > config.netGexWeakThreshold) {
      labels.push(LABEL.POSITIVE_MODERATE);
    } else if (normNetGex < -config.netGexStrongThreshold) {
      labels.push(LABEL.NEGATIVE_DOMINANT);
    } else if (normNetGex < -config.netGexWeakThreshold) {
      labels.push(LABEL.NEGATIVE_MODERATE);
    } else {
      labels.push(LABEL.BALANCED);
    }

    // Concentration classification
    if (concentration.top3Pct != null) {
      if (concentration.top3Pct > config.highConcentrationPct) {
        labels.push(LABEL.HIGH_CONCENTRATION);
      } else if (concentration.top3Pct < config.lowConcentrationPct) {
        labels.push(LABEL.DIFFUSE);
      }
    }

    // Flip distance classification
    if (flipDistancePct != null && Number.isFinite(flipDistancePct)) {
      if (flipDistancePct <= config.flipNearThresholdPct) {
        labels.push(LABEL.FLIP_ADJACENT);
      } else if (flipDistancePct >= config.flipFarThresholdPct) {
        labels.push(LABEL.FLIP_DISTANT);
      }
    }
  }

  // Determine overall status
  const hasData = netGex != null;
  const status = hasData ? "available" : "unavailable";

  return {
    labels,
    netGex,
    normalizedNetGex: normNetGex,
    concentration: {
      top3Pct: concentration.top3Pct,
      top5Pct: concentration.top5Pct,
      top10Pct: concentration.top10Pct,
      totalAbsoluteGex: concentration.totalAbsoluteGex,
      strikeCount: concentration.strikeCount,
    },
    flipDistancePct,
    deltaGexDirection,
    callGexShare,
    confidence: PROFILE_CONFIDENCE,
    configUsed: config,
    metadata: {
      snapshotCount: snapshots.length,
      latestTimestamp: latest.capturedAt ?? null,
      methodology: latest.methodologyMetadata?.gexVersion ?? null,
    },
    status,
  };
}

// ---- Helpers -----------------------------------------------------------------

function unavailableResult(reason) {
  return {
    labels: [LABEL.UNAVAILABLE],
    netGex: null,
    normalizedNetGex: null,
    concentration: { top3Pct: null, top5Pct: null, top10Pct: null, totalAbsoluteGex: 0, strikeCount: 0 },
    flipDistancePct: null,
    deltaGexDirection: null,
    callGexShare: null,
    confidence: PROFILE_CONFIDENCE,
    configUsed: DEFAULT_PROFILE_CONFIG,
    metadata: { snapshotCount: 0, latestTimestamp: null, methodology: null },
    status: "unavailable",
    reason,
  };
}
