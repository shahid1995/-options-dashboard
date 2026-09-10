// =============================================================================
// StrikeNova Public Design System — Tokens
// =============================================================================
// Semantic tokens for the V1.2 public workstream.
//
// ARCHITECTURE SAFETY:
// This file is PUBLIC-ONLY. It does not modify or re-export any token used by
// the authenticated application (lib/ui.js `C` object). Public components must
// import from this module, not from `@/lib/ui`, to avoid coupling.
// =============================================================================

// -----------------------------------------------------------------------------
// COLOR SYSTEM
// -----------------------------------------------------------------------------
// Deep obsidian base, dark slate surfaces, restrained borders.
// Accents: cyan (information/live), violet (intelligence), gold (strategy).

export const COLOR = {
  // --- Base ---
  base: "#06080B",           // deep obsidian — page background
  baseElevated: "#0B0E14",   // slightly lifted background (hero, section)

  // --- Surfaces ---
  surface: "#12161F",        // primary card/panel surface
  surfaceElevated: "#171C27",// raised surface (hover, active states)
  surfaceDeep: "#0E1118",    // deep inset surface (data areas)

  // --- Borders ---
  border: "#242B3A",         // primary border
  borderSubtle: "rgba(36, 43, 58, 0.35)", // faint border (dividers, outlines)
  borderStrong: "#3A4255",   // emphasized border (focus, active)

  // --- Text ---
  textPrimary: "#E7E9EE",    // primary text — high emphasis
  textSecondary: "#949CB0",  // secondary text — medium emphasis
  textMuted: "#7B8398",      // muted text — low emphasis
  textFaint: "#5A6376",      // faint text — lowest emphasis

  // --- Accent: Information / Live ---
  info: "#22D3EE",           // electric cyan — live data, information
  infoDim: "rgba(34, 211, 238, 0.15)",
  infoGlow: "rgba(34, 211, 238, 0.35)",

  // --- Accent: Intelligence ---
  intelligence: "#A78BFA",   // ultraviolet/violet — analysis, intelligence
  intelligenceDim: "rgba(167, 139, 250, 0.15)",
  intelligenceGlow: "rgba(167, 139, 250, 0.35)",

  // --- Accent: Strategy ---
  strategy: "#C9A15A",       // premium gold — strategy, decision, premium
  strategyDim: "rgba(201, 161, 90, 0.12)",
  strategyGlow: "rgba(201, 161, 90, 0.30)",

  // --- Semantic: Positive ---
  positive: "#4CAF7D",       // green — positive result, profit
  positiveDim: "rgba(76, 175, 125, 0.15)",

  // --- Semantic: Negative / Risk ---
  negative: "#E15252",       // red — risk, loss, negative result
  negativeDim: "rgba(225, 82, 82, 0.15)",

  // --- Semantic: Warning ---
  warning: "#F59E0B",        // amber — warning, caution
  warningDim: "rgba(245, 158, 11, 0.15)",

  // --- Signal Field specific ---
  signalOi: "#22D3EE",
  signalIv: "#A78BFA",
  signalGreeks: "#4CAF7D",
  signalPrice: "#E7E9EE",
};

// -----------------------------------------------------------------------------
// TYPOGRAPHY SYSTEM
// -----------------------------------------------------------------------------
// Three voices: Display (headlines), Body (copy), Data (metrics/numbers)

export const TYPE = {
  // --- Font families ---
  display: "'Inter', system-ui, -apple-system, sans-serif",
  body: "'Inter', system-ui, -apple-system, sans-serif",
  data: "'JetBrains Mono', 'SF Mono', 'Fira Code', ui-monospace, monospace",

  // --- Display scale ---
  displayHero: { size: "clamp(2.375rem, 5vw, 4.75rem)", lineHeight: 1.08, weight: 800, letterSpacing: "-0.04em" },
  displayH1:   { size: "clamp(2.125rem, 4.5vw, 4.25rem)", lineHeight: 1.10, weight: 800, letterSpacing: "-0.035em" },
  displayH2:   { size: "clamp(1.75rem, 3.5vw, 2.75rem)",  lineHeight: 1.15, weight: 700, letterSpacing: "-0.02em" },

  // --- Heading scale ---
  h1: { size: "clamp(2.125rem, 4.5vw, 4.25rem)", lineHeight: 1.10, weight: 800, letterSpacing: "-0.035em" },
  h2: { size: "clamp(1.75rem, 3.5vw, 2.75rem)",  lineHeight: 1.15, weight: 700, letterSpacing: "-0.02em" },
  h3: { size: "clamp(1.1875rem, 2vw, 1.625rem)", lineHeight: 1.25, weight: 700, letterSpacing: "-0.01em" },
  h4: { size: "1.125rem",  lineHeight: 1.35, weight: 600, letterSpacing: "-0.005em" },

  // --- Body scale ---
  bodyLarge: { size: "1.125rem", lineHeight: 1.7,  weight: 400 },
  body:      { size: "1rem",     lineHeight: 1.7,  weight: 400 },
  bodySmall: { size: "0.875rem", lineHeight: 1.65, weight: 400 },

  // --- Labels ---
  label:       { size: "0.8125rem", lineHeight: 1.4, weight: 600, letterSpacing: "0.06em", uppercase: true },
  labelSmall:  { size: "0.6875rem", lineHeight: 1.4, weight: 600, letterSpacing: "0.08em", uppercase: true },
  caption:     { size: "0.75rem",   lineHeight: 1.5, weight: 500, letterSpacing: "0.02em" },

  // --- Data scale ---
  dataHero: { size: "clamp(1.5rem, 3vw, 2.5rem)", lineHeight: 1.1, weight: 700, tabular: true },
  dataLarge: { size: "1.5rem",  lineHeight: 1.2, weight: 700, tabular: true },
  data:      { size: "1rem",    lineHeight: 1.4, weight: 600, tabular: true },
  dataSmall: { size: "0.8125rem", lineHeight: 1.4, weight: 600, tabular: true },
};

// -----------------------------------------------------------------------------
// SPACING SYSTEM
// -----------------------------------------------------------------------------
// Semantic spacing tokens for layout composition.

export const SPACE = {
  micro:  "0.25rem",   // 4px  — icon gaps, tight inline
  xs:     "0.375rem",  // 6px  — small inline gaps
  small:  "0.5rem",    // 8px  — compact padding, tight component
  sm:     "0.625rem",  // 10px — label-to-value, small component gaps
  medium: "0.75rem",   // 12px — standard component gaps
  comp:   "1rem",      // 16px — standard component padding
  compLg: "1.25rem",   // 20px — generous component padding
  card:   "1.5rem",    // 24px — card padding (replaces "10px 16px", "12px 18px")
  cardLg: "2rem",      // 32px — large card padding (replaces "22px 20px")
  group:  "2.5rem",    // 40px — between card groups
  section: "4rem",     // 64px — standard section vertical padding (replaces 72-96px)
  sectionLg: "5rem",   // 80px — large section vertical padding
  hero:   "5.5rem",    // 88px — hero vertical padding
};

// -----------------------------------------------------------------------------
// RADII
// -----------------------------------------------------------------------------
// Restrained corner radii.

export const RADIUS = {
  none: "0px",
  sm:   "4px",    // small elements (badges, tags)
  md:   "8px",    // buttons, inputs, small panels
  lg:   "12px",   // cards, panels
  xl:   "16px",   // large cards, modals
  pill: "9999px", // pill buttons, avatars
};

// -----------------------------------------------------------------------------
// SHADOWS / LAYERING
// -----------------------------------------------------------------------------
// Subtle shadows for depth. Avoid heavy elevation.

export const SHADOW = {
  none: "none",
  sm:   "0 1px 3px rgba(0,0,0,0.25)",
  md:   "0 4px 12px rgba(0,0,0,0.30)",
  lg:   "0 12px 40px rgba(0,0,0,0.40)",
  glowInfo:       "0 0 0 1px rgba(34,211,238,0.20), 0 0 12px rgba(34,211,238,0.15)",
  glowStrategy:   "0 0 0 1px rgba(201,161,90,0.20), 0 0 12px rgba(201,161,90,0.15)",
  glowIntelligence: "0 0 0 1px rgba(167,139,250,0.20), 0 0 12px rgba(167,139,250,0.15)",
};

// -----------------------------------------------------------------------------
// LAYER (z-index)
// -----------------------------------------------------------------------------

export const LAYER = {
  base:     0,
  dropdown: 10,
  sticky:   100,
  overlay:  200,
  modal:    300,
};

// -----------------------------------------------------------------------------
// RESPONSIVE BREAKPOINTS
// -----------------------------------------------------------------------------

export const BREAKPOINT = {
  sm:  "640px",
  md:  "768px",
  lg:  "1024px",
  xl:  "1280px",
  xxl: "1440px",
};

// -----------------------------------------------------------------------------
// MOTION SYSTEM
// -----------------------------------------------------------------------------
// Subtle, fast, purposeful motion tokens.

export const MOTION = {
  // --- Durations ---
  instant: "0.08s",
  fast:    "0.15s",
  normal:  "0.25s",
  slow:    "0.40s",

  // --- Easing ---
  easeOut:     "cubic-bezier(0.22, 1, 0.36, 1)",
  easeIn:      "cubic-bezier(0.55, 0, 1, 0.45)",
  easeInOut:   "cubic-bezier(0.4, 0, 0.2, 1)",
  signalTrace: "cubic-bezier(0.25, 0.46, 0.45, 0.94)",

  // --- Keyframe names (defined in CSS) ---
  keyframes: {
    fadeIn:     "sn-fade-in",
    fadeUp:     "sn-fade-up",
    pulse:      "sn-pulse",
    signalGlow: "sn-signal-glow",
    traceDraw:  "sn-trace-draw",
    ticker:     "sn-ticker",
    barFill:    "sn-bar-fill",
    nodeAppear: "sn-node-appear",
  },
};

// -----------------------------------------------------------------------------
// TRUTH / DATA STATE METADATA
// -----------------------------------------------------------------------------

export const DATA_STATE = {
  LIVE:         { label: "LIVE",         color: COLOR.info },
  DERIVED:      { label: "DERIVED",      color: COLOR.intelligence },
  DEMO:         { label: "DEMO",         color: COLOR.warning },
  ILLUSTRATIVE: { label: "ILLUSTRATIVE", color: COLOR.textMuted },
  UNAVAILABLE:  { label: "UNAVAILABLE",  color: COLOR.textFaint },
  RESEARCH:     { label: "RESEARCH",     color: COLOR.intelligence },
};

export const RESEARCH_STATUS = {
  AVAILABLE:        { label: "AVAILABLE",        color: COLOR.positive },
  COMING_LATER:     { label: "COMING LATER",     color: COLOR.info },
  RESEARCH_DIRECTION: { label: "RESEARCH DIRECTION", color: COLOR.intelligence },
};

// Convenience: list of all semantic color keys for test validation
export const SEMANTIC_COLOR_KEYS = Object.keys(COLOR);
export const SEMANTIC_SPACE_KEYS = Object.keys(SPACE);
export const SEMANTIC_TYPE_KEYS = Object.keys(TYPE);
