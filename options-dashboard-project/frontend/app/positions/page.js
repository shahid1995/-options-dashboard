"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { getPaperPositionsFiltered } from "@/lib/api";
import { C, fmtIN, SessionExpired, useIsMobile } from "@/lib/ui";
import { isAuthError } from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";

// ---- Constants ----

const TABS = [
  { key: "open", label: "Open" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
];

const SYMBOL_OPTIONS = ["", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "SENSEX50"];

// ---- Helpers ----

function fmtExpiry(iso) {
  if (!iso) return "\u2014";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

function formatTime(iso) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

// ---- Small reusable components ----

function SideBadge({ side }) {
  const isLong = side === "LONG";
  return (
    <span
      style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
        color: isLong ? C.green : side === "SHORT" ? C.red : C.muted,
      }}
    >
      {side || "\u2014"}
    </span>
  );
}

function OptionBadge({ type }) {
  const isCall = type === "call";
  return (
    <span
      style={{
        fontSize: 10, fontWeight: 600, letterSpacing: 0.5,
        padding: "1px 5px", borderRadius: 3,
        background: isCall ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)",
        color: isCall ? C.green : C.red,
      }}
    >
      {isCall ? "CE" : "PE"}
    </span>
  );
}

function StatusBadge({ status }) {
  const isOpen = status === "open";
  return (
    <span
      style={{
        fontSize: 10, fontWeight: 600, letterSpacing: 0.5,
        padding: "2px 6px", borderRadius: 3,
        background: isOpen ? "rgba(76,175,125,0.15)" : "rgba(136,146,166,0.15)",
        color: isOpen ? C.green : C.muted,
      }}
    >
      {isOpen ? "OPEN" : "CLOSED"}
    </span>
  );
}

// ---- Tabs ----

function PositionTabs({ activeTab, onTabChange, counts }) {
  return (
    <div
      style={{
        display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap",
        borderBottom: `1px solid ${C.border}`, paddingBottom: 8,
      }}
    >
      {TABS.map((tab) => {
        const count = tab.key === "open" ? counts.open : tab.key === "closed" ? counts.closed : counts.all;
        const isActive = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            style={{
              fontSize: 12, padding: "6px 12px", borderRadius: 6,
              border: `1px solid ${isActive ? C.gold : C.border}`,
              background: isActive ? "rgba(201,161,90,0.1)" : "transparent",
              color: isActive ? C.gold : C.muted, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 6,
              fontWeight: isActive ? 600 : 400,
            }}
          >
            {tab.label}
            <span
              style={{
                fontSize: 10, padding: "1px 5px", borderRadius: 3,
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

function PositionFilters({ filters, onFilterChange, isMobile }) {
  const selectStyle = {
    fontSize: 11, padding: "4px 8px", borderRadius: 4,
    border: `1px solid ${C.border}`, background: C.surface,
    color: C.text, cursor: "pointer", minWidth: isMobile ? 80 : 100,
  };

  return (
    <div
      style={{
        display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center",
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
        value={filters.option_type}
        onChange={(e) => onFilterChange({ ...filters, option_type: e.target.value })}
        style={selectStyle}
      >
        <option value="">All Types</option>
        <option value="call">CE (Call)</option>
        <option value="put">PE (Put)</option>
      </select>
      <select
        value={filters.strategy_execution_id}
        onChange={(e) => onFilterChange({ ...filters, strategy_execution_id: e.target.value })}
        style={selectStyle}
      >
        <option value="">All Strategies</option>
      </select>
      {(filters.symbol || filters.option_type || filters.strategy_execution_id) && (
        <button
          onClick={() => onFilterChange({ symbol: "", option_type: "", strategy_execution_id: "" })}
          style={{
            fontSize: 10, padding: "4px 8px", borderRadius: 4,
            border: `1px solid ${C.border}`, background: "transparent",
            color: C.muted, cursor: "pointer",
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
          fontSize: 10, fontWeight: 700, color: C.gold, letterSpacing: 1,
          marginBottom: 6, paddingBottom: 4, borderBottom: `1px solid ${C.border}`,
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
      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
      <div
        style={{
          fontSize: 11.5, fontWeight: 500, color: color || C.text,
          fontFamily: mono ? "monospace" : "inherit",
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ---- Position details (structured) ----

export function PositionDetails({ position }) {
  const absQty = Math.abs(position.net_quantity || 0);
  const lots = position.lot_size ? Math.floor(absQty) : null;
  const legs = position.strategy_leg_exposures || [];
  const orders = position.orders || [];
  const entryOrders = orders.filter((o) => o.kind === "entry" && o.status === "FILLED");
  const exitOrders = orders.filter((o) => o.kind === "exit" && o.status === "FILLED");

  return (
    <div style={{ fontSize: 12, maxWidth: 900 }}>
      {/* Section A: Position */}
      <DetailSection title="POSITION">
        <DetailItem label="Position ID" value={position.id || "\u2014"} mono />
        <DetailItem label="Execution Mode" value="PAPER" color={C.gold} />
        <DetailItem label="Side" value={<SideBadge side={position.side} />} />
        <DetailItem label="Status" value={<StatusBadge status={position.status} />} />
        <DetailItem label="Opened" value={formatTime(position.opened_at)} />
        {position.closed_at && (
          <DetailItem label="Closed" value={formatTime(position.closed_at)} />
        )}
      </DetailSection>

      {/* Section B: Instrument */}
      <DetailSection title="INSTRUMENT">
        <DetailItem label="Symbol" value={position.symbol || "\u2014"} />
        <DetailItem label="Expiry" value={fmtExpiry(position.expiry)} />
        <DetailItem label="Strike" value={position.strike ? fmtIN(position.strike) : "\u2014"} color={C.gold} />
        <DetailItem label="Type" value={<OptionBadge type={position.option_type} />} />
      </DetailSection>

      {/* Section C: Pricing */}
      <DetailSection title="PRICING">
        <DetailItem label="Quantity" value={`${absQty} lots`} />
        {position.lot_size > 0 && (
          <DetailItem label="Lot Size" value={`${position.lot_size} contracts/lot`} />
        )}
        <DetailItem
          label="Avg Entry"
          value={position.average_entry_price ? fmtIN(position.average_entry_price, 2) : "\u2014"}
          color={position.average_entry_price ? C.text : C.muted}
        />
        <DetailItem label="Current Price" value="N/A" color={C.faint} />
        <DetailItem label="Price Source" value="unavailable" color={C.faint} />
      </DetailSection>

      {/* Section D: P&L */}
      <DetailSection title="P&L">
        <DetailItem
          label="Realized P&L"
          value={`${position.realized_pnl >= 0 ? "+" : ""}${fmtIN(position.realized_pnl, 2)}`}
          color={position.realized_pnl >= 0 ? C.green : C.red}
        />
        <DetailItem label="Unrealized P&L" value="N/A" color={C.faint} />
      </DetailSection>

      {/* Section E: Strategy Attribution */}
      <DetailSection title="STRATEGY">
        <DetailItem
          label="Strategy"
          value={position.strategy_tag || "Custom"}
          color={position.strategy_tag && position.strategy_tag !== "Custom" ? C.gold : C.muted}
        />
        <DetailItem label="Execution ID" value={position.strategy_execution_id || "\u2014"} mono />
        {legs.length > 0 && (
          <div style={{ width: "100%", marginTop: 4 }}>
            <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>
              LEG ATTRIBUTION ({legs.length})
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ color: C.faint, fontSize: 9, letterSpacing: 0.5 }}>
                  <th style={{ padding: "3px 6px", textAlign: "left" }}>ACTION</th>
                  <th style={{ padding: "3px 6px", textAlign: "left" }}>ORIGINAL</th>
                  <th style={{ padding: "3px 6px", textAlign: "left" }}>REMAINING</th>
                  <th style={{ padding: "3px 6px", textAlign: "left" }}>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {legs.map((leg) => (
                  <tr key={leg.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: "3px 6px" }}>
                      <span style={{ fontWeight: 700, color: leg.action === "buy" ? C.green : C.red }}>
                        {leg.action?.toUpperCase() || "\u2014"}
                      </span>
                    </td>
                    <td style={{ padding: "3px 6px" }}>{leg.original_quantity}</td>
                    <td style={{ padding: "3px 6px" }}>{leg.remaining_quantity}</td>
                    <td style={{ padding: "3px 6px" }}>
                      <span
                        style={{
                          fontSize: 9, fontWeight: 600, padding: "1px 4px", borderRadius: 3,
                          background: leg.status === "open" ? "rgba(76,175,125,0.1)" : "rgba(136,146,166,0.1)",
                          color: leg.status === "open" ? C.green : C.muted,
                        }}
                      >
                        {leg.status?.toUpperCase() || "\u2014"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DetailSection>

      {/* Section F: Order Trace */}
      <DetailSection title="ORDER TRACE">
        <div style={{ width: "100%" }}>
          {entryOrders.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>
                ENTRY ORDERS ({entryOrders.length})
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ color: C.faint, fontSize: 9, letterSpacing: 0.5 }}>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>ORDER ID</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>SIDE</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>QTY</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>FILL PRICE</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>TIME</th>
                  </tr>
                </thead>
                <tbody>
                  {entryOrders.map((o) => (
                    <tr key={o.id} style={{ borderTop: `1px solid ${C.border}` }}>
                      <td style={{ padding: "3px 6px" }}>{o.id || "\u2014"}</td>
                      <td style={{ padding: "3px 6px" }}>
                        <span style={{ fontWeight: 700, color: o.action === "buy" ? C.green : C.red }}>
                          {o.action?.toUpperCase() || "\u2014"}
                        </span>
                      </td>
                      <td style={{ padding: "3px 6px" }}>{o.filled_quantity}/{o.quantity}</td>
                      <td style={{ padding: "3px 6px" }}>
                        {o.fill_price ? fmtIN(o.fill_price, 2) : "\u2014"}
                      </td>
                      <td style={{ padding: "3px 6px" }}>{formatTime(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {exitOrders.length > 0 && (
            <div>
              <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>
                EXIT ORDERS ({exitOrders.length})
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead>
                  <tr style={{ color: C.faint, fontSize: 9, letterSpacing: 0.5 }}>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>ORDER ID</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>SIDE</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>QTY</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>FILL PRICE</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>P&L</th>
                    <th style={{ padding: "3px 6px", textAlign: "left" }}>TIME</th>
                  </tr>
                </thead>
                <tbody>
                  {exitOrders.map((o) => (
                    <tr key={o.id} style={{ borderTop: `1px solid ${C.border}` }}>
                      <td style={{ padding: "3px 6px" }}>{o.id || "\u2014"}</td>
                      <td style={{ padding: "3px 6px" }}>
                        <span style={{ fontWeight: 700, color: o.action === "buy" ? C.green : C.red }}>
                          {o.action?.toUpperCase() || "\u2014"}
                        </span>
                      </td>
                      <td style={{ padding: "3px 6px" }}>{o.filled_quantity}/{o.quantity}</td>
                      <td style={{ padding: "3px 6px" }}>
                        {o.fill_price ? fmtIN(o.fill_price, 2) : "\u2014"}
                      </td>
                      <td style={{ padding: "3px 6px", color: (o.realized_pnl || 0) >= 0 ? C.green : C.red }}>
                        {o.realized_pnl != null ? `${o.realized_pnl >= 0 ? "+" : ""}${fmtIN(o.realized_pnl, 2)}` : "\u2014"}
                      </td>
                      <td style={{ padding: "3px 6px" }}>{formatTime(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {entryOrders.length === 0 && exitOrders.length === 0 && (
            <div style={{ fontSize: 11, color: C.faint }}>No order data available.</div>
          )}
        </div>
      </DetailSection>

      {/* Section G: Broker */}
      <DetailSection title="BROKER">
        <DetailItem label="Broker" value="Paper" color={C.gold} />
        <DetailItem label="Broker Position ID" value="N/A" color={C.faint} />
      </DetailSection>
    </div>
  );
}

// ---- Position row ----

export function PositionRow({ position, isExpanded, onToggle, isMobile }) {
  const absQty = Math.abs(position.net_quantity || 0);
  const lots = position.lot_size > 0 ? Math.floor(absQty) : null;

  return (
    <>
      <tr
        onClick={onToggle}
        data-testid="position-row"
        style={{
          borderBottom: `1px solid ${C.border}`, cursor: "pointer",
          background: isExpanded ? "rgba(201,161,90,0.04)" : "transparent",
          transition: "background 0.15s",
        }}
      >
        <td style={cellStyle(isMobile)}>
          <SideBadge side={position.side} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontWeight: 600, fontSize: 12 }}>{position.symbol || "\u2014"}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>{fmtExpiry(position.expiry)}</span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, color: C.gold }}>
            {position.strike ? fmtIN(position.strike) : "\u2014"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <OptionBadge type={position.option_type} />
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12 }}>
            {absQty}
            {lots != null && <span style={{ color: C.faint, fontSize: 10 }}> ({lots} lot{lots !== 1 ? "s" : ""})</span>}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>
            {position.average_entry_price ? fmtIN(position.average_entry_price, 2) : "\u2014"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span
            style={{
              fontSize: 12, fontWeight: 600,
              color: (position.realized_pnl || 0) >= 0 ? C.green : C.red,
            }}
          >
            {position.realized_pnl >= 0 ? "+" : ""}
            {fmtIN(position.realized_pnl || 0, 2)}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <span
            style={{
              fontSize: 11,
              color: position.strategy_tag && position.strategy_tag !== "Custom" ? C.gold : C.muted,
            }}
          >
            {position.strategy_tag || "Custom"}
          </span>
        </td>
        <td style={cellStyle(isMobile)}>
          <StatusBadge status={position.status} />
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td
            colSpan={isMobile ? 5 : 10}
            style={{
              padding: "12px 16px",
              background: "rgba(201,161,90,0.03)",
              borderBottom: `1px solid ${C.border}`,
            }}
          >
            <PositionDetails position={position} />
          </td>
        </tr>
      )}
    </>
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

// ---- Empty state ----

function EmptyState({ message }) {
  return (
    <div
      style={{ textAlign: "center", padding: "48px 16px", color: C.muted, fontSize: 13 }}
      data-testid="empty-state"
    >
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>{ "\uD83D\uDCD0" }</div>
      <div>{message}</div>
    </div>
  );
}

// ---- Error state ----

function ErrorState({ message, onRetry }) {
  return (
    <div
      style={{ textAlign: "center", padding: "48px 16px", color: C.red, fontSize: 13 }}
      data-testid="error-state"
    >
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.6 }}>{ "\u26A0\uFE0F" }</div>
      <div style={{ marginBottom: 12 }}>{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            fontSize: 12, padding: "6px 14px", borderRadius: 6,
            border: `1px solid ${C.border}`, background: C.surface,
            color: C.gold, cursor: "pointer",
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ---- Main page ----

export default function PositionsPage() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);
  const [positions, setPositions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("open");
  const [expandedRow, setExpandedRow] = useState(null);
  const [filters, setFilters] = useState({ symbol: "", option_type: "", strategy_execution_id: "" });
  const isMobile = useIsMobile();

  const fetchPositions = useCallback(() => {
    setLoading(true);
    setError(null);

    const params = {};
    if (activeTab === "open") params.status = "open";
    else if (activeTab === "closed") params.status = "closed";
    if (filters.symbol) params.symbol = filters.symbol;
    if (filters.option_type) params.option_type = filters.option_type;
    if (filters.strategy_execution_id) params.strategy_execution_id = filters.strategy_execution_id;

    getPaperPositionsFiltered(params)
      .then((data) => {
        setPositions(data);
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
    fetchPositions();
  }, [loggedIn, fetchPositions]);

  // Compute counts for all tabs by fetching with no status filter
  const [allPositions, setAllPositions] = useState(null);
  useEffect(() => {
    if (!loggedIn) return;
    getPaperPositionsFiltered({})
      .then((data) => setAllPositions(data))
      .catch(() => {});
  }, [loggedIn]);

  const counts = useMemo(() => {
    const src = allPositions || positions || [];
    if (!src.length && !allPositions) return { all: 0, open: 0, closed: 0 };
    const pool = allPositions || src;
    return {
      all: pool.length,
      open: pool.filter((p) => p.status === "open" && (p.net_quantity || 0) !== 0).length,
      closed: pool.filter((p) => p.status === "closed" || (p.net_quantity || 0) === 0).length,
    };
  }, [positions, allPositions]);

  // Summary stats
  const summary = useMemo(() => {
    const src = positions || [];
    const openPositions = src.filter((p) => p.status === "open" && (p.net_quantity || 0) !== 0);
    const longCount = openPositions.filter((p) => p.net_quantity > 0).length;
    const shortCount = openPositions.filter((p) => p.net_quantity < 0).length;
    const realized = src.reduce((sum, p) => sum + (p.realized_pnl || 0), 0);
    return { openCount: openPositions.length, longCount, shortCount, realized };
  }, [positions]);

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
          Positions
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Paper execution \u2014 no real broker orders
        </p>
      </div>

      {/* Summary */}
      {positions && positions.length > 0 && (
        <div
          style={{
            display: "flex", gap: 16, marginBottom: 12, flexWrap: "wrap",
            fontSize: 12, color: C.muted,
          }}
        >
          <span>
            Open: <span style={{ color: C.gold, fontWeight: 600 }}>{summary.openCount}</span>
          </span>
          <span>
            Long: <span style={{ color: C.green, fontWeight: 600 }}>{summary.longCount}</span>
          </span>
          <span>
            Short: <span style={{ color: C.red, fontWeight: 600 }}>{summary.shortCount}</span>
          </span>
          <span>
            Realized P&L:{" "}
            <span
              style={{
                fontWeight: 600,
                color: summary.realized >= 0 ? C.green : C.red,
              }}
            >
              {summary.realized >= 0 ? "+" : ""}{fmtIN(summary.realized, 2)}
            </span>
          </span>
        </div>
      )}

      {/* Tabs */}
      <PositionTabs activeTab={activeTab} onTabChange={setActiveTab} counts={counts} />

      {/* Filters */}
      <PositionFilters filters={filters} onFilterChange={setFilters} isMobile={isMobile} />

      {/* Content */}
      {loading ? (
        <div
          style={{ textAlign: "center", padding: 48, color: C.muted, fontSize: 13 }}
          data-testid="loading-state"
        >
          Loading positions\u2026
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={fetchPositions} />
      ) : !positions || positions.length === 0 ? (
        <EmptyState
          message={
            activeTab === "open" && !filters.symbol && !filters.option_type
              ? "No open positions yet. Execute a strategy to open a position."
              : "No positions match the selected filters."
          }
        />
      ) : (
        <div style={{ overflowX: "auto" }} data-testid="positions-table">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr
                style={{
                  color: C.faint, fontSize: 10, letterSpacing: 0.5,
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>SIDE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>SYMBOL</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>EXPIRY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>STRIKE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>TYPE</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>QTY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>AVG ENTRY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>REALIZED P&L</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>STRATEGY</th>
                <th style={{ ...cellStyle(isMobile), textAlign: "left" }}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, i) => (
                <PositionRow
                  key={pos.id || i}
                  position={pos}
                  isExpanded={expandedRow === pos.id}
                  onToggle={() => setExpandedRow(expandedRow === pos.id ? null : pos.id)}
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
