"use client";
import { useState, useEffect, useMemo } from "react";
import { getPaperPositions } from "@/lib/api";
import { C, fmtIN, useIsMobile } from "@/lib/ui";
import { isAuthError } from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";

function fmtExpiry(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

export default function PositionsPage() {
  const [positions, setPositions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    captureSessionFromUrl();
    getStatus()
      .then((s) => {
        if (!s.logged_in) return;
        return getPaperPositions();
      })
      .then((data) => {
        if (data) setPositions(data);
        setLoading(false);
      })
      .catch((e) => {
        if (isAuthError(e)) setError("Session expired. Log in again.");
        else setError(e.message);
        setLoading(false);
      });
  }, []);

  const openPositions = useMemo(
    () => (positions || []).filter((p) => p.status === "open"),
    [positions]
  );
  const closedPositions = useMemo(
    () => (positions || []).filter((p) => p.status === "closed"),
    [positions]
  );

  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Positions
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Current open positions and recent closures
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 48, color: C.muted, fontSize: 13 }}>
          Loading positions…
        </div>
      ) : error ? (
        <div style={{ textAlign: "center", padding: 48, color: C.red, fontSize: 13 }}>
          {error}
        </div>
      ) : openPositions.length === 0 && closedPositions.length === 0 ? (
        <div style={{ textAlign: "center", padding: 48, color: C.muted, fontSize: 13 }}>
          <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>📐</div>
          <div>No positions yet. Execute a strategy to open a position.</div>
        </div>
      ) : (
        <>
          {/* Open positions */}
          {openPositions.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: C.gold, marginBottom: 8 }}>
                Open ({openPositions.length})
              </h2>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: C.faint, fontSize: 10, letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>SYMBOL</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>EXPIRY</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>STRIKE</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>TYPE</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>QTY</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>AVG PRICE</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p, i) => (
                    <tr key={p.id || i} style={{ borderBottom: `1px solid ${C.border}` }}>
                      <td style={{ padding: "6px 10px", fontWeight: 600 }}>{p.symbol}</td>
                      <td style={{ padding: "6px 10px" }}>{fmtExpiry(p.expiry)}</td>
                      <td style={{ padding: "6px 10px", color: C.gold }}>{fmtIN(p.strike)}</td>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 5px", borderRadius: 3, background: p.option_type === "call" ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)", color: p.option_type === "call" ? C.green : C.red }}>
                          {p.option_type === "call" ? "CE" : "PE"}
                        </span>
                      </td>
                      <td style={{ padding: "6px 10px" }}>{Math.abs(p.net_quantity)}</td>
                      <td style={{ padding: "6px 10px" }}>{fmtIN(p.average_entry_price, 2)}</td>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 3, background: "rgba(76,175,125,0.15)", color: C.green }}>
                          OPEN
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Closed positions */}
          {closedPositions.length > 0 && (
            <div>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
                Closed ({closedPositions.length})
              </h2>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: C.faint, fontSize: 10, letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>SYMBOL</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>EXPIRY</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>STRIKE</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>TYPE</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>REALIZED P&L</th>
                    <th style={{ padding: "6px 10px", textAlign: "left" }}>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {closedPositions.map((p, i) => (
                    <tr key={p.id || i} style={{ borderBottom: `1px solid ${C.border}`, opacity: 0.7 }}>
                      <td style={{ padding: "6px 10px", fontWeight: 600 }}>{p.symbol}</td>
                      <td style={{ padding: "6px 10px" }}>{fmtExpiry(p.expiry)}</td>
                      <td style={{ padding: "6px 10px", color: C.gold }}>{fmtIN(p.strike)}</td>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 5px", borderRadius: 3, background: p.option_type === "call" ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)", color: p.option_type === "call" ? C.green : C.red }}>
                          {p.option_type === "call" ? "CE" : "PE"}
                        </span>
                      </td>
                      <td style={{ padding: "6px 10px", color: p.realized_pnl >= 0 ? C.green : C.red, fontWeight: 600 }}>
                        {p.realized_pnl >= 0 ? "+" : ""}{fmtIN(p.realized_pnl, 2)}
                      </td>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 3, background: "rgba(136,146,166,0.15)", color: C.muted }}>
                          CLOSED
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
