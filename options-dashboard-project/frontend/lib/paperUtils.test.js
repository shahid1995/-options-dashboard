import { describe, it, expect } from "vitest";
import { historyToCsv, strategyStats, recordEquityPoint, isWithinMarketHours, sanitizeEquityHistory } from "./paperUtils";

const trade = {
  symbol: "NIFTY",
  type: "call",
  strike: 24000,
  expiry: "2026-08-27",
  action: "buy",
  qty: 2,
  lotSize: 75,
  strategyName: "Long Call",
  entryPremium: 100,
  exitPrice: 150,
  realizedPnl: 7500,
  entryTime: "2026-08-13T09:00:00Z",
  exitTime: "2026-08-13T10:00:00Z",
};

describe("historyToCsv", () => {
  it("produces a header plus one line per trade", () => {
    const csv = historyToCsv([trade]);
    const [header, line] = csv.split("\n");
    expect(header).toBe("symbol,type,strike,expiry,action,qty,lot_size,strategy,entry_premium,exit_price,realized_pnl,entry_time,exit_time");
    expect(line).toBe("NIFTY,call,24000,2026-08-27,buy,2,75,Long Call,100,150,7500,2026-08-13T09:00:00Z,2026-08-13T10:00:00Z");
  });

  it("returns only the header for empty history", () => {
    expect(historyToCsv([]).split("\n")).toHaveLength(1);
  });

  it("escapes commas and quotes, defaults strategy to Custom, blanks missing values", () => {
    const csv = historyToCsv([{ ...trade, strategyName: 'Iron "Fly", v2', exitPrice: null }]);
    const line = csv.split("\n")[1];
    expect(line).toContain('"Iron ""Fly"", v2"');
    expect(line.split(",").length).toBeGreaterThan(13); // quoted comma splits naive count
    const noStrategy = historyToCsv([{ ...trade, strategyName: undefined }]).split("\n")[1];
    expect(noStrategy).toContain("Custom");
  });
});

describe("strategyStats", () => {
  it("groups by strategy with wins, win rate, and total P&L, sorted by P&L", () => {
    const stats = strategyStats([
      { strategyName: "Long Call", realizedPnl: 100 },
      { strategyName: "Long Call", realizedPnl: -50 },
      { strategyName: "Short Put", realizedPnl: 200 },
      { realizedPnl: -10 },
    ]);
    expect(stats).toEqual([
      { strategyName: "Short Put", trades: 1, wins: 1, totalPnl: 200, winRate: 1 },
      { strategyName: "Long Call", trades: 2, wins: 1, totalPnl: 50, winRate: 0.5 },
      { strategyName: "Custom", trades: 1, wins: 0, totalPnl: -10, winRate: 0 },
    ]);
  });

  it("returns an empty array for empty history", () => {
    expect(strategyStats([])).toEqual([]);
  });
});

describe("recordEquityPoint", () => {
  it("appends the first point", () => {
    expect(recordEquityPoint([], 500000, 1000)).toEqual([{ time: 1000, equity: 500000 }]);
  });

  it("skips points recorded within the minimum interval", () => {
    const points = [{ time: 1000, equity: 500000 }];
    expect(recordEquityPoint(points, 510000, 1000 + 59999)).toBe(points);
  });

  it("appends once the interval has elapsed", () => {
    const points = [{ time: 1000, equity: 500000 }];
    expect(recordEquityPoint(points, 510000, 1000 + 60000)).toHaveLength(2);
  });

  it("caps the series at maxPoints", () => {
    const points = Array.from({ length: 3 }, (_, i) => ({ time: i * 100000, equity: i }));
    const next = recordEquityPoint(points, 99, 10_000_000, 3);
    expect(next).toHaveLength(3);
    expect(next[2]).toEqual({ time: 10_000_000, equity: 99 });
    expect(next[0].equity).toBe(1);
  });

  it("with skipFlat drops a point equal to the previous one", () => {
    const points = [{ time: 1000, equity: 500000 }];
    expect(recordEquityPoint(points, 500000, 1000 + 60000, 500, 60000, { skipFlat: true })).toBe(points);
  });

  it("with skipFlat still records the first change after a flat run", () => {
    const points = [{ time: 1000, equity: 500000 }];
    const next = recordEquityPoint(points, 500250, 1000 + 60000, 500, 60000, { skipFlat: true });
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({ time: 1000 + 60000, equity: 500250 });
  });

  it("without skipFlat still appends equal values (backward compatible)", () => {
    const points = [{ time: 1000, equity: 500000 }];
    expect(recordEquityPoint(points, 500000, 1000 + 60000)).toHaveLength(2);
  });
});

describe("isWithinMarketHours", () => {
  // All times below are expressed in UTC; IST is UTC+05:30 year-round.
  const atIst = (hours, minutes) => new Date(Date.UTC(2026, 7, 13, hours - 5, minutes - 30)); // 2026-08-13 is a Thursday

  it("allows 09:15 and 15:30 on a weekday", () => {
    expect(isWithinMarketHours(atIst(9, 15))).toBe(true);
    expect(isWithinMarketHours(atIst(15, 30))).toBe(true);
  });

  it("blocks just before open and just after close", () => {
    expect(isWithinMarketHours(atIst(9, 14))).toBe(false);
    expect(isWithinMarketHours(atIst(15, 31))).toBe(false);
  });

  it("blocks mid-session overnight hours", () => {
    expect(isWithinMarketHours(atIst(0, 30))).toBe(false);
    expect(isWithinMarketHours(atIst(21, 0))).toBe(false);
  });

  it("blocks weekends", () => {
    const sat = new Date(Date.UTC(2026, 7, 15, 6, 0)); // 11:30 IST Saturday
    const sun = new Date(Date.UTC(2026, 7, 16, 6, 0)); // 11:30 IST Sunday
    expect(isWithinMarketHours(sat)).toBe(false);
    expect(isWithinMarketHours(sun)).toBe(false);
  });
});

describe("sanitizeEquityHistory", () => {
  // 2026-08-13 (Thursday) 09:15, 09:16 IST; then the weekend; then Monday 09:16.
  const thu915 = new Date(Date.UTC(2026, 7, 13, 3, 45)).getTime();
  const thu916 = new Date(Date.UTC(2026, 7, 13, 3, 46)).getTime();
  const mon916 = new Date(Date.UTC(2026, 7, 17, 3, 46)).getTime();

  it("drops off-market points and consecutive flat values", () => {
    const points = [
      { time: thu915, equity: 500000 },
      { time: thu916, equity: 500000 }, // flat -> dropped
      { time: mon916, equity: 500000 }, // off-market (weekend) -> dropped
    ];
    expect(sanitizeEquityHistory(points)).toEqual([{ time: thu915, equity: 500000 }]);
  });

  it("keeps market-hours changes", () => {
    const points = [
      { time: thu915, equity: 500000 },
      { time: thu916, equity: 501000 },
      { time: mon916, equity: 502000 },
    ];
    expect(sanitizeEquityHistory(points)).toEqual(points);
  });

  it("returns an empty array for empty or all-off-market input", () => {
    const sunday = new Date(Date.UTC(2026, 7, 16, 6, 0)).getTime(); // 11:30 IST Sunday
    expect(sanitizeEquityHistory([])).toEqual([]);
    expect(sanitizeEquityHistory([{ time: sunday, equity: 500000 }])).toEqual([]);
  });
});
