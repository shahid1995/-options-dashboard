// =============================================================================
// StrikeNova Design System — Canonical Tokens
// =============================================================================
// This file is the single source of truth for design tokens in the StrikeNova
// frontend. It is consumed by BOTH the public marketing site and the
// authenticated application (via the `C` compatibility bridge in lib/ui.js).
//
// Do not introduce a second token system. Extend these exports instead.
// =============================================================================

export const COLOR = {
  base: "#06080B",
  baseElevated: "#0B0E14",
  surface: "#12161F",
  surfaceElevated: "#171C27",
  surfaceDeep: "#0E1118",

  border: "#242B3A",
  borderSubtle: "rgba(36, 43, 58, 0.35)",
  borderStrong: "#5E6A80",

  textPrimary: "#E7E9EE",
  textSecondary: "#949CB0",
  textMuted: "#7B8398",
  // AA-safe for meaningful small text on both base and surface backgrounds.
  textFaint: "#788094",

  info: "#22D3EE",
  infoDim: "rgba(34, 211, 238, 0.15)",
  infoGlow: "rgba(34, 211, 238, 0.35)",

  intelligence: "#A78BFA",
  intelligenceDim: "rgba(167, 139, 250, 0.15)",
  intelligenceGlow: "rgba(167, 139, 250, 0.35)",

  strategy: "#C9A15A",
  strategyDim: "rgba(201, 161, 90, 0.12)",
  strategyGlow: "rgba(201, 161, 90, 0.30)",

  positive: "#4CAF7D",
  positiveDim: "rgba(76, 175, 125, 0.15)",

  negative: "#E15252",
  negativeDim: "rgba(225, 82, 82, 0.15)",

  warning: "#F59E0B",
  warningDim: "rgba(245, 158, 11, 0.15)",

  signalOi: "#22D3EE",
  signalIv: "#A78BFA",
  signalGreeks: "#4CAF7D",
  signalPrice: "#E7E9EE",
};

export const TYPE = {
  display: "'Inter', system-ui, -apple-system, sans-serif",
  body: "'Inter', system-ui, -apple-system, sans-serif",
  data: "'JetBrains Mono', 'SF Mono', 'Fira Code', ui-monospace, monospace",

  displayHero: { size: "clamp(2.375rem, 5vw, 4.75rem)", lineHeight: 1.08, weight: 800, letterSpacing: "-0.04em" },
  displayH1: { size: "clamp(2.125rem, 4.5vw, 4.25rem)", lineHeight: 1.10, weight: 800, letterSpacing: "-0.035em" },
  displayH2: { size: "clamp(1.75rem, 3.5vw, 2.75rem)", lineHeight: 1.15, weight: 700, letterSpacing: "-0.02em" },

  h1: { size: "clamp(2.125rem, 4.5vw, 4.25rem)", lineHeight: 1.10, weight: 800, letterSpacing: "-0.035em" },
  h2: { size: "clamp(1.75rem, 3.5vw, 2.75rem)", lineHeight: 1.15, weight: 700, letterSpacing: "-0.02em" },
  h3: { size: "clamp(1.1875rem, 2vw, 1.625rem)", lineHeight: 1.25, weight: 700, letterSpacing: "-0.01em" },
  h4: { size: "1.125rem", lineHeight: 1.35, weight: 600, letterSpacing: "-0.005em" },

  bodyLarge: { size: "1.125rem", lineHeight: 1.7, weight: 400 },
  body: { size: "1rem", lineHeight: 1.7, weight: 400 },
  bodySmall: { size: "0.875rem", lineHeight: 1.65, weight: 400 },

  label: { size: "0.8125rem", lineHeight: 1.4, weight: 600, letterSpacing: "0.06em", uppercase: true },
  labelSmall: { size: "0.6875rem", lineHeight: 1.4, weight: 600, letterSpacing: "0.08em", uppercase: true },
  caption: { size: "0.75rem", lineHeight: 1.5, weight: 500, letterSpacing: "0.02em" },

  dataHero: { size: "clamp(1.5rem, 3vw, 2.5rem)", lineHeight: 1.1, weight: 700, tabular: true },
  dataLarge: { size: "1.5rem", lineHeight: 1.2, weight: 700, tabular: true },
  data: { size: "1rem", lineHeight: 1.4, weight: 600, tabular: true },
  dataSmall: { size: "0.8125rem", lineHeight: 1.4, weight: 600, tabular: true },
};

export const SPACE = {
  micro: "0.25rem", xs: "0.375rem", small: "0.5rem", sm: "0.625rem", medium: "0.75rem",
  comp: "1rem", compLg: "1.25rem", card: "1.5rem", cardLg: "2rem", group: "2.5rem",
  section: "4rem", sectionLg: "5rem", hero: "5.5rem",
};

export const RADIUS = {
  none: "0px", sm: "4px", md: "8px", lg: "12px", xl: "16px", pill: "9999px",
};

export const SHADOW = {
  none: "none",
  sm: "0 1px 3px rgba(0,0,0,0.25)",
  md: "0 4px 12px rgba(0,0,0,0.30)",
  lg: "0 12px 40px rgba(0,0,0,0.40)",
  glowInfo: "0 0 0 1px rgba(34,211,238,0.20), 0 0 12px rgba(34,211,238,0.15)",
  glowStrategy: "0 0 0 1px rgba(201,161,90,0.20), 0 0 12px rgba(201,161,90,0.15)",
  glowIntelligence: "0 0 0 1px rgba(167,139,250,0.20), 0 0 12px rgba(167,139,250,0.15)",
};

export const LAYER = { base: 0, dropdown: 10, sticky: 100, overlay: 200, modal: 300 };
export const BREAKPOINT = { sm: "640px", md: "768px", lg: "1024px", xl: "1280px", xxl: "1440px" };

export const MOTION = {
  instant: "0.08s", fast: "0.15s", normal: "0.25s", slow: "0.40s",
  easeOut: "cubic-bezier(0.22, 1, 0.36, 1)",
  easeIn: "cubic-bezier(0.55, 0, 1, 0.45)",
  easeInOut: "cubic-bezier(0.4, 0, 0.2, 1)",
  signalTrace: "cubic-bezier(0.25, 0.46, 0.45, 0.94)",
  keyframes: {
    fadeIn: "sn-fade-in", fadeUp: "sn-fade-up", pulse: "sn-pulse", signalGlow: "sn-signal-glow",
    traceDraw: "sn-trace-draw", ticker: "sn-ticker", barFill: "sn-bar-fill", nodeAppear: "sn-node-appear",
  },
};

export const DATA_STATE = {
  LIVE: { label: "LIVE", color: COLOR.info },
  DERIVED: { label: "DERIVED", color: COLOR.intelligence },
  DEMO: { label: "DEMO", color: COLOR.warning },
  ILLUSTRATIVE: { label: "ILLUSTRATIVE", color: COLOR.textMuted },
  UNAVAILABLE: { label: "UNAVAILABLE", color: COLOR.textFaint },
  RESEARCH: { label: "RESEARCH", color: COLOR.intelligence },
};

export const RESEARCH_STATUS = {
  AVAILABLE: { label: "AVAILABLE", color: COLOR.positive },
  COMING_LATER: { label: "COMING LATER", color: COLOR.info },
  RESEARCH_DIRECTION: { label: "RESEARCH DIRECTION", color: COLOR.intelligence },
};

export const SEMANTIC_COLOR_KEYS = Object.keys(COLOR);
export const SEMANTIC_SPACE_KEYS = Object.keys(SPACE);
export const SEMANTIC_TYPE_KEYS = Object.keys(TYPE);
