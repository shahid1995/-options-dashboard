// =============================================================================
// AnalyticalLayerGrid — 2×4 intelligence grid of analytical layers
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { useIsMobile } from "@/lib/ui";

const LAYERS = [
  {
    label: "PRICE",
    description: "Spot price and underlying movement",
    color: COLOR.signalPrice,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M3 14 L7 8 L11 11 L17 4" stroke={COLOR.signalPrice} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: "OPEN INTEREST",
    description: "Total outstanding contracts at each strike",
    color: COLOR.signalOi,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <rect x="3" y="10" width="3" height="7" fill={COLOR.signalOi} opacity="0.7" />
        <rect x="8" y="6" width="3" height="11" fill={COLOR.signalOi} opacity="0.85" />
        <rect x="13" y="3" width="3" height="14" fill={COLOR.signalOi} />
      </svg>
    ),
  },
  {
    label: "OI CHANGE",
    description: "Change in open interest — new positions vs closure",
    color: COLOR.info,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M4 13 L10 6 L16 13" stroke={COLOR.info} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: "VOLUME",
    description: "Contracts traded during the session",
    color: COLOR.textMuted,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M3 15 L7 9 L11 12 L17 5" stroke={COLOR.textMuted} strokeWidth="2" strokeLinecap="round" />
        <circle cx="17" cy="5" r="2" fill={COLOR.textMuted} />
      </svg>
    ),
  },
  {
    label: "IMPLIED VOLATILITY",
    description: "Market's expectation of future volatility",
    color: COLOR.signalIv,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M3 14 C6 6, 10 16, 13 7 C16 2, 17 10, 17 10" stroke={COLOR.signalIv} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    label: "GREEKS",
    description: "Delta, Gamma, Theta, Vega — sensitivity measures",
    color: COLOR.signalGreeks,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="10" r="7" stroke={COLOR.signalGreeks} strokeWidth="2" />
        <path d="M10 3 L10 10 L15 10" stroke={COLOR.signalGreeks} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    label: "MARKET STRUCTURE",
    description: "Support, resistance, pivot levels from chain data",
    color: COLOR.intelligence,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <line x1="3" y1="6" x2="17" y2="6" stroke={COLOR.intelligence} strokeWidth="1.5" strokeDasharray="2 2" />
        <line x1="3" y1="10" x2="17" y2="10" stroke={COLOR.intelligence} strokeWidth="2" />
        <line x1="3" y1="14" x2="17" y2="14" stroke={COLOR.intelligence} strokeWidth="1.5" strokeDasharray="2 2" />
      </svg>
    ),
  },
  {
    label: "MARKET STATE",
    description: "Synthesis of all layers into a coherent framework",
    color: COLOR.strategy,
    glyph: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <polygon points="10,3 17,17 3,17" stroke={COLOR.strategy} strokeWidth="2" fill="none" strokeLinejoin="round" />
        <circle cx="10" cy="12" r="2" fill={COLOR.strategy} />
      </svg>
    ),
  },
];

export default function AnalyticalLayerGrid() {
  const isMobile = useIsMobile();

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
        gap: SPACE.compLg,
      }}
    >
      {LAYERS.map((layer) => (
        <div
          key={layer.label}
          style={{
            background: COLOR.surface,
            border: `1px solid ${COLOR.border}`,
            borderRadius: RADIUS.lg,
            padding: SPACE.card,
            display: "flex",
            alignItems: "flex-start",
            gap: SPACE.comp,
            transition: "transform 0.18s, border-color 0.18s",
            cursor: "default",
          }}
          className="od-card"
        >
          {/* Glyph */}
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: RADIUS.md,
              background: `${layer.color}15`,
              border: `1px solid ${layer.color}30`,
              display: "grid",
              placeItems: "center",
              flexShrink: 0,
            }}
          >
            {layer.glyph}
          </div>

          {/* Content */}
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: TYPE.label.size,
                fontWeight: 700,
                color: layer.color,
                marginBottom: SPACE.xs,
              }}
            >
              {layer.label}
            </div>
            <div
              style={{
                fontSize: TYPE.bodySmall.size,
                color: COLOR.textMuted,
                lineHeight: 1.5,
              }}
            >
              {layer.description}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
