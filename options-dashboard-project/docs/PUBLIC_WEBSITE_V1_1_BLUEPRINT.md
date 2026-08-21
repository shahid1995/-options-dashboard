# Public Website V1.1 Blueprint

> **Status:** Specification — not yet implemented
> **Created:** 2026-08-21
> **Scope:** Public marketing pages only — no backend, no authenticated application changes

---

## Core Product Message

The public website should communicate:

> **"Turn options-market data into structured trading decisions."**

The website should NOT primarily present itself as a collection of features.

The product story is:

```
Observe → Understand → Build → Analyze Risk → Test → Review → Execute
```

The public website explains this workflow.
The authenticated application performs it.

---

## Public Website Architecture

### Public Routes (unchanged)

| Route | Purpose |
|-------|---------|
| `/` | Homepage |
| `/features` | Feature overview |
| `/market-intelligence` | Market data dimensions |
| `/strategy-lab` | Strategy construction & risk |
| `/paper-trading` | Simulated trading |
| `/how-it-works` | Workflow explanation |
| `/about` | Philosophy & principles |

### Authenticated Routes (unchanged)

| Route | Purpose |
|-------|---------|
| `/dashboard` | Main dashboard |
| `/market` | Market data |
| `/orders` | Paper orders |
| `/positions` | Open/closed positions |
| `/strategies` | Strategy management |
| `/portfolio` | Portfolio overview |
| `/activity` | Activity feed |
| `/brokers` | Broker connections |
| `/settings` | User settings |
| `/paper` | Paper trading engine |

### Route Group Architecture

```
app/
  (public)/        ← marketing pages, no Shell, PublicLayout
  (app)/           ← authenticated pages, Shell wrapper
```

This architecture is correct and must not change.

---

## Navigation

### Desktop

```
OPTIONS DASHBOARD

Product
  ├─ Features
  ├─ Market Intelligence
  ├─ Strategy Lab
  └─ Paper Trading

Learn
  ├─ How It Works
  └─ About

                                    Log in   Get Started
```

"Get Started" should be the visually dominant primary CTA.

### Mobile

Same destinations via hamburger menu.
Mobile navigation must be explicitly tested during V1.1 QA.

---

## Homepage V1.1

The current homepage is too long (5639px desktop, 8395px mobile) and duplicates content from dedicated pages.

The V1.1 homepage should be simplified to **six sections**:

1. Hero
2. The Problem
3. The Platform
4. The Workflow
5. Supported Markets
6. Final CTA

### 1. Hero

**Headline:**

> "From Market Data to Structured Decisions."

**Supporting message:**

> "Analyze options positioning, volatility, Greeks and market structure. Build strategies, understand risk, test ideas and practice execution — all in one workflow."

**Primary CTA:** Explore the Platform
**Secondary CTA:** Start Paper Trading

Keep the existing MockChain visual.
Keep the ticker animation.
Do not remove these unless a later review specifically approves it.

### 2. The Problem

**Headline:**

> "The problem isn't lack of market data. It's knowing what to do with it."

Explain that traders have access to many data points but the challenge is turning them into a coherent decision.

Conceptual flow:

```
OPTION CHAIN
     ↓
      OI
     ↓
  OI CHANGE
     ↓
   VOLUME
     ↓
     IV
     ↓
  GREEKS
     ↓
   PRICE
     ↓
 STRATEGY
     ↓
   RISK
```

The purpose is to explain why the platform exists.

### 3. The Platform

Four major capability pillars:

#### 01 — Market Intelligence

Understand positioning, volatility, Greeks and market structure instead of looking at isolated numbers.

→ Links to `/market-intelligence`

#### 02 — Strategy Lab

Build multi-leg option strategies and understand their payoff, Greeks and risk before committing capital.

→ Links to `/strategy-lab`

#### 03 — Paper Trading

Practice the complete trading workflow without risking real capital.

→ Links to `/paper-trading`

#### 04 — Analytics

Review trades, outcomes and performance to identify what is working and what needs improvement.

→ Links to `/features` (Analytics section)

Each pillar should link to its relevant dedicated page.
Do NOT reproduce the full contents of those pages on the homepage.

### 4. The Workflow

One concise workflow:

```
01 OBSERVE → 02 ANALYZE → 03 BUILD → 04 TEST → 05 REVIEW
```

Desktop: Horizontal flow with arrows
Mobile: Vertical flow with arrows

The homepage links to `/how-it-works`.
The complete six-step workflow belongs on the dedicated How It Works page.
Do not duplicate multiple competing workflows on the homepage.

### 5. Supported Markets

Concise supported-market section.

| Symbol | Underlying | Exchange |
|--------|-----------|----------|
| NIFTY | NIFTY 50 | NSE |
| BANKNIFTY | Bank Nifty | NSE |
| FINNIFTY | Financial Services Nifty | NSE |
| MIDCPNIFTY | Nifty Midcap Select | NSE |
| NIFTYNXT50 | Nifty Next 50 | NSE |
| SENSEX | BSE Sensex | BSE |
| BANKEX | BSE Bankex | BSE |
| SENSEX50 | BSE Sensex 50 | BSE |

Only display lot size information if it is reliable/current.
Improve readability of table headers (increase weight, size).

### 6. Final CTA

**Headline:**

> "Build a more structured trading workflow."

**Supporting message:**

> "Explore the platform, understand the workflow and practice your strategies before putting capital at risk."

**Primary CTA:** Get Started
**Secondary CTA:** How It Works

---

## Features Page

Organize around four capability groups.

### MARKET INTELLIGENCE

- Option Chain
- Open Interest
- OI Change
- Volume
- Implied Volatility
- Greeks
- Market Structure

### STRATEGY & RISK

- Strategy Builder
- Multi-leg positions
- Payoff analysis
- Breakeven
- Max profit/loss
- Greeks
- Scenario analysis

### TRADING

- Paper Trading
- Orders
- Positions
- Portfolio
- Broker integration
- Execution controls

### ANALYTICS

- Performance
- P&L
- Win/loss analysis
- Trade history
- Risk analysis

### Research Direction (separated visually)

Future capabilities that are NOT production features:

- Gamma Exposure
- Statistical signals
- Advanced positioning analysis
- Additional market intelligence

Use clear label: **"Research Direction"**
Do not represent research-direction features as production features.

---

## Market Intelligence Page

**Purpose:** Show how multiple market dimensions combine into a coherent market view.

**Hero:**

> "See the Market Behind the Option Chain."

**Supporting message:**

> "Combine price, positioning, volume, volatility and Greeks to build a more complete view of the options market."

### Core Dimensions

PRICE · OI · OI CHANGE · VOLUME · IV · GREEKS · VOLATILITY · MARKET STRUCTURE

### Visualization Groups

- **Positioning** — CE OI, PE OI, OI shift
- **Volatility** — IV, VIX, Vega
- **Greeks** — Delta, Gamma, Theta, Vega
- **Market Structure** — Resistance, Pivot, Support

Keep the existing demo visualizations but give them sufficient visual breathing room.
All demo numerical values must remain explicitly labeled as demo/illustrative.

---

## Strategy Lab Page

**Purpose:** Demonstrate understanding of risk before execution.

**Hero:**

> "Build the Strategy. See the Risk. Test the Outcome."

### Demo Strategy

Keep the demo Iron Condor:

```
SELL 25,500 CE    BUY 25,700 CE
SELL 25,500 PE    BUY 25,300 PE
```

### Payoff Visualization

Make the payoff visualization more prominent.

**Preferred desktop layout:**

```
┌─────────────────────┬──────────────────────┐
│                     │                      │
│  Strategy Legs      │   Payoff Chart       │
│  (table)            │   (SVG)              │
│                     │                      │
│  MAX PROFIT         │                      │
│  MAX LOSS           │                      │
│  BREAKEVEN          │                      │
│  RISK / REWARD      │                      │
│                     │                      │
└─────────────────────┴──────────────────────┘
```

Below the strategy:
- MAX PROFIT
- MAX LOSS
- BREAKEVEN
- RISK / REWARD

### Position Greeks

DELTA · GAMMA · THETA · VEGA

### Workflow Section

```
BUILD → ANALYZE → STRESS TEST → PAPER TRADE → REVIEW
```

**Primary message:** "Understand the strategy before you trade it."

**CTA:** Try Paper Trading

The payoff chart must remain readable on mobile.

---

## Paper Trading Page

**Hero:**

> "Practice the Workflow. Not Your Capital."

### Conceptual Workflow

```
REAL MARKET DATA
      ↓
YOUR STRATEGY
      ↓
PAPER EXECUTION
      ↓
POSITION MANAGEMENT
      ↓
PERFORMANCE REVIEW
```

### Demo Portfolio

Keep the demo portfolio metrics:

- SIMULATED CAPITAL: ₹5,00,000
- TODAY'S P&L: +₹4,820
- OPEN POSITIONS: 4
- WIN RATE: 68%

### Positions Table

Desktop may use a table.
Mobile should convert the position table into readable cards rather than forcing a compressed desktop table.

### Disclaimer

> "Paper trading is simulated. It does not represent actual execution or guarantee future trading results."

This disclaimer must remain on the page.

---

## How It Works Page

This becomes the **canonical workflow explanation**.

### Six Steps

| Step | Title | Description |
|------|-------|-------------|
| 01 | Observe | Price, option chain, OI, volume, IV and Greeks |
| 02 | Analyze | Positioning, volatility and market structure |
| 03 | Build | Construct a strategy around the market view |
| 04 | Test | Analyze payoff, risk, Greeks and scenarios |
| 05 | Execute | Paper trade the strategy with simulated capital |
| 06 | Review | Study the result, execution and risk |

The homepage shows only the condensed five-step workflow.
This page contains the complete six-step explanation.

---

## About Page

**Hero:**

> "Built Around a Simple Idea."

**Core philosophy:**

> "Better trading decisions don't come from having more numbers. They come from understanding what those numbers mean together."

### Principles

1. **Data First** — Every decision starts with market data.
2. **Risk First** — Understand the risk before committing capital.
3. **Structured Analysis** — Separating analysis from execution.
4. **Transparency** — No black-box claims, no hidden logic.
5. **Test Before Capital** — Paper trade before real execution.
6. **Continuous Improvement** — Learn from every trade.

Avoid generic corporate language.
Do not invent testimonials, customers, performance statistics, endorsements, security certifications, or institutional partnerships.

---

## CTA Strategy

### Global CTAs

| Label | Action |
|-------|--------|
| Get Started | Primary — links to login/signup |
| Explore the Platform | Secondary — links to `/features` |

### Contextual CTAs

| Page | Primary CTA | Secondary CTA |
|------|-------------|---------------|
| Features | Explore Market Intelligence | How It Works |
| Market Intelligence | Build a Strategy | Explore Features |
| Strategy Lab | Try Paper Trading | See How It Works |
| Paper Trading | Get Started | See How It Works |
| How It Works | Explore the Platform | Get Started |
| About | Explore the Platform | Get Started |

Avoid unnecessary repeated generic CTAs.

---

## Trust Strategy

### Do NOT

- Add fabricated testimonials
- Add fake user counts
- Add unsupported security badges
- Make guaranteed-return claims
- Claim accuracy percentages
- Claim market prediction ability

### DO

- Clear paper/live distinction
- Explicit research/future-feature labeling
- Broker-based authentication
- Risk controls
- Transparent product development
- Honest feature availability

Real testimonials can be added later when genuine users provide them.

---

## Visual Design Rules

### Preserve

- Dark professional trading aesthetic
- Gold accent (#C9A15A)
- Subtle borders (#242B3A)
- Existing card styling
- Existing section-heading pattern (SectionHeading component)
- MockChain (animated option chain)
- Ticker animation
- Restrained animations
- Existing footer structure
- PublicHeader / PublicFooter / PublicLayout components

### Do NOT

- Perform a major visual redesign
- Replace the color scheme
- Remove the gold accent
- Add excessive gradients
- Add flashy animations

V1.1 is refinement, not rebranding.

### Typography Targets

**Desktop:**

| Element | Size |
|---------|------|
| H1 | 48–64px |
| H2 | 32–42px |
| H3 | 20–24px |
| Body | 16–18px |
| Small text | ≥13px |

**Mobile:**

| Element | Size |
|---------|------|
| H1 | ~34–40px |
| H2 | ~28–32px |
| Body | minimum ~16px |

Avoid extremely faint text for important information.

---

## Accessibility

V1.1 should target **WCAG AA** where practical.

### Contrast Audit

- Body text contrast
- Secondary text contrast
- Muted text contrast
- Table headers
- Gold text on dark backgrounds
- Button text contrast
- Link contrast
- Border visibility

Important information must never rely on extremely low-contrast text.

---

## Mobile Requirements

### Test Viewports

| Viewport | Context |
|----------|---------|
| 390 × 844 | iPhone 14 Pro |
| 360 × 800 | Common Android |
| 1440 × 900 | Desktop |

### Requirements

- No horizontal overflow
- CTA buttons remain tappable (min 44px touch target)
- Hamburger navigation works and shows all links
- Tables convert to card layouts where needed
- Charts remain readable
- Cards don't become excessively compressed
- Body text remains readable (min ~16px)
- Workflow becomes vertical
- Navigation remains usable

---

## Demo Data Policy

All fictional market numbers must remain clearly labeled.

### Acceptable Labels

- "DEMO DATA · ILLUSTRATIVE VALUES ONLY"
- "ILLUSTRATIVE EXAMPLE"

### What Must Be Labeled

- Option prices
- OI values
- Greeks
- P&L figures
- Win rate
- Capital amounts
- Strategy outcomes

Never allow fictional values to appear to be live market data.

---

## Future Capability Policy

### Future Research Areas

- GEX (Gamma Exposure)
- Dealer positioning analysis
- Statistical models
- Market-maker inference
- Advanced signals
- Self-learning systems

### Labeling Convention

| Status | Label |
|--------|-------|
| Currently available | (no special label needed) |
| In development | "COMING LATER" |
| Research/exploration | "RESEARCH DIRECTION" |

These must NOT be marketed as finished capabilities until they actually exist.

---

## Strict Project Boundaries

During public website V1.1 work, do NOT modify:

- Backend (Python/FastAPI)
- Database (schema, migrations)
- Trading engine
- Paper execution engine
- Risk engine
- Broker APIs / OAuth
- WebSocket connections
- Authentication / session logic
- Order management
- Market-data architecture
- Existing test files (except import paths if route groups change)

The public website is a **presentation/marketing layer** over the application.

---

## Implementation Plan

### P1 — Content & Architecture

- [ ] Fix verified `\u2014` text-rendering issues across all public pages
- [ ] Simplify homepage from 9 sections to 6
- [ ] Remove duplicated homepage content (workflow, market intel, strategy lab, paper trading detail)
- [ ] Update copy per this blueprint
- [ ] Establish CTA hierarchy per page
- [ ] Preserve existing visual identity
- [ ] Update headline text per blueprint

### P2 — Responsive UX

- [ ] Mobile workflow (vertical with arrows)
- [ ] Strategy chart sizing (side-by-side on desktop, stacked on mobile)
- [ ] Paper trading mobile cards (replace compressed table)
- [ ] Market Intelligence spacing (more breathing room)
- [ ] Mobile navigation full test
- [ ] Verify no horizontal overflow on any page

### P3 — Visual Polish

- [ ] Typography hierarchy (H1/H2/H3 sizes per blueprint)
- [ ] Contrast improvements (WCAG AA)
- [ ] Table header readability (weight, size)
- [ ] CTA prominence and contextual messaging
- [ ] Spacing consistency
- [ ] About page card refinement
- [ ] Faint text audit

### P4 — QA

- [ ] Production build passes
- [ ] All existing tests pass
- [ ] All 7 public routes compile and render
- [ ] All 10 authenticated routes still work
- [ ] Authentication flow unchanged
- [ ] Desktop viewport (1440×900) verified
- [ ] Mobile viewport (390×844) verified
- [ ] Mobile viewport (360×800) verified
- [ ] No console errors
- [ ] No network errors
- [ ] No public API/WebSocket usage on public pages
- [ ] Demo-data labeling verified on all pages
- [ ] No backend/API/database changes
- [ ] No trading logic changes
- [ ] No regressions in authenticated application

### P5 — Visual QA

Generate:

- 7 desktop screenshots (1440×900, full-page)
- 7 mobile screenshots (390×844, full-page)

Review against this blueprint.

### P6 — Final Approval

Only after review:

- Approve
- Commit
- Manual deployment (no automatic deployment)

Do not proceed to P1 without explicit authorization.

---

## Important Implementation Rule

**THIS DOCUMENT IS SPECIFICATION ONLY.**

Do not implement P1 yet.
Do not change application files.
Do not change tests.
Do not deploy.

Implementation begins only after explicit authorization.
