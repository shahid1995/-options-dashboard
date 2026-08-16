import { describe, it, expect } from "vitest";
import { calculateScenario, calculateScenarioMatrix, resolveScenarioLegs } from "./scenario";
import { pnlAt } from "./payoff";

const NEAR = "2026-08-28";
const FAR = "2026-09-25";
const VALUATION = "2026-08-25"; // near expiry = 3 days out, far = 31 days out

function makeChain(strikes, { callLtp = 200, putLtp = 150, callIv = 0.18, putIv = 0.2 } = {}) {
  return {
    underlying_spot_price: 25000,
    chain: strikes.map((s) => ({
      strike: s,
      call: { ltp: callLtp, iv: callIv, delta: 0.5, theta: -1, gamma: 0.001, vega: 2 },
      put: { ltp: putLtp, iv: putIv, delta: -0.5, theta: -1, gamma: 0.001, vega: 2 },
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
      [NEAR]: makeChain([24900, 25000, 25100], { callIv: 0.18, putIv: 0.2 }),
      [FAR]: makeChain([24900, 25000, 25100], { callIv: 0.25, putIv: 0.27 }),
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

describe("calculateScenario — single legs", () => {
  it("spot-only scenario (absolute) reprices the leg above intrinsic", () => {
    const res = calculateScenario([leg()], marketContext(), { spot: 25200 });
    expect(res.spot).toBe(25200);
    expect(res.partial).toBe(false);
    expect(res.legs[0].scenarioValue).toBeGreaterThan(200);
    expect(res.legs[0].pnlVsEntry).toBeGreaterThan(0);
    expect(res.strategyValue).toBeCloseTo(res.legs[0].scenarioValue, 8);
  });

  it("spot-only scenario (relative %) resolves the scenario spot", () => {
    const res = calculateScenario([leg()], marketContext(), { spotPct: 0.01 });
    expect(res.spot).toBe(25250);
  });

  it("spot-only scenario (points) resolves the scenario spot", () => {
    const res = calculateScenario([leg()], marketContext(), { spotPoints: -250 });
    expect(res.spot).toBe(24750);
  });

  it("iv-only scenario shifts each leg's own IV by volatility points", () => {
    const base = calculateScenario([leg()], marketContext(), {});
    const res = calculateScenario([leg()], marketContext(), { ivShift: 0.02 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.2, 8);
    expect(res.legs[0].scenarioValue).toBeGreaterThan(base.legs[0].scenarioValue); // higher IV → higher call value
  });

  it("absolute IV override applies to every leg", () => {
    const res = calculateScenario([leg()], marketContext(), { iv: 0.3 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.3, 8);
  });

  it("time-only scenario uses a year-fraction T and decays the ATM call", () => {
    const res = calculateScenario([leg()], marketContext(), { timeShiftDays: 2 });
    expect(res.legs[0].scenarioT).toBeCloseTo(1 / 365, 10);
    expect(res.legs[0].scenarioValue).toBeLessThan(200); // less time → lower value
    expect(res.legs[0].pnlVsEntry).toBeLessThan(0);
  });

  it("combined spot + IV + time scenario applies all inputs together", () => {
    const res = calculateScenario([leg()], marketContext(), { spotPct: 0.02, ivShift: 0.03, timeShiftDays: 3 });
    expect(res.spot).toBe(25500);
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.21, 8);
    expect(res.legs[0].scenarioT).toBe(0); // 3 days forward = expiry day
    expect(Number.isFinite(res.strategyValue)).toBe(true);
  });
});

describe("calculateScenario — direction, size and scaling", () => {
  it("a SELL leg mirrors the BUY leg's P&L sign", () => {
    const buyRes = calculateScenario([leg()], marketContext(), { spot: 25200 });
    const sellRes = calculateScenario([leg({ action: "sell", price: 200 })], marketContext(), { spot: 25200 });
    expect(sellRes.legs[0].pnlVsEntry).toBeCloseTo(-buyRes.legs[0].pnlVsEntry, 8);
  });

  it("quantity scales the rupee figures", () => {
    const one = calculateScenario([leg()], marketContext(), { spot: 25200 });
    const two = calculateScenario([leg({ qty: 2 })], marketContext(), { spot: 25200 });
    expect(two.legs[0].pnlVsEntry).toBeCloseTo(2 * one.legs[0].pnlVsEntry, 8);
    expect(two.strategyValue).toBeCloseTo(2 * one.strategyValue, 8);
  });

  it("lot size scales the rupee figures", () => {
    const one = calculateScenario([leg()], marketContext(), { spot: 25200 });
    const lots = calculateScenario([leg()], marketContext({ lotSize: 65 }), { spot: 25200 });
    expect(lots.legs[0].pnlVsEntry).toBeCloseTo(65 * one.legs[0].pnlVsEntry, 8);
  });

  it("multi-leg strategy totals sum the per-leg figures", () => {
    const legs = [leg({ id: "a" }), leg({ id: "b", type: "put", price: 150 })];
    const res = calculateScenario(legs, marketContext(), { spot: 25200 });
    expect(res.strategyValue).toBeCloseTo(res.legs[0].scenarioValue + res.legs[1].scenarioValue, 8);
    expect(res.scenarioPnl).toBeCloseTo(res.legs[0].pnlVsEntry + res.legs[1].pnlVsEntry, 8);
    expect(res.totals.delta).toBeCloseTo(res.legs[0].delta + res.legs[1].delta, 8);
  });
});

describe("calculateScenario — multi-expiry", () => {
  // Calendar spread: buy far call, sell near call, both strike 25000.
  const calendarLegs = [
    leg({ id: "far", action: "buy", expiry: FAR }),
    leg({ id: "near", action: "sell", expiry: NEAR }),
  ];

  it("each leg uses its OWN expiry's IV (far 0.25, near 0.18)", () => {
    const res = calculateScenario(calendarLegs, marketContext(), {});
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.25, 8);
    expect(res.legs[1].scenarioIv).toBeCloseTo(0.18, 8);
  });

  it("each leg uses its OWN time to expiry", () => {
    const res = calculateScenario(calendarLegs, marketContext(), {});
    expect(res.legs[0].scenarioT).toBeCloseTo(31 / 365, 10);
    expect(res.legs[1].scenarioT).toBeCloseTo(3 / 365, 10);
  });

  it("an IV shift moves each leg from its own base IV", () => {
    const res = calculateScenario(calendarLegs, marketContext(), { ivShift: 0.02 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.27, 8);
    expect(res.legs[1].scenarioIv).toBeCloseTo(0.2, 8);
  });

  it("flags mixed expiries with MULTI_EXPIRY_APPROXIMATION", () => {
    const res = calculateScenario(calendarLegs, marketContext(), {});
    expect(res.warnings.some((w) => w.code === "MULTI_EXPIRY_APPROXIMATION")).toBe(true);
  });

  it("a same-expiry strategy does not emit the mixed-expiry warning", () => {
    const res = calculateScenario([leg()], marketContext(), {});
    expect(res.warnings.some((w) => w.code === "MULTI_EXPIRY_APPROXIMATION")).toBe(false);
  });
});

describe("calculateScenario — boundary and warnings", () => {
  it("at T = 0 the scenario P&L matches the Phase 2 expiry intrinsic payoff", () => {
    const legs = [leg({ price: 200 })];
    const res = calculateScenario(legs, marketContext(), { spot: 25100, timeShiftDays: 3 });
    expect(res.legs[0].scenarioT).toBe(0);
    expect(res.scenarioPnl).toBeCloseTo(pnlAt(legs, 25100, { lotSize: 1, multiplier: 1 }), 6);
    // Intrinsic 100 − entry 200 = −100
    expect(res.scenarioPnl).toBeCloseTo(-100, 6);
  });

  it("a missing IV marks the leg unavailable with MISSING_IV and a partial strategy", () => {
    const chainCache = { [NEAR]: makeChain([25000], { callIv: null }) };
    const res = calculateScenario([leg()], marketContext({ chainCache }), {});
    expect(res.warnings.some((w) => w.code === "MISSING_IV")).toBe(true);
    expect(res.warnings.some((w) => w.code === "MODEL_NOT_AVAILABLE")).toBe(true);
    expect(res.legs[0].available).toBe(false);
    expect(res.legs[0].scenarioValue).toBeNull();
    expect(res.partial).toBe(true);
  });

  it("an absolute IV override lets a leg be priced even without chain IV", () => {
    const chainCache = { [NEAR]: makeChain([25000], { callIv: null }) };
    const res = calculateScenario([leg()], marketContext({ chainCache }), { iv: 0.2 });
    expect(res.legs[0].available).toBe(true);
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.2, 8);
    expect(res.warnings.some((w) => w.code === "MISSING_IV")).toBe(true); // still reported, never invented
  });

  it("a negative scenario spot is rejected with INVALID_SPOT", () => {
    const res = calculateScenario([leg()], marketContext(), { spot: -100 });
    expect(res.spot).toBeNull();
    expect(res.warnings.some((w) => w.code === "INVALID_SPOT")).toBe(true);
    expect(res.legs[0].available).toBe(false);
    // An invalid spot is "unpriced", never silently ₹0.
    expect(res.strategyValue).toBeNull();
    expect(res.scenarioPnl).toBeNull();
    expect(res.partial).toBe(true);
  });

  it("clamps a negative scenario IV to the safe floor and warns", () => {
    const res = calculateScenario([leg()], marketContext(), { ivShift: -0.99 });
    expect(res.legs[0].scenarioIv).toBeGreaterThan(0);
    expect(res.warnings.some((w) => w.code === "INVALID_VOLATILITY")).toBe(true);
  });
});

describe("live vs modelled", () => {
  it("never overwrites the live LTP with the model value", () => {
    const res = calculateScenario([leg()], marketContext(), { spot: 25200 });
    expect(res.legs[0].currentLtp).toBe(200); // live chain LTP, untouched
    expect(res.legs[0].scenarioValue).not.toBe(200);
    expect(res.legs[0].modelVsMarket).toBeCloseTo(res.legs[0].scenarioValue - 200, 8);
    expect(res.legs[0].pnlChangeVsCurrent).toBeCloseTo(res.legs[0].scenarioValue - 200, 8);
  });

  it("exposes both P&L views separately (vs entry and vs current)", () => {
    const res = calculateScenario([leg()], marketContext(), { spot: 25200 });
    expect(res.scenarioPnl).toBeCloseTo(res.legs[0].pnlVsEntry, 8);
    expect(res.scenarioChange).toBeCloseTo(res.legs[0].pnlChangeVsCurrent, 8);
  });

  it("currentValue/scenarioChange are null when any leg has no live LTP", () => {
    const chainCache = { [NEAR]: makeChain([25000], { callLtp: null }) };
    const res = calculateScenario([leg()], marketContext({ chainCache }), { iv: 0.2 });
    expect(res.legs[0].available).toBe(true);
    expect(res.legs[0].currentLtp).toBeNull();
    expect(res.currentValue).toBeNull();
    expect(res.scenarioChange).toBeNull();
  });
});

describe("calculateScenarioMatrix", () => {
  it("spot×IV grid has the expected dimensions and labelled axes", () => {
    const m = calculateScenarioMatrix([leg()], marketContext(), { axis: "spotIv" });
    expect(m.axis).toBe("spotIv");
    expect(m.rows).toHaveLength(7);
    expect(m.columns).toHaveLength(5);
    expect(m.cells).toHaveLength(7);
    expect(m.cells[0]).toHaveLength(5);
  });

  it("custom axes are honoured", () => {
    const m = calculateScenarioMatrix([leg()], marketContext(), {
      axis: "spotIv",
      rows: [-0.01, 0, 0.01],
      columns: [-0.02, 0, 0.02],
    });
    expect(m.rows).toEqual([-0.01, 0, 0.01]);
    expect(m.columns).toEqual([-0.02, 0, 0.02]);
    expect(m.cells).toHaveLength(3);
  });

  it("the centre cell equals the single-scenario result at the current state", () => {
    const m = calculateScenarioMatrix([leg()], marketContext(), { axis: "spotIv" });
    const single = calculateScenario([leg()], marketContext(), { spotPct: 0, ivShift: 0 });
    const centre = m.cells[3][2]; // row 0%, col 0 vol
    expect(centre.scenarioPnl).toBeCloseTo(single.scenarioPnl, 6);
    expect(centre.strategyValue).toBeCloseTo(single.strategyValue, 6);
  });

  it("cells move with the axes: higher spot → higher call P&L", () => {
    const m = calculateScenarioMatrix([leg()], marketContext(), { axis: "spotIv" });
    const spotDown = m.cells[0][2].scenarioPnl; // -3% spot
    const spotUp = m.cells[6][2].scenarioPnl; // +3% spot
    expect(spotUp).toBeGreaterThan(spotDown);
  });

  it("spot×time and iv×time grids are also produced", () => {
    const st = calculateScenarioMatrix([leg()], marketContext(), { axis: "spotTime" });
    expect(st.columns).toEqual([0, 1, 3, 5, 7]);
    expect(st.cells).toHaveLength(7);
    const it = calculateScenarioMatrix([leg()], marketContext(), { axis: "ivTime" });
    expect(it.rows).toHaveLength(5);
    expect(it.cells[0]).toHaveLength(5);
  });

  it("null cells where the strategy cannot be priced", () => {
    const chainCache = { [NEAR]: makeChain([25000], { callIv: null }) };
    const m = calculateScenarioMatrix([leg()], marketContext({ chainCache }), { axis: "spotIv" });
    expect(m.warnings.some((w) => w.code === "MISSING_IV")).toBe(true);
    expect(m.cells[3][2].scenarioPnl).toBeNull();
  });
});

describe("resolveScenarioLegs", () => {
  it("resolves per-expiry market data for every leg", () => {
    const legs = [leg({ id: "near" }), leg({ id: "far", expiry: FAR })];
    const { legData, warnings } = resolveScenarioLegs(legs, marketContext());
    expect(warnings).toEqual([]);
    expect(legData[0].currentIv).toBeCloseTo(0.18, 8);
    expect(legData[1].currentIv).toBeCloseTo(0.25, 8);
    expect(legData[0].baseT).toBeCloseTo(3 / 365, 10);
    expect(legData[1].baseT).toBeCloseTo(31 / 365, 10);
  });

  it("reports MISSING_CHAIN_DATA when a leg's expiry chain is absent", () => {
    const legs = [leg({ id: "ghost", expiry: "2027-01-01" })];
    const { warnings } = resolveScenarioLegs(legs, marketContext());
    expect(warnings.some((w) => w.code === "MISSING_CHAIN_DATA")).toBe(true);
  });
});
