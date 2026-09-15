// =============================================================================
// StrikeNova Public Design System — Surface Primitives
// =============================================================================
// Reusable surface treatments: Surface, Panel, MetricPanel, OutlinePanel.
// These replace the repeated "surface + border + border-radius" pattern.
// =============================================================================

import React from "react";
import { COLOR, RADIUS, SHADOW } from "./tokens";

/**
 * Surface — the most primitive surface treatment.
 * A flat area with background, border, radius, and padding.
 */
export function Surface({
  children,
  background = COLOR.surface,
  border = COLOR.border,
  radius = RADIUS.lg,
  padding,
  shadow = SHADOW.none,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        background,
        border: `1px solid ${border}`,
        borderRadius: radius,
        boxShadow: shadow,
        ...(padding ? { padding } : {}),
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * Panel — a card-like container with elevated surface, standard padding.
 * Use for feature cards, content blocks, grouped information.
 */
export function Panel({
  children,
  background = COLOR.surface,
  padding = "1.5rem",
  radius = RADIUS.lg,
  shadow = SHADOW.none,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        background,
        border: `1px solid ${COLOR.border}`,
        borderRadius: radius,
        boxShadow: shadow,
        padding,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * MetricPanel — a panel optimized for numeric/metric display.
 * Uses tabular numerals by default. Includes a subtle inner glow option.
 */
export function MetricPanel({
  children,
  padding = "1.25rem 1.5rem",
  glow = false,
  background = COLOR.surface,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        background,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.lg,
        padding,
        fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', ui-monospace, monospace",
        ...(glow ? { boxShadow: SHADOW.glowStrategy } : {}),
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * OutlinePanel — a transparent panel with only a border.
 * Use for secondary grouping, nested containers, or when visual weight
 * should be lower than a filled Panel.
 */
export function OutlinePanel({
  children,
  padding = "1.5rem",
  radius = RADIUS.lg,
  border = COLOR.borderSubtle,
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        background: "transparent",
        border: `1px solid ${border}`,
        borderRadius: radius,
        padding,
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * SignalPanel — a specialized container for Signal Field visualizations.
 * Deep background, subtle border, generous padding.
 */
export function SignalPanel({
  children,
  padding = "2rem",
  style,
  as: Tag = "div",
  ...rest
}) {
  return (
    <Tag
      style={{
        background: COLOR.baseElevated,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.xl,
        padding,
        position: "relative",
        overflow: "hidden",
        ...style,
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
