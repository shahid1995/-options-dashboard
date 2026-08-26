/**
 * GEX Phase 7.2 — Gamma Flip & Gamma Walls Tests (CORRECTED)
 *
 * Five levels of validation per GEX_V1_0_SPEC:
 *   Level A — Hand-calculated fixtures
 *   Level B — Algebraic / mathematical properties
 *   Level C — Zero-crossing detection correctness
 *   Level D — Gamma wall detection (directional)
 *   Level E — Integration / edge cases
 *
 * Corrections applied per review:
 *   1. Directional wall semantics with spot preference and signed GEX
 *   2. Crossing-strength metadata and multi-factor primary flip ranking
 *   3. Per-expiry T (not global T)
 *   4. Call/put gamma symmetry test
 */

import { describe, it, expect } from "vitest";
import {
  modelGamma,
  netGexAtSpot,
  detectZeroCrossings,
  findGammaWalls,
  crossingStrength,
  brokerVsModelGamma,
  sweepDataQuality,
  spotSweep,
  selectPrimaryFlip,
  GEX_PHASE72_VERSION,
  DEFAULT_SWEEP_RANGE_PCT,
  DEFAULT_SWEEP_STEPS,
  DEFAULT_WALL_TOP_N,
} from "./gexPhase72";

// =============================================================================
// Level A — Hand-calculated fixtures
// =============================================================================

describe("Level A — Hand-calculated fixtures", () => {
  describe("modelGamma", () => {
    it("BS gamma is always positive for valid calls", () => {
      const T = 7 / 365;
      const gamma = modelGamma("call", 25000, 25000, T, 0.18, 0.065, 0);
      expect(gamma).toBeGreaterThan(0);
      expect(Number.isFinite(gamma)).toBe(true);
    });

    it("BS gamma is always positive for valid puts", () => {
      const T = 7 / 365;
      const gamma = modelGamma("put", 25000, 25000, T, 0.18, 0.065, 0);
      expect(gamma).toBeGreaterThan(0);
      expect(Number.isFinite(gamma)).toBe(true);
    });

    it("ATM gamma is highest; deeper OTM options have smaller gamma", () => {
      const T = 14 / 365;
      const S = 25000;
      const sigma = 0.18;
      const atm = modelGamma("call", S, S, T, sigma);
      const otm1 = modelGamma("call", S, S + 500, T, sigma);
      const otm2 = modelGamma("call", S, S + 1000, T, sigma);
      expect(atm).toBeGreaterThan(otm1);
      expect(otm1).toBeGreaterThan(otm2);
    });

    it("call gamma ≈ put gamma at same strike (BS identity)", () => {
      const T = 7 / 365;
      const S = 25000;
      const K = 25000;
      const sigma = 0.18;
      const callG = modelGamma("call", S, K, T, sigma);
      const putG = modelGamma("put", S, K, T, sigma);
      // BS identity: call gamma = put gamma = N'(d1) / (S × σ × √T)
      expect(callG).toBeCloseTo(putG, 10);
    });

    it("gamma → 0 as T → 0 (at expiry)", () => {
      expect(modelGamma("call", 25000, 25000, 0, 0.18)).toBe(0);
    });

    it("gamma is null for invalid inputs", () => {
      expect(modelGamma("call", -1, 25000, 7 / 365, 0.18)).toBeNull();
      expect(modelGamma("call", 25000, -1, 7 / 365, 0.18)).toBeNull();
      expect(modelGamma("call", 25000, 25000, -1, 0.18)).toBeNull();
      expect(modelGamma("call", 25000, 25000, 7 / 365, -1)).toBeNull();
      expect(modelGamma("call", NaN, 25000, 7 / 365, 0.18)).toBeNull();
      expect(modelGamma("call", Infinity, 25000, 7 / 365, 0.18)).toBeNull();
    });
  });

  describe("netGexAtSpot — single strike", () => {
    it("matches hand calculation for single ATM strike", () => {
      const T = 7 / 365;
      const S = 25000;
      const K = 25000;
      const sigma = 0.18;
      const rows = [{ strike: K, call: { gamma: 0.002, oi: 1000, iv: sigma }, put: { gamma: 0.003, oi: 500, iv: sigma } }];

      const result = netGexAtSpot(rows, S, T, 0, 0);
      const callG = modelGamma("call", S, K, T, sigma);
      const putG = modelGamma("put", S, K, T, sigma);

      expect(result.callGex).toBeCloseTo(callG * 1000 * S * S * 0.01, 5);
      expect(result.putGex).toBeCloseTo(-(putG * 500 * S * S * 0.01), 5);
      expect(result.netGex).toBeCloseTo(result.callGex + result.putGex, 5);
      expect(result.validStrikeCount).toBe(1);
    });

    it("scales linearly with OI (doubling OI doubles GEX)", () => {
      const T = 7 / 365;
      const S = 25000;
      const sigma = 0.18;
      const rows1 = [{ strike: 25000, call: { oi: 100, iv: sigma }, put: { oi: 100, iv: sigma } }];
      const rows2 = [{ strike: 25000, call: { oi: 200, iv: sigma }, put: { oi: 200, iv: sigma } }];

      const r1 = netGexAtSpot(rows1, S, T, 0, 0);
      const r2 = netGexAtSpot(rows2, S, T, 0, 0);
      expect(r2.callGex).toBeCloseTo(2 * r1.callGex, 5);
      expect(r2.putGex).toBeCloseTo(2 * r1.putGex, 5);
    });

    it("call GEX is always positive", () => {
      const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 0, iv: 0 } }];
      expect(netGexAtSpot(rows, 25000, 7 / 365, 0, 0).callGex).toBeGreaterThan(0);
    });

    it("put GEX is always negative (NAIVE_DEALER_CONVENTION)", () => {
      const rows = [{ strike: 25000, call: { oi: 0, iv: 0 }, put: { oi: 1000, iv: 0.18 } }];
      expect(netGexAtSpot(rows, 25000, 7 / 365, 0, 0).putGex).toBeLessThan(0);
    });
  });

  describe("multi-strike", () => {
    it("chain-level GEX is sum of strike-level GEX", () => {
      const T = 7 / 365;
      const S = 25000;
      const sigma = 0.18;
      const strikes = [24000, 24500, 25000, 25500, 26000];
      const rows = strikes.map((k) => ({ strike: k, call: { oi: 500, iv: sigma }, put: { oi: 500, iv: sigma } }));

      const result = netGexAtSpot(rows, S, T, 0, 0);
      let sumCall = 0, sumPut = 0;
      for (const k of strikes) {
        const single = netGexAtSpot([rows.find((r) => r.strike === k)], S, T, 0, 0);
        sumCall += single.callGex;
        sumPut += single.putGex;
      }
      expect(result.callGex).toBeCloseTo(sumCall, 3);
      expect(result.putGex).toBeCloseTo(sumPut, 3);
    });
  });
});

// =============================================================================
// Level B — Algebraic / mathematical properties
// =============================================================================

describe("Level B — Algebraic properties", () => {
  it("net GEX(S) varies with spot (S² factor and gamma dynamics)", () => {
    const T = 1; // long-dated → flatter gamma → S² dominates
    const sigma = 0.18;
    const rows = [{ strike: 25000, call: { oi: 1000, iv: sigma }, put: { oi: 0, iv: 0 } }];
    const r1 = netGexAtSpot(rows, 25000, T, 0, 0);
    const r2 = netGexAtSpot(rows, 26000, T, 0, 0);
    expect(r1.callGex).toBeGreaterThan(0);
    expect(r2.callGex).toBeGreaterThan(0);
    expect(r1.callGex).not.toBeCloseTo(r2.callGex, 5);
  });

  it("doubling OI doubles net GEX at every spot", () => {
    const T = 7 / 365;
    const sigma = 0.18;
    const rows1 = [
      { strike: 25000, call: { oi: 100, iv: sigma }, put: { oi: 200, iv: sigma } },
      { strike: 24500, call: { oi: 150, iv: sigma }, put: { oi: 100, iv: sigma } },
    ];
    const rows2 = rows1.map((r) => ({ ...r, call: { ...r.call, oi: r.call.oi * 2 }, put: { ...r.put, oi: r.put.oi * 2 } }));
    const r1 = netGexAtSpot(rows1, 25000, T, 0, 0);
    const r2 = netGexAtSpot(rows2, 25000, T, 0, 0);
    expect(r2.callGex).toBeCloseTo(2 * r1.callGex, 5);
    expect(r2.putGex).toBeCloseTo(2 * r1.putGex, 5);
    expect(r2.netGex).toBeCloseTo(2 * r1.netGex, 5);
  });

  it("zero OI gives zero GEX", () => {
    const rows = [{ strike: 25000, call: { oi: 0, iv: 0.18 }, put: { oi: 0, iv: 0.18 } }];
    const r = netGexAtSpot(rows, 25000, 7 / 365, 0, 0);
    expect(r.callGex).toBe(0);
    expect(r.putGex).toBe(0);
  });

  it("missing IV gives zero contribution for that side", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: null }, put: { oi: 1000, iv: 0.18 } }];
    const r = netGexAtSpot(rows, 25000, 7 / 365, 0, 0);
    expect(r.callGex).toBe(0);
    expect(r.putGex).toBeLessThan(0);
  });
});

// =============================================================================
// Level C — Zero-crossing detection
// =============================================================================

describe("Level C — Zero-crossing detection", () => {
  it("detects a simple positive-to-negative crossing", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 24500, netGex: 50 },
      { spot: 25000, netGex: -50 },
      { spot: 25500, netGex: -100 },
    ];
    const crossings = detectZeroCrossings(points);
    expect(crossings.length).toBe(1);
    expect(crossings[0].crossingSpot).toBeGreaterThan(24500);
    expect(crossings[0].crossingSpot).toBeLessThan(25000);
    expect(crossings[0].crossingSpot).toBeCloseTo(24750, 0);
  });

  it("detects a negative-to-positive crossing", () => {
    const points = [
      { spot: 24000, netGex: -100 },
      { spot: 25000, netGex: 100 },
    ];
    const crossings = detectZeroCrossings(points);
    expect(crossings.length).toBe(1);
    expect(crossings[0].crossingSpot).toBeCloseTo(24500, 0);
  });

  it("detects multiple crossings", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 24500, netGex: -50 },
      { spot: 25000, netGex: 80 },
      { spot: 25500, netGex: -120 },
    ];
    const crossings = detectZeroCrossings(points);
    // 3 sign changes: +→- (24000→24500), -→+ (24500→25000), +→- (25000→25500)
    expect(crossings.length).toBe(3);
  });

  it("returns empty array when no crossing exists", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 24500, netGex: 150 },
      { spot: 25000, netGex: 200 },
    ];
    expect(detectZeroCrossings(points).length).toBe(0);
  });

  it("handles exact zero values", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 25000, netGex: 0 },
      { spot: 26000, netGex: -100 },
    ];
    const crossings = detectZeroCrossings(points);
    expect(crossings.length).toBeGreaterThanOrEqual(1);
    const at25k = crossings.find((c) => c.crossingSpot === 25000);
    expect(at25k).toBeDefined();
  });

  it("handles null/NaN gracefully", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 24500, netGex: null },
      { spot: 25000, netGex: -100 },
    ];
    expect(detectZeroCrossings(points).length).toBe(0);
  });

  it("handles empty and single-point input", () => {
    expect(detectZeroCrossings([]).length).toBe(0);
    expect(detectZeroCrossings([{ spot: 25000, netGex: 100 }]).length).toBe(0);
  });

  it("interpolation is accurate for uniform grid", () => {
    const points = [];
    for (let s = 100; s <= 200; s += 10) {
      points.push({ spot: s, netGex: 100 - 2 * (s - 100) });
    }
    const crossings = detectZeroCrossings(points);
    expect(crossings.length).toBe(1);
    expect(crossings[0].crossingSpot).toBeCloseTo(150, 0);
  });

  it("crossing includes transitionMagnitude", () => {
    const points = [
      { spot: 24000, netGex: 100 },
      { spot: 25000, netGex: -50 },
    ];
    const crossings = detectZeroCrossings(points);
    expect(crossings[0].transitionMagnitude).toBe(150); // |100| + |-50|
  });
});

// =============================================================================
// Level D — Gamma wall detection (directional)
// =============================================================================

describe("Level D — Directional gamma wall detection", () => {
  it("call walls prefer strikes at/above current spot", () => {
    const data = [
      { strike: 24000, callGex: 300, putGex: null, netGex: null },
      { strike: 24500, callGex: 100, putGex: null, netGex: null },
      { strike: 25000, callGex: 250, putGex: null, netGex: null },
      { strike: 25500, callGex: 400, putGex: null, netGex: null },
      { strike: 26000, callGex: 150, putGex: null, netGex: null },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    expect(walls.callWalls.length).toBeLessThanOrEqual(3);
    // 25500 has highest magnitude (400) and is above spot → should rank first
    expect(walls.callWalls[0].strike).toBe(25500);
    expect(walls.callWalls[0].signedGex).toBe(400);
    expect(walls.callWalls[0].positionPreference).toBe(true);
  });

  it("put walls prefer strikes at/below current spot", () => {
    const data = [
      { strike: 24000, callGex: null, putGex: -100, netGex: null },
      { strike: 24500, callGex: null, putGex: -400, netGex: null },
      { strike: 25000, callGex: null, putGex: -200, netGex: null },
      { strike: 25500, callGex: null, putGex: -50, netGex: null },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    expect(walls.putWalls.length).toBeGreaterThanOrEqual(1);
    // 24500 has highest magnitude (400) and is below spot → should rank first
    expect(walls.putWalls[0].strike).toBe(24500);
    expect(walls.putWalls[0].signedGex).toBe(-400);
    expect(walls.putWalls[0].positionPreference).toBe(true);
  });

  it("walls preserve signed GEX value (not absolute)", () => {
    const data = [
      { strike: 25000, callGex: 500, putGex: -300, netGex: 200 },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    expect(walls.callWalls[0].signedGex).toBe(500);
    expect(walls.putWalls[0].signedGex).toBe(-300);
  });

  it("returns top-N candidates (not all local maxima)", () => {
    // 5 local maxima but topN=2
    const data = [
      { strike: 24000, callGex: 100, putGex: null, netGex: null },
      { strike: 24500, callGex: 300, putGex: null, netGex: null },
      { strike: 25000, callGex: 150, putGex: null, netGex: null },
      { strike: 25500, callGex: 400, putGex: null, netGex: null },
      { strike: 26000, callGex: 200, putGex: null, netGex: null },
    ];
    const walls = findGammaWalls(data, 25000, 2);
    expect(walls.callWalls.length).toBeLessThanOrEqual(2);
  });

  it("finds net walls using absolute net GEX", () => {
    const data = [
      { strike: 24000, callGex: 100, putGex: -50, netGex: 50 },
      { strike: 24500, callGex: 50, putGex: -300, netGex: -250 },
      { strike: 25000, callGex: 80, putGex: -100, netGex: -20 },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    expect(walls.netWalls.length).toBeGreaterThanOrEqual(1);
    const wall24500 = walls.netWalls.find((w) => w.strike === 24500);
    expect(wall24500).toBeDefined();
    expect(wall24500.magnitude).toBe(250);
    expect(wall24500.netGex).toBe(-250);
  });

  it("handles empty and null input", () => {
    const w1 = findGammaWalls([]);
    expect(w1.callWalls).toEqual([]);
    const w2 = findGammaWalls(null);
    expect(w2.callWalls).toEqual([]);
  });

  it("handles null values in GEX data", () => {
    const data = [
      { strike: 24000, callGex: null, putGex: null, netGex: null },
      { strike: 24500, callGex: 100, putGex: null, netGex: null },
      { strike: 25000, callGex: null, putGex: null, netGex: null },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    expect(walls.callWalls.length).toBe(1);
    expect(walls.callWalls[0].strike).toBe(24500);
  });

  it("marks global maximum correctly", () => {
    const data = [
      { strike: 24000, callGex: 500, putGex: null, netGex: null },
      { strike: 24500, callGex: 200, putGex: null, netGex: null },
      { strike: 25000, callGex: 300, putGex: null, netGex: null },
    ];
    const walls = findGammaWalls(data, 25000, 3);
    const globals = walls.callWalls.filter((w) => w.isGlobalMax);
    expect(globals.length).toBe(1);
    expect(globals[0].strike).toBe(24000);
  });

  it("when spot is null, positionPreference is null for all walls", () => {
    const data = [
      { strike: 24000, callGex: 300, putGex: null, netGex: null },
      { strike: 26000, callGex: 200, putGex: null, netGex: null },
    ];
    const walls = findGammaWalls(data, null, 3);
    expect(walls.callWalls[0].positionPreference).toBeNull();
  });
});

// =============================================================================
// Level E — Broker vs model comparison
// =============================================================================

describe("Level E — Broker vs model gamma comparison", () => {
  it("returns empty for empty input", () => {
    const r = brokerVsModelGamma([], 25000, 7 / 365, 0, 0);
    expect(r.comparisons.length).toBe(0);
  });

  it("computes comparison for each option with gamma and IV", () => {
    const T = 7 / 365;
    const sigma = 0.18;
    const rows = [{ strike: 25000, call: { gamma: 0.002, iv: sigma }, put: { gamma: 0.003, iv: sigma } }];
    const r = brokerVsModelGamma(rows, 25000, T, 0, 0);
    expect(r.comparisons.length).toBe(2);
    expect(r.comparisons[0].side).toBe("call");
    expect(r.comparisons[1].side).toBe("put");
  });

  it("model gamma matches broker gamma when broker uses BS model gamma", () => {
    const T = 7 / 365;
    const sigma = 0.18;
    const modelG = modelGamma("call", 25000, 25000, T, sigma);
    const rows = [{ strike: 25000, call: { gamma: modelG, iv: sigma }, put: { gamma: null, iv: null } }];
    const r = brokerVsModelGamma(rows, 25000, T, 0, 0);
    expect(r.comparisons[0].absDiff).toBeCloseTo(0, 8);
  });
});

// =============================================================================
// Level F — Primary flip selection (multi-factor)
// =============================================================================

describe("Level F — Multi-factor primary flip selection", () => {
  it("returns null for no crossings", () => {
    expect(selectPrimaryFlip(25000, [])).toBeNull();
  });

  it("selects the single crossing", () => {
    const crossings = [{ crossingSpot: 24500, gexA: 100, gexB: -50 }];
    const result = selectPrimaryFlip(25000, crossings);
    expect(result.crossingSpot).toBe(24500);
    expect(result.direction).toBe("positive_to_negative");
  });

  it("selects closest crossing to current spot when strengths are similar", () => {
    const crossings = [
      { crossingSpot: 23000, gexA: 100, gexB: -50 },
      { crossingSpot: 25200, gexA: 100, gexB: -50 },
    ];
    const result = selectPrimaryFlip(25000, crossings);
    expect(result.crossingSpot).toBe(25200);
  });

  it("considers crossing strength in ranking", () => {
    // Near crossing has weak transition; far crossing has strong transition
    const crossings = [
      { crossingSpot: 24900, gexA: 10, gexB: -5 },    // near, weak
      { crossingSpot: 25500, gexA: 1000, gexB: -800 }, // far, strong
    ];
    const result = selectPrimaryFlip(25000, crossings);
    // With weights 0.5 proximity + 0.3 strength + 0.2 quality:
    // Near: proximity ≈ 0.95, strength ≈ 0.009 → score ≈ 0.48
    // Far:  proximity ≈ 0.70, strength ≈ 1.0   → score ≈ 0.56
    // Far crossing should win due to much higher strength
    expect(result.crossingSpot).toBe(25500);
    expect(result.crossingStrength).toBe(1800);
  });

  it("includes compositeScore and rankingFactors", () => {
    const crossings = [{ crossingSpot: 25000, gexA: 100, gexB: -50 }];
    const result = selectPrimaryFlip(25000, crossings);
    expect(result.compositeScore).toBeDefined();
    expect(typeof result.compositeScore).toBe("number");
    expect(result.rankingFactors).toBeDefined();
    expect(result.rankingFactors.proximityWeight).toBe(0.5);
    expect(result.rankingFactors.strengthWeight).toBe(0.3);
    expect(result.rankingFactors.qualityWeight).toBe(0.2);
  });

  it("quality data affects ranking when provided", () => {
    const crossings = [
      { crossingSpot: 24900, gexA: 100, gexB: -50 },
      { crossingSpot: 25100, gexA: 100, gexB: -50 },
    ];
    // Same strength and proximity — quality is tiebreaker
    const dq = { totalStrikes: 10, strikesReadyForSweep: 10 };
    const result = selectPrimaryFlip(25000, crossings, dq);
    expect(result.rankingFactors.qualityFraction).toBe(1.0);
  });

  it("selects lowest spot when scores are tied", () => {
    const crossings = [
      { crossingSpot: 24000, gexA: 100, gexB: -50 },
      { crossingSpot: 26000, gexA: 100, gexB: -50 },
    ];
    const result = selectPrimaryFlip(25000, crossings);
    expect(result.crossingSpot).toBe(24000);
  });

  it("direction is correct for negative-to-positive", () => {
    const crossings = [{ crossingSpot: 25000, gexA: -100, gexB: 50 }];
    const result = selectPrimaryFlip(25000, crossings);
    expect(result.direction).toBe("negative_to_positive");
  });
});

// =============================================================================
// Level G — Crossing strength
// =============================================================================

describe("Level G — Crossing strength", () => {
  it("returns |gexA| + |gexB|", () => {
    expect(crossingStrength({ gexA: 100, gexB: -50 })).toBe(150);
  });

  it("returns 0 for null input", () => {
    expect(crossingStrength(null)).toBe(0);
  });

  it("handles NaN values", () => {
    expect(crossingStrength({ gexA: NaN, gexB: 100 })).toBe(0);
  });
});

// =============================================================================
// Level H — Data quality diagnostics
// =============================================================================

describe("Level H — Data quality diagnostics", () => {
  it("returns unavailable for empty input", () => {
    const dq = sweepDataQuality(null, 25000);
    expect(dq.sweepReadiness).toBe("unavailable");
    expect(dq.totalStrikes).toBe(0);
  });

  it("identifies all strikes ready for sweep", () => {
    const rows = [
      { strike: 24500, call: { gamma: 0.001, iv: 0.18, oi: 100 }, put: { gamma: 0.002, iv: 0.20, oi: 200 } },
      { strike: 25000, call: { gamma: 0.002, iv: 0.18, oi: 300 }, put: { gamma: 0.003, iv: 0.18, oi: 400 } },
    ];
    const dq = sweepDataQuality(rows, 25000);
    expect(dq.sweepReadiness).toBe("available");
    expect(dq.strikesReadyForSweep).toBe(2);
  });

  it("identifies partial readiness", () => {
    const rows = [
      { strike: 24500, call: { gamma: 0.001, iv: 0.18, oi: 100 }, put: { gamma: 0.002, iv: 0.20, oi: 200 } },
      { strike: 25000, call: { gamma: null, iv: null, oi: null }, put: { gamma: null, iv: null, oi: null } },
    ];
    const dq = sweepDataQuality(rows, 25000);
    expect(dq.sweepReadiness).toBe("partial");
    expect(dq.strikesReadyForSweep).toBe(1);
  });

  it("detects spot in range vs out of range", () => {
    const rows = [
      { strike: 24500, call: { gamma: 0.001, iv: 0.18, oi: 100 }, put: { gamma: 0.002, iv: 0.20, oi: 200 } },
      { strike: 25500, call: { gamma: 0.001, iv: 0.18, oi: 100 }, put: { gamma: 0.002, iv: 0.20, oi: 200 } },
    ];
    expect(sweepDataQuality(rows, 25000).spotInRange).toBe(true);
    expect(sweepDataQuality(rows, 23000).spotInRange).toBe(false);
  });
});

// =============================================================================
// Level I — Full spot sweep integration
// =============================================================================

describe("Level I — Full spot sweep integration", () => {
  it("returns unavailable for invalid spot/T/empty chain", () => {
    expect(spotSweep([{ strike: 25000 }], { spot: -1, T: 7 / 365 }).status).toBe("unavailable");
    expect(spotSweep([{ strike: 25000 }], { spot: 25000 }).status).toBe("unavailable");
    expect(spotSweep([], { spot: 25000, T: 7 / 365 }).status).toBe("unavailable");
  });

  it("default sweep range is ±30%", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.sweepConfig.spotMin).toBeCloseTo(25000 * 0.7, 0);
    expect(r.sweepConfig.spotMax).toBeCloseTo(25000 * 1.3, 0);
  });

  it("current GEX is computed at current spot", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18, gamma: 0.002 }, put: { oi: 500, iv: 0.18, gamma: 0.003 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.currentGex.callGex).toBeGreaterThan(0);
    expect(r.currentGex.putGex).toBeLessThan(0);
  });

  it("gamma flip structure is complete", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.gammaFlip).toBeDefined();
    expect(r.gammaFlip.crossings).toBeDefined();
    expect(r.gammaFlip.crossingCount).toBeDefined();
    expect(r.gammaFlip.noCrossingFound).toBeDefined();
  });

  it("byExpiry contains per-expiry sweep data", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.byExpiry.length).toBe(1);
    expect(r.byExpiry[0].sweepPoints).toBeDefined();
    expect(r.byExpiry[0].T).toBeCloseTo(7 / 365, 8);
  });

  it("gammaWalls uses directional semantics with spot", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18, gamma: 0.002 }, put: { oi: 500, iv: 0.18, gamma: 0.003 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.gammaWalls.callWalls).toBeDefined();
    expect(r.gammaWalls.putWalls).toBeDefined();
    expect(r.gammaWalls.netWalls).toBeDefined();
  });

  it("data quality and broker-vs-model are included", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18, gamma: 0.002 }, put: { oi: 500, iv: 0.18, gamma: 0.003 } }];
    const r = spotSweep(rows, { spot: 25000, T: 7 / 365 });
    expect(r.dataQuality).toBeDefined();
    expect(r.brokerVsModel).toBeDefined();
  });

  it("methodology version is correct", () => {
    const rows = [{ strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 } }];
    expect(spotSweep(rows, { spot: 25000, T: 7 / 365 }).methodology).toBe(GEX_PHASE72_VERSION);
  });
});

// =============================================================================
// Level J — Synthetic gamma flip detection
// =============================================================================

describe("Level J — Synthetic gamma flip detection", () => {
  it("call-dominant at low spot, put-dominant at high spot", () => {
    const T = 30 / 365;
    const sigma = 0.20;
    const rows = [
      { strike: 24000, call: { oi: 5000, iv: sigma }, put: { oi: 100, iv: sigma } },
      { strike: 25000, call: { oi: 2000, iv: sigma }, put: { oi: 2000, iv: sigma } },
      { strike: 26000, call: { oi: 100, iv: sigma }, put: { oi: 5000, iv: sigma } },
    ];
    const r = spotSweep(rows, { spot: 25000, T, sweepRangePct: 0.20, sweepSteps: 201 });
    expect(r.status).toBe("available");
    expect(r.byExpiry[0].sweepPoints.length).toBe(201);
    const first = r.byExpiry[0].sweepPoints[0];
    const last = r.byExpiry[0].sweepPoints[r.byExpiry[0].sweepPoints.length - 1];
    expect(first.callGex).toBeGreaterThan(0);
    expect(last.putGex).toBeLessThan(0);
  });
});

// =============================================================================
// Level K — Metadata and constants
// =============================================================================

describe("Level K — Metadata and constants", () => {
  it("constants are defined", () => {
    expect(typeof GEX_PHASE72_VERSION).toBe("string");
    expect(DEFAULT_SWEEP_RANGE_PCT).toBe(0.30);
    expect(DEFAULT_SWEEP_STEPS).toBe(501);
    expect(DEFAULT_WALL_TOP_N).toBe(3);
  });
});

// =============================================================================
// Level L — Independent reference calculation
// =============================================================================

describe("Level L — Independent reference calculation", () => {
  function referenceModelGamma(type, S, K, T, sigma, r, q) {
    if (T <= 0) return 0;
    if (S <= 0 || K <= 0 || sigma <= 0) return NaN;
    const sqrtT = Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrtT);
    const pdf = (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * d1 * d1);
    const dfQ = Math.exp(-q * T);
    return (dfQ * pdf) / (S * sigma * sqrtT);
  }

  it("modelGamma matches independent BS gamma reference for calls", () => {
    const cases = [
      { S: 25000, K: 25000, T: 7 / 365, sigma: 0.18, r: 0.065, q: 0 },
      { S: 25000, K: 24000, T: 14 / 365, sigma: 0.22, r: 0, q: 0 },
      { S: 25000, K: 26000, T: 30 / 365, sigma: 0.15, r: 0.05, q: 0.01 },
    ];
    for (const tc of cases) {
      expect(modelGamma("call", tc.S, tc.K, tc.T, tc.sigma, tc.r, tc.q))
        .toBeCloseTo(referenceModelGamma("call", tc.S, tc.K, tc.T, tc.sigma, tc.r, tc.q), 8);
    }
  });

  it("modelGamma matches independent reference for puts", () => {
    const T = 7 / 365;
    expect(modelGamma("put", 25000, 25000, T, 0.18, 0, 0))
      .toBeCloseTo(referenceModelGamma("put", 25000, 25000, T, 0.18, 0, 0), 8);
  });

  it("netGexAtSpot matches independent reference at a single point", () => {
    const T = 7 / 365;
    const S = 25000;
    const sigma = 0.18;
    const gCall = referenceModelGamma("call", S, 25000, T, sigma, 0, 0);
    const gPut = referenceModelGamma("put", S, 25000, T, sigma, 0, 0);

    const rows = [{ strike: 25000, call: { oi: 1000, iv: sigma }, put: { oi: 500, iv: sigma } }];
    const r = netGexAtSpot(rows, S, T, 0, 0);
    expect(r.callGex).toBeCloseTo(gCall * 1000 * S * S * 0.01, 5);
    expect(r.putGex).toBeCloseTo(-(gPut * 500 * S * S * 0.01), 5);
  });
});

// =============================================================================
// Level M — Per-expiry T regression tests
// =============================================================================

describe("Level M — Per-expiry time-to-expiry", () => {
  it("different expiries produce different model gamma", () => {
    const S = 25000;
    const K = 25000;
    const sigma = 0.18;

    const T1 = 7 / 365;   // 1 week
    const T2 = 30 / 365;  // 1 month

    const gamma1 = modelGamma("call", S, K, T1, sigma);
    const gamma2 = modelGamma("call", S, K, T2, sigma);

    // Short-dated ATM options have HIGHER gamma than long-dated
    expect(gamma1).toBeGreaterThan(gamma2);
    expect(gamma1).not.toBeCloseTo(gamma2, 5);
  });

  it("spotSweep uses per-expiry T when valuationDate is provided", () => {
    const rows = [
      { strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 }, expiry: "2026-08-29" },
      { strike: 25000, call: { oi: 800, iv: 0.20 }, put: { oi: 400, iv: 0.20 }, expiry: "2026-09-26" },
    ];
    const r = spotSweep(rows, {
      spot: 25000,
      valuationDate: "2026-08-22",
      sweepSteps: 51,
    });

    expect(r.byExpiry.length).toBe(2);
    // Each expiry should have its own T
    const t1 = r.byExpiry.find((e) => e.expiry === "2026-08-29");
    const t2 = r.byExpiry.find((e) => e.expiry === "2026-09-26");
    expect(t1).toBeDefined();
    expect(t2).toBeDefined();
    expect(t1.T).not.toBe(t2.T);
    // 2026-08-29 is 7 days from 2026-08-22
    expect(t1.T).toBeCloseTo(7 / 365, 4);
    // 2026-09-26 is 35 days from 2026-08-22
    expect(t2.T).toBeCloseTo(35 / 365, 4);
  });

  it("spotSweep uses expiryTMap when provided", () => {
    const expiryTMap = { "2026-08-29": 0.02, "2026-09-26": 0.10 };
    const rows = [
      { strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 }, expiry: "2026-08-29" },
      { strike: 25000, call: { oi: 800, iv: 0.20 }, put: { oi: 400, iv: 0.20 }, expiry: "2026-09-26" },
    ];
    const r = spotSweep(rows, { spot: 25000, expiryTMap, sweepSteps: 51 });
    const t1 = r.byExpiry.find((e) => e.expiry === "2026-08-29");
    const t2 = r.byExpiry.find((e) => e.expiry === "2026-09-26");
    expect(t1.T).toBeCloseTo(0.02, 8);
    expect(t2.T).toBeCloseTo(0.10, 8);
  });

  it("fallback to global T when no valuationDate or expiryTMap", () => {
    const rows = [
      { strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 }, expiry: "2026-08-29" },
    ];
    const r = spotSweep(rows, { spot: 25000, T: 0.05, sweepSteps: 51 });
    expect(r.byExpiry[0].T).toBeCloseTo(0.05, 8);
  });

  it("expiry with invalid T gets unavailable status", () => {
    const rows = [
      { strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 }, expiry: "2026-08-29" },
    ];
    const r = spotSweep(rows, { spot: 25000, sweepSteps: 51 });
    // No valuationDate, no expiryTMap, no global T → overall INVALID_T
    expect(r.status).toBe("unavailable");
    expect(r.reason).toBe("INVALID_T");
  });

  it("one expiry valid and one invalid — partial sweep completes", () => {
    const expiryTMap = { "2026-09-26": 0.10 };
    const rows = [
      { strike: 25000, call: { oi: 1000, iv: 0.18 }, put: { oi: 500, iv: 0.18 }, expiry: "2026-08-29" },
      { strike: 25000, call: { oi: 800, iv: 0.20 }, put: { oi: 400, iv: 0.20 }, expiry: "2026-09-26" },
    ];
    const r = spotSweep(rows, { spot: 25000, expiryTMap, sweepSteps: 51 });
    const t1 = r.byExpiry.find((e) => e.expiry === "2026-08-29");
    const t2 = r.byExpiry.find((e) => e.expiry === "2026-09-26");
    expect(t1.status).toBe("unavailable"); // no T for this expiry
    expect(t2.status).toBe("available");   // T from map
    expect(t2.sweepPoints.length).toBe(51);
  });
});
