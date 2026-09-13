// =============================================================================
// StrikeNova App Core Components — Phase D
// =============================================================================
// Reusable primitives for the authenticated application.
// These compose canonical tokens into product-neutral building blocks.
// =============================================================================

import React from "react";
import { COLOR, SPACE, RADIUS, TYPE } from "@/components/public/tokens";

/* ─── helpers ─── */

const fmtNum = (n, decimals = 0) => {
  if (n === null || n === undefined || n === "") return "—";
  if (typeof n === "number" && Number.isNaN(n)) return "—";
  if (typeof n === "number") {
    return n.toLocaleString("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  return String(n);
};

const SEMANTIC = {
  positive: { color: COLOR.positive, bg: "rgba(76,175,125,0.10)", border: "rgba(76,175,125,0.25)" },
  negative: { color: COLOR.negative, bg: "rgba(225,82,82,0.10)", border: "rgba(225,82,82,0.25)" },
  warning: { color: COLOR.warning, bg: "rgba(245,158,11,0.10)", border: "rgba(245,158,11,0.25)" },
  info: { color: COLOR.info, bg: "rgba(34,211,238,0.10)", border: "rgba(34,211,238,0.25)" },
  intelligence: { color: COLOR.intelligence, bg: "rgba(167,139,250,0.10)", border: "rgba(167,139,250,0.25)" },
  strategy: { color: COLOR.strategy, bg: "rgba(201,161,90,0.10)", border: "rgba(201,161,90,0.25)" },
  neutral: { color: COLOR.textMuted, bg: "rgba(148,156,176,0.10)", border: "rgba(148,156,176,0.25)" },
};

/* ─── 1. Metric / KPI ─── */

const METRIC_SIZES = {
  sm: { valueFs: "0.875rem", labelFs: "0.75rem" },
  md: { valueFs: "1.25rem", labelFs: "0.8125rem" },
  lg: { valueFs: "1.75rem", labelFs: "0.8125rem" },
  hero: { valueFs: "clamp(1.5rem, 3vw, 2.5rem)", labelFs: "0.8125rem" },
};

export function Metric({ label, value, unit, decimals = 0, hint, size = "md", semantic, color, style }) {
  const ss = METRIC_SIZES[size] || METRIC_SIZES.md;
  const formatted = fmtNum(value, decimals);
  const isUnavailable = formatted === "—";
  const sem = semantic && SEMANTIC[semantic] ? SEMANTIC[semantic] : null;

  const valueColor = color || (sem ? sem.color : isUnavailable ? COLOR.textFaint : COLOR.textPrimary);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE.xs, ...style }}>
      <span style={{ fontSize: ss.labelFs, fontWeight: 700, letterSpacing: "0.06em", color: COLOR.textFaint, textTransform: "uppercase" }}>
        {label}
      </span>
      <span style={{ fontSize: ss.valueFs, fontWeight: 800, color: valueColor, lineHeight: 1.1, fontVariantNumeric: "tabular-nums", fontFamily: TYPE.data, display: "flex", alignItems: "baseline", gap: SPACE.xs }}>
        {formatted}
        {unit && <span style={{ fontSize: "0.7em", fontWeight: 600, color: COLOR.textMuted }}>{unit}</span>}
      </span>
      {hint && <span style={{ fontSize: "0.75rem", color: COLOR.textFaint, lineHeight: 1.4 }}>{hint}</span>}
    </div>
  );
}

/* ─── 2. Data Table ─── */

export function Table({ columns, data, compact = false, emptyMessage = "No data available.", keyExtractor, onRowClick }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ padding: `${SPACE.section} ${SPACE.comp}`, textAlign: "center", color: COLOR.textMuted, fontSize: "0.875rem" }}>
        {emptyMessage}
      </div>
    );
  }

  const cellPadding = compact ? `${SPACE.small} ${SPACE.small}` : `${SPACE.small} ${SPACE.comp}`;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${COLOR.border}` }}>
            {columns.map((col, i) => (
              <th
                key={i}
                style={{
                  padding: cellPadding,
                  textAlign: col.align || "left",
                  color: col.align === "right" ? COLOR.textFaint : COLOR.textFaint,
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  whiteSpace: "nowrap",
                  position: col.sticky ? "sticky" : undefined,
                  left: col.sticky ? 0 : undefined,
                  background: col.sticky ? COLOR.surface : undefined,
                  zIndex: col.sticky ? 1 : undefined,
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => (
            <tr
              key={keyExtractor ? keyExtractor(row, rowIdx) : rowIdx}
              onClick={onRowClick ? () => onRowClick(row, rowIdx) : undefined}
              style={{
                borderBottom: `1px solid ${COLOR.border}`,
                background: rowIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)",
                cursor: onRowClick ? "pointer" : undefined,
              }}
              onMouseEnter={(e) => { if (onRowClick) e.currentTarget.style.background = COLOR.surfaceElevated; }}
              onMouseLeave={(e) => { if (onRowClick) e.currentTarget.style.background = rowIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)"; }}
            >
              {columns.map((col, colIdx) => (
                <td
                  key={colIdx}
                  style={{
                    padding: cellPadding,
                    textAlign: col.align || "left",
                    color: col.align === "right" ? COLOR.textSecondary : COLOR.textPrimary,
                    fontVariantNumeric: col.align === "right" ? "tabular-nums" : undefined,
                    whiteSpace: col.noWrap ? "nowrap" : undefined,
                  }}
                >
                  {col.render ? col.render(row[col.key], row, rowIdx) : row[col.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── 3. Badge / Status / Chip ─── */

export function Badge({ variant = "neutral", children, style }) {
  const sem = SEMANTIC[variant] || SEMANTIC.neutral;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: SPACE.xs,
        padding: `${SPACE.xs} ${SPACE.small}`,
        borderRadius: RADIUS.pill,
        fontSize: "0.6875rem",
        fontWeight: 700,
        letterSpacing: "0.04em",
        color: sem.color,
        background: sem.bg,
        border: `1px solid ${sem.border}`,
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export function Chip({ selected, onClick, children, style }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: SPACE.xs,
        padding: `${SPACE.xs} ${SPACE.small}`,
        borderRadius: RADIUS.pill,
        fontSize: "0.6875rem",
        fontWeight: 600,
        cursor: "pointer",
        transition: "background 0.15s, color 0.15s, border-color 0.15s",
        color: selected ? COLOR.strategy : COLOR.textMuted,
        background: selected ? "rgba(201,161,90,0.10)" : COLOR.surface,
        border: `1px solid ${selected ? "rgba(201,161,90,0.3)" : COLOR.border}`,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

/* ─── 4. Segmented Control ─── */

export function SegmentedControl({ options, value, onChange, "aria-label": ariaLabel }) {
  return (
    <div role="tablist" aria-label={ariaLabel} style={{ display: "flex", gap: SPACE.xs, flexWrap: "wrap" }}>
      {options.map((opt) => {
        const isActive = value === opt.value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(opt.value)}
            style={{
              padding: `${SPACE.small} ${SPACE.comp}`,
              fontSize: "0.8125rem",
              fontWeight: isActive ? 600 : 400,
              cursor: "pointer",
              transition: "background 0.15s, color 0.15s, border-color 0.15s",
              color: isActive ? COLOR.strategy : COLOR.textMuted,
              background: isActive ? "rgba(201,161,90,0.10)" : "transparent",
              border: `1px solid ${isActive ? "rgba(201,161,90,0.3)" : COLOR.border}`,
              borderRadius: RADIUS.md,
              whiteSpace: "nowrap",
              minHeight: "36px",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/* ─── 5. Chart Container ─── */

export function ChartContainer({ title, eyebrow, caption, children, source, style }) {
  return (
    <div
      style={{
        background: COLOR.surface,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.lg,
        ...style,
      }}
    >
      {(title || eyebrow || source) && (
        <div style={{ padding: `${SPACE.comp} ${SPACE.comp} 0`, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: SPACE.comp }}>
          <div>
            {eyebrow && <div style={{ fontSize: "0.6875rem", fontWeight: 700, letterSpacing: "0.08em", color: COLOR.textFaint, textTransform: "uppercase", marginBottom: SPACE.xs }}>{eyebrow}</div>}
            {title && <div style={{ fontSize: "0.875rem", fontWeight: 700, color: COLOR.textPrimary }}>{title}</div>}
          </div>
          {source && <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint, fontWeight: 500 }}>{source}</div>}
        </div>
      )}
      <div style={{ padding: SPACE.comp }}>{children}</div>
      {caption && <div style={{ padding: `0 ${SPACE.comp} ${SPACE.comp}`, fontSize: "0.75rem", color: COLOR.textFaint, textAlign: "center" }}>{caption}</div>}
    </div>
  );
}

/* ─── 6. Empty / Loading / Error States ─── */

export function EmptyState({ message = "No data available.", action, style }) {
  return (
    <div style={{ padding: `${SPACE.section} ${SPACE.comp}`, textAlign: "center", ...style }}>
      <div style={{ fontSize: "0.875rem", color: COLOR.textMuted, marginBottom: action ? SPACE.comp : 0 }}>{message}</div>
      {action}
    </div>
  );
}

export function LoadingState({ message = "Loading...", style }) {
  return (
    <div style={{ padding: `${SPACE.section} ${SPACE.comp}`, textAlign: "center", ...style }}>
      <div style={{ fontSize: "0.875rem", color: COLOR.textMuted }}>{message}</div>
    </div>
  );
}

export function ErrorState({ message = "Unable to load data.", onRetry, style }) {
  return (
    <div style={{ padding: `${SPACE.section} ${SPACE.comp}`, textAlign: "center", ...style }}>
      <div style={{ fontSize: "0.875rem", color: COLOR.negative, marginBottom: onRetry ? SPACE.comp : 0 }}>{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            padding: `${SPACE.small} ${SPACE.comp}`,
            fontSize: "0.8125rem",
            fontWeight: 600,
            cursor: "pointer",
            color: COLOR.textPrimary,
            background: COLOR.surface,
            border: `1px solid ${COLOR.border}`,
            borderRadius: RADIUS.md,
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

/* ─── 7. Action Buttons ─── */

const BTN_BASE = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: SPACE.small,
  border: "none",
  cursor: "pointer",
  fontFamily: "inherit",
  fontWeight: 600,
  textDecoration: "none",
  transition: "background 0.15s, color 0.15s, border-color 0.15s, opacity 0.15s",
  whiteSpace: "nowrap",
  minHeight: "36px",
};

const BTN_VARIANTS = {
  primary: {
    background: COLOR.strategy,
    color: "#0B0E14",
    border: `1px solid ${COLOR.strategy}`,
  },
  secondary: {
    background: "transparent",
    color: COLOR.textPrimary,
    border: `1px solid ${COLOR.border}`,
  },
  ghost: {
    background: "transparent",
    color: COLOR.textPrimary,
    border: `1px solid ${COLOR.border}`,
  },
  destructive: {
    background: "transparent",
    color: COLOR.negative,
    border: `1px solid ${COLOR.negative}44`,
  },
};

export function ActionButton({ variant = "primary", size = "md", disabled = false, children, style, ...rest }) {
  const v = BTN_VARIANTS[variant] || BTN_VARIANTS.primary;
  const sizeStyles = {
    sm: { padding: `${SPACE.xs} ${SPACE.small}`, fontSize: "0.8125rem", minHeight: "32px" },
    md: { padding: `${SPACE.small} ${SPACE.comp}`, fontSize: "0.875rem", minHeight: "36px" },
    lg: { padding: `${SPACE.small} ${SPACE.card}`, fontSize: "0.9375rem", minHeight: "44px" },
  };
  const s = sizeStyles[size] || sizeStyles.md;

  return (
    <button
      disabled={disabled}
      style={{
        ...BTN_BASE,
        ...v,
        ...s,
        borderRadius: RADIUS.md,
        opacity: disabled ? 0.45 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );
}
