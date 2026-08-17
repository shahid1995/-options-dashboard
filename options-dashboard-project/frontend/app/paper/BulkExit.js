"use client";

// Phase 5.2 bulk-exit UI: confirmation modal (EXIT STRATEGY / EXIT ALL) and
// the post-execution result banner. Display-only components — the backend is
// authoritative for fills, realized P&L, cash and final status; everything
// shown here is informational or a mirror of the server result.

import { C, fmtIN } from "@/lib/ui";

const fmtPnl = (v) => (v == null || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v))}`);
const fmtCash = (v) => (v == null || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v))}`);

const overlay = {
  position: "fixed",
  inset: 0,
  background: "rgba(8,10,14,0.72)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 60,
  padding: 16,
};

const modalBox = {
  width: "100%",
  maxWidth: 430,
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 12,
  padding: 18,
  boxShadow: "0 18px 50px rgba(0,0,0,0.45)",
};

const row = { display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12, padding: "5px 0", fontVariantNumeric: "tabular-nums" };

// Confirmation dialog. `kind` is "STRATEGY" (one strategy group) or
// "ACCOUNT" (every open position). For STRATEGY, `target` carries the
// group { strategyName, positions, value, unrealized }; for ACCOUNT,
// `accountStats` carries { openPositions, openStrategies }.
export function BulkExitModal({ kind, target, accountStats, busy, error, onCancel, onConfirm }) {
  if (!kind) return null;
  const isStrategy = kind === "STRATEGY";
  const count = isStrategy ? (target?.positions?.length ?? 0) : (accountStats?.openPositions ?? 0);
  const title = isStrategy ? `Exit all positions for ${target?.strategyName ?? "this strategy"}?` : "EXIT ALL PAPER POSITIONS?";
  const value = isStrategy ? target?.value : null;
  const unrealized = isStrategy ? target?.unrealized : null;
  return (
    <div style={overlay}>
      <div style={modalBox} role="dialog" aria-modal="true">
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 0.5, color: C.text, marginBottom: 4 }}>
          {title}
        </div>
        <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.5, marginBottom: 10 }}>
          {isStrategy
            ? "Every open position of this strategy will be closed at the current market price."
            : "This will close ALL currently open paper positions in this account."}
        </div>

        <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", marginBottom: 8 }}>
          {isStrategy ? (
            <>
              <div style={row}>
                <span style={{ color: C.faint }}>Positions</span>
                <span style={{ color: C.text, fontWeight: 700 }}>{count}</span>
              </div>
              <div style={row}>
                <span style={{ color: C.faint }}>Approximate current value</span>
                <span style={{ color: C.text, fontWeight: 700 }}>{value == null ? "—" : `₹${fmtIN(value)}`}</span>
              </div>
              <div style={row}>
                <span style={{ color: C.faint }}>Current unrealized P&amp;L</span>
                <span style={{ color: unrealized == null ? C.muted : unrealized >= 0 ? C.green : C.red, fontWeight: 700 }}>
                  {fmtPnl(unrealized)}
                </span>
              </div>
            </>
          ) : (
            <>
              <div style={row}>
                <span style={{ color: C.faint }}>Open positions</span>
                <span style={{ color: C.text, fontWeight: 700 }}>{accountStats?.openPositions ?? 0}</span>
              </div>
              <div style={row}>
                <span style={{ color: C.faint }}>Open strategies</span>
                <span style={{ color: C.text, fontWeight: 700 }}>{accountStats?.openStrategies ?? 0}</span>
              </div>
            </>
          )}
        </div>

        <div style={{ fontSize: 10.5, color: C.faint, lineHeight: 1.5, marginBottom: 12 }}>
          The final fill prices will be taken from current market data at execution time. This is informational only —
          the backend is authoritative.
        </div>

        {error && (
          <div style={{ fontSize: 11.5, color: C.red, background: "rgba(225,82,82,0.08)", border: `1px solid rgba(225,82,82,0.35)`, borderRadius: 8, padding: "8px 10px", marginBottom: 12, lineHeight: 1.5 }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={onCancel}
            disabled={busy}
            style={{ fontSize: 11.5, fontWeight: 700, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 16px", cursor: busy ? "default" : "pointer", opacity: busy ? 0.5 : 1 }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            style={{ fontSize: 11.5, fontWeight: 800, color: "#fff", background: C.red, border: "1px solid transparent", borderRadius: 8, padding: "8px 16px", cursor: busy ? "progress" : "pointer", opacity: busy ? 0.65 : 1 }}
          >
            {busy ? "EXITING…" : isStrategy ? "EXIT STRATEGY" : "EXIT ALL"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Post-execution result banner. `result` is the bulkExitDisplay shape.
export function BulkExitResultBanner({ result, onDismiss }) {
  if (!result) return null;
  const { status, requestedCount, exitedCount, failedCount, totalRealizedPnl, cashChange, positions, groups, errors } = result;
  const closedStrategies = (groups ?? []).filter((g) => (g.exited ?? 0) > 0).length;
  const failedPositions = (positions ?? []).filter((p) => p.status !== "EXITED");

  const bannerStyle = {
    border: "1px solid",
    borderRadius: 10,
    padding: "12px 14px",
    marginTop: 12,
    fontSize: 12.5,
    lineHeight: 1.6,
  };

  if (status === "NO_POSITIONS") {
    return (
      <div style={{ ...bannerStyle, background: C.surface2, borderColor: C.border, color: C.muted }}>
        No open positions to exit.
      </div>
    );
  }

  if (status === "SUCCESS") {
    return (
      <div style={{ ...bannerStyle, background: "rgba(76,175,125,0.08)", borderColor: "rgba(76,175,125,0.4)", color: C.text }}>
        <div style={{ fontWeight: 800, color: C.green, letterSpacing: 0.5, marginBottom: 6 }}>✓ EXIT COMPLETE</div>
        <div>Positions exited: <b>{exitedCount}</b> · Strategies closed: <b>{closedStrategies}</b></div>
        <div>Realized P&amp;L: <b style={{ color: totalRealizedPnl >= 0 ? C.green : C.red }}>{fmtPnl(totalRealizedPnl)}</b> · Cash change: <b>{fmtCash(cashChange)}</b></div>
        {result.duplicated && <div style={{ fontSize: 10.5, color: C.faint, marginTop: 4 }}>This request was already processed — showing the original result.</div>}
      </div>
    );
  }

  if (status === "PARTIAL" || status === "FAILED") {
    return (
      <div style={{ ...bannerStyle, background: "rgba(225,82,82,0.08)", borderColor: "rgba(225,82,82,0.4)", color: C.text }}>
        <div style={{ fontWeight: 800, color: C.red, letterSpacing: 0.5, marginBottom: 6 }}>
          {status === "PARTIAL" ? "⚠ EXIT PARTIALLY COMPLETED" : "✕ EXIT FAILED"}
        </div>
        <div>
          Exited: <b>{exitedCount}</b> / {requestedCount} · Failed: <b>{failedCount}</b>
        </div>
        {status === "PARTIAL" && (
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Not all positions were closed — see the failures below.</div>
        )}
        {failedPositions.length > 0 && (
          <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 3 }}>
            {failedPositions.map((p, i) => (
              <div key={i} style={{ fontSize: 11, color: C.red, lineHeight: 1.4 }}>
                • {p.symbol} {fmtIN(p.strike)} {p.option_type === "call" ? "CE" : "PE"} ({p.expiry}): {p.error ?? p.status}
              </div>
            ))}
          </div>
        )}
        {errors.length > 0 && failedPositions.length === 0 && (
          <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 3 }}>
            {errors.map((e, i) => (
              <div key={i} style={{ fontSize: 11, color: C.red, lineHeight: 1.4 }}>• {e}</div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return null;
}
