// =============================================================================
// StrikeNova Public Design System — Truth & Label Primitives
// =============================================================================
// Demo label, research status badge, and data classification components.
// Makes it easy to clearly mark illustrative information.
// =============================================================================

import React from "react";
import { COLOR, RESEARCH_STATUS, DATA_STATE, TYPE } from "./tokens";

/**
 * DemoLabel — a reusable "DEMO DATA · ILLUSTRATIVE VALUES ONLY" badge.
 * Use on any visualization or metric that uses fictional data.
 */
export function DemoLabel({ style, ...rest }) {
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "0.6875rem",
        fontWeight: 600,
        letterSpacing: "0.06em",
        color: COLOR.warning,
        background: COLOR.warningDim,
        border: `1px solid ${COLOR.warning}40`,
        borderRadius: "4px",
        padding: "0.125rem 0.625rem",
        textTransform: "uppercase",
        ...style,
      }}
      {...rest}
    >
      Demo Data · Illustrative Values Only
    </span>
  );
}

/**
 * ResearchBadge — a badge for future/research capabilities.
 * Supports: AVAILABLE, COMING_LATER, RESEARCH_DIRECTION
 */
export function ResearchBadge({ status = "RESEARCH_DIRECTION", style, ...rest }) {
  const s = RESEARCH_STATUS[status] || RESEARCH_STATUS.RESEARCH_DIRECTION;
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "0.6875rem",
        fontWeight: 600,
        letterSpacing: "0.06em",
        color: s.color,
        background: `${s.color}15`,
        border: `1px solid ${s.color}30`,
        borderRadius: "4px",
        padding: "0.125rem 0.625rem",
        textTransform: "uppercase",
        ...style,
      }}
      {...rest}
    >
      {s.label}
    </span>
  );
}

/**
 * DataStateBadge — a badge showing the data classification state.
 * LIVE, DERIVED, DEMO, ILLUSTRATIVE, UNAVAILABLE, RESEARCH
 */
export function DataStateBadge({ state, style, ...rest }) {
  const s = DATA_STATE[state];
  if (!s) return null;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.25rem",
        fontSize: "0.625rem",
        fontWeight: 600,
        letterSpacing: "0.06em",
        color: s.color,
        textTransform: "uppercase",
        ...style,
      }}
      {...rest}
    >
      {state === "LIVE" && (
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: s.color,
            boxShadow: `0 0 4px ${s.color}`,
            animation: "sn-pulse 1.6s ease-in-out infinite",
          }}
        />
      )}
      {s.label}
    </span>
  );
}

/**
 * Eyebrow — a small uppercase label used above section headings.
 * Common pattern: "SIGNAL FIELD", "THE PROBLEM", etc.
 */
export function Eyebrow({ children, color = COLOR.textFaint, style, ...rest }) {
  return (
    <span
      style={{
        fontSize: TYPE.caption.size,
        fontWeight: 600,
        letterSpacing: "0.08em",
        color,
        textTransform: "uppercase",
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}

/**
 * SectionTitle — a semantic section heading with optional eyebrow.
 */
export function SectionTitle({
  eyebrow,
  title,
  subtitle,
  align = "center",
  style,
  ...rest
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        textAlign: align,
        maxWidth: "40rem",
        margin: align === "center" ? "0 auto 2.75rem" : "0 0 2.75rem",
        ...style,
      }}
      {...rest}
    >
      {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
      {title && (
        <h2
          style={{
            fontSize: "clamp(1.75rem, 3.5vw, 2.75rem)",
            fontWeight: 700,
            color: COLOR.textPrimary,
            margin: 0,
            letterSpacing: "-0.02em",
            lineHeight: 1.15,
          }}
        >
          {title}
        </h2>
      )}
      {subtitle && (
        <p
          style={{
            fontSize: "1rem",
            color: COLOR.textMuted,
            lineHeight: 1.7,
            margin: 0,
          }}
        >
          {subtitle}
        </p>
      )}
    </div>
  );
}
