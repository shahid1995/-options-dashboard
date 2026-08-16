import { describe, it, expect } from "vitest";
import { pnlAt, payoffRange, payoffCurve, perLegPayoff, breakevensFromCurve } from "./payoff";

// Minimal leg factory: { type, action, strike, price, qty, expiry }.
const leg = (type, action, strike, price, qty = 1, expiry = "2026-08-28") => ({ type, action, strike, price, qty, expiry });

const strikes = [24800, 24900, 25000, 25100, 25200];

describe("pnlAt", () => {
  it("computes at-expiry P&L for a long call (intrinsic minus premium)", () => {
    expect(pnlAt([leg("call", "buy", 25000, 200)], 25100)).toBe(-100);
    expect(pnlAt([leg("call", "buy", 25000, 200)], 25200)).toBe(0);
    expect(pnlAt([leg("call", "buy", 25000, 200)], 25000)).toBe(-200);
  });

  it("computes at-expiry P&L for a long put", () => {
    expect(pnlAt([leg("put", "buy", 25000, 150)], 24900)).toBe(-50);
    expect(pnlAt([leg("put", "buy", 25000, 150)], 24800)).toBe(50);
  });

  it("scales by quantity, lot size and multiplier", () => {
    const pnl = pnlAt([leg("call", "buy", 25000, 200, 2)], 25100, { lotSize: 65, multiplier: 3 });
    expect(pnl).toBe(-100 * 2 * 65 * 3);
  });

  it("sums multiple legs with buy/sell signs", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)];
    expect(pnlAt(legs, 25000)).toBe(-50); // net debit
    expect(pnlAt(legs, 25100)).toBe(50); // max profit (width − debit)
    expect(pnlAt(legs, 25200)).toBe(50); // capped above the short strike
  });
});

describe("payoffRange", () => {
  it("returns exact extrema across the sampled strikes (no rounding)", () => {
    const { maxProfit, maxLoss } = payoffRange([leg("call", "buy", 25000, 205.85)], strikes);
    expect(maxLoss).toBe(-205.85);
    expect(maxProfit).toBe(-205.85 + 200); // at the highest sampled strike
  });

  it("returns 0 extrema for empty legs", () => {
    expect(payoffRange([], strikes)).toEqual({ maxProfit: 0, maxLoss: 0 });
  });

  it("returns 0 extrema when there are no strikes", () => {
    expect(payoffRange([leg("call", "buy", 25000, 200)], [])).toEqual({ maxProfit: 0, maxLoss: 0 });
  });
});

describe("payoffCurve", () => {
  it("returns one exact point per strike, in order", () => {
    const curve = payoffCurve([leg("call", "buy", 25000, 200)], strikes);
    expect(curve.map((p) => p.strike)).toEqual(strikes);
    expect(curve.find((p) => p.strike === 25100).pnl).toBe(-100);
  });
});

describe("perLegPayoff", () => {
  it("returns per-leg and combined P&L at each strike", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)];
    const curve = perLegPayoff(legs, strikes);
    expect(curve).toHaveLength(strikes.length);
    const at25000 = curve.find((p) => p.strike === 25000);
    expect(at25000.legPnl).toEqual([-200, -150]);
    expect(at25000.combined).toBe(-350);
  });

  it("combined always equals the sum of the leg P&Ls", () => {
    const legs = [leg("call", "buy", 25000, 200, 2), leg("put", "sell", 24900, 50, 3)];
    for (const p of perLegPayoff(legs, strikes)) {
      expect(p.combined).toBe(p.legPnl.reduce((a, b) => a + b, 0));
    }
  });
});

describe("breakevensFromCurve", () => {
  it("finds the zero crossing of a bull call spread at the upper strike", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 100)];
    expect(breakevensFromCurve(payoffCurve(legs, strikes))).toEqual([25100]);
  });

  it("finds both breakevens of a long straddle", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)];
    // Payoff bottoms at 25000 (−350) and crosses zero at 25000 ± 350.
    const curve = payoffCurve(legs, [24500, 24600, 24700, 24800, 24900, 25000, 25100, 25200, 25300, 25400, 25500]);
    expect(breakevensFromCurve(curve)).toEqual([24650, 25350]);
  });

  it("returns an empty array for a curve with no crossings", () => {
    const curve = [{ strike: 100, pnl: -50 }, { strike: 200, pnl: -50 }];
    expect(breakevensFromCurve(curve)).toEqual([]);
  });
});
