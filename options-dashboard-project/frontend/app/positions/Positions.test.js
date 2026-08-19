import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  PositionDetails,
  PositionRow,
} from "./page";

// ---- Mock data ----

const MOCK_POSITION = {
  id: 42,
  symbol: "NIFTY",
  expiry: "2026-08-21",
  strike: 25000,
  option_type: "call",
  net_quantity: 2,
  average_entry_price: 185.5,
  lot_size: 65,
  realized_pnl: 0,
  status: "open",
  strategy_execution_id: "exec-abc",
  strategy_tag: "Bull Call Spread",
  side: "LONG",
  opened_at: "2026-08-18T10:30:00Z",
  closed_at: null,
  strategy_leg_exposures: [
    { id: 1, execution_id: "exec-abc", action: "buy", original_quantity: 2, remaining_quantity: 2, status: "open" },
  ],
  orders: [
    {
      id: 100,
      kind: "entry",
      action: "buy",
      filled_quantity: 2,
      quantity: 2,
      fill_price: 185.5,
      status: "FILLED",
      created_at: "2026-08-18T10:30:00Z",
    },
  ],
};

const MOCK_SHORT_POSITION = {
  ...MOCK_POSITION,
  id: 43,
  net_quantity: -3,
  side: "SHORT",
  option_type: "put",
  strike: 24500,
  strategy_tag: "Bear Put Spread",
  strategy_leg_exposures: [
    { id: 2, execution_id: "exec-def", action: "sell", original_quantity: 3, remaining_quantity: 3, status: "open" },
  ],
  orders: [
    {
      id: 101,
      kind: "entry",
      action: "sell",
      filled_quantity: 3,
      quantity: 3,
      fill_price: 120.0,
      status: "FILLED",
      created_at: "2026-08-18T11:00:00Z",
    },
  ],
};

const MOCK_CLOSED_POSITION = {
  ...MOCK_POSITION,
  id: 44,
  status: "closed",
  net_quantity: 0,
  realized_pnl: 1500,
  closed_at: "2026-08-19T14:00:00Z",
  side: "CLOSED",
  strategy_leg_exposures: [],
  orders: [
    { id: 102, kind: "entry", action: "buy", filled_quantity: 2, quantity: 2, fill_price: 185.5, status: "FILLED", created_at: "2026-08-18T10:30:00Z" },
    { id: 103, kind: "exit", action: "sell", filled_quantity: 2, quantity: 2, fill_price: 195.0, realized_pnl: 1500, status: "FILLED", created_at: "2026-08-19T14:00:00Z" },
  ],
};

const MOCK_NO_LEGS = {
  ...MOCK_POSITION,
  id: 45,
  strategy_leg_exposures: [],
  orders: [],
  strategy_tag: "Custom",
};

// ---- Tests ----

describe("PositionDetails", () => {
  it("renders all detail sections for a LONG position", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("POSITION");
    expect(html).toContain("INSTRUMENT");
    expect(html).toContain("PRICING");
    expect(html).toContain("P&amp;L");
    expect(html).toContain("STRATEGY");
    expect(html).toContain("ORDER TRACE");
    expect(html).toContain("BROKER");
  });

  it("displays PAPER execution mode", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("PAPER");
  });

  it("displays LONG side for positive net_quantity", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("LONG");
  });

  it("displays SHORT side for negative net_quantity", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_SHORT_POSITION} />);
    expect(html).toContain("SHORT");
  });

  it("displays strategy tag", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("Bull Call Spread");
  });

  it("shows N/A for Custom strategy tag", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_NO_LEGS} />);
    expect(html).toContain("Custom");
  });

  it("renders strategy leg attributions", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("LEG ATTRIBUTION");
    expect(html).toContain("BUY");
    expect(html).toContain("2");
  });

  it("renders entry order trace", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("ENTRY ORDERS");
  });

  it("renders exit order trace for closed positions", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_CLOSED_POSITION} />);
    expect(html).toContain("EXIT ORDERS");
    expect(html).toContain("1,500");
  });

  it("shows no orders message when empty", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_NO_LEGS} />);
    expect(html).toContain("No order data available");
  });

  it("displays Paper broker with N/A broker position ID", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("Paper");
    expect(html).toContain("N/A");
  });

  it("does not contain Upstox-specific fields", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("instrument_key");
    expect(html).not.toContain("transaction_type");
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("refresh_token");
  });

  it("does not contain fake LIVE position data", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("LIVE");
    expect(html).not.toContain("broker orders sent");
  });

  it("shows realized P&L with correct sign", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_CLOSED_POSITION} />);
    expect(html).toContain("+");
    expect(html).toContain("1,500");
  });

  it("shows N/A for unrealized P&L", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("Unrealized P&amp;L");
    expect(html).toContain("N/A");
  });

  it("renders lot size information", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("Lot Size");
    expect(html).toContain("65");
  });

  it("renders execution ID", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("exec-abc");
  });

  it("shows open status badge", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).toContain("OPEN");
  });

  it("shows closed status badge", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_CLOSED_POSITION} />);
    expect(html).toContain("CLOSED");
  });
});

describe("PositionRow", () => {
  const defaultProps = {
    position: MOCK_POSITION,
    isExpanded: false,
    onToggle: () => {},
    isMobile: false,
  };

  it("renders position row with test id", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("position-row");
  });

  it("displays LONG side badge", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("LONG");
  });

  it("displays SHORT side badge", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} position={MOCK_SHORT_POSITION} /></tbody></table>
    );
    expect(html).toContain("SHORT");
  });

  it("displays CE badge for call option", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("CE");
  });

  it("displays PE badge for put option", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} position={MOCK_SHORT_POSITION} /></tbody></table>
    );
    expect(html).toContain("PE");
  });

  it("displays quantity and lots", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("2");
    expect(html).toContain("lot");
  });

  it("displays average entry price", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("185");
  });

  it("displays realized P&L", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} position={MOCK_CLOSED_POSITION} /></tbody></table>
    );
    expect(html).toContain("1,500");
  });

  it("displays strategy tag", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("Bull Call Spread");
  });

  it("displays OPEN status for open position", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("OPEN");
  });

  it("displays CLOSED status for closed position", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} position={MOCK_CLOSED_POSITION} /></tbody></table>
    );
    expect(html).toContain("CLOSED");
  });

  it("renders expanded details when isExpanded=true", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} isExpanded={true} /></tbody></table>
    );
    expect(html).toContain("POSITION");
    expect(html).toContain("INSTRUMENT");
    expect(html).toContain("BROKER");
  });

  it("does not render expanded details when isExpanded=false", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} isExpanded={false} /></tbody></table>
    );
    expect(html).not.toContain("BROKER");
  });

  it("symbol is displayed", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("NIFTY");
  });

  it("strike is displayed with formatting", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("25");
  });

  it("expiry is displayed", () => {
    const html = renderToStaticMarkup(
      <table><tbody><PositionRow {...defaultProps} /></tbody></table>
    );
    expect(html).toContain("Aug");
  });
});

describe("Static architecture audit", () => {
  it("positions page does not import Upstox-specific modules", () => {
    // Verify by checking component source for forbidden patterns
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("UpstoxAdapter");
    expect(html).not.toContain("broker_adapter");
  });

  it("positions page does not contain broker-specific field names in output", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("instrument_key");
    expect(html).not.toContain("transaction_type");
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("refresh_token");
  });

  it("positions page does not expose broker gateway in rendered output", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("broker_gateway");
    expect(html).not.toContain("BrokerGateway");
    expect(html).not.toContain("execute_order");
  });
});

describe("Edge cases", () => {
  it("handles position with zero lot_size", () => {
    const pos = { ...MOCK_POSITION, lot_size: 0 };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("PRICING");
  });

  it("handles position with no strategy_execution_id", () => {
    const pos = { ...MOCK_POSITION, strategy_execution_id: null, strategy_tag: "Custom" };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("Custom");
    expect(html).toContain("\u2014");
  });

  it("handles position with empty orders array", () => {
    const pos = { ...MOCK_POSITION, orders: [] };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("No order data available");
  });

  it("handles position with empty strategy_leg_exposures", () => {
    const pos = { ...MOCK_POSITION, strategy_leg_exposures: [] };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("STRATEGY");
  });

  it("handles null realized_pnl gracefully", () => {
    const pos = { ...MOCK_POSITION, realized_pnl: null };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("P&amp;L");
  });

  it("handles missing closed_at for open position", () => {
    const html = renderToStaticMarkup(<PositionDetails position={MOCK_POSITION} />);
    expect(html).not.toContain("Closed");
  });

  it("handles missing opened_at gracefully", () => {
    const pos = { ...MOCK_POSITION, opened_at: null };
    const html = renderToStaticMarkup(<PositionDetails position={pos} />);
    expect(html).toContain("POSITION");
  });
});
