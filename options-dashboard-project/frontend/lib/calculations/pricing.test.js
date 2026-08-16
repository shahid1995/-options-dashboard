import { describe, it, expect } from "vitest";
import {
  normalPdf,
  normalCdf,
  bsCall,
  bsPut,
  bsValue,
  bsGreeks,
  bsDelta,
  bsGamma,
  bsTheta,
  bsVega,
  timeToExpiry,
  addDays,
} from "./pricing";

const S = 25000;
const K = 25000;
const T = 30 / 365; // ~1 month
const sigma = 0.2;
const r = 0.05;
const q = 0.01;

describe("normal distribution helpers", () => {
  it("normalCdf saturates and is symmetric", () => {
    expect(normalCdf(0)).toBeCloseTo(0.5, 10);
    expect(normalCdf(Infinity)).toBe(1);
    expect(normalCdf(-Infinity)).toBe(0);
    expect(normalCdf(3) + normalCdf(-3)).toBeCloseTo(1, 8);
    expect(normalPdf(0)).toBeCloseTo(0.3989422804, 8);
  });
});

describe("Black-Scholes values", () => {
  it("prices an ATM call close to the analytic value", () => {
    // ATM call ~ 0.4 * S * σ * √T with r=q≈0
    const v = bsCall(25000, 25000, 30 / 365, 0.2, 0, 0);
    expect(v).toBeGreaterThan(0);
    expect(v).toBeLessThan(0.4 * 25000 * 0.2 * Math.sqrt(30 / 365) * 1.2);
  });

  it("prices a call above intrinsic for positive T", () => {
    const v = bsCall(S, K, T, sigma, r, q);
    expect(v).toBeGreaterThan(Math.max(S - K, 0));
    expect(Number.isFinite(v)).toBe(true);
  });

  it("prices a put via the direct formula", () => {
    const v = bsPut(S, K, T, sigma, r, q);
    expect(v).toBeGreaterThan(Math.max(K - S, 0));
    expect(Number.isFinite(v)).toBe(true);
  });

  it("satisfies put-call parity: C - P = S e^-qT - K e^-rT", () => {
    const c = bsCall(S, K, T, sigma, r, q);
    const p = bsPut(S, K, T, sigma, r, q);
    const lhs = c - p;
    const rhs = S * Math.exp(-q * T) - K * Math.exp(-r * T);
    expect(lhs).toBeCloseTo(rhs, 8);
  });

  it("is monotonic: higher volatility raises both call and put values", () => {
    expect(bsCall(S, K, T, 0.15, r, q)).toBeLessThan(bsCall(S, K, T, 0.3, r, q));
    expect(bsPut(S, K, T, 0.15, r, q)).toBeLessThan(bsPut(S, K, T, 0.3, r, q));
  });

  it("call rises with spot, put falls with spot", () => {
    expect(bsCall(S + 500, K, T, sigma, r, q)).toBeGreaterThan(bsCall(S, K, T, sigma, r, q));
    expect(bsPut(S + 500, K, T, sigma, r, q)).toBeLessThan(bsPut(S, K, T, sigma, r, q));
  });

  it("deep ITM call ≈ intrinsic (adjusted for carry)", () => {
    const v = bsCall(S, K - 5000, T, 0.1, 0, 0);
    expect(v).toBeCloseTo(S - (K - 5000), 0);
  });

  it("deep OTM option value is tiny but finite and positive", () => {
    const v = bsCall(S, K + 8000, T, 0.2, r, q);
    expect(v).toBeGreaterThan(0);
    expect(v).toBeLessThan(1);
  });
});

describe("T = 0 intrinsic behaviour (Phase 2 transition)", () => {
  it("call value reduces to max(S-K, 0)", () => {
    expect(bsCall(S, K, 0, sigma)).toBe(Math.max(S - K, 0));
    expect(bsCall(S - 1000, K, 0, sigma)).toBe(0);
  });

  it("put value reduces to max(K-S, 0)", () => {
    expect(bsPut(S, K, 0, sigma)).toBe(Math.max(K - S, 0));
    expect(bsPut(S + 1000, K, 0, sigma)).toBe(0);
  });

  it("the T = 0 model value equals the Phase 2 intrinsic payoff per unit", () => {
    const callIntrinsic = Math.max(24350 - 24350, 0); // ATM → 0
    expect(bsValue("call", 24350, 24350, 0, 0.2)).toBe(callIntrinsic);
    const putIntrinsic = Math.max(25000 - 24350, 0); // 650
    expect(bsValue("put", 24350, 25000, 0, 0.2)).toBe(putIntrinsic);
  });
});

describe("volatility edge cases", () => {
  it("very small (but positive) volatility works without NaN", () => {
    const v = bsCall(S, K, T, 1e-4, r, q);
    expect(Number.isFinite(v)).toBe(true);
    expect(v).toBeGreaterThan(0);
  });

  it("zero volatility falls back to the deterministic forward value", () => {
    // r=q=0: pure intrinsic on the underlying.
    expect(bsCall(26000, 25000, T, 0, 0, 0)).toBe(1000);
    expect(bsPut(24000, 25000, T, 0, 0, 0)).toBe(1000);
    // Carry-adjusted: the forward strike is K·e^(−rT), so the call pays off
    // against the discounted strike.
    expect(bsCall(S, K, T, 0, 0.05, 0)).toBeCloseTo(Math.max(S - K * Math.exp(-0.05 * T), 0), 6);
    expect(bsPut(S, K, T, 0, 0.05, 0)).toBeCloseTo(Math.max(K * Math.exp(-0.05 * T) - S, 0), 6);
  });

  it("very high volatility stays finite", () => {
    expect(Number.isFinite(bsCall(S, K, T, 5, r, q))).toBe(true);
    expect(bsCall(S, K, T, 5, r, q)).toBeGreaterThan(0);
  });
});

describe("input validation", () => {
  it("rejects non-positive spot, strike and negative time", () => {
    expect(bsCall(0, K, T, sigma)).toBeNaN();
    expect(bsCall(-100, K, T, sigma)).toBeNaN();
    expect(bsCall(S, 0, T, sigma)).toBeNaN();
    expect(bsCall(S, K, -0.1, sigma)).toBe(0); // negative T treated as expired → intrinsic (0 for ATM)
  });

  it("rejects non-numeric inputs", () => {
    expect(bsCall("abc", K, T, sigma)).toBeNaN();
    expect(bsPut(S, K, T, "x")).toBeNaN();
  });
});

describe("model Greeks", () => {
  it("call delta is between 0 and 1 and put delta between -1 and 0", () => {
    expect(bsDelta("call", S, K, T, sigma, r, q)).toBeGreaterThan(0);
    expect(bsDelta("call", S, K, T, sigma, r, q)).toBeLessThan(1);
    expect(bsDelta("put", S, K, T, sigma, r, q)).toBeGreaterThan(-1);
    expect(bsDelta("put", S, K, T, sigma, r, q)).toBeLessThan(0);
  });

  it("delta moves toward 1 (call) / -1 (put) as the option goes ITM", () => {
    expect(bsDelta("call", S + 4000, K, T, sigma, r, q)).toBeGreaterThan(0.9);
    expect(bsDelta("put", S - 4000, K, T, sigma, r, q)).toBeLessThan(-0.9);
  });

  it("gamma is positive for both calls and puts", () => {
    expect(bsGamma("call", S, K, T, sigma, r, q)).toBeGreaterThan(0);
    expect(bsGamma("put", S, K, T, sigma, r, q)).toBeGreaterThan(0);
  });

  it("vega is positive for both calls and puts", () => {
    expect(bsVega("call", S, K, T, sigma, r, q)).toBeGreaterThan(0);
    expect(bsVega("put", S, K, T, sigma, r, q)).toBeGreaterThan(0);
  });

  it("theta (dValue/dT per year) is negative for long calls and puts", () => {
    expect(bsTheta("call", S, K, T, sigma, r, q)).toBeLessThan(0);
    expect(bsTheta("put", S, K, T, sigma, r, q)).toBeLessThan(0);
  });

  it("greeks are finite at T = 0 (step-function limits, no NaN)", () => {
    const callG = bsGreeks("call", S, K, 0, sigma);
    expect(callG.delta).toBeGreaterThanOrEqual(0);
    expect(callG.gamma).toBe(0);
    expect(callG.vega).toBe(0);
    expect(callG.theta).toBe(0);
    const putG = bsGreeks("put", S - 1000, K, 0, sigma);
    expect(putG.delta).toBe(-1);
  });

  it("greeks are finite for tiny volatility and deep OTM", () => {
    const g = bsGreeks("call", S, K + 8000, T, 1e-4, r, q);
    expect(Number.isFinite(g.delta)).toBe(true);
    expect(Number.isFinite(g.gamma)).toBe(true);
    expect(Number.isFinite(g.theta)).toBe(true);
    expect(Number.isFinite(g.vega)).toBe(true);
  });
});

describe("time representation", () => {
  it("timeToExpiry uses calendar days / 365 and clamps at 0", () => {
    expect(timeToExpiry("2026-08-28", "2026-08-28")).toBe(0);
    expect(timeToExpiry("2026-08-28", "2026-09-27")).toBeCloseTo(30 / 365, 10);
    expect(timeToExpiry("2026-09-01", "2026-08-28")).toBe(0);
  });

  it("returns null for unparseable dates", () => {
    expect(timeToExpiry("not-a-date", "2026-08-28")).toBeNull();
  });

  it("addDays shifts ISO dates by whole calendar days", () => {
    expect(addDays("2026-08-28", 3)).toBe("2026-08-31");
    expect(addDays("2026-08-28", -1)).toBe("2026-08-27");
    expect(addDays("2026-08-28", 0)).toBe("2026-08-28");
  });
});
