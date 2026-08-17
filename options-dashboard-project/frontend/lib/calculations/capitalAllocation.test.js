// ---------------------------------------------------------------------------
// Phase 6.4 — Capital Allocation & Portfolio Risk Controls (test matrix §39).
//
// The module under test is pure, deterministic, source-aware and
// MONITORING-ONLY: broker margin is BROKER_REPORTED only (never summed into
// an account figure), unavailable = null (never 0), unlimited risk = null +
// UNLIMITED_RISK (never a fabricated number), limits never block execution,
// and NaN/Infinity never leak. Phase 6.2 analytical capital is consumed
// (never recomputed) and Phase 6.3 capital-efficiency metrics reuse the
// totals (never duplicated).
// ---------------------------------------------------------------------------
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  calculateStrategyAllocation,
  calculatePortfolioAllocation,
  calculateAllocatedCapitalRatio,
  calculateCapitalConcentration,
  calculateRiskExposure,
  calculateAllocationLimits,
  calculatePortfolioRiskControls,
  STATUS_AVAILABLE,
  STATUS_PARTIAL,
  STATUS_UNAVAILABLE,
  BASIS_PREMIUM,
  BASIS_RISK_MODEL,
  BASIS_MAX_LOSS,
  BASIS_UNAVAILABLE,
  W_UNLIMITED_RISK,
  W_MIXED_EXPIRY,
  W_BROKER_MARGIN_NOT_ADDITIVE,
  W_PARTIAL_COVERAGE,
  W_NO_OPEN_STRATEGIES,
  W_INVALID_DENOMINATOR,
  DENOMINATOR_PAPER_STARTING_CAPITAL,
} from "./capitalAllocation";
// Phase 6.2 integration: the analytical capital model that allocation CONSUMES.
import { analyzeCapital } from "./analyticalCapital";
// Phase 6.3 integration: capital-efficiency metrics that consume the totals.
import { calculateReturnOnCapital } from "./capitalEfficiency";
// The authoritative strategy engine that supplies the theoretical max loss.
import { calculateStrategy } from "./strategyCalculator";

// ---- Fixtures ---------------------------------------------------------------

// Realistic NIFTY lot size used by the paper engine.
const LS = 65;

// Bull Call Spread (same-expiry, defined risk, RISK_MODEL analytical basis).
const bcsLegs = [
  { action: "buy", type: "call", strike: 25000, expiry: "2026-08-18", qty: 1, price: 100, lotSize: LS, symbol: "NIFTY" },
  { action: "sell", type: "call", strike: 25100, expiry: "2026-08-18", qty: 1, price: 80, lotSize: LS, symbol: "NIFTY" },
];

// Long Call (premium basis).
const longCallLegs = [
  { action: "buy", type: "call", strike: 25000, expiry: "2026-08-18", qty: 2, price: 120, lotSize: LS, symbol: "NIFTY" },
];

// Bull Put Spread (same-expiry, defined risk, credit).
const bpsLegs = [
  { action: "sell", type: "put", strike: 24800, expiry: "2026-08-18", qty: 1, price: 90, lotSize: LS, symbol: "NIFTY" },
  { action: "buy", type: "put", strike: 24700, expiry: "2026-08-18", qty: 1, price: 60, lotSize: LS, symbol: "NIFTY" },
];

// Calendar (mixed-expiry) — defined risk is NOT defensible across expiries.
const calendarLegs = [
  { action: "buy", type: "call", strike: 25000, expiry: "2026-08-18", qty: 1, price: 100, lotSize: LS, symbol: "NIFTY" },
  { action: "sell", type: "call", strike: 25000, expiry: "2026-08-25", qty: 1, price: 120, lotSize: LS, symbol: "NIFTY" },
];

// Naked Short Call — unlimited risk.
const shortCallLegs = [
  { action: "sell", type: "call", strike: 25000, expiry: "2026-08-18", qty: 1, price: 100, lotSize: LS, symbol: "NIFTY" },
];

const pos = (overrides) => ({
  positionId: "p1",
  id: "pos-p1",
  symbol: "NIFTY",
  type: "call",
  strike: 25000,
  expiry: "2026-08-18",
  action: "buy",
  qty: 1,
  lotSize: LS,
  entryPremium: 100,
  status: "open",
  executionId: "ex-bcs",
  strategyName: "Bull Call Spread",
  ...overrides,
});

// Allocate a strategy the way the UI does: Phase 6.2 analyzeCapital + the
// authoritative theoretical max loss from calculateStrategy + positions/legs
// reflecting CURRENT quantity.
function alloc({ executionId, strategyTag, positions, legs, lotSize = LS, extra = {} }) {
  const cap = analyzeCapital(legs, { lotSize, multiplier: 1 });
  const calc = calculateStrategy(legs, { lotSize, multiplier: 1 });
  return calculateStrategyAllocation({
    executionId,
    strategyTag,
    positions,
    legs,
    estimatedCapital: cap,
    maxLoss: calc.maxLoss,
    maxLossUnlimited: calc.maxLossUnlimited,
    payoffMode: calc.payoffMode,
    premiumOutlay: null,
    ...extra,
  });
}

describe("Phase 6.4 — Allocation (§39.1–9)", () => {
  it("1. one open strategy produces a complete allocation unit (never per-leg sums)", () => {
    const a = alloc({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs" })],
      legs: bcsLegs,
    });
    expect(a.executionId).toBe("ex-bcs");
    expect(a.strategyTag).toBe("Bull Call Spread");
    expect(a.openPositions).toBe(1);
    // Whole-strategy unit: estimated capital = analytical risk model, not a
    // leg-by-leg sum. BCS: net debit 20 × 65 = 1300 → abs max loss 1300.
    expect(a.estimatedCapital).toBe(1300);
    expect(a.capitalBasis).toBe(BASIS_RISK_MODEL);
    expect(a.definedRisk).toBe(1300);
    expect(a.unlimitedRisk).toBe(false);
    expect(a.allocationStatus).toBe(STATUS_AVAILABLE);
  });

  it("2. multiple strategies aggregate additively at the portfolio level", () => {
    const portfolio = calculatePortfolioAllocation({
      strategies: [
        alloc({ executionId: "ex-bcs", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-bcs" })], legs: bcsLegs }),
        alloc({ executionId: "ex-lc", strategyTag: "Long Call", positions: [pos({ executionId: "ex-lc", action: "buy", qty: 2, entryPremium: 120 })], legs: longCallLegs }),
      ],
      paperStartingCapital: 500000,
      paperAvailableCash: 480000,
    });
    expect(portfolio.openStrategyCount).toBe(2);
    expect(portfolio.openPositionCount).toBe(2);
    // Estimated capital: 1300 (BCS risk basis) + 15600 (long call premium) = 16900.
    expect(portfolio.totalEstimatedCapital).toBe(16900);
    expect(portfolio.estimatedCapitalCoverage).toBe("available");
    // Premium outlay: 6500 (BCS buy leg) + 15600 (long call) = 22100.
    expect(portfolio.totalPremiumOutlay).toBe(22100);
    expect(portfolio.status).toBe(STATUS_AVAILABLE);
  });

  it("3. multiple executions of the same strategy type stay separate by execution identity", () => {
    const a1 = alloc({ executionId: "ex-bcs-1", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-bcs-1" })], legs: bcsLegs });
    const a2 = alloc({ executionId: "ex-bcs-2", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-bcs-2" })], legs: bcsLegs });
    const conc = calculateCapitalConcentration([a1, a2], { basis: "ESTIMATED_CAPITAL" });
    // Two executions → two concentration items (never merged by strategy tag).
    expect(conc.items).toHaveLength(2);
    expect(conc.items.every((i) => i.count === 1)).toBe(true);
    expect(conc.highest.concentrationPct).toBe(50);
    // The portfolio treats each execution as ONE allocation unit.
    const portfolio = calculatePortfolioAllocation({ strategies: [a1, a2] });
    expect(portfolio.openStrategyCount).toBe(2);
    expect(portfolio.totalEstimatedCapital).toBe(2600);
  });

  it("4. partial exits reflect the CURRENT remaining quantity, not the entry quantity", () => {
    const a = alloc({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [
        pos({ executionId: "ex-bcs", qty: 1 }), // still open
        pos({ executionId: "ex-bcs", positionId: "p2", type: "call", strike: 25100, action: "sell", qty: 0, status: "closed" }), // fully exited leg
      ],
      legs: [
        { action: "buy", type: "call", strike: 25000, expiry: "2026-08-18", qty: 1, price: 100, lotSize: LS, symbol: "NIFTY" },
        { action: "sell", type: "call", strike: 25100, expiry: "2026-08-18", qty: 0, price: 80, lotSize: LS, symbol: "NIFTY" },
      ],
    });
    // Only the open position counts; the exited leg contributes no exposure.
    expect(a.openPositions).toBe(1);
    const exposure = calculateRiskExposure({ strategies: [a] });
    expect(exposure.totalContracts).toBe(LS); // 1 lot × 65, not 2 × 65
  });

  it("5. closed strategies are excluded from current allocation (caller contract mirrors the backend open-position invariant)", () => {
    const closed = alloc({
      executionId: "ex-closed",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-closed", status: "closed" })],
      legs: bcsLegs,
    });
    const open = alloc({ executionId: "ex-open", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-open" })], legs: bcsLegs });
    // The caller passes only OPEN executions (positionsWithLtp is already
    // server-filtered to status open AND net_quantity != 0).
    const openOnly = [closed, open].filter((a) => a.openPositions > 0);
    expect(openOnly.map((a) => a.executionId)).toEqual(["ex-open"]);
    const portfolio = calculatePortfolioAllocation({ strategies: openOnly });
    expect(portfolio.openStrategyCount).toBe(1);
    expect(portfolio.totalEstimatedCapital).toBe(1300);
  });

  it("6. zero-quantity positions never contribute exposure or allocation", () => {
    const a = alloc({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs", qty: 0 })],
      legs: [
        { action: "buy", type: "call", strike: 25000, expiry: "2026-08-18", qty: 0, price: 100, lotSize: LS, symbol: "NIFTY" },
        { action: "sell", type: "call", strike: 25100, expiry: "2026-08-18", qty: 0, price: 80, lotSize: LS, symbol: "NIFTY" },
      ],
    });
    const exposure = calculateRiskExposure({ strategies: [a] });
    expect(exposure.totalContracts).toBe(0);
    expect(exposure.status).toBe(STATUS_UNAVAILABLE);
    expect(a.premiumOutlay).toBe(0); // valid zero, not a fabricated figure
  });

  it("7. estimated capital aggregation is additive with full coverage", () => {
    const portfolio = calculatePortfolioAllocation({
      strategies: [
        alloc({ executionId: "ex-a", strategyTag: "A", positions: [pos({ executionId: "ex-a" })], legs: bcsLegs }),
        alloc({ executionId: "ex-b", strategyTag: "B", positions: [pos({ executionId: "ex-b" })], legs: bpsLegs }),
      ],
    });
    // 1300 (BCS) + 4550 (BPS) = 5850.
    expect(portfolio.totalEstimatedCapital).toBe(5850);
    expect(portfolio.estimatedCapitalCoverage).toBe("available");
  });

  it("8. premium-basis allocation is preserved from the Phase 6.2 result", () => {
    const a = alloc({ executionId: "ex-lc", strategyTag: "Long Call", positions: [pos({ executionId: "ex-lc", qty: 2, entryPremium: 120 })], legs: longCallLegs });
    expect(a.estimatedCapital).toBe(15600);
    expect(a.capitalBasis).toBe(BASIS_PREMIUM);
    expect(a.allocationStatus).toBe(STATUS_AVAILABLE);
  });

  it("9. risk-basis allocation is preserved from the Phase 6.2 result", () => {
    const a = alloc({ executionId: "ex-bcs", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-bcs" })], legs: bcsLegs });
    expect(a.capitalBasis).toBe(BASIS_RISK_MODEL);
    expect(a.riskBasis).toBe(BASIS_MAX_LOSS);
    expect(a.definedRisk).toBe(1300);
  });
});

describe("Phase 6.4 — Concentration (§39.10–14)", () => {
  const a = (executionId, tag, estimatedCapital, definedRisk, legs, extra = {}) =>
    calculateStrategyAllocation({
      executionId,
      strategyTag: tag,
      positions: [pos({ executionId })],
      legs,
      estimatedCapital: { value: estimatedCapital, source: "ESTIMATED", basis: "risk_model", status: "available", warnings: [] },
      maxLoss: definedRisk == null ? null : -definedRisk,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
      premiumOutlay: null,
      ...extra,
    });

  it("10. strategy concentration = each execution's share of total estimated capital (descriptive only)", () => {
    const s1 = a("ex-1", "Bull Call Spread", 5000, 5000, bcsLegs);
    const s2 = a("ex-2", "Bull Call Spread", 10000, 10000, bcsLegs);
    const s3 = a("ex-3", "Iron Condor", 5000, 5000, bcsLegs);
    const conc = calculateCapitalConcentration([s1, s2, s3], { basis: "ESTIMATED_CAPITAL" });
    expect(conc.label).toBe("Estimated Capital Concentration");
    expect(conc.total).toBe(20000);
    expect(conc.items).toHaveLength(3);
    const byId = Object.fromEntries(conc.items.map((i) => [i.key, i.concentrationPct]));
    expect(byId["ex-1"]).toBe(25);
    expect(byId["ex-2"]).toBe(50);
    expect(byId["ex-3"]).toBe(25);
    expect(conc.highest.key).toBe("ex-2");
  });

  it("11. underlying concentration groups by symbol without NIFTY-specific logic", () => {
    const nifty = a("ex-1", "Bull Call Spread", 6000, 6000, bcsLegs);
    const banknifty = a("ex-2", "Bull Put Spread", 4000, 4000, bpsLegs.map((l) => ({ ...l, symbol: "BANKNIFTY" })));
    const conc = calculateCapitalConcentration([nifty, banknifty], { basis: "ESTIMATED_CAPITAL", groupBy: "symbol" });
    const bySym = Object.fromEntries(conc.items.map((i) => [i.key, i.concentrationPct]));
    expect(bySym.NIFTY).toBe(60);
    expect(bySym.BANKNIFTY).toBe(40);
  });

  it("12. expiry concentration groups by the strategy's first current leg expiry", () => {
    const a18 = a("ex-1", "Bull Call Spread", 3000, 3000, bcsLegs);
    const a25 = a("ex-2", "Bull Call Spread", 7000, 7000, bcsLegs.map((l) => ({ ...l, expiry: "2026-08-25" })));
    const conc = calculateCapitalConcentration([a18, a25], { basis: "ESTIMATED_CAPITAL", groupBy: "expiry" });
    const byExp = Object.fromEntries(conc.items.map((i) => [i.key, i.concentrationPct]));
    expect(byExp["2026-08-18"]).toBe(30);
    expect(byExp["2026-08-25"]).toBe(70);
  });

  it("13. risk concentration = defined risk share of TOTAL defined risk", () => {
    const s1 = a("ex-1", "Bull Call Spread", 5000, 1000, bcsLegs);
    const s2 = a("ex-2", "Bull Put Spread", 3000, 3000, bpsLegs);
    const conc = calculateCapitalConcentration([s1, s2], { basis: "DEFINED_RISK" });
    expect(conc.label).toBe("Defined Risk Concentration");
    expect(conc.total).toBe(4000);
    const byId = Object.fromEntries(conc.items.map((i) => [i.key, i.concentrationPct]));
    expect(byId["ex-1"]).toBe(25);
    expect(byId["ex-2"]).toBe(75);
  });

  it("14. unlimited-risk strategies are excluded from the finite-risk denominator and surfaced separately", () => {
    const s1 = a("ex-1", "Bull Call Spread", 5000, 1000, bcsLegs);
    const s2 = calculateStrategyAllocation({
      executionId: "ex-2",
      strategyTag: "Naked Short Call",
      positions: [pos({ executionId: "ex-2", action: "sell", strike: 25000 })],
      legs: shortCallLegs,
      estimatedCapital: null,
      maxLoss: null,
      maxLossUnlimited: true,
      payoffMode: "same-expiry",
      premiumOutlay: null,
    });
    const conc = calculateCapitalConcentration([s1, s2], { basis: "DEFINED_RISK" });
    // Only the finite-risk strategy enters the denominator.
    expect(conc.total).toBe(1000);
    expect(conc.items).toHaveLength(1);
    expect(conc.items[0].concentrationPct).toBe(100);
    expect(conc.unlimitedRiskStrategyCount).toBe(1);
    expect(conc.unlimitedRiskExposure).toBe(true);
    // The unlimited strategy is never given a fabricated percentage.
    expect(conc.items.find((i) => i.key === "ex-2")).toBeUndefined();
  });
});

describe("Phase 6.4 — Limits (§39.15–20)", () => {
  it("15. limits are disabled (NOT_CONFIGURED) until explicitly configured", () => {
    const result = calculateAllocationLimits({ limits: {}, actuals: { estimatedCapitalAllocationPct: 40 } });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("NOT_CONFIGURED");
    expect(result.rules.maxEstimatedCapitalAllocationPct.breached).toBe(false);
    expect(result.rules.maxEstimatedCapitalAllocationPct.configured).toBe(false);
    expect(result.status).toBe("OK");
  });

  it("16. a configured limit with a healthy actual is OK", () => {
    const result = calculateAllocationLimits({
      limits: { maxEstimatedCapitalAllocationPct: 50, maxOpenStrategies: 10 },
      actuals: { estimatedCapitalAllocationPct: 20, openStrategies: 3 },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("OK");
    expect(result.rules.maxOpenStrategies.status).toBe("OK");
    expect(result.breachedCount).toBe(0);
    expect(result.status).toBe("OK");
  });

  it("17. approaching a limit (>= 90% of threshold) is WARNING, never breached", () => {
    const result = calculateAllocationLimits({
      limits: { maxEstimatedCapitalAllocationPct: 50 },
      actuals: { estimatedCapitalAllocationPct: 45 },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("WARNING");
    expect(result.rules.maxEstimatedCapitalAllocationPct.breached).toBe(false);
    expect(result.status).toBe("WARNING");
  });

  it("18. reaching a limit is BREACHED (monitoring only — nothing blocks)", () => {
    const result = calculateAllocationLimits({
      limits: { maxEstimatedCapitalAllocationPct: 50 },
      actuals: { estimatedCapitalAllocationPct: 50 },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("BREACHED");
    expect(result.rules.maxEstimatedCapitalAllocationPct.breached).toBe(true);
    expect(result.breachedCount).toBe(1);
    expect(result.status).toBe("BREACHED");
    // §24: a breach result is returned normally — no exception, no blocking.
  });

  it("19. unavailable input never auto-breaches", () => {
    const result = calculateAllocationLimits({
      limits: { maxEstimatedCapitalAllocationPct: 50 },
      actuals: { estimatedCapitalAllocationPct: null },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("UNAVAILABLE");
    expect(result.rules.maxEstimatedCapitalAllocationPct.breached).toBe(false);
    expect(result.rules.maxEstimatedCapitalAllocationPct.actual).toBe(null);
  });

  it("20. multiple limits are evaluated together with an overall status", () => {
    const result = calculateAllocationLimits({
      limits: {
        maxEstimatedCapitalAllocationPct: 50,
        maxDefinedRiskPct: 30,
        maxSingleStrategyAllocationPct: 25,
        maxSingleStrategyRiskPct: 40,
        maxUnderlyingConcentrationPct: 80,
        maxOpenStrategies: 5,
        allowUnlimitedRisk: false,
      },
      actuals: {
        estimatedCapitalAllocationPct: 55, // BREACHED
        definedRiskPct: 20, // OK
        maxSingleStrategyAllocationPct: 24, // WARNING (>= 22.5)
        maxSingleStrategyRiskPct: 35, // OK
        maxUnderlyingConcentrationPct: 100, // BREACHED
        openStrategies: 4, // OK
        unlimitedRiskStrategyCount: 1, // BREACHED (not allowed + present)
      },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("BREACHED");
    expect(result.rules.maxSingleStrategyAllocationPct.status).toBe("WARNING");
    expect(result.rules.allowUnlimitedRisk.status).toBe("BREACHED");
    expect(result.breachedCount).toBe(3);
    expect(result.status).toBe("BREACHED");
  });
});

describe("Phase 6.4 — Broker margin (§39.21–24)", () => {
  it("21. broker margin is consumed ONLY as BROKER_REPORTED (aggregate preferred)", () => {
    const strategy = calculateStrategyAllocation({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs" })],
      legs: bcsLegs,
      estimatedCapital: { value: 1300, source: "ESTIMATED", basis: "risk_model", status: "available", warnings: [] },
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
      brokerMargin: 37503,
      brokerMarginSource: "BROKER_REPORTED",
    });
    expect(strategy.brokerMargin).toBe(37503);
    expect(strategy.brokerMarginSource).toBe("BROKER_REPORTED");

    const portfolio = calculatePortfolioAllocation({
      strategies: [strategy],
      brokerMarginAggregate: 37503,
      brokerMarginSource: "BROKER_REPORTED",
    });
    expect(portfolio.brokerMargin).toBe(37503);
    expect(portfolio.brokerMarginSource).toBe("BROKER_REPORTED");
  });

  it("22. unavailable broker margin stays null — never paper cash, never estimated capital", () => {
    const strategy = calculateStrategyAllocation({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs" })],
      legs: bcsLegs,
      estimatedCapital: { value: 1300, source: "ESTIMATED", basis: "risk_model", status: "available", warnings: [] },
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
      brokerMargin: null,
    });
    expect(strategy.brokerMargin).toBe(null);

    const portfolio = calculatePortfolioAllocation({
      strategies: [strategy],
      paperStartingCapital: 500000,
      paperAvailableCash: 480000,
      brokerMarginAggregate: null,
    });
    expect(portfolio.brokerMargin).toBe(null);
    expect(portfolio.totalEstimatedCapital).toBe(1300); // estimate unaffected
  });

  it("23. per-strategy broker margins are NEVER summed into an account figure", () => {
    const strategy = calculateStrategyAllocation({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs" })],
      legs: bcsLegs,
      estimatedCapital: { value: 1300, source: "ESTIMATED", basis: "risk_model", status: "available", warnings: [] },
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
      brokerMargin: 20000,
      brokerMarginSource: "BROKER_REPORTED",
    });
    const portfolio = calculatePortfolioAllocation({ strategies: [strategy] });
    expect(portfolio.brokerMargin).toBe(null); // no aggregate provided → never summed
    expect(portfolio.warnings).toContain(W_BROKER_MARGIN_NOT_ADDITIVE);
    expect(portfolio.perStrategyBrokerPresent).toBe(true);
  });

  it("24. the module is user-data agnostic and side-effect free (isolation by construction)", () => {
    const inputs = {
      strategies: [alloc({ executionId: "ex-a", strategyTag: "A", positions: [pos({ executionId: "ex-a" })], legs: bcsLegs })],
      paperStartingCapital: 500000,
      paperAvailableCash: 480000,
    };
    const first = calculatePortfolioAllocation(inputs);
    const second = calculatePortfolioAllocation(inputs);
    expect(second).toEqual(first); // deterministic: same inputs → same outputs
    // Different user data never leaks between calls.
    const other = calculatePortfolioAllocation({ ...inputs, paperStartingCapital: 1000000, paperAvailableCash: 900000 });
    expect(other.paperStartingCapital).toBe(1000000);
    expect(first.paperStartingCapital).toBe(500000);
  });
});

describe("Phase 6.4 — Capital (§39.25–29)", () => {
  it("25. paper starting capital is exposed separately from broker values", () => {
    const portfolio = calculatePortfolioAllocation({
      strategies: [],
      paperStartingCapital: 500000,
      paperAvailableCash: 470000,
      brokerAvailableFunds: 375000,
    });
    expect(portfolio.paperStartingCapital).toBe(500000);
    expect(portfolio.paperAvailableCash).toBe(470000);
    expect(portfolio.brokerAvailableFunds).toBe(375000);
  });

  it("26. estimated capital is the total allocated capital", () => {
    const portfolio = calculatePortfolioAllocation({
      strategies: [alloc({ executionId: "ex-a", strategyTag: "A", positions: [pos({ executionId: "ex-a" })], legs: bcsLegs })],
    });
    expect(portfolio.totalEstimatedCapital).toBe(1300);
  });

  it("27. current paper cash is exposed as available cash", () => {
    const portfolio = calculatePortfolioAllocation({ strategies: [], paperAvailableCash: 482000 });
    expect(portfolio.paperAvailableCash).toBe(482000);
  });

  it("28. partial coverage is explicit — missing estimates are never treated as ₹0", () => {
    const missing = calculateStrategyAllocation({
      executionId: "ex-missing",
      strategyTag: "Naked Short Call",
      positions: [pos({ executionId: "ex-missing", action: "sell" })],
      legs: shortCallLegs,
      estimatedCapital: null, // Phase 6.2: unavailable for unlimited risk
      maxLoss: null,
      maxLossUnlimited: true,
      payoffMode: "same-expiry",
    });
    const present = alloc({ executionId: "ex-present", strategyTag: "Bull Call Spread", positions: [pos({ executionId: "ex-present" })], legs: bcsLegs });
    const portfolio = calculatePortfolioAllocation({ strategies: [missing, present] });
    expect(portfolio.estimatedCapitalCoverage).toBe("partial");
    expect(portfolio.totalEstimatedCapital).toBe(1300); // only the present one
    expect(portfolio.warnings).toContain(W_PARTIAL_COVERAGE);
    expect(portfolio.status).toBe(STATUS_PARTIAL);
    expect(missing.allocationStatus).toBe(STATUS_PARTIAL);
  });

  it("29. missing data yields unavailable — never fabricated zeros", () => {
    const portfolio = calculatePortfolioAllocation({ strategies: [] });
    expect(portfolio.totalEstimatedCapital).toBe(null);
    expect(portfolio.totalDefinedRisk).toBe(null);
    expect(portfolio.totalPremiumOutlay).toBe(null);
    expect(portfolio.status).toBe(STATUS_UNAVAILABLE);
    expect(portfolio.warnings).toContain(W_NO_OPEN_STRATEGIES);
  });
});

describe("Phase 6.4 — Safety (§39.30–35)", () => {
  it("30. NaN inputs are treated as missing and never leak NaN", () => {
    const a = calculateStrategyAllocation({
      executionId: "ex-1",
      strategyTag: "A",
      positions: [pos({ executionId: "ex-1" })],
      legs: bcsLegs,
      estimatedCapital: { value: NaN, source: "ESTIMATED", basis: "risk_model", status: "unavailable", warnings: [] },
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
      brokerMargin: NaN,
    });
    expect(a.estimatedCapital).toBe(null);
    expect(a.brokerMargin).toBe(null);
    expect(a.definedRisk).toBe(1300);
    expect(Number.isNaN(a.estimatedCapital)).toBe(false);
    expect(Number.isNaN(a.brokerMargin)).toBe(false);

    const portfolio = calculatePortfolioAllocation({
      strategies: [a],
      brokerMarginAggregate: NaN,
      paperAvailableCash: NaN,
    });
    expect(portfolio.totalEstimatedCapital).toBe(null);
    expect(portfolio.brokerMargin).toBe(null);
    expect(portfolio.paperAvailableCash).toBe(null);
  });

  it("31. Infinity inputs are treated as missing and never leak Infinity", () => {
    const ratio = calculateAllocatedCapitalRatio({ allocatedCapital: Infinity, denominator: 500000 });
    expect(ratio.value).toBe(null);
    expect(ratio.numerator).toBe(null);
    const portfolio = calculatePortfolioAllocation({ strategies: [], paperStartingCapital: Infinity });
    expect(portfolio.paperStartingCapital).toBe(null);
  });

  it("32. a zero denominator never divides — value stays null", () => {
    const ratio = calculateAllocatedCapitalRatio({ allocatedCapital: 1000, denominator: 0 });
    expect(ratio.value).toBe(null);
    expect(ratio.status).toBe("unavailable");
    expect(ratio.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("33. a negative denominator is invalid — value stays null", () => {
    const ratio = calculateAllocatedCapitalRatio({ allocatedCapital: 1000, denominator: -500 });
    expect(ratio.value).toBe(null);
    expect(ratio.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("34. null denominators produce a structured MISSING_DENOMINATOR result", () => {
    const ratio = calculateAllocatedCapitalRatio({ allocatedCapital: 1000, denominator: null });
    expect(ratio.value).toBe(null);
    expect(ratio.denominator).toBe(null);
    expect(ratio.warnings).toContain("MISSING_DENOMINATOR");
    expect(ratio.denominatorLabel).toBe("Paper Starting Capital");
    expect(ratio.denominatorSource).toBe(DENOMINATOR_PAPER_STARTING_CAPITAL);
  });

  it("35. mixed-expiry structures never receive a fabricated finite risk", () => {
    const a = calculateStrategyAllocation({
      executionId: "ex-cal",
      strategyTag: "Calendar",
      positions: [pos({ executionId: "ex-cal" })],
      legs: calendarLegs,
      estimatedCapital: { value: null, source: "ESTIMATED", basis: "unavailable", status: "unavailable", warnings: [] },
      maxLoss: null,
      maxLossUnlimited: false,
      payoffMode: "mixed-expiry",
    });
    expect(a.definedRisk).toBe(null);
    expect(a.riskBasis).toBe(BASIS_UNAVAILABLE);
    expect(a.warnings).toContain(W_MIXED_EXPIRY);
    expect(a.unlimitedRisk).toBe(false);

    const conc = calculateCapitalConcentration([a], { basis: "DEFINED_RISK", groupBy: "expiry" });
    expect(conc.warnings).toContain(W_MIXED_EXPIRY);
  });
});

describe("Phase 6.4 — Integration & invariants (§39.36–40)", () => {
  it("36. Phase 6.2 analytical capital is consumed, never recomputed", () => {
    // Build the Phase 6.2 result with the real module, then feed it through.
    const capResult = analyzeCapital(bcsLegs, { lotSize: LS, multiplier: 1 });
    expect(capResult.status).toBe("available");
    const a = calculateStrategyAllocation({
      executionId: "ex-bcs",
      strategyTag: "Bull Call Spread",
      positions: [pos({ executionId: "ex-bcs" })],
      legs: bcsLegs,
      estimatedCapital: capResult,
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
    });
    expect(a.estimatedCapital).toBe(capResult.value);
    expect(a.capitalBasis).toBe(BASIS_RISK_MODEL);
    expect(a.estimatedCapitalBasis).toBe(BASIS_RISK_MODEL);
    // Premium basis flows through identically.
    const lcResult = analyzeCapital(longCallLegs, { lotSize: LS, multiplier: 1 });
    const lc = calculateStrategyAllocation({
      executionId: "ex-lc",
      strategyTag: "Long Call",
      positions: [pos({ executionId: "ex-lc", qty: 2 })],
      legs: longCallLegs,
      estimatedCapital: lcResult,
      maxLoss: -15600,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
    });
    expect(lc.estimatedCapital).toBe(lcResult.value);
    expect(lc.capitalBasis).toBe(BASIS_PREMIUM);
  });

  it("37. Phase 6.3 capital-efficiency metrics consume the allocation totals (no duplication)", () => {
    const portfolio = calculatePortfolioAllocation({
      strategies: [alloc({ executionId: "ex-a", strategyTag: "A", positions: [pos({ executionId: "ex-a" })], legs: bcsLegs })],
    });
    const roc = calculateReturnOnCapital({
      pnl: 260,
      estimatedCapital: portfolio.totalEstimatedCapital, // 1300
      basis: "RISK_MODEL",
    });
    expect(roc.value).toBe(20); // 260 / 1300 × 100
    expect(roc.denominator).toBe(1300);
    expect(roc.denominatorLabel).toBe("Estimated Capital");
  });

  it("38. the domain module reuses engines — no duplicated payoff/risk/premium formulas", () => {
    const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "capitalAllocation.js"), "utf8");
    // The module must not re-derive the engines it consumes.
    expect(source).not.toMatch(/from\s+["'].\/payoff["']/);
    expect(source).not.toMatch(/from\s+["'].\/risk["']/);
    expect(source).not.toMatch(/from\s+["'].\/pricing["']/);
    expect(source).not.toMatch(/from\s+["'].\/strategyCalculator["']/);
  });

  it("39. the pure domain module makes no broker/network calls", async () => {
    const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "capitalAllocation.js"), "utf8");
    expect(source).not.toMatch(/fetch\s*\(/);
    expect(source).not.toMatch(/axios/);
    expect(source).not.toMatch(/XMLHttpRequest/);
    expect(source).not.toMatch(/WebSocket/);
    // Pure exports only — the module has no side effects at import time.
    const { calculateStrategyAllocation: f } = await import("./capitalAllocation");
    const out = f({
      executionId: "ex-a",
      strategyTag: "A",
      positions: [pos({ executionId: "ex-a" })],
      legs: bcsLegs,
      estimatedCapital: { value: 1300, source: "ESTIMATED", basis: "risk_model", status: "available", warnings: [] },
      maxLoss: -1300,
      maxLossUnlimited: false,
      payoffMode: "same-expiry",
    });
    expect(out.estimatedCapital).toBe(1300);
  });

  it("40. limits are monitoring-only — a breach never blocks or throws", () => {
    const result = calculateAllocationLimits({
      limits: { maxEstimatedCapitalAllocationPct: 50 },
      actuals: { estimatedCapitalAllocationPct: 99 },
    });
    expect(result.rules.maxEstimatedCapitalAllocationPct.status).toBe("BREACHED");
    // The full portfolio view still renders with a breached limit.
    const controls = calculatePortfolioRiskControls({
      strategies: [alloc({ executionId: "ex-a", strategyTag: "A", positions: [pos({ executionId: "ex-a" })], legs: bcsLegs })],
      paperStartingCapital: 10000,
      limits: { maxEstimatedCapitalAllocationPct: 10 },
    });
    expect(controls.limits.rules.maxEstimatedCapitalAllocationPct.status).toBe("BREACHED");
    expect(controls.limits.status).toBe("BREACHED");
    expect(controls.status).toBe(STATUS_AVAILABLE);
  });
});
