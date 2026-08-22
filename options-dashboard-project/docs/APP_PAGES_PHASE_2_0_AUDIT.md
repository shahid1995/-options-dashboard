# Phase 2.0 — App Pages Audit

_Last updated: 2026-08-22_

---

## 1. Executive Summary

The authenticated App Pages represent the core trading experience. After a thorough audit of all 10 routes, shared components, API layer, and library code, the findings are:

**The App has a working foundation but significant structural problems.**

- **5 of 10 pages are stubs** (Market, Strategies, Portfolio, Activity, Brokers, Settings) — they are either redirect cards or "coming soon" placeholders
- **1 page is a monolith** — `/paper` is ~3,600 lines containing the strategy builder, paper trading, analytics, journal, capital, broker diagnostics, scenario analysis, Greek analytics, IV analytics, templates, bulk exit, and more
- **The Dashboard is functional but unintuitive** — it shows a raw option chain with no market intelligence interpretation
- **No design-system consistency** with the completed Phase 1 public website
- **Typography and readability issues** identical to the pre-patch public site
- **Navigation doesn't reflect the trader workflow** — 9 sidebar items when only 3-4 are functional

**The App architecture is suitable for continued development**, but the Phase 2 work should focus on:
1. Breaking up the `/paper` monolith into properly separated pages
2. Making the stub pages real
3. Aligning the App design system with the public website
4. Making the trader workflow obvious through navigation and information hierarchy

---

## 2. Current App Architecture

### 2.1 Page Structure

```
frontend/app/
├── layout.js                    (Root layout: html + body)
├── (app)/
│   ├── layout.js                (App layout: Shell wrapper)
│   ├── dashboard/page.js        (482 lines — option chain + watchlist)
│   ├── market/page.js           (58 lines — STUB: redirect card)
│   ├── orders/page.js           (637 lines — paper orders)
│   ├── positions/page.js        (1200+ lines — paper positions)
│   ├── strategies/page.js       (62 lines — STUB: redirect card)
│   ├── portfolio/page.js        (38 lines — STUB: "coming soon")
│   ├── activity/page.js         (36 lines — STUB: "coming soon")
│   ├── brokers/page.js          (42 lines — STUB: "coming soon")
│   ├── settings/page.js         (38 lines — STUB: "coming soon")
│   └── paper/
│       ├── page.js              (3621 lines — MONOLITH)
│       ├── AnalyticsPanel.js
│       ├── BrokerConnectionPanel.js
│       ├── BulkExit.js
│       ├── CapitalPanel.js
│       ├── GreekAnalyticsPanel.js
│       ├── IVAnalyticsPanel.js
│       ├── PortfolioAnalyticsPanel.js
│       ├── ScenarioPanel.js
│       └── TradeDetailModal.js
└── (public)/                    (Phase 1 — public website, completed)
```

### 2.2 Shared Components

| Component | File | Purpose |
|---|---|---|
| `Shell` | `components/Shell.js` | App chrome: TopBar + Sidebar + main area |
| `TopBar` | `Shell.js` | Fixed top bar: title, execution mode, market status |
| `Sidebar` | `Shell.js` | Fixed left nav: 9 items with icons |
| `TopNav` | `lib/ui.js` | Legacy tab bar (Dashboard/Paper Trading) |
| `SymbolTabs` | `lib/ui.js` | Symbol selector (8 indices) |
| `Stat` | `lib/ui.js` | Small label + value display |
| `SessionExpired` | `lib/ui.js` | Session expiry notice |
| `Centered` | `lib/ui.js` | Full-viewport centered content |

### 2.3 API Layer

- **HTTP client**: Axios with base URL from `NEXT_PUBLIC_API_URL`
- **Auth**: Session ID from OAuth callback, stored in localStorage, sent as `X-Session-Id` header
- **WebSocket**: Option chain live feed, falls back to HTTP polling
- **33+ API endpoints** covering: auth, chains, paper trading, portfolio, analytics, capital, broker, templates, resolution, execution

### 2.4 Authentication

- Upstox OAuth flow → callback URL with `#session_id=...`
- Session ID captured from URL fragment, stored in localStorage
- Sent as `X-Session-Id` header on every request (workaround for third-party cookie blocking)
- Session expiry detected via 401 responses

---

## 3. Route Inventory

| Route | Status | Lines | Components | API Calls |
|---|---|---|---|---|
| `/dashboard` | **FUNCTIONAL** | ~482 | Option Chain, Watchlist, Alerts | `getStatus`, `getExpiries`, `useChainFeed` |
| `/market` | **STUB** | ~58 | Redirect card to /dashboard | None |
| `/orders` | **FUNCTIONAL** | ~637 | Order table, Tabs, Filters, Details | `getStatus`, `getPaperOrdersFiltered` |
| `/positions` | **FUNCTIONAL** | ~1200+ | Position table, Tabs, Filters, Details, Exit | `getStatus`, `getPaperPositionsFiltered`, `previewExitIntent`, `confirmExitIntent`, `getPositionsValuation` |
| `/strategies` | **STUB** | ~62 | Redirect card to /paper | None |
| `/portfolio` | **STUB** | ~38 | "Coming soon" | None |
| `/activity` | **STUB** | ~36 | "Coming soon" | None |
| `/brokers` | **STUB** | ~42 | "Coming soon" | None |
| `/settings` | **STUB** | ~38 | "Coming soon" | None |
| `/paper` | **MONOLITH** | ~3621 | Strategy Builder, Paper Trading, Analytics, Journal, Capital, Broker, Scenario, Greeks, IV, Bulk Exit, Templates | 20+ endpoints |

---

## 4. Page-by-Page Audit

### 4.1 Dashboard (`/dashboard`)

**Purpose**: Display the live option chain with watchlist and price alerts.

**Layout**: Two-column on desktop (chain + watchlist sidebar), stacked on mobile.

**Components**: SymbolTabs, expiry dropdown, compact toggle, option chain table, watchlist panel, alert form, spot marker.

**Data displayed**:
- Spot price, PCR (OI), Max Pain, Call OI, Put OI
- Full option chain: OI, Chg OI, Volume, IV, Vega, Theta, Gamma, Delta, LTP (both sides)
- Watchlist items with live LTP
- Price alerts (above/below)

**Interactions**:
- Switch symbol (8 indices)
- Switch expiry
- Toggle compact mode
- Star/unstar strikes (watchlist)
- Set/remove price alerts
- Browser notifications for alerts

**Responsive**: Chain scrolls horizontally on mobile; compact mode auto-enabled.

**Loading/Empty/Error**: Centered loading text, error banner, session expired screen.

**API dependencies**: `getStatus`, `getExpiries`, `useChainFeed` (WebSocket + HTTP polling).

**Auth requirements**: Full auth required (Upstox session).

#### Issues Found

| # | Category | Severity | Issue |
|---|---|---|---|
| D-1 | **UX** | P0 | Dashboard shows raw data with no market intelligence. No interpretation of PCR, OI, IV, or positioning. A trader sees numbers but gets no guidance on what they mean. |
| D-2 | **Typography** | P1 | Table headers at `fontSize: 10.5`, `color: C.faint` — same readability issue as pre-patch public site. |
| D-3 | **Typography** | P1 | Chain cell values at `fontSize: 12.5` — small for a data-dense trading interface. |
| D-4 | **UX** | P1 | No summary/dashboard cards — the trader must mentally aggregate PCR, Max Pain, OI, and volatility to form a view. |
| D-5 | **UX** | P1 | Watchlist/alerts panel is narrow on desktop and completely hidden on mobile (stacked below). |
| D-6 | **UX** | P2 | No directional bias indicator — no way to quickly see bullish/bearish/neutral. |
| D-7 | **UX** | P2 | No recent change summary — "what changed since last session?" is not visible. |
| D-8 | **UX** | P2 | Alert form is inline and cramped — easy to misclick on mobile. |
| D-9 | **Architecture** | P2 | Dashboard title says "Option Chain" but the sidebar says "Dashboard" — naming inconsistency. |
| D-10 | **Mobile** | P2 | Option chain with 21 columns (full mode) is unreadable on mobile even with horizontal scroll. |

**Things that should NOT be changed**: Live chain data, WebSocket/polling feed, watchlist persistence, alert evaluation logic, symbol selection, expiry selection.

**Recommended improvements**:
1. Add market intelligence summary cards (PCR interpretation, OI shift, IV level, directional bias)
2. Apply the same typography/contrast fixes from Phase 1
3. Add a "what changed" summary section
4. Improve mobile option chain (focus on key columns)
5. Consider a risk/alert summary at the top

**Priority**: P1 — functional but needs significant UX improvement

---

### 4.2 Market (`/market`)

**Purpose**: Intended as a market overview page. Currently a single redirect card to `/dashboard`.

**Current state**: **STUB** — 58 lines, just a card linking to Dashboard.

**Issues**:
- M-1 (P1): No market overview, no indices summary, no market breadth
- M-2 (P1): Redundant with Dashboard sidebar link
- M-3 (P2): Could serve as the proper "Market Intelligence" page from the public website workflow

**Recommended**: Transform into a genuine market overview with index summary cards, market breadth, and a gateway to deeper analysis.

**Priority**: P1 — should either become real or be removed from navigation

---

### 4.3 Orders (`/orders`)

**Purpose**: Display paper order history with filtering and detailed view.

**Layout**: Full-width table with expandable rows.

**Components**: Status tabs (All/Open/Executed/Rejected/Cancelled), filter dropdowns (symbol/side/type/kind), order table, expandable detail sections.

**Data displayed**:
- Order status, side (BUY/SELL), symbol, expiry, strike, type (CE/PE), quantity, fill price, timestamp
- Expanded: Order ID, client order ID, execution mode, timestamps, instrument details, request details, execution details, attribution, broker info, rejection reason

**Interactions**:
- Tab filtering
- Symbol/side/type/kind filtering
- Row expansion for full details

**API dependencies**: `getStatus`, `getPaperOrdersFiltered`

#### Issues Found

| # | Category | Severity | Issue |
|---|---|---|---|
| O-1 | **UX** | P1 | Table headers at `fontSize: 10`, `color: C.faint` — unreadable |
| O-2 | **UX** | P1 | Detail section labels at `fontSize: 9`, `color: C.faint` — too small for important metadata |
| O-3 | **UX** | P2 | No order entry capability — orders only come from paper execution in /paper |
| O-4 | **UX** | P2 | No real-time updates — must manually refresh |
| O-5 | **UX** | P2 | No connection to strategy execution — orders lack context of which strategy generated them |

**Things that should NOT be changed**: Order status badges, expandable detail structure, filtering logic, auth flow.

**Priority**: P1 — functional but needs typography fixes and real-time updates

---

### 4.4 Positions (`/positions`)

**Purpose**: Display open and closed paper positions with exit capability.

**Layout**: Full-width with tabs, filters, and expandable position details.

**Components**: Position tabs (Open/Closed/All), filter dropdowns, position table, exit functionality.

**Data displayed**:
- Side (LONG/SHORT), status (OPEN/CLOSED), symbol, expiry, strike, type (CE/PE), quantity, entry premium, current LTP, unrealized P&L, realized P&L
- Expanded: Position ID, execution mode, strategy attribution, entry/exit orders, valuation

**Interactions**:
- Tab filtering
- Symbol/type/strategy filtering
- Position exit (single)
- Bulk exit (per-strategy, all)
- Exit preview and confirmation

**API dependencies**: `getStatus`, `getPaperPositionsFiltered`, `previewExitIntent`, `confirmExitIntent`, `getPositionsValuation`

#### Issues Found

| # | Category | Severity | Issue |
|---|---|---|---|
| P-1 | **UX** | P1 | No position-level Greeks — trader cannot see risk per position |
| P-2 | **UX** | P1 | No margin/capital context per position |
| P-3 | **UX** | P2 | Exit flow requires multiple clicks — could be streamlined |
| P-4 | **UX** | P2 | No real-time P&L updates |
| P-5 | **Typography** | P1 | Same faint text issues as other pages |

**Things that should NOT be changed**: Exit logic, position tracking, server-authoritative state, bulk exit operations.

**Priority**: P1 — needs Greeks per position and typography fixes

---

### 4.5 Strategies (`/strategies`)

**Purpose**: Intended as a strategy management page. Currently a single redirect card to `/paper`.

**Current state**: **STUB** — 62 lines, just a card linking to Strategy Builder.

**Issues**:
- S-1 (P1): All strategy functionality is buried in the /paper monolith
- S-2 (P1): No strategy list/history view
- S-3 (P2): No strategy comparison capability
- S-4 (P2): No strategy performance tracking independent of paper execution

**Recommended**: Extract strategy-related functionality from /paper into this dedicated page.

**Priority**: P1 — critical for workflow separation

---

### 4.6 Portfolio (`/portfolio`)

**Purpose**: Capital allocation, risk controls, and performance analytics.

**Current state**: **STUB** — "Portfolio module coming soon." Redirects to Strategy Builder's Portfolio tab.

**Issues**:
- PF-1 (P1): All portfolio analytics exist in PortfolioAnalyticsPanel.js inside /paper
- PF-2 (P1): Capital, allocation, risk, equity curve — all exist but are buried
- PF-3 (P2): No standalone portfolio view

**Recommended**: Extract PortfolioAnalyticsPanel and CapitalPanel into this page.

**Priority**: P1 — functionality exists, just needs extraction

---

### 4.7 Activity (`/activity`)

**Purpose**: Orders, fills, position events, strategy events, timestamps, filtering, audit trail.

**Current state**: **STUB** — "Activity feed coming soon."

**Issues**:
- A-1 (P2): No unified activity/timeline view
- A-2 (P2): Order history exists in /orders but not as a unified feed
- A-3 (P3): Trade journal exists in /paper's analytics panel

**Recommended**: Build a unified activity feed combining orders, executions, position events, and strategy events.

**Priority**: P2 — useful but lower priority than fixing existing pages

---

### 4.8 Brokers (`/brokers`)

**Purpose**: Broker account management, connection, capabilities, and funds.

**Current state**: **STUB** — "Broker management coming soon." Broker diagnostics exist in BrokerConnectionPanel.js inside /paper.

**Issues**:
- B-1 (P1): Broker connection panel exists in /paper but is not standalone
- B-2 (P1): No multi-broker readiness
- B-3 (P2): Broker security architecture needs documentation
- B-4 (P2): Users should never paste secrets into the frontend — verify this is enforced

**Security note**: The current architecture correctly keeps broker client secrets server-side. The OAuth flow redirects to the backend which handles token exchange. The frontend only receives a session ID. This is the correct pattern.

**Recommended**: Extract BrokerConnectionPanel into this page. Add broker documentation.

**Priority**: P1 — security-relevant, functionality exists

---

### 4.9 Settings (`/settings`)

**Purpose**: Account preferences, trading preferences, display settings, risk settings, notification settings.

**Current state**: **STUB** — "Settings module coming soon."

**Issues**:
- ST-1 (P2): No settings page exists
- ST-2 (P2): Portfolio reset is available in /paper but not in a dedicated settings page
- ST-3 (P3): No notification settings (alerts exist in dashboard but are localStorage-only)
- ST-4 (P3): No risk limit configuration

**Recommended**: Build a settings page with portfolio reset, notification preferences, and display options.

**Priority**: P2 — lower priority

---

### 4.10 Paper Trading (`/paper`)

**Purpose**: The strategy builder, paper execution, analytics, journal, capital, broker diagnostics — the ENTIRE trading workflow in one page.

**Current state**: **MONOLITH** — 3,621 lines in page.js with 9 sub-components.

**Sub-components**:
| Component | Purpose | Lines (approx) |
|---|---|---|
| `page.js` | Strategy builder, legs, execution, positions, journal, settings | ~3621 |
| `ScenarioPanel.js` | Scenario analysis (spot/IV/time/rate changes) | ~300 |
| `GreekAnalyticsPanel.js` | Live vs modelled Greeks | ~200 |
| `IVAnalyticsPanel.js` | IV analysis across strikes/expiries | ~200 |
| `AnalyticsPanel.js` | Trade analytics and journal | ~400 |
| `PortfolioAnalyticsPanel.js` | Portfolio analytics, equity curve, allocation, risk | ~700 |
| `CapitalPanel.js` | Capital summary, broker margin, estimated capital | ~250 |
| `BrokerConnectionPanel.js` | Broker connection diagnostics | ~300 |
| `BulkExit.js` | Bulk exit modal and result banner | ~200 |
| `TradeDetailModal.js` | Individual trade detail view | ~150 |

**The paper page currently does ALL of the following**:
1. Strategy template selection (42 templates)
2. Strategy builder (add/edit/remove legs)
3. Strategy adjustment tools (shift, width, hedge)
4. Payoff chart visualization
5. Scenario analysis
6. Greek analytics
7. IV analytics
8. Strategy execution (V1 and V2)
9. Paper position management
10. Position exit (single and bulk)
11. Portfolio analytics
12. Equity curve
13. Capital summary
14. Broker connection diagnostics
15. Trade journal
16. Strategy performance
17. Strategy templates (CRUD)
18. Draft portfolios
19. Market-hours execution gate
20. Market status monitoring

#### Issues Found

| # | Category | Severity | Issue |
|---|---|---|---|
| PT-1 | **Architecture** | P0 | Monolith: 3,621 lines in a single page component is unmaintainable |
| PT-2 | **UX** | P0 | Too many responsibilities — strategy building, execution, analytics, and portfolio management are all on one page |
| PT-3 | **UX** | P1 | Navigation within the page uses tabs/panels that are hard to discover |
| PT-4 | **UX** | P1 | No clear separation between "build a strategy" and "manage your portfolio" |
| PT-5 | **Typography** | P1 | Same faint text issues throughout all sub-panels |
| PT-6 | **UX** | P2 | Strategy builder and positions are on the same page — confusing for users who just want to check their positions |
| PT-7 | **UX** | P2 | 9+ panels/tabs within one page — cognitive overload |

**Things that should NOT be changed**: All backend logic, strategy calculation, paper execution, portfolio analytics, capital calculations, broker diagnostics, market-hours gate, template CRUD.

**Recommended**: Break into dedicated pages:
- `/paper` → Strategy builder + execution only
- `/positions` → Position management (already exists, needs enhancement)
- `/portfolio` → Portfolio analytics + capital
- `/brokers` → Broker diagnostics
- `/strategies` → Strategy templates and history

**Priority**: P0 — the monolith is the #1 architectural problem

---

## 5. Cross-Page UX Audit

### 5.1 Navigation

**Current sidebar items** (9):
1. Dashboard 📊
2. Market 📈
3. Orders 📋
4. Positions 📐
5. Strategies ⚡
6. Portfolio 💼
7. Activity 🕐
8. Brokers 🔗
9. Settings ⚙️

**Problem**: The sidebar promises 9 distinct areas but only 3-4 actually work. This creates confusion and erodes trust.

**Recommended sidebar** (reflecting actual workflow):
1. **Dashboard** — market overview + chain (functional)
2. **Strategy Builder** — build and execute strategies (extracted from /paper)
3. **Positions** — open/closed positions (functional, needs enhancement)
4. **Portfolio** — analytics, capital, performance (extracted from /paper)
5. **Orders** — order history (functional)
6. **Brokers** — connection and diagnostics (extracted from /paper)
7. **Settings** — preferences (to be built)

The "Market", "Activity", and "Strategies" routes should be reconsidered:
- "Market" could merge into Dashboard or become a genuine market overview
- "Activity" could merge into Orders or become a timeline view
- "Strategies" could become the template management page

### 5.2 Design System

**Comparison with Phase 1 public website**:

| Element | Public Website | App Pages | Gap |
|---|---|---|---|
| **Background** | `#0B0E14` | `#0B0E14` | ✅ Consistent |
| **Surface** | `#12161F` | `#12161F` | ✅ Consistent |
| **Border** | `#242B3A` | `#242B3A` | ✅ Consistent |
| **Gold** | `#C9A15A` | `#C9A15A` | ✅ Consistent |
| **Text** | `#E7E9EE` | `#E7E9EE` | ✅ Consistent |
| **Muted** | `#949CB0` (post-patch) | `#949CB0` | ✅ Consistent |
| **Faint** | `#7B8398` (post-patch) | `#7B8398` | ✅ Consistent |
| **Font sizes** | Bumped (11px+ minimum) | Old sizes (9-10px labels) | ❌ Inconsistent |
| **Cards** | Rounded, padded, hover effects | Inline styles, no hover | ❌ Different feel |
| **Buttons** | `od-btn-gold`, `od-btn-ghost` | Custom inline buttons | ❌ Different feel |
| **Tables** | N/A (no data tables in public) | Dense data tables | N/A |
| **Empty states** | N/A | Emoji + text | ⚠️ Works but inconsistent |
| **Loading states** | N/A | Text "Loading..." | ⚠️ Basic |

**Key gaps**:
1. App pages use the old typography sizes (pre-patch)
2. No shared button styles between public and app
3. No shared card styles
4. Inconsistent empty/loading state design

### 5.3 Information Hierarchy

**Proposed hierarchy** for the App:

| Level | Content | Color | Size |
|---|---|---|---|
| **PRIMARY** | Key values (P&L, spot, position size) | `C.text` | 14-16px bold |
| **SECONDARY** | Supporting context (labels, descriptions) | `C.muted` | 12-13px |
| **TERTIARY** | Metadata (timestamps, IDs, notes) | `C.faint` | 10-11px |
| **ACCENT** | Important highlights (alerts, actions) | `C.gold` | varies |
| **SEMANTIC** | Profit/loss, buy/sell | `C.green`/`C.red` | varies |

### 5.4 Trader Workflow

**Intended workflow** (from the product principle):

```
Market Observation
→ Market Intelligence (interpret data)
→ Options Positioning (understand forces)
→ Strategy Analysis (build and test)
→ Paper/Live Execution (trade)
→ Positions (manage)
→ Portfolio/Risk (monitor)
→ Performance Review (learn)
```

**Current workflow support**:

| Step | Where it happens | Status |
|---|---|---|
| Market Observation | `/dashboard` (raw chain) | ⚠️ Functional but no interpretation |
| Market Intelligence | `/market` (stub) | ❌ Not implemented |
| Options Positioning | `/dashboard` (raw PCR/Max Pain) | ⚠️ Data present, no interpretation |
| Strategy Analysis | `/paper` (builder + payoff) | ✅ Functional |
| Paper/Live Execution | `/paper` (execution) | ✅ Functional |
| Positions | `/positions` + `/paper` | ⚠️ Split across two pages |
| Portfolio/Risk | `/paper` (analytics panel) | ⚠️ Buried in monolith |
| Performance Review | `/paper` (journal + stats) | ⚠️ Buried in monolith |

**The current architecture partially supports the workflow** but:
1. Market Intelligence is completely missing
2. Strategy → Positions → Portfolio transitions are unclear
3. Everything is crammed into /paper

---

## 6. Design-System Audit

### 6.1 Colors
All app pages use the same `C` tokens from `lib/ui.js`. The post-Phase-1 tokens are already correct. No color changes needed for tokens themselves.

### 6.2 Typography — MAJOR ISSUES

| Element | Current | Should Be |
|---|---|---|
| Table headers | 9.5-10.5px, `C.faint` | 11px+, `C.faint` (with new contrast) |
| Detail labels | 9px, `C.faint` | 10-11px minimum |
| Detail values | 11.5px | 12-13px |
| Section titles | 10-11px, `C.muted` | 12-13px, `C.muted` |
| Card labels | 8.5-9px, `C.faint` | 10-11px minimum |
| Row text | 12-12.5px | 13px minimum |
| Filter controls | 10-11px | 12-13px |
| Status badges | 10px | 10-11px (acceptable for badges) |

The App pages have the exact same typography problems that the public website had before the Phase 1 patch.

### 6.3 Spacing
- Sidebar: 200px wide, adequate
- Main content: 16px padding (could be 20px for consistency with public)
- Tables: 6-8px cell padding — tight but acceptable for data density
- Cards: 14px padding — acceptable

### 6.4 Responsive Behavior
- Sidebar collapses to hamburger at 900px (vs 768px for public)
- Tables overflow horizontally on mobile — acceptable for data-dense tables
- Paper page uses fluid type scale (`clamp()`) — good

### 6.5 Consistency Issues
- TopBar height: 44px (no equivalent in public site)
- Sidebar background: `C.surface` (matches public cards)
- Content area: no max-width constraint — content stretches on wide screens
- No consistent card/panel pattern — some use `{ background: C.surface, border: 1px solid ${C.border}, borderRadius: 10 }`, others use different patterns

---

## 7. Information Architecture Audit

### 7.1 Current IA Issues

1. **Sidebar overpromises**: 9 items, 3-4 functional
2. **Paper page is the kitchen sink**: Everything lives here
3. **Dashboard title mismatch**: Sidebar says "Dashboard", page title says "Option Chain"
4. **No breadcrumb or page hierarchy**: Users can't tell where they are in the workflow
5. **No workflow progression indicator**: The trader workflow is invisible

### 7.2 Recommended IA

```
1. Dashboard (Market overview + chain + intelligence)
2. Strategy Builder (Build + analyze + execute)
3. Positions (Open + closed + exit)
4. Portfolio (Analytics + capital + performance)
5. Orders (History + details)
6. Brokers (Connection + diagnostics)
7. Settings (Preferences + risk limits)
```

This reduces from 9 to 7 items, all functional, reflecting the actual workflow.

---

## 8. Trader Workflow Audit

### 8.1 Workflow Gap Analysis

| Workflow Step | Current Support | Gap |
|---|---|---|
| **Observe** market | Raw option chain | No summary cards, no interpretation |
| **Analyze** positioning | Raw PCR + Max Pain numbers | No directional reading, no OI shift analysis |
| **Understand** volatility | Raw IV in chain | No IV context, no skew visualization |
| **Build** strategy | Full builder with templates | ✅ Working well |
| **Test** strategy | Payoff + scenario + Greeks | ✅ Working well |
| **Execute** | Paper execution with market gate | ✅ Working well |
| **Manage** positions | Split between /positions and /paper | Needs consolidation |
| **Monitor** portfolio | Buried in /paper analytics panel | Needs extraction |
| **Review** performance | Buried in /paper journal | Needs extraction |

### 8.2 Critical Workflow Gaps

1. **No Market Intelligence page** — the public website promises this but the app doesn't deliver
2. **No risk dashboard** — a trader needs to see their total risk at a glance
3. **No "what should I pay attention to?" view** — the dashboard shows data but not insights

---

## 9. Responsive/Mobile Audit

### 9.1 Current Mobile Behavior

| Page | Mobile Behavior | Issue |
|---|---|---|
| Dashboard | Chain scrolls horizontally, watchlist stacks below | ⚠️ Chain is very wide |
| Orders | Table scrolls horizontally | ⚠️ 9 columns, cramped |
| Positions | Table scrolls horizontally | ⚠️ Similar to orders |
| Paper | Uses fluid type scale | ✅ Better than others |

### 9.2 Mobile Issues

1. **Option chain on mobile**: 21 columns in full mode, 9 in compact — both require horizontal scroll
2. **Tables on mobile**: Always need horizontal scroll — could benefit from card-based layout
3. **Sidebar on mobile**: Hamburger → overlay works well
4. **Paper page on mobile**: Very complex, many panels — needs careful mobile-first redesign
5. **No bottom navigation**: Mobile users might benefit from a bottom tab bar

---

## 10. Technical Dependency Map

### 10.1 Frontend Dependencies

| Package | Usage | Version |
|---|---|---|
| Next.js | Framework | 14.2.35 |
| React | UI | 18.3.1 |
| Axios | HTTP client | 1.19.0 |
| Recharts | Charts | 2.12.7 |
| Vitest | Testing | 4.1.10 |

### 10.2 Backend API Endpoints Used

| Endpoint | Used By | Purpose |
|---|---|---|
| `/auth/status` | Dashboard, Orders, Positions, Paper | Login check |
| `/chains/{symbol}/expiries` | Dashboard, Paper | Expiry list |
| `/chains/{symbol}` | Dashboard, Paper | Option chain data |
| `/chains/ws/{symbol}` | Dashboard | WebSocket feed |
| `/paper/executions` | Paper | Execute strategy |
| `/paper/positions` | Positions, Paper | List positions |
| `/paper/positions/{id}/exit` | Positions, Paper | Exit position |
| `/paper/positions/exit-all` | Paper | Bulk exit |
| `/paper/orders` | Orders | List orders |
| `/paper/portfolio` | Paper | Portfolio summary |
| `/paper/analytics` | Paper | Analytics + journal |
| `/paper/capital` | Paper | Capital summary |
| `/paper/journal` | Paper | Trade journal |
| `/paper/market-status` | Paper | Market hours |
| `/paper/broker/profile` | Paper | Broker diagnostics |
| `/paper/templates/*` | Paper | Template CRUD |
| `/paper/resolve` | Paper | Template resolution |
| `/paper/exit-intent/*` | Paper, Positions | Exit preview/confirm |

### 10.3 State Management

- **No global state manager** — all state is local to page components via `useState`/`useEffect`
- **localStorage used for**: session ID, watchlist, alerts, drafts, equity history
- **Server-authoritative**: paper positions, orders, portfolio, analytics, capital, journal
- **Client-side only**: watchlist, alerts, drafts, equity history, builder state

---

## 11. Security Considerations

### 11.1 Current Security Posture

| Area | Status | Notes |
|---|---|---|
| Broker secrets | ✅ Backend-only | Client secrets never reach the frontend |
| OAuth flow | ✅ Server-handled | Redirect → backend handles token exchange |
| Session management | ✅ localStorage + header | Session ID sent as X-Session-Id |
| API authentication | ✅ Required | All 33+ endpoints require auth |
| LIVE execution | ✅ Disabled | No real broker orders placed |
| User input validation | ⚠️ Client-side only | Backend re-validates on execution |

### 11.2 Security Recommendations

1. Ensure the strategy validation logic in `strategyValidation.js` is also enforced server-side
2. Verify that the market-hours gate cannot be bypassed
3. Ensure that broker tokens are never logged or exposed in error messages
4. Add rate limiting considerations for the paper execution endpoint

---

## 12. Free-Data Constraint Considerations

### 12.1 Current Data Sources

| Data | Source | Cost | Constraint |
|---|---|---|---|
| Option chain | Upstox (via user's broker) | Free with account | User-specific |
| Market data | Upstox real-time | Free with account | During market hours |
| Greeks | Computed client-side | Free | Black-Scholes model |
| Market calendar | NSE calendar logic | Free | Hardcoded rules |
| Historical data | Not currently used | N/A | — |

### 12.2 Free-Data Recommendations

1. **Do not introduce paid data providers** — the current Upstox integration is free for authenticated users
2. **Historical data**: Consider using free sources like NSE archives or Yahoo Finance for historical analysis
3. **Market news/sentiment**: Avoid paid news feeds — use OI/IV patterns as the primary intelligence source
4. **GEX calculation**: This is purely mathematical (computed from chain data) — no external data needed

---

## 13. Existing Strengths

1. **Server-authoritative paper trading** — correct architecture, backend owns all financial state
2. **Strategy calculation engine** — comprehensive, well-tested (946 tests)
3. **Market-hours execution gate** — proper safety mechanism
4. **Multi-expiry chain support** — calendar/diagonal strategies work end-to-end
5. **Broker connection diagnostics** — detailed, read-only, security-conscious
6. **Template system** — full CRUD with dynamic resolution
7. **Capital/margin foundation** — analytical + broker-reported, well-documented
8. **Payoff visualization** — interactive, accurate
9. **Scenario analysis** — Black-Scholes based, flexible inputs
10. **Exit preview/confirmation** — TOCTOU protection, idempotent execution
11. **946 passing tests** — solid test coverage across calculations and UI

---

## 14. Problems / Gaps

### P0 — Critical

1. **`/paper` monolith** (3,621 lines) — unmaintainable, confusing UX
2. **Dashboard lacks market intelligence** — shows raw data without interpretation

### P1 — Should Fix

3. **5 stub pages** — Market, Strategies, Portfolio, Activity, Brokers, Settings are not implemented
4. **Typography/readability** — same issues as pre-patch public site (9-10px faint text)
5. **No position-level Greeks** — trader can't assess per-position risk
6. **Navigation overpromises** — 9 sidebar items, 3-4 functional
7. **No real-time updates** on Orders/Positions pages
8. **No unified risk view** — risk information scattered across multiple panels

### P2 — Should Improve

9. **No design system consistency** with public website (buttons, cards, empty states)
10. **No mobile-optimized layouts** for data-dense pages
11. **No "what changed" summary** — no delta between sessions
12. **No directional bias indicator** — no quick read on market direction
13. **Dashboard naming inconsistency** — "Dashboard" vs "Option Chain"
14. **No breadcrumb/page hierarchy** — users can't orient themselves

### P3 — Future

15. **No multi-broker support** — currently Upstox only
16. **No trade annotations UI** (API exists but no visible UI)
17. **No strategy comparison** capability
18. **No performance benchmarking**

---

## 15. Recommended Priorities

### Phase 2.1 — Foundation (Highest Impact)

1. **Apply typography/contrast patch to App pages** — same approach as Phase 1 public site
2. **Extract PortfolioAnalyticsPanel + CapitalPanel from /paper → /portfolio**
3. **Extract BrokerConnectionPanel from /paper → /brokers**
4. **Rename /paper to /strategies or /strategy-builder** and scope it to strategy building + execution only
5. **Add position-level Greeks to /positions**

### Phase 2.2 — Market Intelligence

6. **Build /market as a genuine market overview** with index summary, market breadth
7. **Add market intelligence cards to /dashboard** — PCR interpretation, OI shift, IV context
8. **Add directional bias indicator** — quick visual read on market lean

### Phase 2.3 — Navigation + Design

9. **Reduce sidebar to 7 functional items** matching the recommended IA
10. **Apply shared button/card/empty-state patterns** consistent with public website
11. **Add real-time updates to Orders and Positions pages**

### Phase 2.4 — Polish

12. **Build /settings page** with portfolio reset, notification preferences
13. **Build /activity page** as a unified timeline
14. **Mobile-optimized card layouts** for data-dense tables
15. **Add "what changed" session summary** to dashboard

---

## 16. Proposed Phase 2 Implementation Order

| Phase | Focus | Pages Affected | Est. Effort |
|---|---|---|---|
| 2.1a | Typography patch (App) | All 10 pages | Small |
| 2.1b | Extract Portfolio from /paper | /paper, /portfolio | Medium |
| 2.1c | Extract Broker from /paper | /paper, /brokers | Small |
| 2.1d | Scope /paper to builder+execution | /paper (rename/restructure) | Medium |
| 2.1e | Position Greeks | /positions | Small |
| 2.2a | Market overview | /market | Medium |
| 2.2b | Dashboard intelligence cards | /dashboard | Medium |
| 2.3a | Sidebar navigation redesign | Shell.js | Small |
| 2.3b | Shared button/card patterns | All pages | Medium |
| 2.4a | Settings page | /settings | Small |
| 2.4b | Mobile optimizations | All pages | Large |

---

## 17. Items Explicitly Out of Scope

- **Backend changes** — no API modifications
- **Database schema changes** — no model modifications
- **Authentication changes** — OAuth flow is working
- **Broker integration changes** — Upstox integration is stable
- **Trading logic changes** — strategy calculator, payoff, Greeks are working
- **Paper execution changes** — server-authoritative execution is working
- **GEX implementation** — planned separately per GEX_V1_0_SPEC.md
- **Live execution** — remains disabled
- **Paid data providers** — must remain free-data-first
- **New broker adapters** — multi-broker is future work

---

## 18. Open Questions / Decisions Required

1. **Should /paper be split into 3-4 pages, or should the current monolith be reorganized with tabs?** 
   - Recommendation: Split into dedicated pages (cleaner IA, easier maintenance)
   - Alternative: Keep as one page with better tab organization (faster to implement)

2. **Should the sidebar show only functional pages, or should stub pages remain visible?**
   - Recommendation: Show only functional pages, add stubs as they're built
   - Alternative: Keep stubs visible with "coming soon" badges

3. **Should /market become a market overview or merge into /dashboard?**
   - Recommendation: Make /market a genuine overview; /dashboard stays focused on the chain
   - Alternative: Merge intelligence into /dashboard and remove /market

4. **Should real-time updates be added to Orders/Positions, or is manual refresh acceptable?**
   - Recommendation: Add WebSocket/polling for positions (they change during execution)
   - Alternative: Manual refresh for orders (less critical, orders are discrete events)

5. **Should the mobile experience use card-based layouts or keep horizontal-scroll tables?**
   - Recommendation: Cards for positions (fewer items, more detail), tables for chain/orders (data density)
   - Alternative: Keep tables everywhere with better horizontal scroll UX

---

### Phase 2.0 Verdict

1. **Is the current App architecture suitable for continued development?**
   Yes. The backend, API, calculation engine, and paper trading system are solid. The frontend needs restructuring but the foundation is sound.

2. **What should be redesigned first?**
   The `/paper` monolith — extract Portfolio, Broker, and scope it to strategy building + execution only.

3. **What should remain untouched?**
   Backend, API, database, authentication, broker integration, trading logic, strategy calculator, paper execution engine, market-hours gate, and all calculation libraries.

4. **What are the P0 issues?**
   - `/paper` monolith (3,621 lines, too many responsibilities)
   - Dashboard lacks market intelligence interpretation

5. **What are the P1 issues?**
   - Typography/readability across all app pages
   - 5 stub pages need implementation
   - Navigation overpromises (9 items, 3-4 functional)
   - No position-level Greeks
   - No real-time updates on Orders/Positions

6. **What should Phase 2.1 implement?**
   - Typography patch for all app pages
   - Extract Portfolio and Broker from /paper
   - Add position Greeks
   - Scope /paper to strategy builder + execution

7. **What should NOT be implemented yet?**
   - GEX visualization (separate phase)
   - Multi-broker support
   - Live execution
   - Paid data integrations
   - Backend/API changes
   - Historical data backfill

---

## Appendix: Files Inspected

### App Pages
- `frontend/app/(app)/layout.js`
- `frontend/app/(app)/dashboard/page.js`
- `frontend/app/(app)/market/page.js`
- `frontend/app/(app)/orders/page.js`
- `frontend/app/(app)/positions/page.js`
- `frontend/app/(app)/strategies/page.js`
- `frontend/app/(app)/portfolio/page.js`
- `frontend/app/(app)/activity/page.js`
- `frontend/app/(app)/brokers/page.js`
- `frontend/app/(app)/settings/page.js`
- `frontend/app/(app)/paper/page.js`
- `frontend/app/(app)/paper/AnalyticsPanel.js`
- `frontend/app/(app)/paper/BrokerConnectionPanel.js`
- `frontend/app/(app)/paper/BulkExit.js`
- `frontend/app/(app)/paper/CapitalPanel.js`
- `frontend/app/(app)/paper/GreekAnalyticsPanel.js`
- `frontend/app/(app)/paper/IVAnalyticsPanel.js`
- `frontend/app/(app)/paper/PortfolioAnalyticsPanel.js`
- `frontend/app/(app)/paper/ScenarioPanel.js`
- `frontend/app/(app)/paper/TradeDetailModal.js`

### Shared Components
- `frontend/components/Shell.js`

### Library Files
- `frontend/lib/ui.js`
- `frontend/lib/api.js`
- `frontend/lib/session.js`
- `frontend/lib/storage.js`
- `frontend/lib/useChainFeed.js`

### Documentation
- `docs/PROJECT_STATUS.md`
- `docs/PROJECT_MASTER_BLUEPRINT.md`
- `docs/GEX_V1_0_SPEC.md`

---

_Report produced: 2026-08-22_
_Phase: 2.0 Audit Only — No code changes, no commits, no pushes, no deployments_
