/**
 * GEX Phase 7.7 — gexResearchRegistry Tests
 *
 * Level A: Research result builder
 * Level B: Feature definitions
 * Level C: Feature registry
 * Level D: Status classification
 */

import { describe, it, expect } from "vitest";
import {
  buildResearchResult,
  buildFeatureRegistry,
  STATUS,
  RESEARCH_VERSION,
  FEATURE_DEFINITIONS,
} from "./gexResearchRegistry.js";

// ---- Level A: Research result builder ------------------------------------

describe("buildResearchResult", () => {
  it("creates a complete result", () => {
    const result = buildResearchResult({
      feature: "netGex",
      horizon: "candles10",
      sampleCount: 500,
      meanOutcome: 0.001,
      effectSize: 0.6,
      status: "PROMISING",
      methodology: "quintile_analysis",
    });
    expect(result.researchVersion).toBe(RESEARCH_VERSION);
    expect(result.feature).toBe("netGex");
    expect(result.horizon).toBe("candles10");
    expect(result.sampleCount).toBe(500);
    expect(result.effectSize).toBe(0.6);
    expect(result.status).toBe("PROMISING");
    expect(result.computedAt).toBeDefined();
  });

  it("defaults to INSUFFICIENT_DATA", () => {
    const result = buildResearchResult({ feature: "test" });
    expect(result.status).toBe(STATUS.INSUFFICIENT_DATA);
  });

  it("null fields are preserved", () => {
    const result = buildResearchResult({ feature: "test" });
    expect(result.condition).toBeNull();
    expect(result.pValue).toBeNull();
    expect(result.adjustedPValue).toBeNull();
  });
});

// ---- Level B: Feature definitions ----------------------------------------

describe("FEATURE_DEFINITIONS", () => {
  it("contains all GEX features", () => {
    const names = FEATURE_DEFINITIONS.map(f => f.name);
    expect(names).toContain("netGex");
    expect(names).toContain("normalizedNetGex");
    expect(names).toContain("deltaGex");
    expect(names).toContain("velocity");
    expect(names).toContain("acceleration");
    expect(names).toContain("volatility");
    expect(names).toContain("concentrationTop3");
    expect(names).toContain("gexPercentile");
    expect(names).toContain("descriptiveZ");
    expect(names).toContain("callGexShare");
    expect(names).toContain("gammaFlipDistancePct");
    expect(names).toContain("callWallDistancePct");
    expect(names).toContain("putWallDistancePct");
    expect(names).toContain("dte");
  });

  it("each definition has required fields", () => {
    for (const def of FEATURE_DEFINITIONS) {
      expect(def.name).toBeTruthy();
      expect(def.source).toBeTruthy();
      expect(def.computation).toBeTruthy();
      expect(def.unit).toBeTruthy();
      expect(typeof def.description).toBe("string");
    }
  });
});

// ---- Level C: Feature registry -------------------------------------------

describe("buildFeatureRegistry", () => {
  it("builds registry from validation results", () => {
    const mockResults = [
      { feature: "netGex", status: "PROMISING", sampleCount: 500, inSample: { effectSize: 0.6 }, outOfSample: { directionConsistent: true }, walkForward: { aggregate: { positiveWindows: 5, negativeWindows: 2 } } },
      { feature: "velocity", status: "NO_EVIDENCE", sampleCount: 500, inSample: { effectSize: 0.1 }, outOfSample: { directionConsistent: false }, walkForward: { aggregate: { positiveWindows: 2, negativeWindows: 5 } } },
      { feature: "dte", status: "WEAK_ASSOCIATION", sampleCount: 300, inSample: { effectSize: 0.3 }, outOfSample: { directionConsistent: true }, walkForward: { aggregate: { positiveWindows: 3, negativeWindows: 3 } } },
    ];
    const registry = buildFeatureRegistry(mockResults);
    expect(registry.version).toBe(RESEARCH_VERSION);
    expect(registry.featureCount).toBe(3);
    expect(registry.statusCounts[STATUS.PROMISING]).toBe(1);
    expect(registry.statusCounts[STATUS.NO_EVIDENCE]).toBe(1);
    expect(registry.statusCounts[STATUS.WEAK_ASSOCIATION]).toBe(1);
    expect(registry.features[0].name).toBe("netGex");
    expect(registry.features[0].validationStatus).toBe("PROMISING");
  });

  it("empty results produce empty registry", () => {
    const registry = buildFeatureRegistry([]);
    expect(registry.featureCount).toBe(0);
  });
});

// ---- Level D: Status classification --------------------------------------

describe("STATUS constants", () => {
  it("has all 5 statuses", () => {
    expect(Object.keys(STATUS)).toHaveLength(5);
    expect(STATUS.INSUFFICIENT_DATA).toBe("INSUFFICIENT_DATA");
    expect(STATUS.NO_EVIDENCE).toBe("NO_EVIDENCE");
    expect(STATUS.WEAK_ASSOCIATION).toBe("WEAK_ASSOCIATION");
    expect(STATUS.PROMISING).toBe("PROMISING");
    expect(STATUS.ROBUST_ASSOCIATION).toBe("ROBUST_ASSOCIATION");
  });
});
