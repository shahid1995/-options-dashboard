import { describe, it, expect } from "vitest";
import { legGreeks, aggregateGreeks } from "./greeks";

const leg = (type, action, strike, qty = 1, expiry = "2026-08-28") => ({ type, action, strike, qty, expiry });

// A chain row in the backend's transformed shape: { strike, call, put }.
function row(strike, { delta = 0.5, gamma = 0.001, theta = -5, vega = 10 } = {}) {
  return {
    strike,
    call: { ltp: 200, delta, gamma, theta, vega },
    put: { ltp: 150, delta: delta - 1, gamma, theta, vega },
  };
}

function chainCache(rows) {
  return { "2026-08-28": { chain: rows } };
}

describe("legGreeks", () => {
  it("scales a buy by direction × qty × lot size × multiplier", () => {
    const g = legGreeks(leg("call", "buy", 25000, 2), row(25000), { lotSize: 65, multiplier: 3 });
    const mult = 2 * 65 * 3;
    expect(g.delta).toBe(0.5 * mult);
    expect(g.gamma).toBe(0.001 * mult);
    expect(g.theta).toBe(-5 * mult);
    expect(g.vega).toBe(10 * mult);
  });

  it("flips the sign for a sell", () => {
    const g = legGreeks(leg("call", "sell", 25000, 1), row(25000), { lotSize: 65 });
    expect(g.delta).toBe(-0.5 * 65);
    expect(g.vega).toBe(-10 * 65);
  });

  it("reads the put side for put legs", () => {
    const g = legGreeks(leg("put", "buy", 25000, 1), row(25000), { lotSize: 1 });
    expect(g.delta).toBe(-0.5); // put delta = call delta - 1
  });

  it("returns nulls when the chain row is missing", () => {
    const g = legGreeks(leg("call", "buy", 25000), undefined, { lotSize: 1 });
    expect(g).toEqual({ leg: expect.anything(), delta: null, gamma: null, theta: null, vega: null });
  });
});

describe("aggregateGreeks", () => {
  it("resolves each leg against its own expiry's chain and sums the totals", () => {
    const cache = chainCache([row(25000), row(25100, { delta: 0.4, gamma: 0.0008, theta: -4, vega: 8 })]);
    const legs = [leg("call", "buy", 25000, 1), leg("call", "sell", 25100, 1)];
    const { rows, totals } = aggregateGreeks(legs, cache, { lotSize: 1 });
    expect(rows).toHaveLength(2);
    expect(rows[0].delta).toBe(0.5);
    expect(rows[1].delta).toBe(-0.4);
    expect(totals.delta).toBeCloseTo(0.1);
    expect(totals.gamma).toBeCloseTo(0.001 - 0.0008);
    expect(totals.theta).toBeCloseTo(-5 + 4);
    expect(totals.vega).toBeCloseTo(10 - 8);
  });

  it("counts missing Greeks as zero in the totals", () => {
    const cache = chainCache([{ strike: 25000, call: { delta: 0.5 }, put: { delta: -0.5 } }]);
    const { totals } = aggregateGreeks([leg("call", "buy", 25000, 1)], cache, { lotSize: 1 });
    expect(totals.delta).toBe(0.5);
    expect(totals.gamma).toBe(0);
    expect(totals.theta).toBe(0);
    expect(totals.vega).toBe(0);
  });

  it("returns empty rows and zero totals for no legs", () => {
    const { rows, totals } = aggregateGreeks([], chainCache([row(25000)]), { lotSize: 1 });
    expect(rows).toEqual([]);
    expect(totals).toEqual({ delta: 0, gamma: 0, theta: 0, vega: 0 });
  });
});
