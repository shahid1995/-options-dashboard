"use client";
import { useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { C, fmtIN } from "@/lib/ui";
import {
  analyticsDisplay,
  concentration,
  equityChartData,
  hasCompletedTrades,
  journalDisplayRows,
  markedExposure,
  normalizeMarkedPosition,
  sortJournalRows,
} from "@/lib/analytics";

const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, minWidth: 0 };
const sectionTitle = { fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: C.muted, marginBottom: 8 };
const dash = (v) => (v == null || Number.isNaN(v) ? "—" : v);

function Metric({ label, value, color = C.text, hint }) {
  return (
    <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", minWidth: 0 }}>
      <div style={{ fontSize: 9.5, color: C.faint, letterSpacing: 0.6, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color, marginTop: 2, whiteSpace: "nowrap" }}>{dash(value)}</div>
      {hint && <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>{hint}</div>}
    </div>
  );
}

const pnlColor = (v) => (v == null ? C.muted : v >= 0 ? C.green : C.red);
const fmtPnl = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v))}`);
const fmtPct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);

export default function PortfolioAnalyticsPanel({ analytics, positionsWithLtp, loading, error }) {
  const [journalSort, setJournalSort] = useState("date");

  const d = useMemo(() => analyticsDisplay(analytics), [analytics]);
  const { summary, performance, drawdown, strategies } = d;
  const curve = useMemo(() => equityChartData(analytics?.equity_curve), [analytics]);
  const rows = useMemo(() => journalDisplayRows(analytics), [analytics]);
  const sortedRows = useMemo(() => sortJournalRows(rows, journalSort), [rows, journalSort]);
  const hasTrades = hasCompletedTrades(analytics);

  const marked = useMemo(() => (positionsWithLtp ?? []).map(normalizeMarkedPosition), [positionsWithLtp]);
  const conc = useMemo(() => concentration(marked), [marked]);
  const exposure = useMemo(() => markedExposure(marked), [marked]);
  const marksAvailable = marked.some((p) => p.currentLtp != null);

  if (loading && !analytics) {
    return (
      <div style={panel}>
        <div style={sectionTitle}>📊 PORTFOLIO ANALYTICS</div>
        <div style={{ fontSize: 11.5, color: C.faint }}>Loading analytics…</div>
      </div>
    );
  }

  const dq = d.dataQuality ?? {};
  const dqChips = [
    ["Realized equity", "available", C.green],
    ["Historical unrealized", dq.historical_unrealized ?? "unavailable", C.faint],
    ["Live marks", dq.current_marks ?? "unavailable", C.faint],
    ["Completed trades", dq.completed_trades === "available" ? "available" : "none", dq.completed_trades === "available" ? C.gold : C.faint],
  ];

  return (
    <div style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: 0.8, color: C.text }}>📊 PORTFOLIO ANALYTICS</div>
          {dqChips.map(([label, value, color]) => (
            <span
              key={label}
              title={`${label}: ${value}`}
              style={{ fontSize: 9, fontWeight: 700, letterSpacing: 0.4, color, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "2px 8px" }}
            >
              {label.toUpperCase()} · {String(value).toUpperCase()}
            </span>
          ))}
        </div>
        {error && <div style={{ fontSize: 10.5, color: C.gold }}>⚠️ {error}</div>}
      </div>

      {/* Portfolio summary */}
      <div style={sectionTitle}>Portfolio summary</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 14 }}>
        <Metric label="Starting capital" value={`₹${fmtIN(summary.startingCapital ?? 0)}`} />
        <Metric label="Available cash" value={summary.availableCash == null ? "—" : `₹${fmtIN(summary.availableCash)}`} />
        <Metric label="Open exposure" value={`₹${fmtIN(summary.investedValue ?? 0)}`} hint="entry value · not margin" />
        <Metric label="Realized P&L" value={fmtPnl(summary.realizedPnl)} color={pnlColor(summary.realizedPnl)} />
        <Metric
          label="Unrealized P&L"
          value={summary.unrealizedPnl == null ? "Unavailable" : fmtPnl(summary.unrealizedPnl)}
          color={summary.unrealizedPnl == null ? C.faint : pnlColor(summary.unrealizedPnl)}
          hint={summary.unrealizedPnl == null ? "needs a market mark" : undefined}
        />
        <Metric label="Total P&L" value={fmtPnl(summary.totalPnl)} color={pnlColor(summary.totalPnl)} />
        <Metric label="Return" value={summary.returnPct == null ? "—" : fmtPct(summary.returnPct)} color={pnlColor(summary.returnPct)} />
      </div>

      {/* Performance */}
      <div style={sectionTitle}>Performance · completed trades</div>
      {!hasTrades ? (
        <div style={{ fontSize: 11.5, color: C.faint, padding: "10px 0 12px" }}>
          No completed trades yet — win rate and the metrics below stay empty until a strategy is fully exited.
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 8 }}>
            <Metric label="Trades" value={performance.totalCompletedTrades} hint={`${performance.winningTrades}W · ${performance.losingTrades}L · ${performance.breakevenTrades}B`} />
            <Metric label="Win rate" value={performance.winRate == null ? "—" : `${performance.winRate.toFixed(1)}%`} color={C.gold} />
            <Metric label="Avg winner" value={fmtPnl(performance.averageWinner)} color={C.green} />
            <Metric label="Avg loser" value={fmtPnl(performance.averageLoser)} color={C.red} />
            <Metric label="Profit factor" value={performance.profitFactor == null ? "—" : performance.profitFactor.toFixed(2)} />
            <Metric label="Expectancy" value={fmtPnl(performance.expectancy)} color={pnlColor(performance.expectancy)} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 8 }}>
            <Metric label="Largest win" value={fmtPnl(performance.largestWinner)} color={C.green} />
            <Metric label="Largest loss" value={fmtPnl(performance.largestLoser)} color={C.red} />
            <Metric label="Win streak" value={`${performance.currentWinStreak} now · ${performance.maxWinStreak} max`} />
            <Metric label="Loss streak" value={`${performance.currentLossStreak} now · ${performance.maxLossStreak} max`} />
            <Metric label="Avg duration" value={performance.averageHoldingDuration ?? "—"} hint={`median ${performance.medianHoldingDuration ?? "—"}`} />
          </div>
        </>
      )}

      {/* Drawdown + realized equity curve */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8, marginBottom: 14 }}>
        <Metric label="Current drawdown" value={fmtPnl(drawdown.currentDrawdown)} color={drawdown.currentDrawdown != null && drawdown.currentDrawdown < 0 ? C.red : C.muted} hint={fmtPct(drawdown.currentDrawdownPct)} />
        <Metric label="Max drawdown" value={fmtPnl(drawdown.maxDrawdown)} color={drawdown.maxDrawdown != null && drawdown.maxDrawdown < 0 ? C.red : C.muted} hint={fmtPct(drawdown.maxDrawdownPct)} />
      </div>

      <div style={{ ...sectionTitle, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Realized equity curve</span>
        <span style={{ fontSize: 9, fontWeight: 600, color: C.faint, letterSpacing: 0.4 }}>
          EQUITY = STARTING CAPITAL + CUMULATIVE REALIZED P&L · NO HISTORICAL MARKS
        </span>
      </div>
      {curve.length <= 1 ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 150, fontSize: 11.5, color: C.faint, textAlign: "center", padding: "0 20px" }}>
          The realized equity curve plots each fully-exited strategy. It stays empty until at least one trade completes.
        </div>
      ) : (
        <div style={{ height: 170 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve}>
              <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke={C.faint} fontSize={10} tickFormatter={(v) => v.slice(5)} />
              <YAxis stroke={C.faint} fontSize={10} domain={["auto", "auto"]} tickFormatter={(v) => `₹${fmtIN(v)}`} width={72} />
              <ReferenceLine y={summary.startingCapital ?? 0} stroke={C.faint} strokeDasharray="4 2" />
              <Tooltip
                contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11 }}
                labelFormatter={(v) => v}
                formatter={(v, name) => [name === "equity" ? `₹${fmtIN(v)}` : v, name === "equity" ? "Equity" : "Cumulative P&L"]}
              />
              <Line type="monotone" dataKey="equity" stroke={C.gold} strokeWidth={2} dot={{ r: 2 }} name="equity" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Strategy performance */}
      <div style={{ ...sectionTitle, marginTop: 14 }}>Strategy performance</div>
      {strategies.length === 0 ? (
        <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0 10px" }}>No strategy groups yet.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                <th style={{ padding: "5px 6px" }}>Strategy</th>
                <th style={{ padding: "5px 6px" }}>Trades</th>
                <th style={{ padding: "5px 6px" }}>Win rate</th>
                <th style={{ padding: "5px 6px" }}>P&L</th>
                <th style={{ padding: "5px 6px" }}>Avg P&L</th>
                <th style={{ padding: "5px 6px" }}>Profit factor</th>
                <th style={{ padding: "5px 6px" }}>Expectancy</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s.strategy} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: "5px 6px", fontWeight: 700 }}>{s.strategy}</td>
                  <td style={{ padding: "5px 6px" }}>{s.trades} ({s.wins}W/{s.losses}L)</td>
                  <td style={{ padding: "5px 6px", color: s.win_rate == null ? C.faint : C.gold }}>{s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%`}</td>
                  <td style={{ padding: "5px 6px", color: pnlColor(s.total_pnl) }}>{fmtPnl(s.total_pnl)}</td>
                  <td style={{ padding: "5px 6px", color: pnlColor(s.average_pnl) }}>{fmtPnl(s.average_pnl)}</td>
                  <td style={{ padding: "5px 6px" }}>{s.profit_factor == null ? "—" : s.profit_factor.toFixed(2)}</td>
                  <td style={{ padding: "5px 6px", color: pnlColor(s.expectancy) }}>{s.expectancy == null ? "—" : fmtPnl(s.expectancy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Position exposure + concentration (mark-based) */}
      <div style={{ ...sectionTitle, marginTop: 14 }}>Position exposure & concentration</div>
      {!marksAvailable ? (
        <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0 10px" }}>
          Market value and concentration need live marks from the option chain. {positionsWithLtp?.length ? "Load a chain to see them." : "No open positions."}
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 8 }}>
            <Metric label="Long exposure" value={`₹${fmtIN(exposure.longExposure ?? 0)}`} color={C.green} hint="mark value · not margin" />
            <Metric label="Short exposure" value={`₹${fmtIN(exposure.shortExposure ?? 0)}`} color={C.red} hint="mark value · not margin" />
            <Metric label="Total exposure" value={`₹${fmtIN(exposure.totalExposure ?? 0)}`} color={C.gold} />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {conc.items.map((i) => (
              <span key={i.key} style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>
                {i.key} · {i.concentrationPct == null ? "—" : `${i.concentrationPct.toFixed(1)}%`}
              </span>
            ))}
          </div>
        </>
      )}

      {/* Journal: completed strategy trades, grouped */}
      <div style={{ ...sectionTitle, marginTop: 14, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
        <span>Journal · completed strategy trades</span>
        <select
          value={journalSort}
          onChange={(e) => setJournalSort(e.target.value)}
          style={{ fontSize: 10, color: C.text, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: "3px 6px" }}
          aria-label="Sort journal"
        >
          <option value="date">Sort: newest first</option>
          <option value="pnl">Sort: P&L</option>
          <option value="duration">Sort: duration</option>
        </select>
      </div>
      {sortedRows.length === 0 ? (
        <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0 10px" }}>No completed trades. Fully exit a strategy and it appears here as one trade (legs grouped underneath).</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                <th style={{ padding: "5px 6px" }}>Date</th>
                <th style={{ padding: "5px 6px" }}>Strategy</th>
                <th style={{ padding: "5px 6px" }}>Entry / Exit</th>
                <th style={{ padding: "5px 6px" }}>Duration</th>
                <th style={{ padding: "5px 6px" }}>P&L</th>
                <th style={{ padding: "5px 6px" }}>Result</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r) => (
                <tr key={r.executionId} className="paper-row" style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}>
                  <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>{r.exitLabel}</td>
                  <td style={{ padding: "5px 6px", fontWeight: 700 }}>{r.strategy}</td>
                  <td style={{ padding: "5px 6px", fontSize: 10, color: C.muted }}>
                    <div>{r.entryLabel} → {r.exitLabel}</div>
                    <div style={{ marginTop: 2 }}>{r.legs.slice(0, 2).map((l) => l.label).join(" / ")}</div>
                  </td>
                  <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>{r.durationLabel ?? "—"}</td>
                  <td style={{ padding: "5px 6px", fontWeight: 700, color: pnlColor(r.realizedPnl) }}>{fmtPnl(r.realizedPnl)}</td>
                  <td style={{ padding: "5px 6px" }}>
                    <span style={{ fontSize: 9.5, fontWeight: 700, color: r.resultColor, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "2px 8px" }}>
                      {r.result}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(dq.warnings ?? []).length > 0 && (
        <div style={{ marginTop: 12, fontSize: 10.5, color: C.gold, lineHeight: 1.5 }}>
          ⚠️ {dq.warnings.map((w) => w.code).join(", ")} — the backend reconciliation found discrepancies. Data is shown as stored; nothing was silently corrected.
        </div>
      )}
    </div>
  );
}
