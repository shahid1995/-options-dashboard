// =============================================================================
// StrikeNova Public Design System — Metric Primitive
// =============================================================================
// Renders a metric with label, value, unit, status, and source.
// Supports semantic data states: LIVE, DERIVED, DEMO, ILLUSTRATIVE,
// UNAVAILABLE, RESEARCH.
// =============================================================================

import React from "react";
import { COLOR, TYPE, DATA_STATE, SPACE } from "./tokens";

/**
 * formatMetricValue — formats a numeric metric value.
 * Returns null/undefined as "—" (unavailable indicator).
 */
export function formatMetricValue(value, decimals = 0) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isNaN(value)) return "—";
  if (typeof value === "number") {
    return value.toLocaleString("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  return String(value);
}

/**
 * Metric — a reusable metric display primitive.
 *
 * Props:
 *   label       — string (required)
 *   value       — number | string | null
 *   unit        — string (e.g. "%", "₹", "pts")
 *   decimals    — number (default 0)
 *   status      — keyof DATA_STATE | null
 *   source      — string (e.g. "NSE", "BSE", "DEMO")
 *   caption     — string (helper text below value)
 *   size        — 'sm' | 'md' | 'lg' | 'hero'
 *   color       — override value color
 *   style       — additional container styles
 */
export function Metric({
  label,
  value,
  unit,
  decimals = 0,
  status,
  source,
  caption,
  size = "md",
  color,
  style,
}) {
  const formattedValue = formatMetricValue(value, decimals);
  const isUnavailable = formattedValue === "—";

  // Size-based typography
  const sizeStyles = {
    sm: { valueFs: TYPE.dataSmall.size, labelFs: TYPE.caption.size },
    md: { valueFs: TYPE.data.size, labelFs: TYPE.label.size },
    lg: { valueFs: TYPE.dataLarge.size, labelFs: TYPE.label.size },
    hero: { valueFs: "clamp(1.5rem, 3vw, 2.5rem)", labelFs: TYPE.label.size },
  };
  const ss = sizeStyles[size] || sizeStyles.md;

  // Value color
  let valueColor = color || COLOR.textPrimary;
  if (!color && status && DATA_STATE[status]) {
    valueColor = DATA_STATE[status].label === "DEMO" || DATA_STATE[status].label === "ILLUSTRATIVE"
      ? COLOR.textMuted
      : DATA_STATE[status].color;
  }

  // Status indicator
  let statusEl = null;
  if (status && DATA_STATE[status]) {
    const ds = DATA_STATE[status];
    const isLive = status === "LIVE";
    statusEl = (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.25rem",
          fontSize: "0.625rem",
          fontWeight: 600,
          letterSpacing: "0.06em",
          color: ds.color,
          textTransform: "uppercase",
        }}
      >
        {isLive && (
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: ds.color,
              boxShadow: `0 0 6px ${ds.color}`,
              animation: "sn-pulse 1.6s ease-in-out infinite",
            }}
          />
        )}
        {ds.label}
      </span>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
        ...style,
      }}
    >
      {/* Label row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.375rem",
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontSize: ss.labelFs,
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
          }}
        >
          {label}
        </span>
        {statusEl}
        {source && (
          <span
            style={{
              fontSize: "0.625rem",
              color: COLOR.textFaint,
              fontWeight: 500,
            }}
          >
            {source}
          </span>
        )}
      </div>

      {/* Value row */}
      <div
        style={{
          fontSize: ss.valueFs,
          fontWeight: 700,
          color: isUnavailable ? COLOR.textFaint : valueColor,
          lineHeight: 1.1,
          fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
          fontVariantNumeric: "tabular-nums",
          display: "flex",
          alignItems: "baseline",
          gap: "0.25rem",
        }}
      >
        {formattedValue}
        {unit && (
          <span
            style={{
              fontSize: "0.7em",
              fontWeight: 600,
              color: COLOR.textMuted,
            }}
          >
            {unit}
          </span>
        )}
      </div>

      {/* Caption */}
      {caption && (
        <span
          style={{
            fontSize: "0.6875rem",
            color: COLOR.textFaint,
            lineHeight: 1.4,
          }}
        >
          {caption}
        </span>
      )}
    </div>
  );
}
