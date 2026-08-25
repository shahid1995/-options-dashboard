/**
 * GEX Profile Chart — Live GEX visualization for the dashboard.
 *
 * Displays a horizontal bar chart of per-strike Net GEX using Recharts.
 * Positive GEX extends right (green), negative extends left (red).
 *
 * Requires live chain data via useGexCapture → latestSnapshot.strikeData.
 * Optional sweep data (enableSweep in useGexCapture) shows gamma flip and walls.
 *
 * No trading signals. Market-structure analytics only.
 */
"use client";

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

/* ── Helpers ────────────────────────────────────────────────────────── */

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function GexMetric({ label, value, color }) {
  return (
    <div
      style={{
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: "8px 10px",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: 0.8,
          color: C.faint,
          fontWeight: 700,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 13,
          fontWeight: 800,
          color: color || C.text,
          marginTop: 2,
          whiteSpace: "nowrap",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
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
      <div
        style={{
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
        }}
      >
        <div
          style={{
            padding: "10px 14px",
            borderBottom: `1px solid ${C.border}`,
            fontSize: 12,
            color: C.muted,
            letterSpacing: 0.5,
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>GEX PROFILE</span>
        </div>
        <div
          style={{
            padding: "24px 16px",
            textAlign: "center",
            fontSize: 12,
            color: C.faint,
          }}
        >
          GEX data unavailable — waiting for live chain with gamma &amp; OI.
        </div>
      </div>
    );
  }

  /* ── Render ─────────────────────────────────────────────────────── */

  return (
    <div
      style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "10px 14px",
          borderBottom: `1px solid ${C.border}`,
          fontSize: 12,
          color: C.muted,
          letterSpacing: 0.5,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>GEX PROFILE</span>
        {expiry && (
          <span style={{ color: C.faint, fontSize: 10 }}>
            {expiry} · {fmtIN(spot, 2)}
          </span>
        )}
      </div>

      {/* Summary metrics */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 6,
          padding: "8px 10px",
        }}
      >
        <GexMetric
          label="NET GEX"
          value={fmtGex(netGex)}
          color={netGex != null ? (netGex >= 0 ? C.green : C.red) : C.muted}
        />
        <GexMetric label="ATM" value={atmStrike != null ? fmtIN(atmStrike) : "—"} color={C.gold} />
        <GexMetric label="CALL GEX" value={fmtGex(callGex)} color={callGex != null ? C.green : C.muted} />
        <GexMetric label="PUT GEX" value={fmtGex(putGex)} color={putGex != null ? C.red : C.muted} />
        {gammaFlipSpot != null && (
          <GexMetric label="GAMMA FLIP" value={fmtIN(gammaFlipSpot)} color={C.gold} />
        )}
        {profileLabels.length > 0 && profileLabels[0] !== "UNAVAILABLE" && (
          <GexMetric label="REGIME" value={profileLabels[0].replace(/_/g, " ")} color={C.gold} />
        )}
        {callWallStrikes.length > 0 && (
          <GexMetric
            label="CALL WALL"
            value={callWallStrikes.map(fmtIN).join(", ")}
            color={C.green}
          />
        )}
        {putWallStrikes.length > 0 && (
          <GexMetric
            label="PUT WALL"
            value={putWallStrikes.map(fmtIN).join(", ")}
            color={C.red}
          />
        )}
      </div>

      {/* Chart */}
      <div style={{ padding: "4px 4px 0 4px" }}>
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

              {/* Gamma flip line */}
              {gammaFlipSpot != null && (
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
      </div>

      {/* Legend */}
      <div
        style={{
          padding: "6px 14px 10px",
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
        {gammaFlipSpot != null && (
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
    </div>
  );
}
