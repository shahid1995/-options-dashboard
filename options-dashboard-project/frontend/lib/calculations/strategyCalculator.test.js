import { describe, it, expect } from "vitest";
import { calculateStrategy } from "./strategyCalculator";

const leg = (type, action, strike, price, qty = 1) => ({ type, action, strike, price, qty });

// Strikes sampled for the payoff range (ATM 25000, width 200).
const strikes = [24800, 24900, 25000, 25100, 25200];
const one = { strikes, lotSize: 1, multiplier: 1 };

describe("calculateStrategy — required max-loss cases", () => {
  it("Buy 1 CE → max loss = premium paid, not Unlimited; profit unlimited", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200)], one);
    expect(c.maxLoss).toBe(-200);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.netDebit).toBe(200);
    expect(c.netCredit).toBe(0);
  });

  it("Buy 1 PE → max loss = premium paid, not Unlimited", () => {
    const c = calculateStrategy([leg("put", "buy", 25000, 150)], one);
    expect(c.maxLoss).toBe(-150);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.netDebit).toBe(150);
  });

  it("Buy CE + Buy PE → max loss = total debit paid", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)], one);
    expect(c.maxLoss).toBe(-350);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.netDebit).toBe(350);
  });

  it("Sell 1 CE naked → max loss = Unlimited", () => {
    const c = calculateStrategy([leg("call", "sell", 25000, 200)], one);
    expect(c.maxLossUnlimited).toBe(true);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.netCredit).toBe(200);
    expect(c.netDebit).toBe(0);
  });

  it("Sell 1 PE naked → max loss = Unlimited", () => {
    expect(calculateStrategy([leg("put", "sell", 25000, 150)], one).maxLossUnlimited).toBe(true);
  });

  it("Bull Call Spread → defined max loss = net debit, defined max profit", () => {
    // Debit 50 < 100 strike width → max profit = width − debit = 50.
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)], one);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxLoss).toBe(-50); // net debit
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBe(50);
    expect(c.netDebit).toBe(50);
  });

  it("Bear Put Spread → defined max loss = net debit", () => {
    const c = calculateStrategy([leg("put", "buy", 25000, 150), leg("put", "sell", 24900, 50)], one);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxLoss).toBe(-100);
    expect(c.netDebit).toBe(100);
  });

  it("Covered call (short 25000 CE + long 25100 CE) → calculated, never Unlimited", () => {
    const c = calculateStrategy([leg("call", "sell", 25000, 200), leg("call", "buy", 25100, 100)], one);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxLoss).toBe(0); // credit equals the strike width
    expect(c.maxProfit).toBe(100);
  });

  it("regression: fractional premium on a long call is never Unlimited", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 205.85)], one);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxLoss).toBe(-205.85);
  });
});

describe("calculateStrategy — quantities and lot sizes", () => {
  it("scales net debit, max loss and max profit by qty × lot size", () => {
    // Extend above 25100 so the net-long ratio position's max profit shows up
    // (2 long calls vs 1 short call gains +1 per point above 25100).
    const wide = [...strikes, 25300];
    const c = calculateStrategy(
      [leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100, 1)],
      { strikes: wide, lotSize: 65, multiplier: 2 }
    );
    // per-lot net = 2×200 − 1×100 = 300 → total = 300 × 65 × 2
    expect(c.netPerLot).toBe(300);
    expect(c.netTotal).toBe(300 * 65 * 2);
    expect(c.netDebit).toBe(300 * 65 * 2);
    // max profit at 25300: 2×(300−200) − (200−100) = +100 per set
    expect(c.maxProfit).toBe(100 * 65 * 2);
    // max loss at/below 25000: 2×(−200) + 100 = −300 per set
    expect(c.maxLoss).toBe(-300 * 65 * 2);
  });

  it("breakeven of the ratio'd spread lands at the upper sampled strike", () => {
    const wide = [...strikes, 25300];
    const c = calculateStrategy(
      [leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100, 1)],
      { strikes: wide, lotSize: 65 }
    );
    expect(c.breakevens).toEqual([25200]);
  });
});

describe("calculateStrategy — curves and return metrics", () => {
  it("payoff curve matches the risk extrema and per-leg curve sums to it", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)];
    const c = calculateStrategy(legs, one);
    expect(c.payoffCurve).toHaveLength(strikes.length);
    expect(c.payoffCurve.map((p) => p.strike)).toEqual(strikes);
    c.perLegCurve.forEach((p, i) => {
      expect(p.combined).toBe(c.payoffCurve[i].pnl);
      expect(p.legPnl).toHaveLength(2);
    });
  });

  it("reports breakevens, reward/risk and ROI", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)], one);
    expect(c.breakevens).toEqual([25050]);
    expect(c.rewardRisk).toBe(1); // 50 / 50
    expect(c.roi).toBe(100); // 50 profit on 50 outlay
  });

  it("returns nulls/empties for an empty strategy", () => {
    const c = calculateStrategy([], one);
    expect(c.maxProfit).toBe(0);
    expect(c.maxLoss).toBe(0);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.breakevens).toEqual([]);
    expect(c.rewardRisk).toBeNull();
    expect(c.roi).toBeNull();
  });
});
