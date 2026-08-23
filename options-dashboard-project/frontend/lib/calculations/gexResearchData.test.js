/**
 * GEX Phase 7.7 — gexResearchData Tests
 *
 * Level A: Basic construction
 * Level B: Forward outcomes
 * Level C: Edge cases
 * Level D: Look-ahead prevention
 * Level E: Timestamp/timezone
 */

import { describe, it, expect } from "vitest";
import {
  classifyTimeOfDay,
  computeCandleSummary,
  computeForwardOutcomes,
  buildResearchObservation,
  buildResearchDataset,
  HORIZONS,
  MIN_FORWARD_CANDLES,
} from "./gexResearchData.js";

// ---- Fixtures ------------------------------------------------------------

const CANDLE_BASE = {
  symbol: "NIFTY",
  interval: "3min",
};

function makeCandle(openTime, open, high, low, close, volume = 1000) {
  return {
    ...CANDLE_BASE,
    openTime,
    open,
    high,
    low,
    close,
    volume,
  };
}

function makeSnapshot(capturedAt, overrides = {}) {
  return {
    schemaVersion: "GEXSnapshot_v1",
    capturedAt,
    symbol: "NIFTY",
    underlying: "NIFTY",
    spot: 25500,
    expiry: "2026-08-28",
    dte: 5,
    methodology: "GEX_STANDARD_V1",
    callGex: 100000,
    putGex: -80000,
    netGex: 20000,
    availabilityStatus: "available",
    validStrikeCount: 20,
    totalStrikeCount: 20,
    strikeData: [],
    expiryData: [],
    methodologyMetadata: { gexVersion: "GEX_STANDARD_V1" },
    ...overrides,
  };
}

// ---- Level A: Basic construction -----------------------------------------

describe("classifyTimeOfDay", () => {
  it("pre_market before 9:15 IST", () => {
    // 03:00 UTC = 08:30 IST
    expect(classifyTimeOfDay("2026-08-22T03:00:00Z")).toBe("pre_market");
  });

  it("morning 9:15–11:00 IST", () => {
    // 04:00 UTC = 09:30 IST
    expect(classifyTimeOfDay("2026-08-22T04:00:00Z")).toBe("morning");
  });

  it("midday 11:00–13:00 IST", () => {
    // 06:00 UTC = 11:30 IST
    expect(classifyTimeOfDay("2026-08-22T06:00:00Z")).toBe("midday");
  });

  it("afternoon 13:00–15:30 IST", () => {
    // 08:30 UTC = 14:00 IST
    expect(classifyTimeOfDay("2026-08-22T08:30:00Z")).toBe("afternoon");
  });

  it("post_market after 15:30 IST", () => {
    // 10:30 UTC = 16:00 IST
    expect(classifyTimeOfDay("2026-08-22T10:30:00Z")).toBe("post_market");
  });

  it("null timestamp returns unknown", () => {
    expect(classifyTimeOfDay(null)).toBe("unknown");
  });
});

describe("computeCandleSummary", () => {
  it("basic up move", () => {
    const candles = [
      makeCandle("2026-08-22T09:18:00Z", 25500, 25520, 25490, 25515),
      makeCandle("2026-08-22T09:21:00Z", 25515, 25530, 25510, 25525),
    ];
    const result = computeCandleSummary(25500, candles);
    expect(result).not.toBeNull();
    expect(result.direction).toBe(1);
    expect(result.return).toBeCloseTo(25525 / 25500 - 1, 6);
    expect(result.high).toBe(25530);
    expect(result.low).toBe(25490);
    expect(result.highExcursion).toBeGreaterThan(0);
  });

  it("basic down move", () => {
    const candles = [
      makeCandle("2026-08-22T09:18:00Z", 25500, 25510, 25470, 25480),
    ];
    const result = computeCandleSummary(25500, candles);
    expect(result.direction).toBe(-1);
    expect(result.return).toBeLessThan(0);
  });

  it("flat", () => {
    const candles = [
      makeCandle("2026-08-22T09:18:00Z", 25500, 25500, 25500, 25500),
    ];
    const result = computeCandleSummary(25500, candles);
    expect(result.direction).toBe(0);
    expect(result.return).toBe(0);
  });

  it("null referenceClose returns null", () => {
    expect(computeCandleSummary(null, [makeCandle("t", 100, 110, 90, 105)])).toBeNull();
  });

  it("empty candles returns null", () => {
    expect(computeCandleSummary(25500, [])).toBeNull();
  });

  it("MFE and MAE are correct", () => {
    // Price goes up then down
    const candles = [
      makeCandle("t1", 25500, 25600, 25490, 25550), // high=25600, low=25490
      makeCandle("t2", 25550, 25560, 25450, 25460), // final: down
    ];
    const result = computeCandleSummary(25500, candles);
    expect(result.direction).toBe(-1);
    // Favorable = move in direction of final (down): from 25500 to 25450
    expect(result.maxFavorableExcursion).toBeGreaterThan(0);
    // Adverse = move against final (up): from 25500 to 25600
    expect(result.maxAdverseExcursion).toBeGreaterThan(0);
  });
});

describe("computeForwardOutcomes", () => {
  it("computes all horizons", () => {
    const candles = Array.from({ length: 35 }, (_, i) =>
      makeCandle(`2026-08-22T09:${15 + i * 3}:00Z`, 25500 + i, 25510 + i, 25490 + i, 25505 + i)
    );
    const outcomes = computeForwardOutcomes(25500, candles, 0);
    for (const h of HORIZONS) {
      expect(outcomes[`candles${h}`]).not.toBeNull();
      expect(outcomes[`candles${h}`].return).toBeGreaterThan(0);
    }
  });

  it("partial horizons when few candles remain", () => {
    const candles = [
      makeCandle("t1", 25500, 25510, 25490, 25505),
      makeCandle("t2", 25505, 25515, 25500, 25510),
    ];
    const outcomes = computeForwardOutcomes(25500, candles, 0);
    // 1 forward candle available — candles1 gets it, candles3 also gets 1 (partial)
    expect(outcomes.candles1).not.toBeNull();
    expect(outcomes.candles3).not.toBeNull(); // partial: only 1 forward candle
    expect(outcomes.candles3.high).toBe(25515);
  });
});

describe("buildResearchObservation", () => {
  it("constructs observation from snapshot + candles", () => {
    const candles = Array.from({ length: 35 }, (_, i) =>
      makeCandle(`2026-08-22T09:${15 + i * 3}:00Z`, 25500 + i, 25510 + i, 25490 + i, 25505 + i)
    );
    const snapshot = makeSnapshot("2026-08-22T09:15:00Z");
    const obs = buildResearchObservation(snapshot, {
      allCandles: candles,
      candleIndex: 0,
    });
    expect(obs).not.toBeNull();
    expect(obs.spot).toBe(25500);
    expect(obs.netGex).toBe(20000);
    expect(obs.symbol).toBe("NIFTY");
    expect(obs.capturedAt).toBe("2026-08-22T09:15:00Z");
    expect(obs.forward.candles1).not.toBeNull();
  });

  it("null snapshot returns null", () => {
    expect(buildResearchObservation(null)).toBeNull();
  });

  it("missing capturedAt returns null", () => {
    const snap = makeSnapshot(null);
    expect(buildResearchObservation(snap)).toBeNull();
  });

  it("null spot returns null", () => {
    const snap = makeSnapshot("2026-08-22T09:15:00Z", { spot: null });
    expect(buildResearchObservation(snap)).toBeNull();
  });

  it("computes normalizedNetGex correctly", () => {
    const snap = makeSnapshot("2026-08-22T09:15:00Z", { netGex: 25000, spot: 25000 });
    const obs = buildResearchObservation(snap);
    // normalizedNetGex = 25000 / (25000^2 * 0.01) = 25000 / 6250000 = 0.004
    expect(obs.normalizedNetGex).toBeCloseTo(0.004, 6);
  });
});

describe("buildResearchDataset", () => {
  it("joins snapshots with candles chronologically", () => {
    const snapshots = [
      makeSnapshot("2026-08-22T09:15:00Z"),
      makeSnapshot("2026-08-22T09:20:00Z", { netGex: 25000 }),
    ];
    const candles = [
      makeCandle("2026-08-22T09:15:00Z", 25500, 25510, 25490, 25505),
      makeCandle("2026-08-22T09:18:00Z", 25505, 25515, 25500, 25510),
      makeCandle("2026-08-22T09:21:00Z", 25510, 25520, 25505, 25515),
      makeCandle("2026-08-22T09:24:00Z", 25515, 25525, 25510, 25520),
    ];
    const dataset = buildResearchDataset(snapshots, candles);
    expect(dataset.length).toBe(2);
    expect(dataset[0].netGex).toBe(20000);
    expect(dataset[1].netGex).toBe(25000);
  });

  it("skips snapshots with missing capturedAt", () => {
    const snapshots = [makeSnapshot(null), makeSnapshot("2026-08-22T09:15:00Z")];
    const candles = [makeCandle("2026-08-22T09:15:00Z", 25500, 25510, 25490, 25505)];
    const dataset = buildResearchDataset(snapshots, candles);
    expect(dataset.length).toBe(1);
  });

  it("empty inputs return empty array", () => {
    expect(buildResearchDataset([], [])).toEqual([]);
    expect(buildResearchDataset(null, [])).toEqual([]);
  });
});

// ---- Level D: Look-ahead prevention --------------------------------------

describe("Look-ahead prevention", () => {
  it("reference candle is at or before capturedAt, not after", () => {
    const snap = makeSnapshot("2026-08-22T09:21:00Z");
    const candles = [
      makeCandle("2026-08-22T09:15:00Z", 25500, 25510, 25490, 25505),
      makeCandle("2026-08-22T09:18:00Z", 25505, 25515, 25500, 25510),
      makeCandle("2026-08-22T09:21:00Z", 25510, 25520, 25505, 25515),
      makeCandle("2026-08-22T09:24:00Z", 25515, 25525, 25510, 25520),
    ];
    const dataset = buildResearchDataset(snapshots(snap), candles);
    expect(dataset.length).toBe(1);
    // Spot comes from snapshot.spot (authoritative), not candle close
    expect(dataset[0].spot).toBe(25500); // from snapshot
  });

  it("forward candles start AFTER reference candle", () => {
    const snap = makeSnapshot("2026-08-22T09:15:00Z");
    const candles = [
      makeCandle("2026-08-22T09:15:00Z", 25500, 25510, 25490, 25505),
      makeCandle("2026-08-22T09:18:00Z", 25505, 25515, 25500, 25510),
    ];
    const dataset = buildResearchDataset([snap], candles);
    const outcome = dataset[0].forward.candles1;
    // Forward candle is 09:18 with high=25515
    expect(outcome).not.toBeNull();
    expect(outcome.high).toBe(25515);
    // return is relative to snapshot spot (25500), not reference candle close
    expect(outcome.return).toBeCloseTo((25510 - 25500) / 25500, 6);
  });
});

// ---- Baseline price features tests ---------------------------------------

describe("computeBaselineFeatures (via buildResearchObservation)", () => {
  it("populates previousReturn from lookback candles", () => {
    // 5 candles: closes at 25480, 25490, 25500, 25510, 25520
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25475, 25485, 25470, 25480),
      makeCandle("2026-08-22T09:03:00Z", 25480, 25495, 25478, 25490),
      makeCandle("2026-08-22T09:06:00Z", 25490, 25505, 25488, 25500),
      makeCandle("2026-08-22T09:09:00Z", 25500, 25515, 25498, 25510),
      makeCandle("2026-08-22T09:12:00Z", 25510, 25525, 25508, 25520),
    ];
    const snap = makeSnapshot("2026-08-22T09:12:00Z", { spot: 25520 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 4,
      lookbackCandles: 20,
    });
    // previousReturn = (25520 - 25510) / 25510 ≈ 0.000392
    expect(obs.previousReturn).not.toBeNull();
    expect(obs.previousReturn).toBeCloseTo((25520 - 25510) / 25510, 6);
  });

  it("populates intradayRange from reference candle", () => {
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25480, 25500, 25460, 25490),
      makeCandle("2026-08-22T09:03:00Z", 25490, 25520, 25470, 25510),
    ];
    const snap = makeSnapshot("2026-08-22T09:03:00Z", { spot: 25510 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 1,
    });
    // intradayRange = (25520 - 25470) / 25510
    expect(obs.intradayRange).not.toBeNull();
    expect(obs.intradayRange).toBeCloseTo((25520 - 25470) / 25510, 6);
  });

  it("populates momentum from lookback window", () => {
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25400, 25410, 25390, 25400),
      makeCandle("2026-08-22T09:03:00Z", 25400, 25410, 25390, 25420),
      makeCandle("2026-08-22T09:06:00Z", 25420, 25430, 25410, 25440),
      makeCandle("2026-08-22T09:09:00Z", 25440, 25450, 25430, 25500),
    ];
    const snap = makeSnapshot("2026-08-22T09:09:00Z", { spot: 25500 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 3,
    });
    // momentum = (25500 - 25400) / 25400
    expect(obs.momentum).not.toBeNull();
    expect(obs.momentum).toBeCloseTo((25500 - 25400) / 25400, 6);
  });

  it("populates distFromHigh and distFromLow", () => {
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25400, 25450, 25350, 25420),
      makeCandle("2026-08-22T09:03:00Z", 25420, 25430, 25410, 25420),
    ];
    const snap = makeSnapshot("2026-08-22T09:03:00Z", { spot: 25420 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 1,
    });
    // distFromHigh = (25420 - 25450) / 25450 (negative = below high)
    expect(obs.distFromHigh).not.toBeNull();
    expect(obs.distFromHigh).toBeLessThan(0);
    // distFromLow = (25420 - 25350) / 25350 (positive = above low)
    expect(obs.distFromLow).not.toBeNull();
    expect(obs.distFromLow).toBeGreaterThan(0);
  });

  it("computes realizedVolatility from lookback returns", () => {
    const candles = Array.from({ length: 10 }, (_, i) =>
      makeCandle(`2026-08-22T09:${String(i * 3).padStart(2, "0")}:00Z`,
        25500 + i * 10, 25500 + i * 10 + 5, 25500 + i * 10 - 5, 25500 + i * 10)
    );
    const snap = makeSnapshot("2026-08-22T09:27:00Z", { spot: 25590 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 9,
    });
    expect(obs.realizedVolatility).not.toBeNull();
    expect(obs.realizedVolatility).toBeGreaterThanOrEqual(0);
  });

  it("null baseline features when insufficient lookback", () => {
    // Only 1 candle in lookback — not enough for volatility
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25500, 25510, 25490, 25505),
    ];
    const snap = makeSnapshot("2026-08-22T09:00:00Z", { spot: 25505 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 0,
    });
    // No lookback candles before index 0
    expect(obs.previousReturn).toBeNull();
    expect(obs.momentum).toBeNull();
    expect(obs.distFromHigh).toBeNull();
    expect(obs.distFromLow).toBeNull();
    // intradayRange from reference candle itself
    expect(obs.intradayRange).not.toBeNull();
  });

  it("uses only candles at or before capturedAt — no look-ahead", () => {
    // Reference at index 1 (09:03), future candle at index 2 (09:06)
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25400, 25410, 25390, 25400),
      makeCandle("2026-08-22T09:03:00Z", 25400, 25410, 25390, 25500),
      makeCandle("2026-08-22T09:06:00Z", 25500, 25600, 25490, 25550),
    ];
    const snap = makeSnapshot("2026-08-22T09:03:00Z", { spot: 25500 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 1,
    });
    // momentum should use candle 0's close (25400), not candle 2's close (25550)
    expect(obs.momentum).toBeCloseTo((25500 - 25400) / 25400, 6);
  });

  it("zero-return case", () => {
    const candles = [
      makeCandle("2026-08-22T09:00:00Z", 25500, 25500, 25500, 25500),
      makeCandle("2026-08-22T09:03:00Z", 25500, 25500, 25500, 25500),
    ];
    const snap = makeSnapshot("2026-08-22T09:03:00Z", { spot: 25500 });
    const obs = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 1,
    });
    expect(obs.previousReturn).toBe(0);
    expect(obs.momentum).toBe(0);
    expect(obs.intradayRange).toBe(0);
  });

  it("configurable lookbackCandles", () => {
    const candles = Array.from({ length: 30 }, (_, i) =>
      makeCandle(`2026-08-22T09:${String(i * 3).padStart(2, "0")}:00Z`,
        25500 + i, 25500 + i + 5, 25500 + i - 5, 25500 + i)
    );
    const snap = makeSnapshot("2026-08-22T10:27:00Z", { spot: 25529 });
    const obs5 = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 29,
      lookbackCandles: 5,
    });
    const obs20 = buildResearchObservation(snap, {
      allCandles: candles,
      candleIndex: 29,
      lookbackCandles: 20,
    });
    // Different lookback windows should produce different momentum
    expect(obs5.momentum).not.toBeNull();
    expect(obs20.momentum).not.toBeNull();
  });
});

// ---- baselineComparison integration test ---------------------------------

describe("baselineComparison receives populated features", () => {
  it("baseline features are non-zero in observations", () => {
    // Create 30 candles, snapshots start after first few candles so matching works
    const candles = Array.from({ length: 30 }, (_, i) =>
      makeCandle(`2026-08-22T09:${String(i * 3).padStart(2, "0")}:00Z`,
        25500 + i * 5, 25500 + i * 5 + 10, 25500 + i * 5 - 10, 25500 + i * 5)
    );
    // Snapshots at every 3rd minute starting from 09:03
    const snapshotsArr = [];
    for (let i = 1; i <= 20; i++) {
      snapshotsArr.push(makeSnapshot(`2026-08-22T09:${String(i * 3).padStart(2, "0")}:00Z`, {
        spot: 25500 + i * 5,
        netGex: 20000 + i * 1000,
      }));
    }
    const dataset = buildResearchDataset(snapshotsArr, candles);
    // All observations that have candle matches should have intradayRange
    const withRange = dataset.filter(o => o.intradayRange != null);
    expect(withRange.length).toBe(dataset.length);
    // At least some should have previousReturn (need lookback candle)
    const withPrevReturn = dataset.filter(o => o.previousReturn != null);
    expect(withPrevReturn.length).toBeGreaterThan(0);
    // All observations should have baseline fields (even if null)
    for (const obs of dataset) {
      expect(obs).toHaveProperty("previousReturn");
      expect(obs).toHaveProperty("realizedVolatility");
      expect(obs).toHaveProperty("intradayRange");
      expect(obs).toHaveProperty("momentum");
      expect(obs).toHaveProperty("distFromHigh");
      expect(obs).toHaveProperty("distFromLow");
    }
  });
});

function snapshots(...snaps) { return snaps; }
