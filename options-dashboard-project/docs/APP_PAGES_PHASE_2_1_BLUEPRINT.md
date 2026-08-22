# Phase 2.1 Blueprint — App Design System + Shared Layout Foundation

_Last updated: 2026-08-22_

---

## 1. Executive Summary

Phase 2.1 establishes the visual and structural foundation for all authenticated App Pages. This blueprint defines design tokens, typography, navigation architecture, shared components, and responsive behavior.

**Key decisions:**
- The App and public website share the same `C` token set from `lib/ui.js` — no separate token file
- The App needs a `frontend/components/app/styles.js` for app-specific CSS classes (equivalent to the public site's `styles.js`)
- Typography receives the same minimum-size treatment applied in Phase 1 (no text below 11px)
- Navigation is restructured to 7 functional items reflecting the actual trader workflow
- The `/paper` monolith architecture is documented but NOT refactored in Phase 2.1
- All proposed shared components are additive — no existing components are deleted

---

## 2. Design Principles

### 2.1 Core Principles

1. **Same product, different density** — The App must feel like the same product as the public website, but denser because it's a trading application
2. **Data first, interpretation second** — Show the numbers clearly, then add intelligence
3. **Workflow-driven navigation** — Navigation should follow the natural trading workflow
4. **Readable at every size** — No text below 11px for meaningful content, no text below C.faint contrast
5. **Server-authoritative** — The frontend displays; the backend decides
6. **Free-data-first** — No paid data providers required

### 2.2 Marketing UI vs Trading App UI

| Aspect | Marketing (Public Website) | Trading App |
|---|---|---|
| **Spacing** | 72-96px section padding | 16px content padding |
| **Card padding** | 22-28px | 12-14px |
| **Font sizes** | Body 14-16px, H1 48-56px | Body 12-13px, values 13-15px |
| **Information density** | Low — explanatory | High — analytical |
| **Background** | `#0B0E14` page, `#12161F` cards | Same |
| **Color palette** | Identical | Identical |
| **Gold accent** | CTAs, section tags | Active states, important values |
| **Primary text** | `#E7E9EE` | `#E7E9EE` |
| **Secondary text** | `#949CB0` | `#949CB0` |
| **Metadata** | `#7B8398` | `#7B8398` |

The shared token system ensures visual consistency. The difference is density and spacing, not color or typography.

---

## 3. Public Website → App Design Relationship

### 3.1 What Is Shared

| Element | Source | Used In Both |
|---|---|---|
| `C` color tokens | `lib/ui.js` | ✅ |
| `fmtIN` / `fmtChg` | `lib/ui.js` | ✅ |
| `SymbolTabs` | `lib/ui.js` | ✅ |
| `useIsMobile` | `lib/ui.js` | ✅ |
| `Lot sizes` | `lib/ui.js` | ✅ |
| Gold/ghost button patterns | CSS classes | ✅ (to be unified) |
| Card pattern (surface + border + radius) | Inline styles | ✅ (to be formalized) |

### 3.2 What Differs

| Element | Public Website | App |
|---|---|---|
| Navigation | PublicHeader with dropdowns | Shell with sidebar |
| Page width | 1100px max | Full width (no max) |
| Section padding | 72-96px | 16px |
| Animations | fade-up, ticker, pulse | Minimal (data density) |
| Hero sections | Large H1 + subtitle | Terminal header bar |
| CTA buttons | Large (14.5px) | Compact (12-13px) |

### 3.3 What Is App-Only

| Element | Purpose |
|---|---|
| Sidebar navigation | Persistent app chrome |
| TopBar | Execution mode, market status |
| Panel pattern | Dense content containers |
| Stat component | Quick label+value display |
| StepButton | + / - controls |
| Badge patterns | Status indicators |

---

## 4. App Design Tokens

### 4.1 Shared Tokens (from `lib/ui.js` — NO CHANGES)

| Token | Value | Contrast on Surface | Usage |
|---|---|---|---|
| `C.surface` | `#12161F` | — | Card/panel backgrounds |
| `C.surface2` | `#171C27` | — | Elevated surfaces, input backgrounds |
| `C.border` | `#242B3A` | — | Borders, dividers |
| `C.text` | `#E7E9EE` | 14.9:1 | Primary text, values |
| `C.muted` | `#949CB0` | 6.6:1 | Secondary text, labels |
| `C.faint` | `#7B8398` | 4.8:1 | Metadata, timestamps |
| `C.gold` | `#C9A15A` | 7.5:1 | Accents, active states |
| `C.green` | `#4CAF7D` | 6.7:1 | Positive, buy, calls |
| `C.red` | `#E15252` | 4.8:1 | Negative, sell, puts |

### 4.2 App-Specific Tokens (new, in `frontend/components/app/styles.js`)

These are CSS-class-level tokens for common patterns:

```css
/* Panel background — the standard container for content blocks */
.od-app-panel {
  background: #12161F;
  border: 1px solid #242B3A;
  border-radius: 10px;
  padding: 14px;
  min-width: 0;
}

/* Elevated panel — for modals, popovers, dropdowns */
.od-app-elevated {
  background: #0F131B;
  border: 1px solid #242B3A;
  border-radius: 10px;
  box-shadow: 0 18px 50px rgba(0,0,0,0.55);
}

/* Section title — inside panels */
.od-app-section-title {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.8;
  color: #949CB0;
  margin-bottom: 8px;
}

/* Tab button */
.od-app-tab {
  font-size: 11px;
  padding: 5px 11px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #949CB0;
  cursor: pointer;
  font-weight: 400;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}
.od-app-tab-active {
  border-color: #C9A15A;
  background: rgba(201,161,90,0.1);
  color: #C9A15A;
  font-weight: 700;
}

/* Badge/pill */
.od-app-badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.5;
}

/* Row hover for tables */
.od-app-row:hover {
  background: rgba(201,161,90,0.05);
}

/* Scrollbar styling */
.od-app-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.od-app-scroll::-webkit-scrollbar-thumb { background: #242B3A; border-radius: 4px; }
.od-app-scroll::-webkit-scrollbar-track { background: transparent; }

/* Focus-visible for all interactive elements */
.od-app-panel a:focus-visible,
.od-app-panel button:focus-visible,
.od-app-panel input:focus-visible,
.od-app-panel select:focus-visible {
  outline: 2px solid #C9A15A;
  outline-offset: 2px;
}
```

---

## 5. Typography System

### 5.1 Type Scale

| Level | Size | Weight | Color | Usage |
|---|---|---|---|---|
| **Display** | `clamp(20px, 2.5vw, 28px)` | 800 | `C.text` | Page title (rare) |
| **Heading** | 16-18px | 700-800 | `C.text` | Section headings |
| **Subheading** | 14-15px | 700 | `C.text` | Card titles, important labels |
| **Body** | 13px | 400-500 | `C.text` | Primary content |
| **Secondary** | 12px | 400 | `C.muted` | Supporting text, descriptions |
| **Small** | 11px | 600-700 | `C.muted` | Labels, filter controls |
| **Metadata** | 10.5-11px | 600 | `C.faint` | Timestamps, IDs, column headers |
| **Micro** | 10px | 700 | varies | Badges, chips, status pills |

### 5.2 Minimum Sizes

| Context | Minimum | Rationale |
|---|---|---|
| Any readable text | 11px | WCAG + dark-bg readability |
| Table column headers | 11px | Must be legible |
| Labels/metadata | 10.5px | Minimum for identification |
| Badges/chips | 10px | Acceptable for short labels |
| Navigation | 13px | Sidebar items |
| Inputs/selects | 12px | Must be usable |

### 5.3 Font Family

```css
font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
```

Monospace for numerical data where alignment matters:
```css
font-family: "SF Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
font-variant-numeric: tabular-nums;
```

### 5.4 Current Typography Issues (Must Fix)

| Location | Current | Proposed | Reason |
|---|---|---|---|
| Dashboard table headers | 10.5px, `C.faint` | 11px, `C.faint` | Minimum readable |
| Dashboard chain cells | 12.5px | 13px | Body minimum |
| Orders table headers | 10px, `C.faint` | 11px, `C.faint` | Minimum readable |
| Orders detail labels | 9px, `C.faint` | 10.5px, `C.faint` | Minimum readable |
| Paper page section titles | 10-11px | 12px | Must be discoverable |
| Paper page panel labels | 8.5-9px | 10px | Minimum readable |
| Capital panel rows | 11px values | 12px | Primary values need prominence |
| Broker panel detail fields | 8.5px labels | 10px | Must be readable |

---

## 6. Navigation Architecture

### 6.1 Current Sidebar (9 items)

```
📊 Dashboard
📈 Market
📋 Orders
📐 Positions
⚡ Strategies
💼 Portfolio
🕐 Activity
🔗 Brokers
⚙️ Settings
```

### 6.2 Proposed Sidebar (7 items, workflow-aligned)

```
── MARKET ──────────────
📊 Dashboard          Market overview + chain + intelligence

── BUILD ──────────────
⚡ Strategy Builder   Build, analyze, paper-trade strategies

── MANAGE ─────────────
📐 Positions         Open and closed positions
💼 Portfolio         Analytics, capital, performance
📋 Orders            Order history and details

── SYSTEM ─────────────
🔗 Brokers           Connection and diagnostics
⚙️ Settings          Preferences and configuration
```

### 6.3 Route Mapping

| Sidebar Item | Route | Status |
|---|---|---|
| Dashboard | `/dashboard` | Functional — needs intelligence overlay |
| Strategy Builder | `/paper` (rename later) | Functional — monolith to be scoped |
| Positions | `/positions` | Functional — needs Greeks |
| Portfolio | `/portfolio` | Stub → extract from /paper |
| Orders | `/orders` | Functional — needs real-time |
| Brokers | `/brokers` | Stub → extract from /paper |
| Settings | `/settings` | Stub → to be built |

### 6.4 Removed Routes

| Route | Disposition |
|---|---|
| `/market` | Merge intelligence into `/dashboard` or build as standalone later |
| `/strategies` | Becomes the `/paper` route after rename |
| `/activity` | Merge into Orders or build later as timeline view |

### 6.5 Sidebar Visual Design

```
┌──────────────────────────┐
│ ○ MARKET                │  ← section label (10px, faint, uppercase, letter-spacing: 1.5)
│   📊 Dashboard          │  ← active: gold text, gold left border, gold bg tint
│                          │
│ ○ BUILD                 │
│   ⚡ Strategy Builder   │
│                          │
│ ○ MANAGE                │
│   📐 Positions          │
│   💼 Portfolio          │
│   📋 Orders             │
│                          │
│ ○ SYSTEM                │
│   🔗 Brokers            │
│   ⚙️ Settings           │
└──────────────────────────┘
```

**Active state**: `color: C.gold`, `background: rgba(201,161,90,0.08)`, `border-left: 2px solid C.gold`
**Hover state**: `background: rgba(201,161,90,0.04)`
**Section labels**: `fontSize: 10px`, `color: C.faint`, `letterSpacing: 1.5px`, `textTransform: uppercase`, `padding: 16px 16px 4px`

---

## 7. Shared Layout Architecture

### 7.1 Current: `Shell.js`

```
Shell
├── TopBar (fixed, height: 44px)
│   ├── Hamburger (mobile)
│   ├── "Options Dashboard" title
│   ├── Execution mode badge (PAPER/LIVE)
│   ├── Spacer
│   └── Market status indicator
├── Sidebar (fixed, width: 200px)
│   └── NAV_ITEMS (9 items with icons)
├── Mobile overlay
└── Main content (margin-left: 200px, margin-top: 44px, padding: 16px)
```

### 7.2 Proposed: Enhanced Shell

```
Shell
├── TopBar (fixed, height: 48px) ← slightly taller for better spacing
│   ├── Hamburger (mobile only)
│   ├── Logo + "Options Dashboard" (gold)
│   ├── Execution mode badge (PAPER/LIVE)
│   ├── Market status indicator (dot + text)
│   ├── Spacer
│   ├── Equity/value display
│   └── Funds button (popover) + Settings button (popover)
├── Sidebar (fixed, width: 220px) ← slightly wider for section labels
│   ├── Section labels (MARKET, BUILD, MANAGE, SYSTEM)
│   └── Nav items (7 items with icons)
├── Mobile overlay
└── Main content area
    ├── margin-top: 48px
    ├── margin-left: 220px (desktop) / 0 (mobile)
    ├── padding: 16px
    └── max-width: none (data-dense app)
```

### 7.3 TopBar Changes

| Element | Current | Proposed |
|---|---|---|
| Height | 44px | 48px |
| Title | "Options Dashboard" (14px, gold) | "Options Dashboard" (14px, gold) — unchanged |
| Execution badge | 10px font | 10.5px font |
| Market status | 11px text | 12px text |
| Funds popover | In /paper page only | Moved to TopBar (always accessible) |
| Settings popover | In /paper page only | Moved to TopBar → Settings page |

### 7.4 Sidebar Changes

| Element | Current | Proposed |
|---|---|---|
| Width | 200px | 220px |
| Items | 9 flat items | 7 items in 4 sections |
| Section labels | None | MARKET, BUILD, MANAGE, SYSTEM |
| Item font | 13px | 13px (unchanged) |
| Item padding | 8px 16px | 10px 16px |
| Active indicator | 2px left border + gold bg | Same |
| Breakpoint | 900px | 900px (unchanged) |

---

## 8. Shared Component Architecture

### 8.1 Components That Should Be Created

| Component | Purpose | Props | Pages Using |
|---|---|---|---|
| `AppPanel` | Standard content container | `children, className, style` | All pages |
| `SectionTitle` | Panel section header | `children, action?` | All pages |
| `AppTabs` | Tab bar with counts | `tabs[], activeTab, onTabChange` | Orders, Positions |
| `AppBadge` | Status pill | `label, color, variant?` | All pages |
| `MetricCard` | Label + value display | `label, value, color?, hint?` | Dashboard, Portfolio |
| `DataTable` | Consistent table wrapper | `children, scrollable?` | Orders, Positions |
| `FilterBar` | Filter dropdown row | `filters, onFilterChange` | Orders, Positions |
| `EmptyState` | No-data message | `icon, message, action?` | All pages |
| `ErrorState` | Error message with retry | `message, onRetry?` | All pages |
| `LoadingState` | Loading indicator | `message?` | All pages |
| `SessionExpired` | Auth expiry notice | — | All pages (already exists) |

### 8.2 Components That Already Exist (Keep As-Is)

| Component | Location | Purpose |
|---|---|---|
| `TopNav` | `lib/ui.js` | Legacy tab bar (Dashboard/Paper) — will be removed when sidebar is updated |
| `SymbolTabs` | `lib/ui.js` | Symbol selector — used in Dashboard and Paper |
| `Stat` | `lib/ui.js` | Label + value display — used in Paper header |
| `StepButton` | `lib/ui.js` | + / - controls — used in Paper builder |
| `ShapeIcon` | `lib/ui.js` | Strategy shape visualization — used in templates |

### 8.3 Components That Should NOT Be Created Yet

- **StrategyBuilder** — the current builder in /paper works; refactoring is Phase 2.2
- **PayoffChart** — recharts already handles this
- **OrderTicket** — no order entry in the frontend (execution goes through strategy builder)
- **RiskGauge** — premature abstraction

### 8.4 Shared Component File Structure

```
frontend/components/app/
├── AppPanel.js          Standard content container
├── SectionTitle.js      Panel section header
├── AppTabs.js           Tab bar with counts
├── AppBadge.js          Status pill
├── MetricCard.js        Label + value display
├── DataTable.js         Consistent table wrapper
├── FilterBar.js         Filter dropdown row
├── EmptyState.js        No-data message
├── ErrorState.js        Error with retry
├── LoadingState.js      Loading indicator
└── index.js             Barrel exports
```

---

## 9. Page Shell Architecture

### 9.1 Standard Page Pattern

Every app page should follow this structure:

```jsx
<div style={{ padding: isMobile ? 10 : 16 }}>
  {/* Page header */}
  <div style={{ marginBottom: 16 }}>
    <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
      Page Title
    </h1>
    <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
      Page description
    </p>
  </div>
  
  {/* Content */}
  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    {/* Panels go here */}
  </div>
</div>
```

### 9.2 Panel Pattern

```jsx
<div style={{
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
  padding: 14,
  minWidth: 0,
}}>
  <div style={{
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: 0.8,
    color: C.muted,
    marginBottom: 8,
  }}>
    SECTION TITLE
  </div>
  {/* Content */}
</div>
```

### 9.3 Two-Column Layout Pattern (for Dashboard, Positions)

```jsx
<div style={{
  display: "grid",
  gridTemplateColumns: isMobile ? "1fr" : "3fr 2fr",
  gap: 14,
  alignItems: "start",
}}>
  <div>{/* Primary content */}</div>
  <div>{/* Secondary sidebar */}</div>
</div>
```

### 9.4 Metric Grid Pattern

```jsx
<div style={{
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
  gap: 8,
}}>
  <MetricCard label="Spot" value="25,512.00" color={C.gold} />
  <MetricCard label="PCR" value="1.18" color={C.green} />
  {/* ... */}
</div>
```

---

## 10. Dashboard Foundation

### 10.1 Design Principles

The Dashboard should eventually answer:
1. What is the market doing? → Index summary + session change
2. What are the important levels? → Spot, support, resistance, max pain
3. What is positioning saying? → PCR, OI totals, OI shift
4. What is volatility saying? → IV level, VIX, IV change
5. What changed? → Session deltas
6. What is the directional bias? → Composite indicator (future)
7. What deserves attention? → Alerts, unusual activity
8. What risk exists? → Portfolio exposure summary (future)

### 10.2 Proposed Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│  TOP: Market Intelligence Summary (4-6 metric cards)    │
│  [Spot] [PCR] [Max Pain] [IV] [Session Δ] [Bias]      │
├────────────────────────────────────┬────────────────────┤
│  LEFT: Option Chain (primary)      │ RIGHT: Sidebar     │
│  - Symbol selector                 │ - Watchlist        │
│  - Expiry selector                 │ - Price Alerts     │
│  - Spot marker row                 │ - Quick positions  │
│  - Full chain table                │ - Recent activity  │
│  - OI bars, Greeks, LTP           │                    │
├────────────────────────────────────┴────────────────────┤
│  BOTTOM: Intelligence Panels (collapsible)              │
│  [OI Distribution] [Volatility] [Positioning]           │
└─────────────────────────────────────────────────────────┘
```

### 10.3 Intelligence Card Design

Each intelligence card follows this pattern:

```jsx
<div style={{
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 8,
  padding: "8px 10px",
}}>
  <div style={{ fontSize: 10, color: C.faint, letterSpacing: 0.6 }}>SPOT</div>
  <div style={{ fontSize: 14, fontWeight: 700, color: C.gold, marginTop: 2 }}>25,512.00</div>
  <div style={{ fontSize: 10, color: C.green, marginTop: 1 }}>▲ +0.32%</div>
</div>
```

### 10.4 Future Intelligence Integration Points

These are placeholders — no calculations in Phase 2.1:

| Intelligence | Future Source | UI Location |
|---|---|---|
| PCR interpretation | OI analytics | Dashboard summary card |
| OI shift direction | OI change analysis | Dashboard summary card |
| IV regime | IV analytics | Dashboard summary card |
| Directional bias | Composite signal | Dashboard summary card |
| Unusual activity | Volume/OI anomaly | Dashboard alert section |
| GEX levels | GEX calculation | Dashboard + Market page |
| Support/Resistance | OI distribution | Chain table overlays |

---

## 11. Paper Trading Foundation

### 11.1 Current Component Architecture

```
paper/page.js (3,621 lines)
├── State management (~120 state variables)
├── API effects (~15 useEffect blocks)
├── Calculation memos (~20 useMemo blocks)
├── Handler functions (~30 callback functions)
├── Terminal header bar (symbol, spot, mode, equity)
├── PortfolioAnalyticsPanel
├── CapitalPanel
├── BrokerConnectionPanel
├── BulkExitModal
├── 40/60 grid layout
│   ├── ASIDE (40%): Control sidebar
│   │   ├── Strategy builder panel
│   │   ├── Legs table
│   │   ├── Analysis tabs (Scenario, Greeks, IV)
│   │   └── Lower tabs (Ready-made, Positions, My Strategies, Drafts)
│   └── SECTION (60%): Main content
│       ├── Strategy identity strip
│       ├── Dynamic template resolution
│       ├── Legs table (full)
│       ├── Payoff chart
│       ├── Review panel
│       └── Execution controls
└── Journal + History (below the fold)
```

### 11.2 Proposed Component Architecture (Target — NOT Phase 2.1)

```
paper/page.js (RESTRUCTURED — future phase)
├── PaperHeader
│   ├── SymbolSelector
│   ├── SpotDisplay
│   ├── MarketStatusBadge
│   └── EquityDisplay
├── StrategyBuilder
│   ├── TemplateSelector
│   ├── LegEditor
│   ├── AdjustmentTools (Shift/Width/Hedge)
│   └── StrategyIdentity
├── AnalysisPanel
│   ├── PayoffChart
│   ├── ScenarioAnalysis
│   ├── GreekAnalytics
│   └── IVAnalytics
├── ExecutionPanel
│   ├── ReviewPanel
│   ├── ExecutionControls
│   └── MarketGateStatus
├── PositionsPanel (existing, extracted)
├── CapitalPanel (existing, extracted to /portfolio)
├── BrokerPanel (existing, extracted to /brokers)
├── AnalyticsPanel (existing, extracted to /portfolio)
├── JournalPanel (existing, extracted to /portfolio)
└── BulkExitModal (existing)
```

### 11.3 CURRENT vs PROPOSED Components

| Current Component | Proposed Location | Phase |
|---|---|---|
| `page.js` (all state) | Split across focused pages | 2.2+ |
| `PortfolioAnalyticsPanel.js` | `/portfolio` page | 2.1b |
| `CapitalPanel.js` | `/portfolio` page | 2.1b |
| `BrokerConnectionPanel.js` | `/brokers` page | 2.1c |
| `AnalyticsPanel.js` | `/portfolio` page | 2.1b |
| `ScenarioPanel.js` | Stay in `/paper` | 2.2 |
| `GreekAnalyticsPanel.js` | Stay in `/paper` | 2.2 |
| `IVAnalyticsPanel.js` | Stay in `/paper` | 2.2 |
| `BulkExit.js` | Stay in `/paper` | 2.2 |
| `TradeDetailModal.js` | Stay in `/paper` | 2.2 |

---

## 12. Data Visualization Standards

### 12.1 Chart Standards

| Element | Color | Size |
|---|---|---|
| Line (payoff) | `C.gold` | strokeWidth: 2 |
| Area fill (profit) | `rgba(76,175,125,0.12)` | — |
| Area fill (loss) | `rgba(225,82,82,0.12)` | — |
| Grid lines | `C.border` | strokeDasharray: "3 3" |
| Axis text | `C.faint` | fontSize: 10 |
| Reference line | `C.faint` | strokeDasharray: "4 2" |
| Tooltip bg | `C.surface2` | border: `C.border`, borderRadius: 8 |
| Tooltip text | 11px | — |

### 12.2 Bar Chart Standards

| Element | Color |
|---|---|
| Call OI bar | `rgba(225,82,82,0.25)` |
| Put OI bar | `rgba(76,175,125,0.25)` |
| Positive change | `C.green` |
| Negative change | `C.red` |

### 12.3 Table Standards

| Element | Style |
|---|---|
| Header row | `fontSize: 11px`, `color: C.muted`, `fontWeight: 700`, borderBottom: `2px solid C.border` |
| Data row | `fontSize: 13px`, `color: C.text`, borderBottom: `1px solid C.border` |
| Hover | `background: rgba(201,161,90,0.05)` |
| ATM highlight | `background: rgba(201,161,90,0.06)` |
| Cell padding | `8px 12px` (desktop), `6px 8px` (mobile) |
| Numeric alignment | Right-aligned, `fontVariantNumeric: "tabular-nums"` |

---

## 13. Responsive Strategy

### 13.1 Breakpoints

| Name | Width | Behavior |
|---|---|---|
| Mobile | < 768px | Single column, stacked layout, hamburger nav |
| Tablet | 768-1024px | Two columns possible, sidebar visible |
| Desktop | > 1024px | Full layout, sidebar always visible |
| Wide | > 1440px | Can use three columns if needed |

### 13.2 Component Behavior by Breakpoint

| Component | Mobile | Tablet | Desktop |
|---|---|---|---|
| **Sidebar** | Hidden (hamburger) | Visible (220px) | Visible (220px) |
| **TopBar** | Compact (no funds text) | Full | Full |
| **Option chain** | Horizontal scroll, compact mode auto | Horizontal scroll | Full width |
| **Metric cards** | 2 columns | 3-4 columns | 4-6 columns |
| **Charts** | Full width, reduced height | Full width | Full width |
| **Tables** | Horizontal scroll | Horizontal scroll | Full width |
| **Strategy builder** | Full width, stacked | 40/60 grid | 40/60 grid |
| **Positions** | Card-based | Table | Table |
| **Portfolio metrics** | 2 columns | 3 columns | 4-6 columns |
| **Modals** | Full screen | Centered | Centered |

### 13.3 Mobile-Specific Patterns

**Option Chain on Mobile:**
- Auto-enable compact mode (9 columns instead of 21)
- Sticky header row
- Horizontal scroll with momentum
- Consider swipe between calls/puts in future

**Positions on Mobile:**
- Card-based layout instead of table
- Each position card: symbol, strike, type, qty, P&L
- Swipe to exit (future)

**Strategy Builder on Mobile:**
- Stack aside and section vertically
- Full-width legs table
- Collapsible analysis panels

---

## 14. Accessibility Standards

### 14.1 Contrast Requirements

| Text Type | Minimum Ratio | Token Used |
|---|---|---|
| Primary text | 7:1+ | `C.text` (14.9:1) ✅ |
| Secondary text | 4.5:1+ | `C.muted` (6.6:1) ✅ |
| Metadata | 4.5:1+ | `C.faint` (4.8:1) ✅ |
| Gold accent | 4.5:1+ | `C.gold` (7.5:1) ✅ |
| Green/Red | 4.5:1+ | `C.green` (6.7:1), `C.red` (4.8:1) ✅ |

### 14.2 Keyboard Navigation

- All interactive elements must be focusable
- Focus-visible ring: `2px solid C.gold, offset 2px`
- Tab order must follow visual order
- Sidebar navigation must be keyboard-accessible

### 14.3 Screen Reader Considerations

- All tables must have proper `<th>` with `scope`
- All icons must have `aria-label` or be hidden from SR
- Status changes must be announced via `aria-live`
- Loading states must be communicated

---

## 15. Component Reuse Rules

### 15.1 Rules

1. **Don't create a component until 3+ pages need it** — premature abstraction adds complexity
2. **Inline styles are acceptable** for one-off variations — don't over-componentize
3. **Shared components live in `frontend/components/app/`** — not in `lib/`
4. **`lib/ui.js` components stay generic** — they serve both public and app
5. **Panel pattern is the primary container** — don't create alternative container types
6. **Badge/pill pattern is standardized** — all status indicators use the same token set
7. **Charts use recharts** — don't introduce alternative charting libraries

### 15.2 When to Create a Shared Component

| Scenario | Action |
|---|---|
| Used on 1 page | Inline styles |
| Used on 2 pages | Consider shared component |
| Used on 3+ pages | Create shared component |
| Complex behavior (tabs, modals) | Create shared component regardless of count |
| Simple display (label + value) | Create shared component if pattern is consistent |

---

## 16. Implementation Sequence

### Phase 2.1a — Typography + Contrast Patch (App)

**Scope**: Apply the same typography improvements from Phase 1 to all app pages.

| Step | File | Change |
|---|---|---|
| 1 | `components/app/styles.js` | Create new file with app-specific CSS classes |
| 2 | `components/Shell.js` | Update sidebar nav items (7 items, sections), bump font sizes |
| 3 | `app/(app)/dashboard/page.js` | Bump table headers to 11px, chain cells to 13px |
| 4 | `app/(app)/orders/page.js` | Bump table headers to 11px, detail labels to 10.5px |
| 5 | `app/(app)/positions/page.js` | Bump table headers to 11px, detail labels to 10.5px |
| 6 | `app/(app)/paper/page.js` | Bump section titles to 12px, panel labels to 10px |
| 7 | `app/(app)/paper/CapitalPanel.js` | Bump section titles, row values |
| 8 | `app/(app)/paper/BrokerConnectionPanel.js` | Bump section titles, detail fields |
| 9 | `app/(app)/paper/PortfolioAnalyticsPanel.js` | Bump section titles, metric labels |

### Phase 2.1b — Extract Portfolio from /paper

**Scope**: Move PortfolioAnalyticsPanel + CapitalPanel + AnalyticsPanel to `/portfolio`.

| Step | File | Change |
|---|---|---|
| 1 | `app/(app)/portfolio/page.js` | Replace stub with real page consuming existing panels |
| 2 | `app/(app)/paper/page.js` | Remove PortfolioAnalyticsPanel, CapitalPanel imports |

### Phase 2.1c — Extract Broker from /paper

**Scope**: Move BrokerConnectionPanel to `/brokers`.

| Step | File | Change |
|---|---|---|
| 1 | `app/(app)/brokers/page.js` | Replace stub with real page consuming BrokerConnectionPanel |
| 2 | `app/(app)/paper/page.js` | Remove BrokerConnectionPanel import |

### Phase 2.1d — Create Shared App Components

**Scope**: Create the shared component library.

| Step | File | Change |
|---|---|---|
| 1 | `components/app/AppPanel.js` | Standard panel container |
| 2 | `components/app/SectionTitle.js` | Panel section header |
| 3 | `components/app/AppTabs.js` | Tab bar with counts |
| 4 | `components/app/AppBadge.js` | Status pill |
| 5 | `components/app/MetricCard.js` | Label + value display |
| 6 | `components/app/EmptyState.js` | No-data message |
| 7 | `components/app/ErrorState.js` | Error with retry |
| 8 | `components/app/LoadingState.js` | Loading indicator |
| 9 | `components/app/index.js` | Barrel exports |

---

## 17. Files Expected to Change

### Phase 2.1a (Typography Patch)

| File | Change |
|---|---|
| `frontend/components/app/styles.js` | **NEW** — App CSS classes |
| `frontend/components/Shell.js` | Nav restructure, font size bumps |
| `frontend/app/(app)/dashboard/page.js` | Typography fixes |
| `frontend/app/(app)/orders/page.js` | Typography fixes |
| `frontend/app/(app)/positions/page.js` | Typography fixes |
| `frontend/app/(app)/paper/page.js` | Typography fixes |
| `frontend/app/(app)/paper/CapitalPanel.js` | Typography fixes |
| `frontend/app/(app)/paper/BrokerConnectionPanel.js` | Typography fixes |
| `frontend/app/(app)/paper/PortfolioAnalyticsPanel.js` | Typography fixes |
| `frontend/app/(app)/paper/AnalyticsPanel.js` | Typography fixes |

### Phase 2.1b (Extract Portfolio)

| File | Change |
|---|---|
| `frontend/app/(app)/portfolio/page.js` | Replace stub with real page |
| `frontend/app/(app)/paper/page.js` | Remove PortfolioAnalyticsPanel, CapitalPanel |

### Phase 2.1c (Extract Broker)

| File | Change |
|---|---|
| `frontend/app/(app)/brokers/page.js` | Replace stub with real page |
| `frontend/app/(app)/paper/page.js` | Remove BrokerConnectionPanel |

### Phase 2.1d (Shared Components)

| File | Change |
|---|---|
| `frontend/components/app/AppPanel.js` | **NEW** |
| `frontend/components/app/SectionTitle.js` | **NEW** |
| `frontend/components/app/AppTabs.js` | **NEW** |
| `frontend/components/app/AppBadge.js` | **NEW** |
| `frontend/components/app/MetricCard.js` | **NEW** |
| `frontend/components/app/EmptyState.js` | **NEW** |
| `frontend/components/app/ErrorState.js` | **NEW** |
| `frontend/components/app/LoadingState.js` | **NEW** |
| `frontend/components/app/index.js` | **NEW** |

---

## 18. Files That Must NOT Change

| Category | Files |
|---|---|
| **Backend** | `backend/` — entire directory |
| **API** | `frontend/lib/api.js` — endpoints |
| **Auth** | `frontend/lib/session.js` — OAuth flow |
| **Calculations** | `frontend/lib/calculations/` — all calculation modules |
| **Strategy logic** | `frontend/lib/strategy/` — all strategy modules |
| **Templates** | `frontend/lib/templates.js` |
| **Paper utils** | `frontend/lib/paperUtils.js` |
| **Portfolio logic** | `frontend/lib/portfolio.js` |
| **Capital logic** | `frontend/lib/capital.js` |
| **Market status** | `frontend/lib/marketStatus.js` |
| **Pricing** | `frontend/lib/pricing.js` |
| **Alerts** | `frontend/lib/alerts.js` |
| **Analytics** | `frontend/lib/analytics.js` |
| **Broker diagnostics** | `frontend/lib/brokerDiagnostics.js` |
| **Chain feed** | `frontend/lib/useChainFeed.js` |
| **Tests** | All `.test.js` files |

---

## 19. Testing Strategy

### 19.1 Existing Tests (Must Continue Passing)

- 946 tests across 38 test files
- All must continue passing after Phase 2.1 changes

### 19.2 New Tests Needed

| Test | Scope | Priority |
|---|---|---|
| Shell sidebar rendering | 7 items, correct sections | P1 |
| EmptyState component | Renders message | P2 |
| ErrorState component | Renders message + retry button | P2 |
| MetricCard component | Renders label + value | P2 |

### 19.3 Visual Verification

- All 10 routes must render without errors
- Sidebar must show 7 items in 4 sections
- Typography must be consistent across all pages
- No horizontal overflow on any page at 390px mobile

---

## 20. Acceptance Criteria

### Phase 2.1a

- [ ] All app pages use minimum 11px for readable text
- [ ] Table headers are 11px minimum
- [ ] Detail labels are 10.5px minimum
- [ ] Section titles are 12px minimum
- [ ] `frontend/components/app/styles.js` exists with all CSS classes
- [ ] All 946 tests pass
- [ ] All 10 routes render without errors
- [ ] No horizontal overflow at 390px mobile

### Phase 2.1b

- [ ] `/portfolio` renders PortfolioAnalyticsPanel and CapitalPanel
- [ ] `/paper` no longer renders PortfolioAnalyticsPanel or CapitalPanel
- [ ] Portfolio data loads correctly on `/portfolio`
- [ ] All tests pass

### Phase 2.1c

- [ ] `/brokers` renders BrokerConnectionPanel
- [ ] `/paper` no longer renders BrokerConnectionPanel
- [ ] Broker data loads correctly on `/brokers`
- [ ] All tests pass

### Phase 2.1d

- [ ] All shared components exist in `frontend/components/app/`
- [ ] Components render correctly in isolation
- [ ] Barrel exports work from `index.js`
- [ ] All tests pass

---

## 21. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Shell.js restructure breaks existing pages | High | Test all 10 routes after each change |
| Extracting panels from /paper breaks data flow | High | Pass same props, test data loading |
| New CSS classes conflict with existing styles | Medium | Use `od-app-` prefix consistently |
| Mobile sidebar change breaks existing mobile behavior | Medium | Test at 390px and 768px breakpoints |
| Shared component abstraction is premature | Low | Only create components used 3+ times |

---

## 22. Open Decisions

1. **Should the TopBar funds popover move to the TopBar, or stay in /paper?**
   - Recommendation: Keep in /paper for now (moving requires TopBar to access paper-specific state)

2. **Should `/market` be removed from the sidebar, or kept as "coming soon"?**
   - Recommendation: Remove from sidebar until it becomes a real page

3. **Should the sidebar sections use dividers or just spacing?**
   - Recommendation: Spacing only (cleaner, matches the minimal aesthetic)

4. **Should shared components use CSS classes or inline styles?**
   - Recommendation: CSS classes in `styles.js` for reusable patterns, inline styles for one-off variations

5. **Should Phase 2.1b/2.1c extract panels before or after the typography patch?**
   - Recommendation: Typography patch first (2.1a), then extraction (2.1b/2.1c)

---

### Phase 2.1 Approval Checklist

Every decision that requires approval before coding begins:

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | **Sidebar item count** | Keep 9 / Reduce to 7 | Reduce to 7 (workflow-aligned) |
| 2 | **Sidebar sections** | No sections / 4 sections | 4 sections (MARKET, BUILD, MANAGE, SYSTEM) |
| 3 | **Remove `/market` from sidebar** | Keep as stub / Remove | Remove until real |
| 4 | **Remove `/strategies` from sidebar** | Keep as stub / Remove | Remove (becomes /paper rename) |
| 5 | **Remove `/activity` from sidebar** | Keep as stub / Remove | Remove until real |
| 6 | **TopBar height** | Keep 44px / Bump to 48px | Bump to 48px |
| 7 | **Sidebar width** | Keep 200px / Widen to 220px | Widen to 220px |
| 8 | **Funds popover location** | Keep in /paper / Move to TopBar | Keep in /paper for now |
| 9 | **App CSS file location** | `components/app/styles.js` / `lib/appStyles.js` | `components/app/styles.js` |
| 10 | **Shared component prefix** | `od-app-*` / `App*` | `od-app-*` for CSS, `App*` for components |
| 11 | **Portfolio extraction timing** | Phase 2.1 / Phase 2.2 | Phase 2.1b |
| 12 | **Broker extraction timing** | Phase 2.1 / Phase 2.2 | Phase 2.1c |
| 13 | **Dashboard intelligence cards** | Phase 2.1 / Phase 2.2 | Phase 2.2 (define layout only in 2.1) |
| 14 | **Position Greeks** | Phase 2.1 / Phase 2.2 | Phase 2.2 |
| 15 | **Real-time Orders/Positions** | Phase 2.1 / Phase 2.2 | Phase 2.2 |

---

_Report produced: 2026-08-22_
_Phase: 2.1 Blueprint Only — No code changes, no commits, no pushes, no deployments_
