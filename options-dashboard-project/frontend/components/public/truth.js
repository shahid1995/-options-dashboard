// =============================================================================
// StrikeNova Public Design System — Truth & Label Primitives
// =============================================================================

import React from "react";
import { COLOR, RESEARCH_STATUS, DATA_STATE, TYPE } from "./tokens";

export function DemoLabel({ style, ...rest }) {
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: TYPE.labelSmall.size,
        fontWeight: TYPE.labelSmall.weight,
        letterSpacing: TYPE.labelSmall.letterSpacing,
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

export function ResearchBadge({ status = "RESEARCH_DIRECTION", style, ...rest }) {
  const s = RESEARCH_STATUS[status] || RESEARCH_STATUS.RESEARCH_DIRECTION;
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: TYPE.labelSmall.size,
        fontWeight: TYPE.labelSmall.weight,
        letterSpacing: TYPE.labelSmall.letterSpacing,
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

export function SectionTitle({ eyebrow, title, subtitle, align = "center", style, ...rest }) {
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
            fontSize: TYPE.h2.size,
            fontWeight: TYPE.h2.weight,
            color: COLOR.textPrimary,
            margin: 0,
            letterSpacing: TYPE.h2.letterSpacing,
            lineHeight: TYPE.h2.lineHeight,
          }}
        >
          {title}
        </h2>
      )}
      {subtitle && (
        <p
          style={{
            fontSize: TYPE.body.size,
            color: COLOR.textMuted,
            lineHeight: TYPE.body.lineHeight,
            margin: 0,
          }}
        >
          {subtitle}
        </p>
      )}
    </div>
  );
}
