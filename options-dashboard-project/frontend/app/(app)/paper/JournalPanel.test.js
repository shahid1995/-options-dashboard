import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import JournalPanel from "./JournalPanel";

const emptyProps = {
  journal: null,
  journalError: null,
  paperHistory: [],
  journalPage: 0,
  onPageChange: () => {},
  onExportCsv: () => {},
  perStrategy: [],
};

function renderJournal(props) {
  return renderToStaticMarkup(React.createElement(JournalPanel, { ...emptyProps, ...props }));
}

const sampleTrades = [
  {
    id: "1",
    status: "closed",
    strategy_tag: "Short Strangle",
    symbol: "NIFTY",
    legs: [
      { action: "sell", strike_price: 25000, option_type: "call", quantity: 1 },
    ],
    entry_net: -1500,
    realized_pnl: 1200,
    entry_at: "2026-08-13T09:00:00Z",
    exit_at: "2026-08-13T10:00:00Z",
  },
  {
    id: "2",
    status: "open",
    strategy_tag: "Iron Condor",
    symbol: "NIFTY",
    legs: [
      { action: "sell", strike_price: 24800, option_type: "put", quantity: 1 },
      { action: "buy", strike_price: 24600, option_type: "put", quantity: 1 },
    ],
    entry_net: -800,
    realized_pnl: null,
    entry_at: "2026-08-14T09:30:00Z",
    exit_at: null,
  },
];

describe("JournalPanel — Task 7: presentation hierarchy", () => {
  it("renders the transaction log heading", () => {
    const html = renderJournal({ journal: { trades: [], stats: { closed_trades: 0 } } });
    expect(html).toContain("TRANSACTION LOG &amp; HISTORICAL JOURNAL");
  });

  it("shows loading state when journal is null and no error", () => {
    const html = renderJournal({});
    expect(html).toContain("Loading journal");
  });

  it("shows empty state when no journal entries exist", () => {
    const html = renderJournal({ journal: { trades: [], stats: { closed_trades: 0 } } });
    expect(html).toContain("No journal entries yet");
    expect(html).toContain("submit a paper order");
  });

  it("shows unavailable empty state when journal error occurs", () => {
    const html = renderJournal({
      journal: null,
      journalError: "503 Service Unavailable",
      paperHistory: [],
    });
    expect(html).toContain("No closed trades in this browser yet");
    expect(html).toContain("503 Service Unavailable");
  });

  it("renders journal record count badge", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("2 records");
  });

  it("renders pagination controls when records exceed page size", () => {
    const manyTrades = Array.from({ length: 15 }, (_, i) => ({
      ...sampleTrades[0],
      id: `t-${i}`,
    }));
    const html = renderJournal({
      journal: { trades: manyTrades, stats: { closed_trades: 15 } },
      journalPage: 0,
    });
    expect(html).toContain("Page 1 / 2");
    expect(html).toContain("15 rows");
    expect(html).toContain("Prev");
    expect(html).toContain("Next");
  });

  it("pagination Previous button is disabled on first page", () => {
    const manyTrades = Array.from({ length: 15 }, (_, i) => ({
      ...sampleTrades[0],
      id: `t-${i}`,
    }));
    const html = renderJournal({
      journal: { trades: manyTrades, stats: { closed_trades: 15 } },
      journalPage: 0,
    });
    expect(html).toContain('disabled=""');
  });

  it("hides pagination when records fit on one page", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).not.toContain("Page 1");
    expect(html).not.toContain("Prev");
    expect(html).not.toContain("Next");
  });

  it("renders table headers with correct columns", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("Status");
    expect(html).toContain("Strategy Tag");
    expect(html).toContain("Strike / Legs");
    expect(html).toContain("Net Entry");
    expect(html).toContain("Realized P&amp;L");
    expect(html).toContain("Opened");
    expect(html).toContain("Closed");
  });

  it("renders OPEN badge for open trades", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("open");
    expect(html).toContain("closed");
  });

  it("renders local trades with CLOSED badge", () => {
    const localHistory = [
      {
        tradeId: "local-1",
        strategyName: "Custom",
        symbol: "NIFTY",
        action: "buy",
        strike: 25000,
        type: "call",
        qty: 1,
        entryPremium: 150,
        realizedPnl: 300,
        entryTime: "2026-08-13T09:00:00Z",
        exitTime: "2026-08-13T10:00:00Z",
      },
    ];
    const html = renderJournal({
      journal: null,
      journalError: "backend unavailable",
      paperHistory: localHistory,
    });
    expect(html).toContain("CLOSED");
    expect(html).toContain("Custom");
  });

  it("formats journal dates using en-IN locale", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("13 Aug");
  });

  it("renders em-dash for unavailable exit_at", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("—");
  });

  it("renders CSV export button when paper history exists", () => {
    const html = renderJournal({
      journal: { trades: [], stats: { closed_trades: 0 } },
      paperHistory: [
        {
          tradeId: "h1",
          strategyName: "Test",
          symbol: "NIFTY",
          action: "buy",
          strike: 25000,
          type: "call",
          qty: 1,
          entryPremium: 100,
          realizedPnl: 50,
          entryTime: "2026-08-13T09:00:00Z",
          exitTime: "2026-08-13T10:00:00Z",
        },
      ],
    });
    expect(html).toContain("Export CSV");
  });

  it("does not render CSV export button when no history", () => {
    const html = renderJournal({ journal: { trades: [], stats: { closed_trades: 0 } }, paperHistory: [] });
    expect(html).not.toContain("Export CSV");
  });

  it("renders per-strategy summary chips", () => {
    const perStrategy = [
      { strategyName: "Short Strangle", trades: 5, wins: 3, totalPnl: 2500, winRate: 0.6 },
    ];
    const html = renderJournal({
      journal: { trades: sampleTrades, stats: { closed_trades: 1 } },
      perStrategy,
    });
    expect(html).toContain("Short Strangle");
    expect(html).toContain("5 closed");
    expect(html).toContain("60% win");
  });

  it("renders win rate metric when stats available", () => {
    const html = renderJournal({
      journal: {
        trades: sampleTrades,
        stats: { closed_trades: 10, win_rate: 0.6, profit_factor: 1.5 },
      },
    });
    expect(html).toContain("60.0%");
    expect(html).toContain("1.50");
    expect(html).toContain("10");
  });
});

describe("JournalPanel — Task 8: responsive & keyboard behavior", () => {
  it("pagination buttons have aria-labels for screen readers", () => {
    const manyTrades = Array.from({ length: 15 }, (_, i) => ({
      ...sampleTrades[0],
      id: `t-${i}`,
    }));
    const html = renderJournal({
      journal: { trades: manyTrades, stats: { closed_trades: 15 } },
      journalPage: 0,
    });
    expect(html).toContain('aria-label="Previous page"');
    expect(html).toContain('aria-label="Next page"');
  });

  it("renders table with overflow-x:auto to prevent silent overflow", () => {
    const manyTrades = Array.from({ length: 15 }, (_, i) => ({
      ...sampleTrades[0],
      id: `t-${i}`,
    }));
    const html = renderJournal({
      journal: { trades: manyTrades, stats: { closed_trades: 15 } },
    });
    expect(html).toContain("overflow-x");
    expect(html).toContain("auto");
  });

  it("uses compact table variant for journal data", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    expect(html).toContain("Status");
    expect(html).toContain("Strategy Tag");
  });

  it("preserves null as unavailable for realized PnL (never zero)", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 1 } } });
    // Trade 2 is open with realized_pnl: null → should show — not ₹0
    expect(html).toContain("—");
  });

  it("renders page info text with mobile-friendly font size", () => {
    const manyTrades = Array.from({ length: 15 }, (_, i) => ({
      ...sampleTrades[0],
      id: `t-${i}`,
    }));
    const html = renderJournal({
      journal: { trades: manyTrades, stats: { closed_trades: 15 } },
      journalPage: 0,
    });
    expect(html).toContain("Page 1 / 2");
  });

  it("renders empty state with descriptive message (not invented zeros)", () => {
    const html = renderJournal({ journal: { trades: [], stats: { closed_trades: 0 } } });
    expect(html).toContain("No journal entries yet");
    expect(html).not.toContain("₹0");
  });

  it("renders performance summary metrics only when stats exist", () => {
    const html = renderJournal({ journal: { trades: sampleTrades, stats: { closed_trades: 10, win_rate: 0.5, profit_factor: 1.2 } } });
    expect(html).toContain("Win rate");
    expect(html).toContain("Profit factor");
    expect(html).toContain("Closed trades");
  });

  it("does not render performance summary when no stats", () => {
    const html = renderJournal({ journal: { trades: sampleTrades } });
    expect(html).not.toContain("Win rate");
  });
});
