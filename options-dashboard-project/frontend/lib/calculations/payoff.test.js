import { describe, it, expect } from "vitest";
import {
  pnlAt,
  payoffRange,
  payoffCurve,
  perLegPayoff,
  breakevensFromCurve,
  payoffMode,
  theoreticalBreakpoints,
  theoreticalPayoffAnalysis,
  theoreticalBreakevens,
  payoffGrid,
} from "./payoff";

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

describe("payoffMode", () => {
  it("is same-expiry when all legs share one expiry", () => {
    expect(payoffMode([leg("call", "buy", 25000, 200), leg("put", "sell", 24900, 50)])).toBe("same-expiry");
  });

  it("is multi-expiry when expiries differ", () => {
    expect(
      payoffMode([leg("call", "buy", 25000, 200, 1, "2026-08-28"), leg("call", "sell", 25000, 150, 1, "2026-09-04")])
    ).toBe("multi-expiry");
  });

  it("is same-expiry for an empty leg set", () => {
    expect(payoffMode([])).toBe("same-expiry");
  });
});

describe("theoreticalBreakpoints", () => {
  it("returns the unique strategy strikes in ascending order", () => {
    expect(theoreticalBreakpoints([leg("call", "buy", 25100, 100), leg("put", "buy", 25000, 150), leg("call", "sell", 25100, 50)])).toEqual([
      25000,
      25100,
    ]);
  });

  it("ignores legs without a finite strike and returns [] for empty input", () => {
    expect(theoreticalBreakpoints([{ type: "call", action: "buy", price: 100 }])).toEqual([]);
    expect(theoreticalBreakpoints([])).toEqual([]);
  });
});

describe("theoreticalPayoffAnalysis — chain-independent extrema and tail slopes", () => {
  it("long call → finite extrema over {0} ∪ strikes, open-ended profit up the right tail", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200)]);
    expect(a.breakpoints).toEqual([25000]);
    expect(a.minPrice).toBe(0);
    expect(a.maxPrice).toBeNull(); // unbounded above
    expect(a.atZero).toBe(-200);
    expect(a.leftSlope).toBe(0);
    expect(a.rightSlope).toBe(1);
    expect(a.rightUnboundedUp).toBe(true);
    expect(a.rightUnboundedDown).toBe(false);
    expect(a.maxFinite).toBe(-200);
    expect(a.minFinite).toBe(-200);
  });

  it("bull call spread → flat tails, exact max profit/loss at the strike kinks", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)]);
    expect(a.breakpoints).toEqual([25000, 25100]);
    expect(a.atZero).toBe(-50);
    expect(a.atStrikes).toEqual([
      { price: 25000, pnl: -50 },
      { price: 25100, pnl: 50 },
    ]);
    expect(a.leftSlope).toBe(0);
    expect(a.rightSlope).toBe(0);
    expect(a.rightUnboundedUp).toBe(false);
    expect(a.rightUnboundedDown).toBe(false);
    expect(a.maxFinite).toBe(50);
    expect(a.minFinite).toBe(-50);
  });

  it("naked short call → open-ended loss down the right tail", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "sell", 25000, 200)]);
    expect(a.rightSlope).toBe(-1);
    expect(a.rightUnboundedDown).toBe(true);
    expect(a.rightUnboundedUp).toBe(false);
    expect(a.maxFinite).toBe(200); // credit received at/below the strike
  });

  it("long put → exact max profit at S = 0, bounded, no unbounded tails", () => {
    const a = theoreticalPayoffAnalysis([leg("put", "buy", 25000, 150)]);
    expect(a.atZero).toBe(25000 - 150);
    expect(a.leftSlope).toBe(-1); // puts gain as S falls toward 0
    expect(a.rightSlope).toBe(0);
    expect(a.rightUnboundedUp).toBe(false);
    expect(a.rightUnboundedDown).toBe(false);
    expect(a.maxFinite).toBe(25000 - 150);
    expect(a.minFinite).toBe(-150);
  });

  it("naked short put → worst case is at S = 0 (strike − premium), never Unlimited", () => {
    const a = theoreticalPayoffAnalysis([leg("put", "sell", 25000, 150)]);
    expect(a.atZero).toBe(150 - 25000);
    expect(a.leftSlope).toBe(1);
    expect(a.rightSlope).toBe(0);
    expect(a.rightUnboundedDown).toBe(false);
    expect(a.minFinite).toBe(150 - 25000);
    expect(a.maxFinite).toBe(150);
  });

  it("scales slopes and P&L by qty × lot size × multiplier", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200, 2)], { lotSize: 65, multiplier: 3 });
    expect(a.rightSlope).toBe(2 * 65 * 3);
    expect(a.atZero).toBe(-200 * 2 * 65 * 3);
  });
});

describe("theoreticalBreakevens — exact, chain-independent", () => {
  it("long call → single breakeven above the strike", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200)]);
    expect(theoreticalBreakevens(a)).toEqual([25200]);
  });

  it("bull call spread → single breakeven between the strikes", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)]);
    expect(theoreticalBreakevens(a)).toEqual([25050]);
  });

  it("long straddle → both breakevens symmetric around the ATM strike", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)]);
    expect(theoreticalBreakevens(a)).toEqual([24650, 25350]);
  });

  it("naked short call → breakeven above the strike where the loss turns unlimited", () => {
    const a = theoreticalPayoffAnalysis([leg("call", "sell", 25000, 200)]);
    expect(theoreticalBreakevens(a)).toEqual([25200]);
  });

  it("box spread (flat zero payoff) → no distinct breakevens", () => {
    const a = theoreticalPayoffAnalysis([
      leg("call", "buy", 25000, 100),
      leg("call", "sell", 25100, 50),
      leg("put", "sell", 25000, 50),
      leg("put", "buy", 25100, 100),
    ]);
    expect(theoreticalBreakevens(a)).toEqual([]);
  });
});

describe("payoffGrid — display grid, never below 0, includes every anchor", () => {
  it("covers chain strikes, strategy breakpoints and spot, sorted and unique", () => {
    const grid = payoffGrid({ strikes: [24500, 25000], breakpoints: [25000, 25200], spot: 24700 });
    expect(grid[0]).toBeGreaterThanOrEqual(0);
    expect(grid).toEqual([...grid].sort((a, b) => a - b));
    expect(new Set(grid).size).toBe(grid.length);
    [24500, 24700, 25000, 25200].forEach((s) => expect(grid).toContain(s));
  });

  it("pads beyond the anchor range on both sides and never goes below 0", () => {
    const grid = payoffGrid({ strikes: [100, 200], spot: 150 });
    expect(grid[0]).toBeLessThan(100);
    expect(grid[grid.length - 1]).toBeGreaterThan(200);
    expect(grid[0]).toBeGreaterThanOrEqual(0);
  });

  it("returns an empty grid when there are no anchors", () => {
    expect(payoffGrid({ strikes: [], breakpoints: [], spot: null })).toEqual([]);
  });
});
