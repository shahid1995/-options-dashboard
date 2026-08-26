/**
 * GEX Phase 7.4a — Time-Series Analytics Tests
 *
 * Level A — Hand-calculated fixtures
 * Level B — Algebraic properties
 * Level C — Edge cases
 * Level D — Timestamp-based velocity/acceleration
 * Level E — Window behavior
 */

import { describe, it, expect } from "vitest";
import {
  computeNetGexSma,
  computeDeltaGexSma,
  computeVelocity,
  computeAcceleration,
  computeDeltaGexVolatility,
  computeTimeSeriesStats,
  DEFAULT_NET_GEX_SMA_WINDOW,
  DEFAULT_DELTA_GEX_SMA_WINDOW,
  DEFAULT_VELOCITY_WINDOW,
  DEFAULT_VOLATILITY_WINDOW,
  MIN_VELOCITY_DT_SEC,
} from "./gexTimeSeries";

// =============================================================================
// Test fixtures
// =============================================================================

/** Create a minimal snapshot with netGex and capturedAt */
function snap(netGex, capturedAt) {
  return {
    netGex,
    capturedAt,
    spot: 25000,
    expiry: "2026-08-28",
    symbol: "NIFTY",
    callGex: netGex > 0 ? netGex : 0,
    putGex: netGex < 0 ? netGex : 0,
    strikeData: [],
    expiryData: [],
  };
}

/** Create snapshots at 5-minute intervals with given NetGEX values */
function series(values, startMs = Date.parse("2026-08-22T09:00:00Z"), intervalMs = 300_000) {
  return values.map((v, i) => snap(v, new Date(startMs + i * intervalMs).toISOString()));
}

// =============================================================================
// Level A — Hand-calculated fixtures
// =============================================================================

describe("Level A — Hand-calculated fixtures", () => {
  it("NetGexSma with 3 points, window=3", () => {
    // Values: [100, 200, 300], window=3
    // SMA at last point = (100 + 200 + 300) / 3 = 200
    const data = series([100, 200, 300]);
    const result = computeNetGexSma(data, 3);
    expect(result.sma).toBeCloseTo(200, 10);
    expect(result.availablePoints).toBe(3);
    expect(result.status).toBe("available");
  });

  it("NetGexSma with window=1 returns raw values", () => {
    const data = series([100, 200, 300]);
    const result = computeNetGexSma(data, 1);
    expect(result.sma).toBeCloseTo(300, 10);
    expect(result.status).toBe("available");
  });

  it("DeltaGexSma with known ΔGEX values", () => {
    // Values: [1000, 4000, 6000], ΔGEX = [3000, 2000]
    // SMA(3000, 2000) = 2500
    const data = series([1000, 4000, 6000]);
    const result = computeDeltaGexSma(data, 2);
    expect(result.sma).toBeCloseTo(2500, 10);
    expect(result.availablePoints).toBe(2);
  });

  it("Velocity with known timestamps and ΔGEX", () => {
    // Snapshot A: netGex=1000 at 09:00:00
    // Snapshot B: netGex=4000 at 09:05:00 (300s later)
    // ΔGEX = 3000, Δt = 300s
    // velocity = 3000 / 300 = 10 GEX/sec
    const data = series([1000, 4000]);
    const result = computeVelocity(data, 1);
    expect(result.velocity).toBeCloseTo(10, 10);
    expect(result.history).toHaveLength(1);
    expect(result.history[0].deltaTimeSec).toBe(300);
    expect(result.history[0].value).toBeCloseTo(10, 10);
  });

  it("Velocity with different intervals correctly scales", () => {
    // A→B: 1000→4000 in 300s → 10 GEX/sec
    // B→C: 4000→10000 in 600s → 10 GEX/sec (same rate)
    // SMA(window=1) should show 10 for both
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:05:00Z"), // 300s, Δ=3000
      snap(10000, "2026-08-22T09:15:00Z"), // 600s, Δ=6000
    ];
    const result = computeVelocity(data, 1);
    expect(result.velocity).toBeCloseTo(10, 10); // 6000/600 = 10
    expect(result.history[0].value).toBeCloseTo(10, 10); // 3000/300 = 10
    expect(result.history[1].value).toBeCloseTo(10, 10); // 6000/600 = 10
  });

  it("Acceleration with known velocity change", () => {
    // Snapshots at 5-min intervals:
    // t=0: 1000, t=5m: 4000, t=10m: 12000
    // vel1 = 3000/300 = 10 GEX/sec
    // vel2 = 8000/300 = 26.667 GEX/sec
    // accel = (26.667 - 10) / 300 = 0.05556 GEX/sec²
    const data = series([1000, 4000, 12000]);
    const result = computeAcceleration(data, 2);
    expect(result.acceleration).not.toBeNull();
    const expectedAccel = (8000 / 300 - 3000 / 300) / 300;
    expect(result.acceleration).toBeCloseTo(expectedAccel, 6);
  });

  it("ΔGEX volatility with known values", () => {
    // Values: [100, 400, 100, 400, 100] → ΔGEX = [300, -300, 300, -300]
    // stddev([300, -300, 300, -300]) = 300 (population)
    const data = series([100, 400, 100, 400, 100]);
    const result = computeDeltaGexVolatility(data, 4);
    expect(result.volatility).toBeCloseTo(300, 5);
    expect(result.status).toBe("available");
  });

  it("Single-point snapshot → all metrics unavailable", () => {
    const data = [snap(1000, "2026-08-22T09:00:00Z")];
    expect(computeNetGexSma(data, 3).status).toBe("partial");
    expect(computeDeltaGexSma(data, 3).status).toBe("unavailable");
    expect(computeVelocity(data).status).toBe("unavailable");
    expect(computeAcceleration(data).status).toBe("unavailable");
    expect(computeDeltaGexVolatility(data).status).toBe("unavailable");
  });
});

// =============================================================================
// Level B — Algebraic properties
// =============================================================================

describe("Level B — Algebraic properties", () => {
  it("doubling ΔGEX doubles velocity", () => {
    const a = series([1000, 4000]); // Δ=3000
    const b = series([1000, 7000]); // Δ=6000
    const va = computeVelocity(a, 1);
    const vb = computeVelocity(b, 1);
    expect(vb.velocity).toBeCloseTo(va.velocity * 2, 5);
  });

  it("zero spot change → zero velocity", () => {
    const data = series([5000, 5000, 5000]);
    const result = computeVelocity(data, 2);
    expect(result.velocity).toBeCloseTo(0, 5);
  });

  it("NetGexSma preserves mean property", () => {
    // All values same → SMA equals that value
    const data = series([3000, 3000, 3000, 3000]);
    const result = computeNetGexSma(data, 3);
    expect(result.sma).toBeCloseTo(3000, 10);
  });

  it("DeltaGexSma of constant ΔGEX equals that constant", () => {
    // Values: [1000, 2000, 3000, 4000] → ΔGEX = [1000, 1000, 1000]
    const data = series([1000, 2000, 3000, 4000]);
    const result = computeDeltaGexSma(data, 3);
    expect(result.sma).toBeCloseTo(1000, 10);
  });

  it("volatility of constant ΔGEX is zero", () => {
    // Values: [1000, 2000, 3000, 4000] → ΔGEX = [1000, 1000, 1000]
    const data = series([1000, 2000, 3000, 4000]);
    const result = computeDeltaGexVolatility(data, 3);
    expect(result.volatility).toBeCloseTo(0, 10);
  });

  it("velocity window=1 gives instantaneous velocity", () => {
    const data = series([1000, 4000]);
    const result = computeVelocity(data, 1);
    expect(result.velocity).toBeCloseTo(10, 10); // 3000/300
  });
});

// =============================================================================
// Level C — Edge cases
// =============================================================================

describe("Level C — Edge cases", () => {
  it("empty input → all unavailable", () => {
    expect(computeNetGexSma([], 5).status).toBe("unavailable");
    expect(computeDeltaGexSma([], 5).status).toBe("unavailable");
    expect(computeVelocity([]).status).toBe("unavailable");
    expect(computeAcceleration([]).status).toBe("unavailable");
    expect(computeDeltaGexVolatility([]).status).toBe("unavailable");
  });

  it("null netGex in snapshots → treated as missing", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(null, "2026-08-22T09:05:00Z"),
      snap(3000, "2026-08-22T09:10:00Z"),
    ];
    const vel = computeVelocity(data, 1);
    expect(vel.history[0].value).toBeNull(); // null ΔGEX
    expect(vel.history[1].value).toBeNull(); // null ΔGEX
  });

  it("zero deltaTime → velocity null (avoids division by zero)", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:00:00Z"), // same timestamp
    ];
    const result = computeVelocity(data, 1);
    expect(result.velocity).toBeNull();
    expect(result.history[0].value).toBeNull();
  });

  it("negative deltaTime → velocity null (time reversal)", () => {
    const data = [
      snap(1000, "2026-08-22T09:05:00Z"),
      snap(4000, "2026-08-22T09:00:00Z"), // earlier timestamp
    ];
    const result = computeVelocity(data, 1);
    expect(result.velocity).toBeNull();
  });

  it("window larger than data → partial status", () => {
    const data = series([100, 200]);
    const result = computeNetGexSma(data, 10);
    expect(result.status).toBe("partial");
    expect(result.availablePoints).toBe(2);
  });

  it("window=1 for volatility → unavailable (need ≥2)", () => {
    const data = series([100, 200, 300]);
    const result = computeDeltaGexVolatility(data, 1);
    expect(result.status).toBe("unavailable");
  });

  it("NaN netGex → treated as missing", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(NaN, "2026-08-22T09:05:00Z"),
      snap(3000, "2026-08-22T09:10:00Z"),
    ];
    const sma = computeNetGexSma(data, 3);
    expect(sma.sma).not.toBeNull(); // at least 2 valid values
    expect(sma.availablePoints).toBe(2);
  });

  it("Infinity netGex → treated as missing", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(Infinity, "2026-08-22T09:05:00Z"),
    ];
    const vel = computeVelocity(data, 1);
    expect(vel.history[0].value).toBeNull();
  });

  it("ring buffer input works via toArray", () => {
    // Simulate ring buffer interface
    const buf = {
      getAll: () => series([100, 200, 300]),
    };
    const result = computeNetGexSma(buf, 3);
    expect(result.sma).toBeCloseTo(200, 10);
  });
});

// =============================================================================
// Level D — Timestamp-based velocity/acceleration
// =============================================================================

describe("Level D — Timestamp-based velocity/acceleration", () => {
  it("non-uniform intervals produce correct velocities", () => {
    // A→B: 1000→4000 in 300s → 10 GEX/sec
    // B→C: 4000→5000 in 60s → 16.667 GEX/sec
    // C→D: 5000→8000 in 120s → 25 GEX/sec
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:05:00Z"),
      snap(5000, "2026-08-22T09:06:00Z"),
      snap(8000, "2026-08-22T09:08:00Z"),
    ];
    const result = computeVelocity(data, 1);
    expect(result.history).toHaveLength(3);
    expect(result.history[0].value).toBeCloseTo(10, 5);
    expect(result.history[1].value).toBeCloseTo(1000 / 60, 5);
    expect(result.history[2].value).toBeCloseTo(3000 / 120, 5);
  });

  it("acceleration uses actual timestamps between velocity points", () => {
    // Non-uniform: vel1 computed at t=5m, vel2 at t=7m
    // accel = (vel2 - vel1) / (t2 - t1)
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:05:00Z"), // vel1 = 3000/300 = 10
      snap(10000, "2026-08-22T09:07:00Z"), // vel2 = 6000/120 = 50
    ];
    const result = computeAcceleration(data, 2);
    // accel = (50 - 10) / (7min - 5min) = 40 / 120 = 0.333
    expect(result.acceleration).toBeCloseTo(40 / 120, 6);
  });

  it("constant interval velocity is just ΔGEX / interval", () => {
    const data = series([0, 1500, 3000, 4500, 6000]); // all 5-min intervals
    const result = computeVelocity(data, 1);
    // All ΔGEX = 1500, Δt = 300s → velocity = 5 GEX/sec
    for (const h of result.history) {
      expect(h.value).toBeCloseTo(5, 10);
    }
  });

  it("deltaTimeSec is surfaced in velocity history", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:05:00Z"),
    ];
    const result = computeVelocity(data, 1);
    expect(result.history[0].deltaTimeSec).toBe(300);
  });

  it("deltaGex is surfaced in velocity history", () => {
    const data = [
      snap(1000, "2026-08-22T09:00:00Z"),
      snap(4000, "2026-08-22T09:05:00Z"),
    ];
    const result = computeVelocity(data, 1);
    expect(result.history[0].deltaGex).toBe(3000);
  });
});

// =============================================================================
// Level E — Window behavior
// =============================================================================

describe("Level E — Window behavior", () => {
  it("partial window at start produces partial status", () => {
    const data = series([100, 200, 300, 400, 500]);
    const result = computeNetGexSma(data, 5);
    // At index 0: 1 point (partial), at index 4: 5 points (available)
    expect(result.history[0].pointsUsed).toBe(1);
    expect(result.history[4].pointsUsed).toBe(5);
    expect(result.status).toBe("available"); // current is the last one
  });

  it("window > data length still computes with available points", () => {
    const data = series([1000, 2000]);
    const result = computeDeltaGexSma(data, 10);
    expect(result.status).toBe("partial");
    expect(result.sma).toBeCloseTo(1000, 10); // single ΔGEX = 1000
  });

  it("acceleration needs ≥3 snapshots", () => {
    const data = series([1000, 2000]);
    expect(computeAcceleration(data).status).toBe("unavailable");
    const data3 = series([1000, 2000, 3000]);
    expect(computeAcceleration(data3).status).not.toBe("unavailable");
  });

  it("convenience function returns all sub-results", () => {
    const data = series([1000, 2000, 3000, 4000, 5000]);
    const result = computeTimeSeriesStats(data);
    expect(result).toHaveProperty("netGexSma");
    expect(result).toHaveProperty("deltaGexSma");
    expect(result).toHaveProperty("velocity");
    expect(result).toHaveProperty("acceleration");
    expect(result).toHaveProperty("volatility");
  });

  it("config overrides are applied", () => {
    const data = series([1000, 2000, 3000, 4000, 5000]);
    const result = computeTimeSeriesStats(data, {
      netGexSmaWindow: 2,
      deltaGexSmaWindow: 2,
      velocityWindow: 2,
      volatilityWindow: 2,
    });
    expect(result.netGexSma.windowSize).toBe(2);
    expect(result.deltaGexSma.windowSize).toBe(2);
    expect(result.velocity.windowSize).toBe(2);
    expect(result.volatility.windowSize).toBe(2);
  });
});
