import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  OrderStatusBadge,
  OrderSideBadge,
  OrderOptionBadge,
  OrderTabs,
  OrderFilters,
  OrderDetails,
  OrderRow,
} from "./page";

// ---- Mock data ----

const MOCK_ORDER = {
  id: 1,
  client_order_id: "cli-abc-123",
  execution_id: "exec-1",
  position_id: 42,
  kind: "entry",
  symbol: "NIFTY",
  expiry: "2026-08-21",
  strike: 25000,
  option_type: "call",
  action: "buy",
  quantity: 2,
  lot_size: 65,
  status: "FILLED",
  filled_quantity: 2,
  fill_price: 150.0,
  price_source: "market",
  realized_pnl: null,
  rejected_reason: null,
  created_at: "2026-08-18T10:00:00Z",
  updated_at: "2026-08-18T10:00:01Z",
  strategy_tag: "Bull Call Spread",
  strategy_execution_id: "exec-1",
};

const MOCK_EXIT_ORDER = {
  ...MOCK_ORDER,
  id: 2,
  client_order_id: "cli-exit-456",
  kind: "exit",
  action: "sell",
  realized_pnl: 500.0,
};

const MOCK_REJECTED_ORDER = {
  ...MOCK_ORDER,
  id: 3,
  client_order_id: "cli-rej-789",
  status: "REJECTED",
  rejected_reason: "Market closed",
};

const MOCK_PARTIAL_ORDER = {
  ...MOCK_ORDER,
  id: 4,
  client_order_id: "cli-partial-012",
  status: "PARTIALLY_FILLED",
  quantity: 10,
  filled_quantity: 4,
};

// ---- Helper to render and get text content ----

function html(renderFn) {
  return renderToStaticMarkup(renderFn());
}

// ---- OrderStatusBadge tests ----

describe("OrderStatusBadge", () => {
  it("renders FILLED", () => {
    expect(html(() => <OrderStatusBadge status="FILLED" />)).toContain("FILLED");
  });

  it("renders PENDING", () => {
    expect(html(() => <OrderStatusBadge status="PENDING" />)).toContain("PENDING");
  });

  it("renders REJECTED", () => {
    expect(html(() => <OrderStatusBadge status="REJECTED" />)).toContain("REJECTED");
  });

  it("renders PARTIALLY_FILLED as PARTIAL", () => {
    expect(html(() => <OrderStatusBadge status="PARTIALLY_FILLED" />)).toContain("PARTIAL");
  });

  it("renders CANCELLED", () => {
    expect(html(() => <OrderStatusBadge status="CANCELLED" />)).toContain("CANCELLED");
  });

  it("renders FAILED", () => {
    expect(html(() => <OrderStatusBadge status="FAILED" />)).toContain("FAILED");
  });

  it("renders unknown status as-is", () => {
    expect(html(() => <OrderStatusBadge status="UNKNOWN" />)).toContain("UNKNOWN");
  });
});

// ---- OrderSideBadge tests ----

describe("OrderSideBadge", () => {
  it("renders BUY", () => {
    expect(html(() => <OrderSideBadge action="buy" />)).toContain("BUY");
  });

  it("renders SELL", () => {
    expect(html(() => <OrderSideBadge action="sell" />)).toContain("SELL");
  });

  it("renders dash for null", () => {
    expect(html(() => <OrderSideBadge action={null} />)).toContain("\u2014");
  });
});

// ---- OrderOptionBadge tests ----

describe("OrderOptionBadge", () => {
  it("renders CE for call", () => {
    expect(html(() => <OrderOptionBadge type="call" />)).toContain("CE");
  });

  it("renders PE for put", () => {
    expect(html(() => <OrderOptionBadge type="put" />)).toContain("PE");
  });
});

// ---- OrderTabs tests ----

describe("OrderTabs", () => {
  const counts = { total: 10, open: 2, filled: 5, rejected: 1, cancelled: 2 };

  it("renders all tab labels", () => {
    const h = html(() => <OrderTabs activeTab="all" onTabChange={() => {}} counts={counts} />);
    expect(h).toContain("All Orders");
    expect(h).toContain("Open");
    expect(h).toContain("Executed");
    expect(h).toContain("Rejected");
    expect(h).toContain("Cancelled");
  });

  it("renders counts", () => {
    const h = html(() => <OrderTabs activeTab="all" onTabChange={() => {}} counts={counts} />);
    expect(h).toContain("10");
    expect(h).toContain("2");
    expect(h).toContain("5");
    expect(h).toContain("1");
  });
});

// ---- OrderFilters tests ----

describe("OrderFilters", () => {
  const emptyFilters = { symbol: "", action: "", option_type: "", kind: "" };

  it("renders filter label", () => {
    expect(html(() => <OrderFilters filters={emptyFilters} onFilterChange={() => {}} />)).toContain("FILTERS");
  });

  it("renders All Symbols option", () => {
    expect(html(() => <OrderFilters filters={emptyFilters} onFilterChange={() => {}} />)).toContain("All Symbols");
  });

  it("renders All Sides option", () => {
    expect(html(() => <OrderFilters filters={emptyFilters} onFilterChange={() => {}} />)).toContain("All Sides");
  });

  it("shows clear button when filters active", () => {
    const filters = { symbol: "NIFTY", action: "", option_type: "", kind: "" };
    expect(html(() => <OrderFilters filters={filters} onFilterChange={() => {}} />)).toContain("Clear");
  });

  it("hides clear button when no filters", () => {
    expect(html(() => <OrderFilters filters={emptyFilters} onFilterChange={() => {}} />)).not.toContain("Clear");
  });
});

// ---- OrderDetails tests ----

describe("OrderDetails", () => {
  it("renders all section titles", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).toContain("ORDER");
    expect(h).toContain("INSTRUMENT");
    expect(h).toContain("REQUEST");
    expect(h).toContain("EXECUTION");
    expect(h).toContain("ATTRIBUTION");
    expect(h).toContain("BROKER");
  });

  it("renders strategy tag", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("Bull Call Spread");
  });

  it("renders execution mode as PAPER", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("PAPER");
  });

  it("renders broker as Paper", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("Paper");
  });

  it("renders N/A for broker order ID", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).toContain("N/A");
  });

  it("renders realized P&L for exit orders", () => {
    expect(html(() => <OrderDetails order={MOCK_EXIT_ORDER} />)).toContain("500");
  });

  it("renders rejection reason", () => {
    expect(html(() => <OrderDetails order={MOCK_REJECTED_ORDER} />)).toContain("Market closed");
  });

  it("renders partial execution quantities", () => {
    const h = html(() => <OrderDetails order={MOCK_PARTIAL_ORDER} />);
    expect(h).toContain("4 lots"); // filled
    expect(h).toContain("6 lots"); // remaining
    expect(h).toContain("10 lots"); // requested
  });

  it("renders ENTRY kind", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("ENTRY");
  });

  it("renders EXIT kind for exit orders", () => {
    expect(html(() => <OrderDetails order={MOCK_EXIT_ORDER} />)).toContain("EXIT");
  });

  it("renders Custom for null strategy tag", () => {
    const orderNoTag = { ...MOCK_ORDER, strategy_tag: null };
    expect(html(() => <OrderDetails order={orderNoTag} />)).toContain("Custom");
  });

  it("renders position ID", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("42");
  });

  it("excludes Position detail when position_id is null", () => {
    const orderWithPos = { ...MOCK_ORDER, position_id: 42 };
    const orderNoPos = { ...MOCK_ORDER, position_id: null };
    const hWith = html(() => <OrderDetails order={orderWithPos} />);
    const hWithout = html(() => <OrderDetails order={orderNoPos} />);
    expect(hWithout.length).toBeLessThan(hWith.length);
  });

  it("renders client order ID", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("cli-abc-123");
  });

  it("renders order ID", () => {
    expect(html(() => <OrderDetails order={MOCK_ORDER} />)).toContain("1");
  });
});

// ---- OrderRow tests ----

describe("OrderRow", () => {
  it("renders order data in table row", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("NIFTY");
    expect(h).toContain("BUY");
    expect(h).toContain("CE");
  });

  it("renders expanded details", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={true} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("ORDER");
    expect(h).toContain("INSTRUMENT");
  });

  it("does not render details when collapsed", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).not.toContain("ORDER");
    expect(h).not.toContain("INSTRUMENT");
  });

  it("renders expiry date", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("Aug");
  });

  it("renders strike price", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("25,000");
  });

  it("renders filled/total quantity", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("2/2");
  });

  it("renders fill price", () => {
    const h = html(() => (
      <table>
        <tbody>
          <OrderRow order={MOCK_ORDER} isExpanded={false} onToggle={() => {}} />
        </tbody>
      </table>
    ));
    expect(h).toContain("150");
  });
});

// ---- Broker neutrality ----

describe("Broker neutrality", () => {
  it("no Upstox-specific fields in OrderDetails output", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).not.toContain("instrument_key");
    expect(h).not.toContain("transaction_type");
    expect(h).not.toContain("upstox");
  });

  it("shows Paper as broker, not Upstox", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).toContain("Paper");
    expect(h).not.toContain("Upstox");
  });
});

// ---- Execution mode safety ----

describe("Execution mode", () => {
  it("all orders show PAPER execution mode", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).toContain("PAPER");
  });

  it("no LIVE execution mode shown", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).not.toContain("LIVE");
  });
});

// ---- Quantity safety ----

describe("Quantity representation", () => {
  it("shows remaining quantity for partial fills", () => {
    const h = html(() => <OrderDetails order={MOCK_PARTIAL_ORDER} />);
    // 10 - 4 = 6 remaining
    expect(h).toContain("6 lots");
  });

  it("shows zero remaining for full fills", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    // 2 - 2 = 0 remaining
    expect(h).toContain("0 lots");
  });

  it("original quantity is distinct from filled quantity", () => {
    const h = html(() => <OrderDetails order={MOCK_PARTIAL_ORDER} />);
    expect(h).toContain("10 lots"); // requested
    expect(h).toContain("4 lots"); // filled
    expect(h).toContain("6 lots"); // remaining
  });
});

// ---- Null/missing fields ----

describe("Null/missing fields", () => {
  it("renders N/A for missing fill price", () => {
    const orderNoFill = { ...MOCK_ORDER, fill_price: null };
    const h = html(() => <OrderDetails order={orderNoFill} />);
    expect(h).toContain("\u2014");
  });

  it("renders N/A for missing execution_id", () => {
    const orderNoExec = { ...MOCK_ORDER, execution_id: null };
    const h = html(() => <OrderDetails order={orderNoExec} />);
    expect(h).toContain("\u2014");
  });

  it("does not show realized P&L when null", () => {
    const h = html(() => <OrderDetails order={MOCK_ORDER} />);
    expect(h).not.toContain("Realized P&L");
  });
});
