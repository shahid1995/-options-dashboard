// =============================================================================
// StrikeNova Public Design System — Signal Primitives
// =============================================================================
// Lightweight SVG/CSS-first primitives for Signal Field visualizations.
// These establish the building blocks that P2 will compose.
// No live data dependency. Reduced-motion compatible.
// =============================================================================

import React from "react";
import { COLOR, MOTION } from "./tokens";

/**
 * SignalLine — a horizontal or vertical technical line.
 * Used as a base layer for rails, dividers, and grid lines.
 */
export function SignalLine({
  orientation = "horizontal",
  color = COLOR.borderSubtle,
  length = "100%",
  strokeWidth = 1,
  dashed = false,
  style,
  ...rest
}) {
  const isH = orientation === "horizontal";
  return (
    <div
      style={{
        width: isH ? length : `${strokeWidth}px`,
        height: isH ? `${strokeWidth}px` : length,
        background: dashed ? "transparent" : color,
        backgroundImage: dashed
          ? isH
            ? `repeating-linear-gradient(90deg, ${color} 0, ${color} 4px, transparent 4px, transparent 8px)`
            : `repeating-linear-gradient(180deg, ${color} 0, ${color} 4px, transparent 4px, transparent 8px)`
          : "none",
        flexShrink: 0,
        ...style,
      }}
      aria-hidden="true"
      {...rest}
    />
  );
}

/**
 * SignalNode — a semantic marker used by Signal Field.
 * Renders a small circular node with optional label and value.
 * Accessible: includes text alongside the visual marker.
 */
export function SignalNode({
  label,
  value,
  x = 0,
  y = 0,
  color = COLOR.info,
  size = 8,
  pulsing = false,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: "translate(-50%, -50%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "0.25rem",
        ...style,
      }}
      role="img"
      aria-label={label && value ? `${label}: ${value}` : label || "Signal node"}
      {...rest}
    >
      {/* Visual marker */}
      <span
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: color,
          boxShadow: `0 0 0 3px ${color}26, 0 0 8px ${color}40`,
          animation: pulsing ? "sn-pulse 1.6s ease-in-out infinite" : "none",
          flexShrink: 0,
        }}
      />
      {/* Text label */}
      {label && (
        <span
          style={{
            fontSize: "0.625rem",
            fontWeight: 600,
            color: COLOR.textMuted,
            whiteSpace: "nowrap",
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {label}
        </span>
      )}
      {value && (
        <span
          style={{
            fontSize: "0.6875rem",
            fontWeight: 700,
            color: COLOR.textPrimary,
            whiteSpace: "nowrap",
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {value}
        </span>
      )}
    </div>
  );
}

/**
 * StrikeRail — a vertical rail showing strike/price levels.
 * Supports desktop (vertical) and mobile (horizontal) orientation.
 */
export function StrikeRail({
  strikes = [],
  spotIndex = null,
  orientation = "vertical",
  color = COLOR.textMuted,
  spotColor = COLOR.strategy,
  style,
  ...rest
}) {
  const isV = orientation === "vertical";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: isV ? "column" : "row",
        alignItems: "center",
        gap: "0.5rem",
        position: "relative",
        ...style,
      }}
      role="list"
      aria-label="Strike rail"
      {...rest}
    >
      {/* Rail line */}
      <SignalLine
        orientation={orientation}
        color={COLOR.borderSubtle}
        style={{ position: "absolute", top: isV ? "50%" : "auto", left: isV ? "auto" : "50%" }}
      />
      {/* Strike labels */}
      {strikes.map((strike, i) => {
        const isSpot = i === spotIndex;
        return (
          <span
            key={i}
            role="listitem"
            style={{
              fontSize: "0.75rem",
              fontWeight: isSpot ? 700 : 500,
              color: isSpot ? spotColor : color,
              fontFamily: "'JetBrains Mono', monospace",
              padding: isV ? "0.25rem 0" : "0 0.375rem",
              background: isSpot ? COLOR.strategyDim : "transparent",
              borderRadius: "4px",
              ...(isSpot ? { border: `1px solid ${spotColor}40` } : {}),
            }}
          >
            {typeof strike === "number" ? strike.toLocaleString("en-IN") : strike}
          </span>
        );
      })}
    </div>
  );
}

/**
 * DataTrace — a simple SVG path for drawing signal/data traces.
 * Used for payoff curves, signal paths, etc.
 */
export function DataTrace({
  pathD,
  color = COLOR.info,
  strokeWidth = 2,
  fill,
  animated = false,
  style,
  width = 600,
  height = 200,
  viewBox,
  ...rest
}) {
  const vb = viewBox || `0 0 ${width} ${height}`;
  return (
    <svg
      viewBox={vb}
      width="100%"
      height="auto"
      style={{ overflow: "visible", ...style }}
      aria-hidden="true"
      {...rest}
    >
      {fill && (
        <path d={pathD} fill={fill} stroke="none" />
      )}
      <path
        d={pathD}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={
          animated
            ? {
                strokeDasharray: "100%",
                strokeDashoffset: "100%",
                animation: `${MOTION.keyframes.traceDraw} 1.2s ${MOTION.signalTrace} both`,
              }
            : {}
        }
      />
    </svg>
  );
}

/**
 * TechnicalDivider — a horizontal divider with optional label.
 * More semantic than a bare <hr>.
 */
export function TechnicalDivider({
  label,
  color = COLOR.borderSubtle,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        width: "100%",
        ...style,
      }}
      {...rest}
    >
      <SignalLine orientation="horizontal" color={color} style={{ flex: 1 }} />
      {label && (
        <span
          style={{
            fontSize: "0.6875rem",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
      )}
      <SignalLine orientation="horizontal" color={color} style={{ flex: 1 }} />
    </div>
  );
}

/**
 * GridOverlay — a subtle grid background for visualization areas.
 * Pure CSS, no SVG overhead.
 */
export function GridOverlay({
  color = COLOR.borderSubtle,
  spacing = 40,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundImage: `
          repeating-linear-gradient(0deg, ${color} 0, ${color} 1px, transparent 1px, transparent ${spacing}px),
          repeating-linear-gradient(90deg, ${color} 0, ${color} 1px, transparent 1px, transparent ${spacing}px)
        `,
        opacity: 0.3,
        pointerEvents: "none",
        ...style,
      }}
      aria-hidden="true"
      {...rest}
    />
  );
}
