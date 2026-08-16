import { describe, it, expect } from "vitest";
import {
  oiTotals,
  putCallRatio,
  maxPainStrike,
  maxOI,
} from "./analytics";
import {
  analyticsDisplay,
  concentration,
  equityChartData,
  formatDuration,
  hasCompletedTrades,
  journalDisplayRows,
  markedExposure,
  marketValue,
  resultBadge,
  sortJournalRows,
} from "./analytics";

const rows = [
  { strike: 100, call: { oi: 100 }, put: { oi: 50 } },
  { strike: 110, call: { oi: 200 }, put: { oi: 300 } },
  { strike: 120, call: { oi: 400 }, put: { oi: 150 } },
];

describe("oiTotals", () => {
  it("sums call and put OI", () => {
    expect(oiTotals(rows)).toEqual({ callOI: 700, putOI: 500 });
  });

  it("treats missing sides / OI as zero", () => {
    expect(oiTotals([{ strike: 100 }, { strike: 110, call: {}, put: { oi: 5 } }])).toEqual({ callOI: 0, putOI: 5 });
  });

  it("returns zeros for empty rows", () => {
    expect(oiTotals([])).toEqual({ callOI: 0, putOI: 0 });
  });
});

describe("putCallRatio", () => {
  it("returns putOI / callOI", () => {
    expect(putCallRatio(rows)).toBeCloseTo(500 / 700);
  });

  it("returns null when there is no call OI", () => {
    expect(putCallRatio([{ strike: 100, put: { oi: 10 } }])).toBeNull();
    expect(putCallRatio([])).toBeNull();
  });
});

describe("maxPainStrike", () => {
  it("returns null for empty rows", () => {
    expect(maxPainStrike([])).toBeNull();
  });

  it("finds the strike minimizing total intrinsic payout", () => {
    // At 100: calls pay 0, puts pay 300*10 + 150*20 = 6000
    // At 110: calls pay 100*10 = 1000, puts pay 150*10 = 1500 -> 2500
    // At 120: calls pay 100*20 + 200*10 = 4000, puts pay 0 -> 4000
    expect(maxPainStrike(rows)).toBe(110);
  });

  it("handles a single strike", () => {
    expect(maxPainStrike([{ strike: 100, call: { oi: 1 }, put: { oi: 1 } }])).toBe(100);
  });
});

describe("maxOI", () => {
  it("returns the largest single-side OI", () => {
    expect(maxOI(rows)).toBe(400);
  });

  it("returns 0 for empty or OI-less rows", () => {
    expect(maxOI([])).toBe(0);
    expect(maxOI([{ strike: 100 }])).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Phase 5.1 — portfolio & journal analytics display helpers
// ---------------------------------------------------------------------------

describe("formatDuration", () => {
  it("formats seconds / minutes / hours / days", () => {
    expect(formatDuration(30)).toBe("30s");
    expect(formatDuration(45 * 60)).toBe("45m");
    expect(formatDuration(2 * 3600 + 14 * 60)).toBe("2h 14m");
    expect(formatDuration(3 * 86400 + 4 * 3600)).toBe("3d 4h");
  });

  it("returns null for missing or NaN durations", () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(undefined)).toBeNull();
    expect(formatDuration(NaN)).toBeNull();
  });
});

describe("resultBadge", () => {
  it("maps WIN/LOSS/BREAKEVEN to label + color", () => {
    expect(resultBadge("WIN").label).toBe("WIN");
    expect(resultBadge("LOSS").label).toBe("LOSS");
    expect(resultBadge("BREAKEVEN").label).toBe("BREAKEVEN");
    expect(resultBadge("WIN").color).toMatch(/^#/);
  });

  it("maps unknown results to a dash", () => {
    expect(resultBadge(null).label).toBe("—");
    expect(resultBadge("PENDING").label).toBe("—");
  });
});

describe("analyticsDisplay", () => {
  const payload = {
    summary: {
      starting_capital: 500000,
      available_cash: 491000,
      invested_value: 8141.25,
      realized_pnl: 1300,
      unrealized_pnl: null,
      total_pnl: 1300,
      return_pct: 0.26,
      open_position_count: 1,
      open_strategy_count: 1,
    },
    performance: {
      total_completed_trades: 4,
      winning_trades: 3,
      losing_trades: 1,
      breakeven_trades: 0,
      win_rate: 75,
      average_winner: 2000,
      average_loser: -500,
      profit_factor: 3.25,
      expectancy: 1375,
      largest_winner: 4000,
      largest_loser: -500,
      current_win_streak: 2,
      current_loss_streak: 0,
      max_win_streak: 2,
      max_loss_streak: 1,
      average_holding_duration: 7200,
      median_holding_duration: 3600,
    },
    drawdown: {
      current_drawdown: -500,
      current_drawdown_pct: -0.1,
      max_drawdown: -1200,
      max_drawdown_pct: -0.24,
    },
    positions: { long_exposure: 8000, short_exposure: 141.25, total_exposure: 8141.25, items: [] },
    strategies: [],
    journal: [],
    daily_pnl: [],
    data_quality: { completed_trades: "available" },
  };

  it("shapes a full payload with separate realized/unrealized", () => {
    const d = analyticsDisplay(payload);
    expect(d.summary.startingCapital).toBe(500000);
    expect(d.summary.unrealizedPnl).toBeNull(); // unavailable != 0
    expect(d.performance.winRate).toBe(75);
    expect(d.performance.averageHoldingDuration).toBe("2h 0m");
    expect(d.drawdown.maxDrawdown).toBe(-1200);
  });

  it("handles a missing payload with null-safe defaults (no NaN/Infinity)", () => {
    const d = analyticsDisplay(null);
    expect(d.summary.startingCapital).toBeNull();
    expect(d.summary.realizedPnl).toBe(0);
    expect(d.performance.winRate).toBeNull();
    expect(d.performance.totalCompletedTrades).toBe(0);
    expect(d.drawdown.currentDrawdown).toBeNull();
    expect(d.strategies).toEqual([]);
    expect(d.journal).toEqual([]);
  });
});

describe("equityChartData", () => {
  it("maps server curve points for recharts", () => {
    const data = equityChartData([
      { date: "2026-08-14", pnl: 0, cumulative_pnl: 0, equity: 500000 },
      { date: "2026-08-15", pnl: 1000, cumulative_pnl: 1000, equity: 501000 },
    ]);
    expect(data).toEqual([
      { date: "2026-08-14", equity: 500000, cumulativePnl: 0, pnl: 0 },
      { date: "2026-08-15", equity: 501000, cumulativePnl: 1000, pnl: 1000 },
    ]);
  });

  it("returns an empty series for missing curves", () => {
    expect(equityChartData(null)).toEqual([]);
    expect(equityChartData(undefined)).toEqual([]);
  });
});

describe("journalDisplayRows", () => {
  const analytics = {
    journal: [
      {
        execution_id: "ex1",
        strategy: "Bull Call Spread",
        symbol: "NIFTY",
        entry_at: "2026-08-14T09:30:00Z",
        exit_at: "2026-08-14T11:44:00Z",
        duration_seconds: 8040,
        duration_label: "2h 14m",
        realized_pnl: 2450,
        result: "WIN",
        legs: [
          { symbol: "NIFTY", expiry: "2026-08-27", strike: 24350, option_type: "call", action: "buy", quantity: 1, lot_size: 65, fill_price: 125.25 },
          { symbol: "NIFTY", expiry: "2026-08-27", strike: 24550, option_type: "call", action: "sell", quantity: 1, lot_size: 65, fill_price: 35.6 },
        ],
      },
      {
        execution_id: "ex2",
        strategy: "Iron Condor",
        symbol: "NIFTY",
        entry_at: null,
        exit_at: null,
        duration_seconds: null,
        duration_label: null,
        realized_pnl: -900,
        result: "LOSS",
        legs: [],
      },
    ],
  };

  it("groups a multi-leg execution as ONE row with legs underneath", () => {
    const rows = journalDisplayRows(analytics);
    expect(rows).toHaveLength(2);
    expect(rows[0].strategy).toBe("Bull Call Spread");
    expect(rows[0].durationLabel).toBe("2h 14m");
    expect(rows[0].resultColor).toMatch(/^#/);
    expect(rows[0].legs).toHaveLength(2);
    expect(rows[0].legs[0].label).toContain("BUY NIFTY 24350 CE");
    expect(rows[0].legs[1].label).toContain("SELL NIFTY 24550 CE");
  });

  it("falls back gracefully for trades without timestamps/durations", () => {
    const rows = journalDisplayRows(analytics);
    expect(rows[1].durationLabel).toBeNull();
    expect(rows[1].entryLabel).toBe("—");
    expect(rows[1].resultColor).toMatch(/^#/);
  });

  it("returns [] when there is no journal", () => {
    expect(journalDisplayRows(null)).toEqual([]);
  });
});

describe("sortJournalRows", () => {
  const rows = [
    { realizedPnl: 100, duration_seconds: 3600, exitAt: "2026-08-15T10:00:00Z" },
    { realizedPnl: 500, duration_seconds: 7200, exitAt: "2026-08-14T10:00:00Z" },
    { realizedPnl: -50, duration_seconds: 1800, exitAt: "2026-08-16T10:00:00Z" },
  ];

  it("sorts by date (newest first)", () => {
    const out = sortJournalRows(rows, "date");
    expect(out.map((r) => r.realizedPnl)).toEqual([-50, 100, 500]);
  });

  it("sorts by P&L descending", () => {
    const out = sortJournalRows(rows, "pnl");
    expect(out.map((r) => r.realizedPnl)).toEqual([500, 100, -50]);
  });

  it("sorts by duration descending", () => {
    const out = sortJournalRows(rows, "duration");
    expect(out.map((r) => r.duration_seconds)).toEqual([7200, 3600, 1800]);
  });
});

describe("marketValue / concentration / exposure", () => {
  const pos = (overrides) => ({
    symbol: "NIFTY",
    strike: 24350,
    option_type: "call",
    net_quantity: 2,
    lot_size: 65,
    currentLtp: 150,
    ...overrides,
  });

  it("market value = |qty| × lot × LTP; null when no mark", () => {
    expect(marketValue(pos({}))).toBe(2 * 65 * 150);
    expect(marketValue(pos({ currentLtp: null }))).toBeNull();
  });

  it("concentration: single position = 100%", () => {
    const c = concentration([pos({})]);
    expect(c.total).toBe(19500);
    expect(c.items).toHaveLength(1);
    expect(c.items[0].concentrationPct).toBe(100);
  });

  it("concentration: multiple positions split proportionally (measurement only)", () => {
    const c = concentration([pos({ net_quantity: 1 }), pos({ strike: 24550, net_quantity: 1 })]);
    expect(c.total).toBe(19500);
    const pcts = c.items.map((i) => i.concentrationPct).sort((a, b) => b - a);
    expect(pcts[0]).toBe(50);
    expect(pcts[1]).toBe(50);
  });

  it("concentration: zero exposure -> pct null, never 0-without-data", () => {
    const c = concentration([]);
    expect(c.total).toBe(0);
    expect(c.items).toEqual([]);
    const c2 = concentration([pos({ currentLtp: null })]);
    expect(c2.total).toBe(0);
    expect(c2.items).toEqual([]);
  });

  it("marked exposure splits long vs short; null when no marks", () => {
    const e = markedExposure([pos({ net_quantity: 1 }), pos({ strike: 24550, net_quantity: -1 })]);
    expect(e.longExposure).toBe(9750);
    expect(e.shortExposure).toBe(9750);
    expect(e.totalExposure).toBe(19500);
    const none = markedExposure([pos({ currentLtp: null })]);
    expect(none.longExposure).toBeNull();
    expect(none.shortExposure).toBeNull();
  });
});

describe("hasCompletedTrades", () => {
  it("distinguishes 0 trades (no data) from real numbers", () => {
    expect(hasCompletedTrades(null)).toBe(false);
    expect(hasCompletedTrades({})).toBe(false);
    expect(hasCompletedTrades({ performance: { total_completed_trades: 0 } })).toBe(false);
    expect(hasCompletedTrades({ performance: { total_completed_trades: 3 } })).toBe(true);
  });
});
