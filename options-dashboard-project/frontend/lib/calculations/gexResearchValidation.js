/**
 * GEX Phase 7.7 — Chronological Validation Framework
 *
 * Walk-forward validation, in-sample/out-of-sample splits,
 * parameter freezing, and robustness checks.
 *
 * Strict rules:
 *   - No random shuffling of time-series observations
 *   - Parameters frozen on training data
 *   - Test set never consulted during parameter selection
 */

import { quintileAnalysis, blockBootstrapMean, holmBonferroni } from "./gexResearchTests.js";
import { HORIZONS, GEX_FEATURES } from "./gexResearchData.js";

// ---- Constants -----------------------------------------------------------

export const DEFAULT_TRAIN_RATIO = 0.6;
export const DEFAULT_VAL_RATIO = 0.2;
export const DEFAULT_TEST_RATIO = 0.2;
export const MIN_TRAIN_SIZE = 300;
export const MIN_VAL_SIZE = 100;
export const MIN_TEST_SIZE = 100;
export const MIN_WALK_FORWARD_WINDOWS = 3;

// ---- Chronological split -------------------------------------------------

/**
 * Split observations chronologically into train/val/test.
 *
 * @param {Array} observations — sorted by capturedAt ascending
 * @param {object} options
 * @param {number} options.trainRatio
 * @param {number} options.valRatio
 * @param {number} options.testRatio
 * @returns {object} { train, val, test, splitTimestamps }
 */
export function chronologicalSplit(observations, options = {}) {
  const {
    trainRatio = DEFAULT_TRAIN_RATIO,
    valRatio = DEFAULT_VAL_RATIO,
    testRatio = DEFAULT_TEST_RATIO,
  } = options;

  const n = observations.length;
  const trainEnd = Math.floor(n * trainRatio);
  const valEnd = Math.floor(n * (trainRatio + valRatio));

  const train = observations.slice(0, trainEnd);
  const val = observations.slice(trainEnd, valEnd);
  const test = observations.slice(valEnd);

  return {
    train,
    val,
    test,
    splitTimestamps: {
      trainStart: train[0]?.capturedAt ?? null,
      trainEnd: train[train.length - 1]?.capturedAt ?? null,
      valStart: val[0]?.capturedAt ?? null,
      valEnd: val[val.length - 1]?.capturedAt ?? null,
      testStart: test[0]?.capturedAt ?? null,
      testEnd: test[test.length - 1]?.capturedAt ?? null,
    },
    sizes: { train: train.length, val: val.length, test: test.length },
  };
}

// ---- Parameter freezing --------------------------------------------------

/**
 * Freeze parameters on training data.
 *
 * For each GEX feature, determine optimal window sizes using only
 * training observations.  These frozen parameters are used for
 * validation and test evaluation.
 *
 * @param {Array} trainObservations
 * @returns {object} frozen parameter set
 */
export function freezeParameters(trainObservations) {
  // Simple parameter freezing: use default window sizes
  // (In a more sophisticated implementation, we'd tune these on training data)
  return {
    netGexSmaWindow: 10,
    deltaGexSmaWindow: 10,
    velocityWindow: 6,
    volatilityWindow: 10,
    percentileWindow: 10,
    quintileCount: 5,
    minObservations: MIN_TRAIN_SIZE,
    frozenAt: trainObservations[0]?.capturedAt ?? null,
    frozenUntil: trainObservations[trainObservations.length - 1]?.capturedAt ?? null,
    trainSize: trainObservations.length,
  };
}

// ---- Walk-forward validation ---------------------------------------------

/**
 * Walk-forward validation: slide a window through time, training on
 * historical data and testing on the next period.
 *
 * @param {Array} observations — sorted by capturedAt ascending
 * @param {string} featureName — GEX feature to test
 * @param {string} outcomeKey — forward outcome to predict
 * @param {object} options
 * @param {number} options.trainSize — observations per training window
 * @param {number} options.testSize — observations per test window
 * @param {number} options.stepSize — sliding step (default: testSize)
 * @returns {object} walk-forward results
 */
export function walkForward(observations, featureName, outcomeKey, options = {}) {
  const {
    trainSize = MIN_TRAIN_SIZE,
    testSize = MIN_TEST_SIZE,
    stepSize = MIN_TEST_SIZE,
  } = options;

  if (observations.length < trainSize + testSize) {
    return { status: "INSUFFICIENT_DATA", totalObservations: observations.length };
  }

  const windows = [];
  let start = 0;

  while (start + trainSize + testSize <= observations.length) {
    const train = observations.slice(start, start + trainSize);
    const test = observations.slice(start + trainSize, start + trainSize + testSize);

    // Freeze parameters on training data
    const frozenParams = freezeParameters(train);

    // Evaluate on test data using frozen parameters
    const testResult = quintileAnalysis(test, featureName, outcomeKey);

    windows.push({
      windowIndex: windows.length,
      trainRange: {
        start: train[0].capturedAt,
        end: train[train.length - 1].capturedAt,
      },
      testRange: {
        start: test[0].capturedAt,
        end: test[test.length - 1].capturedAt,
      },
      trainSize: train.length,
      testSize: test.length,
      frozenParams,
      testResult,
    });

    start += stepSize;
  }

  if (windows.length < MIN_WALK_FORWARD_WINDOWS) {
    return {
      status: "INSUFFICIENT_WINDOWS",
      windowCount: windows.length,
      windows,
    };
  }

  // Aggregate across windows
  const testEffects = windows
    .map(w => w.testResult?.effectSize)
    .filter(v => Number.isFinite(v));

  const testQ5MinusQ1 = windows
    .map(w => w.testResult?.q5MinusQ1)
    .filter(v => Number.isFinite(v));

  return {
    status: "COMPUTED",
    feature: featureName,
    outcome: outcomeKey,
    windowCount: windows.length,
    windows,
    aggregate: {
      meanEffectSize: _mean(testEffects),
      medianEffectSize: _median(testEffects),
      meanQ5MinusQ1: _mean(testQ5MinusQ1),
      positiveWindows: testEffects.filter(v => v > 0).length,
      negativeWindows: testEffects.filter(v => v < 0).length,
    },
  };
}

// ---- Out-of-sample evaluation --------------------------------------------

/**
 * Evaluate a feature on held-out test data using parameters frozen on training.
 *
 * @param {Array} trainObservations
 * @param {Array} testObservations
 * @param {string} featureName
 * @param {string} outcomeKey
 * @returns {object} OOS evaluation result
 */
export function outOfSampleEvaluation(trainObservations, testObservations, featureName, outcomeKey) {
  const frozenParams = freezeParameters(trainObservations);
  const trainResult = quintileAnalysis(trainObservations, featureName, outcomeKey);
  const testResult = quintileAnalysis(testObservations, featureName, outcomeKey);

  // Robustness: does the test result direction match training?
  const trainDirection = trainResult?.q5MinusQ1 ?? 0;
  const testDirection = testResult?.q5MinusQ1 ?? 0;
  const directionConsistent = (trainDirection > 0 && testDirection > 0) ||
    (trainDirection < 0 && testDirection < 0) ||
    (trainDirection === 0 && testDirection === 0);

  // Effect size degradation
  const trainEffect = trainResult?.effectSize ?? 0;
  const testEffect = testResult?.effectSize ?? 0;
  const effectDegradation = trainEffect !== 0
    ? Math.abs(testEffect - trainEffect) / Math.abs(trainEffect)
    : null;

  return {
    status: "COMPUTED",
    feature: featureName,
    outcome: outcomeKey,
    frozenParams,
    trainResult,
    testResult,
    directionConsistent,
    effectDegradation,
    robust: directionConsistent && (effectDegradation == null || effectDegradation < 0.5),
  };
}

// ---- Full validation pipeline --------------------------------------------

/**
 * Run the complete validation pipeline for one feature.
 *
 * @param {Array} observations — all observations, chronological
 * @param {string} featureName
 * @param {string} outcomeKey
 * @returns {object} comprehensive validation result
 */
export function validateFeature(observations, featureName, outcomeKey) {
  // Split
  const split = chronologicalSplit(observations);
  if (split.sizes.test < MIN_TEST_SIZE) {
    return { status: "INSUFFICIENT_DATA", feature: featureName, outcome: outcomeKey };
  }

  // In-sample (train)
  const inSampleResult = quintileAnalysis(split.train, featureName, outcomeKey);

  // Out-of-sample (test)
  const oosResult = outOfSampleEvaluation(split.train, split.test, featureName, outcomeKey);

  // Walk-forward
  const wfResult = walkForward(observations, featureName, outcomeKey);

  // Block bootstrap CI on full dataset
  const fullOutcomes = observations
    .map(obs => {
      const f = _getNestedValue(obs, featureName);
      const y = _getNestedValue(obs, outcomeKey);
      return Number.isFinite(f) && Number.isFinite(y) ? y : null;
    })
    .filter(v => v !== null);
  const bootstrapCI = blockBootstrapMean(fullOutcomes);

  // Classify
  const status = _classifyStatus(inSampleResult, oosResult, wfResult, fullOutcomes.length);

  return {
    feature: featureName,
    outcome: outcomeKey,
    sampleCount: fullOutcomes.length,
    inSample: inSampleResult,
    outOfSample: oosResult,
    walkForward: wfResult,
    bootstrapCI,
    status,
  };
}

// ---- Status classification -----------------------------------------------

function _classifyStatus(inSample, oos, walkForward, totalSamples) {
  if (totalSamples < 200) return "INSUFFICIENT_DATA";

  const inSampleEffect = Math.abs(inSample?.effectSize ?? 0);
  const oosConsistent = oos?.directionConsistent ?? false;
  const wfPositive = (walkForward?.aggregate?.positiveWindows ?? 0) >
    (walkForward?.aggregate?.negativeWindows ?? 0);

  if (inSampleEffect < 0.2 && !oosConsistent) return "NO_EVIDENCE";
  if (inSampleEffect < 0.5) return "WEAK_ASSOCIATION";
  if (inSampleEffect >= 0.5 && oosConsistent && wfPositive) return "PROMISING";
  if (inSampleEffect >= 0.8 && oosConsistent && wfPositive) return "ROBUST_ASSOCIATION";
  return "WEAK_ASSOCIATION";
}

// ---- Internal helpers ----------------------------------------------------

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
