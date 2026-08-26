/**
 * GEX Phase 7.4d — Analytics Coordinator Tests
 *
 * Level A — Integration (full pipeline)
 * Level B — Strategy Builder interface
 * Level C — Freshness
 * Level D — Methodology consistency
 * Level E — Status propagation
 * Level F — Edge cases
 */

import { describe, it, expect } from "vitest";
import { computeGexAnalytics, FRESHNESS } from "./gexAnalytics";
import { LABEL } from "./gexProfileLabel";

// =============================================================================
// Test fixtures
// =============================================================================

const VALUATION_DATE = "2026-08-22";

/**
 * Create a full-featured snapshot with all required fields.
 */
function makeSnapshot(opts = {}) {
  const spot = opts.spot ?? 25000;
  const netGex = opts.netGex ?? 3125000;
  const callGex = opts.callGex ?? 5000000;
  const putGex = opts.putGex ?? -1875000;

  return {
    symbol: "NIFTY",
    expiry: opts.expiry ?? "2026-08-28",
    spot,
    netGex,
    callGex,
    putGex,
    availabilityStatus: "available",
    validStrikeCount: 10,
    totalStrikeCount: 10,
    chainAgeMs: 0,
    capturedAt: opts.capturedAt ?? "2026-08-22T09:00:00Z",
    strikeData: opts.strikeData ?? [
      { strike: 25000, netGex },
    ],
    expiryData: opts.expiryData ?? [
      { expiry: "2026-08-28", netGex, callGex, putGex, availabilityStatus: "available", validStrikeCount: 10, totalStrikeCount: 10 },
    ],
    methodologyMetadata: { gexVersion: opts.methodologyVersion ?? "GEX_STANDARD_V1" },
  };
}

/** Create snapshots at 5-min intervals */
function series(snapConfigs, startMs = Date.parse("2026-08-22T09:00:00Z"), intervalMs = 300_000) {
  return snapConfigs.map((cfg, i) => makeSnapshot({ ...cfg, capturedAt: new Date(startMs + i * intervalMs).toISOString() }));
}

// =============================================================================
// Level A — Integration
// =============================================================================

describe("Level A — Integration", () => {
  it("full pipeline with multiple snapshots", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000, spot: 25000 },
      { netGex: 3500, callGex: 5500, putGex: -2000, spot: 25100 },
      { netGex: 4000, callGex: 6000, putGex: -2000, spot: 25200 },
      { netGex: 4500, callGex: 6500, putGex: -2000, spot: 25300 },
      { netGex: 5000, callGex: 7000, putGex: -2000, spot: 25400 },
    ]);
    const result = computeGexAnalytics(data, { valuationDate: VALUATION_DATE });

    // Status
    expect(result.status).not.toBe("unavailable");
    expect(result.snapshotCount).toBe(5);

    // Current
    expect(result.current.netGex).toBe(5000);
    expect(result.current.spot).toBe(25400);

    // Time series
    expect(result.timeSeries.netGexSma.sma).not.toBeNull();
    expect(result.timeSeries.velocity.velocity).not.toBeNull();
    expect(result.timeSeries.volatility.volatility).not.toBeNull();

    // Percentiles
    expect(result.percentiles.gexPercentile.absolutePercentile).not.toBeNull();

    // Profile labels
    expect(result.profileLabel.labels).toBeDefined();
    expect(result.profileLabel.labels.length).toBeGreaterThan(0);

    // Expiry decomposition
    expect(result.expiryDecomposition.current).not.toBeNull();
  });

  it("convenience — works with ring buffer interface", () => {
    const buf = {
      getAll: () => series([
        { netGex: 3000, callGex: 5000, putGex: -2000 },
        { netGex: 3500, callGex: 5500, putGex: -2000 },
        { netGex: 4000, callGex: 6000, putGex: -2000 },
      ]),
    };
    const result = computeGexAnalytics(buf, { valuationDate: VALUATION_DATE });
    expect(result.snapshotCount).toBe(3);
  });
});

// =============================================================================
// Level B — Strategy Builder interface
// =============================================================================

describe("Level B — Strategy Builder interface", () => {
  it("strategyBuilderInputs has all required fields", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    const sb = result.strategyBuilderInputs;

    expect(sb).toHaveProperty("netGex");
    expect(sb).toHaveProperty("netGexSma");
    expect(sb).toHaveProperty("deltaGexSma");
    expect(sb).toHaveProperty("velocity");
    expect(sb).toHaveProperty("acceleration");
    expect(sb).toHaveProperty("volatility");
    expect(sb).toHaveProperty("gexPercentile");
    expect(sb).toHaveProperty("descriptiveZ");
    expect(sb).toHaveProperty("callGexShare");
    expect(sb).toHaveProperty("concentrationTop3");
    expect(sb).toHaveProperty("profileLabels");
    expect(sb).toHaveProperty("flipDistancePct");
    expect(sb).toHaveProperty("normalizedNetGex");
  });

  it("strategyBuilderReady with sufficient data", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.strategyBuilderReady).toBe(true);
  });

  it("strategyBuilderReady with insufficient data", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.strategyBuilderReady).toBe(false);
  });

  it("SB inputs are numbers, not strings or objects", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    const sb = result.strategyBuilderInputs;

    // Numbers or null, never strings/objects
    for (const [key, val] of Object.entries(sb)) {
      if (key === "profileLabels") {
        expect(Array.isArray(val)).toBe(true);
      } else {
        expect(val === null || typeof val === "number").toBe(true);
      }
    }
  });
});

// =============================================================================
// Level C — Freshness
// =============================================================================

describe("Level C — Freshness", () => {
  it("fresh snapshot (< 5 min) → fresh label", () => {
    const now = new Date();
    const data = [
      makeSnapshot({ netGex: 3000, capturedAt: new Date(now - 60_000).toISOString() }), // 1 min ago
      makeSnapshot({ netGex: 3500, capturedAt: new Date(now - 30_000).toISOString() }), // 30 sec ago
    ];
    const result = computeGexAnalytics(data);
    expect(result.freshnessLabel).toBe(FRESHNESS.FRESH);
  });

  it("stale snapshot (10–30 min) → stale label", () => {
    const now = new Date();
    const data = [
      makeSnapshot({ netGex: 3000, capturedAt: new Date(now - 20 * 60_000).toISOString() }),
      makeSnapshot({ netGex: 3500, capturedAt: new Date(now - 15 * 60_000).toISOString() }),
    ];
    const result = computeGexAnalytics(data);
    expect(result.freshnessLabel).toBe(FRESHNESS.STALE);
  });

  it("dataFreshnessMs is computed from capturedAt", () => {
    const now = Date.now();
    const snap = makeSnapshot({ netGex: 3000, capturedAt: new Date(now - 600_000).toISOString() });
    const result = computeGexAnalytics([snap]);
    expect(result.dataFreshnessMs).toBeGreaterThanOrEqual(590_000);
    expect(result.dataFreshnessMs).toBeLessThan(610_000);
  });
});

// =============================================================================
// Level D — Methodology consistency
// =============================================================================

describe("Level D — Methodology consistency", () => {
  it("all same version → consistent", () => {
    const data = series([
      { methodologyVersion: "GEX_STANDARD_V1", netGex: 3000, callGex: 5000, putGex: -2000 },
      { methodologyVersion: "GEX_STANDARD_V1", netGex: 3500, callGex: 5500, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.methodologyConsistency.allSameMethodology).toBe(true);
    expect(result.methodologyConsistency.versionCount).toBe(1);
  });

  it("different versions → inconsistent", () => {
    const data = series([
      { methodologyVersion: "GEX_STANDARD_V1", netGex: 3000, callGex: 5000, putGex: -2000 },
      { methodologyVersion: "GEX_STANDARD_V2", netGex: 3500, callGex: 5500, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.methodologyConsistency.allSameMethodology).toBe(false);
    expect(result.methodologyConsistency.versionCount).toBe(2);
    expect(result.methodologyConsistency.methodologyVersions).toContain("GEX_STANDARD_V1");
    expect(result.methodologyConsistency.methodologyVersions).toContain("GEX_STANDARD_V2");
  });
});

// =============================================================================
// Level E — Status propagation
// =============================================================================

describe("Level E — Status propagation", () => {
  it("empty input → unavailable", () => {
    const result = computeGexAnalytics([]);
    expect(result.status).toBe("unavailable");
    expect(result.snapshotCount).toBe(0);
  });

  it("single snapshot → partial (some metrics unavailable)", () => {
    const data = [makeSnapshot({ netGex: 3000, callGex: 5000, putGex: -2000 })];
    const result = computeGexAnalytics(data);
    expect(result.snapshotCount).toBe(1);
    // Velocity needs ≥2, acceleration needs ≥3
    expect(result.timeSeries.velocity.status).toBe("unavailable");
  });

  it("three snapshots → more metrics available", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.timeSeries.velocity.status).not.toBe("unavailable");
    expect(result.timeSeries.netGexSma.status).not.toBe("unavailable");
  });
});

// =============================================================================
// Level F — Edge cases
// =============================================================================

describe("Level F — Edge cases", () => {
  it("null input → unavailable", () => {
    const result = computeGexAnalytics(null);
    expect(result.status).toBe("unavailable");
  });

  it("decomposition computed from last two snapshots", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.decomposition).not.toBeNull();
    expect(result.decomposition.total).toBeCloseTo(1000, 0);
  });

  it("migration computed from last two snapshots", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000, strikeData: [{ strike: 25000, netGex: 3000 }] },
      { netGex: 4000, callGex: 6000, putGex: -2000, strikeData: [{ strike: 25000, netGex: 4000 }] },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.migration).not.toBeNull();
  });

  it("valuationDate is optional for expiry decomposition", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
    ]);
    const resultWithout = computeGexAnalytics(data);
    expect(resultWithout.expiryDecomposition.status).toBe("unavailable");
  });

  it("profileLabels is an array of strings", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
      { netGex: 4000, callGex: 6000, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(Array.isArray(result.profileLabel.labels)).toBe(true);
    for (const label of result.profileLabel.labels) {
      expect(typeof label).toBe("string");
    }
  });

  it("confidence is always experimental", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3500, callGex: 5500, putGex: -2000 },
    ]);
    const result = computeGexAnalytics(data);
    expect(result.profileLabel.confidence).toBe("experimental");
  });
});
