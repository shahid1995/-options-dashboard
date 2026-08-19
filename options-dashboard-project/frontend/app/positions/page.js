"use client";
import React, { useEffect, useState, useMemo, useCallback } from "react";
import { getPaperPositionsFiltered, previewExitIntent, confirmExitIntent } from "@/lib/api";
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

export function PositionDetails({ position, onExit }) {
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

      {/* Exit Button */}
      {position.status === "open" && (
        <div style={{ marginTop: 8 }}>
          <button data-testid="exit-button"
            onClick={(e) => { e.stopPropagation(); onExit?.(); }}
            style={{ fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 6,
              border: "none", background: C.gold, color: "#0B0E14", cursor: "pointer" }}>
            Exit Position
          </button>
        </div>
      )}
    </div>
  );
}

// ---- Exit Flow (Phase 6.6.5) ----

export function ExitFlow({ position, onClose, onExited }) {
  // Generate one stable client_order_id for the ENTIRE exit flow (preview + confirm).
  // This is the idempotency key — using the same key for preview and confirm
  // ensures the paper engine treats a retry as a replay, not a second execution.
  const [clientOrderId] = useState(() =>
    `exit-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  );
  const [step, setStep] = useState("select"); // select | preview | confirming | result
  const [selector, setSelector] = useState({
    scope: "POSITION",
    strategy_execution_id: "",
    option_type: "",
    action: "",
    quantity_mode: "ALL",
    quantity: "",
  });
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // Derive unique strategy executions from the position's exposures.
  // A position can contain exposures from multiple strategies; the UI
  // must list all of them so the user can target the correct one.
  const strategyOptions = useMemo(() => {
    const legs = position.strategy_leg_exposures || [];
    const seen = new Map();
    for (const leg of legs) {
      if (leg.status === "open" && leg.remaining_quantity > 0 && leg.execution_id) {
        if (!seen.has(leg.execution_id)) {
          seen.set(leg.execution_id, {
            execution_id: leg.execution_id,
            label: position.strategy_tag && seen.size === 0
              ? position.strategy_tag
              : leg.execution_id,
          });
        }
      }
    }
    return Array.from(seen.values());
  }, [position.strategy_leg_exposures, position.strategy_tag]);

  const canPreview = selector.quantity_mode === "ALL" ||
    (selector.quantity_mode === "QUANTITY" && Number(selector.quantity) > 0);

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = {
        client_order_id: clientOrderId,
        scope: selector.scope,
        quantity_mode: selector.quantity_mode,
      };
      if (selector.scope === "POSITION") payload.position_id = position.id;
      if (selector.scope === "STRATEGY") {
        payload.strategy_execution_id = selector.strategy_execution_id ||
          (strategyOptions.length === 1 ? strategyOptions[0].execution_id : "");
      }
      if (selector.option_type) payload.option_type = selector.option_type;
      if (selector.action) payload.action = selector.action;
      if (selector.quantity_mode === "QUANTITY") payload.quantity = Number(selector.quantity);

      const data = await previewExitIntent(payload);
      if (data.status === "PREVIEW" && data.targets.length > 0) {
        setPreview(data);
        setStep("preview");
      } else {
        setError(data.errors?.[0] || "No matching exposure found.");
      }
    } catch (e) {
      setError(e.message || "Preview failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);
    setStep("confirming");
    try {
      const payload = {
        client_order_id: clientOrderId,
        scope: selector.scope,
        quantity_mode: selector.quantity_mode,
      };
      if (selector.scope === "POSITION") payload.position_id = position.id;
      if (selector.scope === "STRATEGY") {
        payload.strategy_execution_id = selector.strategy_execution_id ||
          (strategyOptions.length === 1 ? strategyOptions[0].execution_id : "");
      }
      if (selector.option_type) payload.option_type = selector.option_type;
      if (selector.action) payload.action = selector.action;
      if (selector.quantity_mode === "QUANTITY") payload.quantity = Number(selector.quantity);

      const data = await confirmExitIntent(payload);
      setResult(data);
      setStep("result");
      if (data.status === "SUCCESS") onExited?.();
    } catch (e) {
      setError(e.message || "Exit failed.");
      setStep("preview");
    } finally {
      setLoading(false);
    }
  };

  const badge = (text, color, bg) => (
    <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.5, padding: "2px 6px",
      borderRadius: 3, color, background: bg }}>{text}</span>
  );

  return (
    <div data-testid="exit-flow" style={{ background: C.surface2, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: 12, marginTop: 8 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: C.gold, letterSpacing: 0.5 }}>
          EXIT {position.symbol} {position.strike ? fmtIN(position.strike) : ""} {position.option_type === "call" ? "CE" : "PE"}
        </div>
        <button onClick={onClose} style={{ fontSize: 11, color: C.muted, background: "none",
          border: "none", cursor: "pointer" }}>✕ Close</button>
      </div>

      {/* PAPER mode indicator */}
      <div style={{ marginBottom: 8 }}>
        {badge("PAPER", C.gold, "rgba(201,161,90,0.15)")}
        <span style={{ fontSize: 10, color: C.faint, marginLeft: 6 }}>
          Simulated — no broker orders
        </span>
      </div>

      {/* Step: Select */}
      {step === "select" && (
        <div>
          {/* Scope */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>SCOPE</div>
            <div style={{ display: "flex", gap: 4 }}>
              {["POSITION", "STRATEGY"].map((s) => (
                <button key={s} onClick={() => setSelector({ ...selector, scope: s })}
                  style={{ fontSize: 10, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                    border: `1px solid ${selector.scope === s ? C.gold : C.border}`,
                    background: selector.scope === s ? "rgba(201,161,90,0.1)" : "transparent",
                    color: selector.scope === s ? C.gold : C.muted, cursor: "pointer" }}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Strategy selector (only when scope is STRATEGY) */}
          {selector.scope === "STRATEGY" && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>STRATEGY</div>
              {strategyOptions.length > 1 ? (
                <select
                  value={selector.strategy_execution_id}
                  onChange={(e) => setSelector({ ...selector, strategy_execution_id: e.target.value })}
                  style={{ fontSize: 11, padding: "4px 8px", borderRadius: 4,
                    border: `1px solid ${C.border}`, background: C.surface, color: C.text, cursor: "pointer" }}
                >
                  <option value="">All strategies</option>
                  {strategyOptions.map((opt) => (
                    <option key={opt.execution_id} value={opt.execution_id}>
                      {opt.execution_id}
                    </option>
                  ))}
                </select>
              ) : strategyOptions.length === 1 ? (
                <div style={{ fontSize: 11, color: C.gold, fontWeight: 600 }}>
                  {position.strategy_tag || strategyOptions[0].execution_id}
                </div>
              ) : (
                <div style={{ fontSize: 10, color: C.faint }}>No open strategy exposures</div>
              )}
            </div>
          )}

          {/* Option Type */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>OPTION TYPE</div>
            <div style={{ display: "flex", gap: 4 }}>
              {[{ v: "", l: "ALL" }, { v: "CALL", l: "CE" }, { v: "PUT", l: "PE" }].map(({ v, l }) => (
                <button key={v} onClick={() => setSelector({ ...selector, option_type: v })}
                  style={{ fontSize: 10, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                    border: `1px solid ${selector.option_type === v ? C.gold : C.border}`,
                    background: selector.option_type === v ? "rgba(201,161,90,0.1)" : "transparent",
                    color: selector.option_type === v ? C.gold : C.muted, cursor: "pointer" }}>
                  {l}
                </button>
              ))}
            </div>
          </div>

          {/* Action */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>SOURCE ACTION</div>
            <div style={{ display: "flex", gap: 4 }}>
              {[{ v: "", l: "ALL" }, { v: "BUY", l: "BUY" }, { v: "SELL", l: "SELL" }].map(({ v, l }) => (
                <button key={v} onClick={() => setSelector({ ...selector, action: v })}
                  style={{ fontSize: 10, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                    border: `1px solid ${selector.action === v ? C.gold : C.border}`,
                    background: selector.action === v ? "rgba(201,161,90,0.1)" : "transparent",
                    color: selector.action === v ? C.gold : C.muted, cursor: "pointer" }}>
                  {l}
                </button>
              ))}
            </div>
          </div>

          {/* Quantity */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.5, marginBottom: 4 }}>QUANTITY (lots)</div>
            <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
              <button onClick={() => setSelector({ ...selector, quantity_mode: "ALL" })}
                style={{ fontSize: 10, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                  border: `1px solid ${selector.quantity_mode === "ALL" ? C.gold : C.border}`,
                  background: selector.quantity_mode === "ALL" ? "rgba(201,161,90,0.1)" : "transparent",
                  color: selector.quantity_mode === "ALL" ? C.gold : C.muted, cursor: "pointer" }}>
                ALL
              </button>
              <button onClick={() => setSelector({ ...selector, quantity_mode: "QUANTITY" })}
                style={{ fontSize: 10, fontWeight: 600, padding: "4px 8px", borderRadius: 4,
                  border: `1px solid ${selector.quantity_mode === "QUANTITY" ? C.gold : C.border}`,
                  background: selector.quantity_mode === "QUANTITY" ? "rgba(201,161,90,0.1)" : "transparent",
                  color: selector.quantity_mode === "QUANTITY" ? C.gold : C.muted, cursor: "pointer" }}>
                QTY
              </button>
              {selector.quantity_mode === "QUANTITY" && (
                <input type="number" min={1} value={selector.quantity}
                  onChange={(e) => setSelector({ ...selector, quantity: e.target.value })}
                  placeholder="lots"
                  style={{ width: 60, fontSize: 11, padding: "4px 6px", borderRadius: 4,
                    background: C.surface, color: C.text, border: `1px solid ${C.border}` }} />
              )}
            </div>
            {selector.quantity_mode === "QUANTITY" && Number(selector.quantity) > 0 && position.lot_size > 0 && (
              <div style={{ fontSize: 9, color: C.faint, marginTop: 3 }}>
                = {Number(selector.quantity) * position.lot_size} contracts ({position.lot_size} contracts/lot)
              </div>
            )}
          </div>

          {/* Preview button */}
          <button onClick={handlePreview} disabled={!canPreview || loading}
            style={{ width: "100%", fontSize: 11, fontWeight: 700, padding: "8px 0",
              borderRadius: 6, border: "none", cursor: canPreview && !loading ? "pointer" : "default",
              background: canPreview ? C.gold : C.surface2,
              color: canPreview ? "#0B0E14" : C.muted, opacity: canPreview ? 1 : 0.5 }}>
            {loading ? "Resolving…" : "Preview Exit"}
          </button>
        </div>
      )}

      {/* Step: Preview */}
      {step === "preview" && preview && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.gold, letterSpacing: 0.5, marginBottom: 8 }}>
            EXIT PREVIEW
          </div>
          {preview.targets.map((t, i) => (
            <div key={i} style={{ background: C.surface, border: `1px solid ${C.border}`,
              borderRadius: 6, padding: 10, marginBottom: 8 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", fontSize: 11 }}>
                <div><span style={{ color: C.faint, fontSize: 9 }}>INSTRUMENT</span><br />
                  <span style={{ fontWeight: 600 }}>{t.symbol} {fmtIN(t.strike)} {t.option_type === "call" ? "CE" : "PE"}</span></div>
                <div><span style={{ color: C.faint, fontSize: 9 }}>STRATEGY</span><br />
                  <span style={{ color: C.gold }}>{position.strategy_tag || "Custom"}</span></div>
                <div><span style={{ color: C.faint, fontSize: 9 }}>SOURCE</span><br />
                  <span style={{ fontWeight: 700, color: t.source_action === "buy" ? C.green : C.red }}>
                    {t.source_action?.toUpperCase()} {t.option_type === "call" ? "CE" : "PE"}
                  </span></div>
                <div><span style={{ color: C.faint, fontSize: 9 }}>EXECUTION</span><br />
                  <span style={{ fontWeight: 700, color: t.exit_side === "buy" ? C.green : C.red }}>
                    {t.exit_side?.toUpperCase()} {t.option_type === "call" ? "CE" : "PE"}
                  </span></div>
                <div><span style={{ color: C.faint, fontSize: 9 }}>EXIT QTY</span><br />
                  <span style={{ fontWeight: 600 }}>{t.quantity} lot{t.quantity !== 1 ? "s" : ""}
                  {t.lot_size > 0 && <span style={{ color: C.faint, fontSize: 9 }}> ({t.quantity * t.lot_size} contracts)</span>}</span></div>
                <div><span style={{ color: C.faint, fontSize: 9 }}>REMAINING AFTER</span><br />
                  <span style={{ fontWeight: 600 }}>{t.remaining_quantity - t.quantity} lot{(t.remaining_quantity - t.quantity) !== 1 ? "s" : ""}</span></div>
              </div>
            </div>
          ))}

          {preview.warnings?.length > 0 && (
            <div style={{ fontSize: 10, color: C.gold, marginBottom: 8 }}>
              {preview.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}

          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => setStep("select")}
              style={{ flex: 1, fontSize: 11, fontWeight: 700, padding: "8px 0", borderRadius: 6,
                border: `1px solid ${C.border}`, background: C.surface2, color: C.muted, cursor: "pointer" }}>
              Back
            </button>
            <button onClick={handleConfirm} disabled={loading}
              style={{ flex: 1, fontSize: 11, fontWeight: 800, padding: "8px 0", borderRadius: 6,
                border: "none", background: C.gold, color: "#0B0E14", cursor: loading ? "default" : "pointer",
                opacity: loading ? 0.6 : 1 }}>
              {loading ? "Executing…" : "Confirm Exit"}
            </button>
          </div>
        </div>
      )}

      {/* Step: Confirming */}
      {step === "confirming" && (
        <div style={{ textAlign: "center", padding: 20, color: C.muted, fontSize: 12 }}>
          Executing exit…
        </div>
      )}

      {/* Step: Result */}
      {step === "result" && result && (
        <div>
          <div style={{ textAlign: "center", marginBottom: 10 }}>
            {result.status === "SUCCESS" && badge("EXIT SUCCESSFUL", C.green, "rgba(76,175,125,0.15)")}
            {result.status === "DUPLICATE" && badge("ALREADY EXECUTED", C.gold, "rgba(201,161,90,0.15)")}
            {result.status === "FAILED" && badge("EXIT FAILED", C.red, "rgba(225,82,82,0.15)")}
            {result.status === "REJECTED" && badge("EXIT REJECTED", C.red, "rgba(225,82,82,0.15)")}
          </div>
          {result.orders?.length > 0 && (
            <div style={{ fontSize: 11, marginBottom: 8 }}>
              <span style={{ color: C.faint }}>Order:</span>{" "}
              <span style={{ fontWeight: 600 }}>
                {result.orders[0].action?.toUpperCase()} {result.orders[0].filled_quantity} @ {fmtIN(result.orders[0].fill_price, 2)}
              </span>
            </div>
          )}
          {result.errors?.length > 0 && (
            <div style={{ fontSize: 10, color: C.red, marginBottom: 8 }}>
              {result.errors.map((e, i) => <div key={i}>{e}</div>)}
            </div>
          )}
          <button onClick={onClose}
            style={{ width: "100%", fontSize: 11, fontWeight: 700, padding: "8px 0", borderRadius: 6,
              border: `1px solid ${C.border}`, background: C.surface2, color: C.gold, cursor: "pointer" }}>
            Close
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ fontSize: 10, color: C.red, marginTop: 8, padding: 6, borderRadius: 4,
          background: "rgba(225,82,82,0.08)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ---- Position row ----

export function PositionRow({ position, isExpanded, onToggle, isMobile, onExit }) {
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
            <PositionDetails position={position} onExit={() => onExit?.(position)} />
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
  const [exitPosition, setExitPosition] = useState(null);
  const [filters, setFilters] = useState({ symbol: "", option_type: "", strategy_execution_id: "" });
  const isMobile = useIsMobile();

  const handleExit = useCallback((pos) => {
    setExitPosition(pos);
    setExpandedRow(pos.id);
  }, []);

  const fetchPositions = useCallback(() => {
    setLoading(true);
    setError(null);

    // Use all=true for the "All" tab to activate the enriched endpoint
    // and return both open + closed positions (server-authoritative).
    // The backend falls back to legacy get_open_positions() when no params.
    const params = {};
    if (activeTab === "open") params.status = "open";
    else if (activeTab === "closed") params.status = "closed";
    else if (activeTab === "all") params.all = true;
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

  // Compute counts for all tabs by fetching all positions via enriched path.
  const [allPositions, setAllPositions] = useState(null);
  useEffect(() => {
    if (!loggedIn) return;
    getPaperPositionsFiltered({ all: true, limit: 500 })
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
                <React.Fragment key={pos.id || i}>
                  <PositionRow
                    position={pos}
                    isExpanded={expandedRow === pos.id}
                    onToggle={() => {
                      if (exitPosition?.id === pos.id) setExitPosition(null);
                      setExpandedRow(expandedRow === pos.id ? null : pos.id);
                    }}
                    isMobile={isMobile}
                    onExit={handleExit}
                  />
                  {expandedRow === pos.id && exitPosition?.id === pos.id && (
                    <tr>
                      <td colSpan={isMobile ? 5 : 10} style={{ padding: "0 16px 12px" }}>
                        <ExitFlow
                          position={pos}
                          onClose={() => setExitPosition(null)}
                          onExited={() => {
                            setExitPosition(null);
                            fetchPositions();
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
