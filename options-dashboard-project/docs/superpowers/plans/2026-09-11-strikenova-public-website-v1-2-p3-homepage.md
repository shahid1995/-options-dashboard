# StrikeNova Public Website V1.2 — P3 Homepage Flagship Redesign

> Status: AUTHORIZED — implementation handoff
> Date: 2026-09-11
> Scope: Homepage (`/`) only. Transform the public homepage into the flagship StrikeNova Signal Field experience.
> Predecessors: P1 accepted at `17492609dfb031f2b23e6566798e4c787caba669`; P2 accepted at `9f86412345cd49c25351491d6541a7aaba9950e2`.

## Authority

Design specification:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 audit:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

P2 Signal Field:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p2-signal-field.md

Current status:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## Goal

Turn `/` into the canonical public expression of StrikeNova:

**Options intelligence for structured decisions.**

The homepage should feel computational, futuristic, premium, market-native and memorable — not like a generic SaaS landing page and not like a screenshot of a trading terminal.

## Scope

### Allowed

- `frontend/app/(public)/page.js`
- public-only supporting components when required by the homepage
- focused homepage tests

### Reuse

Use the accepted P1/P2 public design system:

- `tokens.js`
- `motion.js`
- `signals.js`
- `SignalField.js`
- `VisualizationFrame.js`
- `Metric.js`
- layout/surface/button/truth primitives

Do not duplicate Signal Field primitives.

## Strict no-touch boundary

Do not modify:

- backend/FastAPI
- database/schema/migrations
- broker integrations
- OAuth/session logic
- execution/trading engine
- market-data architecture
- financial calculation engines
- authenticated `(app)` routes
- other six public page compositions
- deployment configuration

Do not add live broker/market data to the homepage.

Do not fabricate testimonials, customers, partnerships, performance statistics, certifications, prediction accuracy, guarantees or institutional claims.

## Homepage composition

### 01 — Signal Field Hero

Build a strong first viewport.

Required conceptual content:

```text
STRIKENOVA

OPTIONS INTELLIGENCE
FOR STRUCTURED DECISIONS

See the forces behind the option chain.
Understand positioning, volatility and risk.
Build. Test. Review.

[ Explore StrikeNova ]   [ Strategy Lab ]

              SIGNAL FIELD
```

Use the accepted `SignalField` as the dominant visual.

The existing MockChain may be removed/reframed if it no longer serves the new composition.

Do not preserve old UI merely for continuity.

### 02 — The market is more than price

Create a predominantly visual section showing the layers:

```text
PRICE
OI
ΔOI
VOLUME
IV
GREEKS
STRUCTURE
        ↓
    MARKET STATE
```

Use existing Signal Field primitives where useful. Keep copy concise.

### 03 — Market Intelligence

Introduce Market Intelligence as a core product capability.

Composition should visually communicate:

- positioning
- volatility
- Greeks
- market structure

CTA:
**Explore Market Intelligence**

Do not reproduce the entire Market Intelligence page.

### 04 — Strategy Lab

Show:

```text
MARKET VIEW → STRATEGY → PAYOFF → RISK
```

Use the existing strategy/payoff concepts as supporting evidence.

CTA:
**Open Strategy Lab**

Do not add new financial calculation logic.

### 05 — Risk before capital

Visually communicate:

- payoff
- max profit
- max loss
- breakevens
- Greeks
- scenario concept

The concept is educational: risk is visible before capital is committed.

All illustrative numbers must remain clearly demo/illustrative.

### 06 — Paper trading

Present paper trading as a rehearsal loop:

```text
DECISION
   ↓
SIMULATION
   ↓
POSITION
   ↓
P&L
   ↓
REVIEW
```

CTA may point to `/paper-trading`.

Do not imply real-money execution.

### 07 — Workflow rail

Implement a concise visual narrative:

```text
01 OBSERVE → 02 ANALYZE → 03 BUILD → 04 TEST → 05 PAPER TRADE → 06 REVIEW
```

Prefer a small reusable public component only if it is genuinely useful beyond the homepage. Otherwise keep it page-local.

### 08 — Final CTA

Direction:

> **Enter the StrikeNova workflow.**

Use a strong primary action and a clear secondary exploration action.

## Brand migration

Homepage must use:

**StrikeNova**

Do not present `Options Dashboard` as the product identity anywhere in the visible homepage experience.

Legacy technical names may remain in source code where unrelated to visible branding.

## Visual rules

Use P1 tokens and P2 Signal Field.

Desired:

- deep obsidian foundation
- cyan for information/live-style visual layer
- violet for intelligence
- gold for strategy/decision
- restrained green/red for semantic outcomes
- technical lines
- signal nodes
- strike rails
- data traces
- asymmetric composition
- large visual canvas
- controlled depth

Avoid:

- generic hero stock images
- generic AI imagery
- excessive neon
- crypto/gamer styling
- rainbow gradients
- excessive rounded-card grids
- heavy glassmorphism
- unnecessary parallax
- particle-field backgrounds
- fake live market state

## Motion

Use P1 motion utilities and reduced-motion support.

Motion must communicate:

- market state
- signal flow
- transformation from market observation to decision

Do not create expensive animation loops.

## Responsive

Verify at effective:

- 1440×900
- 1280×800
- 390×844
- 360×800

No horizontal overflow.

No clipped Signal Field.

No unreadable typography.

No CTA below practical touch target.

The P0 caveat about device-metrics verification remains relevant: confirm the actual effective viewport during browser verification.

## Accessibility

- One clear homepage H1.
- Correct heading hierarchy.
- Keyboard-visible focus.
- No color-only critical meaning.
- SignalField accessible text equivalent.
- Decorative visual layers hidden from assistive technology when appropriate.
- Reduced-motion support.

## Tests

Update/add homepage tests for:

- StrikeNova brand text
- H1 presence/uniqueness
- SignalField presence
- CTA destinations
- demo/illustrative labeling
- section ordering
- removal of legacy visible branding
- no random/live data dependency

Tests must not depend on network or broker availability.

## Browser verification

Use a real browser against a local development server.

Verify:

- no console errors
- no horizontal overflow
- hero hierarchy
- SignalField renders correctly
- desktop/mobile visual composition
- CTA interaction/navigation
- focus visibility
- mobile navigation is not broken by homepage changes
- reduced-motion behavior where practical

## Verification gate

Freshly run:

1. full frontend test suite
2. production Next.js build
3. all seven public routes
4. browser verification of homepage at the target viewports
5. final diff inspection

Confirm protected files are unchanged.

## P3 non-goals

Do not redesign:

- `/features`
- `/market-intelligence`
- `/strategy-lab`
- `/paper-trading`
- `/how-it-works`
- `/about`

Those belong to later phases.

Do not perform full responsive/accessibility hardening across the site; P7 remains the comprehensive hardening gate.

## Commit

Recommended:

`feat(public): redesign StrikeNova homepage with Signal Field`

Do not deploy.

## Required final report

Return exactly:

### P3 RESULT
`PASS` or `BLOCKED`

### FILES CHANGED
Exact paths.

### HOMEPAGE INVENTORY
Describe the actual implemented sections and reused primitives.

### VERIFICATION

```text
Tests:
Build:
Routes:
Browser:
Console errors:
Responsive overflow:
```

### PROTECTED SCOPE
Confirm:

```text
Backend: NONE
Database/schema/migrations: NONE
Broker: NONE
OAuth/session: NONE
Execution: NONE
Trading engine: NONE
Market-data architecture: NONE
Financial calculations: NONE
Authenticated app: NONE
Other six public pages: NOT REDESIGNED
```

### BOUNDARY
Confirm:

```text
P4 product-page redesign: NOT IMPLEMENTED
Deployment: NOT PERFORMED
```

## STOP

After completing P3 and reporting verification:

STOP.

Do not continue to P4.
Do not redesign other public pages.
Do not deploy.
