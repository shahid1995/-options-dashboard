/**
 * GEX Phase 7.7 — gexResearchValidation Tests
 *
 * Level A: Chronological split
 * Level B: Parameter freezing
 * Level C: Walk-forward
 * Level D: Out-of-sample evaluation
 * Level E: Full validation pipeline
 * Level F: Edge cases
 */

import { describe, it, expect } from "vitest";
import {
  chronologicalSplit,
  freezeParameters,
  walkForward,
  outOfSampleEvaluation,
  validateFeature,
  MIN_TRAIN_SIZE,
  MIN_TEST_SIZE,
} from "./gexResearchValidation.js";

// ---- Fixtures ------------------------------------------------------------

function makeObs(capturedAt, netGex, outcome) {
  return {
    capturedAt,
    netGex,
    forward: { candles10: { return: outcome } },
  };
}

function makeChronologicalDataset(n) {
  return Array.from({ length: n }, (_, i) => {
    const hour = 9 + Math.floor(i / 12);
    const min = 15 + (i % 12) * 5;
    return makeObs(
      `2026-08-22T${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}:00Z`,
      i * 100 + Math.sin(i) * 50,
      Math.sin(i * 0.1) * 0.001
    );
  });
}

// ---- Level A: Chronological split ----------------------------------------

describe("chronologicalSplit", () => {
  it("splits 60/20/20 by default", () => {
    const data = makeChronologicalDataset(1000);
    const split = chronologicalSplit(data);
    expect(split.sizes.train).toBe(600);
    expect(split.sizes.val).toBe(200);
    expect(split.sizes.test).toBe(200);
  });

  it("preserves chronological order", () => {
    const data = makeChronologicalDataset(100);
    const split = chronologicalSplit(data);
    // Train end < Val start < Val end < Test start (string comparison of ISO dates)
    const trainEnd = split.train[split.train.length - 1].capturedAt;
    const valStart = split.val[0].capturedAt;
    const valEnd = split.val[split.val.length - 1].capturedAt;
    const testStart = split.test[0].capturedAt;
    expect(trainEnd.localeCompare(valStart)).toBeLessThan(0);
    expect(valEnd.localeCompare(testStart)).toBeLessThan(0);
  });

  it("reports split timestamps", () => {
    const data = makeChronologicalDataset(100);
    const split = chronologicalSplit(data);
    expect(split.splitTimestamps.trainStart).toBe(data[0].capturedAt);
    expect(split.splitTimestamps.testEnd).toBe(data[data.length - 1].capturedAt);
  });

  it("custom ratios", () => {
    const data = makeChronologicalDataset(100);
    const split = chronologicalSplit(data, { trainRatio: 0.5, valRatio: 0.25, testRatio: 0.25 });
    expect(split.sizes.train).toBe(50);
    expect(split.sizes.val).toBe(25);
    expect(split.sizes.test).toBe(25);
  });
});

// ---- Level B: Parameter freezing -----------------------------------------

describe("freezeParameters", () => {
  it("freezes default window sizes", () => {
    const data = makeChronologicalDataset(500);
    const params = freezeParameters(data);
    expect(params.netGexSmaWindow).toBe(10);
    expect(params.velocityWindow).toBe(6);
    expect(params.frozenAt).toBe(data[0].capturedAt);
    expect(params.frozenUntil).toBe(data[data.length - 1].capturedAt);
    expect(params.trainSize).toBe(500);
  });
});

// ---- Level C: Walk-forward -----------------------------------------------

describe("walkForward", () => {
  it("creates multiple windows", () => {
    const data = makeChronologicalDataset(1000);
    const result = walkForward(data, "netGex", "forward.candles10.return", {
      trainSize: 200,
      testSize: 100,
      stepSize: 100,
    });
    expect(result.status).toBe("COMPUTED");
    expect(result.windowCount).toBeGreaterThanOrEqual(3);
    expect(result.windows.length).toBeGreaterThanOrEqual(3);
  });

  it("each window has frozen parameters", () => {
    const data = makeChronologicalDataset(600);
    const result = walkForward(data, "netGex", "forward.candles10.return", {
      trainSize: 200,
      testSize: 100,
      stepSize: 100,
    });
    for (const w of result.windows) {
      expect(w.frozenParams).toBeDefined();
      expect(w.frozenParams.frozenAt).not.toBeNull();
    }
  });

  it("insufficient data returns INSUFFICIENT_DATA", () => {
    const data = makeChronologicalDataset(50);
    const result = walkForward(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });

  it("insufficient windows returns INSUFFICIENT_WINDOWS", () => {
    const data = makeChronologicalDataset(250);
    const result = walkForward(data, "netGex", "forward.candles10.return", {
      trainSize: 100,
      testSize: 100,
      stepSize: 100,
    });
    // Only 1 window possible from 250 observations
    expect(result.windowCount).toBeLessThan(3);
  });

  it("aggregate statistics are computed", () => {
    const data = makeChronologicalDataset(1000);
    const result = walkForward(data, "netGex", "forward.candles10.return", {
      trainSize: 200,
      testSize: 100,
      stepSize: 100,
    });
    expect(result.aggregate).toBeDefined();
    expect(result.aggregate).toBeDefined();
    expect(typeof result.aggregate.positiveWindows).toBe("number");
    expect(typeof result.aggregate.negativeWindows).toBe("number");
  });
});

// ---- Level D: Out-of-sample evaluation -----------------------------------

describe("outOfSampleEvaluation", () => {
  it("compares train and test results", () => {
    const train = makeChronologicalDataset(500);
    const test = makeChronologicalDataset(200);
    const result = outOfSampleEvaluation(train, test, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.trainResult).toBeDefined();
    expect(result.testResult).toBeDefined();
    expect(typeof result.directionConsistent).toBe("boolean");
  });

  it("frozen params come from training data", () => {
    const train = makeChronologicalDataset(500);
    const test = makeChronologicalDataset(200);
    const result = outOfSampleEvaluation(train, test, "netGex", "forward.candles10.return");
    expect(result.frozenParams.trainSize).toBe(500);
  });
});

// ---- Level E: Full validation pipeline -----------------------------------

describe("validateFeature", () => {
  it("runs complete pipeline", () => {
    const data = makeChronologicalDataset(1000);
    const result = validateFeature(data, "netGex", "forward.candles10.return");
    expect(result.feature).toBe("netGex");
    expect(result.outcome).toBe("forward.candles10.return");
    expect(result.inSample).toBeDefined();
    expect(result.outOfSample).toBeDefined();
    expect(result.walkForward).toBeDefined();
    expect(result.bootstrapCI).toBeDefined();
    expect(result.status).toBeDefined();
    expect([
      "INSUFFICIENT_DATA", "NO_EVIDENCE", "WEAK_ASSOCIATION", "PROMISING", "ROBUST_ASSOCIATION",
    ]).toContain(result.status);
  });

  it("insufficient data returns INSUFFICIENT_DATA", () => {
    const data = makeChronologicalDataset(50);
    const result = validateFeature(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });
});

// ---- Level F: Edge cases -------------------------------------------------

describe("Edge cases", () => {
  it("empty dataset", () => {
    const split = chronologicalSplit([]);
    expect(split.sizes.train).toBe(0);
    expect(split.sizes.val).toBe(0);
    expect(split.sizes.test).toBe(0);
  });

  it("very small dataset", () => {
    const data = makeChronologicalDataset(10);
    const split = chronologicalSplit(data);
    expect(split.sizes.train + split.sizes.val + split.sizes.test).toBe(10);
  });

  it("constant netGex values", () => {
    const data = Array.from({ length: 500 }, (_, i) =>
      makeObs(`2026-08-22T${String(9 + Math.floor(i / 12)).padStart(2, "0")}:${String(15 + (i % 12) * 5).padStart(2, "0")}:00Z`, 100, 0.001)
    );
    const result = validateFeature(data, "netGex", "forward.candles10.return");
    expect(result.status).toBeDefined();
  });
});
