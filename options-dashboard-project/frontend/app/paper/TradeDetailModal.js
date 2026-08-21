"use client";
import { useEffect, useState } from "react";
import { C, fmtIN } from "@/lib/ui";
import { getTradeDetail } from "@/lib/api";

const pnlColor = (v) => (v == null ? C.muted : v >= 0 ? C.green : C.red);
const fmtPnl = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v), 2)}`);
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
    + " " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
};

const sectionTitle = { fontSize: 10, fontWeight: 800, letterSpacing: 0.8, color: C.muted, marginBottom: 6 };
const labelStyle = { fontSize: 10, color: C.muted };
const valueStyle = { fontSize: 12, fontWeight: 600 };

function Field({ label, value, color }) {
  return (
    <div style={{ minWidth: 100 }}>
      <div style={labelStyle}>{label}</div>
      <div style={{ ...valueStyle, color: color || C.text }}>{value ?? "—"}</div>
    </div>
  );
}

export default function TradeDetailModal({ executionId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!executionId) return;
    setLoading(true);
    setError(null);
    getTradeDetail(executionId)
      .then(setData)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load"))
      .finally(() => setLoading(false));
  }, [executionId]);

  if (!executionId) return null;

  const resultColor = data?.result === "WIN" ? C.green : data?.result === "LOSS" ? C.red : C.gold;

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10000 }}
      onClick={onClose}
    >
      <div
        style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 20, width: 520, maxWidth: "92vw", maxHeight: "85vh", overflowY: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontSize: 14, fontWeight: 800 }}>Trade Detail</div>
          <button onClick={onClose} style={{ fontSize: 18, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>×</button>
        </div>

        {loading && <div style={{ fontSize: 12, color: C.muted, padding: 20 }}>Loading…</div>}
        {error && <div style={{ fontSize: 12, color: C.red, padding: 20 }}>{error}</div>}

        {data && (
          <>
            {/* Overview */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 14 }}>
              <Field label="Strategy" value={data.strategy} />
              <Field label="Symbol" value={data.symbol} />
              <Field label="Status" value={data.status} />
              <Field label="Result" value={data.result} color={resultColor} />
              <Field label="P&L" value={fmtPnl(data.realized_pnl)} color={pnlColor(data.realized_pnl)} />
              <Field label="Duration" value={data.duration_label} />
              <Field label="Entry Net" value={data.entry_net != null ? `₹${fmtIN(data.entry_net, 2)}` : "—"} />
              <Field label="Execution ID" value={data.execution_id} />
            </div>

            <div style={{ display: "flex", gap: 16, marginBottom: 14 }}>
              <Field label="Entry" value={fmtDate(data.entry_at)} />
              <Field label="Exit" value={fmtDate(data.exit_at)} />
              <Field label="Total Qty" value={data.total_quantity} />
              <Field label="Exposure" value={data.total_exposure ? `₹${fmtIN(data.total_exposure, 2)}` : "—"} />
            </div>

            {/* Legs */}
            {data.legs && data.legs.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={sectionTitle}>LEGS</div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                      <th style={{ padding: "4px 6px" }}>Action</th>
                      <th style={{ padding: "4px 6px" }}>Type</th>
                      <th style={{ padding: "4px 6px" }}>Strike</th>
                      <th style={{ padding: "4px 6px" }}>Expiry</th>
                      <th style={{ padding: "4px 6px" }}>Qty</th>
                      <th style={{ padding: "4px 6px" }}>Entry</th>
                      <th style={{ padding: "4px 6px" }}>Exit</th>
                      <th style={{ padding: "4px 6px" }}>P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.legs.map((l, i) => (
                      <tr key={i} style={{ borderTop: `1px solid ${C.border}` }}>
                        <td style={{ padding: "4px 6px", fontWeight: 700, color: l.action === "buy" ? C.green : C.red }}>
                          {l.action.toUpperCase()}
                        </td>
                        <td style={{ padding: "4px 6px" }}>{l.option_type === "call" ? "CE" : "PE"}</td>
                        <td style={{ padding: "4px 6px" }}>{l.strike}</td>
                        <td style={{ padding: "4px 6px" }}>{l.expiry}</td>
                        <td style={{ padding: "4px 6px" }}>{l.quantity}×{l.lot_size}</td>
                        <td style={{ padding: "4px 6px" }}>{l.entry_price != null ? `₹${fmtIN(l.entry_price, 2)}` : "—"}</td>
                        <td style={{ padding: "4px 6px" }}>{l.exit_price != null ? `₹${fmtIN(l.exit_price, 2)}` : "—"}</td>
                        <td style={{ padding: "4px 6px", color: pnlColor(l.realized_pnl), fontWeight: 600 }}>
                          {fmtPnl(l.realized_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Execution Metadata */}
            {data.execution_metadata && (
              <div style={{ marginBottom: 14 }}>
                <div style={sectionTitle}>EXECUTION METADATA</div>
                <pre style={{ fontSize: 10, color: C.muted, background: C.surface2, padding: 8, borderRadius: 6, overflowX: "auto", margin: 0 }}>
                  {JSON.stringify(data.execution_metadata, null, 2)}
                </pre>
              </div>
            )}

            {/* Annotations */}
            <div style={{ marginBottom: 14 }}>
              <div style={sectionTitle}>ANNOTATIONS</div>
              {data.tags && data.tags.length > 0 ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
                  {data.tags.map((t, i) => (
                    <span key={i} style={{ fontSize: 10, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 6px", color: C.muted }}>{t}</span>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: C.faint }}>No tags</div>
              )}
              {data.notes && (
                <div style={{ fontSize: 11, color: C.text, marginTop: 4, whiteSpace: "pre-wrap" }}>{data.notes}</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
