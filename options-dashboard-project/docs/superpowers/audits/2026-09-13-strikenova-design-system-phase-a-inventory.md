# StrikeNova Visual Design System V1 — Phase A Inventory & Baseline Audit

**Date:** 2026-09-13
**Author:** Design-system audit agent
**Scope:** Read-only frontend inventory against `2026-09-13-strikenova-design-system-v1-design.md`
**Status:** Audit complete — no source modified

---

## 1. Executive Summary

The repository contains **two parallel visual systems** that the StrikeNova Design System V1 must reconcile:

1. **Public design system** (`components/public/`): a comprehensive, well-structured semantic token + primitive system built for the V1.2 public-website workstream. It is isolated by architecture-rule (does not import from `lib/ui`) and is actively tested (1706 tests).
2. **Authenticated application** (`lib/ui.js` + inline styles): a minimal flat color object (`C`) consumed directly by every app page via hand-rolled inline styles. No design tokens, no primitives, no component reuse infrastructure.

**Critical finding:** The two systems share the same color *values* (gold `#C9A15A`, green `#4CAF7D`, red `#E15252`, surface `#12161F`, border `#242B3A`) but are structurally decoupled. The public system is a proper design system; the app is a collection of inline-styled pages.

**Quantitative UI semantics:** The authenticated GEX/Greek/IV UI is **methodologically sound** — every panel carries explicit caveats ("Structural level, not directional signal", "Not a trading signal"). No single metric is presented as a directional guarantee. The dashboard option chain is the one area where color could be misread (PCR colored green/red, OI bars colored by side).

**Verdict: READY for Phase B.** The public token system should become the single source of truth; the app should be migrated to consume it incrementally. No architecture blockers.

---

## 2. Repository Baseline

| Field | Value |
| ----- | ----- |
| Branch | `feat/strikenova-day35-portfolio-intelligence` |
| HEAD SHA | `5f2e0765ffd32c80577a488876d83e6b64891500` |
| Working tree | **DIRTY** — 16 modified files (all backend + architecture docs), 114 untracked (backend/scripts/temp). **No frontend source files modified.** |
| Frontend path | `options-dashboard-project/frontend` |
| Framework | Next.js 14.2.35 (App Router) |
| React | 18.3.1 |
| Package manager | npm |
| Build command | `next build` ✓ passes |
| Test command | `vitest run` ✓ 1706 tests pass across 72 files |
| Lint/type-check | Not configured (no ESLint, no TypeScript) |
| Chart library | Recharts 2.12.7 |
| UI libraries | None (no Tailwind, no shadcn, no Radix, no MUI) |
| Auth | `@react-oauth/google` 0.13.5 |
| HTTP | Axios 1.19.0 |
| Path alias | `@/*` → `./` (jsconfig.json + vitest alias) |

**Authoritative documents:**
- ✓ Spec: `options-dashboard-project/docs/superpowers/specs/2026-09-13-strikenova-design-system-v1-design.md` (present, 885 lines)
- ✗ Plan: `options-dashboard-project/docs/superpowers/plans/2026-09-13-strikenova-design-system-v1-implementation-plan.md` — **DOES NOT EXIST**. Execution proceeds from the spec alone.

**Working-tree cleanliness:** Dirty, but all modifications are in `backend/` and `docs/architecture/`. No frontend source, CSS, package files, or deployment configs are touched. The audit will create only the artifact below.

---

## 3. Frontend Architecture Inventory

### 3.1 Application structure

```
app/
├── layout.js                       # Root: html/body, dark bg, system-ui font
├── (app)/                         # Authenticated route group
│   ├── layout.js                   # AuthGate > Shell
│   ├── dashboard/page.js           # Option chain + GEX profile + watchlist
│   ├── gex/page.js                 # GEX Intelligence (tabs: overview/history/regime/walls/flip/quality)
│   ├── paper/page.js               # Strategy Builder + Paper Trading (3621 lines)
│   ├── paper/*.js                  # AnalyticsPanel, BrokerConnectionPanel, BulkExit, CapitalPanel, GreekAnalyticsPanel, IVAnalyticsPanel, PortfolioAnalyticsPanel, ScenarioPanel, TradeDetailModal
│   ├── positions/page.js           # Paper positions management
│   ├── portfolio/page.js           # Portfolio overview
│   ├── orders/page.js              # Order history
│   ├── brokers/page.js             # Broker connection management
│   ├── settings/page.js            # Settings + Google OAuth
│   ├── activity/page.js            # Legacy route (redirected)
│   ├── market/page.js              # Legacy route (redirected)
│   └── strategies/page.js          # Legacy route (redirected)
└── (public)/                      # Public marketing route group
    ├── layout.js                   # PublicLayout (PublicHeader + content + PublicFooter)
    ├── page.js                     # Home page (hero + 8 sections)
    ├── about/page.js               # (ClientPage)
    ├── features/page.js            # (ClientPage)
    ├── how-it-works/page.js        # (ClientPage)
    ├── market-intelligence/page.js # (ClientPage)
    ├── paper-trading/page.js       # (ClientPage)
    └── strategy-lab/page.js        # (ClientPage)
```

**Layout pattern:**
- Root `app/layout.js` sets global `body` style (background `#0B0E14`, color `#E7E9EE`).
- `(app)/layout.js` wraps content in `AuthGate > Shell` (top bar + sidebar navigation).
- `(public)/layout.js` wraps content in `PublicLayout` (sticky public header + footer).
- Both inject CSS strings via `<style>` tags (no CSS modules, no Tailwind, no styled-components).

**Authentication boundary:**
- `components/AuthGate.js` gates the `(app)` group.
- `(public)` pages are open but expose auth via modal (`AuthModalContext` + `AuthModal`).
- Google OAuth callback handled in `PublicLayout` → cross-origin handoff to app URL.

### 3.2 Component structure

**Public design system** (`components/public/`):

| File | Purpose |
| ---- | ------- |
| `tokens.js` | COLOR, TYPE, SPACE, RADIUS, SHADOW, LAYER, BREAKPOINT, MOTION, DATA_STATE, RESEARCH_STATUS |
| `surfaces.js` | Surface, Panel, MetricPanel, OutlinePanel, SignalPanel |
| `buttons.js` | Button, LinkButton, TextLink (variants: primary/secondary/ghost/subtle) |
| `motion.js` | PUBLIC_DS_CSS keyframes + utilities (fadeUpStyle, signalGlowStyle, traceDrawStyle) |
| `signals.js` | SignalLine, SignalNode, StrikeRail, DataTrace, TechnicalDivider, GridOverlay |
| `layout.js` | Section, Container, TwoColumn, MetricGrid, CardGrid, BentoGrid, FlexRow, FlexColumn, Asymmetric |
| `truth.js` | DemoLabel, ResearchBadge, DataStateBadge, Eyebrow, SectionTitle |
| `Metric.js` | Metric primitive with status/source/size |
| `SignalField.js` | Signature visualization (OI bars + IV curve + strikes + structure + Greeks) |
| `VisualizationFrame` | Chart/visualization container (title, eyebrow, caption, legend, demo label) |
| `HomeHero.js` | Hero with branding, tagline, CTAs |
| `AnalyticalLayerGrid.js` | 8-layer intelligence grid |
| `MarketIntelligenceGrid.js` | 4-panel data grid (Positioning, Volatility, Greeks, Structure) |
| `FeatureCard.js` | Feature card (icon + title + desc) |
| `WorkflowTabs.js` | Accessible tab interface |
| `EvidenceTrustSection.js` | Trust/evidence content |
| `CTASection.js` | CTA block |
| `PayoffMiniChart.js` | Payoff curve SVG |
| `PlatformPreview.js` | Platform screenshot/mockup |
| `PublicHeader.js` | Sticky header with dropdown nav + mobile menu |
| `PublicFooter.js` | Footer |
| `PublicLayout.js` | Public page shell (header + main + footer + OAuth handler) |
| `AuthModal.js`, `AuthModalContext.js` | Auth modal state |
| `styles.js` | PUBLIC_CSS (legacy keyframes, utility classes, button/link/card styles) |
| `index.js` | Re-export barrel |

**App design system** (`components/app/`):

| File | Purpose |
| ---- | ------- |
| `styles.js` | Flat style objects: AppPanel, SectionTitle, SectionLabel, AppTable, AppBadge, AppChip, MetricCard, MetricLabel/Value/Hint, AppButtonPrimary/Secondary/Ghost, AppTab, AppInput, AppSelect, EmptyState, LoadingState, PageHeader/Title/Subtitle, MetricGrid, MetricCard component, SectionHeader component |

**App shared primitives** (`components/`):

| File | Purpose |
| ---- | ------- |
| `Shell.js` | App shell (top bar + sidebar nav + mobile overlay) — 462 lines |
| `AuthGate.js` | Auth boundary |
| `GexProfileChart.js` | Recharts horizontal bar chart (net GEX by strike) |
| `GexHistoryChart.js` | Recharts line chart (net GEX time series) |
| `GexRegimeTimeline.js` | Recharts bar chart (gamma regime timeline) |
| `GexWallTracker.js` | Call/put wall cards + ranked wall list |
| `GexFlipPanel.js` | Gamma flip spot/distance/position display |
| `GexDataQualityPanel.js` | Data quality score/metrics |

### 3.3 Supporting infrastructure

**`lib/` — domain logic (not UI):**
- `lib/ui.js` — THE APP TOKEN OBJECT (`C`: surface, surface2, border, muted, faint, text, gold, green, red) + helpers (fmtIN, fmtChg, useIsMobile, TopNav, SymbolTabs, Centered, Stat, StepButton, ShapeIcon)
- `lib/api.js` — Backend REST client
- `lib/session.js` — Session ID capture/storage
- `lib/storage.js` — localStorage wrapper
- `lib/calculations/` — Quantitative engines (gex, greeks, ivAnalytics, payoff, pricing, scenario, strategyCalculator, etc.)
- `lib/strategy/` — Strategy domain logic
- `lib/portfolio.js`, `lib/paperUtils.js`, `lib/capital.js` — Portfolio/journal utilities
- `lib/alerts.js`, `lib/marketStatus.js`, `lib/brokerDiagnostics.js` — Alert/market/diagnostic logic
- `lib/useChainFeed.js`, `lib/useGexCapture.js` — Data hooks
- `lib/useAuth.js`, `lib/templates.js` — Auth/template hooks

---

## 4. Route Inventory

### Public routes (`(public)` group)

| Route | Layout | Purpose | UI type | Shared shell | Key components | Status |
| ----- | ------ | ------- | ------- | ------------ | -------------- | ------ |
| `/` | PublicLayout | Home | Marketing editorial | PublicHeader + PublicFooter | HomeHero, PlatformPreview, AnalyticalLayerGrid, SignalMetricOverview, MarketIntelligenceGrid, EvidenceTrustSection, WorkflowTabs (Strategy + Paper), PayoffMiniChart, CTASection | Active |
| `/features` | PublicLayout | Feature list | Marketing | Same | FeatureCard grid | Active |
| `/market-intelligence` | PublicLayout | MI deep-dive | Marketing | Same | SignalField demo | Active |
| `/strategy-lab` | PublicLab | Strategy Lab preview | Marketing | Same | PayoffMiniChart, WorkflowTabs | Active |
| `/paper-trading` | PublicLayout | Paper Trading preview | Marketing | Same | WorkflowTabs | Active |
| `/how-it-works` | PublicLayout | How It Works | Marketing | Same | — | Active |
| `/about` | PublicLayout | About | Marketing | Same | — | Active |

### Authenticated routes (`(app)` group)

| Route | Layout | Purpose | UI type | Shell | Key components | Status |
| ----- | ------ | ------- | ------- | ----- | -------------- | ------ |
| `/dashboard` | AuthGate > Shell | Option Chain + GEX | Trading terminal | TopNav + Sidebar | GexProfileChart, MetricCard grid, watchlist | Active |
| `/gex` | AuthGate > Shell | GEX Intelligence | Analytics | Same | GexHistoryChart, GexRegimeTimeline, GexWallTracker, GexFlipPanel, GexDataQualityPanel | Active |
| `/paper` | AuthGate > Shell | Strategy Builder + Paper Trading | Trading terminal | Same | Recharts ComposedChart/LineChart, ScenarioPanel, GreekAnalyticsPanel, IVAnalyticsPanel, CapitalPanel, BrokerConnectionPanel | Active |
| `/positions` | AuthGate > Shell | Open positions | Table | Same | Position table + exit controls | Active |
| `/portfolio` | AuthGate > Shell | Portfolio summary | Dashboard | Same | — | Active |
| `/orders` | AuthGate > Shell | Order history | Table | Same | — | Active |
| `/brokers` | AuthGate > Shell | Broker connection | Settings | Same | — | Active |
| `/settings` | AuthGate > Shell | Settings + OAuth | Settings | Same | — | Active |
| `/market` | — | Legacy redirect | — | — | Redirects to `/dashboard` | Redirect |
| `/strategies` | — | Legacy redirect | — | — | Redirects to `/paper` | Redirect |
| `/activity` | — | Legacy redirect | — | — | Redirects to `/orders` | Redirect |

### Navigation structure (`Shell.js` NAV_SECTIONS)

```
MARKET:    Dashboard, GEX Intelligence
BUILD:     Strategy Builder
MANAGE:    Positions, Portfolio, Orders
SYSTEM:    Brokers, Settings
```

**Legacy route map** (`ROUTE_KEY_MAP`): `/market`→dashboard, `/strategies`→paper, `/activity`→orders.

**Responsive behavior:** Mobile breakpoint at 900px (sidebar collapses to hamburger + overlay). Public header collapses at 768px (dropdown→hamburger). Dashboard table supports compact mode.

---

## 5. Existing Design-System Inventory

### 5.1 Public token system (`components/public/tokens.js`)

#### Color (COLOR)
- **Base:** `#06080B` (obsidian), `#0B0E14` (elevated bg)
- **Surfaces:** surface `#12161F`, surfaceElevated `#171C27`, surfaceDeep `#0E1118`
- **Borders:** border `#242B3A`, borderSubtle `rgba(36,43,58,0.35)`, borderStrong `#3A4255`
- **Text:** textPrimary `#E7E9EE`, textSecondary `#949CB0`, textMuted `#7B8398`, textFaint `#5A6376`
- **Accents:** info `#22D3EE` (cyan/live), intelligence `#A78BFA` (violet/analysis), strategy `#C9A15A` (gold/decision)
- **Semantic:** positive `#4CAF7D`, negative `#E15252`, warning `#F59E0B`
- **Signal field:** signalOi, signalIv, signalGreeks, signalPrice
- All accent colors have `Dim` (15% opacity fill) and `Glow` (35% glow) variants

#### Typography (TYPE)
- **Families:** display/body = `Inter, system-ui`; data = `JetBrains Mono, SF Mono, Fira Code, monospace`
- **Display:** displayHero, displayH1, displayH2 (clamp-scaled, -0.04em to -0.02em letter-spacing, weight 700-800)
- **Heading:** h1-h4 (clamp + fixed)
- **Body:** bodyLarge 1.125rem, body 1rem, bodySmall 0.875rem (lineHeight 1.65-1.7)
- **Labels:** label 0.8125rem/0.06em/uppercase, labelSmall 0.6875rem/0.08em/uppercase, caption 0.75rem/0.02em
- **Data:** dataHero, dataLarge, data 1rem, dataSmall 0.8125rem (tabular numerals)

#### Spacing (SPACE)
- 4px → 88px scale: micro(4), xs(6), small(8), sm(10), medium(12), comp(16), compLg(20), card(24), cardLg(32), group(40), section(64), sectionLg(80), hero(88)

#### Radii (RADIUS)
- none 0, sm 4, md 8, lg 12, xl 16, pill 9999px

#### Shadows (SHADOW)
- none, sm `0 1px 3px rgba(0,0,0,0.25)`, md `0 4px 12px rgba(0,0,0,0.30)`, lg `0 12px 40px rgba(0,0,0,0.40)`
- glowInfo, glowStrategy, glowIntelligence (1px border + 12px glow)

#### Layer (z-index)
- base 0, dropdown 10, sticky 100, overlay 200, modal 300

#### Breakpoints (BREAKPOINT)
- sm 640, md 768, lg 1024, xl 1280, xxl 1440

#### Motion (MOTION)
- Durations: instant 0.08s, fast 0.15s, normal 0.25s, slow 0.40s
- Easing: easeOut `cubic-bezier(0.22,1,0.36,1)`, easeIn, easeInOut, signalTrace
- Keyframes: fadeIn, fadeUp, pulse, signalGlow, traceDraw, ticker, barFill, nodeAppear

#### Data states (DATA_STATE, RESEARCH_STATUS)
- LIVE (info), DERIVED (intelligence), DEMO (warning), ILLUSTRATIVE (textMuted), UNAVAILABLE (textFaint), RESEARCH (intelligence)
- RESEARCH_STATUS: AVAILABLE (positive), COMING_LATER (info), RESEARCH_DIRECTION (intelligence)

### 5.2 App token system (`lib/ui.js` `C` object)

| Token | Value |
| ----- | ----- |
| surface | `#12161F` |
| surface2 | `#171C27` |
| border | `#242B3A` |
| muted | `#949CB0` |
| faint | `#7B8398` |
| text | `#E7E9EE` |
| gold | `#C9A15A` |
| green | `#4CAF7D` |
| red | `#E15252` |

**Gap:** The app system is missing info, intelligence, positive/negative/warning semantic tokens, all spacing/radius/shadow/motion/typography tokens. This means any Phase B work that introduces new app UI must either extend `C` (risking duplication) or bridge to the public token system.

### 5.3 App page design patterns

All app pages use the same pattern:
1. Import `C` (and helpers) from `@/lib/ui`
2. Import `AppPanel`, `SectionTitle`, `MetricCard` from `@/components/app/styles`
3. Inline styles via `style={{...}}` objects
4. Hand-built tables with sticky headers
5. No component primitives for buttons, badges, inputs — these are inline-styled elements with manual hover handlers (`onMouseEnter`/`onMouseLeave`)

---

## 6. Component Inventory

| Component | Location | Current purpose | Reuse level | DS relevance | Recommendation |
| -------- | -------- | --------------- | ----------- | ------------ | -------------- |
| `Surface` | `components/public/surfaces.js` | Primitive surface treatment | High | Foundation | **existing** |
| `Panel` | `components/public/surfaces.js` | Card-like container | High | Foundation | **existing** |
| `MetricPanel` | `components/public/surfaces.js` | Numeric display panel | High | Core data | **existing** |
| `Button` | `components/public/buttons.js` | Semantic button (4 variants × 3 sizes) | High | Foundation | **existing** |
| `LinkButton` | `components/public/buttons.js` | Anchor-as-button | High | Foundation | **existing** |
| `SignalField` | `components/public/SignalField.js` | Market state visualization | High | Core module | **existing** |
| `Metric` | `components/public/Metric.js` | Metric with status/source | High | Core data | **existing** |
| `WorkflowTabs` | `components/public/WorkflowTabs.js` | Accessible tabs | High | Interaction | **existing** |
| `SectionTitle` | `components/public/truth.js` | Semantic section heading | High | Foundation | **existing** |
| `DemoLabel` | `components/public/truth.js` | Demo/illustrative badge | High | Truth | **existing** |
| `DataStateBadge` | `components/public/truth.js` | Data classification badge | High | Truth | **existing** |
| `Shell` | `components/Shell.js` | App shell (top bar + sidebar) | Critical | Application shell | **adapt** |
| `AppPanel` | `components/app/styles.js` | App panel/card | High | Application shell | **adapt** (consume public tokens) |
| `MetricCard` | `components/app/styles.js` | Metric display in app | High | Core data | **adapt** (replace with `Metric`) |
| `GexProfileChart` | `components/GexProfileChart.js` | Net GEX bar chart | High | MI module | **adapt** |
| `GexFlipPanel` | `components/GexFlipPanel.js` | Gamma flip display | High | MI module | **adapt** |
| `GexWallTracker` | `components/GexWallTracker.js` | Gamma wall cards | High | MI module | **adapt** |
| `GexHistoryChart` | `components/GexHistoryChart.js` | GEX time series | High | MI module | **adapt** |
| `GexRegimeTimeline` | `components/GexRegimeTimeline.js` | Regime timeline | High | MI module | **adapt** |
| `GexDataQualityPanel` | `components/GexDataQualityPanel.js` | Data quality | High | MI module | **adapt** |
| `HomeHero` | `components/public/HomeHero.js` | Hero section | Public only | H shell | **existing** |
| `PublicHeader` | `components/public/PublicHeader.js` | Public navigation | Public only | H shell | **existing** |
| `AuthModal` | `components/public/AuthModal.js` | Auth modal | Shared | Interaction | **existing** |

---

## 7. UI Surface Inventory

### A. Foundation (typography, colors, spacing, radii, borders, shadows, focus, chart tokens)
- **Public:** Full system in `tokens.js`. Complete.
- **App:** Only `C` color object. No typography/spacing/radius/shadow tokens. **Gap: High.**

### B. Application shell
- **Public:** `PublicLayout` + `PublicHeader` + `PublicFooter` (sticky, responsive, mobile menu, dropdown nav).
- **App:** `Shell` (fixed top bar + collapsible sidebar + mobile overlay). `AuthGate` boundary.
- **Gap:** App shell has no token consumption; uses raw `C` values inline.

### C. Core data components
- **KPI/metric blocks:** `MetricCard` (app, inline) vs `Metric` (public, token-driven). **Gap: adapt.**
- **Intelligence cards:** `MarketIntelligenceGrid`, `AnalyticalLayerGrid` (public only). App has no equivalent.
- **Tables:** App uses hand-rolled `<table>` with sticky headers. No table primitive. **Gap: create.**
- **Filters:** App uses raw `<select>` elements. No filter primitive. **Gap: create.**
- **Segmented controls:** None. App uses custom tab buttons. **Gap: create.**
- **Badges:** `AppBadge`/`AppChip` (app, inline) vs `DataStateBadge`/`DemoLabel` (public). **Gap: adapt.**
- **Tooltips:** Recharts `Tooltip` (app) vs none (public). **Gap: create.**
- **Chart containers:** Recharts `ResponsiveContainer` (app) vs `VisualizationFrame`/`SignalPanel` (public). **Gap: adapt.**
- **Loading/error/empty:** `EmptyState`/`LoadingState` objects (app) vs none (public). **Gap: create.**
- **Actions:** `AppButtonPrimary/Secondary/Ghost` (app) vs `Button` (public). **Gap: adapt.**

### D. Market Intelligence
- **GEX:** `GexProfileChart` (Recharts horizontal bar, color-coded green/red by sign). Good caveats.
- **Gamma Flip:** `GexFlipPanel` (spot, flip strike, distance, position above/below). Good caveats.
- **Walls:** `GexWallTracker` (call/put wall cards + ranked list). Good caveats.
- **OI:** Dashboard option chain OI cells with background bars (red=call, green=put). **Note:** Color here indicates side, not direction — but could be misread.
- **IV:** Dashboard chain shows IV per contract. `IVAnalyticsPanel` in paper page.
- **Vega/Delta/Gamma/Theta:** Dashboard chain columns + `GreekAnalyticsPanel`.
- **Regime/signal:** `GexRegimeTimeline` (POS/NEG/NEUTRAL colored bars). Good caveats.

### E. Strategy Lab
- Paper page (`/paper`) has full strategy builder: leg table, payoff chart (Recharts ComposedChart), scenario panel, Greek analytics, IV analytics, capital panel, portfolio analytics. All inline-styled.

### F. Paper Trading
- Same `/paper` route. Positions table, order execution, journal, equity curve. All inline-styled.

### G. Trading Journal
- Backend-driven journal with pagination, CSV export. Inline-styled table.

### H. Public website
- Home page with 8 sections: Hero, Platform Preview, Analytical Layers, Signal Field, Market Intelligence, Evidence & Trust, Strategy Lab (interactive tabs), Risk (payoff), Paper Trading (interactive tabs), CTA.
- Sub-pages: features, market-intelligence, strategy-lab, paper-trading, how-it-works, about.

---

## 8. Quantitative UI Semantics Audit

### 8.1 Methodological soundness (✓ = good, ⚠ = watch, ✗ = issue)

| Component | Caveat present | Structural framing | No directional claim | Units clear | Verdict |
| --------- | :------------: | :----------------: | :------------------: | :---------: | :-----: |
| `GexProfileChart` | ✓ (legend) | ✓ (call+/put−) | ✓ | ✓ (₹ Cr/L) | ✓ |
| `GexFlipPanel` | ✓ (footer) | ✓ (flip strike) | ✓ (no bull/bear) | ✓ (points/%) | ✓ |
| `GexWallTracker` | ✓ (footer) | ✓ (structural levels) | ✓ (not targets) | ✓ (₹ Cr/L) | ✓ |
| `GexHistoryChart` | ✓ (footer) | ✓ (net GEX) | ✓ (not trading signal) | ✓ (₹ Cr/L) | ✓ |
| `GexRegimeTimeline` | ✓ (footer) | ✓ (regime = sign) | ✓ (not directional) | ✓ (POS/NEG/NEU) | ✓ |
| `GexDataQualityPanel` | ✓ (classification) | ✓ (score) | n/a | ✓ (% coverage) | ✓ |
| Dashboard GEX card | ✓ (header) | ✓ (regime) | ✓ | ✓ | ✓ |
| Dashboard option chain | ⚠ (header) | ✓ (OI bars) | ⚠ (PCR color) | ✓ | ⚠ |
| Dashboard PCR metric | ✗ | ✗ | ✗ | ✓ | ✗ |
| Paper payoff chart | ✓ (visualization) | ✓ (P&L curve) | ✓ | ✓ (₹) | ✓ |
| Paper scenario panel | ✓ (hypothetical) | ✓ (BS model) | ✓ | ✓ | ✓ |
| Paper Greek analytics | ✓ (live vs model) | ✓ (canonical units) | ✓ | ✓ | ✓ |

### 8.2 Findings

**Finding 1 (Medium): Dashboard PCR color implies direction.**
- Location: `app/(app)/dashboard/page.js:282`
- Code: `color={pcr == null ? C.muted : pcr > 1 ? C.green : pcr < 0.8 ? C.red : C.text}`
- Issue: PCR > 1 colored green (traditionally "bullish"), PCR < 0.8 colored red ("bearish"). This is a directional implication that contradicts the design system's rule against using green/red for market state.
- Recommendation: Use neutral text color for PCR; rely on label/text, not color, for interpretation.

**Finding 2 (Low): Dashboard OI cell bars use red/green for call/put.**
- Location: `app/(app)/dashboard/page.js:427`
- Code: `barColor = side === "call" ? "rgba(225,82,82,0.25)" : "rgba(76,175,125,0.25)"`
- Issue: Red = call, green = put. This is a side-indicator convention (not direction), but the colors are the same as the semantic positive/negative palette. A user might read "red OI = bad" or "green OI = good."
- Recommendation: Consider using neutral/info tones for side distinction, reserving green/red for semantic states.

**Finding 3 (Low): Dashboard header "Market Regime: BULLISH" example in spec.**
- The design spec shows `Market Regime: BULLISH` with `Confidence: 78%`. The current app does NOT implement this (it shows Gamma Regime as POSITIVE_GAMMA/NEGATIVE_GAMMA). When Phase B implements the Market State panel, it must ensure confidence is scientifically justified and caveated.

**Finding 4 (Positive): GEX components are exemplary.**
All five GEX components (`GexProfileChart`, `GexFlipPanel`, `GexWallTracker`, `GexHistoryChart`, `GexRegimeTimeline`) carry explicit footer caveats: "Not a trading signal", "Structural level, not directional signal", "Structural context, not directional signal", "Structural levels, not targets". This matches the design spec's requirement that GEX be presented as market-structure context, not direction.

**Finding 5 (Positive): SignalField demo is fully deterministic.**
`DEMO_SIGNAL_STATE` is a static object (no `Math.random()`). All values are illustrative and labeled DEMO. The component carries `role="img"` with descriptive `aria-label`. Reduced-motion is supported via `prefers-reduced-motion` in `PUBLIC_DS_CSS`.

**Finding 6 (Low): No color-only state communication.**
All semantic states in the public system have text labels alongside color. The app's market-status badge uses color + text ("MARKET OPEN" / "MARKET CLOSED"). The execution-mode badge uses color + text ("PAPER" / "LIVE"). This is compliant.

---

## 9. Public Website Inventory

### Home page (`/`)

| Element | Implementation |
| ------ | -------------- |
| Hero | `HomeHero` — radial gradient bg, "OPTIONS INTELLIGENCE FOR STRUCTURED DECISIONS." headline, gold accent on "FOR STRUCTURED DECISIONS.", supporting copy, primary CTA "Explore StrikeNova →", secondary "Strategy Lab" |
| Branding | "StrikeNova" wordmark + "OPTIONS INTELLIGENCE" tagline in header |
| Navigation | Sticky `PublicHeader` with dropdown groups (Product, Learn), mobile hamburger menu |
| Sections | 8 sections: Hero, Platform Preview, Analytical Layers (8 intelligence layers), Signal Field (SignalMetricOverview), Market Intelligence (4-panel grid), Evidence & Trust, Strategy Lab (interactive tabs), Risk (payoff + metrics), Paper Trading (interactive tabs), CTA |
| Feature cards | `FeatureCard` (icon + title + desc) |
| Charts | `SignalField` (SVG), `PayoffMiniChart` (SVG), `AnalyticalLayerGrid` (SVG glyphs), `MarketIntelligenceGrid` (SVG + CSS bars) |
| Animations | `sn-fade-up`, `sn-pulse`, `sn-ticker` (CSS keyframes), reduced-motion support |
| Responsive | 768px breakpoint (header), grid collapses to 1-column on mobile |
| Footer | `PublicFooter` |

### Visual language classification

The current public site is **fintech / trading-terminal** with **premium SaaS** restraint. It avoids:
- neon/glow aesthetics (only subtle gold glow on hover)
- crypto/Web3 visual language
- generic AI illustrations
- template-generated look
- excessive glassmorphism
- animation-first design

It embraces:
- dark obsidian surfaces
- restrained gold accent
- technical SVG visualizations
- editorial section rhythm
- real analytical artifacts (not fake charts)
- tabular numerals for data

**Match to design spec:** High. The public site already embodies the spec's "premium, quietly powerful, quantitative" personality.

---

## 10. Verification Results

| Check | Result | Evidence |
| ----- | ------ | -------- |
| Install state | ✓ | `node_modules` present, no install needed |
| Build | ✓ PASS | `next build` — 17 routes compiled, all static |
| Tests | ✓ PASS | `vitest run` — **1706 tests passed** across 72 test files, 19.15s |
| Lint/type-check | N/A | Not configured (no ESLint, no TypeScript) |
| Dev server smoke test | Skipped | Requires running backend for authenticated pages; public pages are static |
| Screenshots | Skipped | Browser tool not invoked (static build verification sufficient) |

**Warnings during test run:**
- `tokens.js` has duplicate keys `body` and `data` in the TYPE object (lines 97, 108). The later entry wins at runtime (no functional impact), but this is a code-quality issue for Phase B to clean up.

---

## 11. Gap Matrix

| Area | Current state | Evidence/location | DS requirement | Gap | Classification |
| ---- | ------------- | ----------------- | -------------- | --- | -------------- |
| **Token system (public)** | Complete semantic tokens | `components/public/tokens.js` | Tokens for color/type/space/radius/shadow/motion | None | **existing** |
| **Token system (app)** | Minimal flat `C` object (9 keys) | `lib/ui.js` | Full token coverage | Missing: info/intelligence/warning, spacing, radius, shadow, typography, motion, data states | **Critical** → adapt |
| **Surface primitives** | 5 surface components (public) | `components/public/surfaces.js` | Surface/Panel/MetricPanel | App has no equivalent; uses inline `AppPanel` object | **High** → adapt |
| **Button primitives** | 3 button components (public) | `components/public/buttons.js` | Button/LinkButton/TextLink | App uses inline-styled `<button>` elements | **High** → adapt |
| **Metric display** | `Metric` component (public) | `components/public/Metric.js` | Metric with status/source/size | App uses `MetricCard` (inline, no status/source) | **High** → adapt |
| **Data state badges** | `DataStateBadge`, `DemoLabel` (public) | `components/public/truth.js` | LIVE/DERIVED/DEMO/ILLUSTRATIVE | App uses inline `AppBadge`/`AppChip` | **Medium** → adapt |
| **Section heading** | `SectionTitle` (public) | `components/public/truth.js` | Semantic heading with eyebrow | App uses raw `<h1>`/`<h2>` with inline styles | **Medium** → adapt |
| **App shell** | `Shell` (inline-styled) | `components/Shell.js` | Stable shell with nav/context | No token consumption; hardcoded widths (220px sidebar) | **High** → adapt |
| **App navigation** | `NAV_SECTIONS` in Shell | `components/Shell.js:10-39` | Workflow-aligned nav | Current nav is functional but not design-system driven | **Medium** → adapt |
| **Option chain table** | Hand-rolled `<table>` | `app/(app)/dashboard/page.js` | Configurable columns, progressive disclosure | No table primitive; inline styles; no column configuration | **High** → create |
| **Loading/empty/error** | Inline objects | `components/app/styles.js` | Shared empty/loading/error states | Duplicated per-page; no shared component | **Medium** → create |
| **Tooltip** | Recharts `Tooltip` | Various app pages | Contextual tooltips | No shared tooltip primitive; Recharts-only | **Medium** → create |
| **Filter/segmented control** | Raw `<select>` | Various app pages | Filters, segmented controls | No filter/segmented-control primitive | **Medium** → create |
| **Dialog/modal** | `AuthModal` (public) | `components/public/AuthModal.js` | Modal dialogs | Only auth modal exists; no generic dialog | **Medium** → create |
| **Chart containers** | `ResponsiveContainer` (app) | Various app pages | Chart containers with frame | App uses raw Recharts; public has `VisualizationFrame` | **Medium** → adapt |
| **GEX components** | 5 components (app) | `components/Gex*.js` | GEX/Flip/Walls/History/Regime | Good structure; need token migration | **Low** → adapt |
| **Market State panel** | Not implemented | — | Market state + confidence | Spec example shows "BULLISH / 78%"; not yet built | **High** → create |
| **Strategy Lab** | Paper page builder | `app/(app)/paper/page.js` | Strategy builder + payoff | Functional but inline-styled; no DS primitives | **Medium** → adapt |
| **Paper Trading** | Paper page positions | `app/(app)/paper/page.js` | Execution environment | Functional but inline-styled | **Medium** → adapt |
| **Trading Journal** | Backend-driven table | `app/(app)/paper/page.js` | Journal/review | Functional but inline-styled | **Low** → adapt |
| **Public pages** | 7 pages | `app/(public)/*` | Marketing site | Already design-system compliant | **existing** → existing |
| **TypeScript** | None | — | Type safety | No TypeScript; no type checking | **Low** → defer |
| **ESLint** | None | — | Code quality | No linting configured | **Low** → defer |

### Priority summary

| Priority | Count | Areas |
| -------- | ----- | ----- |
| Critical | 1 | App token system (bridge to public tokens) |
| High | 5 | Surface primitives, Button primitives, Metric display, App shell, Option chain table, Market State panel |
| Medium | 8 | Data state badges, Section heading, App nav, Loading/empty/error, Tooltip, Filter/segmented, Dialog, Chart containers, Strategy Lab, Paper Trading |
| Low | 3 | GEX components, Journal, TypeScript/ESLint |

---

## 12. Phase B Readiness

### 12.1 Readiness answers

1. **Is there already a usable token system?**
   Yes — `components/public/tokens.js` is a complete, tested, production-ready semantic token system. It covers color, typography, spacing, radii, shadows, z-index, breakpoints, motion, and data states.

2. **Are duplicate token systems present?**
   Yes — `lib/ui.js` exports a flat `C` object with 9 color keys that duplicate values from the public COLOR tokens. The app consumes `C` exclusively; the public system consumes `tokens.js`. These must be unified.

3. **Which tokens should be normalized?**
   The `C` object in `lib/ui.js` should be replaced by re-exports from `components/public/tokens.js` (e.g. `export const C = { surface: COLOR.surface, ... }`). All app pages import from `@/lib/ui`; changing the import target is a mechanical refactor.

4. **Which existing primitives should be retained?**
   All public primitives: `Surface`, `Panel`, `MetricPanel`, `OutlinePanel`, `SignalPanel`, `Button`, `LinkButton`, `TextLink`, `Metric`, `SignalField`, `VisualizationFrame`, `WorkflowTabs`, `SectionTitle`, `DemoLabel`, `DataStateBadge`, `Eyebrow`, `SignalLine`, `SignalNode`, `StrikeRail`, `DataTrace`, `TechnicalDivider`, `GridOverlay`, `Section`, `Container`, `TwoColumn`, `MetricGrid`, `CardGrid`, `BentoGrid`, `FlexRow`, `FlexColumn`, `Asymmetric`.

5. **Which components need adaptation?**
   `Shell`, `AppPanel`, `MetricCard`, `AppBadge`, `AppChip`, `AppButtonPrimary/Secondary/Ghost`, `AppTab`, `AppInput`, `AppSelect`, `GexProfileChart`, `GexFlipPanel`, `GexWallTracker`, `GexHistoryChart`, `GexRegimeTimeline`, `GexDataQualityPanel`.

6. **Which components genuinely need creation?**
   - `Table` (configurable options chain with progressive disclosure)
   - `MarketStateBadge` (market state + confidence)
   - `Dialog`/`Modal` (generic, beyond auth)
   - `Tooltip` (shared, reduced-motion safe)
   - `Filter`/`SegmentedControl`
   - `EmptyState`/`LoadingState`/`ErrorState` (shared components)
   - `ChartContainer` (Recharts wrapper with frame)

7. **Are there architecture risks?**
   - Low risk. The public system is isolated and tested. The migration is additive (new imports) before subtractive (removing `C`).
   - The `lib/ui.js` helpers (`fmtIN`, `fmtChg`, `useIsMobile`, `TopNav`, `SymbolTabs`, `Stat`, `StepButton`, `ShapeIcon`, `LOT_SIZES`, `SYMBOLS`) are used across many pages and must remain available during migration.

8. **Are there visual-regression risks?**
   - Medium risk. The app's inline styles use the same color *values* as the public system, so a token-swap should be visually identical. However, spacing/typography changes (if introduced) could shift layouts.
   - Mitigation: migrate tokens first (no visual change), then primitives (visual parity), then spacing/typography (visual refinement with regression testing).

9. **Are there accessibility risks?**
   - Low risk. The public system has reduced-motion support, focus-visible rings, 44px touch targets, and aria-labels on visualizations. The app has basic aria labels but no reduced-motion support and inconsistent focus management.
   - Migration to public primitives will *improve* app accessibility.

10. **Are there quantitative-label/semantic risks?**
    - Low risk. The GEX/Greek/IV UI is methodologically sound. The one PCR color issue (Finding 1) is a quick fix.
    - The `Metric` primitive's `DATA_STATE` system (LIVE/DERIVED/DEMO/ILLUSTRATIVE) should be adopted app-wide to ensure consistent data provenance labeling.

### 12.2 Phase B recommended starting files/components

**Phase B.1 — Token bridge (Critical, ~1 day):**
1. `options-dashboard-project/frontend/lib/ui.js` — Replace `C` object with re-exports from `components/public/tokens.js`. Keep all helper functions intact.
2. `options-dashboard-project/frontend/components/public/tokens.js` — Fix duplicate `body`/`data` keys (cosmetic).

**Phase B.2 — App shell migration (High, ~2 days):**
3. `options-dashboard-project/frontend/components/Shell.js` — Consume public tokens/spacing/radius. Extract nav config to a shared module.
4. `options-dashboard-project/frontend/components/app/styles.js` — Replace inline style objects with public token references.

**Phase B.3 — Core data primitives (High, ~3 days):**
5. `options-dashboard-project/frontend/components/app/Table.js` — New: configurable options chain table with progressive disclosure.
6. `options-dashboard-project/frontend/components/app/MarketStateBadge.js` — New: market state + confidence display.
7. `options-dashboard-project/frontend/components/app/EmptyState.js`, `LoadingState.js`, `ErrorState.js` — New: shared states.

**Phase B.4 — MI component migration (Medium, ~2 days):**
8. `options-dashboard-project/frontend/components/GexProfileChart.js` — Adopt public tokens.
9. `options-dashboard-project/frontend/components/GexFlipPanel.js` — Adopt public tokens.
10. `options-dashboard-project/frontend/components/GexWallTracker.js` — Adopt public tokens.
11. `options-dashboard-project/frontend/components/GexHistoryChart.js` — Adopt public tokens.
12. `options-dashboard-project/frontend/components/GexRegimeTimeline.js` — Adopt public tokens.
13. `options-dashboard-project/frontend/components/GexDataQualityPanel.js` — Adopt public tokens.

**Phase B.5 — Dashboard migration (High, ~2 days):**
14. `options-dashboard-project/frontend/app/(app)/dashboard/page.js` — Adopt Table, Metric, Badge primitives. Fix PCR color (Finding 1).

**Phase B.6 — Paper/Strategy migration (Medium, ~3 days):**
15. `options-dashboard-project/frontend/app/(app)/paper/page.js` — Adopt primitives. (Large file — incremental.)

---

## 13. Risks

| Risk | Severity | Likelihood | Mitigation |
| ---- | -------- | ---------- | ---------- |
| Token bridge breaks app imports | Critical | Low | Re-export pattern (`C` → `COLOR`) preserves all existing import paths |
| Visual regression during migration | Medium | Medium | Token-swap first (no visual change), then primitives, then spacing |
| `lib/ui.js` helper coupling | Medium | High | Keep all helpers (`fmtIN`, `fmtChg`, etc.) in place during migration; only change the `C` export |
| Large file migration (`paper/page.js` 3621 lines) | Medium | High | Incremental: token → primitives → sections; verify build after each |
| Duplicate `body`/`data` keys in `tokens.js` | Low | Certain | Fix immediately in Phase B.1 (cosmetic but confusing) |
| No TypeScript/type safety | Low | Certain | Defer; not blocking for design system |
| PCR color implies direction | Medium | Certain | Fix in Phase B.5 (change to neutral color) |
| OI bar colors (red/green) misread as directional | Low | Medium | Document as "side indicator, not direction"; consider neutral tones in Phase B.5 |
| Missing implementation plan | Medium | Certain | Proceed from spec; document decisions in Phase B artifacts |

---

## 14. Recommended Next Steps

1. **Acknowledge the missing implementation plan.** The file `docs/superpowers/plans/2026-09-13-strikenova-design-system-v1-implementation-plan.md` does not exist. Phase B should either create it or proceed with this audit as the execution authority.

2. **Approve the token-bridge strategy.** The public `tokens.js` is the clear winner — it's complete, tested, and already in production on the public site. The app's `C` object should be re-exported from it, not the other way around.

3. **Start Phase B with the token bridge (Phase B.1).** This is the lowest-risk, highest-leverage change. It unifies the two systems without any visual change.

4. **Fix the duplicate `body`/`data` keys in `tokens.js`** as part of Phase B.1.

5. **Fix the PCR color issue** (Finding 1) as part of Phase B.5.

6. **Create the `Table` primitive** (Phase B.3) before migrating the dashboard — it's the most complex new component and the dashboard depends on it.

7. **Preserve the GEX components' caveats** during migration. They are exemplary and must not lose their methodological footer text.

8. **Do not redesign the public site.** It already complies with the design spec. Phase B focus is the authenticated application.

---

## Appendix A: File inventory (frontend source)

```
components/
├── app/
│   └── styles.js                          # App style objects (AppPanel, MetricCard, etc.)
├── public/
│   ├── tokens.js                          # ★ Public design tokens (239 lines)
│   ├── surfaces.js                        # Surface primitives (162 lines)
│   ├── buttons.js                         # Button primitives (227 lines)
│   ├── motion.js                          # Motion CSS + utilities (137 lines)
│   ├── signals.js                         # Signal SVG primitives (300 lines)
│   ├── layout.js                          # Layout primitives (286 lines)
│   ├── truth.js                           # Label/badge primitives (180 lines)
│   ├── Metric.js                          # Metric primitive (195 lines)
│   ├── SignalField.js                     # Signal field visualization (481 lines)
│   ├── VisualizationFrame.js              # Chart container
│   ├── HomeHero.js                        # Hero section (112 lines)
│   ├── AnalyticalLayerLayerGrid.js        # 8-layer grid (168 lines)
│   ├── MarketIntelligenceGrid.js          # 4-panel grid (122 lines)
│   ├── FeatureCard.js                     # Feature card (40 lines)
│   ├── WorkflowTabs.js                    # Accessible tabs (86 lines)
│   ├── EvidenceTrustSection.js            # Trust section
│   ├── CTASection.js                      # CTA block
│   ├── PayoffMiniChart.js                 # Payoff SVG
│   ├── PlatformPreview.js                 # Platform mockup
│   ├── PublicHeader.js                    # Public nav (366 lines)
│   ├── PublicFooter.js                    # Footer
│   ├── PublicLayout.js                    # Public shell (62 lines)
│   ├── AuthModal.js                       # Auth modal
│   ├── AuthModalContext.js                # Auth modal state
│   ├── styles.js                          # Legacy public CSS (89 lines)
│   ├── index.js                           # Barrel export
│   └── *.test.js                          # Component tests
├── Shell.js                               # App shell (462 lines)
├── AuthGate.js                            # Auth boundary
├── GexProfileChart.js                     # GEX bar chart (430 lines)
├── GexHistoryChart.js                     # GEX line chart (147 lines)
├── GexRegimeTimeline.js                   # Regime timeline (185 lines)
├── GexWallTracker.js                      # Wall tracker (150 lines)
├── GexFlipPanel.js                        # Flip panel (154 lines)
└── GexDataQualityPanel.js                 # Data quality (170 lines)

app/
├── layout.js                              # Root layout
├── (app)/
│   ├── layout.js                          # AuthGate > Shell
│   ├── dashboard/page.js                  # Option chain (559 lines)
│   ├── gex/page.js                        # GEX intelligence (491 lines)
│   ├── paper/page.js                      # Strategy + Paper (3621 lines)
│   ├── paper/*.js                         # 9 sub-components
│   ├── positions/page.js
│   ├── portfolio/page.js
│   ├── orders/page.js
│   ├── brokers/page.js
│   ├── settings/page.js
│   ├── activity/page.js                   # Legacy
│   ├── market/page.js                     # Legacy
│   └── strategies/page.js                 # Legacy
└── (public)/
    ├── layout.js                          # PublicLayout
    ├── page.js                            # Home (375 lines)
    ├── about/page.js
    ├── features/page.js
    ├── how-it-works/page.js
    ├── market-intelligence/page.js
    ├── paper-trading/page.js
    └── strategy-lab/page.js

lib/
├── ui.js                                  # ★ App token object `C` (169 lines)
├── api.js                                 # Backend client
├── session.js                             # Session management
├── storage.js                             # localStorage
├── calculations/                          # 20+ quantitative engines
├── strategy/                              # Strategy domain logic
├── portfolio.js, paperUtils.js, capital.js
├── alerts.js, marketStatus.js, brokerDiagnostics.js
├── useChainFeed.js, useGexCapture.js
├── useAuth.js, templates.js
└── *.test.js                              # Library tests
```

## Appendix B: Quantitative caveats inventory

| Component | Caveat text | Location |
| --------- | ----------- | -------- |
| GEX page header | "Market-structure analytics · Not trading signals" | `gex/page.js:179` |
| GEX history footer | "Net GEX = Call GEX (+) + Put GEX (−) · Not a trading signal" | `GexHistoryChart.js:143` |
| GEX regime footer | "Regime = sign of aggregate Net GEX · Structural context, not directional signal" | `GexRegimeTimeline.js:181` |
| GEX flip footer | "Gamma flip = strike where aggregate GEX changes sign · Structural level, not directional signal" | `GexFlipPanel.js:150` |
| GEX walls footer | "Gamma walls = strikes with highest \|GEX\| concentration · Structural levels, not targets" | `GexWallTracker.js:146` |
| GEX profile legend | "Call GEX (+)", "Put GEX (−)" | `GexProfileChart.js:407-414` |
| SignalField | "Demo Data · Illustrative Values Only" | `truth.js:33` |
| Paper scenario | "Analytical only: prices the strategy under hypothetical..." | `paper/page.js` comments |
| Paper Greek analytics | "LIVE broker-chain Greeks vs MODELLED Black-Scholes Greeks" | `paper/page.js` comments |

---

*End of Phase A audit. No source files modified. Ready for Phase B authorization.*
