/**
 * GEX Phase 7.7 — Research Result & Feature Registry
 *
 * Machine-readable catalog of validated features, research output schema,
 * and status classification.
 */

// ---- Status constants ----------------------------------------------------

export const STATUS = Object.freeze({
  INSUFFICIENT_DATA: "INSUFFICIENT_DATA",
  NO_EVIDENCE: "NO_EVIDENCE",
  WEAK_ASSOCIATION: "WEAK_ASSOCIATION",
  PROMISING: "PROMISING",
  ROBUST_ASSOCIATION: "ROBUST_ASSOCIATION",
});

export const RESEARCH_VERSION = "gex_research_v1";

// ---- Research result builder ---------------------------------------------

/**
 * Build a standardized ResearchResult from test output.
 *
 * @param {object} params
 * @param {string} params.feature
 * @param {string|null} params.condition
 * @param {string} params.horizon
 * @param {number} params.sampleCount
 * @param {number|null} params.meanOutcome
 * @param {number|null} params.medianOutcome
 * @param {number|null} params.stdOutcome
 * @param {number|null} params.effectSize
 * @param {object|null} params.confidenceInterval
 * @param {number|null} params.pValue
 * @param {number|null} params.adjustedPValue
 * @param {number|null} params.baselineOutcome
 * @param {number|null} params.incrementalImprovement
 * @param {object|null} params.inSampleResult
 * @param {object|null} params.outOfSampleResult
 * @param {string} params.status
 * @param {string} params.methodology
 * @param {boolean} params.blockBootstrapUsed
 * @param {boolean} params.autocorrelationAdjusted
 * @param {boolean} params.multipleTestingCorrected
 * @returns {object} ResearchResult
 */
export function buildResearchResult(params) {
  return {
    researchVersion: RESEARCH_VERSION,
    feature: params.feature,
    condition: params.condition ?? null,
    horizon: params.horizon,
    sampleCount: params.sampleCount ?? 0,
    meanOutcome: params.meanOutcome ?? null,
    medianOutcome: params.medianOutcome ?? null,
    stdOutcome: params.stdOutcome ?? null,
    effectSize: params.effectSize ?? null,
    confidenceInterval: params.confidenceInterval ?? null,
    pValue: params.pValue ?? null,
    adjustedPValue: params.adjustedPValue ?? null,
    baselineOutcome: params.baselineOutcome ?? null,
    incrementalImprovement: params.incrementalImprovement ?? null,
    inSampleResult: params.inSampleResult ?? null,
    outOfSampleResult: params.outOfSampleResult ?? null,
    status: params.status ?? STATUS.INSUFFICIENT_DATA,
    methodology: params.methodology ?? "unknown",
    blockBootstrapUsed: params.blockBootstrapUsed ?? false,
    autocorrelationAdjusted: params.autocorrelationAdjusted ?? false,
    multipleTestingCorrected: params.multipleTestingCorrected ?? false,
    computedAt: new Date().toISOString(),
  };
}

// ---- Feature definitions -------------------------------------------------

/**
 * Canonical feature definitions with metadata.
 */
export const FEATURE_DEFINITIONS = [
  {
    name: "netGex",
    source: "gex",
    computation: "gamma * oi * spot^2 * 0.01",
    unit: "GEX units",
    description: "Total net gamma exposure across all strikes",
  },
  {
    name: "normalizedNetGex",
    source: "gex",
    computation: "netGex / (spot^2 * 0.01)",
    unit: "dimensionless",
    description: "Net GEX normalized by spot level",
  },
  {
    name: "deltaGex",
    source: "gex_history",
    computation: "netGex(t) - netGex(t-1)",
    unit: "GEX units",
    description: "Change in net GEX between snapshots",
  },
  {
    name: "velocity",
    source: "gex_timeseries",
    computation: "deltaGex / deltaTime",
    unit: "GEX/second",
    description: "Rate of GEX change",
  },
  {
    name: "acceleration",
    source: "gex_timeseries",
    computation: "deltaVelocity / deltaTime",
    unit: "GEX/second^2",
    description: "Rate of GEX velocity change",
  },
  {
    name: "volatility",
    source: "gex_timeseries",
    computation: "stddev(deltaGex, window)",
    unit: "GEX units",
    description: "Volatility of GEX changes",
  },
  {
    name: "concentrationTop3",
    source: "gex_concentration",
    computation: "sum(|gex| top 3 strikes) / sum(|gex| all strikes) * 100",
    unit: "percentage",
    description: "Top 3 strikes' share of total absolute GEX",
  },
  {
    name: "gexPercentile",
    source: "gex_concentration",
    computation: "percentileRank(netGex, history)",
    unit: "percentile (0-100)",
    description: "Percentile rank of current net GEX in history",
  },
  {
    name: "descriptiveZ",
    source: "gex_concentration",
    computation: "(netGex - mean) / stddev",
    unit: "z-score",
    description: "Standardized net GEX value",
  },
  {
    name: "callGexShare",
    source: "gex_concentration",
    computation: "|callGex| / (|callGex| + |putGex|) * 100",
    unit: "percentage",
    description: "Share of absolute GEX from calls",
  },
  {
    name: "gammaFlipDistancePct",
    source: "gex_phase72",
    computation: "|spot - gammaFlipSpot| / spot * 100",
    unit: "percentage",
    description: "Distance from spot to gamma flip level",
  },
  {
    name: "callWallDistancePct",
    source: "gex_phase72",
    computation: "|spot - nearestCallWall| / spot * 100",
    unit: "percentage",
    description: "Distance from spot to nearest call gamma wall",
  },
  {
    name: "putWallDistancePct",
    source: "gex_phase72",
    computation: "|spot - nearestPutWall| / spot * 100",
    unit: "percentage",
    description: "Distance from spot to nearest put gamma wall",
  },
  {
    name: "dte",
    source: "gex_history",
    computation: "timeToExpiry(valuationDate, expiry) * 365",
    unit: "days",
    description: "Days to expiry",
  },
];

// ---- Feature registry ----------------------------------------------------

/**
 * Build a feature registry from validation results.
 *
 * @param {Array} validationResults — array of validateFeature() outputs
 * @returns {object} versioned feature registry
 */
export function buildFeatureRegistry(validationResults) {
  const features = [];

  for (const result of validationResults) {
    const definition = FEATURE_DEFINITIONS.find(f => f.name === result.feature);
    features.push({
      name: result.feature,
      source: definition?.source ?? "unknown",
      computation: definition?.computation ?? "unknown",
      unit: definition?.unit ?? "unknown",
      description: definition?.description ?? "",
      validationStatus: result.status,
      validationDate: new Date().toISOString(),
      sampleCount: result.sampleCount,
      effectSize: result.inSample?.effectSize ?? null,
      oosConsistent: result.outOfSample?.directionConsistent ?? false,
      walkForwardPositive: (result.walkForward?.aggregate?.positiveWindows ?? 0) >
        (result.walkForward?.aggregate?.negativeWindows ?? 0),
      knownLimitations: _getLimitations(result),
      dataRequirements: {
        minObservations: 200,
        minHistoryWindow: 10,
      },
    });
  }

  return {
    version: RESEARCH_VERSION,
    generatedAt: new Date().toISOString(),
    featureCount: features.length,
    statusCounts: {
      [STATUS.INSUFFICIENT_DATA]: features.filter(f => f.validationStatus === STATUS.INSUFFICIENT_DATA).length,
      [STATUS.NO_EVIDENCE]: features.filter(f => f.validationStatus === STATUS.NO_EVIDENCE).length,
      [STATUS.WEAK_ASSOCIATION]: features.filter(f => f.validationStatus === STATUS.WEAK_ASSOCIATION).length,
      [STATUS.PROMISING]: features.filter(f => f.validationStatus === STATUS.PROMISING).length,
      [STATUS.ROBUST_ASSOCIATION]: features.filter(f => f.validationStatus === STATUS.ROBUST_ASSOCIATION).length,
    },
    features,
  };
}

// ---- Internal helpers ----------------------------------------------------

function _getLimitations(result) {
  const limitations = [];
  if (result.sampleCount < 500) limitations.push("Limited sample size");
  if (!result.outOfSample?.directionConsistent) limitations.push("OOS direction inconsistent");
  if (!result.walkForward?.aggregate?.positiveWindows) limitations.push("Walk-forward not consistently positive");
  if (result.status === STATUS.WEAK_ASSOCIATION) limitations.push("Weak statistical evidence");
  return limitations;
}
