import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import PortfolioAnalyticsPanel from "./PortfolioAnalyticsPanel";

// Regression test for "ReferenceError: Line is not defined".
//
// The realized equity curve in PortfolioAnalyticsPanel renders recharts
// <Line>. Imports in one module are NOT visible in another, so this
// component must import Line from "recharts" itself. It previously did not
// (only page.js and IVAnalyticsPanel did), so the FIRST time a strategy
// completed a trade the equity-curve branch evaluated <Line> and threw
// "ReferenceError: Line is not defined" — the reported crash path was
// open position → partial/full exit → refresh → crash. This test renders the
// component with a curve that has a completed trade so the <Line> branch
// actually executes; before the fix it throws, after it renders.

// Server-shape analytics payload with ONE completed trade (equity curve has
// the baseline + one realized point, so the LineChart/<Line> branch runs).
function analyticsWithCompletedTrade() {
  return {
    summary: {
      starting_capital: 500000,
      available_cash: 480000,
      invested_value: 0,
      realized_pnl: 12000,
      unrealized_pnl: null,
      total_pnl: 12000,
      return_pct: 2.4,
      open_position_count: 0,
      open_strategy_count: 0,
    },
    performance: {
      total_completed_trades: 1,
      winning_trades: 1,
      losing_trades: 0,
      breakeven_trades: 0,
      win_rate: 100,
      average_winner: 12000,
      average_loser: null,
      profit_factor: null,
      expectancy: 12000,
      largest_winner: 12000,
      largest_loser: null,
      current_win_streak: 1,
      current_loss_streak: 0,
      max_win_streak: 1,
      max_loss_streak: 0,
      average_holding_duration: 3600,
      median_holding_duration: 3600,
    },
    drawdown: {
      current_drawdown: 0,
      current_drawdown_pct: 0,
      max_drawdown: 0,
      max_drawdown_pct: 0,
    },
    positions: { long_exposure: 0, short_exposure: 0, total_exposure: 0, items: [] },
    strategies: [
      {
        strategy: "Long Call",
        trades: 1,
        wins: 1,
        losses: 0,
        win_rate: 100,
        total_pnl: 12000,
        average_pnl: 12000,
        profit_factor: null,
        expectancy: 12000,
      },
    ],
    journal: [
      {
        execution_id: "ex-1",
        strategy: "Long Call",
        symbol: "NIFTY",
        entry_at: "2026-08-01T09:30:00Z",
        exit_at: "2026-08-01T10:00:00Z",
        duration_label: "30m",
        realized_pnl: 12000,
        result: "WIN",
        legs: [{ action: "buy", symbol: "NIFTY", strike: 25000, option_type: "call", quantity: 1, lot_size: 65 }],
      },
    ],
    equity_curve: [
      { date: "2026-07-01", equity: 500000, cumulative_pnl: 0, pnl: 0 },
      { date: "2026-08-01", equity: 512000, cumulative_pnl: 12000, pnl: 12000 },
    ],
    data_quality: {
      historical_unrealized: "unavailable",
      current_marks: "unavailable",
      completed_trades: "available",
      warnings: [],
    },
  };
}

describe("PortfolioAnalyticsPanel — realized equity curve", () => {
  it("renders <Line> (from recharts) without ReferenceError once a trade completes", () => {
    const html = renderToStaticMarkup(
      React.createElement(PortfolioAnalyticsPanel, {
        analytics: analyticsWithCompletedTrade(),
        positionsWithLtp: [],
        loading: false,
        error: null,
      })
    );
    expect(html).toContain("PORTFOLIO ANALYTICS");
    // The equity-curve section (which renders recharts <Line>) must render.
    expect(html).toContain("Realized equity curve");
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders the Phase 6.4 CAPITAL ALLOCATION & RISK section for open strategies", () => {
    const positions = [
      { positionId: "1", id: "pos-1", symbol: "NIFTY", type: "call", strike: 25000, expiry: "2026-08-18", action: "buy", qty: 1, lotSize: 65, entryPremium: 100, avgEntryPrice: 100, realizedPnl: 0, strategyName: "Bull Call Spread", executionId: "ex-bcs", status: "open", currentLtp: 120, rawLtp: 120, unrealizedPnl: 1300 },
      { positionId: "2", id: "pos-2", symbol: "NIFTY", type: "call", strike: 25100, expiry: "2026-08-18", action: "sell", qty: 1, lotSize: 65, entryPremium: 80, avgEntryPrice: 80, realizedPnl: 0, strategyName: "Bull Call Spread", executionId: "ex-bcs", status: "open", currentLtp: 95, rawLtp: 95, unrealizedPnl: -975 },
    ];
    const capital = {
      paper_starting_capital: { value: 500000, source: "CALCULATED", status: "available" },
      paper_available_cash: { value: 480000, source: "CALCULATED", status: "available" },
      broker_margin: { value: 37503, source: "BROKER_REPORTED", status: "available" },
      broker_available_funds: { value: null, source: "UNAVAILABLE", status: "unavailable" },
      strategies: [{ execution_id: "ex-bcs", strategy_tag: "Bull Call Spread", broker_margin: 37503, broker_margin_status: "available" }],
    };
    const html = renderToStaticMarkup(
      React.createElement(PortfolioAnalyticsPanel, {
        analytics: analyticsWithCompletedTrade(),
        positionsWithLtp: positions,
        capital,
        loading: false,
        error: null,
      })
    );
    // Allocation section, strategy row, broker aggregate and status badge.
    expect(html).toContain("ALLOCATION BY STRATEGY");
    expect(html).toContain("Bull Call Spread");
    expect(html).toContain("37,503"); // broker-reported aggregate, never summed per leg
    expect(html).toContain("1,300"); // analytical risk-basis estimated capital (BCS)
    expect(html).toContain("AVAILABLE"); // data-quality badge
  });

  it("renders the Phase 6.4 allocation empty state safely without positions/capital", () => {
    const html = renderToStaticMarkup(
      React.createElement(PortfolioAnalyticsPanel, {
        analytics: analyticsWithCompletedTrade(),
        positionsWithLtp: [],
        loading: false,
        error: null,
      })
    );
    expect(html).toContain("No open positions");
  });

  it("renders the empty curve state safely when no trade has completed", () => {
    const analytics = analyticsWithCompletedTrade();
    analytics.performance.total_completed_trades = 0;
    analytics.performance.winning_trades = 0;
    analytics.strategies = [];
    analytics.journal = [];
    analytics.equity_curve = [{ date: "2026-07-01", equity: 500000, cumulative_pnl: 0, pnl: 0 }];
    const html = renderToStaticMarkup(
      React.createElement(PortfolioAnalyticsPanel, {
        analytics,
        positionsWithLtp: [],
        loading: false,
        error: null,
      })
    );
    expect(html).toContain("No completed trades");
  });
});
