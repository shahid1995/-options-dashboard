import { describe, it, expect } from "vitest";
import { hasUnlimitedLoss, hasUnlimitedProfit, payoffRange } from "./options.js";

// Minimal leg factory for the payoff/risk helpers.
const leg = (type, action, strike, price, qty = 1) => ({ type, action, strike, price, qty });

// Strikes across which the at-expiry payoff is sampled.
const strikes = [24800, 24900, 25000, 25100, 25200];

describe("max-loss classification", () => {
  it("Buy 1 CE → max loss = debit paid, never Unlimited", () => {
    const legs = [leg("call", "buy", 25000, 200)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    expect(hasUnlimitedProfit(legs)).toBe(true); // upside is open-ended
    expect(payoffRange(legs, strikes).maxLoss).toBe(-200);
  });

  it("Buy 1 PE → max loss = debit paid, never Unlimited", () => {
    const legs = [leg("put", "buy", 25000, 150)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    expect(payoffRange(legs, strikes).maxLoss).toBe(-150);
  });

  it("Buy CE + Buy PE → max loss = total debit paid", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    expect(payoffRange(legs, strikes).maxLoss).toBe(-350);
  });

  it("Sell 1 CE naked → max loss = Unlimited", () => {
    expect(hasUnlimitedLoss([leg("call", "sell", 25000, 200)])).toBe(true);
    expect(hasUnlimitedProfit([leg("call", "sell", 25000, 200)])).toBe(false);
  });

  it("Sell 1 PE naked → loss is bounded by S = 0, never Unlimited", () => {
    // Phase 2 price-domain rule: the underlying cannot be negative, so a short
    // put's worst case is finite (strike − premium) at S = 0.
    expect(hasUnlimitedLoss([leg("put", "sell", 25000, 150)])).toBe(false);
    expect(hasUnlimitedProfit([leg("put", "sell", 25000, 150)])).toBe(false);
    // Display-layer sample over the visible strikes (worst visible = −50 at 24800);
    // the theoretical bound lives at S = 0, outside this chain.
    expect(payoffRange([leg("put", "sell", 25000, 150)], strikes).maxLoss).toBe(-50);
  });

  it("Bull Call Spread (long 25000 CE, short 25100 CE) → max loss = net debit 100", () => {
    const legs = [leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 100)];
    expect(hasUnlimitedLoss(legs)).toBe(false); // short side is hedged
    expect(payoffRange(legs, strikes).maxLoss).toBe(-100);
  });

  it("Bear Put Spread (long 25000 PE, short 24900 PE) → max loss = net debit 100", () => {
    const legs = [leg("put", "buy", 25000, 150), leg("put", "sell", 24900, 50)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    expect(payoffRange(legs, strikes).maxLoss).toBe(-100);
  });

  it("Covered short call (short 25000 CE + long 25100 CE) → calculated, not Unlimited", () => {
    const legs = [leg("call", "sell", 25000, 200), leg("call", "buy", 25100, 100)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    // Credit equals the strike width here, so worst case is breakeven (0).
    expect(payoffRange(legs, strikes).maxLoss).toBe(0);
    expect(payoffRange(legs, strikes).maxProfit).toBe(100);
  });

  it("Short Straddle (net short both sides) → Unlimited", () => {
    const legs = [leg("call", "sell", 25000, 200), leg("put", "sell", 25000, 150)];
    expect(hasUnlimitedLoss(legs)).toBe(true);
  });

  it("regression: fractional premium on a long call never flips to Unlimited", () => {
    // The original bug compared a rounded payoff min against the exact value,
    // so 205.85 (any fractional premium) was misclassified as Unlimited.
    const legs = [leg("call", "buy", 25000, 205.85)];
    expect(hasUnlimitedLoss(legs)).toBe(false);
    expect(payoffRange(legs, strikes).maxLoss).toBe(-205.85);
  });
});
