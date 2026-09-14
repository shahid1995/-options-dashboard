"use client";
/**
 * Gamma Flip Panel — Phase E (Market Intelligence)
 *
 * Displays the gamma flip level (where aggregate GEX changes sign)
 * from /gex/flip data. Shows current spot, flip strike, distance,
 * and whether spot is above/below the flip.
 *
 * Uses Phase D primitives: ChartContainer, Metric, EmptyState, ErrorState.
 *
 * Structural positioning context only.
 * Does NOT interpret above/below as bullish/bearish.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import { ChartContainer, Metric, Badge, EmptyState } from "@/components/app/core";

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
      <ChartContainer
        title="GAMMA FLIP"
        eyebrow="MODEL TRANSITION"
        caption="Strike where aggregate GEX changes sign · Structural level, not directional signal"
      >
        <EmptyState message="No flip data available." />
      </ChartContainer>
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
    <ChartContainer
      title="GAMMA FLIP"
      eyebrow="MODEL TRANSITION"
      caption="Strike where aggregate GEX changes sign · Structural level, not directional signal"
      source={latest.timestamp ? fmtTime(latest.timestamp) : undefined}
    >
      {/* Main metrics */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr",
          gap: 8,
          paddingBottom: 12,
        }}
      >
        <Metric
          label="SPOT"
          value={spot ? fmtIN(spot, 2) : "—"}
          size="lg"
          semantic="strategy"
          hint="Current underlying price"
        />
        <Metric
          label="FLIP STRIKE"
          value={flipStrike ? fmtIN(flipStrike) : "—"}
          size="lg"
          semantic="strategy"
          hint="Modeled gamma-regime transition level"
        />
        <Metric
          label="DISTANCE"
          value={distancePct ? `${distancePct}%` : "—"}
          size="lg"
          semantic="neutral"
          hint={distance != null ? `${fmtIN(distance)} points from spot` : "Spot vs flip level"}
        />
      </div>

      {/* Position indicator - neutral language */}
      {position && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 12,
          }}
        >
          <Badge variant={position === "at" ? "neutral" : "info"}>
            {position === "above" ? "Spot is above the gamma flip" : position === "below" ? "Spot is below the gamma flip" : "At flip level"}
          </Badge>
          <span style={{ fontSize: 12, color: C.muted }}>
            Modeled regime transition · Not a reversal prediction
          </span>
        </div>
      )}

      {/* Metadata */}
      <div
        style={{
          display: "flex",
          gap: 16,
          fontSize: 11,
          color: C.faint,
          flexWrap: "wrap",
        }}
      >
        {latest.status && <div>Status: {latest.status}</div>}
        {confidencePct && (
          <div>Confidence: {confidencePct}%</div>
        )}
        {latest.numSignChanges != null && (
          <div>
            Sign changes: <span style={{ color: C.text, fontWeight: 600 }}>{latest.numSignChanges}</span>
          </div>
        )}
      </div>
    </ChartContainer>
  );
}
