// =============================================================================
// StrikeNova Public Design System — Layout Primitives
// =============================================================================
// Reusable layout primitives for public page composition.
// Supports: full-width sections, two-column layouts, asymmetric layouts,
// bento-style compositions, metric grids, responsive stacking.
// =============================================================================

import React from "react";
import { SPACE } from "./tokens";

/**
 * Section — a full-width vertical section with consistent padding.
 */
export function Section({
  children,
  background,
  padding = SPACE.section,
  style,
  as: Tag = "section",
  ...rest
}) {
  return (
    <Tag
      style={{
        width: "100%",
        paddingTop: padding,
        paddingBottom: padding,
        paddingLeft: "1.25rem",
        paddingRight: "1.25rem",
        ...(background ? { background } : {}),
        boxSizing: "border-box",
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * Container — a centered content container with max-width.
 */
export function Container({
  children,
  maxWidth = 1100,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        width: "100%",
        maxWidth: `${maxWidth}px`,
        margin: "0 auto",
        boxSizing: "border-box",
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * TwoColumn — a responsive two-column layout that stacks on mobile.
 */
export function TwoColumn({
  left,
  right,
  gap = SPACE.section,
  reverse = false,
  breakpoint = 768,
  leftStyle,
  rightStyle,
  style,
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: reverse ? "row-reverse" : "row",
        gap,
        flexWrap: "wrap",
        ...style,
      }}
    >
      <div
        style={{
          flex: "1 1 0",
          minWidth: `calc(${breakpoint}px - 200px)`,
          display: "flex",
          flexDirection: "column",
          gap: SPACE.comp,
          ...leftStyle,
        }}
      >
        {left}
      </div>
      <div
        style={{
          flex: "1 1 0",
          minWidth: `calc(${breakpoint}px - 200px)`,
          display: "flex",
          flexDirection: "column",
          gap: SPACE.comp,
          ...rightStyle,
        }}
      >
        {right}
      </div>
    </div>
  );
}

/**
 * MetricGrid — a responsive grid for metric panels.
 * Collapses to single column on mobile.
 */
export function MetricGrid({
  children,
  minItemWidth = 160,
  gap = SPACE.comp,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${minItemWidth}px, 1fr))`,
        gap,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * CardGrid — a responsive grid for content cards.
 */
export function CardGrid({
  children,
  minItemWidth = 280,
  gap = SPACE.compLg,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${minItemWidth}px, 1fr))`,
        gap,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * BentoGrid — an asymmetric bento-style layout.
 * Uses CSS grid with configurable row/column spans.
 */
export function BentoGrid({
  children,
  columns = 3,
  gap = SPACE.compLg,
  style,
  ...rest
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap,
        gridAutoRows: "minmax(120px, auto)",
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * FlexRow — a simple flex row with gap and wrap.
 */
export function FlexRow({
  children,
  gap = SPACE.comp,
  justify = "flex-start",
  align = "center",
  wrap = true,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? "wrap" : "nowrap",
        gap,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * FlexColumn — a simple flex column with gap.
 */
export function FlexColumn({
  children,
  gap = SPACE.comp,
  align = "stretch",
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: align,
        gap,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * Asymmetric — a layout with a larger side and smaller side.
 * Useful for Strategy Lab composition (content + payoff split).
 */
export function Asymmetric({
  main,
  side,
  ratio = "2:1",
  gap = SPACE.section,
  reverse = false,
  style,
}) {
  const parts = ratio.split(":").map(Number);
  const total = parts[0] + parts[1];
  const mainFrac = `0 0 ${(parts[0] / total) * 100}%`;
  const sideFrac = `0 0 ${(parts[1] / total) * 100}%`;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        gap,
        flexWrap: "wrap",
        ...style,
      }}
    >
      <div style={{ flex: mainFrac, minWidth: "300px" }}>{main}</div>
      <div style={{ flex: sideFrac, minWidth: "250px" }}>{side}</div>
    </div>
  );
}
