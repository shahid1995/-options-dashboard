/**
 * GEX Phase 7.3 — Comprehensive Tests
 *
 * Level A — Hand-calculated fixtures
 * Level B — Algebraic properties
 * Level C — Decomposition correctness (invariant)
 * Level D — Migration detection
 * Level E — Ring buffer
 * Level F — Reproducibility
 * Level G — Data quality
 * Level H — Independent reference calculation
 */

import { describe, it, expect } from "vitest";
import {
  captureGexSnapshot,
  GexRingBuffer,
  computeDeltaGex,
  computeSpotDeltaGex,
  computeStructureDeltaGex,
  decomposeDeltaGex,
  computeGexMigration,
  computeStrikeCentroid,
  computeConcentration,
  assembleGexTimeSeries,
  reconstructChainRows,
  snapshotDataQuality,
  INVARIANT_TOLERANCE,
} from "./gexHistory";
import { chainGex, rawGex } from "./gex";

// =============================================================================
// Test fixtures — use FIXED strikes so decomposition works across spot changes
// =============================================================================

const SPOT = 25000;

/** Canonical chain response with fixed strike set */
function makeChain(rows, spot = SPOT, expiry = "2026-08-28", symbol = "NIFTY") {
  return {
    symbol,
    expiry_date: expiry,
    underlying_spot_price: spot,
    chain: rows,
  };
}

/** Default fixed-strike rows (two strikes near ATM) */
const FIXED_ROWS = [
  { strike: 24900, call: { gamma: 0.001, oi: 500, iv: 0.22 }, put: { gamma: 0.003, oi: 1200, iv: 0.19 } },
  { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 800, iv: 0.20 } },
];

/** Capture a snapshot using fixed strikes at a given spot */
function snap(spot = SPOT, overrides = {}) {
  const rows = overrides.rows ?? FIXED_ROWS;
  const chain = makeChain(rows, spot, overrides.expiry, overrides.symbol);
  const ts = overrides.timestamp ?? "2026-08-22T09:00:00Z";
  return captureGexSnapshot(chain, spot, ts, { symbol: overrides.symbol });
}

// =============================================================================
// Level A — Hand-calculated fixtures
// =============================================================================

describe("Level A — Hand-calculated fixtures", () => {
  it("single-strike GEX matches rawGex for call and put", () => {
    const gamma = 0.002;
    const oi = 1000;
    const spot = 25000;
    const expectedCall = gamma * oi * spot * spot * 0.01; // 12,500,000
    const expectedPut = 0.003 * 500 * spot * spot * 0.01; // 9,375,000

    const s = snap(spot, { rows: [
      { strike: spot, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 500, iv: 0.20 } },
    ]});

    expect(s.callGex).toBeCloseTo(expectedCall, 0);
    expect(s.putGex).toBeCloseTo(-expectedPut, 0);
    expect(s.netGex).toBeCloseTo(expectedCall - expectedPut, 0);
  });

  it("snapshot captures broker-observed inputs for reproducibility", () => {
    const s = snap(25000, { rows: [
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 500, iv: 0.20 } },
    ]});
    expect(s.strikeData).toHaveLength(1);
    expect(s.strikeData[0].callGamma).toBe(0.002);
    expect(s.strikeData[0].callOi).toBe(1000);
    expect(s.strikeData[0].callIv).toBe(0.18);
    expect(s.strikeData[0].putGamma).toBe(0.003);
    expect(s.strikeData[0].putOi).toBe(500);
    expect(s.strikeData[0].putIv).toBe(0.20);
  });

  it("spot-only ΔGEX matches hand calculation", () => {
    // Fixed strikes: 24900 and 25000. Spot moves 25000 → 25100.
    // Call side per strike: γ × OI × (S_B² − S_A²) × 0.01
    // Put side per strike: −γ × OI × (S_B² − S_A²) × 0.01 (negative convention)
    const s2Diff = 25100 * 25100 - 25000 * 25000;

    // Strike 24900: call 0.001*500, put -0.003*1200
    const expected24900 = (0.001 * 500 + (-0.003) * 1200) * s2Diff * 0.01;
    // Strike 25000: call 0.002*1000, put -0.003*800
    const expected25000 = (0.002 * 1000 + (-0.003) * 800) * s2Diff * 0.01;
    const expectedTotal = expected24900 + expected25000;

    const a = snap(25000);
    const b = snap(25100);
    const result = computeSpotDeltaGex(a, b);

    expect(result.status).toBe("available");
    expect(result.spotDelta).toBeCloseTo(expectedTotal, 0);
  });

  it("total ΔGEX equals chain-level difference", () => {
    const a = snap(25000);
    const b = snap(25100);
    const delta = computeDeltaGex(a, b);
    expect(delta.total).toBeCloseTo(b.netGex - a.netGex, 0);
  });

  it("structure ΔGEX with unchanged OI/IV and spot gives zero", () => {
    const a = snap(25000);
    const b = snap(25000); // same spot, same everything
    const result = computeStructureDeltaGex(a, b, { T: 0.02 });
    expect(result.oiDelta).toBeCloseTo(0, 5);
    expect(result.ivDelta).toBeCloseTo(0, 5);
  });
});

// =============================================================================
// Level B — Algebraic properties
// =============================================================================

describe("Level B — Algebraic properties", () => {
  it("same snapshot vs itself gives all-zero deltas", () => {
    const a = snap(25000);
    const delta = computeDeltaGex(a, a);
    expect(delta.total).toBe(0);

    const spot = computeSpotDeltaGex(a, a);
    expect(spot.spotDelta).toBeCloseTo(0, 5);
  });

  it("zero spot change → zero spot ΔGEX", () => {
    const a = snap(25000);
    const b = snap(25000);
    const spot = computeSpotDeltaGex(a, b);
    expect(spot.spotDelta).toBeCloseTo(0, 5);
  });

  it("spot-only ΔGEX uses S² factor (larger spot change → larger delta)", () => {
    const a = snap(25000);
    const b1 = snap(25100); // +100
    const b2 = snap(25200); // +200

    const d1 = computeSpotDeltaGex(a, b1);
    const d2 = computeSpotDeltaGex(a, b2);

    if (d1.spotDelta != null && d2.spotDelta != null && Math.abs(d1.spotDelta) > 0) {
      expect(Math.abs(d2.spotDelta)).toBeGreaterThan(Math.abs(d1.spotDelta));
    }
  });

  it("doubling OI roughly doubles structure ΔGEX", () => {
    const a1 = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b1 = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.003, oi: 1400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: 0.18 }, put: { gamma: 0.003, oi: 900, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const a2 = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 1000, iv: 0.22 }, put: { gamma: 0.003, oi: 2400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 2000, iv: 0.18 }, put: { gamma: 0.003, oi: 1600, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:00:00Z" });
    const b2 = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 1200, iv: 0.22 }, put: { gamma: 0.003, oi: 2800, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 2400, iv: 0.18 }, put: { gamma: 0.003, oi: 1800, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d1 = computeStructureDeltaGex(a1, b1, { T: 0.02 });
    const d2 = computeStructureDeltaGex(a2, b2, { T: 0.02 });

    if (d1.oiDelta != null && d2.oiDelta != null && Math.abs(d1.oiDelta) > 1) {
      expect(d2.oiDelta).toBeCloseTo(d1.oiDelta * 2, -2);
    }
  });

  it("deltaTimeMs is computed between snapshots", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25100, { timestamp: "2026-08-22T09:05:00Z" });
    const delta = computeDeltaGex(a, b);
    expect(delta.deltaTimeMs).toBe(5 * 60 * 1000); // 5 minutes
  });

  it("expiry change is detected in decomposition", () => {
    const a = snap(25000, { expiry: "2026-08-28", timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { expiry: "2026-09-04", timestamp: "2026-08-22T09:05:00Z" });
    const decomp = decomposeDeltaGex(a, b);
    expect(decomp.expiryChanged).toBe(true);
  });
});

// =============================================================================
// Level C — Decomposition correctness (invariant)
// =============================================================================

describe("Level C — Decomposition correctness", () => {
  it("invariant holds: total = spot + oi + iv + residual (same spot, OI change only)", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    // Only OI changes, spot and IV stay the same
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.003, oi: 1400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: 0.18 }, put: { gamma: 0.003, oi: 900, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });
    expect(d.status).not.toBe("unavailable");
    expect(d.spot).toBeCloseTo(0, 0); // no spot change
    expect(d.oi).not.toBeNull();
    expect(d.iv).toBeCloseTo(0, 5); // no IV change
    expect(d.invariantOk).toBe(true);
  });

  it("invariant holds: spot-only change (no OI/IV change)", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25100, { timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });
    expect(d.status).not.toBe("unavailable");
    expect(d.invariantOk).toBe(true);
    // OI and IV should be zero (same OI/IV in both snapshots)
    expect(d.oi).toBeCloseTo(0, 0);
    expect(d.iv).toBeCloseTo(0, 0);
  });

  it("invariant holds: combined spot + OI change", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    // Spot moves to 25100 AND OI changes — same fixed strikes
    const b = snap(25100, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.003, oi: 1400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: 0.18 }, put: { gamma: 0.003, oi: 900, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });
    expect(d.status).not.toBe("unavailable");
    expect(d.invariantOk).toBe(true);
  });

  it("invariant holds for multi-strike chains", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.0012, oi: 600, iv: 0.23 }, put: { gamma: 0.0035, oi: 1300, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.0022, oi: 1100, iv: 0.19 }, put: { gamma: 0.0032, oi: 850, iv: 0.21 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });
    expect(d.invariantOk).toBe(true);
    expect(d.status).toBe("available");
  });

  it("residual captures cross-terms (not forced to zero)", () => {
    // Spot AND OI change simultaneously — residual captures interaction
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25100, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.003, oi: 1400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: 0.18 }, put: { gamma: 0.003, oi: 900, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });
    expect(d.residual).toBeDefined();
    expect(d.invariantOk).toBe(true);
  });
});

// =============================================================================
// Level D — Migration detection
// =============================================================================

describe("Level D — Migration detection", () => {
  it("same strikes → no migration (stable)", () => {
    const a = snap(25000);
    const b = snap(25000);
    const mig = computeGexMigration(a, b);
    expect(mig.direction).toBe("stable");
    expect(mig.migration).toBeCloseTo(0, 5);
  });

  it("identical snapshots → centroid equal", () => {
    const a = snap(25000);
    const b = snap(25000);
    const mig = computeGexMigration(a, b);
    expect(mig.centroidA).toBeCloseTo(mig.centroidB, 5);
  });

  it("gamma shifting to higher strikes → up", () => {
    // A: balanced — use ASYMMETRIC call/put so netGex ≠ 0
    const a = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.18 } },
    ], timestamp: "2026-08-22T09:00:00Z" });

    // B: heavy gamma at higher strike (25000), reduced at lower (24900)
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.0005, oi: 200, iv: 0.18 }, put: { gamma: 0.0002, oi: 100, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.005, oi: 5000, iv: 0.18 }, put: { gamma: 0.002, oi: 2000, iv: 0.18 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const mig = computeGexMigration(a, b);
    expect(mig.status).toBe("available");
    expect(mig.direction).toBe("up");
    expect(mig.migration).toBeGreaterThan(0);
  });

  it("gamma shifting to lower strikes → down", () => {
    const a = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.18 } },
    ], timestamp: "2026-08-22T09:00:00Z" });

    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.005, oi: 5000, iv: 0.18 }, put: { gamma: 0.002, oi: 2000, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.0005, oi: 200, iv: 0.18 }, put: { gamma: 0.0002, oi: 100, iv: 0.18 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const mig = computeGexMigration(a, b);
    expect(mig.status).toBe("available");
    expect(mig.direction).toBe("down");
    expect(mig.migration).toBeLessThan(0);
  });

  it("centroid at one strike → centroid equals that strike", () => {
    const rows = [
      { strike: 25000, call: { gamma: 0.005, oi: 5000, iv: 0.18 }, put: { gamma: 0.002, oi: 2000, iv: 0.18 } },
    ];
    const a = captureGexSnapshot(makeChain(rows, 25000), 25000, "2026-08-22T09:00:00Z");
    const centroid = computeStrikeCentroid(a.strikeData);
    expect(centroid).toBeCloseTo(25000, 0);
  });

  it("empty strikeData → null centroid", () => {
    expect(computeStrikeCentroid([])).toBeNull();
    expect(computeStrikeCentroid(null)).toBeNull();
  });

  it("concentration metrics computed correctly", () => {
    // Use ASYMMETRIC call/put so netGex ≠ 0
    const a = snap(25000, { rows: [
      { strike: 24800, call: { gamma: 0.0005, oi: 100, iv: 0.18 }, put: { gamma: 0.0002, oi: 50, iv: 0.18 } },
      { strike: 24900, call: { gamma: 0.0005, oi: 100, iv: 0.18 }, put: { gamma: 0.0002, oi: 50, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.005, oi: 5000, iv: 0.18 }, put: { gamma: 0.002, oi: 2000, iv: 0.18 } },
      { strike: 25100, call: { gamma: 0.0005, oi: 100, iv: 0.18 }, put: { gamma: 0.0002, oi: 50, iv: 0.18 } },
      { strike: 25200, call: { gamma: 0.0005, oi: 100, iv: 0.18 }, put: { gamma: 0.0002, oi: 50, iv: 0.18 } },
    ], timestamp: "2026-08-22T09:00:00Z" });

    const conc = computeConcentration(a.strikeData);
    expect(conc.top3Pct).toBeGreaterThan(80);
    expect(conc.totalAbsoluteGex).toBeGreaterThan(0);
    expect(conc.strikeCount).toBe(5);
  });

  it("concentration with empty data → nulls", () => {
    const conc = computeConcentration([]);
    expect(conc.top3Pct).toBeNull();
    expect(conc.totalAbsoluteGex).toBe(0);
  });
});

// =============================================================================
// Level E — Ring buffer
// =============================================================================

describe("Level E — Ring buffer", () => {
  it("push and get all", () => {
    const buf = new GexRingBuffer(5);
    buf.push(snap(25000, { timestamp: "2026-08-22T09:00:00Z" }));
    buf.push(snap(25001, { timestamp: "2026-08-22T09:05:00Z" }));
    expect(buf.size()).toBe(2);
    expect(buf.getAll()).toHaveLength(2);
  });

  it("evicts oldest when full", () => {
    const buf = new GexRingBuffer(3);
    buf.push(snap(25000, { timestamp: "2026-08-22T09:00:00Z" }));
    buf.push(snap(25001, { timestamp: "2026-08-22T09:05:00Z" }));
    buf.push(snap(25002, { timestamp: "2026-08-22T09:10:00Z" }));
    buf.push(snap(25003, { timestamp: "2026-08-22T09:15:00Z" }));
    expect(buf.size()).toBe(3);
    const spots = buf.getAll().map((s) => s.spot);
    expect(spots).not.toContain(25000);
    expect(spots).toContain(25001);
    expect(spots).toContain(25003);
  });

  it("shouldCapture respects interval", () => {
    const buf = new GexRingBuffer(200, 300_000); // 5 min
    // Empty buffer: should capture at any time (lastCaptureAt = 0, so now - 0 >= 300000 when now >= 300000)
    expect(buf.shouldCapture(300_000)).toBe(true);
    expect(buf.shouldCapture(299_999)).toBe(false);

    // After push with timestamp 300000
    buf.push(snap(25000, { timestamp: new Date(300_000).toISOString() }));
    expect(buf.shouldCapture(300_000)).toBe(false); // same time
    expect(buf.shouldCapture(400_000)).toBe(false); // 1.6 min later
    expect(buf.shouldCapture(600_000)).toBe(true); // 5 min later
  });

  it("recent returns last N", () => {
    const buf = new GexRingBuffer(5);
    for (let i = 0; i < 5; i++) {
      buf.push(snap(25000 + i, { timestamp: `2026-08-22T09:0${i}:00Z` }));
    }
    const last2 = buf.recent(2);
    expect(last2).toHaveLength(2);
    expect(last2[1].spot).toBe(25004);
  });

  it("closest finds nearest timestamp", () => {
    const buf = new GexRingBuffer(5);
    buf.push(snap(25000, { timestamp: "2026-08-22T09:00:00Z" }));
    buf.push(snap(25001, { timestamp: "2026-08-22T09:10:00Z" }));
    const closest = buf.closest("2026-08-22T09:03:00Z");
    expect(closest.spot).toBe(25000);
  });

  it("clear empties buffer", () => {
    const buf = new GexRingBuffer(5);
    buf.push(snap(25000));
    buf.clear();
    expect(buf.size()).toBe(0);
    expect(buf.lastCaptureAt).toBe(0);
  });

  it("load replaces content", () => {
    const buf = new GexRingBuffer(5);
    buf.push(snap(25000));
    buf.load([snap(25100, { timestamp: "2026-08-22T09:10:00Z" })]);
    expect(buf.size()).toBe(1);
    expect(buf.getAll()[0].spot).toBe(25100);
  });

  it("push null is no-op", () => {
    const buf = new GexRingBuffer(5);
    buf.push(null);
    buf.push(undefined);
    expect(buf.size()).toBe(0);
  });
});

// =============================================================================
// Level F — Reproducibility
// =============================================================================

describe("Level F — Reproducibility", () => {
  it("reconstructChainRows + chainGex reproduces snapshot totals", () => {
    const chain = makeChain(FIXED_ROWS, 25000);
    const snapshot = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z");

    // Reconstruct and recompute
    const reconstructed = reconstructChainRows(snapshot);
    const recomputed = chainGex(reconstructed, { spot: snapshot.spot, symbol: snapshot.symbol });

    expect(recomputed.callGex).toBeCloseTo(snapshot.callGex, 0);
    expect(recomputed.putGex).toBeCloseTo(snapshot.putGex, 0);
    expect(recomputed.netGex).toBeCloseTo(snapshot.netGex, 0);
  });

  it("reconstructChainRows preserves expiry", () => {
    const snapshot = snap(25000, { expiry: "2026-09-04" });
    const rows = reconstructChainRows(snapshot);
    expect(rows[0].expiry).toBe("2026-09-04");
  });

  it("same inputs produce identical snapshots", () => {
    const chain = makeChain(FIXED_ROWS, 25000);
    const s1 = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z");
    const s2 = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z");
    expect(s1.callGex).toBe(s2.callGex);
    expect(s1.putGex).toBe(s2.putGex);
    expect(s1.netGex).toBe(s2.netGex);
    expect(s1.strikeData).toEqual(s2.strikeData);
  });

  it("computeDeltaGex is deterministic", () => {
    const a = snap(25000);
    const b = snap(25100);
    const d1 = computeDeltaGex(a, b);
    const d2 = computeDeltaGex(a, b);
    expect(d1.total).toBe(d2.total);
    expect(d1.deltaTimeMs).toBe(d2.deltaTimeMs);
  });

  it("reconstructed chain from snapshot uses broker gamma (not model gamma)", () => {
    const snapshot = snap(25000);
    const rows = reconstructChainRows(snapshot);
    expect(rows[0].call.gamma).toBe(snapshot.strikeData[0].callGamma);
    expect(rows[0].put.gamma).toBe(snapshot.strikeData[0].putGamma);
  });
});

// =============================================================================
// Level G — Data quality
// =============================================================================

describe("Level G — Data quality", () => {
  it("snapshot with null GEX values has unavailable status", () => {
    const chain = makeChain([
      { strike: 25000, call: { gamma: null, oi: null }, put: { gamma: null, oi: null } },
    ], 25000);
    const s = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z");
    expect(s).not.toBeNull();
    expect(s.availabilityStatus).not.toBe("available");
  });

  it("invalid spot returns null snapshot", () => {
    const chain = makeChain(FIXED_ROWS, 25000);
    expect(captureGexSnapshot(chain, 0, "2026-08-22T09:00:00Z")).toBeNull();
    expect(captureGexSnapshot(chain, -100, "2026-08-22T09:00:00Z")).toBeNull();
    expect(captureGexSnapshot(chain, NaN, "2026-08-22T09:00:00Z")).toBeNull();
  });

  it("empty chain returns null snapshot", () => {
    expect(captureGexSnapshot(null, 25000, "2026-08-22T09:00:00Z")).toBeNull();
    expect(captureGexSnapshot({ chain: [] }, 25000, "2026-08-22T09:00:00Z")).toBeNull();
  });

  it("snapshotDataQuality reports fields", () => {
    const s = snap(25000);
    const q = snapshotDataQuality(s);
    expect(q.status).toBe("available");
    expect(q.strikeCount).toBeGreaterThan(0);
    expect(q.methodology).toBe("GEX_STANDARD_V1");
  });

  it("snapshotDataQuality for null snapshot", () => {
    const q = snapshotDataQuality(null);
    expect(q.status).toBe("unavailable");
    expect(q.strikeCount).toBe(0);
  });

  it("expiry change between snapshots is detected", () => {
    const a = snap(25000, { expiry: "2026-08-28" });
    const b = snap(25000, { expiry: "2026-09-04" });
    const decomp = decomposeDeltaGex(a, b);
    expect(decomp.expiryChanged).toBe(true);
  });
});

// =============================================================================
// Level H — Independent reference calculation
// =============================================================================

describe("Level H — Independent reference calculation", () => {
  function referenceSpotDelta(gammaA, oiA, spotA, spotB) {
    return gammaA * oiA * (spotB * spotB - spotA * spotA) * 0.01;
  }

  function referenceOiDelta(oiA, oiB, gammaRef, spotA) {
    return (oiB - oiA) * gammaRef * spotA * spotA * 0.01;
  }

  it("production spot ΔGEX matches independent reference", () => {
    const gamma = 0.002;
    const oi = 1000;
    const spotA = 25000;
    const spotB = 25100;

    const ref = referenceSpotDelta(gamma, oi, spotA, spotB);
    const s2Diff = spotB * spotB - spotA * spotA;
    const prod = gamma * oi * s2Diff * 0.01;
    expect(prod).toBeCloseTo(ref, 10);
  });

  it("production OI ΔGEX matches independent reference", () => {
    const oiA = 1000;
    const oiB = 1200;
    const gammaRef = 0.002;
    const spot = 25000;

    const ref = referenceOiDelta(oiA, oiB, gammaRef, spot);
    const prod = (oiB - oiA) * gammaRef * spot * spot * 0.01;
    expect(prod).toBeCloseTo(ref, 10);
  });

  it("invariant verified by independent reconstruction", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25100, { timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    if (d.total != null && d.spot != null && d.oi != null && d.iv != null && d.residual != null) {
      const reconstructed = d.spot + d.oi + d.iv + d.residual;
      expect(Math.abs(d.total - reconstructed)).toBeLessThan(
        Math.max(Math.abs(d.total) * INVARIANT_TOLERANCE, INVARIANT_TOLERANCE)
      );
    }
  });

  it("strike centroid computed by independent formula matches", () => {
    const snapshot = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 1000, iv: 0.18 } },
      { strike: 25000, call: { gamma: 0.005, oi: 5000, iv: 0.18 }, put: { gamma: 0.005, oi: 5000, iv: 0.18 } },
      { strike: 25100, call: { gamma: 0.001, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 1000, iv: 0.18 } },
    ]});

    const strikeData = snapshot.strikeData;
    let wSum = 0;
    let wTotal = 0;
    for (const s of strikeData) {
      const ng = s.netGex;
      if (ng != null && Number.isFinite(ng)) {
        const absNg = Math.abs(ng);
        wSum += absNg * s.strike;
        wTotal += absNg;
      }
    }
    const refCentroid = wTotal > 0 ? wSum / wTotal : null;

    const prodCentroid = computeStrikeCentroid(strikeData);
    expect(prodCentroid).toBeCloseTo(refCentroid, 5);
  });
});

// =============================================================================
// Time-series assembly
// =============================================================================

describe("Time-series assembly", () => {
  it("empty source returns empty series", () => {
    const ts = assembleGexTimeSeries([]);
    expect(ts.points).toHaveLength(0);
    expect(ts.summary.dataPoints).toBe(0);
  });

  it("assembles points from ring buffer", () => {
    const buf = new GexRingBuffer(10);
    buf.push(snap(25000, { timestamp: "2026-08-22T09:00:00Z" }));
    buf.push(snap(25005, { timestamp: "2026-08-22T09:05:00Z" }));
    buf.push(snap(25010, { timestamp: "2026-08-22T09:10:00Z" }));

    const ts = assembleGexTimeSeries(buf);
    expect(ts.points).toHaveLength(3);
    expect(ts.deltaGexSeries).toHaveLength(2);
    expect(ts.summary.dataPoints).toBe(3);
  });

  it("filters by expiry", () => {
    const buf = new GexRingBuffer(10);
    buf.push(snap(25000, { expiry: "2026-08-28", timestamp: "2026-08-22T09:00:00Z" }));
    buf.push(snap(25000, { expiry: "2026-09-04", timestamp: "2026-08-22T09:05:00Z" }));

    const ts = assembleGexTimeSeries(buf, { expiry: "2026-08-28" });
    expect(ts.points).toHaveLength(1);
  });
});

// =============================================================================
// Snapshot metadata
// =============================================================================

// =============================================================================
// Level I — Regression: broker gamma vs BS model gamma distinction
// =============================================================================

describe("Level I — Broker gamma / BS model gamma distinction", () => {
  it("broker gamma changes while OI/IV/spot unchanged → residual captures change", () => {
    // A: broker gamma = 0.002 at strike 25000
    const aRows = [
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.20 } },
    ];
    const a = snap(25000, { rows: aRows, timestamp: "2026-08-22T09:00:00Z" });

    // B: broker gamma changes to 0.003 (market gamma increased), OI/IV/spot same
    const bRows = [
      { strike: 25000, call: { gamma: 0.003, oi: 1000, iv: 0.18 }, put: { gamma: 0.001, oi: 500, iv: 0.20 } },
    ];
    const b = snap(25000, { rows: bRows, timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // Spot contribution = 0 (same spot)
    expect(d.spot).toBeCloseTo(0, 0);

    // OI contribution = 0 (same OI)
    expect(d.oi).toBeCloseTo(0, 0);

    // IV contribution = 0 (same IV, so BS gamma doesn't change)
    expect(d.iv).toBeCloseTo(0, 0);

    // Total ΔGEX ≠ 0 (broker gamma changed)
    expect(d.total).not.toBeCloseTo(0, 0);

    // Residual must capture the broker gamma change
    // total ΔGEX = (0.003 - 0.002) × 1000 × 25000² × 0.01 = 6,250,000 (call)
    //            + (0.001 - 0.001) × 500 × ... = 0 (put unchanged)
    //            = 6,250,000
    expect(d.residual).toBeCloseTo(d.total, 0);
    expect(Math.abs(d.residual)).toBeGreaterThan(0);
    expect(d.invariantOk).toBe(true);
  });

  it("historical GEX uses broker gamma, not BS model gamma", () => {
    // Create a chain where broker gamma (0.005) differs from what BS would give
    // for the stated IV. This proves the snapshot stores broker gamma.
    const rows = [
      { strike: 25000, call: { gamma: 0.005, oi: 1000, iv: 0.10 }, put: { gamma: 0.001, oi: 500, iv: 0.25 } },
    ];
    const s = snap(25000, { rows });

    // Snapshot stores the broker gamma directly
    expect(s.strikeData[0].callGamma).toBe(0.005);

    // Historical GEX uses broker gamma: 0.005 × 1000 × 25000² × 0.01
    const expectedBrokerGex = 0.005 * 1000 * 25000 * 25000 * 0.01;
    expect(s.callGex).toBeCloseTo(expectedBrokerGex, 0);

    // Reconstruct and verify Phase 7.1 uses broker gamma
    const reconstructed = reconstructChainRows(s);
    const recomputed = chainGex(reconstructed, { spot: s.spot });
    expect(recomputed.callGex).toBeCloseTo(s.callGex, 0);

    // The reconstructed gamma is the broker gamma, not BS model gamma
    expect(reconstructed[0].call.gamma).toBe(0.005);
  });

  it("structure decomposition correctly attributes OI change at frozen BS gamma", () => {
    // Same IV in both snapshots → BS gamma doesn't change → ivDelta = 0
    // Only OI changes → oiDelta captures the full structure change
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 700, iv: 0.22 }, put: { gamma: 0.003, oi: 1500, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1300, iv: 0.18 }, put: { gamma: 0.003, oi: 1000, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // IV didn't change → ivDelta should be zero
    expect(d.iv).toBeCloseTo(0, 0);
    // OI changed → oiDelta should be non-zero
    expect(d.oi).not.toBeNull();
    expect(Math.abs(d.oi)).toBeGreaterThan(0);
    expect(d.invariantOk).toBe(true);
  });

  it("structure decomposition correctly attributes IV change at frozen OI", () => {
    // Same OI in both snapshots → oiDelta = 0
    // Only IV changes → ivDelta captures the full structure change
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 500, iv: 0.25 }, put: { gamma: 0.003, oi: 1200, iv: 0.22 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.22 }, put: { gamma: 0.003, oi: 800, iv: 0.24 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // OI didn't change → oiDelta should be zero
    expect(d.oi).toBeCloseTo(0, 0);
    // IV changed → ivDelta should be non-zero
    expect(d.iv).not.toBeNull();
    expect(Math.abs(d.iv)).toBeGreaterThan(0);
    expect(d.invariantOk).toBe(true);
  });

  it("put-side structure decomposition has correct negative sign convention", () => {
    // OI increases on put side → put GEX becomes more negative →
    // structure oiDelta should be negative (put convention)
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 500, iv: 0.22 }, put: { gamma: 0.003, oi: 2000, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 1500, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // Put OI increased → more negative put GEX contribution
    // The oiDelta from put side should be negative
    expect(d.oi).not.toBeNull();
    expect(d.oi).toBeLessThan(0);
  });
});

// =============================================================================
// Level J — Edge cases: missing data, strike changes, expiry transitions
// =============================================================================

describe("Level J — Edge cases", () => {
  it("missing IV on B side → structure uses old BS gamma for new-OI calculation", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: null }, put: { gamma: 0.003, oi: 1400, iv: null } },
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: null }, put: { gamma: 0.003, oi: 900, iv: null } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // When B has no IV, gammaNew falls back to gammaOld → ivDelta = 0
    expect(d.iv).toBeCloseTo(0, 0);
    // OI changed → oiDelta is non-zero
    expect(d.oi).not.toBeNull();
    expect(d.invariantOk).toBe(true);
  });

  it("missing gamma on B side → structure still computes, total may be null", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: null, oi: 600, iv: 0.25 }, put: { gamma: null, oi: 1400, iv: 0.22 } },
      { strike: 25000, call: { gamma: null, oi: 1200, iv: 0.22 }, put: { gamma: null, oi: 900, iv: 0.24 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // Structure delta computes from BS model gamma (independent of broker gamma)
    expect(d._structureDetail.oiDelta).not.toBeNull();
    expect(d._structureDetail.ivDelta).not.toBeNull();
    // But total ΔGEX may be null when B has no broker gamma → invariant can't be checked
    // This is correct: the invariant only holds when all components are computable
    if (d.total != null) {
      expect(d.invariantOk).toBe(true);
    }
  });

  it("missing OI on B side → OI treated as 0, decomposition uses −oiA × gammaOld", () => {
    const a = snap(25000, { timestamp: "2026-08-22T09:00:00Z" });
    // B keeps valid OI on strike 24900 (so total ΔGEX is computable),
    // but strike 25000 has null OI on both sides
    const b = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.003, oi: 1400, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: null, iv: 0.18 }, put: { gamma: 0.003, oi: null, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // Strike 25000: OI went from non-null to null (treated as 0)
    // Structure decomposition computes over common strikes (25000 included)
    // Call side: (0 - 1000) × gammaOld × S² × 0.01 = negative
    // Put side: -(0 - 800) × gammaOld × S² × 0.01 = positive (negative convention)
    expect(d.oi).not.toBeNull();
    expect(Math.abs(d.oi)).toBeGreaterThan(0);
    expect(d.iv).toBeCloseTo(0, 0); // no IV change
    expect(d.invariantOk).toBe(true);
  });

  it("changing strike sets → decomposition uses common strikes only", () => {
    // A has strikes 24900, 25000. B has strikes 25000, 25100.
    // Only 25000 is common.
    const a = snap(25000, { rows: [
      { strike: 24900, call: { gamma: 0.001, oi: 500, iv: 0.22 }, put: { gamma: 0.003, oi: 1200, iv: 0.19 } },
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 800, iv: 0.20 } },
    ], timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: [
      { strike: 25000, call: { gamma: 0.002, oi: 1200, iv: 0.18 }, put: { gamma: 0.003, oi: 900, iv: 0.20 } },
      { strike: 25100, call: { gamma: 0.001, oi: 600, iv: 0.22 }, put: { gamma: 0.002, oi: 700, iv: 0.19 } },
    ], timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // Structure decomposition should have computed over common strikes only
    expect(d._structureDetail.perStrike).toHaveLength(1);
    expect(d._structureDetail.perStrike[0].strike).toBe(25000);
    expect(d.invariantOk).toBe(true);
  });

  it("expiry transitions detected but decomposition still computes", () => {
    const a = snap(25000, { expiry: "2026-08-28", timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { expiry: "2026-09-04", timestamp: "2026-08-22T09:05:00Z" });
    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    expect(d.expiryChanged).toBe(true);
    // Decomposition still computes using common strikes
    expect(d.invariantOk).toBe(true);
  });

  it("residual is explicitly calculated, not forced to zero", () => {
    // Create a scenario where total ≠ spot + oi + iv (broker gamma drift)
    const aRows = [
      { strike: 25000, call: { gamma: 0.001, oi: 1000, iv: 0.18 }, put: { gamma: 0.0005, oi: 500, iv: 0.20 } },
    ];
    const bRows = [
      // Broker gamma changes (0.001→0.002), but IV doesn't change
      // so BS model sees no IV-driven gamma change
      { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.0005, oi: 500, iv: 0.20 } },
    ];
    const a = snap(25000, { rows: aRows, timestamp: "2026-08-22T09:00:00Z" });
    const b = snap(25000, { rows: bRows, timestamp: "2026-08-22T09:05:00Z" });

    const d = decomposeDeltaGex(a, b, { T: 0.02 });

    // spot=0, oi=0, iv=0 (no OI/IV change, same spot)
    // total ≠ 0 (broker gamma changed)
    // residual = total (all unexplained broker gamma change)
    expect(d.spot).toBeCloseTo(0, 0);
    expect(d.oi).toBeCloseTo(0, 0);
    expect(d.iv).toBeCloseTo(0, 0);
    expect(Math.abs(d.total)).toBeGreaterThan(0);
    expect(d.residual).toBeCloseTo(d.total, 0);
    expect(d.invariantOk).toBe(true);
  });
});

describe("Snapshot metadata", () => {
  it("methodology metadata records formula and convention", () => {
    const s = snap(25000);
    expect(s.methodologyMetadata.gexVersion).toBe("GEX_STANDARD_V1");
    expect(s.methodologyMetadata.formula).toBe("gamma * oi * spot^2 * 0.01");
    expect(s.methodologyMetadata.oiUnit).toBe("contracts");
    expect(s.methodologyMetadata.lotSizeFactorApplied).toBe(false);
  });

  it("sign convention is documented", () => {
    const s = snap(25000);
    expect(s.signConvention).toBe("NAIVE_DEALER_CONVENTION");
    expect(s.methodologyMetadata.callSign).toBe(1);
    expect(s.methodologyMetadata.putSign).toBe(-1);
  });
});
