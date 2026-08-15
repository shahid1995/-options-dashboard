import { describe, it, expect } from "vitest";
import { STRATEGIES, STRATEGY_CATEGORIES, strategiesFor } from "./strategies.js";

// Chain with 9 strikes spaced 50 apart, ATM at index 4 (strike 25000).
function makeCtx() {
  const strikes = [24800, 24850, 24900, 24950, 25000, 25050, 25100, 25150, 25200];
  const chainByStrike = new Map(
    strikes.map((s) => [
      s,
      {
        call: { ltp: 25000 - s + 200 }, // e.g. 25000 -> 200
        put: { ltp: s - 25000 + 150 }, // e.g. 25000 -> 150
      },
    ])
  );
  return {
    strikes,
    atmIndex: 4,
    chainByStrike,
    chainByStrikeForExpiry: {},
    expiry: "2026-08-28",
    expiries: ["2026-08-28", "2026-09-04", "2026-09-11"],
  };
}

describe("STRATEGY_CATEGORIES", () => {
  it("covers every strategy's category", () => {
    for (const s of STRATEGIES) {
      expect(STRATEGY_CATEGORIES).toContain(s.category);
    }
  });
});

describe("STRATEGIES", () => {
  it("have unique ids", () => {
    const ids = STRATEGIES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every build returns legs with required fields", () => {
    const ctx = makeCtx();
    for (const s of STRATEGIES) {
      const legs = s.build(ctx);
      expect(legs.length).toBeGreaterThan(0);
      for (const l of legs) {
        expect(["call", "put"]).toContain(l.type);
        expect(["buy", "sell"]).toContain(l.action);
        expect(ctx.strikes).toContain(l.strike);
        expect(l.qty).toBeGreaterThan(0);
        expect(ctx.expiries).toContain(l.expiry); // calendar/diagonal use a second expiry
        expect(typeof l.price).toBe("number");
        expect(typeof l.id).toBe("string");
      }
    }
  });

  it("generates unique leg ids within a strategy", () => {
    const ctx = makeCtx();
    for (const s of STRATEGIES) {
      const ids = s.build(ctx).map((l) => l.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });
});

describe("individual strategy legs", () => {
  const get = (id) => STRATEGIES.find((s) => s.id === id);

  it("buy_call buys one ATM call at its premium", () => {
    const ctx = makeCtx();
    const legs = get("buy_call").build(ctx);
    expect(legs).toHaveLength(1);
    expect(legs[0]).toMatchObject({ type: "call", strike: 25000, action: "buy", qty: 1, price: 200 });
  });

  it("bull_call_spread buys ATM and sells ATM+2 strikes", () => {
    const legs = get("bull_call_spread").build(makeCtx());
    expect(legs.map((l) => [l.type, l.strike, l.action])).toEqual([
      ["call", 25000, "buy"],
      ["call", 25100, "sell"],
    ]);
  });

  it("call_ratio_back sells 1 ATM and buys 2 OTM calls", () => {
    const legs = get("call_ratio_back").build(makeCtx());
    expect(legs.map((l) => [l.strike, l.action, l.qty])).toEqual([
      [25000, "sell", 1],
      [25100, "buy", 2],
    ]);
  });

  it("iron_condor builds four legs around ATM", () => {
    const legs = get("iron_condor").build(makeCtx());
    expect(legs.map((l) => [l.type, l.strike, l.action])).toEqual([
      ["put", 24800, "buy"],
      ["put", 24900, "sell"],
      ["call", 25100, "sell"],
      ["call", 25200, "buy"],
    ]);
  });

  it("uses put premium for put legs", () => {
    const legs = get("buy_put").build(makeCtx());
    expect(legs[0]).toMatchObject({ type: "put", strike: 25000, price: 150 });
  });

  it("clamps strikes at the edges of the chain", () => {
    const ctx = makeCtx();
    ctx.atmIndex = 0; // ATM at lowest strike; negative offsets must clamp
    const legs = get("iron_condor").build(ctx);
    expect(legs.map((l) => l.strike)).toEqual([24800, 24800, 24900, 25000]);

    ctx.atmIndex = ctx.strikes.length - 1; // highest strike; positive offsets clamp
    const high = get("iron_condor").build(ctx);
    expect(high.map((l) => l.strike)).toEqual([25000, 25100, 25200, 25200]);
  });

  it("prices legs at 0 when the strike row is missing", () => {
    const ctx = makeCtx();
    ctx.chainByStrike.delete(25000);
    const legs = get("buy_call").build(ctx);
    expect(legs[0].price).toBe(0);
  });

  it("prices legs at 0 when ltp is null", () => {
    const ctx = makeCtx();
    ctx.chainByStrike.set(25000, { call: { ltp: null }, put: { ltp: null } });
    expect(get("buy_call").build(ctx)[0].price).toBe(0);
    expect(get("buy_put").build(ctx)[0].price).toBe(0);
  });
});

describe("new ready-made strategies", () => {
  const get = (id) => STRATEGIES.find((s) => s.id === id);

  it("adds the requested strategies to the catalog", () => {
    const ids = [
      "jade_lizard",
      "long_seagull",
      "short_seagull",
      "long_iron_condor",
      "long_iron_butterfly",
      "broken_wing_call",
      "broken_wing_put",
      "long_guts",
      "short_guts",
      "ratio_call_spread",
      "ratio_put_spread",
      "calendar",
      "diagonal_call",
      "diagonal_put",
      "box_spread",
    ];
    for (const id of ids) expect(get(id)).toBeTruthy();
  });

  it("jade_lizard sells a put and a call, buying a further-OTM call", () => {
    const legs = get("jade_lizard").build(makeCtx());
    expect(legs.map((l) => [l.type, l.strike, l.action, l.qty])).toEqual([
      ["put", 24950, "sell", 1],
      ["call", 25050, "sell", 1],
      ["call", 25150, "buy", 1],
    ]);
  });

  it("long iron condor inverts the wings of the short iron condor", () => {
    const legs = get("long_iron_condor").build(makeCtx());
    expect(legs.map((l) => [l.type, l.strike, l.action])).toEqual([
      ["put", 24800, "sell"],
      ["put", 24900, "buy"],
      ["call", 25100, "buy"],
      ["call", 25200, "sell"],
    ]);
  });

  it("ratio call spread buys 1 ATM and sells 2 OTM calls", () => {
    const legs = get("ratio_call_spread").build(makeCtx());
    expect(legs.map((l) => [l.type, l.strike, l.action, l.qty])).toEqual([
      ["call", 25000, "buy", 1],
      ["call", 25100, "sell", 2],
    ]);
  });

  it("box spread builds four legs around the ATM", () => {
    const legs = get("box_spread").build(makeCtx());
    expect(legs).toHaveLength(4);
    expect(legs.map((l) => [l.type, l.strike, l.action])).toEqual([
      ["call", 24900, "buy"],
      ["call", 25100, "sell"],
      ["put", 25100, "buy"],
      ["put", 24900, "sell"],
    ]);
  });

  it("calendar spread uses the next expiry for the far leg", () => {
    const ctx = makeCtx();
    const legs = get("calendar").build(ctx);
    expect(legs).toHaveLength(2);
    expect(new Set(legs.map((l) => l.expiry)).size).toBe(2);
    expect(legs[0].expiry).toBe(ctx.expiry);
    expect(legs[1].expiry).toBe("2026-09-04"); // next listed expiry after the primary
  });

  it("diagonal call buys far expiry at ATM and sells near expiry OTM", () => {
    const ctx = makeCtx();
    const legs = get("diagonal_call").build(ctx);
    expect(legs.map((l) => [l.action, l.strike, l.expiry])).toEqual([
      ["buy", 25000, "2026-09-04"],
      ["sell", 25050, ctx.expiry],
    ]);
  });
});

describe("strategiesFor", () => {
  it("returns only strategies of the requested category", () => {
    for (const cat of STRATEGY_CATEGORIES) {
      const list = strategiesFor(cat);
      expect(list.length).toBeGreaterThan(0);
      expect(list.every((s) => s.category === cat)).toBe(true);
    }
  });

  it("partitions all strategies across the categories", () => {
    const total = STRATEGY_CATEGORIES.reduce((n, c) => n + strategiesFor(c).length, 0);
    expect(total).toBe(STRATEGIES.length);
  });

  it("returns empty array for unknown category", () => {
    expect(strategiesFor("Nonexistent")).toEqual([]);
  });
});
