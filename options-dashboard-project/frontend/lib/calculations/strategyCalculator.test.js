import { describe, it, expect } from "vitest";
import { calculateStrategy } from "./strategyCalculator";

const leg = (type, action, strike, price, qty = 1, expiry = "2026-08-28") => ({ type, action, strike, price, qty, expiry });

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

  it("Sell 1 PE naked → max loss is bounded by S = 0 (strike − premium), not Unlimited", () => {
    const c = calculateStrategy([leg("put", "sell", 25000, 150)], one);
    expect(c.maxLossUnlimited).toBe(false); // the underlying cannot go below 0
    expect(c.maxLoss).toBe(150 - 25000);
    expect(c.maxProfit).toBe(150); // premium received
    expect(c.maxProfitUnlimited).toBe(false);
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
  it("scales net debit and max loss by qty × lot size; open-ended profit comes from the tail", () => {
    const wide = [...strikes, 25300];
    const c = calculateStrategy(
      [leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100, 1)],
      { strikes: wide, lotSize: 65, multiplier: 2 }
    );
    // per-lot net = 2×200 − 1×100 = 300 → total = 300 × 65 × 2
    expect(c.netPerLot).toBe(300);
    expect(c.netTotal).toBe(300 * 65 * 2);
    expect(c.netDebit).toBe(300 * 65 * 2);
    // Net long 1 call above 25100 → the upper tail is open-ended profit.
    expect(c.maxProfitUnlimited).toBe(true);
    // Finite reference over {0} ∪ breakpoints (25000, 25100): −100 per set at 25100.
    expect(c.maxProfit).toBe(-100 * 65 * 2);
    // max loss at/below 25000: 2×(−200) + 100 = −300 per set
    expect(c.maxLoss).toBe(-300 * 65 * 2);
    expect(c.maxLossUnlimited).toBe(false);
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
    expect(c.rewardRiskUnlimited).toBe(false);
    expect(c.roi).toBeNull();
    expect(c.roiUnlimited).toBe(false);
    expect(c.premiumOutlay).toBe(0);
  });
});

describe("calculateStrategy — unlimited reward/risk & premium ROI", () => {
  it("Long Call → reward/risk and premium ROI are unlimited, never finite sampled values", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200)], one);
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.rewardRisk).toBeNull();
    expect(c.rewardRiskUnlimited).toBe(true);
    expect(c.roi).toBeNull();
    expect(c.roiUnlimited).toBe(true);
  });

  it("Long Put → max profit is the exact finite value at S = 0 (strike − premium)", () => {
    const c = calculateStrategy([leg("put", "buy", 25000, 150)], one);
    expect(c.maxProfitUnlimited).toBe(false); // bounded below by S = 0
    expect(c.maxProfit).toBe(25000 - 150);
    expect(c.maxLoss).toBe(-150); // premium paid
    expect(c.rewardRisk).toBeCloseTo((25000 - 150) / 150, 5);
    expect(c.rewardRiskUnlimited).toBe(false);
    expect(c.roi).toBeCloseTo(((25000 - 150) / 150) * 100, 5);
    expect(c.roiUnlimited).toBe(false);
  });

  it("Bull Call Spread → finite reward/risk ≈ 1.231 and premium ROI ≈ 123.1%", () => {
    // BUY 24350 CE @125.25, SELL 24550 CE @35.60, lot size 65.
    // Net debit (125.25 − 35.60) × 65 = 5,827.25; max profit 200 × 65 − 5,827.25 = 7,172.75.
    const strikes = [24200, 24300, 24350, 24400, 24500, 24550, 24600];
    const c = calculateStrategy([leg("call", "buy", 24350, 125.25), leg("call", "sell", 24550, 35.6)], { strikes, lotSize: 65 });
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.netDebit).toBeCloseTo(5827.25, 2);
    expect(c.maxLoss).toBeCloseTo(-5827.25, 2);
    expect(c.maxProfit).toBeCloseTo(7172.75, 2);
    expect(c.rewardRisk).toBeCloseTo(1.231, 3);
    expect(c.rewardRiskUnlimited).toBe(false);
    expect(c.roi).toBeCloseTo(123.1, 1);
    expect(c.roiUnlimited).toBe(false);
  });

  it("Bear Put Spread → finite calculated reward/risk and premium ROI", () => {
    // Buy 25000 PE @200, sell 24800 PE @50 → debit 150, width 200 → max profit 50.
    const c = calculateStrategy([leg("put", "buy", 25000, 200), leg("put", "sell", 24800, 50)], one);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfit).toBe(50);
    expect(c.maxLoss).toBe(-150);
    expect(c.rewardRisk).toBeCloseTo(1 / 3, 5);
    expect(c.rewardRiskUnlimited).toBe(false);
    expect(c.roi).toBeCloseTo(100 / 3, 5);
    expect(c.roiUnlimited).toBe(false);
  });

  it("Naked Short Call → reward/risk is never a misleading finite ratio; premium ROI is N/A", () => {
    const c = calculateStrategy([leg("call", "sell", 25000, 200)], one);
    expect(c.maxLossUnlimited).toBe(true);
    expect(c.rewardRisk).toBeNull();
    expect(c.rewardRiskUnlimited).toBe(true);
    expect(c.roi).toBeNull();
    expect(c.roiUnlimited).toBe(false); // profit defined, but there is no premium outlay
  });

  it("Naked Short Put → loss is bounded at S = 0; reward/risk is finite; premium ROI is N/A", () => {
    const c = calculateStrategy([leg("put", "sell", 25000, 150)], one);
    expect(c.maxLossUnlimited).toBe(false); // bounded by the S = 0 floor
    expect(c.maxLoss).toBe(150 - 25000);
    expect(c.maxProfit).toBe(150); // premium received
    expect(c.rewardRisk).toBeCloseTo(150 / (25000 - 150), 5);
    expect(c.rewardRiskUnlimited).toBe(false);
    expect(c.roi).toBeNull(); // no premium outlay (credit strategy)
    expect(c.roiUnlimited).toBe(false);
  });
});

describe("calculateStrategy — required strategy regressions", () => {
  it("Short Straddle → unlimited loss, defined profit at the short strike", () => {
    const c = calculateStrategy([leg("call", "sell", 25000, 200), leg("put", "sell", 25000, 150)], one);
    expect(c.maxLossUnlimited).toBe(true);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBe(350); // credit received with both OTM
    expect(c.netCredit).toBe(350);
    expect(c.netDebit).toBe(0);
  });

  it("Long Straddle → max loss = total debit, unlimited profit", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)], one);
    expect(c.maxLoss).toBe(-350);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.netDebit).toBe(350);
  });

  it("Iron Condor → defined max loss and defined max profit", () => {
    const c = calculateStrategy(
      [leg("put", "buy", 24800, 40), leg("put", "sell", 24900, 80), leg("call", "sell", 25100, 70), leg("call", "buy", 25200, 35)],
      one
    );
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBe(75); // full credit received in the inner range
    expect(c.maxLoss).toBe(-25); // wing width minus credit
    expect(c.netCredit).toBe(75);
  });

  it("Ratio Call Spread (1:2) → net credit, capped profit, unlimited loss beyond the short strikes", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150, 2)], one);
    expect(c.maxLossUnlimited).toBe(true); // net short 1 call (2 sold vs 1 bought)
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBe(200); // peaks at the short strike, capped as the position turns over
    expect(c.netCredit).toBe(100);
    expect(c.netDebit).toBe(0);
  });

  it("multi-leg quantity: strap (2 call + 1 put) sums debit and stays defined-risk on loss", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200, 2), leg("put", "buy", 25000, 150)], one);
    expect(c.maxLoss).toBe(-550); // 2×200 + 150
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.netDebit).toBe(550);
  });

  it("surfaces the premium outlay (capital / premium requirement)", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150)], one);
    expect(c.premiumOutlay).toBe(200); // only the long leg
  });
});

describe("calculateStrategy — lot-size scaling", () => {
  it("1 lot vs 2 lots scale max loss, max profit and net flow linearly", () => {
    const oneLot = calculateStrategy([leg("call", "buy", 25000, 200)], one);
    const twoLots = calculateStrategy([leg("call", "buy", 25000, 200, 2)], one);
    expect(twoLots.maxLoss).toBe(oneLot.maxLoss * 2);
    expect(twoLots.netDebit).toBe(oneLot.netDebit * 2);
    expect(twoLots.premiumOutlay).toBe(oneLot.premiumOutlay * 2);
  });

  it("applies lot size × multiplier to contracts (65 × 2 = 130 per lot)", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200)], { strikes, lotSize: 65, multiplier: 2 });
    expect(c.netTotal).toBe(200 * 65 * 2);
    expect(c.maxLoss).toBe(-200 * 65 * 2);
    expect(c.premiumOutlay).toBe(200 * 65 * 2);
  });
});
describe("calculateStrategy — chain-independent theoretical engine", () => {
  it("Bull Call Spread max profit is based on the strategy strikes, not the visible chain", () => {
    // Strategy strikes 24350 / 24550; the visible chain stops at 24450.
    const narrowChain = [24300, 24350, 24400, 24450];
    const c = calculateStrategy([leg("call", "buy", 24350, 125.25), leg("call", "sell", 24550, 35.6)], { strikes: narrowChain, lotSize: 65 });
    expect(c.payoffMode).toBe("same-expiry");
    expect(c.maxProfit).toBeCloseTo(7172.75, 2); // NOT capped at the 24450 chain end
    expect(c.maxLoss).toBeCloseTo(-5827.25, 2);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.theoreticalBreakpoints).toEqual([24350, 24550]);
    expect(c.theoreticalMinPrice).toBe(0);
    expect(c.theoreticalMaxPrice).toBeNull(); // unbounded above
    expect(c.breakevens).toHaveLength(1);
    expect(c.breakevens[0]).toBeCloseTo(24350 + (125.25 - 35.6), 2); // 24439.65
    expect(c.calculationWarnings).toEqual([]);
  });

  it("Long Call stays Unlimited even when the visible chain ends near the strike", () => {
    const c = calculateStrategy([leg("call", "buy", 24350, 125.25)], { strikes: [24300, 24350, 24400], lotSize: 65 });
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.maxLoss).toBeCloseTo(-125.25 * 65, 2);
    expect(c.theoreticalBreakpoints).toEqual([24350]);
  });

  it("Long Put max profit is exact at S = 0 regardless of the chain floor", () => {
    const c = calculateStrategy([leg("put", "buy", 24350, 125.25)], { strikes: [24400, 24450, 24500], lotSize: 65 });
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBeCloseTo((24350 - 125.25) * 65, 2);
    expect(c.maxLoss).toBeCloseTo(-125.25 * 65, 2);
  });

  it("Bull Put Spread → defined risk from the strategy structure", () => {
    // Sell 25000 PE @150, buy 24800 PE @50 → credit 100, width 200.
    const c = calculateStrategy([leg("put", "sell", 25000, 150), leg("put", "buy", 24800, 50)], one);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfit).toBe(100);
    expect(c.maxLoss).toBe(-100);
    expect(c.netCredit).toBe(100);
  });

  it("Bear Call Spread → defined risk", () => {
    // Sell 25000 CE @200, buy 25200 CE @80 → credit 120, width 200 → max loss 80.
    const c = calculateStrategy([leg("call", "sell", 25000, 200), leg("call", "buy", 25200, 80)], one);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxProfit).toBe(120);
    expect(c.maxLoss).toBe(-80);
    expect(c.netCredit).toBe(120);
  });

  it("Call ratio 1:2 (buy 1, sell 2) → open-ended loss from the upper tail", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 150, 2)], one);
    expect(c.maxLossUnlimited).toBe(true); // net short 1 call → right tail slopes down
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxProfit).toBe(200);
  });

  it("Call ratio 2:1 (buy 2, sell 1) → open-ended profit from the upper tail", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100)], one);
    expect(c.maxProfitUnlimited).toBe(true); // net long 1 call → right tail slopes up
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.maxLoss).toBe(-300); // 2×(−200) + (−100) at/below 25000 per set
  });

  it("Mixed quantity 2:3 (buy 2, sell 3) → net short call, open-ended loss", () => {
    const c = calculateStrategy([leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100, 3)], one);
    expect(c.maxLossUnlimited).toBe(true);
    expect(c.maxProfitUnlimited).toBe(false);
  });

  it("Put ratio 1:2 → large but finite loss bounded by S = 0", () => {
    // Buy 1 put 25000 @150, sell 2 puts 24800 @125 → net short 1 put.
    const c = calculateStrategy([leg("put", "buy", 25000, 150), leg("put", "sell", 24800, 125, 2)], one);
    expect(c.maxLossUnlimited).toBe(false); // puts are bounded below by S = 0
    expect(c.maxLoss).toBe((25000 - 150) - 2 * (24800 - 125)); // exact value at S = 0
    expect(c.maxProfit).toBe(300); // at 24800: (200−150) + 2×125
    expect(c.maxProfitUnlimited).toBe(false);
  });

  it("Box spread → flat payoff emerges from the legs (max profit = max loss, never Unlimited)", () => {
    // Long box: buy 25000 CE, sell 25100 CE, sell 25000 PE, buy 25100 PE with
    // net debit = intrinsic width (100) → constant zero P&L.
    const c = calculateStrategy(
      [leg("call", "buy", 25000, 100), leg("call", "sell", 25100, 50), leg("put", "sell", 25000, 50), leg("put", "buy", 25100, 100)],
      one
    );
    expect(c.maxProfit).toBe(0);
    expect(c.maxLoss).toBe(0);
    expect(c.maxProfitUnlimited).toBe(false);
    expect(c.maxLossUnlimited).toBe(false);
    expect(c.breakevens).toEqual([]); // flat zero payoff has no distinct breakeven
  });

  it("Boundary checks: exact values at S = 0, at strikes, between and above strikes", () => {
    // Long call 25000 @200, short put 24800 @50 (bullish synthetic-like combo).
    const c = calculateStrategy([leg("call", "buy", 25000, 200), leg("put", "sell", 24800, 50)], one);
    // at S = 0: call −200 + put premium +50 − short-put intrinsic 24800 → −24950;
    // between 24800 and 25000 the payoff is flat at −150; above 25000 the call
    // carries the position (unlimited profit). The true worst case is S = 0.
    expect(c.maxProfitUnlimited).toBe(true);
    expect(c.maxLoss).toBe(-24950);
    expect(c.maxLossUnlimited).toBe(false);
  });
});

describe("calculateStrategy — multi-expiry fallback", () => {
  it("calendar spread → sampled approximation with an explicit warning, never presented as exact", () => {
    const c = calculateStrategy(
      [leg("call", "buy", 25000, 200, 1, "2026-08-28"), leg("call", "sell", 25000, 150, 1, "2026-09-04")],
      { strikes, lotSize: 1 }
    );
    expect(c.payoffMode).toBe("multi-expiry");
    expect(c.calculationWarnings.length).toBeGreaterThan(0);
    expect(c.calculationWarnings[0]).toMatch(/mixed-expiry/);
    expect(c.theoreticalBreakpoints).toEqual([]);
    expect(c.maxProfitUnlimited).toBe(false); // net call exposure is zero
    expect(c.maxLossUnlimited).toBe(false);
  });
});

