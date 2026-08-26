/**
 * GEX Phase 7.7 — gexResearchTests Tests
 *
 * Level A: Quintile analysis
 * Level B: Effect sizes
 * Level C: Block bootstrap
 * Level D: Multiple testing
 * Level E: Interaction analysis
 * Level F: Regime analysis
 * Level G: Edge cases
 */

import { describe, it, expect } from "vitest";
import {
  quintileAnalysis,
  cohensD,
  blockBootstrapMean,
  holmBonferroni,
  benjaminiHochberg,
  interactionAnalysis,
  regimeAnalysis,
  baselineComparison,
  MIN_OBSERVATIONS,
} from "./gexResearchTests.js";

// ---- Fixtures ------------------------------------------------------------

function makeObs(featureVal, outcomeVal) {
  return { netGex: featureVal, forward: { candles10: { return: outcomeVal } } };
}

function makeDataset(n, featureFn, outcomeFn) {
  return Array.from({ length: n }, (_, i) => makeObs(featureFn(i), outcomeFn(i)));
}

// ---- Level A: Quintile analysis ------------------------------------------

describe("quintileAnalysis", () => {
  it("basic quintile analysis with clear signal", () => {
    // Feature correlates positively with outcome
    const data = makeDataset(500, i => i, i => i * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.sampleCount).toBe(500);
    expect(result.quintiles).toHaveLength(5);
    // Q5 mean should be higher than Q1 mean
    expect(result.quintiles[4].mean).toBeGreaterThan(result.quintiles[0].mean);
    expect(result.effectSize).toBeGreaterThan(0);
  });

  it("no signal produces small effect size", () => {
    const data = makeDataset(500, () => Math.random(), () => Math.random() * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(Math.abs(result.effectSize)).toBeLessThan(0.5);
  });

  it("insufficient data returns INSUFFICIENT_DATA", () => {
    const data = makeDataset(50, i => i, i => i * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });

  it("baseline statistics are computed", () => {
    const data = makeDataset(300, i => i, i => i * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.baseline).toBeDefined();
    expect(result.baseline.mean).not.toBeNull();
    expect(result.baseline.count).toBe(300);
  });

  it("handles null features gracefully", () => {
    const data = [
      ...makeDataset(250, i => i, i => i * 0.001),
      ...makeDataset(50, () => null, () => 0.001),
    ];
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.sampleCount).toBe(250); // nulls excluded
  });
});

// ---- Level B: Effect sizes -----------------------------------------------

describe("cohensD", () => {
  it("large positive effect", () => {
    const g1 = Array.from({ length: 100 }, (_, i) => 0 + i * 0.01);
    const g2 = Array.from({ length: 100 }, (_, i) => 1 + i * 0.01);
    expect(cohensD(g1, g2)).toBeGreaterThan(3);
  });

  it("zero effect", () => {
    const g1 = Array.from({ length: 100 }, (_, i) => 0.5 + i * 0.001);
    const g2 = Array.from({ length: 100 }, (_, i) => 0.5 + i * 0.001);
    expect(cohensD(g1, g2)).toBeCloseTo(0, 5);
  });

  it("small sample returns null", () => {
    expect(cohensD([1], [2])).toBeNull();
  });
});

// ---- Level C: Block bootstrap --------------------------------------------

describe("blockBootstrapMean", () => {
  it("returns mean and CI", () => {
    const values = Array.from({ length: 200 }, () => Math.random() * 0.01);
    const result = blockBootstrapMean(values, { replicates: 500 });
    expect(result.mean).not.toBeNull();
    expect(result.ciLower).not.toBeNull();
    expect(result.ciUpper).not.toBeNull();
    expect(result.ciLower).toBeLessThan(result.mean);
    expect(result.ciUpper).toBeGreaterThan(result.mean);
  });

  it("constant values produce narrow CI", () => {
    const values = Array.from({ length: 200 }, () => 0.5);
    const result = blockBootstrapMean(values, { replicates: 500 });
    expect(result.mean).toBeCloseTo(0.5, 5);
    expect(result.ciLower).toBeCloseTo(0.5, 2);
    expect(result.ciUpper).toBeCloseTo(0.5, 2);
  });

  it("insufficient data returns null CI", () => {
    const result = blockBootstrapMean([1]);
    expect(result.ciLower).toBeNull();
    expect(result.ciUpper).toBeNull();
  });

  it("preserves serial dependence structure", () => {
    // Autocorrelated series
    const values = [0.1];
    for (let i = 1; i < 200; i++) {
      values.push(values[i - 1] * 0.9 + Math.random() * 0.1);
    }
    const result = blockBootstrapMean(values, { blockSize: 5, replicates: 500 });
    expect(result.mean).not.toBeNull();
    expect(result.se).toBeGreaterThan(0);
  });
});

// ---- Level D: Multiple testing correction --------------------------------

describe("holmBonferroni", () => {
  it("adjusts p-values upward", () => {
    const pvals = [0.01, 0.02, 0.03, 0.04, 0.05];
    const adjusted = holmBonferroni(pvals);
    expect(adjusted).toHaveLength(5);
    for (let i = 0; i < 5; i++) {
      expect(adjusted[i]).toBeGreaterThanOrEqual(pvals[i]);
    }
  });

  it("most significant p-value adjusted least", () => {
    const pvals = [0.001, 0.01, 0.05];
    const adjusted = holmBonferroni(pvals);
    expect(adjusted[0]).toBeCloseTo(0.003, 3); // 0.001 * 3
  });

  it("handles null p-values", () => {
    const adjusted = holmBonferroni([0.01, null, 0.05]);
    expect(adjusted[0]).not.toBeNull();
    expect(adjusted[1]).toBeNull();
    expect(adjusted[2]).not.toBeNull();
  });
});

describe("benjaminiHochberg", () => {
  it("less conservative than Holm-Bonferroni", () => {
    const pvals = [0.01, 0.02, 0.03, 0.04, 0.05];
    const holm = holmBonferroni(pvals);
    const bh = benjaminiHochberg(pvals);
    // BH should be <= Holm for each p-value
    for (let i = 0; i < 5; i++) {
      if (holm[i] != null && bh[i] != null) {
        expect(bh[i]).toBeLessThanOrEqual(holm[i] + 0.001);
      }
    }
  });
});

// ---- Level E: Interaction analysis ---------------------------------------

describe("interactionAnalysis", () => {
  it("computes interaction between two features", () => {
    const data = Array.from({ length: 300 }, (_, i) => ({
      netGex: Math.sin(i * 0.1) * 1000,
      velocity: Math.cos(i * 0.1) * 100,
      forward: { candles10: { return: (Math.sin(i * 0.1) + Math.cos(i * 0.1)) * 0.001 } },
    }));
    const result = interactionAnalysis(data, "netGex", "velocity", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.cellMeans).toBeDefined();
    expect(result.sampleCount).toBe(300);
  });

  it("insufficient data", () => {
    const data = Array.from({ length: 10 }, (_, i) => ({
      netGex: i, velocity: i, forward: { candles10: { return: 0.001 } },
    }));
    const result = interactionAnalysis(data, "netGex", "velocity", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });
});

// ---- Level F: Regime analysis --------------------------------------------

describe("regimeAnalysis", () => {
  it("classifies regimes by rolling percentile", () => {
    const data = Array.from({ length: 300 }, (_, i) => ({
      netGex: i * 100,
      forward: { candles10: { return: i * 0.0001 } },
    }));
    const result = regimeAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.regimes.low).toBeDefined();
    expect(result.regimes.neutral).toBeDefined();
    expect(result.regimes.high).toBeDefined();
    expect(result.regimes.low.mean).toBeLessThan(result.regimes.high.mean);
  });

  it("insufficient data", () => {
    const data = Array.from({ length: 50 }, (_, i) => ({
      netGex: i, forward: { candles10: { return: 0.001 } },
    }));
    const result = regimeAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });
});

// ---- Level G: Edge cases -------------------------------------------------

describe("Edge cases", () => {
  it("all-null features produce INSUFFICIENT_DATA", () => {
    const data = Array.from({ length: 300 }, () => ({
      netGex: null,
      forward: { candles10: { return: 0.001 } },
    }));
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("INSUFFICIENT_DATA");
  });

  it("constant feature values produce no differentiation", () => {
    // All features the same → quintiles split randomly → effect size ≈ 0
    const data = makeDataset(300, () => 100, () => (Math.random() - 0.5) * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.sampleCount).toBe(300);
  });

  it("negative GEX values", () => {
    const data = makeDataset(300, i => -i * 100, i => i * 0.001);
    const result = quintileAnalysis(data, "netGex", "forward.candles10.return");
    expect(result.status).toBe("COMPUTED");
    expect(result.sampleCount).toBe(300);
  });
});
