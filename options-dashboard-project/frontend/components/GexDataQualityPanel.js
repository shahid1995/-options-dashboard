"use client";
/**
 * GEX Data Quality Panel — Phase E (Market Intelligence)
 *
 * Displays data quality metrics from /gex/data-quality endpoint.
 * Shows coverage, exclusions, timestamps, and overall classification.
 *
 * Uses Phase D primitives: ChartContainer, Metric, Badge, EmptyState.
 *
 * Deterministic, transparent quality metrics.
 * No fabricated data.
 */
import { C } from "@/lib/ui";
import { ChartContainer, Metric, Badge, EmptyState } from "@/components/app/core";

const CLASSIFICATION_COLORS = {
  EXCELLENT: C.green,
  GOOD: "#8BC34A",
  DEGRADED: C.gold,
  INSUFFICIENT: C.red,
};

export default function GexDataQualityPanel({ quality, compact = false }) {
  if (!quality) {
    return <EmptyState message="No data quality information available." />;
  }

  const score = quality.score;
  const classification = quality.classification;
  const classColor = CLASSIFICATION_COLORS[classification] || C.muted;

  // Calculate derived metrics
  const gexCoverage =
    quality.totalHistoricalGex && quality.totalOptionCandles
      ? ((quality.totalHistoricalGex / quality.totalOptionCandles) * 100).toFixed(1)
      : null;

  const timestampCoverage =
    quality.timestampsTotal && quality.timestampsWithGex
      ? ((quality.timestampsWithGex / quality.timestampsTotal) * 100).toFixed(1)
      : null;

  if (compact) {
    return (
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Badge variant={
          classification === "EXCELLENT" ? "positive" :
          classification === "GOOD" ? "positive" :
          classification === "DEGRADED" ? "warning" :
          classification === "INSUFFICIENT" ? "negative" : "neutral"
        }>
          {classification || "UNKNOWN"}
        </Badge>
        {score != null && (
          <span style={{ fontSize: 12 }}>
            <span style={{ color: C.faint }}>Score: </span>
            <span style={{ color: C.text, fontWeight: 700 }}>{score}/100</span>
          </span>
        )}
        {gexCoverage && (
          <span style={{ fontSize: 12 }}>
            <span style={{ color: C.faint }}>GEX: </span>
            <span style={{ color: C.text, fontWeight: 700 }}>{gexCoverage}%</span>
          </span>
        )}
      </div>
    );
  }

  return (
    <ChartContainer
      title="GEX DATA QUALITY"
      eyebrow="DATA TRUST SURFACE"
      caption="Freshness, completeness, and coverage metrics"
      source={quality.generatedAt ? new Date(quality.generatedAt).toLocaleString() : undefined}
    >
      {/* Classification header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <Badge
          variant={
            classification === "EXCELLENT" ? "positive" :
            classification === "GOOD" ? "positive" :
            classification === "DEGRADED" ? "warning" :
            classification === "INSUFFICIENT" ? "negative" : "neutral"
          }
        >
          {classification || "UNKNOWN"}
        </Badge>
        {score != null && (
          <Metric label="QUALITY SCORE" value={`${score}/100`} size="sm" semantic="neutral" />
        )}
      </div>

      {/* Metrics grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: 8,
        }}
      >
        {quality.totalHistoricalGex != null && (
          <Metric
            label="HISTORICAL GEX"
            value={quality.totalHistoricalGex.toLocaleString("en-IN")}
            sub={gexCoverage ? `${gexCoverage}% coverage` : undefined}
            size="sm"
            semantic="neutral"
          />
        )}
        {quality.totalOptionCandles != null && (
          <Metric
            label="OPTION CANDLES"
            value={quality.totalOptionCandles.toLocaleString("en-IN")}
            size="sm"
            semantic="neutral"
          />
        )}
        {quality.totalOptionGreeks != null && (
          <Metric
            label="OPTION GREEKS"
            value={quality.totalOptionGreeks.toLocaleString("en-IN")}
            size="sm"
            semantic="neutral"
          />
        )}
        {quality.totalNiftyCandles != null && (
          <Metric
            label="NIFTY CANDLES"
            value={quality.totalNiftyCandles.toLocaleString("en-IN")}
            size="sm"
            semantic="neutral"
          />
        )}
        {quality.timestampsTotal != null && (
          <Metric
            label="TIMESTAMPS"
            value={quality.timestampsTotal.toLocaleString("en-IN")}
            sub={timestampCoverage ? `${timestampCoverage}% with GEX` : undefined}
            size="sm"
            semantic="neutral"
          />
        )}
      </div>
    </ChartContainer>
  );
}
