// =============================================================================
// StrikeNova Public Design System — VisualizationFrame
// =============================================================================
// A reusable frame for Signal Field visualizations, charts, and analytical
// displays. Wraps the visual area with title, eyebrow, caption, legend,
// and demo-data label.
// =============================================================================

import React from "react";
import { COLOR, SPACE, TYPE } from "./tokens";

/**
 * VisualizationFrame — a container for public visualizations.
 *
 * Props:
 *   eyebrow       — small label above title (e.g. "SIGNAL FIELD")
 *   title         — main title string
 *   caption       — helper text below the visual
 *   legend        — array of { label, color } objects
 *   demoLabel     — boolean, show "DEMO DATA" badge
 *   children      — the visualization content
 *   style         — additional container styles
 */
export function VisualizationFrame({
  eyebrow,
  title,
  caption,
  legend,
  demoLabel = false,
  children,
  style,
}) {
  return (
    <div
      style={{
        background: COLOR.baseElevated,
        border: `1px solid ${COLOR.border}`,
        borderRadius: "16px",
        padding: SPACE.cardLg,
        display: "flex",
        flexDirection: "column",
        gap: SPACE.comp,
        position: "relative",
        overflow: "hidden",
        ...style,
      }}
      role="figure"
      aria-label={title ? `Visualization: ${title}` : "Data visualization"}
    >
      {/* Header */}
      {(eyebrow || title) && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
          {eyebrow && (
            <span
              style={{
                fontSize: TYPE.caption.size,
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: COLOR.textFaint,
                textTransform: "uppercase",
              }}
            >
              {eyebrow}
            </span>
          )}
          {title && (
            <h3
              style={{
                fontSize: TYPE.h3.size,
                fontWeight: 700,
                color: COLOR.textPrimary,
                margin: 0,
                letterSpacing: "-0.01em",
              }}
            >
              {title}
            </h3>
          )}
        </div>
      )}

      {/* Visual area */}
      <div style={{ position: "relative", minHeight: "120px" }}>
        {children}
      </div>

      {/* Legend */}
      {legend && legend.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            paddingTop: "0.75rem",
            borderTop: `1px solid ${COLOR.borderSubtle}`,
          }}
        >
          {legend.map((item, i) => (
            <span
              key={i}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.375rem",
                fontSize: "0.75rem",
                color: COLOR.textMuted,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: item.color,
                  flexShrink: 0,
                }}
              />
              {item.label}
            </span>
          ))}
        </div>
      )}

      {/* Caption */}
      {caption && (
        <p
          style={{
            fontSize: "0.75rem",
            color: COLOR.textFaint,
            lineHeight: 1.5,
            margin: 0,
          }}
        >
          {caption}
        </p>
      )}

      {/* Demo label */}
      {demoLabel && (
        <div
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            fontSize: "0.625rem",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.warning,
            background: COLOR.warningDim,
            border: `1px solid ${COLOR.warning}40`,
            borderRadius: "4px",
            padding: "0.125rem 0.5rem",
            textTransform: "uppercase",
          }}
        >
          Demo Data
        </div>
      )}
    </div>
  );
}
