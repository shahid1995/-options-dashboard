"use client";

// Scenario Analysis panel (Phase 3) — the minimal Strategy Builder UI for the
// scenario engine in lib/calculations/scenario.js.
//
// Analytical only: it prices the strategy under hypothetical spot / IV / time /
// rate / dividend inputs. It never executes an order, never touches paper
// positions, cash or the journal, and never bypasses the market-hours gate.
//
// Live values (Live LTP) and MODELLED values (Black-Scholes scenario estimates)
// are labelled separately and never mixed: a modelled value is never shown in a
// field labelled LTP, and the live LTP is never overwritten by the model.
// Heatmap colours are a UI concern — the calculation layer returns numbers only.

import { C, fmtIN } from "@/lib/ui";

const chip = (active) => ({
  fontSize: 10.5,
  padding: "4px 9px",
  borderRadius: 6,
  cursor: "pointer",
  border: `1px solid ${active ? C.gold : C.border}`,
  background: active ? "rgba(201,161,90,0.12)" : "transparent",
  color: active ? C.gold : C.muted,
  fontWeight: active ? 700 : 400,
});
const ctrlLabel = { fontSize: 10, letterSpacing: 0.8, color: C.faint, fontWeight: 700, minWidth: 46 };
const field = { background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 6px", fontSize: 11, width: 56 };

const fmtSigned = (v, digits = 0) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`);
const fmtRupee = (v) => (v == null ? "—" : `₹${fmtIN(v)}`);
const fmtPct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const fmtNum = (v, digits = 2) => (v == null ? "—" : v.toFixed(digits));

function Summary({ label, value, color, sub }) {
  return (
    <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", minWidth: 0 }}>
      <div style={{ fontSize: 9, letterSpacing: 0.8, color: C.faint, fontWeight: 700 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 13, fontWeight: 800, color: color || C.text, marginTop: 2, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

export default function ScenarioPanel({
  result,
  matrix,
  axis,
  onAxisChange,
  spotPct,
  onSpotPct,
  ivShift,
  onIvShift,
  timeDays,
  onTimeDays,
  rate,
  onRate,
  div,
  onDiv,
  onReset,
  isMobile,
}) {
  if (!result) {
    return <div style={{ fontSize: 12, color: C.faint, padding: "40px 0", textAlign: "center" }}>Add legs to run scenario analysis.</div>;
  }

  // ---- Summary metrics from the engine result -----------------------------
  const scenarioIvs = [...new Set(result.legs.map((l) => (l.scenarioIv != null ? Number(l.scenarioIv.toFixed(4)) : null)).filter((v) => v != null))];
  const nearestT = Math.min(...result.legs.map((l) => (l.scenarioT != null ? l.scenarioT : Infinity)));
  const ivLabel = scenarioIvs.length ? scenarioIvs.map((v) => `${(v * 100).toFixed(1)}%`).join(" / ") : "—";

  // ---- Heatmap (diverging colours are a UI concern) -----------------------
  let maxAbs = 1;
  if (matrix) {
    matrix.cells.forEach((row) =>
      row.forEach((c) => {
        if (c && c.scenarioPnl != null && Math.abs(c.scenarioPnl) > maxAbs) maxAbs = Math.abs(c.scenarioPnl);
      })
    );
  }
  const cellBg = (pnl) => {
    if (pnl == null) return "rgba(136,146,166,0.06)";
    const t = Math.min(1, Math.abs(pnl) / maxAbs);
    if (Math.abs(pnl) < 0.02 * maxAbs) return "rgba(136,146,166,0.1)";
    return pnl > 0 ? `rgba(76,175,125,${(0.1 + 0.25 * t).toFixed(3)})` : `rgba(225,82,82,${(0.1 + 0.25 * t).toFixed(3)})`;
  };
  const rowLabel = (v) => (axis === "ivTime" ? `${fmtSigned(v * 100, 0)} vol` : `${fmtSigned(v * 100, 0)}%`);
  const colLabel = (v) => (axis === "spotIv" ? `${fmtSigned(v * 100, 0)} vol` : `${v}D`);
  const rowAxisName = axis === "ivTime" ? "IV shift" : "Spot move";
  const colAxisName = axis === "spotIv" ? "IV shift" : "Time forward";

  return (
    <div>
      {/* Controls */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={ctrlLabel}>SPOT</span>
          {[-0.02, -0.01, 0, 0.01, 0.02].map((p) => (
            <button key={p} onClick={() => onSpotPct(p)} style={chip(spotPct === p)}>
              {p === 0 ? "ATM" : `${p > 0 ? "+" : ""}${(p * 100).toFixed(0)}%`}
            </button>
          ))}
          <span style={{ fontSize: 11, color: C.text, fontWeight: 700, marginLeft: 6 }}>{spotPct === 0 ? "ATM" : `${fmtSigned(spotPct * 100, 1)}%`}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={ctrlLabel}>IV</span>
          {[-0.05, -0.02, 0, 0.02, 0.05].map((p) => (
            <button key={p} onClick={() => onIvShift(p)} style={chip(ivShift === p)}>
              {p === 0 ? "0" : fmtSigned(p * 100, 0)} vol
            </button>
          ))}
          <span style={{ fontSize: 11, color: C.text, fontWeight: 700, marginLeft: 6 }}>
            {ivShift === 0 ? "0 vol" : `${fmtSigned(ivShift * 100, 0)} vol`}
            <span style={{ color: C.faint, fontWeight: 400 }}> (vol points)</span>
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={ctrlLabel}>TIME</span>
          {[0, 1, 3, 5, 7].map((d) => (
            <button key={d} onClick={() => onTimeDays(d)} style={chip(timeDays === d)}>
              {d}D
            </button>
          ))}
          <span style={{ fontSize: 11, color: C.text, fontWeight: 700, marginLeft: 6 }}>{timeDays}D forward</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <label style={{ fontSize: 10.5, color: C.muted, display: "flex", alignItems: "center", gap: 5 }}>
            Rate % <input type="number" step={0.1} value={rate} onChange={(e) => onRate(Number(e.target.value) || 0)} style={field} />
          </label>
          <label style={{ fontSize: 10.5, color: C.muted, display: "flex", alignItems: "center", gap: 5 }}>
            Div % <input type="number" step={0.1} value={div} onChange={(e) => onDiv(Number(e.target.value) || 0)} style={field} />
          </label>
          <span style={{ fontSize: 10, color: C.faint }}>rate / dividend are configurable scenario inputs (defaults 0%)</span>
          <button onClick={onReset} style={{ fontSize: 10.5, color: C.gold, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer", marginLeft: "auto" }}>
            ↻ Reset Scenario
          </button>
        </div>
      </div>

      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
        <Summary label="Scenario Spot" value={result.spot != null ? fmtIN(result.spot, 2) : "—"} color={C.gold} sub="modelled underlying" />
        <Summary label="Scenario IV" value={ivLabel} color={C.gold} sub={`shift ${ivShift === 0 ? "0" : fmtSigned(ivShift * 100, 0)} vol`} />
        <Summary label="Time to Expiry" value={Number.isFinite(nearestT) ? `${Math.round(nearestT * 365)}D` : "—"} color={C.text} sub="nearest leg (year-fraction model)" />
        <Summary label="Strategy Value" value={fmtRupee(result.strategyValue)} color={C.text} sub="MODELLED · Black-Scholes" />
        <Summary
          label="P&L vs Entry"
          value={fmtRupee(result.scenarioPnl)}
          color={result.scenarioPnl == null ? C.text : result.scenarioPnl >= 0 ? C.green : C.red}
          sub={result.partial ? "partial (some legs unpriced)" : "vs original entry cost"}
        />
        <Summary
          label="Change vs Current"
          value={fmtRupee(result.scenarioChange)}
          color={result.scenarioChange == null ? C.text : result.scenarioChange >= 0 ? C.green : C.red}
          sub="MODELLED vs live LTP mark"
        />
      </div>

      {/* Modelled Greeks */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
        <Summary label="Delta (modelled)" value={fmtNum(result.totals.delta)} color={C.text} />
        <Summary label="Gamma (modelled)" value={fmtNum(result.totals.gamma, 4)} color={C.text} />
        <Summary label="Theta (modelled)" value={fmtNum(result.totals.theta)} color={C.text} />
        <Summary label="Vega (modelled)" value={fmtNum(result.totals.vega)} color={C.text} />
      </div>

      {/* Heatmap */}
      {matrix && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.6, color: C.text }}>SCENARIO P&L HEATMAP</div>
            <div style={{ display: "flex", gap: 5 }}>
              {[
                ["spotIv", "Spot × IV"],
                ["spotTime", "Spot × Time"],
                ["ivTime", "IV × Time"],
              ].map(([key, label]) => (
                <button key={key} onClick={() => onAxisChange(key)} style={chip(axis === key)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={{ padding: "4px 8px", color: C.faint, fontWeight: 700, fontSize: 10, textAlign: "left" }}>{rowAxisName} ↓ / {colAxisName} →</th>
                  {matrix.columns.map((c) => (
                    <th key={c} style={{ padding: "4px 8px", color: C.gold, fontWeight: 700, fontSize: 10, textAlign: "center" }}>
                      {colLabel(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((r, ri) => (
                  <tr key={r}>
                    <td style={{ padding: "4px 8px", color: C.muted, fontWeight: 700, fontSize: 10, whiteSpace: "nowrap" }}>{rowLabel(r)}</td>
                    {matrix.columns.map((c, ci) => {
                      const cell = matrix.cells[ri]?.[ci];
                      return (
                        <td key={c} title={cell?.scenarioPnl != null ? fmtRupee(cell.scenarioPnl) : "not priced"} style={{ background: cellBg(cell?.scenarioPnl), padding: "5px 8px", textAlign: "center", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                          {cell?.scenarioPnl != null ? `₹${fmtIN(Math.round(cell.scenarioPnl))}` : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 14, marginTop: 6, fontSize: 9.5, color: C.faint, flexWrap: "wrap" }}>
            <span><span style={{ color: C.red }}>■</span> negative P&L</span>
            <span><span style={{ color: C.green }}>■</span> positive P&L</span>
            <span><span style={{ color: C.muted }}>■</span> near zero</span>
            <span>cells are strategy P&L vs entry under combined scenario inputs</span>
          </div>
        </div>
      )}

      {/* Per-leg breakdown: LIVE vs MODELLED */}
      <div style={{ overflowX: "auto", marginBottom: 12 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
              <th style={{ padding: 5 }}>Leg</th>
              <th style={{ padding: 5 }}>Live LTP</th>
              <th style={{ padding: 5 }}>Model Value</th>
              <th style={{ padding: 5 }}>Δ vs Live</th>
              <th style={{ padding: 5 }}>P&L vs Entry</th>
              <th style={{ padding: 5 }}>Change vs Current</th>
              <th style={{ padding: 5 }}>Δ</th>
              <th style={{ padding: 5 }}>Γ</th>
              <th style={{ padding: 5 }}>Θ</th>
              <th style={{ padding: 5 }}>V</th>
            </tr>
          </thead>
          <tbody>
            {result.legs.map((l) => (
              <tr key={l.leg.id} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                <td style={{ padding: 5, whiteSpace: "nowrap" }}>
                  {l.leg.action.toUpperCase()} {fmtIN(l.leg.strike)} {l.leg.type === "call" ? "CE" : "PE"} ×{l.leg.qty}
                  <span style={{ color: C.faint }}> · {l.leg.expiry}</span>
                </td>
                <td style={{ padding: 5, color: C.green }}>{l.currentLtp != null ? l.currentLtp.toFixed(2) : "—"}</td>
                <td style={{ padding: 5 }}>{l.scenarioValue != null ? l.scenarioValue.toFixed(2) : "—"}</td>
                <td style={{ padding: 5, color: l.modelVsMarket == null ? C.muted : l.modelVsMarket >= 0 ? C.green : C.red }}>
                  {fmtSigned(l.modelVsMarket, 2)}
                </td>
                <td style={{ padding: 5, color: l.pnlVsEntry == null ? C.muted : l.pnlVsEntry >= 0 ? C.green : C.red }}>
                  {fmtRupee(l.pnlVsEntry)}
                </td>
                <td style={{ padding: 5, color: l.pnlChangeVsCurrent == null ? C.muted : l.pnlChangeVsCurrent >= 0 ? C.green : C.red }}>
                  {fmtRupee(l.pnlChangeVsCurrent)}
                </td>
                <td style={{ padding: 5 }}>{fmtNum(l.delta)}</td>
                <td style={{ padding: 5 }}>{fmtNum(l.gamma, 4)}</td>
                <td style={{ padding: 5 }}>{fmtNum(l.theta)}</td>
                <td style={{ padding: 5 }}>{fmtNum(l.vega)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 10, color: C.faint, lineHeight: 1.5, marginBottom: 8 }}>
        <span style={{ color: C.green, fontWeight: 700 }}>LIVE</span> = broker/chain LTP ·{" "}
        <span style={{ color: C.gold, fontWeight: 700 }}>MODELLED</span> = Black-Scholes estimate from scenario inputs (spot, IV, time, rate, dividend).
        Each leg uses its own expiry and its own chain IV — the model value never overwrites the live LTP, and a modelled value is never shown as LTP.
      </div>

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div style={{ background: "rgba(224,163,58,0.08)", border: "1px solid rgba(224,163,58,0.35)", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: C.gold, lineHeight: 1.5 }}>
          {result.warnings.map((w, i) => (
            <div key={i}>
              {w.code}: {w.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
