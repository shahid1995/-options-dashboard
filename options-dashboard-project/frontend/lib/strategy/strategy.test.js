import { describe, it, expect } from "vitest";
import {
  makeLeg,
  addLeg,
  updateLeg,
  removeLeg,
  moveLegByStrikes,
  changeLegStrike,
  changeLegExpiry,
  duplicateLeg,
  duplicateLegIn,
  reverseLeg,
  reverseLegIn,
  resetLegPrices,
  strikesForLeg,
  rowForLeg,
  priceForLeg,
  applyShift,
  applyWidth,
  buildHedgeLeg,
  addHedgeLeg,
  removeLastHedgeLeg,
} from "./strategy";
import { buildChainContext } from "./strategyUtils";

// Chain with 9 strikes spaced 50 apart, ATM at index 4 (strike 25000).
// call ltp = 25000 − strike + 200 (e.g. 25000 → 200); put ltp = strike − 25000 + 150.
function makeCtx() {
  const strikes = [24800, 24850, 24900, 24950, 25000, 25050, 25100, 25150, 25200];
  const chainByStrike = new Map(
    strikes.map((s) => [
      s,
      {
        call: { ltp: 25000 - s + 200 },
        put: { ltp: s - 25000 + 150 },
      },
    ])
  );
  return buildChainContext({
    chainCache: {
      "2026-08-28": {
        chain: strikes.map((s) => ({
          strike: s,
          call: { ltp: 25000 - s + 200 },
          put: { ltp: s - 25000 + 150 },
        })),
        underlying_spot_price: 25000,
      },
    },
    strikes,
    chainByStrike,
    spot: 25000,
    atmIndex: 4,
    expiry: "2026-08-28",
  });
}

const leg = (overrides = {}) =>
  makeLeg({ type: "call", strike: 25000, action: "buy", qty: 1, expiry: "2026-08-28", price: 200, ...overrides });

describe("makeLeg", () => {
  it("builds the canonical leg shape with defaults", () => {
    const l = makeLeg({ type: "put", strike: 25000 });
    expect(l).toMatchObject({ type: "put", strike: 25000, action: "buy", qty: 1, price: 0, hedge: false });
    expect(typeof l.id).toBe("string");
    expect(l.expiry).toBeNull();
  });

  it("coerces non-numeric prices to 0 and preserves valid prices", () => {
    expect(makeLeg({ type: "call", strike: 25000, price: "205.85" }).price).toBe(205.85);
    expect(makeLeg({ type: "call", strike: 25000, price: NaN }).price).toBe(0);
    expect(makeLeg({ type: "call", strike: 25000, price: null }).price).toBe(0);
  });

  it("keeps the supplied id", () => {
    expect(makeLeg({ type: "call", strike: 25000, id: "fixed" }).id).toBe("fixed");
  });
});

describe("leg mutations", () => {
  it("addLeg appends and never mutates", () => {
    const a = [leg({ id: "a" })];
    const next = addLeg(a, leg({ id: "b" }));
    expect(next).toHaveLength(2);
    expect(a).toHaveLength(1);
  });

  it("updateLeg patches only the matching leg", () => {
    const legs = [leg({ id: "a", qty: 1 }), leg({ id: "b", qty: 2 })];
    const next = updateLeg(legs, "b", { qty: 5 });
    expect(next[0].qty).toBe(1);
    expect(next[1].qty).toBe(5);
    expect(legs[1].qty).toBe(2); // input untouched
  });

  it("removeLeg drops the matching leg", () => {
    const next = removeLeg([leg({ id: "a" }), leg({ id: "b" })], "a");
    expect(next.map((l) => l.id)).toEqual(["b"]);
  });
});

describe("strike changes", () => {
  it("moves a leg one strike up and re-prices it from the chain", () => {
    const ctx = makeCtx();
    const moved = moveLegByStrikes(leg({ id: "a" }), 1, ctx);
    expect(moved.strike).toBe(25050);
    expect(moved.price).toBe(150); // call ltp at 25050
  });

  it("clamps at the edges of the chain", () => {
    const ctx = makeCtx();
    const top = moveLegByStrikes(leg({ id: "a", strike: 25200 }), 1, ctx);
    expect(top.strike).toBe(25200);
    const bottom = moveLegByStrikes(leg({ id: "a", strike: 24800 }), -1, ctx);
    expect(bottom.strike).toBe(24800);
  });

  it("returns the same leg for zero steps or an unknown strike", () => {
    const ctx = makeCtx();
    const l = leg({ id: "a" });
    expect(moveLegByStrikes(l, 0, ctx)).toBe(l);
    expect(moveLegByStrikes(leg({ id: "a", strike: 99999 }), 1, ctx).strike).toBe(99999);
  });

  it("changeLegStrike updates the list at the right index", () => {
    const ctx = makeCtx();
    const legs = [leg({ id: "a" }), leg({ id: "b" })];
    const next = changeLegStrike(legs, "b", -1, ctx);
    expect(next[0].strike).toBe(25000);
    expect(next[1].strike).toBe(24950);
  });
});

describe("resetLegPrices", () => {
  it("refreshes prices from the chain and keeps the current price when missing", () => {
    const ctx = makeCtx();
    const legs = [
      leg({ id: "a", strike: 25000, price: 1 }),
      leg({ id: "b", strike: 25200, price: 99 }),
      leg({ id: "c", strike: 99999, price: 77 }),
    ];
    const next = resetLegPrices(legs, ctx);
    expect(next[0].price).toBe(200);
    expect(next[1].price).toBe(0); // call ltp at 25200
    expect(next[2].price).toBe(77);
  });
});

describe("chain lookups", () => {
  it("prefers the leg's own expiry chain over the primary", () => {
    const ctx = makeCtx();
    expect(strikesForLeg(leg({ expiry: "2026-08-28" }), ctx)).toHaveLength(9);
    // A far expiry that hasn't been fetched falls back to the primary chain.
    expect(strikesForLeg(leg({ expiry: "2026-09-04" }), ctx)).toHaveLength(9);
    const row = rowForLeg(ctx, "call", 25000, "2026-08-28");
    expect(row.call.ltp).toBe(200);
    expect(priceForLeg(ctx, "put", 25000, "2026-08-28")).toBe(150);
  });
});

describe("applyShift", () => {
  it("moves every leg the same number of strikes", () => {
    const ctx = makeCtx();
    const legs = [leg({ id: "a", strike: 25000 }), leg({ id: "b", strike: 25100, type: "put" })];
    const next = applyShift(legs, 1, ctx);
    expect(next[0].strike).toBe(25050);
    expect(next[1].strike).toBe(25150);
    expect(next[1].price).toBe(300); // put ltp at 25150
  });
});

describe("applyWidth", () => {
  it("pushes wings away from the ATM on widen", () => {
    const ctx = makeCtx();
    const legs = [leg({ id: "a", strike: 25000 }), leg({ id: "b", strike: 25100 })];
    const next = applyWidth(legs, 1, ctx);
    // ATM long call drifts up; the +1 wing rides up too.
    expect(next[0].strike).toBe(25050);
    expect(next[1].strike).toBe(25150);
  });

  it("pulls wings back toward the ATM on narrow", () => {
    const ctx = makeCtx();
    const legs = [leg({ id: "a", strike: 25000 }), leg({ id: "b", strike: 25100 })];
    const next = applyWidth(legs, -1, ctx);
    expect(next[0].strike).toBe(24950); // ATM call drifts down
    expect(next[1].strike).toBe(25050);
  });
});

describe("hedge legs", () => {
  it("builds alternating long OTM call/put hedges creeping further OTM", () => {
    const ctx = makeCtx();
    // 50-point spacing here, so a +4 index offset lands 4 strikes above ATM.
    const level1 = buildHedgeLeg(1, ctx);
    expect(level1).toMatchObject({ type: "call", strike: 25200, action: "buy", qty: 1, hedge: true });
    const level2 = buildHedgeLeg(2, ctx);
    expect(level2).toMatchObject({ type: "put", strike: 24800, action: "buy", qty: 1, hedge: true });
  });

  it("addHedgeLeg appends and removeLastHedgeLeg removes only hedge legs (LIFO)", () => {
    const ctx = makeCtx();
    const base = [leg({ id: "a" })];
    const h1 = addHedgeLeg(base, 1, ctx);
    const h2 = addHedgeLeg(h1, 2, ctx);
    expect(h2).toHaveLength(3);
    const back = removeLastHedgeLeg(h2);
    expect(back).toHaveLength(2);
    expect(back[1].strike).toBe(25200); // level 1 hedge remains
    expect(removeLastHedgeLeg(base)).toBe(base); // no hedge legs → unchanged
  });
});

describe("duplicate / reverse", () => {
  it("duplicateLeg copies every field with a brand-new id", () => {
    const original = leg({ id: "a", type: "put", action: "sell", strike: 24900, qty: 2, price: 150, hedge: true });
    const copy = duplicateLeg(original);
    expect(copy).toMatchObject({ type: "put", action: "sell", strike: 24900, qty: 2, price: 150, hedge: true });
    expect(copy.id).not.toBe(original.id);
  });

  it("duplicateLegIn inserts the copy right after the original", () => {
    const legs = [leg({ id: "a" }), leg({ id: "b" })];
    const next = duplicateLegIn(legs, "a");
    expect(next.map((l) => l.id)).toEqual(["a", expect.any(String), "b"]);
    expect(next[1]).toMatchObject({ type: "call", action: "buy", strike: 25000, qty: 1, expiry: "2026-08-28", price: 200 });
    expect(next[0].id).toBe("a");
    expect(legs).toHaveLength(2); // input untouched
  });

  it("duplicateLegIn is a no-op for an unknown id", () => {
    const legs = [leg({ id: "a" })];
    expect(duplicateLegIn(legs, "nope")).toBe(legs);
  });

  it("reverseLeg flips buy → sell and preserves everything else", () => {
    const l = leg({ id: "a", action: "buy" });
    const flipped = reverseLeg(l);
    expect(flipped.action).toBe("sell");
    expect(flipped.id).toBe("a");
    expect(flipped.strike).toBe(25000);
    expect(reverseLeg(flipped).action).toBe("buy");
  });

  it("reverseLegIn reverses only the matching leg", () => {
    const legs = [leg({ id: "a", action: "buy" }), leg({ id: "b", action: "sell" })];
    const next = reverseLegIn(legs, "a");
    expect(next[0].action).toBe("sell");
    expect(next[1].action).toBe("sell");
    expect(legs[0].action).toBe("buy"); // input untouched
  });

  it("reverseLegIn is a no-op for an unknown id", () => {
    const legs = [leg({ id: "a" })];
    expect(reverseLegIn(legs, "nope")).toBe(legs);
  });
});

describe("expiry changes", () => {
  it("moves a leg to a loaded expiry and re-prices it from that chain", () => {
    const ctx = makeCtx();
    const next = changeLegExpiry([leg({ id: "a", expiry: "2026-08-28", price: 200 })], "a", "2026-08-28", ctx);
    expect(next[0].expiry).toBe("2026-08-28");
    expect(next[0].price).toBe(200); // same chain, same strike → same price
  });

  it("keeps the premium when the target expiry's chain is not loaded yet", () => {
    const ctx = makeCtx(); // only 2026-08-28 is loaded
    const next = changeLegExpiry([leg({ id: "a", price: 123 })], "a", "2026-09-04", ctx);
    expect(next[0].expiry).toBe("2026-09-04");
    expect(next[0].price).toBe(123); // never priced from the primary-chain fallback
    expect(next[0]).toMatchObject({ type: "call", strike: 25000, qty: 1, action: "buy" }); // other props preserved
  });

  it("is a no-op for the same expiry or an unknown leg", () => {
    const ctx = makeCtx();
    const legs = [leg({ id: "a" })];
    expect(changeLegExpiry(legs, "a", "2026-08-28", ctx)).toBe(legs);
    expect(changeLegExpiry(legs, "nope", "2026-09-04", ctx)).toBe(legs);
  });
});
