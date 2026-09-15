// =============================================================================
// StrikeNova Public Design System — Button & Link Primitives
// =============================================================================
// Semantic button variants: primary, secondary, ghost, subtle.
// All support: normal, hover, active, focus-visible, disabled states.
// Touch-friendly: minimum 44px effective target height.
// =============================================================================

import React from "react";
import { COLOR, RADIUS, SPACE } from "./tokens";
import { PUBLIC_DS_CSS } from "./motion";

// Base button styles
const BASE_BUTTON = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "0.5rem",
  border: "none",
  cursor: "pointer",
  fontFamily: "inherit",
  fontWeight: 600,
  textDecoration: "none",
  transition: `background 0.15s, color 0.15s, border-color 0.15s, box-shadow 0.15s, transform 0.15s`,
  whiteSpace: "nowrap",
};

// Button variants
const VARIANTS = {
  primary: {
    base: {
      background: COLOR.strategy,
      color: "#0B0E14",
      border: `1px solid ${COLOR.strategy}`,
    },
    hover: {
      background: "#D9B36A",
      boxShadow: "0 6px 24px rgba(201, 161, 90, 0.35)",
      transform: "translateY(-1px)",
    },
    active: {
      transform: "translateY(0)",
    },
  },
  secondary: {
    base: {
      background: "transparent",
      color: COLOR.textPrimary,
      border: `1px solid ${COLOR.border}`,
    },
    hover: {
      borderColor: COLOR.strategy,
      background: COLOR.strategyDim,
      transform: "translateY(-1px)",
    },
    active: {
      transform: "translateY(0)",
    },
  },
  ghost: {
    base: {
      background: "transparent",
      color: COLOR.textPrimary,
      border: `1px solid ${COLOR.border}`,
    },
    hover: {
      background: COLOR.surfaceElevated,
      borderColor: COLOR.borderStrong,
    },
    active: {
      transform: "scale(0.98)",
    },
  },
  subtle: {
    base: {
      background: "transparent",
      color: COLOR.textMuted,
      border: "none",
    },
    hover: {
      color: COLOR.textPrimary,
      background: COLOR.surface,
    },
    active: {
      transform: "scale(0.98)",
    },
  },
};

// Button sizes
const SIZES = {
  sm: {
    padding: "0.625rem 1rem",
    fontSize: "0.875rem",
    minHeight: "44px",
  },
  md: {
    padding: "0.625rem 1.25rem",
    fontSize: "0.9375rem",
    minHeight: "44px",
  },
  lg: {
    padding: "0.875rem 2rem",
    fontSize: "1rem",
    minHeight: "52px",
  },
};

/**
 * Button — semantic button component.
 *
 * @param {string} variant - 'primary' | 'secondary' | 'ghost' | 'subtle'
 * @param {string} size - 'sm' | 'md' | 'lg'
 * @param {boolean} disabled
 * @param {function} onClick
 * @param {ReactNode} children
 * @param {object} style
 * @param {string} testId
 */
export function Button({
  variant = "primary",
  size = "md",
  disabled = false,
  children,
  style,
  testId,
  onMouseEnter,
  onMouseLeave,
  ...rest
}) {
  const v = VARIANTS[variant] || VARIANTS.primary;
  const s = SIZES[size] || SIZES.md;

  return (
    <button
      data-testid={testId}
      disabled={disabled}
      className="ds-focus-ring"
      style={{
        ...BASE_BUTTON,
        ...v.base,
        ...s,
        ...(disabled ? { opacity: 0.45, cursor: "not-allowed", pointerEvents: "none" } : {}),
        borderRadius: RADIUS.md,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!disabled && v.hover) Object.assign(e.currentTarget.style, v.hover);
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        if (!disabled) Object.assign(e.currentTarget.style, v.base, { transform: "none", boxShadow: "none" });
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * LinkButton — button rendered as an anchor tag.
 * Use when the action navigates to another page.
 */
export function LinkButton({
  variant = "primary",
  size = "md",
  children,
  href = "/",
  style,
  testId,
  ...rest
}) {
  const v = VARIANTS[variant] || VARIANTS.primary;
  const s = SIZES[size] || SIZES.md;

  return (
    <a
      href={href}
      data-testid={testId}
      className="ds-focus-ring"
      style={{
        ...BASE_BUTTON,
        ...v.base,
        ...s,
        borderRadius: RADIUS.md,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (v.hover) Object.assign(e.currentTarget.style, v.hover);
      }}
      onMouseLeave={(e) => {
        Object.assign(e.currentTarget.style, v.base, { transform: "none", boxShadow: "none" });
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

/**
 * TextLink — simple text link with gold hover.
 * For inline navigation, footer links, etc.
 */
export function TextLink({ children, href = "/", style, testId, ...rest }) {
  return (
    <a
      href={href}
      data-testid={testId}
      className="ds-focus-ring"
      style={{
        color: COLOR.textMuted,
        textDecoration: "none",
        fontSize: "0.875rem",
        transition: "color 0.15s",
        ...style,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.color = COLOR.strategy; }}
      onMouseLeave={(e) => { e.currentTarget.style.color = COLOR.textMuted; }}
      {...rest}
    >
      {children}
    </a>
  );
}
