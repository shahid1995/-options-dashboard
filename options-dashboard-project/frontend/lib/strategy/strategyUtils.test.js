import { describe, it, expect } from "vitest";
import { buildStrategyContext, buildChainContext } from "./strategyUtils";

describe("buildStrategyContext", () => {
  const chain = (expiry) => ({
    expiry_date: expiry,
    underlying_spot_price: 25000,
    chain: [
      { strike: 24900, call: { ltp: 300 }, put: { ltp: 50 } },
      { strike: 25000, call: { ltp: 200 }, put: { ltp: 150 } },
      { strike: 25100, call: { ltp: 100 }, put: { ltp: 250 } },
    ],
  });

  it("produces the ctx shape ready-made strategies expect", () => {
    const chainCache = {
      "2026-08-28": chain("2026-08-28"),
      "2026-09-04": chain("2026-09-04"),
    };
    const chainByStrike = new Map(chainCache["2026-08-28"].chain.map((r) => [r.strike, r]));
    const ctx = buildStrategyContext({
      strikes: [24900, 25000, 25100],
      atmIndex: 1,
      chainByStrike,
      expiry: "2026-08-28",
      expiries: ["2026-08-28", "2026-09-04"],
      chainCache,
    });
    expect(ctx).toMatchObject({ strikes: [24900, 25000, 25100], atmIndex: 1, expiry: "2026-08-28", expiries: ["2026-08-28", "2026-09-04"] });
    expect(ctx.chainByStrike).toBe(chainByStrike);
    // Both fetched expiries get a strike -> row map for calendar/diagonal legs.
    expect(ctx.chainByStrikeForExpiry["2026-08-28"].get(25000).call.ltp).toBe(200);
    expect(ctx.chainByStrikeForExpiry["2026-09-04"].get(25100).put.ltp).toBe(250);
  });

  it("only maps expiries that have been fetched", () => {
    const ctx = buildStrategyContext({
      strikes: [],
      atmIndex: 0,
      chainByStrike: new Map(),
      expiry: "2026-08-28",
      expiries: ["2026-08-28", "2026-09-04"],
      chainCache: { "2026-08-28": chain("2026-08-28") },
    });
    expect(ctx.chainByStrikeForExpiry["2026-08-28"]).toBeInstanceOf(Map);
    expect(ctx.chainByStrikeForExpiry["2026-09-04"]).toBeUndefined();
  });
});

describe("buildChainContext", () => {
  it("caches sorted strikes, strike->row maps and per-expiry spots", () => {
    const ctx = buildChainContext({
      chainCache: {
        "2026-08-28": {
          chain: [
            { strike: 25100, call: { ltp: 1 }, put: { ltp: 1 } },
            { strike: 24900, call: { ltp: 1 }, put: { ltp: 1 } },
            { strike: 25000, call: { ltp: 1 }, put: { ltp: 1 } },
          ],
          underlying_spot_price: 25000,
        },
      },
      strikes: [24900, 25000, 25100],
      chainByStrike: new Map(),
      spot: 25000,
      atmIndex: 1,
      expiry: "2026-08-28",
    });
    expect(ctx.chainsByExpiry["2026-08-28"].chain).toEqual([24900, 25000, 25100]);
    expect(ctx.chainsByExpiry["2026-08-28"].rows.get(25000)).toBeTruthy();
    expect(ctx.chainsByExpiry["2026-08-28"].spot).toBe(25000);
    expect(ctx.atmIndex).toBe(1);
    expect(ctx.expiry).toBe("2026-08-28");
  });

  it("ignores empty chain entries and keeps primary fallbacks", () => {
    const ctx = buildChainContext({ chainCache: { "2026-09-04": null }, strikes: [25000], chainByStrike: new Map(), spot: null, atmIndex: 0, expiry: "2026-08-28" });
    expect(ctx.chainsByExpiry).toEqual({});
    expect(ctx.strikes).toEqual([25000]);
  });
});
