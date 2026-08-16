import { describe, it, expect } from "vitest";
import {
  MIN_STAT_SAMPLE,
  MIN_STDDEV_SAMPLE,
  cleanNumber,
  cleanNumbers,
  rollingMean,
  rollingMedian,
  rollingStdDev,
  rollingMin,
  rollingMax,
  zScore,
  percentileRank,
  anomalyMeasurement,
} from "./statistics";

// ---- Rolling statistics ------------------------------------------------------

describe("rolling statistics", () => {
  it("mean of [1,2,3,4] is 2.5", () => {
    expect(rollingMean([1, 2, 3, 4])).toBeCloseTo(2.5, 10);
  });

  it("median is the middle for odd counts and midpoint for even counts", () => {
    expect(rollingMedian([3, 1, 2])).toBe(2);
    expect(rollingMedian([1, 2, 3, 4])).toBeCloseTo(2.5, 10);
  });

  it("population standard deviation of [2,4,4,4,5,5,7,9] is 2", () => {
    expect(rollingStdDev([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(2, 10);
  });

  it("min/max of [3,1,2] are 1 and 3", () => {
    expect(rollingMin([3, 1, 2])).toBe(1);
    expect(rollingMax([3, 1, 2])).toBe(3);
  });

  it("invalid entries (null/NaN/Infinity/strings) are ignored safely", () => {
    // Valid entries after cleaning: [1, 3, 5] → mean 3, population σ = √(8/3)
    const values = [1, null, undefined, NaN, Infinity, -Infinity, "3", 5];
    expect(rollingMean(values)).toBeCloseTo(3, 10);
    expect(rollingMedian(values)).toBeCloseTo(3, 10);
    expect(rollingStdDev(values)).toBeCloseTo(Math.sqrt(8 / 3), 10);
    expect(rollingMin(values)).toBe(1);
    expect(rollingMax(values)).toBe(5);
  });

  it("empty history → null for every rolling statistic", () => {
    expect(rollingMean([])).toBeNull();
    expect(rollingMedian([])).toBeNull();
    expect(rollingStdDev([])).toBeNull();
    expect(rollingMin([])).toBeNull();
    expect(rollingMax([])).toBeNull();
    expect(rollingMean(null)).toBeNull();
    expect(rollingMean([null, NaN])).toBeNull();
  });

  it("standard deviation needs ≥ 2 observations", () => {
    expect(rollingStdDev([5])).toBeNull();
    expect(rollingStdDev([5, 5])).toBeCloseTo(0, 10);
  });
});

// ---- Z-score / percentile ------------------------------------------------------

describe("z-score", () => {
  it("z-score of a value one σ above the mean is ≈ 1", () => {
    const history = [10, 12, 8, 11, 9, 13, 7, 12, 10, 8, 11, 9]; // mean 10, σ 1.779…
    expect(zScore(11.78, history)).toBeCloseTo(1, 1);
  });

  it("z-score is 0 at the mean", () => {
    const history = [10, 12, 8, 11, 9, 13, 7, 12, 10, 8, 11, 9];
    expect(zScore(rollingMean(history), history)).toBeCloseTo(0, 10);
  });

  it("empty history → null", () => {
    expect(zScore(5, [])).toBeNull();
  });

  it("insufficient history → null", () => {
    expect(zScore(5, [1, 2])).toBeNull(); // below MIN_STAT_SAMPLE
  });

  it("constant history → null (σ = 0 is undefined, never Infinity)", () => {
    const constant = Array(MIN_STAT_SAMPLE).fill(5);
    expect(zScore(5, constant)).toBeNull();
    expect(zScore(7, constant)).toBeNull();
  });

  it("invalid value → null", () => {
    expect(zScore(null, [1, 2, 3, 4, 5, 6])).toBeNull();
    expect(zScore(NaN, [1, 2, 3, 4, 5, 6])).toBeNull();
  });
});

describe("percentile rank", () => {
  it("mean-rank convention: minimum → (0.5/n)×100, maximum → (n−0.5)/n×100", () => {
    const history = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    expect(percentileRank(1, history)).toBeCloseTo(5, 10); // (0 + 0.5×1)/10 × 100
    expect(percentileRank(10, history)).toBeCloseTo(95, 10); // (9 + 0.5×1)/10 × 100
  });

  it("value at the median of an even sample → 50", () => {
    const history = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    expect(percentileRank(5.5, history)).toBeCloseTo(50, 10);
  });

  it("constant history → exact safe result (50 for the same value), not fabricated", () => {
    const constant = Array(MIN_STAT_SAMPLE).fill(5);
    expect(percentileRank(5, constant)).toBeCloseTo(50, 10);
    expect(percentileRank(6, constant)).toBe(100);
    expect(percentileRank(4, constant)).toBe(0);
  });

  it("empty history → null", () => {
    expect(percentileRank(5, [])).toBeNull();
  });

  it("insufficient history → null (no fake 0% / 100%)", () => {
    expect(percentileRank(5, [1, 2, 3])).toBeNull();
  });
});

// ---- Anomaly measurement ---------------------------------------------------------

describe("anomaly measurement (neutral, 0–100 unusualness)", () => {
  it("magnitude scales with |z| and saturates at 100 for |z| ≥ 3", () => {
    const history = [10, 10, 10, 10, 10, 10, 10, 10, 10, 20]; // σ > 0, mean 11
    const a = anomalyMeasurement(20, history);
    expect(a.zScore).not.toBeNull();
    expect(a.magnitude).toBeGreaterThan(0);
    expect(a.magnitude).toBeLessThanOrEqual(100);
    expect(a.percentileRank).not.toBeNull();
    expect(a.status).toBe("available");
  });

  it("returns baseline = rolling mean and available/expected counts", () => {
    const a = anomalyMeasurement(7, [1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(a.baseline).toBeCloseTo(5, 10);
    expect(a.availableCount).toBe(9);
    expect(a.expectedCount).toBe(9);
  });

  it("empty history → unavailable with null magnitude (never 0)", () => {
    const a = anomalyMeasurement(5, []);
    expect(a.status).toBe("unavailable");
    expect(a.zScore).toBeNull();
    expect(a.magnitude).toBeNull();
    expect(a.percentileRank).toBeNull();
  });

  it("insufficient history → partial (no fabricated score)", () => {
    const a = anomalyMeasurement(5, [1, 2]);
    expect(a.status).toBe("partial");
    expect(a.zScore).toBeNull();
    expect(a.magnitude).toBeNull();
  });

  it("cleanNumber keeps valid zero but rejects invalid", () => {
    expect(cleanNumber(0)).toBe(0);
    expect(cleanNumber(null)).toBeNull();
    expect(cleanNumber(undefined)).toBeNull();
    expect(cleanNumber(NaN)).toBeNull();
    expect(cleanNumber(Infinity)).toBeNull();
    expect(cleanNumber("12")).toBe(12);
    expect(cleanNumbers([0, null, NaN, "3"])).toEqual([0, 3]);
    expect(MIN_STDDEV_SAMPLE).toBe(2);
  });
});
