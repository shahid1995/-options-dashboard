"use client";
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import {
  brokerDataCaption,
  brokerVsEstimateDifference,
  capitalDisplay,
  capitalRows,
  capitalStrategyRows,
  firstBrokerError,
  rocInputsAvailable,
} from "@/lib/capital";

const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, minWidth: 0 };
const sectionTitle = { fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: C.muted, marginBottom: 8 };

// Phase 5.2.1: financial values always display with two decimals (₹8,420.00).
const money = (v) => (v == null ? "—" : `₹${fmtIN(v, 2)}`);
const fmtSigned = (v) =>
  v == null ? "—" : `${v >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(v), 2)}`;

function Row({ label, value, source, status, note }) {
  const unavailable = value == null;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        padding: "7px 0",
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: C.text }}>{label}</div>
        <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 1 }}>
          {source.toUpperCase()}
          {status === "partial" ? " · PARTIAL" : ""}
          {note ? ` · ${note.toUpperCase()}` : ""}
        </div>
      </div>
      <div
        style={{
          fontSize: 12.5,
          fontWeight: 700,
          color: unavailable ? C.faint : status === "partial" ? C.gold : C.text,
          whiteSpace: "nowrap",
        }}
      >
        {unavailable ? "Unavailable" : money(value)}
      </div>
    </div>
  );
}

function Chip({ label, value, color }) {
  return (
    <span
      title={`${label}: ${value}`}
      style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: 0.4,
        color,
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 999,
        padding: "2px 8px",
        whiteSpace: "nowrap",
      }}
    >
      {label.toUpperCase()} · {String(value).toUpperCase()}
    </span>
  );
}

export default function CapitalPanel({ capital, loading, error }) {
  const d = useMemo(() => capitalDisplay(capital), [capital]);
  const rows = useMemo(() => capitalRows(d), [d]);
  const strategyRows = useMemo(() => capitalStrategyRows(d.strategies), [d]);
  const rocReady = rocInputsAvailable(d.rocInputs);
  const brokerError = useMemo(() => firstBrokerError(d), [d]);
  const brokerCaption = useMemo(() => brokerDataCaption(d), [d]);
  // Phase 6.2 §18: neutral descriptive difference, ONLY when both numbers are
  // available. Never labeled Savings/Advantage/Efficiency/Better.
  const brokerVsEstimate = useMemo(
    () => brokerVsEstimateDifference(d.brokerMargin.value, d.estimatedCapital.value),
    [d]
  );

  if (loading && !capital) {
    return (
      <div style={panel}>
        <div style={sectionTitle}>💼 CAPITAL</div>
        <div style={{ fontSize: 11.5, color: C.faint }}>Loading capital summary…</div>
      </div>
    );
  }

  return (
    <div style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: 0.8, color: C.text }}>💼 CAPITAL</div>
          <Chip label="Capital status" value={d.status} color={d.status === "unavailable" ? C.faint : d.status === "partial" ? C.gold : C.green} />
          <Chip
            label="Return on Capital"
            value={rocReady ? "inputs ready · not computed" : "not available"}
            color={rocReady ? C.gold : C.faint}
          />
        </div>
        {error && <div style={{ fontSize: 10.5, color: C.gold }}>⚠️ {error}</div>}
        {brokerError && !error && (
          <div
            title={brokerError.code}
            style={{ fontSize: 10.5, color: C.gold, fontWeight: 700 }}
          >
            ⚠️ {brokerError.label}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div style={sectionTitle}>Capital summary</div>
          <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "2px 10px", marginBottom: 10 }}>
            {rows.map((r) => (
              <Row key={r.key} label={r.label} value={r.value} source={r.source} status={r.status} note={r.note} />
            ))}
          </div>
          <div style={{ fontSize: 9.5, color: C.faint, lineHeight: 1.5 }}>
            Premium outlay ≠ capital required. Broker margin and broker funds come only from a connected broker
            (unavailable states are never replaced by estimated capital or paper cash). Paper values are
            paper-account values. Return on Capital is a future metric; only its inputs are prepared.
          </div>
          {brokerVsEstimate != null && (
            <div
              title="Broker-reported whole-strategy margin minus the analytical estimated capital. Descriptive only — never a savings/advantage claim."
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                padding: "7px 10px",
                marginTop: 8,
                background: C.surface2,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
              }}
            >
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.text }}>Broker vs Estimate Difference</div>
                <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 1 }}>
                  BROKER MARGIN − ESTIMATED CAPITAL · DESCRIPTIVE ONLY
                </div>
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text, whiteSpace: "nowrap" }}>
                {money(brokerVsEstimate)}
              </div>
            </div>
          )}
          {brokerCaption && (
            <div style={{ fontSize: 9.5, color: C.muted, marginTop: 8, letterSpacing: 0.3 }}>
              🕒 {brokerCaption}
            </div>
          )}
        </div>

        <div style={{ minWidth: 0 }}>
          <div style={sectionTitle}>Open strategy capital units</div>
          {strategyRows.length === 0 ? (
            <div style={{ fontSize: 11, color: C.faint, padding: "14px 0" }}>
              No open strategies — no premium outlay or estimated capital engaged.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {strategyRows.map((s) => (
                <div key={s.executionId} style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 800, color: C.text }}>{s.strategy}</div>
                    <div style={{ fontSize: 9.5, color: C.faint }}>{s.symbol}</div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))", gap: 6, marginTop: 6 }}>
                    <div>
                      <div style={{ fontSize: 8.5, color: C.faint, letterSpacing: 0.4 }}>NET ENTRY</div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: s.entryNet >= 0 ? C.text : C.gold }}>{fmtSigned(s.entryNet)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 8.5, color: C.faint, letterSpacing: 0.4 }}>PREMIUM OUTLAY</div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: C.text }}>{money(s.premiumOutlay)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 8.5, color: C.faint, letterSpacing: 0.4 }}>EST. CAPITAL</div>
                      <div
                        style={{ fontSize: 11, fontWeight: 700, color: s.estimatedCapital == null ? C.faint : C.text }}
                        title={s.estimatedCapitalBasis ?? "unavailable — credit strategies have no premium-basis estimate"}
                      >
                        {s.estimatedCapital == null ? "—" : money(s.estimatedCapital)}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 8.5, color: C.faint, letterSpacing: 0.4 }}>BROKER MARGIN</div>
                      <div
                        style={{ fontSize: 11, fontWeight: 700, color: s.brokerMargin == null ? C.faint : C.text }}
                        title={
                          s.brokerMargin == null
                            ? `${s.brokerMarginError ?? "unavailable"} — broker-reported only, never estimated`
                            : `Broker-reported whole-strategy margin · ${s.brokerMarginTimestamp ?? ""}`
                        }
                      >
                        {s.brokerMargin == null ? "—" : money(s.brokerMargin)}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 8.5, color: C.faint, marginTop: 4 }}>
                    {s.estimatedCapitalBasis ? `${s.estimatedCapitalBasis.toUpperCase()} · ESTIMATED` : "NO CAPITAL ESTIMATE · PREMIUM ≠ MARGIN"}
                    {s.brokerMargin != null && <span style={{ color: C.muted }}> · BROKER MARGIN · BROKER REPORTED</span>}
                    {s.brokerMargin == null && s.brokerMarginError && (
                      <span style={{ color: C.gold }}> · {s.brokerMarginError}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
