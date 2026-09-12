// =============================================================================
// SignalMetricOverview — Key indicators + Greeks + demo labeling
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { DemoLabel } from "@/components/public/truth";
import { useIsMobile } from "@/lib/ui";

const KEY_METRICS = [
  { label: "SPOT", value: "25,500" },
  { label: "PCR", value: "0.92" },
  { label: "ATM IV", value: "14.2%" },
  { label: "ΔOI", value: "+8.4%" },
];

const GREEKS = [
  { name: "Delta", label: "DELTA", value: "-0.02", desc: "Price sensitivity" },
  { name: "Gamma", label: "GAMMA", value: "0.0003", desc: "Delta change" },
  { name: "Theta", label: "THETA", value: "+42.15", desc: "Time decay" },
  { name: "Vega", label: "VEGA", value: "-18.40", desc: "Volatility sensitivity" },
];

export default function SignalMetricOverview() {
  const isMobile = useIsMobile();

  return (
    <div
      style={{
        background: COLOR.surface,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.xl,
        padding: isMobile ? SPACE.card : SPACE.cardLg,
      }}
    >
      {/* Key indicators */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
          gap: SPACE.comp,
          marginBottom: SPACE.cardLg,
        }}
      >
        {KEY_METRICS.map((m) => (
          <div
            key={m.label}
            style={{
              background: COLOR.baseElevated,
              border: `1px solid ${COLOR.borderSubtle}`,
              borderRadius: RADIUS.md,
              padding: SPACE.comp,
            }}
          >
            <div
              style={{
                fontSize: TYPE.caption.size,
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                textTransform: "uppercase",
                marginBottom: SPACE.xs,
              }}
            >
              {m.label}
            </div>
            <div
              style={{
                fontSize: TYPE.data.size,
                fontWeight: 700,
                color: COLOR.textPrimary,
                fontFamily: TYPE.data,
              }}
            >
              {m.value}
            </div>
          </div>
        ))}
      </div>

      {/* Signal visualization area */}
      <div
        style={{
          background: COLOR.baseElevated,
          border: `1px solid ${COLOR.borderSubtle}`,
          borderRadius: RADIUS.md,
          padding: SPACE.card,
          marginBottom: SPACE.cardLg,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.textFaint,
            marginBottom: SPACE.comp,
          }}
        >
          SIGNAL VISUALIZATION
        </div>
        {/* Mini OI bars */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: "0.25rem",
            height: 80,
            justifyContent: "center",
          }}
        >
          {[40, 65, 85, 70, 55, 90, 75, 50].map((h, i) => (
            <div
              key={i}
              style={{
                width: "100%",
                height: `${h}%`,
                background: i < 4 ? COLOR.negative : COLOR.positive,
                opacity: 0.7,
                borderRadius: "2px 2px 0 0",
              }}
            />
          ))}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: SPACE.xs,
          }}
        >
          {[25.3, 25.4, 25.5, 25.6, 25.7].map((s) => (
            <span
              key={s}
              style={{ fontSize: "0.625rem", color: COLOR.textFaint, fontFamily: TYPE.data }}
            >
              {s}k
            </span>
          ))}
        </div>
      </div>

      {/* Greeks */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: SPACE.comp,
          marginBottom: SPACE.cardLg,
        }}
      >
        {GREEKS.map((g) => (
          <div key={g.label}>
            <div
              style={{
                fontSize: TYPE.caption.size,
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                textTransform: "uppercase",
                marginBottom: SPACE.xs,
              }}
            >
              {g.name}
            </div>
            <div
              style={{
                fontSize: TYPE.data.size,
                fontWeight: 700,
                color: COLOR.textPrimary,
                fontFamily: TYPE.data,
              }}
            >
              {g.value}
            </div>
            <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint }}>{g.desc}</div>
          </div>
        ))}
      </div>

      {/* Demo label */}
      <div style={{ textAlign: "center" }}>
        <DemoLabel style={{ fontSize: "0.625rem" }} />
      </div>
    </div>
  );
}
