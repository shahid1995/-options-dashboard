"use client";

// IV Analytics panel (Phase 4.1) — implied-volatility foundation UI.
//
// Analytical only: it reads the already-loaded chain cache (the existing
// Phase 2.1 polling architecture — no new polling loop) and derives descriptive
// volatility analytics. It never executes an order, never touches positions,
// cash or the journal, and never bypasses the market-hours gate.
//
// Provenance is explicit everywhere:
//   LIVE     — broker-provided IV, normalized to canonical decimal
//              (18.24% → 0.1824); shown as a percentage.
//   DERIVED  — ATM average, skew, term-structure slope, session change.
//   HISTORY  — nothing is displayed: Phase 4.1 deliberately shows NO IV Rank /
//              IV Percentile because no reliable historical sample exists yet.
//
// Canonical units: the calculation layer (lib/calculations/ivAnalytics.js)
// works in decimal fractions and volatility points; this panel only formats
// them for display (percentages, "+X.X vol pts").

import { useEffect, useMemo, useState } from "react";
import { C, fmtIN } from "@/lib/ui";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { calculateIvAnalytics, calculateIvChange, decimalToIvPercent, formatIvPercent } from "@/lib/calculations/ivAnalytics";

const fmtVolPts = (v, digits = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`);
const fmtIv = (v) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);
const fmtPctNum = (v) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);

const STATUS_NOTE = {
  available: null,
  partial: "· partial (one side only)",
  unavailable: "· unavailable",
};

function MetricBox({ label, value, sub, color }) {
  return (
    <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", minWidth: 0 }}>
      <div style={{ fontSize: 9, letterSpacing: 0.8, color: C.faint, fontWeight: 700 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 13, fontWeight: 800, color: color || C.text, marginTop: 2, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

export default function IVAnalyticsPanel({ chainCache, spot, expiry, isMobile }) {
  const analytics = useMemo(
    () =>
      calculateIvAnalytics({
        chainCache,
        spot,
        valuationDate: new Date().toISOString().slice(0, 10),
        selectedExpiry: expiry,
        legs: [], // IV analytics are chain-level; per-leg rows appear when legs exist
      }),
    [chainCache, spot, expiry]
  );

  // ---- Session IV change (vs the FIRST observation of this expiry in this
  // view). No new polling: it piggybacks on the existing chain poll. Only
  // shown once a second observation exists — a single snapshot never claims
  // to be a change. ----
  const [ivBase, setIvBase] = useState({}); // { [expiry]: firstSeenAtmIv }
  const [ivSeen, setIvSeen] = useState({}); // { [expiry]: observation count }
  useEffect(() => {
    if (!expiry || analytics.atm.atmIv == null) return;
    setIvBase((prev) => (prev[expiry] == null ? { ...prev, [expiry]: analytics.atm.atmIv } : prev));
    setIvSeen((prev) => ({ ...prev, [expiry]: (prev[expiry] ?? 0) + 1 }));
  }, [expiry, analytics.atm.atmIv]);

  const change = useMemo(
    () => calculateIvChange(ivBase[expiry] ?? null, analytics.atm.atmIv),
    [ivBase, expiry, analytics.atm.atmIv]
  );
  const showChange = (ivSeen[expiry] ?? 0) >= 2 && change.available;

  // ---- Chart data (display percentages; ATM marker on the strike axis) ----
  const curveData = useMemo(
    () => analytics.curve.map((p) => ({ ...p, callIvPct: p.callIvPercent, putIvPct: p.putIvPercent })),
    [analytics.curve]
  );
  const termData = useMemo(
    () =>
      analytics.termStructure
        .filter((t) => t.available)
        .map((t) => ({ dte: t.daysToExpiry, expiry: t.expiry, atmIvPct: t.atmIv != null ? decimalToIvPercent(t.atmIv) : null })),
    [analytics.termStructure]
  );
  const slopeSeg = analytics.termSlope?.[0] ?? null;

  const { atm } = analytics;
  const atmStatusNote = STATUS_NOTE[atm.status] ?? null;

  return (
    <div>
      {/* Provenance legend */}
      <div style={{ fontSize: 10, color: C.faint, lineHeight: 1.5, marginBottom: 10 }}>
        <span style={{ color: C.green, fontWeight: 700 }}>LIVE</span> = broker/chain IV (normalized, displayed as %) ·{" "}
        <span style={{ color: C.gold, fontWeight: 700 }}>DERIVED</span> = ATM average, skew, slope, session change ·{" "}
        <span style={{ color: C.faint, fontWeight: 700 }}>HISTORY</span> = none shown yet (IV Rank/Percentile need a reliable
        historical sample — not collected in this phase).
      </div>

      {/* ATM IV + IV change */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 8, marginBottom: 10 }}>
        <MetricBox label="ATM IV · Call" value={fmtIv(atm.callIv)} color={C.green} sub={`strike ${fmtIN(atm.atmStrike)}`} />
        <MetricBox label="ATM IV · Put" value={fmtIv(atm.putIv)} color={C.red} sub={atm.callIv != null && atm.putIv != null ? "same ATM strike" : "one side missing"} />
        <MetricBox
          label="ATM IV · Average"
          value={fmtIv(atm.atmIv)}
          color={C.gold}
          sub={atmStatusNote ?? "derived (call + put) / 2"}
        />
        <MetricBox
          label="IV change · session"
          value={showChange ? `${fmtVolPts(change.ivChangeVolPoints)} vol pts` : "—"}
          color={showChange ? (change.ivChangeVolPoints >= 0 ? C.green : C.red) : C.muted}
          sub={showChange ? `rel ${fmtPctNum(change.ivChangePercent)}` : "needs a second observation"}
        />
      </div>

      {/* ATM skew */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 8, marginBottom: 12 }}>
        <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
          <div style={{ fontSize: 9, letterSpacing: 0.8, color: C.faint, fontWeight: 700 }}>ATM SKEW · PUT (2% OTM)</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: analytics.skew.put.available ? C.gold : C.muted, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
            {analytics.skew.put.available ? `${fmtVolPts(analytics.skew.put.putSkewVolPoints)} vol pts` : "—"}
          </div>
          <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>
            {analytics.skew.put.strike != null ? `put IV at ${fmtIN(analytics.skew.put.strike)} − ATM IV` : "no −2% strike available"}
          </div>
        </div>
        <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
          <div style={{ fontSize: 9, letterSpacing: 0.8, color: C.faint, fontWeight: 700 }}>ATM SKEW · CALL (+2% OTM)</div>
          <div style={{ fontSize: 13, fontWeight: 800, color: analytics.skew.call.available ? C.gold : C.muted, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
            {analytics.skew.call.available ? `${fmtVolPts(analytics.skew.call.callSkewVolPoints)} vol pts` : "—"}
          </div>
          <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>
            {analytics.skew.call.strike != null ? `call IV at ${fmtIN(analytics.skew.call.strike)} − ATM IV` : "no +2% strike available"}
          </div>
        </div>
      </div>

      {/* IV vs strike curve */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 0.6, color: C.text, marginBottom: 6 }}>
          IV CURVE · {expiry ?? "selected expiry"}
          <span style={{ color: C.faint, fontWeight: 400 }}> · IV vs strike (call / put, separate lines)</span>
        </div>
        {curveData.length === 0 ? (
          <div style={{ fontSize: 11, color: C.faint, padding: "24px 0", textAlign: "center", border: `1px dashed ${C.border}`, borderRadius: 8 }}>
            No chain data for this expiry.
          </div>
        ) : (
          <div style={{ height: isMobile ? 220 : 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curveData} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                <XAxis dataKey="strike" stroke={C.faint} fontSize={10} tickFormatter={(v) => fmtIN(v)} />
                <YAxis stroke={C.faint} fontSize={10} tickFormatter={(v) => `${v}%`} width={44} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0F131B", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11 }}
                  labelFormatter={(v) => `Strike ${fmtIN(v)}`}
                  formatter={(value, name) => [`${formatIvPercent(value / 100, 2)}`, name === "callIvPct" ? "Call IV" : "Put IV"]}
                />
                <Line type="monotone" dataKey="callIvPct" name="call" stroke={C.green} dot={false} strokeWidth={1.8} />
                <Line type="monotone" dataKey="putIvPct" name="put" stroke={C.red} dot={false} strokeWidth={1.8} />
                {atm.atmStrike != null && <ReferenceLine x={atm.atmStrike} stroke={C.gold} strokeDasharray="4 4" label={{ value: "ATM", fill: C.gold, fontSize: 10, position: "top" }} />}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <div style={{ fontSize: 9.5, color: C.faint, marginTop: 5 }}>
          <span style={{ color: C.green }}>■</span> Call IV · <span style={{ color: C.red }}>■</span> Put IV — broker IV normalized to %.
        </div>
      </div>

      {/* Term structure */}
      <div>
        <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 0.6, color: C.text, marginBottom: 6 }}>
          IV TERM STRUCTURE · ATM IV vs days to expiry
          <span style={{ color: C.faint, fontWeight: 400 }}> · each expiry uses its own chain</span>
        </div>
        {termData.length < 2 ? (
          <div style={{ fontSize: 11, color: C.faint, padding: "24px 0", textAlign: "center", border: `1px dashed ${C.border}`, borderRadius: 8 }}>
            {termData.length === 1
              ? "Load a second expiry's chain (e.g. via a calendar/diagonal template) to see the term structure."
              : "No expiry chains loaded yet."}
          </div>
        ) : (
          <div style={{ height: isMobile ? 200 : 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={termData} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                <XAxis dataKey="dte" stroke={C.faint} fontSize={10} label={{ value: "Days to expiry", fill: C.faint, fontSize: 9.5, position: "insideBottom", offset: -2 }} />
                <YAxis stroke={C.faint} fontSize={10} tickFormatter={(v) => `${v}%`} width={44} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0F131B", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11 }}
                  labelFormatter={(v) => `DTE ${v}`}
                  formatter={(value) => [`${formatIvPercent(value / 100, 2)}`, "ATM IV"]}
                />
                <Line type="monotone" dataKey="atmIvPct" name="atm" stroke={C.gold} strokeWidth={2} dot={{ r: 3, fill: C.gold, strokeWidth: 0 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {slopeSeg && (
          <div style={{ fontSize: 9.5, color: C.faint, marginTop: 5 }}>
            Slope {slopeSeg.from} → {slopeSeg.to}: {fmtVolPts(slopeSeg.ivChangeVolPoints)} vol pts over {slopeSeg.days} days ={" "}
            <span style={{ color: C.gold, fontWeight: 700 }}>{fmtVolPts(slopeSeg.volPointsPerDay, 3)} vol pts/day</span> · descriptive only,
            not a signal.
          </div>
        )}
      </div>

      {/* Warnings from the calculation layer */}
      {analytics.warnings.length > 0 && (
        <div style={{ background: "rgba(224,163,58,0.08)", border: "1px solid rgba(224,163,58,0.35)", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: C.gold, lineHeight: 1.5, marginTop: 10 }}>
          {analytics.warnings.map((w, i) => (
            <div key={i}>
              {w.code}: {w.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
