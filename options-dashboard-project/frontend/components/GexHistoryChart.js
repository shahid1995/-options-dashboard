"use client";
/**
 * GEX Historical Time-Series Chart — Phase 8D
 *
 * Displays net GEX over time using Recharts LineChart.
 * Uses /gex/history endpoint data.
 *
 * No directional interpretation. Structural analytics only.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import { AppPanel, SectionTitle } from "@/components/app/styles";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)} L`;
  return `${sign}${fmtIN(v)}`;
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
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
      <div style={{ fontWeight: 700, marginBottom: 2, color: C.gold }}>
        {fmtTime(d.timestamp)}
      </div>
      <div>
        Net GEX: <span style={{ color: d.netGex >= 0 ? C.green : C.red }}>{fmtGex(d.netGex)}</span>
      </div>
      <div>
        Call: <span style={{ color: C.green }}>{fmtGex(d.callGex)}</span>
      </div>
      <div>
        Put: <span style={{ color: C.red }}>{fmtGex(d.putGex)}</span>
      </div>
      <div style={{ color: C.faint }}>Spot: {fmtIN(d.spot, 2)}</div>
    </div>
  );
}

export default function GexHistoryChart({ data, isMobile = false }) {
  const chartData = useMemo(() => {
    if (!data?.timestamps) return [];
    return data.timestamps.map((t) => ({
      timestamp: t.timestamp,
      netGex: t.netGex,
      callGex: t.callGex,
      putGex: t.putGex,
      spot: t.spot,
      absoluteGex: t.absoluteGex,
    }));
  }, [data]);

  if (!chartData.length) {
    return (
      <div style={AppPanel}>
        <div style={SectionTitle}>HISTORICAL GEX</div>
        <div style={{ padding: 24, textAlign: "center", color: C.muted, fontSize: 12 }}>
          No historical GEX data available.
        </div>
      </div>
    );
  }

  return (
    <div style={AppPanel}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <div style={SectionTitle}>HISTORICAL NET GEX</div>
        <div style={{ fontSize: 10, color: C.faint }}>
          {chartData.length} timestamps
        </div>
      </div>

      <ResponsiveContainer width="100%" height={isMobile ? 250 : 350}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={fmtTime}
            stroke={C.faint}
            fontSize={10}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v) => fmtGex(v)}
            stroke={C.faint}
            fontSize={10}
            tickLine={false}
            width={80}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={0} stroke={C.border} strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="netGex"
            stroke={C.gold}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: C.gold }}
          />
        </LineChart>
      </ResponsiveContainer>

      <div style={{ fontSize: 10, color: C.faint, marginTop: 8, textAlign: "center" }}>
        Net GEX = Call GEX (+) + Put GEX (−) · Not a trading signal
      </div>
    </div>
  );
}
