"use client";
/**
 * GEX Profile Chart — Phase E (Market Intelligence)
 *
 * Horizontal bar chart of per-strike Net GEX using Recharts.
 * Positive GEX extends right (green), negative extends left (red).
 *
 * Uses Phase D primitives: ChartContainer, Metric, EmptyState, ErrorState.
 *
 * No trading signals. Market-structure analytics only.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { ChartContainer, Metric, EmptyState } from "@/components/app/core";

/* ── Helpers ────────────────────────────────────────────────────────── */

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/* ── Custom bar shape: horizontal bar centered at zero ──────────────── */

function HorizontalGexBar(props) {
  const { x, y, width, height, value } = props;
  if (value == null || !Number.isFinite(value)) return null;
  const zeroX = x + width / 2;
  const absW = Math.abs(value);
  const maxHalf = width / 2;
  const barW = Math.min(absW, maxHalf);
  const isPos = value >= 0;
  const barX = isPos ? zeroX : zeroX - barW;
  const fill = isPos ? C.green : C.red;
  return (
    <rect
      x={barX}
      y={y}
      width={Math.max(barW, 1)}
      height={height}
      fill={fill}
      rx={2}
    />
  );
}

/* ── Custom tooltip ─────────────────────────────────────────────────── */

function GexTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div
      style={{
        background: "#0F131B",
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 11,
        lineHeight: 1.6,
        color: C.text,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 3, color: C.gold }}>
        Strike {fmtIN(label)}
      </div>
      {d.callGex != null && (
        <div>
          Call: <span style={{ color: C.green }}>{fmtGex(d.callGex)}</span>
        </div>
      )}
      {d.putGex != null && (
        <div>
          Put: <span style={{ color: C.red }}>{fmtGex(d.putGex)}</span>
        </div>
      )}
      {d.netGex != null && (
        <div>
          Net:{" "}
          <span style={{ color: d.netGex >= 0 ? C.green : C.red, fontWeight: 700 }}>
            {fmtGex(d.netGex)}
          </span>
        </div>
      )}
    </div>
  );
}

/* ── Main Component ─────────────────────────────────────────────────── */

/**
 * @param {object} props
 * @param {object|null} props.analytics — output of computeGexAnalytics (from useGexCapture)
 * @param {object|null} props.latestSnapshot — snapshot from useGexCapture (has strikeData, sweepData)
 * @param {number|null} props.atmStrike — closest strike to spot (computed by dashboard)
 * @param {boolean} [props.isMobile] — mobile layout flag
 */
export default function GexProfileChart({
  analytics,
  latestSnapshot,
  atmStrike,
  isMobile = false,
}) {
  /* ── Extract data from existing GEX structures ──────────────────── */

  const spot = latestSnapshot?.spot ?? analytics?.current?.spot ?? null;
  const expiry = latestSnapshot?.expiry ?? analytics?.current?.expiry ?? null;

  const netGex = analytics?.current?.netGex ?? latestSnapshot?.netGex ?? null;
  const callGex = analytics?.current?.callGex ?? latestSnapshot?.callGex ?? null;
  const putGex = analytics?.current?.putGex ?? latestSnapshot?.putGex ?? null;

  const profileLabels = analytics?.profileLabel?.labels ?? [];

  const sweep = latestSnapshot?.sweepData ?? null;
  const gammaFlipSpot = sweep?.gammaFlipSpot ?? null;
  const callWallStrikes = sweep?.callWallStrikes ?? [];
  const putWallStrikes = sweep?.putWallStrikes ?? [];

  const strikeData = latestSnapshot?.strikeData ?? [];

  /* ── Prepare chart data (sorted by strike ascending) ────────────── */

  const chartData = useMemo(() => {
    if (!strikeData.length) return [];
    return strikeData
      .filter(
        (s) =>
          (s.callGex != null && Number.isFinite(s.callGex)) ||
          (s.putGex != null && Number.isFinite(s.putGex)) ||
          (s.netGex != null && Number.isFinite(s.netGex))
      )
      .sort((a, b) => a.strike - b.strike)
      .map((s) => ({
        strike: s.strike,
        callGex: s.callGex,
        putGex: s.putGex,
        netGex: s.netGex,
      }));
  }, [strikeData]);

  /* ── Symmetric domain around zero ───────────────────────────────── */

  const domain = useMemo(() => {
    if (!chartData.length) return [-1, 1];
    let maxAbs = 0;
    for (const d of chartData) {
      const v = Math.abs(d.netGex ?? 0);
      if (v > maxAbs) maxAbs = v;
    }
    return [-maxAbs || -1, maxAbs || 1];
  }, [chartData]);

  /* ── Empty state ────────────────────────────────────────────────── */

  if (!chartData.length) {
    return (
      <ChartContainer
        title="GEX PROFILE"
        eyebrow="MARKET STRUCTURE"
        caption="Dealer positioning context · Not a directional signal"
        source={expiry ? `${expiry} · Spot ${spot ? fmtIN(spot, 2) : "—"}` : undefined}
      >
        <EmptyState message="GEX data unavailable — waiting for live chain with gamma & OI." />
      </ChartContainer>
    );
  }

  /* ── Render ─────────────────────────────────────────────────────── */

  const hasGammaFlip = gammaFlipSpot != null;
  const hasWalls = callWallStrikes.length > 0 || putWallStrikes.length > 0;

  return (
    <ChartContainer
      title="GEX PROFILE"
      eyebrow="MARKET STRUCTURE"
      caption="Call GEX (+) dealer long gamma · Put GEX (−) dealer short gamma"
      source={expiry ? `${expiry} · Spot ${fmtIN(spot, 2)}` : undefined}
    >
      {/* Summary metrics using Phase D Metric primitive */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(auto-fill, minmax(120px, 1fr))",
          gap: 8,
          padding: "0 4px 12px",
        }}
      >
        <Metric
          label="NET GEX"
          value={fmtGex(netGex)}
          size="md"
          semantic={netGex != null ? (netGex >= 0 ? "positive" : "negative") : "neutral"}
          hint="Aggregate dealer gamma exposure"
        />
        <Metric
          label="ATM"
          value={atmStrike != null ? fmtIN(atmStrike) : "—"}
          size="md"
          semantic="strategy"
          hint="At-the-money strike"
        />
        <Metric
          label="CALL GEX"
          value={fmtGex(callGex)}
          size="sm"
          semantic={callGex != null ? "positive" : "neutral"}
          hint="Total call-side dealer gamma"
        />
        <Metric
          label="PUT GEX"
          value={fmtGex(putGex)}
          size="sm"
          semantic={putGex != null ? "negative" : "neutral"}
          hint="Total put-side dealer gamma"
        />
        {hasGammaFlip && (
          <Metric
            label="GAMMA FLIP"
            value={fmtIN(gammaFlipSpot)}
            size="sm"
            semantic="strategy"
            hint="Modeled regime transition level"
          />
        )}
        {profileLabels.length > 0 && profileLabels[0] !== "UNAVAILABLE" && (
          <Metric
            label="REGIME"
            value={profileLabels[0].replace(/_/g, " ")}
            size="sm"
            semantic="strategy"
            hint="Current modeled gamma regime"
          />
        )}
        {callWallStrikes.length > 0 && (
          <Metric
            label="CALL WALL"
            value={callWallStrikes.map(fmtIN).join(", ")}
            size="sm"
            semantic="positive"
            hint="Highest call-side GEX concentration"
          />
        )}
        {putWallStrikes.length > 0 && (
          <Metric
            label="PUT WALL"
            value={putWallStrikes.map(fmtIN).join(", ")}
            size="sm"
            semantic="negative"
            hint="Highest put-side GEX concentration"
          />
        )}
      </div>

      {/* Chart */}
      <div style={{ height: isMobile ? 320 : 380 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 4, right: 12, bottom: 4, left: 4 }}
          >
            <XAxis
              type="number"
              domain={domain}
              tick={{ fill: C.faint, fontSize: 9 }}
              tickFormatter={fmtGex}
              stroke={C.border}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="strike"
              tick={{ fill: C.muted, fontSize: 10 }}
              tickFormatter={(v) => fmtIN(v)}
              width={isMobile ? 48 : 56}
              stroke={C.border}
              tickLine={false}
            />
            <Tooltip
              content={<GexTooltip />}
              cursor={{ fill: "rgba(201,161,90,0.06)" }}
            />

            {/* Zero-GEX line */}
            <ReferenceLine
              x={0}
              stroke={C.muted}
              strokeDasharray="3 3"
              strokeWidth={1}
            />

            {/* ATM strike line */}
            {atmStrike != null && chartData.some((d) => d.strike === atmStrike) && (
              <ReferenceLine
                y={atmStrike}
                stroke={C.gold}
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{
                  value: "ATM",
                  fill: C.gold,
                  fontSize: 9,
                  position: "right",
                }}
              />
            )}

            {/* Gamma flip annotation */}
            {hasGammaFlip && (
              <ReferenceLine
                x={0}
                stroke={C.gold}
                strokeWidth={0}
                label={{
                  value: `Flip ${fmtIN(gammaFlipSpot)}`,
                  fill: C.gold,
                  fontSize: 9,
                  position: "insideTopRight",
                }}
              />
            )}

            {/* Net GEX bars */}
            <Bar
              dataKey="netGex"
              shape={<HorizontalGexBar />}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div
        style={{
          padding: "6px 14px 0",
          fontSize: 9.5,
          color: C.faint,
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>
          <span style={{ display: "inline-block", width: 8, height: 8, background: C.green, borderRadius: 2, marginRight: 4, verticalAlign: "middle" }} />
          Call GEX (+)
        </span>
        <span>
          <span style={{ display: "inline-block", width: 8, height: 8, background: C.red, borderRadius: 2, marginRight: 4, verticalAlign: "middle" }} />
          Put GEX (−)
        </span>
        {hasGammaFlip && (
          <span>
            <span style={{ display: "inline-block", width: 8, height: 2, background: C.gold, marginRight: 4, verticalAlign: "middle" }} />
            Gamma Flip
          </span>
        )}
        {callWallStrikes.length > 0 && (
          <span style={{ color: C.green }}>■ Call Wall</span>
        )}
        {putWallStrikes.length > 0 && (
          <span style={{ color: C.red }}>■ Put Wall</span>
        )}
      </div>
    </ChartContainer>
  );
}
