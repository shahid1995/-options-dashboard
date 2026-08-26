"use client";
/**
 * Gamma Flip Panel — Phase 8D
 *
 * Displays the gamma flip level (where aggregate GEX changes sign)
 * from /gex/flip data. Shows current spot, flip strike, distance,
 * and whether spot is above/below the flip.
 *
 * Structural positioning context only.
 * Does NOT interpret above/below as bullish/bearish.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import { AppPanel, SectionTitle } from "@/components/app/styles";

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

export default function GexFlipPanel({ data, isMobile = false }) {
  const latest = useMemo(() => {
    if (!data?.flips?.length) return null;
    return data.flips[data.flips.length - 1];
  }, [data]);

  if (!latest) {
    return (
      <div style={AppPanel}>
        <div style={SectionTitle}>GAMMA FLIP</div>
        <div style={{ padding: 24, textAlign: "center", color: C.muted, fontSize: 12 }}>
          No flip data available.
        </div>
      </div>
    );
  }

  const spot = latest.spot;
  const flipStrike = latest.flipStrike;
  const distance =
    spot != null && flipStrike != null ? Math.abs(spot - flipStrike) : null;
  const distancePct =
    spot != null && distance != null ? ((distance / spot) * 100).toFixed(3) : null;
  const position =
    spot != null && flipStrike != null
      ? spot > flipStrike
        ? "above"
        : spot < flipStrike
          ? "below"
          : "at"
      : null;

  const confidencePct =
    latest.flipConfidence != null ? (latest.flipConfidence * 100).toFixed(0) : null;

  return (
    <div style={AppPanel}>
      <div style={SectionTitle}>GAMMA FLIP</div>

      {/* Main display */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr",
          gap: 12,
          marginBottom: 16,
        }}
      >
        {/* Spot */}
        <div
          style={{
            background: C.surface2,
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            padding: "10px 14px",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.5 }}>
            SPOT
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.text }}>
            {spot ? fmtIN(spot, 2) : "—"}
          </div>
        </div>

        {/* Flip Strike */}
        <div
          style={{
            background: C.surface2,
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            padding: "10px 14px",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: C.gold, letterSpacing: 0.5 }}>
            FLIP STRIKE
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.gold }}>
            {flipStrike ? fmtIN(flipStrike) : "—"}
          </div>
        </div>

        {/* Distance */}
        <div
          style={{
            background: C.surface2,
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            padding: "10px 14px",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.5 }}>
            DISTANCE
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.text }}>
            {distancePct ? `${distancePct}%` : "—"}
          </div>
        </div>
      </div>

      {/* Position indicator */}
      {position && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: position === "above" ? C.green : position === "below" ? C.red : C.muted,
            marginBottom: 8,
          }}
        >
          Spot is {position} the gamma flip
          {distance != null && (
            <span style={{ fontWeight: 400, color: C.faint, marginLeft: 6 }}>
              ({fmtIN(distance)} points)
            </span>
          )}
        </div>
      )}

      {/* Metadata */}
      <div style={{ display: "flex", gap: 16, fontSize: 11, color: C.faint, flexWrap: "wrap" }}>
        <div>Status: {latest.status}</div>
        {confidencePct && <div>Confidence: {confidencePct}%</div>}
        {latest.numSignChanges != null && <div>Sign changes: {latest.numSignChanges}</div>}
        {latest.timestamp && <div>Updated: {fmtTime(latest.timestamp)}</div>}
      </div>

      <div style={{ fontSize: 10, color: C.faint, marginTop: 12, textAlign: "center" }}>
        Gamma flip = strike where aggregate GEX changes sign · Structural level, not directional signal
      </div>
    </div>
  );
}
