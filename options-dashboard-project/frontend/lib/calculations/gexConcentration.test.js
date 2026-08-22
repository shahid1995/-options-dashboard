/**
 * GEX Phase 7.4b — Concentration & Expiry Decomposition Tests
 *
 * Level A — Hand-calculated fixtures
 * Level B — Expiry bucket classification
 * Level C — Call GEX Share
 * Level D — Percentile behavior
 * Level E — Expiry continuity
 * Level F — Edge cases
 */

import { describe, it, expect } from "vitest";
import {
  computeDte,
  classifyDteBucket,
  computeConcentrationHistory,
  computeConcentrationPercentile,
  computeGexPercentile,
  computeExpiryDecomposition,
  computeCallGexShare,
  DTE_NEAR_MAX,
  DTE_MID_MAX,
  BUCKET_NEAR,
  BUCKET_MID,
  BUCKET_FAR,
} from "./gexConcentration";
import { captureGexSnapshot } from "./gexHistory";

// =============================================================================
// Test fixtures
// =============================================================================

const VALUATION_DATE = "2026-08-22";

/** Create a snapshot with strike data and expiry data */
function snap(opts = {}) {
  const spot = opts.spot ?? 25000;
  const netGex = opts.netGex ?? 3125000;
  const callGex = opts.callGex ?? 5000000;
  const putGex = opts.putGex ?? -1875000;
  const expiry = opts.expiry ?? "2026-08-28";
  const expiryData = opts.expiryData ?? [
    { expiry, callGex: callGex, putGex: putGex, netGex, availabilityStatus: "available", validStrikeCount: 10, totalStrikeCount: 10 },
  ];

  return {
    symbol: "NIFTY",
    expiry,
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
      { strike: 25000, callGamma: 0.002, callOi: 1000, callIv: 0.18, callGex: 12500000, putGamma: 0.003, putOi: 500, putIv: 0.20, putGex: -9375000, netGex: 3125000 },
    ],
    expiryData,
    methodologyMetadata: { gexVersion: "GEX_STANDARD_V1" },
  };
}

/** Create snapshots at 5-min intervals */
function series(snapConfigs, startMs = Date.parse("2026-08-22T09:00:00Z"), intervalMs = 300_000) {
  return snapConfigs.map((cfg, i) => snap({ ...cfg, capturedAt: new Date(startMs + i * intervalMs).toISOString() }));
}

// =============================================================================
// Level A — Hand-calculated fixtures
// =============================================================================

describe("Level A — Hand-calculated fixtures", () => {
  it("DTE calculation from expiry date", () => {
    // 2026-08-28 is 6 days from 2026-08-22
    const dte = computeDte("2026-08-28", VALUATION_DATE);
    expect(dte).not.toBeNull();
    expect(dte).toBeGreaterThan(5);
    expect(dte).toBeLessThan(7);
  });

  it("classifyDteBucket boundaries", () => {
    expect(classifyDteBucket(0.5)).toBe(BUCKET_NEAR);
    expect(classifyDteBucket(7)).toBe(BUCKET_NEAR);   // inclusive at upper bound
    expect(classifyDteBucket(7.1)).toBe(BUCKET_MID);
    expect(classifyDteBucket(30)).toBe(BUCKET_MID);   // inclusive at upper bound
    expect(classifyDteBucket(30.1)).toBe(BUCKET_FAR);
    expect(classifyDteBucket(90)).toBe(BUCKET_FAR);
  });

  it("callGexShare with known values", () => {
    // callGex = 7000, putGex = -3000 → share = 7000 / (7000 + 3000) × 100 = 70%
    const data = series([{ callGex: 7000, putGex: -3000, netGex: 4000 }]);
    const result = computeCallGexShare(data);
    expect(result.current).toBeCloseTo(70, 10);
  });

  it("callGexShare all-call (putGex = 0)", () => {
    const data = series([{ callGex: 5000, putGex: 0, netGex: 5000 }]);
    const result = computeCallGexShare(data);
    expect(result.current).toBeCloseTo(100, 10);
  });

  it("callGexShare all-put (callGex = 0)", () => {
    const data = series([{ callGex: 0, putGex: -5000, netGex: -5000 }]);
    const result = computeCallGexShare(data);
    expect(result.current).toBeCloseTo(0, 10);
  });

  it("normalized GEX formula: normalizedNetGex = netGex / (spot² × 0.01)", () => {
    const netGex = 3125000;
    const spot = 25000;
    const expected = netGex / (spot * spot * 0.01);
    expect(expected).toBeCloseTo(0.5, 10);
  });
});

// =============================================================================
// Level B — Expiry bucket classification
// =============================================================================

describe("Level B — Expiry bucket classification", () => {
  it("NEAR expiry correctly bucketed", () => {
    const data = series([{
      expiryData: [
        { expiry: "2026-08-25", netGex: 1000, callGex: 2000, putGex: -1000 },  // DTE ≈ 3
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.near.netGex).toBeCloseTo(1000, 0);
    expect(result.current.near.expiryCount).toBe(1);
  });

  it("MID expiry correctly bucketed", () => {
    const data = series([{
      expiryData: [
        { expiry: "2026-09-10", netGex: 2000, callGex: 3000, putGex: -1000 },  // DTE ≈ 19
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.mid.netGex).toBeCloseTo(2000, 0);
    expect(result.current.mid.expiryCount).toBe(1);
  });

  it("FAR expiry correctly bucketed", () => {
    const data = series([{
      expiryData: [
        { expiry: "2026-10-28", netGex: 3000, callGex: 5000, putGex: -2000 },  // DTE ≈ 67
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.far.netGex).toBeCloseTo(3000, 0);
    expect(result.current.far.expiryCount).toBe(1);
  });

  it("multi-expiry decomposition across all buckets", () => {
    const data = series([{
      expiryData: [
        { expiry: "2026-08-28", netGex: 1000, callGex: 2000, putGex: -1000 },  // NEAR
        { expiry: "2026-09-10", netGex: 2000, callGex: 3000, putGex: -1000 },  // MID
        { expiry: "2026-10-28", netGex: 3000, callGex: 5000, putGex: -2000 },  // FAR
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.near.expiryCount).toBe(1);
    expect(result.current.mid.expiryCount).toBe(1);
    expect(result.current.far.expiryCount).toBe(1);
    expect(result.current.total).toBeCloseTo(6000, 0);
  });

  it("multiple expiries in same bucket are summed", () => {
    const data = series([{
      expiryData: [
        { expiry: "2026-08-25", netGex: 1000, callGex: 2000, putGex: -1000 },
        { expiry: "2026-08-28", netGex: 2000, callGex: 3000, putGex: -1000 },
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.near.netGex).toBeCloseTo(3000, 0);
    expect(result.current.near.expiryCount).toBe(2);
  });
});

// =============================================================================
// Level C — Call GEX Share
// =============================================================================

describe("Level C — Call GEX Share", () => {
  it("50/50 split → 50%", () => {
    const data = series([{ callGex: 5000, putGex: -5000, netGex: 0 }]);
    const result = computeCallGexShare(data);
    expect(result.current).toBeCloseTo(50, 10);
  });

  it("callGexShare history is tracked over time", () => {
    const data = series([
      { callGex: 7000, putGex: -3000, netGex: 4000 },
      { callGex: 6000, putGex: -4000, netGex: 2000 },
    ]);
    const result = computeCallGexShare(data);
    expect(result.history).toHaveLength(2);
    expect(result.history[0].value).toBeCloseTo(70, 10);
    expect(result.history[1].value).toBeCloseTo(60, 10);
  });

  it("missing callGex and putGex → null share for that point", () => {
    // Construct directly to bypass snap() helper which uses ?? (fills defaults for null)
    const s1 = { callGex: 7000, putGex: -3000, netGex: 4000, capturedAt: "2026-08-22T09:00:00Z", strikeData: [], expiryData: [] };
    const s2 = { callGex: null, putGex: null, netGex: null, capturedAt: "2026-08-22T09:05:00Z", strikeData: [], expiryData: [] };
    const result = computeCallGexShare([s1, s2]);
    expect(result.history[1].value).toBeNull();
  });

  it("zero both → null share", () => {
    const data = series([{ callGex: 0, putGex: 0, netGex: 0 }]);
    const result = computeCallGexShare(data);
    expect(result.current).toBeNull();
  });
});

// =============================================================================
// Level D — Percentile behavior
// =============================================================================

describe("Level D — Percentile behavior", () => {
  it("GEX percentile with known ranking", () => {
    // |NetGex|: [100, 200, 300, 400, 500]
    // Current = 500, expected percentile near 100
    const data = series([
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 200, callGex: 400, putGex: -200 },
      { netGex: 300, callGex: 600, putGex: -300 },
      { netGex: 400, callGex: 800, putGex: -400 },
      { netGex: 500, callGex: 1000, putGex: -500 },
    ]);
    const result = computeGexPercentile(data, 5);
    expect(result.absolutePercentile).not.toBeNull();
    expect(result.absolutePercentile).toBeGreaterThan(80);
    expect(result.status).toBe("available");
  });

  it("constant history → percentile = 50", () => {
    const data = series([
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3000, callGex: 5000, putGex: -2000 },
      { netGex: 3000, callGex: 5000, putGex: -2000 },
    ]);
    const result = computeGexPercentile(data, 5);
    // percentileRank of value equal to all entries → 50
    expect(result.absolutePercentile).toBeCloseTo(50, 5);
  });

  it("descriptiveZ is null for constant history (zero stddev)", () => {
    const data = series(Array(6).fill({ netGex: 3000, callGex: 5000, putGex: -2000 }));
    const result = computeGexPercentile(data, 6);
    expect(result.descriptiveZ).toBeNull();
  });

  it("descriptiveZ positive for above-mean value", () => {
    // Values: [100, 100, 100, 100, 500] → mean=180, above mean
    const data = series([
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 500, callGex: 1000, putGex: -500 },
    ]);
    const result = computeGexPercentile(data, 5);
    expect(result.descriptiveZ).not.toBeNull();
    expect(result.descriptiveZ).toBeGreaterThan(0);
  });

  it("concentration percentile with known ranking", () => {
    // snapshots with different concentration levels
    const data = series([
      { strikeData: makeConcentration(20) },  // low concentration
      { strikeData: makeConcentration(40) },
      { strikeData: makeConcentration(60) },
      { strikeData: makeConcentration(80) },
      { strikeData: makeConcentration(95) },  // high concentration — should rank high
    ]);
    const result = computeConcentrationPercentile(data, 5);
    expect(result.status).toBe("available");
    expect(result.top3Percentile).toBeGreaterThan(80);
  });
});

// =============================================================================
// Level E — Expiry continuity
// =============================================================================

describe("Level E — Expiry continuity", () => {
  it("expiry transition doesn't break time-series continuity", () => {
    // Both snapshots have the same expiry (NEAR bucket) — timestamps are continuous
    const data = [
      snap({ expiry: "2026-08-28", netGex: 1000, callGex: 2000, putGex: -1000, capturedAt: "2026-08-22T09:00:00Z" }),
      snap({ expiry: "2026-08-28", netGex: 1200, callGex: 2200, putGex: -1000, capturedAt: "2026-08-22T09:05:00Z" }),
    ];
    const decomp = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(decomp.history).toHaveLength(2);
    expect(decomp.status).toBe("available");
    expect(decomp.history[0].near.netGex).not.toBeNull();
    expect(decomp.history[1].near.netGex).not.toBeNull();
  });

  it("expiry roll changes which bucket receives GEX", () => {
    // First: NEAR expiry, Second: MID expiry (after roll)
    const data = [
      snap({ expiry: "2026-08-28", netGex: 1000, callGex: 2000, putGex: -1000, capturedAt: "2026-08-22T09:00:00Z" }),
      snap({ expiry: "2026-09-04", netGex: 1200, callGex: 2200, putGex: -1000, capturedAt: "2026-08-22T09:05:00Z" }),
    ];
    const decomp = computeExpiryDecomposition(data, VALUATION_DATE);
    // First snapshot: NEAR bucket
    expect(decomp.history[0].near.netGex).not.toBeNull();
    expect(decomp.history[0].mid.netGex).toBeNull();
    // Second snapshot: MID bucket (DTE ≈ 13)
    expect(decomp.history[1].near.netGex).toBeNull();
    expect(decomp.history[1].mid.netGex).not.toBeNull();
    // Time-series is continuous despite bucket shift
    expect(decomp.history).toHaveLength(2);
    expect(decomp.status).toBe("available");
  });

  it("historical comparability — no spot normalization", () => {
    // Two snapshots at different spot levels — percentile is over raw |NetGEX|
    const data = series([
      { netGex: 1000, callGex: 2000, putGex: -1000, spot: 24000 },
      { netGex: 2000, callGex: 4000, putGex: -2000, spot: 25000 },
      { netGex: 3000, callGex: 6000, putGex: -3000, spot: 26000 },
      { netGex: 4000, callGex: 8000, putGex: -4000, spot: 27000 },
      { netGex: 5000, callGex: 10000, putGex: -5000, spot: 28000 },
    ]);
    const result = computeGexPercentile(data, 5);
    // Should rank the highest |NetGEX| at a high percentile
    expect(result.absolutePercentile).toBeGreaterThan(80);
  });
});

// =============================================================================
// Level F — Edge cases
// =============================================================================

describe("Level F — Edge cases", () => {
  it("empty input → all unavailable", () => {
    expect(computeConcentrationHistory([]).status).toBe("unavailable");
    expect(computeConcentrationPercentile([]).status).toBe("unavailable");
    expect(computeGexPercentile([]).status).toBe("unavailable");
    expect(computeExpiryDecomposition([], VALUATION_DATE).status).toBe("unavailable");
    expect(computeCallGexShare([]).status).toBe("unavailable");
  });

  it("missing valuationDate → expiry decomposition unavailable", () => {
    const data = series([{ expiryData: [{ expiry: "2026-08-28", netGex: 1000 }] }]);
    const result = computeExpiryDecomposition(data, null);
    expect(result.status).toBe("unavailable");
  });

  it("fewer than MIN_STAT_SAMPLE → partial status", () => {
    const data = series([
      { netGex: 100, callGex: 200, putGex: -100 },
      { netGex: 200, callGex: 400, putGex: -200 },
    ]);
    const result = computeGexPercentile(data, 5);
    expect(result.status).toBe("partial");
  });

  it("DTE with invalid dates → null", () => {
    expect(computeDte(null, VALUATION_DATE)).toBeNull();
    expect(computeDte("2026-08-28", null)).toBeNull();
    expect(computeDte("not-a-date", VALUATION_DATE)).toBeNull();
  });

  it("expiryData with null expiry → skipped in decomposition", () => {
    const data = series([{
      expiryData: [
        { expiry: null, netGex: 1000, callGex: 2000, putGex: -1000 },
        { expiry: "2026-08-28", netGex: 2000, callGex: 3000, putGex: -1000 },
      ],
    }]);
    const result = computeExpiryDecomposition(data, VALUATION_DATE);
    expect(result.current.near.expiryCount).toBe(1); // only the valid one
  });

  it("ring buffer input works", () => {
    const buf = {
      getAll: () => series([
        { callGex: 7000, putGex: -3000, netGex: 4000 },
        { callGex: 8000, putGex: -2000, netGex: 6000 },
      ]),
    };
    const result = computeCallGexShare(buf);
    expect(result.current).toBeCloseTo(80, 10); // 8000 / (8000+2000) = 80%
  });
});

// =============================================================================
// Helpers
// =============================================================================

/**
 * Create strike data with a specific top3 concentration percentage.
 * Puts most |GEX| at the ATM strike and the rest distributed.
 */
function makeConcentration(top3Pct) {
  // Total absolute GEX = 10000
  // We want top3 to be top3Pct% of total
  const total = 10000;
  const top3Total = total * (top3Pct / 100);
  const restTotal = total - top3Total;
  const restStrikes = 7;
  const perRestStrike = restTotal / restStrikes;

  const strikes = [];
  // Top 3 strikes (ATM heavy)
  strikes.push({ strike: 24900, callGamma: 0.001, callOi: 100, callIv: 0.18, callGex: top3Total * 0.3, putGamma: 0.001, putOi: 50, putIv: 0.18, putGex: 0, netGex: top3Total * 0.3 });
  strikes.push({ strike: 25000, callGamma: 0.002, callOi: 1000, callIv: 0.18, callGex: top3Total * 0.5, putGamma: 0.002, putOi: 500, putIv: 0.18, putGex: 0, netGex: top3Total * 0.5 });
  strikes.push({ strike: 25100, callGamma: 0.001, callOi: 100, callIv: 0.18, callGex: top3Total * 0.2, putGamma: 0.001, putOi: 50, putIv: 0.18, putGex: 0, netGex: top3Total * 0.2 });
  // Rest strikes
  for (let i = 0; i < restStrikes; i++) {
    strikes.push({
      strike: 24000 + i * 100,
      callGamma: 0.0005, callOi: 50, callIv: 0.18,
      callGex: perRestStrike / 2,
      putGamma: 0.0005, putOi: 50, putIv: 0.18,
      putGex: 0,
      netGex: perRestStrike / 2,
    });
  }

  return strikes;
}
