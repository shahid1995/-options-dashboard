// =============================================================================
// MarketIntelligenceGrid — 2×2 premium data panels with micro-visuals
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { useIsMobile } from "@/lib/ui";

const PANELS = [
  {
    label: "POSITIONING",
    color: COLOR.signalOi,
    description: "Track open interest distribution across strikes to identify where market participants are positioned.",
    visual: (
      <div style={{ display: "flex", alignItems: "flex-end", gap: "0.25rem", height: 40 }}>
        {[30, 50, 75, 90, 65, 40, 55].map((h, i) => (
          <div key={i} style={{ width: "100%", height: `${h}%`, background: COLOR.signalOi, opacity: 0.7, borderRadius: "2px 2px 0 0" }} />
        ))}
      </div>
    ),
  },
  {
    label: "VOLATILITY",
    color: COLOR.signalIv,
    description: "Analyze implied volatility across strikes and expiries to understand how the market prices risk.",
    visual: (
      <svg width="100%" height="40" viewBox="0 0 200 40" preserveAspectRatio="none">
        <path d="M0 30 C40 10, 80 35, 120 15 C160 5, 180 20, 200 25" fill="none" stroke={COLOR.signalIv} strokeWidth="2" />
      </svg>
    ),
  },
  {
    label: "GREEKS",
    color: COLOR.signalGreeks,
    description: "Delta, gamma, theta and vega computed for every option in the chain.",
    visual: (
      <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center" }}>
        {[
          { l: "Δ", v: "-0.02" },
          { l: "Γ", v: "0.0003" },
          { l: "Θ", v: "+42" },
          { l: "V", v: "-18" },
        ].map((g) => (
          <div key={g.l} style={{ textAlign: "center" }}>
            <div style={{ fontSize: "0.75rem", color: COLOR.textFaint }}>{g.l}</div>
            <div style={{ fontSize: "0.6875rem", color: COLOR.textPrimary, fontFamily: TYPE.data }}>{g.v}</div>
          </div>
        ))}
      </div>
    ),
  },
  {
    label: "STRUCTURE",
    color: COLOR.intelligence,
    description: "Identify resistance, support and pivot levels derived from option chain data.",
    visual: (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        {[
          { l: "R", v: "25,700", c: COLOR.negative },
          { l: "P", v: "25,500", c: COLOR.strategy },
          { l: "S", v: "25,300", c: COLOR.positive },
        ].map((level) => (
          <div key={level.l} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.625rem", color: level.c, fontWeight: 700, width: 12 }}>{level.l}</span>
            <div style={{ flex: 1, height: 1, background: `${level.c}40` }} />
            <span style={{ fontSize: "0.625rem", color: COLOR.textFaint, fontFamily: TYPE.data }}>{level.v}</span>
          </div>
        ))}
      </div>
    ),
  },
];

export default function MarketIntelligenceGrid() {
  const isMobile = useIsMobile();

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
        gap: SPACE.cardLg,
      }}
    >
      {PANELS.map((panel) => (
        <div
          key={panel.label}
          style={{
            background: COLOR.surface,
            border: `1px solid ${COLOR.border}`,
            borderRadius: RADIUS.lg,
            padding: SPACE.cardLg,
            transition: "transform 0.18s, border-color 0.18s",
          }}
          className="od-card"
        >
          <div
            style={{
              fontSize: TYPE.label.size,
              fontWeight: 700,
              color: panel.color,
              marginBottom: SPACE.comp,
            }}
          >
            {panel.label}
          </div>
          <div style={{ marginBottom: SPACE.comp }}>{panel.visual}</div>
          <p
            style={{
              fontSize: TYPE.bodySmall.size,
              color: COLOR.textMuted,
              lineHeight: 1.6,
              margin: 0,
            }}
          >
            {panel.description}
          </p>
        </div>
      ))}
    </div>
  );
}
