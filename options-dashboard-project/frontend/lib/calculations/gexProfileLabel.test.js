/**
 * GEX Phase 7.4c — GEX Profile Label Tests
 *
 * Level A — Label classification with hand-crafted inputs
 * Level B — Multi-label combinations
 * Level C — Config override
 * Level D — Edge cases
 * Level E — Normalized GEX
 */

import { describe, it, expect } from "vitest";
import {
  classifyGexProfile,
  LABEL,
  DEFAULT_PROFILE_CONFIG,
  PROFILE_CONFIDENCE,
} from "./gexProfileLabel";
import { computeConcentration } from "./gexHistory";

// =============================================================================
// Test fixtures
// =============================================================================

/**
 * Create a snapshot with given netGex, spot, and optional strikeData.
 * Uses fixed strikes so concentration is controllable.
 */
function makeSnapshot(opts = {}) {
  const spot = opts.spot ?? 25000;
  const netGex = opts.netGex ?? 0;
  const strikeData = opts.strikeData ?? [
    // Default: balanced single strike with netGex
    { strike: 25000, callGex: Math.max(netGex, 0) + 1000000, putGex: -(Math.max(-netGex, 0) + 1000000), netGex },
  ];
  return {
    symbol: "NIFTY",
    expiry: opts.expiry ?? "2026-08-28",
    spot,
    netGex,
    callGex: opts.callGex ?? Math.max(netGex, 0),
    putGex: opts.putGex ?? Math.min(netGex, 0),
    availabilityStatus: "available",
    validStrikeCount: 10,
    totalStrikeCount: 10,
    chainAgeMs: 0,
    capturedAt: opts.capturedAt ?? "2026-08-22T09:00:00Z",
    strikeData,
    expiryData: opts.expiryData ?? [
      { expiry: "2026-08-28", netGex, callGex: Math.max(netGex, 0), putGex: Math.min(netGex, 0), availabilityStatus: "available", validStrikeCount: 10, totalStrikeCount: 10 },
    ],
    methodologyMetadata: { gexVersion: "GEX_STANDARD_V1" },
  };
}

/** Create strike data with controlled concentration.
 * computeConcentration uses Math.abs(netGex) per strike.
 * We want top3 strikes to hold top3Pct% of the total absolute GEX. */
function makeConcentrationStrikeData(targetTop3Pct) {
  // Total absolute GEX = 10000 (spread across strikes)
  // Top 3 strikes hold targetTop3Pct% of 10000
  // Remaining strikes hold (100 - targetTop3Pct)% of 10000
  const total = 10000;
  const top3Total = total * (targetTop3Pct / 100);
  const restTotal = total - top3Total;
  const restStrikes = 7;
  const perRest = restTotal / restStrikes;

  // Top 3 strikes with netGex values that |computeConcentration| will see
  const strikes = [
    { strike: 24900, netGex: top3Total * 0.3 },
    { strike: 25000, netGex: top3Total * 0.5 },
    { strike: 25100, netGex: top3Total * 0.2 },
  ];
  for (let i = 0; i < restStrikes; i++) {
    strikes.push({
      strike: 24000 + i * 100,
      netGex: perRest,
    });
  }
  return strikes;
}

// =============================================================================
// Level A — Label classification with hand-crafted inputs
// =============================================================================

describe("Level A — Label classification", () => {
  it("strong positive normalized GEX → POSITIVE_DOMINANT", () => {
    // normalizedNetGex > 0.5
    // netGex = 0.6 × spot² × 0.01 = 0.6 × 6,250,000 = 3,750,000
    const spot = 25000;
    const netGex = 0.6 * spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.POSITIVE_DOMINANT);
    expect(result.normalizedNetGex).toBeCloseTo(0.6, 5);
  });

  it("moderate positive normalized GEX → POSITIVE_MODERATE", () => {
    const spot = 25000;
    const netGex = 0.2 * spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.POSITIVE_MODERATE);
    expect(result.normalizedNetGex).toBeCloseTo(0.2, 5);
  });

  it("near-zero normalized GEX → BALANCED", () => {
    const spot = 25000;
    const netGex = 0.05 * spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.BALANCED);
  });

  it("strong negative normalized GEX → NEGATIVE_DOMINANT", () => {
    const spot = 25000;
    const netGex = -0.6 * spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.NEGATIVE_DOMINANT);
    expect(result.normalizedNetGex).toBeCloseTo(-0.6, 5);
  });

  it("moderate negative normalized GEX → NEGATIVE_MODERATE", () => {
    const spot = 25000;
    const netGex = -0.2 * spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.NEGATIVE_MODERATE);
  });

  it("high concentration → HIGH_CONCENTRATION", () => {
    const strikeData = makeConcentrationStrikeData(85);
    const data = [makeSnapshot({ netGex: 5000, strikeData })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.HIGH_CONCENTRATION);
    expect(result.concentration.top3Pct).toBeGreaterThan(70);
  });

  it("diffuse concentration → DIFFUSE", () => {
    const strikeData = makeConcentrationStrikeData(25);
    // Verify fixture produces low concentration
    const conc = computeConcentration(strikeData);
    expect(conc.top3Pct).toBeLessThan(40);
    const data = [makeSnapshot({ netGex: 5000, strikeData })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.DIFFUSE);
  });

  it("flip adjacent → FLIP_ADJACENT", () => {
    const data = [makeSnapshot({ netGex: 5000 })];
    const result = classifyGexProfile(data, {}, { flipDistancePct: 0.5 });
    expect(result.labels).toContain(LABEL.FLIP_ADJACENT);
  });

  it("flip distant → FLIP_DISTANT", () => {
    const data = [makeSnapshot({ netGex: 5000 })];
    const result = classifyGexProfile(data, {}, { flipDistancePct: 8.0 });
    expect(result.labels).toContain(LABEL.FLIP_DISTANT);
  });

  it("null netGex → UNAVAILABLE", () => {
    // Construct directly — snap() helper fills defaults for null via ??
    const snap = { netGex: null, callGex: null, putGex: null, spot: 25000, capturedAt: "2026-08-22T09:00:00Z", strikeData: [], expiryData: [] };
    const result = classifyGexProfile([snap]);
    expect(result.labels).toContain(LABEL.UNAVAILABLE);
    expect(result.status).toBe("unavailable");
  });
});

// =============================================================================
// Level B — Multi-label combinations
// =============================================================================

describe("Level B — Multi-label combinations", () => {
  it("strong positive + high concentration + flip adjacent", () => {
    const spot = 25000;
    const netGex = 0.6 * spot * spot * 0.01;
    const strikeData = makeConcentrationStrikeData(85);
    const data = [makeSnapshot({ netGex, spot, strikeData })];
    const result = classifyGexProfile(data, {}, { flipDistancePct: 0.3 });
    expect(result.labels).toContain(LABEL.POSITIVE_DOMINANT);
    expect(result.labels).toContain(LABEL.HIGH_CONCENTRATION);
    expect(result.labels).toContain(LABEL.FLIP_ADJACENT);
    expect(result.labels.length).toBe(3);
  });

  it("balanced + moderate concentration (no concentration label)", () => {
    const spot = 25000;
    const netGex = 0.05 * spot * spot * 0.01;
    const strikeData = makeConcentrationStrikeData(55); // between 40 and 70
    // Verify fixture
    const conc = computeConcentration(strikeData);
    expect(conc.top3Pct).toBeGreaterThan(40);
    expect(conc.top3Pct).toBeLessThan(70);
    const data = [makeSnapshot({ netGex, spot, strikeData })];
    const result = classifyGexProfile(data);
    expect(result.labels).toContain(LABEL.BALANCED);
    // Should NOT have HIGH_CONCENTRATION or DIFFUSE
    expect(result.labels).not.toContain(LABEL.HIGH_CONCENTRATION);
    expect(result.labels).not.toContain(LABEL.DIFFUSE);
  });
});

// =============================================================================
// Level C — Config override
// =============================================================================

describe("Level C — Config override", () => {
  it("custom thresholds produce different labels", () => {
    const spot = 25000;
    const netGex = 0.3 * spot * spot * 0.01; // normalizedNetGex = 0.3
    const data = [makeSnapshot({ netGex, spot })];

    // Default: 0.3 > 0.1 → POSITIVE_MODERATE
    const defaultResult = classifyGexProfile(data);
    expect(defaultResult.labels).toContain(LABEL.POSITIVE_MODERATE);

    // Override: set strong threshold to 0.2 → 0.3 > 0.2 → POSITIVE_DOMINANT
    const customResult = classifyGexProfile(data, { netGexStrongThreshold: 0.2 });
    expect(customResult.labels).toContain(LABEL.POSITIVE_DOMINANT);
  });

  it("configUsed reflects applied thresholds", () => {
    const data = [makeSnapshot({ netGex: 5000 })];
    const result = classifyGexProfile(data, { netGexStrongThreshold: 0.99 });
    expect(result.configUsed.netGexStrongThreshold).toBe(0.99);
  });
});

// =============================================================================
// Level D — Edge cases
// =============================================================================

describe("Level D — Edge cases", () => {
  it("empty input → UNAVAILABLE", () => {
    const result = classifyGexProfile([]);
    expect(result.labels).toContain(LABEL.UNAVAILABLE);
    expect(result.status).toBe("unavailable");
    expect(result.metadata.snapshotCount).toBe(0);
  });

  it("null input → UNAVAILABLE", () => {
    const result = classifyGexProfile(null);
    expect(result.labels).toContain(LABEL.UNAVAILABLE);
  });

  it("missing spot → normalized GEX null → UNAVAILABLE for magnitude, BALANCED fallback", () => {
    // Construct directly so spot is truly null (not filled by ??)
    const snap = { netGex: 1000000, callGex: 1000000, putGex: 0, spot: null, capturedAt: "2026-08-22T09:00:00Z", strikeData: [], expiryData: [] };
    const result = classifyGexProfile([snap]);
    // normNetGex is null → labels include UNAVAILABLE
    expect(result.labels).toContain(LABEL.UNAVAILABLE);
  });

  it("confidence is always experimental", () => {
    const data = [makeSnapshot({ netGex: 5000 })];
    const result = classifyGexProfile(data);
    expect(result.confidence).toBe(PROFILE_CONFIDENCE);
    expect(result.confidence).toBe("experimental");
  });

  it("metadata includes snapshot count and timestamp", () => {
    const data = [
      makeSnapshot({ netGex: 5000, capturedAt: "2026-08-22T09:00:00Z" }),
      makeSnapshot({ netGex: 6000, capturedAt: "2026-08-22T09:05:00Z" }),
    ];
    const result = classifyGexProfile(data);
    expect(result.metadata.snapshotCount).toBe(2);
    expect(result.metadata.latestTimestamp).toBe("2026-08-22T09:05:00Z");
  });

  it("callGexShare is computed from latest snapshot", () => {
    const data = [makeSnapshot({ callGex: 7000, putGex: -3000, netGex: 4000 })];
    const result = classifyGexProfile(data);
    expect(result.callGexShare).toBeCloseTo(70, 5);
  });

  it("multiple snapshots uses the latest", () => {
    const data = [
      makeSnapshot({ netGex: 1000, capturedAt: "2026-08-22T09:00:00Z" }),
      makeSnapshot({ netGex: 5000, capturedAt: "2026-08-22T09:05:00Z" }),
    ];
    const result = classifyGexProfile(data);
    expect(result.netGex).toBe(5000);
  });
});

// =============================================================================
// Level E — Normalized GEX
// =============================================================================

describe("Level E — Normalized GEX", () => {
  it("normalized GEX removes spot² factor", () => {
    // netGex = spot² × 0.01 → normalizedNetGex = 1.0
    const spot = 25000;
    const netGex = spot * spot * 0.01;
    const data = [makeSnapshot({ netGex, spot })];
    const result = classifyGexProfile(data);
    expect(result.normalizedNetGex).toBeCloseTo(1.0, 10);
  });

  it("different spots with same netGex/spot² ratio produce same normalized value", () => {
    const ratio = 0.3;
    const spot1 = 25000;
    const spot2 = 50000;
    const data1 = [makeSnapshot({ netGex: ratio * spot1 * spot1 * 0.01, spot: spot1 })];
    const data2 = [makeSnapshot({ netGex: ratio * spot2 * spot2 * 0.01, spot: spot2 })];
    const r1 = classifyGexProfile(data1);
    const r2 = classifyGexProfile(data2);
    expect(r1.normalizedNetGex).toBeCloseTo(r2.normalizedNetGex, 5);
  });

  it("cross-spot comparability: same normalized label despite different spots", () => {
    const ratio = 0.6;
    const data1 = [makeSnapshot({ netGex: ratio * 25000 * 25000 * 0.01, spot: 25000 })];
    const data2 = [makeSnapshot({ netGex: ratio * 50000 * 50000 * 0.01, spot: 50000 })];
    const r1 = classifyGexProfile(data1);
    const r2 = classifyGexProfile(data2);
    expect(r1.labels).toContain(LABEL.POSITIVE_DOMINANT);
    expect(r2.labels).toContain(LABEL.POSITIVE_DOMINANT);
  });
});
