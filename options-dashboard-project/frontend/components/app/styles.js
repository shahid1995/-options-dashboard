/**
 * App Design System — Phase 2.1
 *
 * Shared style objects for authenticated App pages.
 * CSS class prefix: od-app-*
 * React component prefix: App*
 *
 * These styles follow the same dark + gold identity as the public website
 * but are tuned for higher information density (trading application).
 */
import { C } from "@/lib/ui";

/* ── Panel / Card ── */

export const AppPanel = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
  padding: 14,
  minWidth: 0,
};

export const AppPanelElevated = {
  ...AppPanel,
  background: C.surface2,
};

/* ── Section Titles ── */

export const SectionTitle = {
  fontSize: 12,
  fontWeight: 800,
  letterSpacing: 0.8,
  color: C.muted,
  marginBottom: 8,
};

export const SectionLabel = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: 0.7,
  color: C.muted,
  marginBottom: 6,
};

/* ── Table Styles ── */

export const AppTable = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12,
};

export const AppTableHead = {
  color: C.muted,
  fontSize: 10,
  letterSpacing: 0.5,
};

export const AppTableCell = {
  padding: "8px 12px",
  fontSize: 12,
  verticalAlign: "middle",
  whiteSpace: "nowrap",
};

/* ── Badge / Chip ── */

export const AppBadge = (color) => ({
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 0.5,
  padding: "2px 6px",
  borderRadius: 3,
  background: `${color}18`,
  color,
  border: `1px solid ${color}30`,
});

export const AppChip = (color) => ({
  fontSize: 9.5,
  fontWeight: 700,
  letterSpacing: 0.6,
  color,
  background: C.surface2,
  border: `1px solid ${C.border}`,
  borderRadius: 999,
  padding: "2px 8px",
  whiteSpace: "nowrap",
});

/* ── Metric Card ── */

export const MetricCardStyle = {
  background: C.surface2,
  border: `1px solid ${C.border}`,
  borderRadius: 8,
  padding: "10px 12px",
  minWidth: 0,
};

export const MetricLabel = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 0.6,
  color: C.muted,
  textTransform: "uppercase",
};

export const MetricValue = {
  fontSize: 16,
  fontWeight: 700,
  color: C.text,
  marginTop: 2,
  whiteSpace: "nowrap",
};

export const MetricHint = {
  fontSize: 10,
  color: C.faint,
  marginTop: 2,
};

/* ── Button Styles ── */

export const AppButtonPrimary = {
  fontSize: 12,
  fontWeight: 700,
  padding: "7px 16px",
  borderRadius: 6,
  border: "none",
  background: C.gold,
  color: "#0B0E14",
  cursor: "pointer",
};

export const AppButtonSecondary = {
  fontSize: 12,
  fontWeight: 700,
  padding: "7px 16px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.surface,
  color: C.text,
  cursor: "pointer",
};

export const AppButtonGhost = {
  fontSize: 11,
  fontWeight: 700,
  padding: "5px 12px",
  borderRadius: 6,
  border: `1px solid ${C.gold}66`,
  background: "rgba(201,161,90,0.08)",
  color: C.gold,
  cursor: "pointer",
};

/* ── Tab Styles ── */

export const AppTab = {
  fontSize: 12,
  padding: "6px 12px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: "transparent",
  color: C.muted,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 6,
  fontWeight: 400,
};

export const AppTabActive = {
  ...AppTab,
  border: `1px solid ${C.gold}`,
  background: "rgba(201,161,90,0.1)",
  color: C.gold,
  fontWeight: 600,
};

export const AppTabCount = (isActive) => ({
  fontSize: 10,
  padding: "1px 5px",
  borderRadius: 3,
  background: isActive ? "rgba(201,161,90,0.2)" : "rgba(136,146,166,0.15)",
  color: isActive ? C.gold : C.faint,
});

/* ── Input / Select ── */

export const AppInput = {
  fontSize: 12,
  padding: "6px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.surface,
  color: C.text,
};

export const AppSelect = {
  fontSize: 11,
  padding: "4px 8px",
  borderRadius: 4,
  border: `1px solid ${C.border}`,
  background: C.surface,
  color: C.text,
  cursor: "pointer",
};

/* ── Empty / Loading States ── */

export const EmptyState = {
  textAlign: "center",
  padding: "48px 16px",
  color: C.muted,
  fontSize: 13,
};

export const LoadingState = {
  textAlign: "center",
  padding: "48px 16px",
  color: C.muted,
  fontSize: 13,
};

/* ── Page Header ── */

export const PageHeader = {
  marginBottom: 16,
};

export const PageTitle = {
  fontSize: 20,
  fontWeight: 700,
  margin: 0,
  marginBottom: 4,
};

export const PageSubtitle = {
  fontSize: 13,
  color: C.muted,
  margin: 0,
};

/* ── Grid Layouts ── */

export const MetricGrid = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
  gap: 8,
};

export const MetricGridCompact = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))",
  gap: 8,
};

/* ── Shared component functions ── */

/**
 * MetricCard component — reusable metric display
 * Usage: <MetricCard label="Spot" value="25,512" color={C.gold} hint="Underlying price" />
 */
export function MetricCard({ label, value, color, hint }) {
  return (
    <div style={MetricCardStyle}>
      <div style={MetricLabel}>{label}</div>
      <div style={{ ...MetricValue, color: color || C.text }}>{value ?? "—"}</div>
      {hint && <div style={MetricHint}>{hint}</div>}
    </div>
  );
}

/**
 * SectionHeader — section title with optional right-aligned content
 */
export function SectionHeader({ title, children }) {
  return (
    <div
      style={{
        ...SectionTitle,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 6,
      }}
    >
      <span>{title}</span>
      {children}
    </div>
  );
}
