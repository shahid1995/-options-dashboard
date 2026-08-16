import { describe, it, expect } from "vitest";
import {
  GREEK_KEYS,
  LIVE_THETA_PER_DAY_FACTOR,
  LIVE_VEGA_PER_VOL_POINT_FACTOR,
  MODEL_THETA_PER_DAY_FACTOR,
  MODEL_VEGA_PER_VOL_POINT_FACTOR,
  canonicalizeLive,
  canonicalizeModelScaled,
  sumWithStatus,
  perLegGreekAnalytics,
  totalGreekSet,
  greekContribution,
  calculateStrategyGreeks,
  scenarioGreekComparison,
} from "./greekAnalytics";
import { calculateScenario } from "./scenario";

const NEAR = "2026-08-28";
const FAR = "2026-09-25";
const VALUATION = "2026-08-25"; // near = 3 days out, far = 31 days out

// Chain IV follows the real broker convention: PERCENT (18 = 18%). The
// scenario engine normalizes to canonical decimal before pricing, so model
// Greeks below are computed at 0.18 / 0.20 / 0.25 / 0.27 as before.
function makeChain(strikes, { callIv = 18, putIv = 20, greeks = {} } = {}) {
  return {
    underlying_spot_price: 25000,
    chain: strikes.map((s) => ({
      strike: s,
      call: {
        ltp: 200,
        iv: callIv,
        delta: 0.5,
        gamma: 0.001,
        theta: -13,
        vega: 33,
        ...greeks.call,
      },
      put: {
        ltp: 150,
        iv: putIv,
        delta: -0.5,
        gamma: 0.001,
        theta: -13,
        vega: 33,
        ...greeks.put,
      },
    })),
  };
}

function marketContext(overrides = {}) {
  return {
    spot: 25000,
    valuationDate: VALUATION,
    interestRate: 0,
    dividendYield: 0,
    lotSize: 1,
    multiplier: 1,
    chainCache: {
      [NEAR]: makeChain([24900, 25000, 25100], { callIv: 18, putIv: 20 }),
      [FAR]: makeChain([24900, 25000, 25100], { callIv: 25, putIv: 27 }),
    },
    ...overrides,
  };
}

const leg = (overrides = {}) => ({
  id: "l1",
  type: "call",
  action: "buy",
  strike: 25000,
  expiry: NEAR,
  qty: 1,
  price: 200,
  ...overrides,
});

// ---- Section 23: unit normalization ----------------------------------------

describe("canonical unit normalization", () => {
  it("converts model theta from annualized to per calendar day (365 → 1)", () => {
    expect(MODEL_THETA_PER_DAY_FACTOR).toBeCloseTo(1 / 365, 12);
    const c = canonicalizeModelScaled({ delta: 1, gamma: 1, theta: 365, vega: 1 });
    expect(c.thetaPerDay).toBeCloseTo(1, 10);
  });

  it("converts model vega from per 1.00 volatility to per 1 vol point (100 → 1.0)", () => {
    expect(MODEL_VEGA_PER_VOL_POINT_FACTOR).toBeCloseTo(0.01, 12);
    const c = canonicalizeModelScaled({ delta: 1, gamma: 1, theta: 1, vega: 100 });
    expect(c.vegaPerVolPoint).toBeCloseTo(1.0, 10);
  });

  it("keeps live theta per day and vega per vol point unchanged (factors of 1)", () => {
    expect(LIVE_THETA_PER_DAY_FACTOR).toBe(1);
    expect(LIVE_VEGA_PER_VOL_POINT_FACTOR).toBe(1);
    const c = canonicalizeLive({ delta: 0.5, gamma: 0.001, theta: -13, vega: 33 }, 2);
    expect(c.thetaPerDay).toBe(-26); // -13 × 2 exposure
    expect(c.vegaPerVolPoint).toBe(66); // 33 × 2 exposure
  });

  it("scales canonical values by exposure (dir × qty × lot × mult) with BUY positive", () => {
    const c = canonicalizeLive({ delta: 0.5, gamma: 0.001, theta: -13, vega: 33 }, 1 * 2 * 65 * 3);
    expect(c.delta).toBe(0.5 * 2 * 65 * 3);
    expect(c.gamma).toBe(0.001 * 2 * 65 * 3);
  });

  it("flips exposure sign for SELL", () => {
    const c = canonicalizeLive({ delta: 0.5, gamma: 0.001, theta: -13, vega: 33 }, -1 * 65);
    expect(c.delta).toBe(-0.5 * 65);
    expect(c.thetaPerDay).toBe(13 * 65);
  });

  it("nulls stay null through normalization (never become zero)", () => {
    const c = canonicalizeLive({ delta: null, gamma: 0.001, theta: null, vega: null }, 5);
    expect(c.delta).toBeNull();
    expect(c.thetaPerDay).toBeNull();
    expect(c.vegaPerVolPoint).toBeNull();
    const m = canonicalizeModelScaled({ delta: null, gamma: null, theta: null, vega: 2 });
    expect(m.delta).toBeNull();
    expect(m.thetaPerDay).toBeNull();
    expect(m.vegaPerVolPoint).toBeCloseTo(0.02, 10);
  });

  it("handles a null source entirely", () => {
    expect(canonicalizeLive(null, 5)).toEqual({
      delta: null,
      gamma: null,
      thetaPerDay: null,
      vegaPerVolPoint: null,
    });
    expect(canonicalizeModelScaled(null)).toEqual({
      delta: null,
      gamma: null,
      thetaPerDay: null,
      vegaPerVolPoint: null,
    });
  });
});

// ---- Section 24: mathematical consistency -----------------------------------

describe("mathematical consistency (model Greeks via the scenario engine)", () => {
  it("call delta is positive and put delta is negative", () => {
    const call = calculateStrategyGreeks([leg()], marketContext());
    const put = calculateStrategyGreeks([leg({ type: "put", price: 150 })], marketContext());
    expect(call.rows[0].model.delta).toBeGreaterThan(0);
    expect(put.rows[0].model.delta).toBeLessThan(0);
  });

  it("long option gamma is positive; short option gamma is negative", () => {
    const long = calculateStrategyGreeks([leg()], marketContext());
    const short = calculateStrategyGreeks([leg({ action: "sell" })], marketContext());
    expect(long.rows[0].model.gamma).toBeGreaterThan(0);
    expect(short.rows[0].model.gamma).toBeLessThan(0);
  });

  it("long option vega is positive; short option vega is negative", () => {
    const long = calculateStrategyGreeks([leg()], marketContext());
    const short = calculateStrategyGreeks([leg({ action: "sell" })], marketContext());
    expect(long.rows[0].model.vegaPerVolPoint).toBeGreaterThan(0);
    expect(short.rows[0].model.vegaPerVolPoint).toBeLessThan(0);
  });

  it("live long call delta is positive and live short call delta is negative", () => {
    const long = calculateStrategyGreeks([leg()], marketContext());
    const short = calculateStrategyGreeks([leg({ action: "sell" })], marketContext());
    expect(long.rows[0].live.delta).toBe(0.5);
    expect(short.rows[0].live.delta).toBe(-0.5);
  });

  it("strategy totals equal the sum of the scaled legs", () => {
    const legs = [
      leg({ id: "a" }),
      leg({ id: "b", type: "put", price: 150 }),
      leg({ id: "c", action: "sell", strike: 25100 }),
    ];
    const a = calculateStrategyGreeks(legs, marketContext());
    const sum = (k) => a.rows.reduce((acc, r) => acc + r.live[k], 0);
    expect(a.totals.live.delta).toBeCloseTo(sum("delta"), 8);
    expect(a.totals.live.gamma).toBeCloseTo(sum("gamma"), 8);
    expect(a.totals.live.thetaPerDay).toBeCloseTo(sum("thetaPerDay"), 8);
    expect(a.totals.live.vegaPerVolPoint).toBeCloseTo(sum("vegaPerVolPoint"), 8);
  });

  it("reversing BUY ↔ SELL flips the directional Greeks", () => {
    const buy = calculateStrategyGreeks([leg()], marketContext());
    const sell = calculateStrategyGreeks([leg({ action: "sell" })], marketContext());
    expect(sell.rows[0].live.delta).toBeCloseTo(-buy.rows[0].live.delta, 10);
    expect(sell.rows[0].live.gamma).toBeCloseTo(-buy.rows[0].live.gamma, 10);
    expect(sell.rows[0].live.thetaPerDay).toBeCloseTo(-buy.rows[0].live.thetaPerDay, 10);
    expect(sell.rows[0].live.vegaPerVolPoint).toBeCloseTo(-buy.rows[0].live.vegaPerVolPoint, 10);
  });

  it("doubling quantity doubles Greek exposure", () => {
    const one = calculateStrategyGreeks([leg()], marketContext());
    const two = calculateStrategyGreeks([leg({ qty: 2 })], marketContext());
    GREEK_KEYS.forEach((k) => {
      expect(two.rows[0].live[k]).toBeCloseTo(2 * one.rows[0].live[k], 8);
      expect(two.totals.model[k]).toBeCloseTo(2 * one.totals.model[k], 6);
    });
  });

  it("doubling lot size doubles Greek exposure", () => {
    const one = calculateStrategyGreeks([leg()], marketContext({ lotSize: 65 }));
    const two = calculateStrategyGreeks([leg()], marketContext({ lotSize: 130 }));
    GREEK_KEYS.forEach((k) => {
      expect(two.rows[0].live[k]).toBeCloseTo(2 * one.rows[0].live[k], 8);
    });
  });

  it("multi-expiry strategies use each leg's own expiry and own IV", () => {
    const legs = [
      leg({ id: "near" }),
      leg({ id: "far", expiry: FAR }),
    ];
    const a = calculateStrategyGreeks(legs, marketContext());
    // Live values come from each leg's own chain row (both 0.5 delta here),
    // but the MODEL greeks must differ because far has 31 days vs near 3 days.
    const near = a.rows.find((r) => r.legId === "near");
    const far = a.rows.find((r) => r.legId === "far");
    expect(near.model.delta).not.toBeCloseTo(far.model.delta, 4);
    // Far expiry has 31 days out vs near 3: near-the-money greeks differ.
    expect(far.model.vegaPerVolPoint).toBeGreaterThan(near.model.vegaPerVolPoint);
  });

  it("missing live Greek does not silently become model Greek", () => {
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, delta: null },
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    expect(a.rows[0].live.delta).toBeNull();
    expect(a.rows[0].model.delta).not.toBeNull();
    expect(a.rows[0].difference.delta).toBeNull();
  });

  it("missing model Greek does not silently become live Greek", () => {
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, iv: null },
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    expect(a.rows[0].model.delta).toBeNull();
    expect(a.rows[0].live.delta).toBe(0.5);
    expect(a.rows[0].difference.delta).toBeNull();
  });

  it("T = 0 model greeks are safe (no NaN / Infinity)", () => {
    // Scenario pushed 3 days forward = the near expiry day (T = 0).
    const a = calculateStrategyGreeks([leg()], marketContext(), { scenario: { timeShiftDays: 3 } });
    GREEK_KEYS.forEach((k) => {
      const v = a.rows[0].model[k];
      expect(Number.isFinite(v)).toBe(true);
    });
  });
});

// ---- Section 25: live-vs-model difference -----------------------------------

describe("live vs model difference", () => {
  it("difference = model − live for every Greek (sign preserved)", () => {
    const a = calculateStrategyGreeks([leg()], marketContext());
    const r = a.rows[0];
    GREEK_KEYS.forEach((k) => {
      expect(r.difference[k]).toBeCloseTo(r.model[k] - r.live[k], 8);
    });
  });

  it("a forced live/model delta spread shows the exact signed gap", () => {
    // Live delta 0.50 (chain) vs a model delta shifted by using a very
    // different IV so the model Greeks differ measurably.
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, iv: 50 }, // 50% → canonical 0.50
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    const r = a.rows[0];
    expect(r.difference.delta).toBeCloseTo(r.model.delta - r.live.delta, 8);
    expect(r.difference.thetaPerDay).toBeCloseTo(r.model.thetaPerDay - r.live.thetaPerDay, 8);
    expect(r.difference.vegaPerVolPoint).toBeCloseTo(r.model.vegaPerVolPoint - r.live.vegaPerVolPoint, 8);
  });

  it("difference is null when either side is null", () => {
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, gamma: null },
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    expect(a.rows[0].difference.gamma).toBeNull();
    expect(a.rows[0].difference.delta).not.toBeNull();
  });
});

// ---- Zero vs unavailable ----------------------------------------------------

describe("totals distinguish ZERO from UNAVAILABLE", () => {
  it("a valid zero total is reported as available, not unavailable", () => {
    // Buy 25000 call (delta +0.5) + sell 25000 call (delta −0.5) → delta 0.
    const legs = [leg({ id: "a" }), leg({ id: "b", action: "sell" })];
    const a = calculateStrategyGreeks(legs, marketContext());
    expect(a.totals.live.delta).toBe(0);
    expect(a.totals.status.live.delta).toBe("available");
  });

  it("an entirely missing Greek is unavailable (null), not zero", () => {
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, vega: null },
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    expect(a.rows[0].live.vegaPerVolPoint).toBeNull();
    expect(a.totals.live.vegaPerVolPoint).toBeNull();
    expect(a.totals.status.live.vegaPerVolPoint).toBe("unavailable");
  });

  it("partial totals are flagged partial", () => {
    const ctx = marketContext();
    ctx.chainCache[FAR].chain = ctx.chainCache[FAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, theta: null },
    }));
    const legs = [leg({ id: "near" }), leg({ id: "far", expiry: FAR })];
    const a = calculateStrategyGreeks(legs, ctx);
    expect(a.totals.status.live.thetaPerDay).toBe("partial");
    expect(a.totals.live.thetaPerDay).not.toBeNull();
    expect(a.totals.status.live.delta).toBe("available");
  });
});

// ---- Contributions ----------------------------------------------------------

describe("greek contributions", () => {
  it("per-leg contribution percentages sum to 100 over available legs", () => {
    const legs = [
      leg({ id: "a", strike: 24900, type: "call" }),
      leg({ id: "b", action: "sell", strike: 25100, type: "call" }),
      leg({ id: "c", type: "put", price: 150 }),
    ];
    const a = calculateStrategyGreeks(legs, marketContext());
    const contrib = greekContribution(a.rows, "delta", "live");
    const pctSum = contrib.entries.filter((e) => e.value != null).reduce((s, e) => s + e.pct, 0);
    expect(pctSum).toBeCloseTo(100, 6);
    // Buy call (positive delta) and sell call (negative delta) must oppose.
    const buy = contrib.entries.find((e) => e.legId === "a");
    const sell = contrib.entries.find((e) => e.legId === "b");
    expect(buy.value).toBeGreaterThan(0);
    expect(sell.value).toBeLessThan(0);
  });

  it("returns available=false when no leg contributes a value", () => {
    const ctx = marketContext();
    ctx.chainCache[NEAR].chain = ctx.chainCache[NEAR].chain.map((r) => ({
      ...r,
      call: { ...r.call, delta: null },
    }));
    const a = calculateStrategyGreeks([leg()], ctx);
    const contrib = greekContribution(a.rows, "delta", "live");
    expect(contrib.available).toBe(false);
    expect(contrib.total).toBeNull();
  });
});

// ---- Per-leg row shape ------------------------------------------------------

describe("per-leg analytics row", () => {
  it("exposes unit (contract-level) and exposure (scaled) canonical values", () => {
    const ctx = marketContext({ lotSize: 65 });
    const a = calculateStrategyGreeks([leg()], ctx);
    const r = a.rows[0];
    expect(r.unit.delta).toBeCloseTo(0.5, 8); // contract-level, unscaled
    expect(r.live.delta).toBeCloseTo(0.5 * 65, 8); // exposure
    expect(r.unit.vegaPerVolPoint).toBeCloseTo(33, 8);
    expect(r.live.vegaPerVolPoint).toBeCloseTo(33 * 65, 8);
  });

  it("exposes availability flags", () => {
    const a = calculateStrategyGreeks([leg()], marketContext());
    expect(a.rows[0].liveAvailable).toBe(true);
    expect(a.rows[0].modelAvailable).toBe(true);
  });

  it("keeps live and model fully separate", () => {
    const a = calculateStrategyGreeks([leg()], marketContext());
    const r = a.rows[0];
    expect(r.live.delta).toBe(0.5);
    // Model delta at 3 days to expiry is NOT the chain's 0.5.
    expect(r.model.delta).not.toBeCloseTo(0.5, 3);
  });
});

// ---- Scenario integration ---------------------------------------------------

describe("scenarioGreekComparison (reuses the scenario result)", () => {
  it("derives the same totals as calculateStrategyGreeks for the neutral scenario", () => {
    const legs = [leg()];
    const direct = calculateStrategyGreeks(legs, marketContext());
    const result = calculateScenario(legs, marketContext(), {});
    const fromResult = scenarioGreekComparison(result);
    GREEK_KEYS.forEach((k) => {
      expect(fromResult.live[k]).toBeCloseTo(direct.totals.live[k], 8);
      expect(fromResult.model[k]).toBeCloseTo(direct.totals.model[k], 8);
    });
  });

  it("reflects an ACTIVE scenario for the model side while live stays current", () => {
    const legs = [leg()];
    const base = calculateStrategyGreeks(legs, marketContext());
    const up = calculateStrategyGreeks(legs, marketContext(), { scenario: { spotPct: 0.02 } });
    // Live greeks are current-state (untouched by the scenario).
    expect(up.rows[0].live.delta).toBe(base.rows[0].live.delta);
    // Model greeks move with the scenario spot.
    expect(up.rows[0].model.delta).not.toBeCloseTo(base.rows[0].model.delta, 4);
  });
});
