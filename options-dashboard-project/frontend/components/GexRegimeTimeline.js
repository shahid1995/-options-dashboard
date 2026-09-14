"use client";
/**
 * Gamma Regime Timeline — Phase E (Market Intelligence)
 *
 * Displays gamma regime transitions (POSITIVE_GAMMA, NEGATIVE_GAMMA, NEUTRAL)
 * as a horizontal timeline using Recharts.
 *
 * Uses /gex/regime endpoint data.
 * No directional interpretation. Structural positioning context only.
 *
 * Uses Phase D primitives: ChartContainer, EmptyState.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { ChartContainer, EmptyState } from "@/components/app/core";

const REGIME_COLORS = {
  POSITIVE_GAMMA: C.green,
  NEGATIVE_GAMMA: C.red,
  NEUTRAL: C.muted,
};

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)} L`;
  return `${sign}${fmtIN(v)}`;
}

function RegimeTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const color = REGIME_COLORS[d.regime] || C.muted;
  return (
    <div
      style={{
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 11,
        lineHeight: 1.6,
        color: C.text,
      }}
    >
      <div style={{ fontWeight: 700, color: C.gold }}>{fmtTime(d.timestamp)}</div>
      <div style={{ color, fontWeight: 700 }}>
        {d.regime.replace(/_/g, " ")}
      </div>
      <div>Net GEX: {fmtGex(d.netGex)}</div>
      <div>Spot: {fmtIN(d.spot, 2)}</div>
      {d.regimeTransition && (
        <div style={{ color: C.faint }}>Transition: {d.regimeTransition}</div>
      )}
      <div style={{ color: C.faint }}>Duration: {d.regimeDuration} periods</div>
    </div>
  );
}

export default function GexRegimeTimeline({ data, isMobile = false }) {
  const chartData = useMemo(() => {
    if (!data?.regimes) return [];
    return data.regimes.map((r) => ({
      timestamp: r.timestamp,
      regime: r.regime,
      netGex: r.netGex,
      spot: r.spot,
      regimeTransition: r.regimeTransition,
      regimeDuration: r.regimeDuration,
      regimeValue:
        r.regime === "POSITIVE_GAMMA" ? 1 : r.regime === "NEGATIVE_GAMMA" ? -1 : 0,
    }));
  }, [data]);

  if (!chartData.length) {
    return (
      <ChartContainer
        title="GAMMA REGIME TIMELINE"
        eyebrow="STRUCTURAL CONTEXT"
        caption="Regime = sign of aggregate Net GEX · Structural context, not directional signal"
      >
        <EmptyState message="No regime data available." />
      </ChartContainer>
    );
  }

  // Count transitions
  const transitions = chartData.filter((d) => d.regimeTransition).length;
  const currentRegime = chartData[chartData.length - 1]?.regime;

  return (
    <ChartContainer
      title="GAMMA REGIME TIMELINE"
      eyebrow="STRUCTURAL CONTEXT"
      caption="Regime = sign of aggregate Net GEX · Structural context, not directional signal"
      source={currentRegime ? `Current: ${currentRegime.replace(/_/g, " ")} · ${transitions} transitions` : undefined}
    >
      {/* Current regime indicator */}
      {currentRegime && (
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
          <div style={{ fontSize: 14, fontWeight: 800, color: REGIME_COLORS[currentRegime] || C.muted }}>
            Current: {currentRegime.replace(/_/g, " ")}
            <span style={{ fontSize: 11, fontWeight: 400, color: C.faint, marginLeft: 8 }}>
              {transitions} transitions
            </span>
          </div>
          <div style={{ display: "flex", gap: 12, fontSize: 10 }}>
            {Object.entries(REGIME_COLORS).map(([regime, color]) => (
              <span key={regime} style={{ color, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: "inline-block" }} />
                {regime.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
      )}

      <div style={{ height: isMobile ? 200 : 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
            <XAxis
              dataKey="timestamp"
              tickFormatter={fmtTime}
              stroke={C.faint}
              fontSize={10}
              tickLine={false}
            />
            <YAxis
              domain={[-1.5, 1.5]}
              ticks={[-1, 0, 1]}
              tickFormatter={(v) =>
                v === 1 ? "POS" : v === -1 ? "NEG" : "NEU"
              }
              stroke={C.faint}
              fontSize={10}
              tickLine={false}
              width={40}
            />
            <Tooltip content={<RegimeTooltip />} />
            <Bar dataKey="regimeValue" radius={[2, 2, 2, 2]}>
              {chartData.map((entry, i) => (
                <Cell
                  key={i}
                  fill={REGIME_COLORS[entry.regime] || C.muted}
                  fillOpacity={0.7}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartContainer>
  );
}
