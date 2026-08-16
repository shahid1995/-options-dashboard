"use client";

// Greek Analytics panel (Phase 4.0) — LIVE (broker chain) vs MODELLED
// (Black-Scholes) Greek comparison for the Strategy Builder.
//
// Analytical only: it never submits orders, modifies positions, cash or the
// journal, and never touches the market-hours gate. It consumes ONLY the
// canonical values produced by lib/calculations/greekAnalytics.js (delta per
// underlying point, gamma per underlying point, theta per calendar day in ₹,
// vega per 1 volatility point in ₹, all exposure-scaled by
// dir × qty × lot size × multiplier). Labels are explicit — LIVE, MODELLED,
// DIFFERENCE — and the difference is a neutral comparison, never a signal.

import { useState } from "react";
import { C, fmtIN } from "@/lib/ui";
import { GREEK_KEYS, CANONICAL_UNIT_CONTRACT } from "@/lib/calculations/greekAnalytics";

const fmtSigned = (v, digits = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`);
const fmtRupeeSigned = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v))}`);

// Value formatter per canonical Greek: delta/gamma are unitless numbers,
// thetaPerDay and vegaPerVolPoint are rupee figures.
const fmtValue = (greek, v) =>
  v == null
    ? "—"
    : greek === "thetaPerDay" || greek === "vegaPerVolPoint"
      ? fmtRupeeSigned(v)
      : greek === "gamma"
        ? fmtSigned(v, 4)
        : fmtSigned(v, 1);

const GREEK_LABELS = {
  delta: "Delta",
  gamma: "Gamma",
  thetaPerDay: "Theta/day",
  vegaPerVolPoint: "Vega/1pt",
};

const GREEK_DESCRIPTIONS = {
  delta: CANONICAL_UNIT_CONTRACT.delta,
  gamma: CANONICAL_UNIT_CONTRACT.gamma,
  thetaPerDay: CANONICAL_UNIT_CONTRACT.thetaPerDay,
  vegaPerVolPoint: CANONICAL_UNIT_CONTRACT.vegaPerVolPoint,
};

export default function GreekAnalyticsPanel({ analytics, isMobile }) {
  const [contribGreek, setContribGreek] = useState("delta");
  const { rows, totals, contributions, warnings } = analytics;

  const statusNote = (status) =>
    status === "available" ? null : status === "partial" ? "· partial" : "· unavailable";

  const cell = (greek, source) => {
    const v = totals[source][greek];
    const st = totals.status[source][greek];
    return (
      <div style={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
        <span style={{ color: v == null ? C.faint : C.text, fontWeight: 700 }}>{fmtValue(greek, v)}</span>
        {statusNote(st) && <span style={{ color: C.faint, fontSize: 9 }}> {statusNote(st)}</span>}
      </div>
    );
  };

  const diffCell = (greek) => {
    const v = totals.difference[greek];
    return (
      <span
        style={{
          whiteSpace: "nowrap",
          fontVariantNumeric: "tabular-nums",
          fontWeight: 700,
          color: v == null ? C.faint : v === 0 ? C.muted : v > 0 ? C.green : C.red,
        }}
      >
        {fmtValue(greek, v)}
      </span>
    );
  };

  const contrib = contributions[contribGreek];
  const pctMax = Math.max(1, ...contrib.entries.map((e) => Math.abs(e.pct ?? 0)));

  return (
    <div>
      {/* Unit contract / legend */}
      <div style={{ fontSize: 10, color: C.faint, lineHeight: 1.5, marginBottom: 10 }}>
        <span style={{ color: C.green, fontWeight: 700 }}>LIVE</span> = broker/chain Greeks ·{" "}
        <span style={{ color: C.gold, fontWeight: 700 }}>MODELLED</span> = Black-Scholes at the current state ·{" "}
        <span style={{ color: C.muted, fontWeight: 700 }}>Δ MODEL</span> = model − live (neutral comparison, not a
        signal). All values are exposure-scaled: dir × qty × lot size × multiplier. Theta is per calendar day (₹);
        Vega is per 1 volatility point (₹).
      </div>

      {/* Strategy summary: LIVE | MODELLED | Δ MODEL */}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5, marginBottom: 12 }}>
        <thead>
          <tr style={{ color: C.muted, fontSize: 10, textAlign: "left" }}>
            <th style={{ padding: "5px 8px" }}>GREEK</th>
            <th style={{ padding: "5px 8px", textAlign: "right" }}>
              <span style={{ color: C.green, fontWeight: 700 }}>LIVE</span>
            </th>
            <th style={{ padding: "5px 8px", textAlign: "right" }}>
              <span style={{ color: C.gold, fontWeight: 700 }}>MODELLED</span>
            </th>
            <th style={{ padding: "5px 8px", textAlign: "right" }}>
              <span style={{ color: C.muted, fontWeight: 700 }}>Δ MODEL</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {GREEK_KEYS.map((g) => (
            <tr key={g} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }} title={GREEK_DESCRIPTIONS[g]}>
              <td style={{ padding: "5px 8px", fontWeight: 700, color: C.text }}>{GREEK_LABELS[g]}</td>
              <td style={{ padding: "5px 8px", textAlign: "right" }}>{cell(g, "live")}</td>
              <td style={{ padding: "5px 8px", textAlign: "right" }}>{cell(g, "model")}</td>
              <td style={{ padding: "5px 8px", textAlign: "right" }}>{diffCell(g)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Per-leg LIVE vs MODELLED table */}
      <div style={{ overflowX: "auto", marginBottom: 12 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
              <th style={{ padding: 5 }}>Leg</th>
              <th style={{ padding: 5, textAlign: "right" }}>Δ (L / M)</th>
              <th style={{ padding: 5, textAlign: "right" }}>Γ (L / M)</th>
              <th style={{ padding: 5, textAlign: "right" }}>Θ/day (L / M)</th>
              <th style={{ padding: 5, textAlign: "right" }}>V/1pt (L / M)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.legId} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                <td style={{ padding: 5, whiteSpace: "nowrap" }}>
                  <span style={{ fontWeight: 700, color: r.action === "buy" ? C.green : C.red }}>
                    {r.action.toUpperCase()}
                  </span>{" "}
                  {fmtIN(r.strike)} {r.type === "call" ? "CE" : "PE"} ×{r.qty}
                  <span style={{ color: C.faint }}> · {r.expiry}</span>
                </td>
                {GREEK_KEYS.map((g) => (
                  <td key={g} style={{ padding: "5px 5px", textAlign: "right", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                    <span style={{ color: r.live[g] != null ? C.green : C.faint }}>{fmtValue(g, r.live[g])}</span>
                    <span style={{ color: C.faint }}> / </span>
                    <span style={{ color: r.model[g] != null ? C.gold : C.faint }}>{fmtValue(g, r.model[g])}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 9.5, color: C.faint, marginTop: 4 }}>
          L = LIVE (broker chain) · M = MODELLED (Black-Scholes). Missing values stay “—” and are never substituted.
        </div>
      </div>

      {/* Contribution view */}
      <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          <span style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 0.6, color: C.text }}>GREEK CONTRIBUTORS</span>
          <span style={{ fontSize: 9.5, color: C.faint }}>which leg drives the strategy {GREEK_LABELS[contribGreek].toLowerCase()}?</span>
          <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
            {GREEK_KEYS.map((g) => (
              <button
                key={g}
                onClick={() => setContribGreek(g)}
                style={{
                  fontSize: 10,
                  padding: "3px 8px",
                  borderRadius: 5,
                  cursor: "pointer",
                  border: `1px solid ${contribGreek === g ? C.gold : C.border}`,
                  background: contribGreek === g ? "rgba(201,161,90,0.12)" : "transparent",
                  color: contribGreek === g ? C.gold : C.muted,
                  fontWeight: contribGreek === g ? 700 : 400,
                }}
              >
                {GREEK_LABELS[g]}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {contrib.entries.map((e) => (
            <div key={e.legId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ minWidth: 130, fontSize: 10.5, color: C.muted, whiteSpace: "nowrap" }}>{e.label}</span>
              <div style={{ flex: 1, height: 8, borderRadius: 4, background: C.surface, overflow: "hidden", position: "relative" }}>
                {e.value != null && e.pct != null && (
                  <div
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 0,
                      left: "50%",
                      width: `${Math.min(50, (Math.abs(e.pct) / pctMax) * 50)}%`,
                      transform: e.pct >= 0 ? "translateX(0)" : "translateX(-100%)",
                      background: e.value >= 0 ? "rgba(76,175,125,0.55)" : "rgba(225,82,82,0.55)",
                      borderRadius: 4,
                    }}
                  />
                )}
              </div>
              <span style={{ minWidth: 76, textAlign: "right", fontSize: 10.5, fontWeight: 700, fontVariantNumeric: "tabular-nums", color: e.value == null ? C.faint : e.value >= 0 ? C.green : C.red }}>
                {fmtValue(contribGreek, e.value)}
              </span>
              <span style={{ minWidth: 44, textAlign: "right", fontSize: 10, color: e.pct == null ? C.faint : C.muted, fontVariantNumeric: "tabular-nums" }}>
                {e.pct == null ? "—" : `${e.pct >= 0 ? "+" : ""}${e.pct.toFixed(0)}%`}
              </span>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 8, borderTop: `1px solid ${C.border}`, paddingTop: 5 }}>
            <span style={{ minWidth: 130, fontSize: 10.5, fontWeight: 800, color: C.text }}>Strategy total</span>
            <span style={{ flex: 1 }} />
            <span style={{ minWidth: 76, textAlign: "right", fontSize: 10.5, fontWeight: 800, fontVariantNumeric: "tabular-nums", color: contrib.total == null ? C.faint : contrib.total >= 0 ? C.green : C.red }}>
              {fmtValue(contribGreek, contrib.total)}
            </span>
            <span style={{ minWidth: 44 }} />
          </div>
        </div>
        <div style={{ fontSize: 9.5, color: C.faint, marginTop: 6 }}>
          Contribution % = leg value ÷ signed strategy total × 100 (contributing legs sum to 100%). Analytical only — no
          directional signal is implied.
        </div>
      </div>

      {/* Warnings from the calculation layer */}
      {warnings.length > 0 && (
        <div style={{ background: "rgba(224,163,58,0.08)", border: "1px solid rgba(224,163,58,0.35)", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: C.gold, lineHeight: 1.5 }}>
          {warnings.map((w, i) => (
            <div key={i}>
              {w.code}: {w.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
