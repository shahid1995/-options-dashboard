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
import { capitalDisplay, capitalStrategyRows } from "@/lib/capital";
import { calculateCapitalEfficiencySet, calculatePremiumRoi } from "@/lib/calculations/capitalEfficiency";
// Phase 6.4: portfolio capital allocation & risk controls (MONITORING ONLY).
import { openStrategyGroups } from "@/lib/portfolio";
import { calculateStrategy } from "@/lib/calculations/strategyCalculator";
import { analyzeCapital } from "@/lib/calculations/analyticalCapital";
import {
  calculatePortfolioRiskControls,
  calculateStrategyAllocation,
} from "@/lib/calculations/capitalAllocation";
import { updateTradeAnnotations, getStrategyDetail } from "@/lib/api";
import TradeDetailModal from "./TradeDetailModal";

const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, minWidth: 0 };
const sectionTitle = { fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: C.muted, marginBottom: 8 };
const dash = (v) => (v == null || Number.isNaN(v) ? "—" : v);

// Phase 6.4 — data-quality badges are neutral status chips (§20/§37), never
// traffic-light trading signals; unavailable values render N/A, never 0.
const ALLOC_STATUS_COLORS = { AVAILABLE: C.green, PARTIAL: C.gold, UNAVAILABLE: C.faint };
const ALLOC_WARNING_LABELS = {
  UNLIMITED_RISK: "Unlimited-risk strategy present",
  MIXED_EXPIRY_APPROXIMATION: "Mixed-expiry structure · defined risk unavailable",
  PARTIAL_COVERAGE: "Partial coverage · some values unavailable",
  BROKER_MARGIN_NOT_ADDITIVE: "Per-strategy broker margins are never summed",
  BROKER_MARGIN_AGGREGATE_USED: "Broker margin is the broker-reported aggregate",
  NO_OPEN_STRATEGIES: "No open strategies",
  INVALID_DENOMINATOR: "Invalid allocation denominator",
  MISSING_DENOMINATOR: "Allocation denominator unavailable",
};
const ALLOC_BASIS_LABELS = {
  PREMIUM: "Premium basis",
  RISK_MODEL: "Risk basis · defined loss",
  MAX_LOSS: "Max-loss basis",
  UNAVAILABLE: "Basis unavailable",
};

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
// Phase 5.2.1: financial values always display with two decimals (₹3,169.00).
const fmtPnl = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v), 2)}`);
const fmtPct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);

export default function PortfolioAnalyticsPanel({ analytics, positionsWithLtp, capital, loading, error }) {
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

  // Phase 7.0: trade annotation editing state
  const [editingAnnotations, setEditingAnnotations] = useState(null);
  const [annotationDraft, setAnnotationDraft] = useState({ tags: "", notes: "" });
  const [annotationSaving, setAnnotationSaving] = useState(false);
  const [annotationFeedback, setAnnotationFeedback] = useState(null);

  // Phase 7.1: trade detail + strategy drill-down state
  const [tradeDetailId, setTradeDetailId] = useState(null);
  const [strategyDrilldown, setStrategyDrilldown] = useState(null); // strategy name or null
  const [strategyDetail, setStrategyDetail] = useState(null);
  const [strategyDetailLoading, setStrategyDetailLoading] = useState(false);
  const [strategyDetailError, setStrategyDetailError] = useState(null);

  const openStrategyDrilldown = async (strategyName) => {
    setStrategyDrilldown(strategyName);
    setStrategyDetailLoading(true);
    setStrategyDetailError(null);
    try {
      const detail = await getStrategyDetail(strategyName);
      setStrategyDetail(detail);
    } catch (e) {
      setStrategyDetailError(e?.response?.data?.detail || "Failed to load strategy");
    } finally {
      setStrategyDetailLoading(false);
    }
  };

  const closeStrategyDrilldown = () => {
    setStrategyDrilldown(null);
    setStrategyDetail(null);
    setStrategyDetailError(null);
  };

  const saveAnnotations = async () => {
    if (!editingAnnotations) return;
    setAnnotationSaving(true);
    setAnnotationFeedback(null);
    try {
      const tags = annotationDraft.tags.split(",").map((t) => t.trim()).filter(Boolean);
      await updateTradeAnnotations(editingAnnotations.executionId, { tags, notes: annotationDraft.notes || null });
      setAnnotationFeedback({ type: "success", message: "Saved" });
      setTimeout(() => setEditingAnnotations(null), 600);
      // Trigger a reload by dispatching a custom event — the parent page will handle it
      window.dispatchEvent(new CustomEvent("annotations-updated"));
    } catch (e) {
      setAnnotationFeedback({ type: "error", message: e?.response?.data?.detail || "Save failed" });
    } finally {
      setAnnotationSaving(false);
    }
  };
  const marksAvailable = marked.some((p) => p.currentLtp != null);

  // Phase 6.3: capital-efficiency metrics (portfolio level, since inception).
  // Every metric carries its explicit denominator/source; broker margin is
  // used only when BROKER_REPORTED and available — never estimated, never
  // paper cash, never an invented aggregate (§15/§25/§28).
  const capD = useMemo(() => capitalDisplay(capital), [capital]);
  const ce = useMemo(
    () =>
      calculateCapitalEfficiencySet({
        pnl: summary.realizedPnl,
        pnlType: "REALIZED",
        period: "inception",
        capitalPeriod: "inception",
        premiumOutlay: capD.premiumOutlay.value,
        estimatedCapital: { value: capD.estimatedCapital.value, source: capD.estimatedCapital.source, basis: capD.estimatedCapitalBasis },
        brokerMargin: { value: capD.brokerMargin.value, source: capD.brokerMargin.source, status: capD.brokerMargin.status },
        maxLoss: null,
        maxLossUnlimited: false,
      }),
    [summary.realizedPnl, capD]
  );
  // §29: per-journal-row Premium ROI — premium outlay derived from the row's
  // own buy-leg fills (fill_price × qty × lot_size), the only journal-level
  // denominator genuinely available; other denominators stay N/A.
  const journalRoi = useMemo(() => {
    const map = new Map();
    for (const row of analytics?.journal ?? []) {
      const outlay = (row.legs ?? []).reduce(
        (s, l) => (l.action === "buy" ? s + Number(l.fill_price ?? 0) * Number(l.quantity ?? 0) * Number(l.lot_size ?? 0) : s),
        0
      );
      map.set(row.execution_id, calculatePremiumRoi({ pnl: row.realized_pnl, premiumOutlay: outlay }));
    }
    return map;
  }, [analytics]);

  // Phase 6.4 — CAPITAL ALLOCATION & RISK (MONITORING ONLY). Built from the
  // server-authoritative OPEN positions (CURRENT remaining quantity, §26),
  // the Phase 6.2 analytical capital result per open strategy (§6 — never
  // recomputed), and broker margin ONLY as BROKER_REPORTED (§7/§10 — the
  // account aggregate is preferred; per-strategy rows are never summed).
  // Limits default to DISABLED until explicitly configured (§21).
  const allocationView = useMemo(() => {
    const groups = openStrategyGroups(positionsWithLtp ?? []);
    const brokerByExecution = new Map(capitalStrategyRows(capD.strategies).map((r) => [r.executionId, r]));
    const strategies = groups.map((g) => {
      const legs = g.positions.map((p) => ({
        action: p.action,
        type: p.type,
        strike: p.strike,
        expiry: p.expiry,
        symbol: p.symbol,
        qty: p.qty,
        price: p.entryPremium,
        lotSize: p.lotSize,
      }));
      const lotSize = g.positions[0]?.lotSize ?? 1;
      const multiplier = 1;
      let calc = null;
      try {
        calc = calculateStrategy(legs, { lotSize, multiplier });
      } catch {
        calc = null;
      }
      const brokerRow = brokerByExecution.get(g.executionId);
      const brokerMargin = brokerRow?.brokerMarginStatus === "available" ? brokerRow.brokerMargin : null;
      return calculateStrategyAllocation({
        executionId: g.executionId,
        strategyTag: g.strategyName,
        positions: g.positions,
        legs,
        estimatedCapital: analyzeCapital(legs, { lotSize, multiplier }),
        maxLoss: calc?.maxLoss ?? null,
        maxLossUnlimited: calc?.maxLossUnlimited === true,
        payoffMode: calc?.payoffMode ?? "same-expiry",
        brokerMargin,
        brokerMarginSource: brokerMargin == null ? null : "BROKER_REPORTED",
        premiumOutlay: null,
      });
    });
    const paperStarting = capD.paperStartingCapital.value;
    const paperAvailable = capD.paperAvailableCash.value;
    const brokerAgg = capD.brokerMargin.source === "BROKER_REPORTED" ? capD.brokerMargin.value : null;
    const brokerFunds = capD.brokerAvailableFunds.source === "BROKER_REPORTED" ? capD.brokerAvailableFunds.value : null;
    return calculatePortfolioRiskControls({
      strategies,
      paperStartingCapital: paperStarting,
      paperAvailableCash: paperAvailable,
      brokerAvailableFunds: brokerFunds,
      brokerMarginAggregate: brokerAgg,
      brokerMarginSource: brokerAgg == null ? null : "BROKER_REPORTED",
      limits: {}, // Phase 6.4: limits disabled until explicitly configured
    });
  }, [positionsWithLtp, capD]);

  const hasOpenPositions = (positionsWithLtp ?? []).length > 0;
  // Allocation-table rows enriched with each strategy's capital/risk share.
  const allocRows = useMemo(() => {
    const capPct = new Map((allocationView.concentration?.byStrategy?.items ?? []).map((i) => [i.key, i.concentrationPct]));
    const riskPct = new Map((allocationView.concentration?.byRisk?.items ?? []).map((i) => [i.key, i.concentrationPct]));
    return (allocationView.allocation?.strategies ?? []).map((s) => {
      const key = s.executionId ?? "standalone";
      return { ...s, capitalPct: capPct.get(key) ?? null, riskPct: riskPct.get(key) ?? null };
    });
  }, [allocationView]);
  const allocWarnings = (allocationView.warnings ?? []).map((w) => ALLOC_WARNING_LABELS[w] ?? w);

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
        <Metric label="Starting capital" value={`₹${fmtIN(summary.startingCapital ?? 0, 2)}`} />
        <Metric label="Available cash" value={summary.availableCash == null ? "—" : `₹${fmtIN(summary.availableCash, 2)}`} />
        <Metric label="Open exposure" value={`₹${fmtIN(summary.investedValue ?? 0, 2)}`} hint="entry value · not margin" />
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

      {/* Phase 6.3: capital efficiency — denominators explicit, never hidden */}
      <div style={sectionTitle}>Capital efficiency · since inception</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 14 }}>
        <Metric
          label="Premium ROI"
          value={ce.premiumRoi.value == null ? "N/A" : fmtPct(ce.premiumRoi.value)}
          color={ce.premiumRoi.value == null ? C.faint : pnlColor(ce.premiumRoi.value)}
          hint={ce.premiumRoi.value == null ? "N/A — premium outlay unavailable" : `return on premium outlay · ₹${fmtIN(ce.premiumRoi.denominator, 2)}`}
        />
        <Metric
          label="Return on Capital"
          value={ce.returnOnCapital.value == null ? "N/A" : fmtPct(ce.returnOnCapital.value)}
          color={ce.returnOnCapital.value == null ? C.faint : pnlColor(ce.returnOnCapital.value)}
          hint={ce.returnOnCapital.value == null ? "N/A — estimated capital unavailable" : `return on estimated capital · ₹${fmtIN(ce.returnOnCapital.denominator, 2)} · ${String(ce.returnOnCapital.basis ?? "").toUpperCase()}`}
        />
        <Metric
          label="Return on Margin"
          value={ce.returnOnMargin.value == null ? "N/A" : fmtPct(ce.returnOnMargin.value)}
          color={ce.returnOnMargin.value == null ? C.faint : pnlColor(ce.returnOnMargin.value)}
          hint={ce.returnOnMargin.value == null ? "N/A — broker margin unavailable" : `return on broker-reported margin · ₹${fmtIN(ce.returnOnMargin.denominator, 2)}`}
        />
        <Metric label="Return on Risk Capital" value="N/A" color={C.faint} hint="per-strategy defined max loss is shown below in CAPITAL ALLOCATION & RISK" />
      </div>

      {/* Phase 6.4: capital allocation & risk (monitoring only) */}
      <div style={{ ...sectionTitle, marginTop: 14, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
        <span>Capital allocation &amp; risk · open strategies</span>
        {hasOpenPositions && (
          <span
            title="Data-quality state — monitoring only, never a trading signal"
            style={{ fontSize: 9, fontWeight: 700, letterSpacing: 0.6, color: ALLOC_STATUS_COLORS[allocationView.status] ?? C.faint, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "2px 8px" }}
          >
            {allocationView.status}
          </span>
        )}
      </div>
      {!hasOpenPositions ? (
        <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0 10px" }}>
          No open positions — capital allocation and portfolio risk are computed from currently open positions only.
        </div>
      ) : (
        <>
          {/* §20 summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 8, marginBottom: 8 }}>
            <Metric label="Paper Capital" value={`₹${fmtIN(allocationView.allocation.paperStartingCapital ?? 0, 2)}`} hint="paper starting capital" />
            <Metric
              label="Allocated Capital"
              value={allocationView.allocation.totalEstimatedCapital == null ? "N/A" : `₹${fmtIN(allocationView.allocation.totalEstimatedCapital, 2)}`}
              color={allocationView.allocation.totalEstimatedCapital == null ? C.faint : C.gold}
              hint="estimated capital · analytical"
            />
            <Metric label="Remaining Cash" value={allocationView.allocation.paperAvailableCash == null ? "N/A" : `₹${fmtIN(allocationView.allocation.paperAvailableCash, 2)}`} hint="paper available cash" />
            <Metric
              label="Broker Margin"
              value={allocationView.allocation.brokerMargin == null ? "Unavailable" : `₹${fmtIN(allocationView.allocation.brokerMargin, 2)}`}
              color={allocationView.allocation.brokerMargin == null ? C.faint : C.gold}
              hint="broker-reported aggregate · never summed per strategy"
            />
            <Metric label="Defined Risk" value={allocationView.allocation.totalDefinedRisk == null ? "N/A" : `₹${fmtIN(allocationView.allocation.totalDefinedRisk, 2)}`} hint="finite open risk · same-expiry only" />
            <Metric label="Unlimited-Risk" value={allocationView.unlimitedRiskStrategyCount ?? 0} hint="open strategies with open-ended risk" />
            <Metric
              label="Cap. Concentration"
              value={allocationView.concentration.byStrategy.highest?.concentrationPct == null ? "N/A" : `${allocationView.concentration.byStrategy.highest.concentrationPct.toFixed(1)}%`}
              hint="highest estimated-capital share · descriptive"
            />
            <Metric
              label="Risk Concentration"
              value={allocationView.concentration.byRisk.highest?.concentrationPct == null ? "N/A" : `${allocationView.concentration.byRisk.highest.concentrationPct.toFixed(1)}%`}
              hint="highest defined-risk share · descriptive"
            />
          </div>

          {/* §19 allocation table — one logical unit per open strategy execution */}
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.7, color: C.muted, margin: "6px 0 6px" }}>ALLOCATION BY STRATEGY</div>
          {allocRows.length === 0 ? (
            <div style={{ fontSize: 11.5, color: C.faint, padding: "4px 0 8px" }}>No open strategy executions.</div>
          ) : (
            <div style={{ overflowX: "auto", marginBottom: 10 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                <thead>
                  <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                    <th style={{ padding: "5px 6px" }}>Strategy</th>
                    <th style={{ padding: "5px 6px" }}>Open Legs</th>
                    <th style={{ padding: "5px 6px" }}>Estimated Capital</th>
                    <th style={{ padding: "5px 6px" }}>Broker Margin</th>
                    <th style={{ padding: "5px 6px" }}>Defined Risk</th>
                    <th style={{ padding: "5px 6px" }}>Capital %</th>
                    <th style={{ padding: "5px 6px" }}>Risk %</th>
                  </tr>
                </thead>
                <tbody>
                  {allocRows.map((s) => (
                    <tr key={s.executionId ?? "standalone"} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                      <td style={{ padding: "5px 6px", fontWeight: 700 }}>{s.strategyTag}</td>
                      <td style={{ padding: "5px 6px" }}>{s.openPositions}</td>
                      <td style={{ padding: "5px 6px", color: s.estimatedCapital == null ? C.faint : C.text }}>
                        {s.estimatedCapital == null ? "N/A" : `₹${fmtIN(s.estimatedCapital, 2)}`}
                        {s.estimatedCapital != null && <div style={{ fontSize: 9, color: C.faint }}>{ALLOC_BASIS_LABELS[s.capitalBasis] ?? s.capitalBasis}</div>}
                      </td>
                      <td style={{ padding: "5px 6px", color: s.brokerMargin == null ? C.faint : C.text }}>{s.brokerMargin == null ? "N/A" : `₹${fmtIN(s.brokerMargin, 2)}`}</td>
                      <td style={{ padding: "5px 6px" }}>
                        {s.unlimitedRisk ? (
                          <span title="Open-ended risk — never converted to a fabricated rupee figure" style={{ fontSize: 9.5, fontWeight: 700, color: C.gold }}>UNLIMITED RISK</span>
                        ) : s.definedRisk == null ? (
                          <span style={{ color: C.faint }}>N/A</span>
                        ) : (
                          `₹${fmtIN(s.definedRisk, 2)}`
                        )}
                      </td>
                      <td style={{ padding: "5px 6px", color: s.capitalPct == null ? C.faint : C.text }}>{s.capitalPct == null ? "N/A" : `${s.capitalPct.toFixed(1)}%`}</td>
                      <td style={{ padding: "5px 6px", color: s.riskPct == null ? C.faint : C.text }}>{s.riskPct == null ? "N/A" : `${s.riskPct.toFixed(1)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* §13/§16/§17 concentration — descriptive, never directional */}
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.7, color: C.muted, margin: "6px 0 6px" }}>CONCENTRATION · DESCRIPTIVE</div>
          {[
            ["By strategy · estimated capital", allocationView.concentration.byStrategy.items],
            ["By underlying", allocationView.concentration.byUnderlying.items],
            ["By expiry", allocationView.concentration.byExpiry.items],
          ].map(([label, items]) => (
            <div key={label} style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 9.5, color: C.faint, marginBottom: 3 }}>{label}</div>
              {items.length === 0 ? (
                <span style={{ fontSize: 10, color: C.faint }}>—</span>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {items.map((i) => (
                    <span key={`${label}-${i.key}`} style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>
                      {i.key} · {i.concentrationPct == null ? "—" : `${i.concentrationPct.toFixed(1)}%`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* §21–§24 control limits — monitoring only, defaults disabled */}
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.7, color: C.muted, margin: "6px 0 6px" }}>CONTROL LIMITS · MONITORING ONLY</div>
          <div style={{ fontSize: 10.5, color: C.faint, lineHeight: 1.5 }}>
            Limits are disabled until explicitly configured. Phase 6.4 never blocks paper execution — limits are control visibility only.
          </div>

          {/* §18 exposure — neutral measurement, never bullish/bearish */}
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.7, color: C.muted, margin: "8px 0 6px" }}>EXPOSURE · CONTRACTS</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <span style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>BUY {allocationView.exposure.buyExposure}</span>
            <span style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>SELL {allocationView.exposure.sellExposure}</span>
            <span style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>CALL {allocationView.exposure.callExposure}</span>
            <span style={{ fontSize: 10, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 9px" }}>PUT {allocationView.exposure.putExposure}</span>
          </div>

          {allocWarnings.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 10, color: C.gold, lineHeight: 1.5 }}>
              ⚠️ {allocWarnings.join(" · ")}
            </div>
          )}
        </>
      )}

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
              <YAxis stroke={C.faint} fontSize={10} domain={["auto", "auto"]} tickFormatter={(v) => `₹${fmtIN(v, 2)}`} width={72} />
              <ReferenceLine y={summary.startingCapital ?? 0} stroke={C.faint} strokeDasharray="4 2" />
              <Tooltip
                contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11 }}
                labelFormatter={(v) => v}
                formatter={(v, name) => [name === "equity" ? `₹${fmtIN(v, 2)}` : v, name === "equity" ? "Equity" : "Cumulative P&L"]}
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
                  <td style={{ padding: "5px 6px", fontWeight: 700 }}>
                    <button
                      onClick={() => openStrategyDrilldown(s.strategy)}
                      style={{ background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: 11.5, fontWeight: 700, padding: 0, textAlign: "left" }}
                    >
                      {s.strategy}
                    </button>
                  </td>
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
            <Metric label="Long exposure" value={`₹${fmtIN(exposure.longExposure ?? 0, 2)}`} color={C.green} hint="mark value · not margin" />
            <Metric label="Short exposure" value={`₹${fmtIN(exposure.shortExposure ?? 0, 2)}`} color={C.red} hint="mark value · not margin" />
            <Metric label="Total exposure" value={`₹${fmtIN(exposure.totalExposure ?? 0, 2)}`} color={C.gold} />
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
                <th style={{ padding: "5px 6px" }}>Premium ROI</th>
                <th style={{ padding: "5px 6px" }}>Result</th>
                <th style={{ padding: "5px 6px" }}>Tags / Notes</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r) => {
                const premRoi = journalRoi.get(r.executionId);
                return (
                  <tr key={r.executionId} className="paper-row" style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}>
                    <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>{r.exitLabel}</td>
                    <td style={{ padding: "5px 6px", fontWeight: 700 }}>
                      <button
                        onClick={() => setTradeDetailId(r.executionId)}
                        style={{ background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: 11.5, fontWeight: 700, padding: 0, textAlign: "left" }}
                      >
                        {r.strategy}
                      </button>
                    </td>
                    <td style={{ padding: "5px 6px", fontSize: 10, color: C.muted }}>
                      <div>{r.entryLabel} → {r.exitLabel}</div>
                      <div style={{ marginTop: 2 }}>{r.legs.slice(0, 2).map((l) => l.label).join(" / ")}</div>
                    </td>
                    <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>{r.durationLabel ?? "—"}</td>
                    <td style={{ padding: "5px 6px", fontWeight: 700, color: pnlColor(r.realizedPnl) }}>{fmtPnl(r.realizedPnl)}</td>
                    <td style={{ padding: "5px 6px", fontSize: 10.5 }}>
                      {premRoi && premRoi.value != null ? (
                        <span title={`return on premium outlay · ₹${fmtIN(premRoi.denominator, 2)}`} style={{ fontWeight: 700, color: pnlColor(premRoi.value) }}>
                          {fmtPct(premRoi.value)}
                        </span>
                      ) : (
                        <span style={{ color: C.faint }}>N/A</span>
                      )}
                    </td>
                    <td style={{ padding: "5px 6px" }}>
                      <span style={{ fontSize: 9.5, fontWeight: 700, color: r.resultColor, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "2px 8px" }}>
                        {r.result}
                      </span>
                    </td>
                    <td style={{ padding: "5px 6px", fontSize: 10 }}>
                      {r.tags && r.tags.length > 0 ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                          {r.tags.map((t, i) => (
                            <span key={i} style={{ fontSize: 9, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 4, padding: "1px 5px", color: C.muted }}>{t}</span>
                          ))}
                        </div>
                      ) : r.notes ? (
                        <span style={{ color: C.faint, fontStyle: "italic" }} title={r.notes}>📝</span>
                      ) : (
                        <span style={{ color: C.faint }}>—</span>
                      )}
                      <button
                        onClick={() => {
                          setEditingAnnotations({ executionId: r.executionId, tags: r.tags, notes: r.notes });
                          setAnnotationDraft({ tags: (r.tags ?? []).join(", "), notes: r.notes ?? "" });
                          setAnnotationFeedback(null);
                        }}
                        style={{ fontSize: 9, color: C.accent, background: "none", border: "none", cursor: "pointer", padding: "2px 4px", marginTop: 2 }}
                      >
                        edit
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(dq.warnings ?? []).length > 0 && (
        <div style={{ marginTop: 12, fontSize: 10.5, color: C.gold, lineHeight: 1.5 }}>
          ⚠️ {dq.warnings.map((w) => w.code).join(", ")} — the backend reconciliation found discrepancies. Data is shown as stored; nothing was silently corrected.
        </div>
      )}

      {/* Phase 7.0: Annotation edit modal */}
      {editingAnnotations && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999 }} onClick={() => setEditingAnnotations(null)}>
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20, width: 380, maxWidth: "90vw" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Trade Annotations</div>
            <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>Tags (comma-separated)</label>
            <input
              value={annotationDraft.tags}
              onChange={(e) => setAnnotationDraft((d) => ({ ...d, tags: e.target.value }))}
              placeholder="e.g. earnings, high-conviction"
              style={{ width: "100%", fontSize: 12, padding: "6px 8px", background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, boxSizing: "border-box" }}
            />
            <label style={{ fontSize: 11, color: C.muted, display: "block", marginTop: 10, marginBottom: 4 }}>Notes</label>
            <textarea
              value={annotationDraft.notes}
              onChange={(e) => setAnnotationDraft((d) => ({ ...d, notes: e.target.value }))}
              placeholder="Trade notes..."
              rows={3}
              maxLength={2000}
              style={{ width: "100%", fontSize: 12, padding: "6px 8px", background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, resize: "vertical", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
              <span style={{ fontSize: 10, color: annotationFeedback?.type === "error" ? C.red : annotationFeedback?.type === "success" ? C.green : C.faint }}>
                {annotationFeedback?.message ?? ""}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => setEditingAnnotations(null)} style={{ fontSize: 11, padding: "5px 12px", background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, cursor: "pointer" }}>Cancel</button>
                <button onClick={saveAnnotations} disabled={annotationSaving} style={{ fontSize: 11, padding: "5px 12px", background: C.accent, border: "none", borderRadius: 6, color: "#fff", cursor: annotationSaving ? "wait" : "pointer" }}>
                  {annotationSaving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Phase 7.1: Trade Detail Modal */}
      {tradeDetailId && (
        <TradeDetailModal executionId={tradeDetailId} onClose={() => setTradeDetailId(null)} />
      )}

      {/* Phase 7.1: Strategy Drill-Down Modal */}
      {strategyDrilldown && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10000 }} onClick={closeStrategyDrilldown}>
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 20, width: 560, maxWidth: "92vw", maxHeight: "85vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ fontSize: 14, fontWeight: 800 }}>Strategy: {strategyDrilldown}</div>
              <button onClick={closeStrategyDrilldown} style={{ fontSize: 18, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>×</button>
            </div>
            {strategyDetailLoading && <div style={{ fontSize: 12, color: C.muted, padding: 20 }}>Loading…</div>}
            {strategyDetailError && <div style={{ fontSize: 12, color: C.red, padding: 20 }}>{strategyDetailError}</div>}
            {strategyDetail && (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 14 }}>
                  {["total_executions", "closed_executions", "open_executions"].map((k) => (
                    <div key={k} style={{ minWidth: 80 }}>
                      <div style={{ fontSize: 10, color: C.muted }}>{k.replace(/_/g, " ")}</div>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{strategyDetail[k]}</div>
                    </div>
                  ))}
                  <div style={{ minWidth: 80 }}>
                    <div style={{ fontSize: 10, color: C.muted }}>win rate</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: C.gold }}>{strategyDetail.win_rate != null ? `${strategyDetail.win_rate.toFixed(0)}%` : "—"}</div>
                  </div>
                  <div style={{ minWidth: 80 }}>
                    <div style={{ fontSize: 10, color: C.muted }}>net P&L</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor(strategyDetail.net_realized_pnl) }}>{fmtPnl(strategyDetail.net_realized_pnl)}</div>
                  </div>
                  <div style={{ minWidth: 80 }}>
                    <div style={{ fontSize: 10, color: C.muted }}>profit factor</div>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>{strategyDetail.profit_factor != null ? strategyDetail.profit_factor.toFixed(2) : "—"}</div>
                  </div>
                  <div style={{ minWidth: 80 }}>
                    <div style={{ fontSize: 10, color: C.muted }}>expectancy</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor(strategyDetail.expectancy) }}>{strategyDetail.expectancy != null ? fmtPnl(strategyDetail.expectancy) : "—"}</div>
                  </div>
                </div>
                <div style={sectionTitle}>TRADES</div>
                {strategyDetail.trades.length === 0 ? (
                  <div style={{ fontSize: 11, color: C.faint }}>No trades</div>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                    <thead>
                      <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                        <th style={{ padding: "4px 6px" }}>Date</th>
                        <th style={{ padding: "4px 6px" }}>Result</th>
                        <th style={{ padding: "4px 6px" }}>P&L</th>
                        <th style={{ padding: "4px 6px" }}>Duration</th>
                        <th style={{ padding: "4px 6px" }}>Tags</th>
                      </tr>
                    </thead>
                    <tbody>
                      {strategyDetail.trades.map((t) => (
                        <tr key={t.execution_id} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: "4px 6px" }}>
                            <button
                              onClick={() => { closeStrategyDrilldown(); setTradeDetailId(t.execution_id); }}
                              style={{ background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: 11, padding: 0 }}
                            >
                              {t.entry_at ? new Date(t.entry_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) : "—"}
                            </button>
                          </td>
                          <td style={{ padding: "4px 6px" }}>
                            <span style={{ fontSize: 9, fontWeight: 700, color: t.result === "WIN" ? C.green : t.result === "LOSS" ? C.red : C.gold, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "1px 6px" }}>
                              {t.result ?? "OPEN"}
                            </span>
                          </td>
                          <td style={{ padding: "4px 6px", fontWeight: 600, color: pnlColor(t.realized_pnl) }}>{fmtPnl(t.realized_pnl)}</td>
                          <td style={{ padding: "4px 6px" }}>{t.duration_label ?? "—"}</td>
                          <td style={{ padding: "4px 6px", fontSize: 10 }}>
                            {t.tags && t.tags.length > 0 ? t.tags.join(", ") : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
