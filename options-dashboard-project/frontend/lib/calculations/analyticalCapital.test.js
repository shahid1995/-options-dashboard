// Phase 6.2 — Analytical Capital Model tests.
//
// Deterministic fixtures (NIFTY, LOT = 65). Expected values are derived from
// the existing authoritative payoff/risk engine, never from a visible chain.

import { describe, it, expect, vi } from "vitest";
import {
  analyzeCapital,
  scenarioCapital,
  capitalEfficiencyInputs,
  BASIS_PREMIUM,
  BASIS_RISK_MODEL,
  BASIS_UNAVAILABLE,
  WARNING_INVALID_LEG,
  WARNING_MISSING_PREMIUM,
  WARNING_UNLIMITED_RISK,
  WARNING_MIXED_EXPIRY,
} from "./analyticalCapital";

const E = "2026-08-27"; // near expiry
const F = "2026-09-24"; // far expiry
const LOT = 65;

const leg = (overrides) => ({
  type: "call",
  action: "buy",
  strike: 24500,
  qty: 1,
  price: 89.65,
  expiry: E,
  ...overrides,
});

const run = (legs, opts) => analyzeCapital(legs, { lotSize: LOT, ...opts });

describe("analyzeCapital — structure classification (§8)", () => {
  it("1. Long Call → premium basis", () => {
    const r = run([leg()]);
    expect(r.basis).toBe(BASIS_PREMIUM);
    expect(r.source).toBe("ESTIMATED");
    expect(r.status).toBe("available");
    expect(r.value).toBe(89.65 * LOT); // 5827.25
  });

  it("2. Long Put → premium basis", () => {
    const r = run([leg({ type: "put", price: 90 })]);
    expect(r.basis).toBe(BASIS_PREMIUM);
    expect(r.value).toBe(90 * LOT);
  });

  it("3. Bull Call Spread → risk basis (defined loss)", () => {
    const r = run([leg({ strike: 24500, price: 125.25 }), leg({ action: "sell", strike: 25000, price: 35.6 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe((125.25 - 35.6) * LOT); // 5827.25 — worst-case defined loss
  });

  it("4. Bear Put Spread → risk basis", () => {
    const r = run([leg({ type: "put", strike: 25000, price: 200 }), leg({ type: "put", action: "sell", strike: 24500, price: 90 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(110 * LOT); // 7150
  });

  it("5. Bull Put Spread → risk basis (credit, defined)", () => {
    const r = run([leg({ type: "put", action: "sell", strike: 24500, price: 90 }), leg({ type: "put", strike: 24000, price: 40 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(450 * LOT); // 29250 = width 500 − credit 50
  });

  it("6. Bear Call Spread → risk basis (credit, defined)", () => {
    const r = run([leg({ action: "sell", strike: 24500, price: 35.6 }), leg({ strike: 25000, price: 15 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(479.4 * LOT); // 31161 = width 500 − credit 20.60
  });

  it("7. Iron Condor → risk basis", () => {
    const r = run([
      leg({ type: "put", strike: 24000, price: 30 }),
      leg({ type: "put", action: "sell", strike: 24500, price: 90 }),
      leg({ action: "sell", strike: 25000, price: 35.6 }),
      leg({ strike: 25500, price: 12 }),
    ]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(416.4 * LOT); // 27066 = width 500 − net credit 83.60
  });

  it("8. Butterfly → risk basis", () => {
    const r = run([
      leg({ strike: 24000, price: 40 }),
      leg({ action: "sell", strike: 24500, qty: 2, price: 125.25 }),
      leg({ strike: 25000, price: 15 }),
    ]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(195.5 * LOT); // 12707.50 = net debit (max loss)
  });

  it("9. Long Straddle → risk basis (finite)", () => {
    const r = run([leg({ price: 125.25 }), leg({ type: "put", price: 90 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(215.25 * LOT); // 13991.25
  });

  it("10. Long Strangle → risk basis (finite)", () => {
    const r = run([leg({ strike: 25000, price: 35.6 }), leg({ type: "put", strike: 24000, price: 30 })]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(65.6 * LOT); // 4264
  });

  it("11. Defined ratio (1:2 back spread) → risk basis when finite", () => {
    const r = run([
      leg({ action: "sell", strike: 24500, price: 125.25 }),
      leg({ strike: 25000, qty: 2, price: 35.6 }),
    ]);
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(445.95 * LOT); // 28986.75 = width 500 − credit 54.05
  });

  it("12. Naked Short Call → unavailable + UNLIMITED_RISK", () => {
    const r = run([leg({ action: "sell" })]);
    expect(r.value).toBeNull();
    expect(r.status).toBe("unavailable");
    expect(r.basis).toBe(BASIS_UNAVAILABLE);
    expect(r.warnings).toContain(WARNING_UNLIMITED_RISK);
  });

  it("13. Short Straddle → unavailable + UNLIMITED_RISK", () => {
    const r = run([leg({ action: "sell", price: 125.25 }), leg({ type: "put", action: "sell", price: 90 })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_UNLIMITED_RISK);
  });

  it("14. Short Strangle → unavailable + UNLIMITED_RISK", () => {
    const r = run([leg({ action: "sell", strike: 25000, price: 35.6 }), leg({ type: "put", action: "sell", strike: 24000, price: 30 })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_UNLIMITED_RISK);
  });

  it("15. Naked Short Put → follows the Phase 2 S ≥ 0 domain result (defined)", () => {
    const r = run([leg({ type: "put", action: "sell", price: 90 })]);
    // The existing engine classifies a naked short put as defined risk
    // (max loss at S = 0). No new risk interpretation is introduced.
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.status).toBe("available");
    expect(r.value).toBe((24500 - 90) * LOT); // 1586650
  });

  it("16. Calendar → premium basis when net debit; mixed-expiry warning preserved", () => {
    const r = run([leg({ action: "sell", price: 125.25, expiry: E }), leg({ price: 180, expiry: F })]);
    expect(r.basis).toBe(BASIS_PREMIUM);
    expect(r.status).toBe("available");
    expect(r.value).toBe(54.75 * LOT); // 3558.75 = net debit
    expect(r.notes.length).toBeGreaterThan(0); // engine warning preserved
  });

  it("17. Diagonal → premium basis when net debit", () => {
    const r = run([leg({ strike: 25000, price: 200, expiry: F }), leg({ action: "sell", price: 125.25, expiry: E })]);
    expect(r.basis).toBe(BASIS_PREMIUM);
    expect(r.value).toBe(74.75 * LOT); // 4858.75
  });

  it("18. Mixed-expiry credit → unavailable + MIXED_EXPIRY_APPROXIMATION + preserved warning", () => {
    const r = run([leg({ action: "sell", price: 125.25, expiry: E }), leg({ price: 100, expiry: F })]);
    expect(r.value).toBeNull();
    expect(r.status).toBe("unavailable");
    expect(r.warnings).toContain(WARNING_MIXED_EXPIRY);
    expect(r.notes.length).toBeGreaterThan(0);
  });
});

describe("analyzeCapital — input validation (§11)", () => {
  it("19. invalid leg (bad action)", () => {
    const r = run([leg({ action: "hold" })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_INVALID_LEG);
  });

  it("20. zero quantity → unavailable", () => {
    const r = run([leg({ qty: 0 })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_INVALID_LEG);
  });

  it("21. negative quantity → unavailable", () => {
    const r = run([leg({ qty: -1 })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_INVALID_LEG);
  });

  it("fractional quantity → unavailable", () => {
    const r = run([leg({ qty: 1.5 })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_INVALID_LEG);
  });

  it("22. missing premium → MISSING_PREMIUM", () => {
    const r = run([leg({ price: undefined })]);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(WARNING_MISSING_PREMIUM);
  });

  it("23. missing/invalid lot size → unavailable", () => {
    const r = analyzeCapital([leg()], { lotSize: 0 });
    expect(r.value).toBeNull();
    expect(r.status).toBe("unavailable");
    expect(r.warnings).toContain(WARNING_INVALID_LEG);
  });

  it("invalid strike / option type / malformed expiry → unavailable", () => {
    expect(run([leg({ strike: 0 })])).toMatchObject({ value: null, status: "unavailable" });
    expect(run([leg({ strike: -100 })])).toMatchObject({ value: null, status: "unavailable" });
    expect(run([leg({ type: "future" })])).toMatchObject({ value: null, status: "unavailable" });
    expect(run([leg({ expiry: "" })])).toMatchObject({ value: null, status: "unavailable" });
    expect(run([leg({ expiry: 12345 })])).toMatchObject({ value: null, status: "unavailable" });
  });

  it("zero legs → unavailable", () => {
    expect(analyzeCapital([], { lotSize: LOT })).toMatchObject({ value: null, status: "unavailable" });
  });

  it("negative premium → unavailable", () => {
    const r = run([leg({ price: -5 })]);
    expect(r.value).toBeNull();
    expect(r.status).toBe("unavailable");
  });
});

describe("analyzeCapital — number safety (§5/§9/§12)", () => {
  it("24. zero is a VALID estimate, never collapsed with unavailable", () => {
    // Same-strike opposing legs net to a perfect offset: value 0, available.
    const zero = run([leg({ price: 100 }), leg({ action: "sell", price: 100 })]);
    expect(zero.value).toBe(0);
    expect(zero.status).toBe("available");
    expect(zero.basis).toBe(BASIS_RISK_MODEL);

    // Unavailable is null, never 0.
    const missing = run([leg({ action: "sell" })]);
    expect(missing.value).toBeNull();
    expect(missing.status).toBe("unavailable");
  });

  it("25/26. no NaN / no Infinity ever", () => {
    const nan = run([leg({ price: NaN })]);
    expect(nan.value).toBeNull();
    expect(nan.warnings).toContain(WARNING_MISSING_PREMIUM);

    const inf = run([leg({ price: Infinity })]);
    expect(inf.value).toBeNull();

    // Every available result is a finite, JSON-safe number.
    const ok = run([leg()]);
    expect(Number.isFinite(ok.value)).toBe(true);
    expect(JSON.stringify(ok)).not.toMatch(/NaN|Infinity/);
  });
});

describe("analyzeCapital — scaling (§13)", () => {
  it("27. quantity scaling (1 lot vs 2 lots)", () => {
    expect(run([leg({ qty: 1 })]).value).toBe(89.65 * LOT);
    expect(run([leg({ qty: 2 })]).value).toBe(89.65 * LOT * 2);
  });

  it("28. lot-size scaling (65 vs 130)", () => {
    expect(run([leg()], { lotSize: 65 }).value).toBe(89.65 * 65);
    expect(run([leg()], { lotSize: 130 }).value).toBe(89.65 * 130);
  });

  it("multiplier scaling", () => {
    expect(analyzeCapital([leg()], { lotSize: LOT, multiplier: 2 }).value).toBe(89.65 * LOT * 2);
  });
});

describe("analyzeCapital — strategy mutation (§29)", () => {
  it("29. changing a leg (sell qty 1 → 2) flips the risk to UNLIMITED_RISK", () => {
    const spread = [leg({ strike: 24500, price: 125.25 }), leg({ action: "sell", strike: 25000, price: 35.6 })];
    expect(run(spread)).toMatchObject({ basis: BASIS_RISK_MODEL, value: 5827.25 });

    const ratio = [leg({ strike: 24500, price: 125.25 }), leg({ action: "sell", strike: 25000, qty: 2, price: 35.6 })];
    const mutated = run(ratio);
    expect(mutated.value).toBeNull();
    expect(mutated.warnings).toContain(WARNING_UNLIMITED_RISK);
  });

  it("mutating a leg price changes the defined-loss estimate", () => {
    const base = run([leg({ strike: 24350, price: 140 }), leg({ action: "sell", strike: 24550, price: 45 })]);
    const cheaper = run([leg({ strike: 24350, price: 140 }), leg({ action: "sell", strike: 24550, price: 20 })]);
    expect(base.value).toBe(95 * LOT); // 6175
    expect(cheaper.value).toBe(120 * LOT); // 7800 — larger net debit, larger defined loss
    expect(base.value).not.toBe(cheaper.value);
  });
});

describe("scenarioCapital (§15/§30/§33)", () => {
  it("30. same result contract, purely analytical", () => {
    const r = scenarioCapital([leg({ strike: 24500, price: 125.25 }), leg({ action: "sell", strike: 25000, price: 35.6 })], { lotSize: LOT });
    expect(r).toHaveProperty("value");
    expect(r).toHaveProperty("source");
    expect(r).toHaveProperty("basis");
    expect(r).toHaveProperty("status");
    expect(r).toHaveProperty("warnings");
    expect(r.basis).toBe(BASIS_RISK_MODEL);
    expect(r.value).toBe(5827.25);
  });

  it("33. tick compatibility: off-tick scenario premium is evaluated at the tradable ₹0.05 tick", () => {
    // 125.23 is not a valid NIFTY option tick → aligned to 125.25.
    const r = scenarioCapital([leg({ price: 125.23 })], { lotSize: LOT });
    expect(r.basis).toBe(BASIS_PREMIUM);
    expect(r.value).toBe(125.25 * LOT); // 8141.25
  });

  it("capital totals are NEVER tick-rounded (analytical path keeps raw premiums)", () => {
    const r = analyzeCapital([leg({ price: 125.23 })], { lotSize: LOT });
    expect(r.value).toBe(125.23 * LOT); // 8139.95 — premium flow, not a tradable price
  });
});

describe("broker independence (§15/§31/§32)", () => {
  it("31. no broker API call — fetch is never touched", () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn();
    try {
      analyzeCapital([leg()], { lotSize: LOT });
      scenarioCapital([leg({ price: 125.23 })], { lotSize: LOT });
      expect(global.fetch).not.toHaveBeenCalled();
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("32. broker/estimate separation — results are ESTIMATED, never BROKER_REPORTED", () => {
    const cases = [
      run([leg()]),
      run([leg({ action: "sell" })]),
      run([leg({ action: "sell", price: 125.25, expiry: E }), leg({ price: 100, expiry: F })]),
    ];
    for (const r of cases) {
      expect(r.source).toBe("ESTIMATED");
      expect(JSON.stringify(r)).not.toContain("BROKER_REPORTED");
    }
  });
});

describe("display contract (§34)", () => {
  it("34. values are rounded to exactly two decimals", () => {
    const r = run([leg({ price: 125.25 }), leg({ action: "sell", strike: 25000, price: 35.6 })]);
    expect(Number.isInteger(r.value * 100)).toBe(true);
    expect(r.value).toBe(5827.25);
  });
});

describe("capitalEfficiencyInputs (§21)", () => {
  it("prepares the five-field input contract (no metric computed)", () => {
    const inputs = capitalEfficiencyInputs({
      pnl: 1200.5,
      capitalUsed: 5827.25,
      brokerMargin: 37503,
      estimatedCapital: 5827.25,
    });
    expect(inputs).toEqual({
      pnl: 1200.5,
      capital_used: 5827.25,
      broker_margin: 37503,
      estimated_capital: 5827.25,
      available: true,
    });
  });

  it("available is false when pnl or capital_used is missing", () => {
    expect(capitalEfficiencyInputs({ pnl: null, capitalUsed: 100 }).available).toBe(false);
    expect(capitalEfficiencyInputs({ pnl: 100, capitalUsed: null }).available).toBe(false);
    expect(capitalEfficiencyInputs({}).available).toBe(false);
  });

  it("missing broker/estimated values stay null — never 0, never fabricated", () => {
    const inputs = capitalEfficiencyInputs({ pnl: 100, capitalUsed: 50 });
    expect(inputs.broker_margin).toBeNull();
    expect(inputs.estimated_capital).toBeNull();
  });
});
