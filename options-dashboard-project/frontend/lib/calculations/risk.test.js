import { describe, it, expect } from "vitest";
import {
  sideNetQty,
  hasUnlimitedLoss,
  hasUnlimitedProfit,
  netDebitCredit,
  roiPct,
  rewardRisk,
} from "./risk";

const leg = (type, action, strike, price, qty = 1) => ({ type, action, strike, price, qty });

describe("sideNetQty", () => {
  it("is positive for net long, negative for net short, zero when hedged", () => {
    expect(sideNetQty([leg("call", "buy", 25000, 200)], "call")).toBe(1);
    expect(sideNetQty([leg("call", "sell", 25000, 200)], "call")).toBe(-1);
    expect(sideNetQty([leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 100)], "call")).toBe(0);
    expect(sideNetQty([leg("call", "buy", 25000, 200, 2), leg("call", "sell", 25100, 100)], "call")).toBe(1);
  });
});

describe("unlimited classification", () => {
  it("long-only positions are never unlimited-loss", () => {
    expect(hasUnlimitedLoss([leg("call", "buy", 25000, 200)])).toBe(false);
    expect(hasUnlimitedLoss([leg("put", "buy", 25000, 150)])).toBe(false);
    expect(hasUnlimitedLoss([leg("call", "buy", 25000, 200), leg("put", "buy", 25000, 150)])).toBe(false);
  });

  it("naked short options are unlimited-loss", () => {
    expect(hasUnlimitedLoss([leg("call", "sell", 25000, 200)])).toBe(true);
    expect(hasUnlimitedLoss([leg("put", "sell", 25000, 150)])).toBe(true);
  });

  it("hedged spreads are not unlimited-loss", () => {
    expect(hasUnlimitedLoss([leg("call", "sell", 25000, 200), leg("call", "buy", 25100, 100)])).toBe(false);
  });

  it("net long positions have unlimited profit, net short do not", () => {
    expect(hasUnlimitedProfit([leg("call", "buy", 25000, 200)])).toBe(true);
    expect(hasUnlimitedProfit([leg("call", "sell", 25000, 200)])).toBe(false);
  });
});

describe("netDebitCredit", () => {
  it("returns debit for a net-long position, scaled by lot size and multiplier", () => {
    const { perLot, total, netPerLot, netTotal } = netDebitCredit(
      [leg("call", "buy", 25000, 200), leg("call", "sell", 25100, 100)],
      { lotSize: 65, multiplier: 2 }
    );
    expect(perLot).toBe(100);
    expect(netPerLot).toBe(100);
    expect(total).toBe(100 * 65 * 2);
    expect(netTotal).toBe(100 * 65 * 2);
  });

  it("returns credit (negative) for a net-short position", () => {
    const { netTotal } = netDebitCredit([leg("put", "sell", 25000, 150), leg("call", "sell", 25000, 200)]);
    expect(netTotal).toBe(-350);
  });
});

describe("roiPct / rewardRisk", () => {
  it("computes ROI on the premium outlay", () => {
    expect(roiPct(100, 100)).toBe(100);
    expect(roiPct(100, 500)).toBe(20);
  });

  it("computes ROI against the absolute premium flow (credit positions included)", () => {
    expect(roiPct(100, -300)).toBeCloseTo(100 / 3);
    expect(roiPct(100, -100)).toBe(100);
  });

  it("is null when there is no premium flow", () => {
    expect(roiPct(100, 0)).toBeNull();
  });

  it("computes reward/risk as max profit over max loss", () => {
    expect(rewardRisk(100, -100)).toBe(1);
    expect(rewardRisk(200, -50)).toBe(4);
  });

  it("is null when the position cannot lose", () => {
    expect(rewardRisk(100, 0)).toBeNull();
    expect(rewardRisk(100, 50)).toBeNull();
  });
});
