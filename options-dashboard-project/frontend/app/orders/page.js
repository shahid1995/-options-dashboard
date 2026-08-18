"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { getPaperOrdersFiltered } from "@/lib/api";
import { C, fmtIN, SessionExpired, useIsMobile } from "@/lib/ui";
import { isAuthError } from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";

// ---- Constants ----

const STATUS_TABS = [
  { key: "all", label: "All Orders" },
  { key: "open", label: "Open" },
  { key: "filled", label: "Executed" },
  { key: "rejected", label: "Rejected" },
  { key: "cancelled", label: "Cancelled" },
];

const STATUS_COLORS = {
  FILLED: C.green,
  PENDING: C.gold,
  PARTIALLY_FILLED: "#5B9BD5",
  CANCELLED: C.muted,
  REJECTED: C.red,
  FAILED: C.red,
  EXPIRED: C.faint,
};

const STATUS_DISPLAY = {
  FILLED: "FILLED",
  PENDING: "PENDING",
  PARTIALLY_FILLED: "PARTIAL",
  CANCELLED: "CANCELLED",
  REJECTED: "REJECTED",
  FAILED: "FAILED",
  EXPIRED: "EXPIRED",
};

const SYMBOL_OPTIONS = ["", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "SENSEX50"];

// ---- Helpers ----

function formatTime(iso) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatExpiry(iso) {
  if (!iso) return "\u2014";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

// ---- Small reusable components ----

export function OrderStatusBadge({ status }) {
  const color = STATUS_COLORS[status] || C.faint;
  const display = STATUS_DISPLAY[status] || status;
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: 0.5,
        padding: "2px 6px",
        borderRadius: 3,
        background: `${color}18`,
        color,
        border: `1px solid ${color}30`,
      }}
    >
      {display}
    </span>
  );
}

export function OrderSideBadge({ action }) {
  const isBuy = action === "buy";
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 0.5,
        color: isBuy ? C.green : C.red,
      }}
    >
      {action?.toUpperCase() || "\u2014"}
    </span>
  );
}

export function OrderOptionBadge({ type }) {
  const isCall = type === "call";
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: 0.5,
        padding: "1px 5px",
        borderRadius: 3,
        background: isCall ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)",
        color: isCall ? C.green : C.red,
      }}
    >
      {isCall ? "CE" : "PE"}
    </span>
  );
}

// ---- Tabs ----

export function OrderTabs({ activeTab, onTabChange, counts }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 6,
        marginBottom: 16,
        flexWrap: "wrap",
        borderBottom: `1px solid ${C.border}`,
        paddingBottom: 8,
      }}
    >
      {STATUS_TABS.map((tab) => {
        const count =
          tab.key === "all" ? counts.total
          : tab.key === "open" ? counts.open
          : tab.key === "filled" ? counts.filled
          : tab.key === "rejected" ? counts.rejected
          : tab.key === "cancelled" ? counts.cancelled
          : 0;
        const isActive = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            style={{
              fontSize: 12,
              padding: "6px 12px",
              borderRadius: 6,
              border: `1px solid ${isActive ? C.gold : C.border}`,
              background: isActive ? "rgba(201,161,90,0.1)" : "transparent",
              color: isActive ? C.gold : C.muted,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontWeight: isActive ? 600 : 400,
            }}
          >
            {tab.label}
            <span
              style={{
                fontSize: 10,
                padding: "1px 5px",
                borderRadius: 3,
                background: isActive ? "rgba(201,161,90,0.2)" : "rgba(136,146,166,0.15)",
                color: isActive ? C.gold : C.faint,
              }}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---- Filters ----

export function OrderFilters({ filters, onFilterChange, isMobile }) {
  const selectStyle = {
    fontSize: 11,
    padding: "4px 8px",
    borderRadius: 4,
    border: `1px solid ${C.border}`,
    background: C.surface,
    color: C.text,
    cursor: "pointer",
    minWidth: isMobile ? 80 : 100,
  };

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        marginBottom: 12,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span style={{ fontSize: 10, color: C.faint, letterSpacing: 0.5 }}>FILTERS</span>
      <select
        value={filters.symbol}
        onChange={(e) => onFilterChange({ ...filters, symbol: e.target.value })}
        style={selectStyle}
      >
        {SYMBOL_OPTIONS.map((s) => (
          <option key={s} value={s}>{s || "All Symbols"}</option>
        ))}
      </select>
      <select
        value={filters.action}
        onChange={(e) => onFilterChange({ ...filters, action: e.target.value })}
        style={selectStyle}
      >
        <option value="">All Sides</option>
        <option value="buy">BUY</option>
        <option value="sell">SELL</option>
      </select>
      <select
        value={filters.option_type}
        onChange={(e) => onFilterChange({ ...filters, option_type: e.target.value })}
        style={selectStyle}
      >
        <option value="">All Types</option>
        <option value="call">CE (Call)</option>
        <option value="put">PE (Put)</option>
      </select>
      <select
        value={filters.kind}
        onChange={(e) => onFilterChange({ ...filters, kind: e.target.value })}
        style={selectStyle}
      >
        <option value="">Entry + Exit</option>
        <option value="entry">Entry</option>
        <option value="exit">Exit</option>
      </select>
      {(filters.symbol || filters.action || filters.option_type || filters.kind) && (
        <button
          onClick={() => onFilterChange({ symbol: "", action: "", option_type: "", kind: "" })}
          style={{
            fontSize: 10,
            padding: "4px 8px",
            borderRadius: 4,
            border: `1px solid ${C.border}`,
            background: "transparent",
            color: C.muted,
            cursor: "pointer",
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}

// ---- Detail sections ----

function DetailSection({ title, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: C.gold,
          letterSpacing: 1,
          marginBottom: 6,
          paddingBottom: 4,
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        {title}
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}

function DetailItem({ label, value, color, mono }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 2 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 11.5,
          fontWeight: 500,
          color: color || C.text,
          fontFamily: mono ? "monospace" : "inherit",
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ---- Order details (structured) ----

export function OrderDetails({ order }) {
  const requestedQty = order.quantity || 0;
  const filledQty = order.filled_quantity || 0;
  const remainingQty = Math.max(0, requestedQty - filledQty);

  return (
    <div style={{ fontSize: 12, maxWidth: 900 }}>
      {/* Section A: Order */}
      <DetailSection title="ORDER">
        <DetailItem label="Order ID" value={order.id || "\u2014"} mono />
        <DetailItem label="Client Order ID" value={order.client_order_id || "\u2014"} mono />
        <DetailItem label="Execution Mode" value="PAPER" color={C.gold} />
        <DetailItem
          label="Status"
          value={<OrderStatusBadge status={order.status} />}
        />
        <DetailItem label="Created" value={formatTime(order.created_at)} />
        <DetailItem label="Updated" value={formatTime(order.updated_at)} />
      </DetailSection>

      {/* Section B: Instrument */}
      <DetailSection title="INSTRUMENT">
        <DetailItem label="Symbol" value={order.symbol || "\u2014"} />
        <DetailItem label="Expiry" value={formatExpiry(order.expiry)} />
        <DetailItem label="Strike" value={order.strike ? fmtIN(order.strike) : "\u2014"} color={C.gold} />
        <DetailItem label="Type" value={<OrderOptionBadge type={order.option_type} />} />
      </DetailSection>

      {/* Section C: Request */}
      <DetailSection title="REQUEST">
        <DetailItem label="Side" value={<OrderSideBadge action={order.action} />} />
        <DetailItem label="Kind" value={order.kind === "entry" ? "ENTRY" : "EXIT"} />
        <DetailItem label="Lot Size" value={order.lot_size || "\u2014"} />
        <DetailItem label="Requested Qty" value={`${requestedQty} lots`} />
        <DetailItem label="Price Source" value={order.price_source || "market"} />
      </DetailSection>

      {/* Section D: Execution */}
      <DetailSection title="EXECUTION">
        <DetailItem label="Filled Qty" value={`${filledQty} lots`} />
        <DetailItem
          label="Remaining Qty"
          value={`${remainingQty} lots`}
          color={remainingQty > 0 ? C.gold : C.muted}
        />
        <DetailItem
          label="Avg Fill Price"
          value={order.fill_price ? fmtIN(order.fill_price, 2) : "\u2014"}
          color={order.fill_price ? C.text : C.muted}
        />
        {order.realized_pnl != null && (
          <DetailItem
            label="Realized P&L"
            value={`${order.realized_pnl >= 0 ? "+" : ""}${fmtIN(order.realized_pnl, 2)}`}
            color={order.realized_pnl >= 0 ? C.green : C.red}
          />
        )}
      </DetailSection>

      {/* Section E: Attribution */}
      <DetailSection title="ATTRIBUTION">
        <DetailItem
          label="Strategy"
          value={order.strategy_tag || "Custom"}
          color={order.strategy_tag && order.strategy_tag !== "Custom" ? C.gold : C.muted}
        />
        <DetailItem
          label="Strategy Execution"
          value={order.execution_id || "\u2014"}
          mono
        />
        {order.position_id && (
          <DetailItem label="Position" value={String(order.position_id)} mono />
        )}
        <DetailItem
          label="Entry / Exit"
          value={order.kind === "entry" ? "ENTRY" : "EXIT"}
          color={order.kind === "exit" ? C.gold : C.muted}
        />
      </DetailSection>

      {/* Section F: Broker */}
      <DetailSection title="BROKER">
        <DetailItem label="Broker" value="Paper" color={C.gold} />
        <DetailItem label="Broker Order ID" value="N/A" color={C.faint} />
      </DetailSection>

      {/* Rejection reason (if any) */}
      {order.rejected_reason && (
        <div
          style={{
            marginTop: 8,
            padding: "6px 10px",
            borderRadius: 4,
            background: "rgba(225,82,82,0.08)",
            border: `1px solid rgba(225,82,82,0.2)`,
            fontSize: 11,
            color: C.red,
          }}
        >
          <span style={{ fontWeight: 600 }}>Rejection Reason: </span>
          {order.rejected_reason}
        </div>
      )}
    </div>
  );
}

// ---- Order row ----

export function OrderRow({ order, isExpanded, onToggle, isMobile }) {
  return (
    <>
      <tr
        onClick={onToggle}
        data-testid="order-row"
        style={{
          borderBottom: `1px solid ${C.border}`,
          cursor: "pointer",
          background: isExpanded ? "rgba(201,161,90,0.04)" : "transparent",
          transition: "background 0.15s",
        }}
      >
        <td style={cellStyle(isMobile)}>
          <OrderStatusBadge status={order.status} />
        </td>
        <td style={cellStyle(isMobile)}>
          <OrderSideBadge action={order.action} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontWeight: 600, fontSize: 12 }}>{order.symbol || "\u2014"}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>{formatExpiry(order.expiry)}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, color: C.gold }}>
            {order.strike ? fmtIN(order.strike) : "\u2014"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <OrderOptionBadge type={order.option_type} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>
            {order.filled_quantity || 0}/{order.quantity || 0}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>
            {order.fill_price ? fmtIN(order.fill_price, 2) : "\u2014"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 11, color: C.muted }}>
            {formatTime(order.created_at)}
          </span>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td
            colSpan={isMobile ? 5 : 9}
            style={{
              padding: "12px 16px",
              background: "rgba(201,161,90,0.03)",
              borderBottom: `1px solid ${C.border}`,
            }}
          >
            <OrderDetails order={order} />
          </td>
        </tr>
      )}
    </>
  );
}

// ---- Empty state ----

function EmptyState({ message }) {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "48px 16px",
        color: C.muted,
        fontSize: 13,
      }}
      data-testid="empty-state"
    >
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>{"\uD83D\uDCCB"}</div>
      <div>{message}</div>
    </div>
  );
}

// ---- Error state ----

function ErrorState({ message, onRetry }) {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "48px 16px",
        color: C.red,
        fontSize: 13,
      }}
      data-testid="error-state"
    >
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.6 }}>{"\u26A0\uFE0F"}</div>
      <div style={{ marginBottom: 12 }}>{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            fontSize: 12,
            padding: "6px 14px",
            borderRadius: 6,
            border: `1px solid ${C.border}`,
            background: C.surface,
            color: C.gold,
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ---- Cell style ----

function cellStyle(isMobile) {
  return {
    padding: isMobile ? "6px 8px" : "8px 12px",
    fontSize: 12,
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  };
}

// ---- Main page ----

export default function OrdersPage() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);
  const [orders, setOrders] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("all");
  const [expandedRow, setExpandedRow] = useState(null);
  const [filters, setFilters] = useState({ symbol: "", action: "", option_type: "", kind: "" });
  const isMobile = useIsMobile();

  const fetchOrders = useCallback(() => {
    setLoading(true);
    setError(null);

    // Map tab to status filter
    let statusFilter = null;
    if (activeTab === "open") statusFilter = "PENDING";
    else if (activeTab === "filled") statusFilter = "FILLED";
    else if (activeTab === "rejected") statusFilter = "REJECTED";
    else if (activeTab === "cancelled") statusFilter = "CANCELLED";

    const params = {};
    if (statusFilter) params.status = statusFilter;
    if (filters.symbol) params.symbol = filters.symbol;
    if (filters.action) params.action = filters.action;
    if (filters.option_type) params.option_type = filters.option_type;
    if (filters.kind) params.kind = filters.kind;

    getPaperOrdersFiltered(params)
      .then((data) => {
        setOrders(data);
        setLoading(false);
      })
      .catch((e) => {
        if (isAuthError(e)) setSessionExpired(true);
        else setError(e.message);
        setLoading(false);
      });
  }, [activeTab, filters]);

  useEffect(() => {
    captureSessionFromUrl();
    getStatus()
      .then((s) => setLoggedIn(s.logged_in))
      .catch((e) => {
        setError(e.message);
        setLoggedIn(false);
      });
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    fetchOrders();
  }, [loggedIn, fetchOrders]);

  // Client-side counts (from all orders, fetched once)
  const [allOrders, setAllOrders] = useState(null);
  useEffect(() => {
    if (!loggedIn) return;
    getPaperOrdersFiltered({})
      .then((data) => setAllOrders(data))
      .catch(() => {});
  }, [loggedIn]);

  const counts = useMemo(() => {
    const src = allOrders || orders || [];
    if (!src.length && !allOrders) return { total: 0, open: 0, filled: 0, rejected: 0, cancelled: 0 };
    const pool = allOrders || src;
    return {
      total: pool.length,
      open: pool.filter((o) => o.status === "PENDING" || o.status === "PARTIALLY_FILLED").length,
      filled: pool.filter((o) => o.status === "FILLED" || o.status === "PARTIALLY_FILLED").length,
      rejected: pool.filter((o) => o.status === "REJECTED" || o.status === "FAILED").length,
      cancelled: pool.filter((o) => o.status === "CANCELLED" || o.status === "EXPIRED").length,
    };
  }, [orders, allOrders]);

  if (loggedIn === null) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
        Checking login\u2026
      </div>
    );
  }
  if (sessionExpired) return <SessionExpired />;

  return (
    <div style={{ maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Orders
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Paper execution \u2014 no real broker orders
        </p>
      </div>

      {/* Tabs */}
      <OrderTabs activeTab={activeTab} onTabChange={setActiveTab} counts={counts} />

      {/* Filters */}
      <OrderFilters filters={filters} onFilterChange={setFilters} isMobile={isMobile} />

      {/* Content */}
      {loading ? (
        <div
          style={{ textAlign: "center", padding: 48, color: C.muted, fontSize: 13 }}
          data-testid="loading-state"
        >
          Loading orders\u2026
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={fetchOrders} />
      ) : !orders || orders.length === 0 ? (
        <EmptyState
          message={
            activeTab === "all" && !filters.symbol && !filters.action
              ? "No orders yet. Execute a strategy to see orders here."
              : "No orders match the selected filters."
          }
        />
      ) : (
        <div style={{ overflowX: "auto" }} data-testid="orders-table">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr
                style={{
                  color: C.faint,
                  fontSize: 10,
                  letterSpacing: 0.5,
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>STATUS</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>SIDE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>SYMBOL</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>EXPIRY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>STRIKE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>TYPE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>QTY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>PRICE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>TIME</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order, i) => (
                <OrderRow
                  key={order.client_order_id || order.id || i}
                  order={order}
                  isExpanded={expandedRow === (order.client_order_id || order.id)}
                  onToggle={() =>
                    setExpandedRow(
                      expandedRow === (order.client_order_id || order.id)
                        ? null
                        : order.client_order_id || order.id
                    )
                  }
                  isMobile={isMobile}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
