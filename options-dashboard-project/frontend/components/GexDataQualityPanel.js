"use client";
/**
 * GEX Data Quality Panel — Phase 8D
 *
 * Displays data quality metrics from /gex/data-quality endpoint.
 * Shows coverage, exclusions, timestamps, and overall classification.
 *
 * Deterministic, transparent quality metrics.
 * No fabricated data.
 */
import { C, fmtIN } from "@/lib/ui";
import { AppPanel, SectionTitle } from "@/components/app/styles";

const CLASSIFICATION_COLORS = {
  EXCELLENT: C.green,
  GOOD: "#8BC34A",
  DEGRADED: C.gold,
  INSUFFICIENT: C.red,
};

function QualityMetric({ label, value, sub, color }) {
  return (
    <div
      style={{
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: "8px 10px",
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: 9, fontWeight: 700, color: C.faint, letterSpacing: 0.5 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 800,
          color: color || C.text,
          marginTop: 2,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: C.faint, marginTop: 1 }}>{sub}</div>
      )}
    </div>
  );
}

export default function GexDataQualityPanel({ quality, compact = false }) {
  if (!quality) {
    return (
      <div style={{ fontSize: 12, color: C.muted, padding: 12 }}>
        No data quality information available.
      </div>
    );
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
        <div style={{ fontSize: 12 }}>
          <span style={{ color: C.faint }}>Status: </span>
          <span style={{ fontWeight: 700, color: classColor }}>{classification || "—"}</span>
        </div>
        {score != null && (
          <div style={{ fontSize: 12 }}>
            <span style={{ color: C.faint }}>Score: </span>
            <span style={{ fontWeight: 700, color: C.text }}>{score}/100</span>
          </div>
        )}
        {gexCoverage && (
          <div style={{ fontSize: 12 }}>
            <span style={{ color: C.faint }}>GEX: </span>
            <span style={{ fontWeight: 700, color: C.text }}>{gexCoverage}%</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={SectionTitle}>GEX DATA QUALITY</div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 800,
            color: classColor,
            padding: "2px 8px",
            borderRadius: 4,
            background: `${classColor}15`,
            border: `1px solid ${classColor}30`,
          }}
        >
          {classification || "UNKNOWN"}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: 8,
        }}
      >
        {score != null && (
          <QualityMetric label="QUALITY SCORE" value={`${score}/100`} color={classColor} />
        )}
        {quality.totalHistoricalGex != null && (
          <QualityMetric
            label="HISTORICAL GEX"
            value={fmtIN(quality.totalHistoricalGex)}
            sub={gexCoverage ? `${gexCoverage}% coverage` : undefined}
          />
        )}
        {quality.totalOptionCandles != null && (
          <QualityMetric
            label="OPTION CANDLES"
            value={fmtIN(quality.totalOptionCandles)}
          />
        )}
        {quality.totalOptionGreeks != null && (
          <QualityMetric
            label="OPTION GREEKS"
            value={fmtIN(quality.totalOptionGreeks)}
          />
        )}
        {quality.totalNiftyCandles != null && (
          <QualityMetric
            label="NIFTY CANDLES"
            value={fmtIN(quality.totalNiftyCandles)}
          />
        )}
        {quality.timestampsTotal != null && (
          <QualityMetric
            label="TIMESTAMPS"
            value={fmtIN(quality.timestampsTotal)}
            sub={timestampCoverage ? `${timestampCoverage}% with GEX` : undefined}
          />
        )}
      </div>

      {quality.generatedAt && (
        <div style={{ fontSize: 10, color: C.faint, marginTop: 12, textAlign: "center" }}>
          Generated: {new Date(quality.generatedAt).toLocaleString()}
        </div>
      )}
    </div>
  );
}
