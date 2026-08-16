"use client";

// Analytics panel (Phase 4.2) — GENERIC, strategy-agnostic measurements.
//
// This panel deliberately shows DATA + MEASUREMENTS only:
//   - CE vs PE comparisons at the ATM strike (IV, Delta, Gamma, Theta, Vega)
//   - Price/IV relationship (directions, same/opposite — purely mathematical)
//   - Statistics (z-score / percentile / anomaly) — all UNAVAILABLE until a
//     reliable historical observation set exists
//   - VIX status (unavailable — never substituted by ATM/average IV)
//
// There are NO buy/sell buttons, no signals, no bullish/bearish labels and no
// strategy suggestions anywhere in this panel. Direction words ("up"/"down")
// describe number movement only.
//
// Data flow: the current observation is built from the ALREADY-LOADED chain
// (the existing Phase 2.1 polling architecture — no new polling loop) at the
// nearest strike to spot. A session baseline (first-seen observation) powers
// the change/relationship metrics once a second observation exists — exactly
// the pattern the IV panel uses for its session change. History is not
// collected in this phase, so every statistical measure stays null with a
// structured INSUFFICIENT_HISTORY note — nothing is fabricated.

import { useEffect, useMemo, useState } from "react";
import { C, fmtIN } from "@/lib/ui";
import { nearestStrike } from "@/lib/calculations/ivAnalytics";
import {
  calculateMarketAnalytics,
  observationFromChainRow,
  observationKey,
  cePeComparison,
} from "@/lib/calculations/marketAnalytics";

const fmtIv = (v) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);
const fmtVolPts = (v, digits = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`);
const fmtNum = (v, digits = 3) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`);
const fmtINR = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v), 2)}`);

const DIR_LABEL = { up: "↑ up", down: "↓ down", flat: "→ flat", unavailable: "—" };

function SectionTitle({ children, note }) {
  return (
    <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 0.6, color: C.text, marginBottom: 6 }}>
      {children}
      {note && <span style={{ color: C.faint, fontWeight: 400 }}> · {note}</span>}
    </div>
  );
}

function MetricBox({ label, value, sub, color }) {
  return (
    <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", minWidth: 0 }}>
      <div style={{ fontSize: 9, letterSpacing: 0.8, color: C.faint, fontWeight: 700 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 13, fontWeight: 800, color: color || C.text, marginTop: 2, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: C.faint, marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

export default function AnalyticsPanel({ chainCache, spot, expiry, symbol, isMobile }) {
  // ---- Current observation: the ATM strike row of the SELECTED expiry's
  // chain (its own expiry — never another expiry's data). ----
  const currentObs = useMemo(() => {
    const chain = chainCache?.[expiry];
    if (!chain?.chain?.length) return null;
    const atmStrike = nearestStrike(chain.chain.map((r) => r.strike), spot);
    if (atmStrike == null) return null;
    const row = chain.chain.find((r) => r.strike === atmStrike);
    if (!row) return null;
    return observationFromChainRow({
      symbol,
      expiry,
      row,
      spot: chain.underlying_spot_price ?? spot,
      timestamp: new Date().toISOString(),
    });
  }, [chainCache, expiry, spot, symbol]);

  // ---- Session baseline (first-seen observation per identity). No new
  // polling: piggybacks on the existing chain poll. Change/relationship
  // metrics only appear once a second observation exists. ----
  const [baseObs, setBaseObs] = useState({});
  const [obsSeen, setObsSeen] = useState({});
  useEffect(() => {
    if (!currentObs) return;
    const key = observationKey(currentObs);
    if (!key) return;
    setBaseObs((prev) => (prev[key] ? prev : { ...prev, [key]: currentObs }));
    setObsSeen((prev) => ({ ...prev, [key]: (prev[key] ?? 0) + 1 }));
  }, [currentObs]);

  const key = currentObs ? observationKey(currentObs) : null;
  const previous = key && (obsSeen[key] ?? 0) >= 2 ? baseObs[key] : null;

  // One authoritative analytics result, reused by every section.
  const analytics = useMemo(
    () =>
      calculateMarketAnalytics({
        current: currentObs,
        previous,
        history: [], // no historical observation set is collected in this phase
        timestamp: currentObs?.timestamp ?? null,
      }),
    [currentObs, previous]
  );

  const [ivDetailOpen, setIvDetailOpen] = useState(false);

  if (!currentObs) {
    return (
      <div style={{ fontSize: 12, color: C.faint, padding: "40px 0", textAlign: "center" }}>
        Load a chain for {expiry ?? "the selected expiry"} to see neutral market analytics.
      </div>
    );
  }

  const iv = analytics.iv;
  const price = analytics.price;
  const rel = analytics.relationships.priceIv;
  const showChange = previous != null;

  const cePeRows = [
    ["iv", "IV", (v) => fmtIv(v)],
    ["delta", "Delta", (v) => fmtNum(v, 3)],
    ["gamma", "Gamma", (v) => fmtNum(v, 5)],
    ["thetaPerDay", "Theta / day", (v) => fmtINR(v)],
    ["vegaPerVolPoint", "Vega / 1 vol pt", (v) => fmtINR(v)],
  ];

  const statsRows = [
    ["IV z-score", iv.zScore, (v) => fmtNum(v, 2)],
    ["Gamma z-score", analytics.greeks.gamma.anomaly?.zScore ?? null, (v) => fmtNum(v, 2)],
    ["IV percentile", iv.percentileRank, (v) => (v == null ? "—" : `${v.toFixed(1)}`)],
    ["IV anomaly (0–100)", iv.anomaly?.magnitude ?? null, (v) => (v == null ? "—" : v.toFixed(0))],
  ];
  const anyStats = statsRows.some(([, v]) => v != null);

  return (
    <div>
      {/* Provenance legend */}
      <div style={{ fontSize: 10, color: C.faint, lineHeight: 1.5, marginBottom: 10 }}>
        <span style={{ color: C.green, fontWeight: 700 }}>LIVE</span> = broker/chain data (normalized to canonical units) ·{" "}
        <span style={{ color: C.gold, fontWeight: 700 }}>DERIVED</span> = session change, comparisons, relationships ·{" "}
        <span style={{ color: C.faint, fontWeight: 700 }}>STATISTICS</span> = unavailable until a reliable historical sample exists.
      </div>

      {/* CURRENT OBSERVATION — CE vs PE */}
      <SectionTitle note={`${symbol} · ${expiry ?? "selected expiry"} · ATM strike ${fmtIN(currentObs.strike)} · spot ${fmtIN(currentObs.spot)}`}>
        CURRENT OBSERVATION — CE vs PE
      </SectionTitle>
      <div style={{ overflowX: "auto", marginBottom: 12 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5, minWidth: 420 }}>
          <thead>
            <tr style={{ color: C.muted, fontSize: 10 }}>
              <th style={{ padding: "5px 8px", textAlign: "left" }}>Metric</th>
              <th style={{ padding: 5 }}>CE</th>
              <th style={{ padding: 5 }}>PE</th>
              <th style={{ padding: 5 }}>Difference</th>
              <th style={{ padding: 5, textAlign: "right" }}>Higher side</th>
            </tr>
          </thead>
          <tbody>
            {cePeRows.map(([metric, label, fmt]) => {
              const cmp = cePeComparison(currentObs, metric);
              return (
                <tr key={metric} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: "5px 8px", color: C.text }}>{label}</td>
                  <td style={{ padding: 5, textAlign: "center", color: C.green, fontVariantNumeric: "tabular-nums" }}>{fmt(cmp.ce)}</td>
                  <td style={{ padding: 5, textAlign: "center", color: C.red, fontVariantNumeric: "tabular-nums" }}>{fmt(cmp.pe)}</td>
                  <td style={{ padding: 5, textAlign: "center", color: C.muted, fontVariantNumeric: "tabular-nums" }}>
                    {cmp.difference != null ? fmt(cmp.difference) : "—"}
                  </td>
                  <td style={{ padding: 5, textAlign: "right", color: C.faint }}>
                    {cmp.dominantSide === "first" ? "CE" : cmp.dominantSide === "second" ? "PE" : cmp.dominantSide === "equal" ? "equal" : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div style={{ fontSize: 9.5, color: C.faint, marginTop: 4 }}>
          "Higher side" is the side with the greater numeric value — a measurement, not a bullish/bearish statement.
        </div>
      </div>

      {/* PRICE / IV RELATIONSHIP */}
      <SectionTitle note="purely mathematical — no trading interpretation">PRICE / IV RELATIONSHIP</SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
        <MetricBox
          label="Price change"
          value={showChange && price.current != null ? fmtINR(price.current - price.previous) : "—"}
          color={showChange && price.current != null ? (price.current - price.previous >= 0 ? C.green : C.red) : C.muted}
          sub={showChange ? "vs session baseline" : "needs a second observation"}
        />
        <MetricBox
          label="IV change"
          value={showChange && rel.ivChangeVolPoints != null ? `${fmtVolPts(rel.ivChangeVolPoints)} vol pts` : "—"}
          color={showChange && rel.ivChangeVolPoints != null ? (rel.ivChangeVolPoints >= 0 ? C.green : C.red) : C.muted}
          sub={showChange ? `rel ${iv.changePercent != null ? iv.changePercent.toFixed(2) + "%" : "—"}` : "needs a second observation"}
        />
        <MetricBox label="Price direction" value={showChange ? DIR_LABEL[rel.priceDirection] : "—"} color={C.text} sub="movement only" />
        <MetricBox label="IV direction" value={showChange ? DIR_LABEL[rel.ivDirection] : "—"} color={C.text} sub="movement only" />
      </div>
      {showChange && (
        <div style={{ fontSize: 10.5, color: C.faint, marginBottom: 12 }}>
          Price and IV moved {rel.sameDirection ? "in the SAME direction" : rel.oppositeDirection ? "in OPPOSITE directions" : "independently (one is flat)"}.
        </div>
      )}

      {/* STATISTICS */}
      <SectionTitle note="z-scores / percentiles need a reliable historical sample — not collected in this phase">
        STATISTICS
      </SectionTitle>
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
        {statsRows.map(([label, value, fmt]) => (
          <MetricBox key={label} label={label} value={fmt(value)} color={value != null ? C.gold : C.muted} sub={value != null ? "vs history" : "no history"} />
        ))}
      </div>
      {!anyStats && (
        <div style={{ fontSize: 10.5, color: C.faint, lineHeight: 1.5, marginBottom: 12 }}>
          Statistical measures are intentionally unavailable: this phase does not fabricate ranks or z-scores from missing history. A
          future phase that collects historical observations will populate these automatically.
        </div>
      )}

      {/* IV detail (expandable) */}
      <button
        onClick={() => setIvDetailOpen((v) => !v)}
        style={{ background: "transparent", border: "none", color: C.gold, fontSize: 11, fontWeight: 700, cursor: "pointer", padding: 0, marginBottom: 8, display: "block" }}
      >
        {ivDetailOpen ? "▾" : "▸"} IV detail — current · previous · change · rolling stats
      </button>
      {ivDetailOpen && (
        <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 12, fontSize: 11.5 }}>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 8 }}>
            <MetricBox label="Current IV" value={fmtIv(iv.current)} color={C.text} sub="live chain (ATM)" />
            <MetricBox label="Previous IV" value={fmtIv(iv.previous)} color={C.text} sub="session baseline" />
            <MetricBox label="Change" value={showChange ? `${fmtVolPts(iv.changeVolPoints)} vol pts` : "—"} color={iv.changeVolPoints != null ? (iv.changeVolPoints >= 0 ? C.green : C.red) : C.muted} sub={showChange ? "vs baseline" : "needs a second observation"} />
            <MetricBox label="Anomaly" value={iv.anomaly?.magnitude != null ? iv.anomaly.magnitude.toFixed(0) : "—"} color={iv.anomaly?.magnitude != null ? C.gold : C.muted} sub={iv.anomaly?.magnitude != null ? "0–100 unusualness" : "no history"} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(5, 1fr)", gap: 8, marginTop: 8 }}>
            {[
              ["Rolling mean", iv.rollingMean != null ? fmtIv(iv.rollingMean) : "—"],
              ["Rolling median", iv.rollingMedian != null ? fmtIv(iv.rollingMedian) : "—"],
              ["Rolling σ", iv.rollingStdDev != null ? fmtIv(iv.rollingStdDev) : "—"],
              ["Min", iv.rollingMin != null ? fmtIv(iv.rollingMin) : "—"],
              ["Max", iv.rollingMax != null ? fmtIv(iv.rollingMax) : "—"],
            ].map(([label, value]) => (
              <MetricBox key={label} label={label} value={value} color={C.muted} sub="history" />
            ))}
          </div>
          <div style={{ fontSize: 9.5, color: C.faint, marginTop: 8 }}>
            Z-score {iv.zScore != null ? fmtNum(iv.zScore, 2) : "—"} · percentile {iv.percentileRank != null ? `${iv.percentileRank.toFixed(1)}` : "—"} · anomaly magnitude {iv.anomaly?.magnitude != null ? iv.anomaly.magnitude.toFixed(0) : "—"} (0–100 statistical
            unusualness — not a probability, not a signal).
          </div>
        </div>
      )}

      {/* VIX */}
      <SectionTitle note="no VIX source in the current data feed">VIX</SectionTitle>
      <div style={{ fontSize: 11, color: C.faint, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
        Status: <span style={{ color: C.muted, fontWeight: 700 }}>{analytics.vix.status === "available" ? "available" : "unavailable"}</span>
        {analytics.vix.status === "unavailable" && " — ATM / index / average IV is never substituted for VIX."}
      </div>

      {/* Warnings from the calculation layer */}
      {analytics.warnings.length > 0 && (
        <div style={{ background: "rgba(224,163,58,0.08)", border: "1px solid rgba(224,163,58,0.35)", borderRadius: 8, padding: "8px 12px", fontSize: 11, color: C.gold, lineHeight: 1.5, marginBottom: 10 }}>
          {analytics.warnings.map((w, i) => (
            <div key={i}>
              {w.code}: {w.message}
            </div>
          ))}
        </div>
      )}

      <div style={{ fontSize: 9.5, color: C.faint, borderTop: `1px solid ${C.border}`, paddingTop: 8 }}>
        Analytics only — measurements and relationships, no buy/sell advice, no trading signals, no execution.
      </div>
    </div>
  );
}
