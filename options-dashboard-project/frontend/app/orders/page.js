"use client";
import { useEffect, useState, useMemo } from "react";
import { getPaperOrders } from "@/lib/api";
import { C, fmtIN, SessionExpired, useIsMobile } from "@/lib/ui";
import { isAuthError } from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";

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

function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatExpiry(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/* ---------- Status badge ---------- */
function StatusBadge({ status }) {
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

/* ---------- Side badge ---------- */
function SideBadge({ action }) {
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
      {action?.toUpperCase() || "—"}
    </span>
  );
}

/* ---------- Option type badge ---------- */
function OptionBadge({ type }) {
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

/* ---------- Order row ---------- */
function OrderRow({ order, isExpanded, onToggle, isMobile }) {
  return (
    <>
      <tr
        onClick={onToggle}
        style={{
          borderBottom: `1px solid ${C.border}`,
          cursor: "pointer",
          background: isExpanded ? "rgba(201,161,90,0.04)" : "transparent",
          transition: "background 0.15s",
        }}
      >
        <td style={cellStyle(isMobile)}>
          <StatusBadge status={order.status} />
        </td>
        <td style={cellStyle(isMobile)}>
          <SideBadge action={order.action} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontWeight: 600, fontSize: 12 }}>{order.symbol || "—"}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>{formatExpiry(order.expiry)}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, color: C.gold }}>
            {order.strike ? fmtIN(order.strike) : "—"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <OptionBadge type={order.option_type} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>
            {order.filled_quantity || order.quantity || 0}
            {order.quantity ? `/${order.quantity}` : ""}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>
            {order.fill_price ? fmtIN(order.fill_price, 2) : "—"}
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
              padding: "10px 16px",
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

/* ---------- Order details panel ---------- */
function OrderDetails({ order }) {
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12 }}>
      <DetailItem label="Order ID" value={order.id || "—"} />
      <DetailItem label="Client Order ID" value={order.client_order_id || "—"} />
      <DetailItem label="Execution Mode" value="PAPER" color={C.gold} />
      <DetailItem label="Kind" value={order.kind === "entry" ? "ENTRY" : "EXIT"} />
      <DetailItem label="Lot Size" value={order.lot_size || "—"} />
      <DetailItem
        label="Realized P&L"
        value={
          order.realized_pnl != null
            ? `${order.realized_pnl >= 0 ? "+" : ""}${fmtIN(order.realized_pnl, 2)}`
            : "—"
        }
        color={
          order.realized_pnl != null
            ? order.realized_pnl >= 0
              ? C.green
              : C.red
            : C.muted
        }
      />
      {order.rejected_reason && (
        <DetailItem
          label="Rejection Reason"
          value={order.rejected_reason}
          color={C.red}
        />
      )}
      <DetailItem
        label="Price Source"
        value={order.price_source || "market"}
      />
      {order.execution_id && (
        <DetailItem label="Strategy Execution" value={order.execution_id} />
      )}
      {order.position_id && (
        <DetailItem label="Position ID" value={String(order.position_id)} />
      )}
    </div>
  );
}

function DetailItem({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 9.5, color: C.faint, letterSpacing: 0.5, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 12, fontWeight: 500, color: color || C.text }}>
        {value}
      </div>
    </div>
  );
}

/* ---------- Empty state ---------- */
function EmptyState({ message }) {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "48px 16px",
        color: C.muted,
        fontSize: 13,
      }}
    >
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>📋</div>
      <div>{message}</div>
    </div>
  );
}

/* ---------- Table cell style ---------- */
function cellStyle(isMobile) {
  return {
    padding: isMobile ? "6px 8px" : "8px 12px",
    fontSize: 12,
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  };
}

/* ---------- Main page ---------- */
export default function OrdersPage() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);
  const [orders, setOrders] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("all");
  const [expandedRow, setExpandedRow] = useState(null);
  const isMobile = useIsMobile();

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
    setLoading(true);
    getPaperOrders()
      .then((data) => {
        setOrders(data);
        setLoading(false);
      })
      .catch((e) => {
        if (isAuthError(e)) setSessionExpired(true);
        else setError(e.message);
        setLoading(false);
      });
  }, [loggedIn]);

  const filteredOrders = useMemo(() => {
    if (!orders) return [];
    if (activeTab === "all") return orders;
    if (activeTab === "open")
      return orders.filter(
        (o) => o.status === "PENDING" || o.status === "PARTIALLY_FILLED"
      );
    if (activeTab === "filled")
      return orders.filter(
        (o) => o.status === "FILLED" || o.status === "PARTIALLY_FILLED"
      );
    if (activeTab === "rejected")
      return orders.filter((o) => o.status === "REJECTED" || o.status === "FAILED");
    if (activeTab === "cancelled")
      return orders.filter(
        (o) => o.status === "CANCELLED" || o.status === "EXPIRED"
      );
    return orders;
  }, [orders, activeTab]);

  // Summary counts
  const counts = useMemo(() => {
    if (!orders) return { total: 0, open: 0, filled: 0, rejected: 0, cancelled: 0 };
    return {
      total: orders.length,
      open: orders.filter(
        (o) => o.status === "PENDING" || o.status === "PARTIALLY_FILLED"
      ).length,
      filled: orders.filter(
        (o) => o.status === "FILLED" || o.status === "PARTIALLY_FILLED"
      ).length,
      rejected: orders.filter(
        (o) => o.status === "REJECTED" || o.status === "FAILED"
      ).length,
      cancelled: orders.filter(
        (o) => o.status === "CANCELLED" || o.status === "EXPIRED"
      ).length,
    };
  }, [orders]);

  if (loggedIn === null) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60vh" }}>
        Checking login…
      </div>
    );
  }
  if (sessionExpired) return <SessionExpired />;
  if (error && !orders) {
    return (
      <div style={{ textAlign: "center", padding: 48, color: C.red }}>
        Something went wrong: {error}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Orders
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Paper execution — no real broker orders
        </p>
      </div>

      {/* Tabs */}
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
            tab.key === "all"
              ? counts.total
              : tab.key === "open"
                ? counts.open
                : tab.key === "filled"
                  ? counts.filled
                  : tab.key === "rejected"
                    ? counts.rejected
                    : tab.key === "cancelled"
                      ? counts.cancelled
                      : 0;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
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

      {/* Orders table */}
      {loading ? (
        <div
          style={{
            textAlign: "center",
            padding: 48,
            color: C.muted,
            fontSize: 13,
          }}
        >
          Loading orders…
        </div>
      ) : filteredOrders.length === 0 ? (
        <EmptyState
          message={
            activeTab === "all"
              ? "No orders yet. Execute a strategy to see orders here."
              : `No ${activeTab} orders.`
          }
        />
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 12,
            }}
          >
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
              {filteredOrders.map((order, i) => (
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
