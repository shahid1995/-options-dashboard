# StrikeNova Public Website V1.2 — P4 Product Page Redesign

> **Status:** AUTHORIZED — implementation handoff
> **Date:** 2026-09-11
> **Scope:** Four product pages only: `/features`, `/market-intelligence`, `/strategy-lab`, `/paper-trading`.
> **Predecessors:** P1 accepted at `17492609dfb031f2b23e6566798e4c787caba669`; P2 accepted at `9f86412345cd49c25351491d6541a7aaba9950e2`; P3 accepted at `6d901c4a8e8063daf758ecabe29b3e8f0aeac227`.

## Authority documents

Design specification:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 audit:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

P2 handoff:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p2-signal-field.md

P3 handoff:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p3-homepage.md

Current project status:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## P4 objective

Transform the four product pages from the V1.1 restrained card-oriented presentation into four distinct StrikeNova product experiences that share one visual language but have different purposes.

The four pages must NOT look like four copies of the homepage.

Use the homepage as the brand/reference layer, then specialize each page:

```text
FEATURES
→ Capability Atlas

MARKET INTELLIGENCE
→ Market State / Signal Field

STRATEGY LAB
→ Strategy Forge / workspace

PAPER TRADING
→ Rehearsal cockpit
```

## Global rules

- Keep all existing URLs unchanged.
- Use P1 design-system primitives and P2 SignalField.
- Preserve truthful capability scope.
- Numerical demo content must remain clearly demo/illustrative.
- No fabricated users, testimonials, partnerships, certifications, performance statistics, accuracy claims, guarantees or institutional claims.
- No live broker/market-data calls added for presentation.
- No backend endpoints.
- No authentication or execution coupling.
- No changes to authenticated `(app)` routes.
- No changes to trading/financial engines.
- No deployment.
- Existing homepage `/` is accepted and should not be redesigned in P4.
- `/how-it-works` and `/about` remain untouched until P5.

## Protected boundary

Do NOT modify:

- `backend/**`
- database/schema/migrations
- broker integrations
- OAuth/session behavior
- paper/live execution semantics
- trading engine
- market-data architecture
- financial calculation engines
- `frontend/app/(app)/**`
- homepage composition except shared-component bug fixes that are strictly necessary and documented
- `/how-it-works`
- `/about`

---

# P4.1 — Features / Capability Atlas

**File:**
`frontend/app/(public)/features/ClientPage.js`

## Goal

Make Features feel like an architectural map of what StrikeNova can do, rather than a list of cards.

### Required composition

1. **Hero / positioning**
   - Strong StrikeNova title.
   - Short statement about options intelligence and structured decisions.
   - Avoid generic feature-list language.

2. **Capability Atlas**
   Build an asymmetric visual composition around the major capability families:

   ```text
   MARKET INTELLIGENCE
            │
     ┌──────┼──────┐
     │      │      │
   GEX/   GREEKS  VOL
   STRUCTURE
            │
       STRATEGY LAB
            │
       PAPER TRADING
   ```

   The exact geometry can differ, but the page must feel like a connected capability system.

3. **Primary capability modules**
   - Market Intelligence
   - Strategy Lab
   - Risk / payoff analysis
   - Paper Trading

4. **Research / future area**
   - Advanced/future capabilities must be visually distinguished as research/future.
   - Do not imply unavailable features are production-ready.

5. **Navigation**
   - Each major capability should have a clear path to its dedicated page.

### Visual requirements

Use:
- asymmetric composition;
- large visual anchor;
- technical-line accents;
- Signal Field-inspired framing;
- restrained cyan/violet/gold semantics.

Avoid:
- repeating 8–12 identical cards;
- giant icon grids;
- meaningless gradients;
- fake product statistics.

### Acceptance

A visitor should understand the platform's capability architecture within one scroll without reading every word.

---

# P4.2 — Market Intelligence

**File:**
`frontend/app/(public)/market-intelligence/ClientPage.js`

## Goal

Make Market Intelligence the strongest analytical product page and the most direct home of the Signal Field concept.

### Required composition

1. **Hero**
   - `MARKET INTELLIGENCE`
   - concise value proposition.
   - Signal Field / Market State visual immediately visible.

2. **Market State centerpiece**

   Show connected dimensions:

   ```text
   PRICE
     │
   OI ───── IV
     │      │
   ΔOI ─ GREeks
     │      │
   STRUCTURE
     │
   MARKET STATE
   ```

   Use the accepted `SignalField` component.

3. **Analytical dimensions**

   Explain, visually and briefly:

   - Positioning
   - Open-interest change
   - Volatility
   - Greeks
   - Structure

4. **Workflow interpretation**

   Show:

   `Observe → Analyze → Market State`

5. **Future/research section**

   Advanced GEX or other research-direction concepts remain clearly labeled as future/research unless actually implemented.

6. **Demo truth**

   Keep illustrative-data labels prominent wherever values appear.

### Important

Do not turn the page into a live dashboard.

Do not add network data.

Do not add backend logic.

---

# P4.3 — Strategy Lab

**File:**
`frontend/app/(public)/strategy-lab/ClientPage.js`

## Goal

Transform the page into a **Strategy Forge**: a visual explanation of how a market view becomes a strategy and then becomes measurable risk.

### Required composition

```text
MARKET VIEW
     ↓
STRATEGY LEGS
     ↓
PAYOFF
     ↓
GREEKS
     ↓
SCENARIO / RISK
```

### Hero

Position Strategy Lab as the place to:

- build option structures;
- inspect payoff;
- inspect Greeks;
- understand risk before capital.

### Strategy workspace

Use the existing Iron Condor demonstration as the illustrative anchor, but make it feel like a compact workspace rather than a stack of cards.

Possible layout:

```text
┌─────────────────────┬────────────────────────┐
│ Strategy legs       │ Payoff visualization    │
│                     │                        │
│ CE / PE positions   │      /\____/\         │
│ strikes             │                        │
├─────────────────────┼────────────────────────┤
│ Greeks              │ Risk / scenarios       │
└─────────────────────┴────────────────────────┘
```

Exact implementation may differ.

### Requirements

- Keep strategy-leg semantics accurate.
- Preserve illustrative-data disclaimer.
- Make risk metrics visually important.
- Preserve readable mobile stacking.
- No new financial calculation engine.
- Reuse existing payoff/Greek concepts where they already exist.

### Acceptance

A visitor should understand:

**Build → Visualize → Measure Risk**

without needing the authenticated application.

---

# P4.4 — Paper Trading

**File:**
`frontend/app/(public)/paper-trading/ClientPage.js`

## Goal

Make the page feel like a **rehearsal cockpit**, clearly separate from real-money trading.

### Hero

Position paper trading as:

**Practice the decision before risking capital.**

Keep the educational/simulation distinction explicit.

### Rehearsal flow

```text
DECISION
   ↓
SIMULATION
   ↓
ORDERS
   ↓
POSITIONS
   ↓
P&L
   ↓
REVIEW
```

### Visual cockpit

Create a connected visual presentation for:

- simulated capital
- orders
- positions
- P&L
- review/journal concept

Do not require a live API.

Use deterministic/demo values.

### Mobile

The existing dense position-table problem must be visually improved for mobile as part of this page's redesign when changing the composition, while the comprehensive whole-site responsive hardening remains in P7.

Prefer:

- stacked position cards;
- compact metric rows;
- horizontally safe visual modules.

Avoid:

- wide fixed tables that force viewport scrolling.

### Trust / truth

Prominently state:

- no real-money execution;
- simulated/paper environment;
- illustrative values where applicable.

Do not imply broker execution.

---

# Shared P4 visual behavior

## 1. Do not clone the homepage

All four pages should use the same:

- typography;
- semantic colors;
- surfaces;
- signal primitives;
- motion language;
- CTA language;

but each page needs a unique visual centerpiece.

## 2. Signal Field reuse

Recommended:

- Market Intelligence → major SignalField usage;
- Features → compact SignalField/capability relationship;
- Strategy Lab → reuse signal/trace primitives, not necessarily full SignalField;
- Paper Trading → use signal/workflow primitives where useful.

Do not place a full SignalField on every page merely for consistency.

## 3. Cards

Cards remain available but should become supporting surfaces, not the dominant information architecture.

## 4. Visual hierarchy

Each page should have:

```text
HERO
 ↓
SIGNATURE VISUAL
 ↓
EXPLANATION
 ↓
CAPABILITY / WORKFLOW
 ↓
PROOF / DEMO
 ↓
CTA
```

The exact number of sections can vary.

---

# Branding

Replace visible legacy public product identity with **StrikeNova** on these four pages.

Do not globally change authenticated/internal technical naming.

Do not attempt to redesign the header/footer globally in P4; that belongs to P6.

---

# Accessibility

P4 pages must use the P1/P2 accessibility foundations.

Verify:

- one clear H1 per page;
- logical heading progression;
- visible focus;
- no color-only critical meaning;
- accessible visualization descriptions;
- demo labels are readable to assistive technology;
- reduced-motion behavior remains functional;
- data tables/cards remain understandable without visual effects.

Do not treat P4 as the final whole-site accessibility audit; P7 remains the comprehensive gate.

---

# Responsive requirements

Verify each redesigned page at effective:

- 1440×900
- 1280×800
- 390×844
- 360×800

No page-specific horizontal overflow should be introduced.

For Paper Trading, actively verify the redesigned content does not recreate the known dense-table problem.

Confirm actual viewport dimensions during browser testing rather than relying only on nominal CDP settings.

---

# Performance requirements

- Reuse P1/P2 primitives.
- No new heavy visualization dependency.
- No WebGL.
- No expensive animation loops.
- No new live-data fetches.
- No unnecessary client components.

---

# Testing

Update/add focused tests for each page.

### Features

- title/brand
- capability sections
- research labeling
- CTA destinations
- no unsupported claims

### Market Intelligence

- SignalField presence
- demo labeling
- analytical dimensions
- research/future labeling
- accessible text equivalent

### Strategy Lab

- strategy-leg display
- payoff/risk display
- demo labeling
- CTA destination

### Paper Trading

- rehearsal workflow
- simulation disclaimer
- responsive presentation contract
- no live execution dependency

Do not test against network/broker availability.

---

# Browser verification

Use a real browser against a local development server.

For each page verify:

- no console errors;
- visual hierarchy;
- desktop layout;
- mobile layout;
- no horizontal overflow;
- CTA navigation;
- focus visibility;
- visualization rendering;
- demo/research truth labels;
- mobile navigation remains unaffected.

Capture screenshots for internal comparison where practical.

---

# Verification gate

Before reporting P4 complete:

1. Run the full frontend test suite.
2. Run the production Next.js build.
3. Verify all seven public routes.
4. Browser-test all four redesigned pages.
5. Inspect desktop/mobile output.
6. Inspect final Git diff.
7. Confirm protected files unchanged.

Actual results must be reported.

---

# Git

Recommended commit:

`feat(public): redesign StrikeNova product pages`

Do not deploy.

Do not merge unrelated work.

---

# Required final report

## P4 RESULT

`PASS` or `BLOCKED`

## FILES CHANGED

Exact paths.

## PAGE INVENTORY

Summarize the final composition of:

- Features
- Market Intelligence
- Strategy Lab
- Paper Trading

## DESIGN-SYSTEM USAGE

Report which P1/P2 primitives were reused.

## VERIFICATION

```text
Tests:
Build:
Routes:
Browser:
Console errors:
Responsive overflow:
```

## PROTECTED SCOPE

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
Homepage redesign: NOT MODIFIED
How It Works: NOT REDESIGNED
About: NOT REDESIGNED
Deployment: NOT PERFORMED
```

## STOP

After P4 verification:

STOP.

Do not continue to P5.
Do not redesign How It Works.
Do not redesign About.
Do not perform global navigation/footer changes.
Do not deploy.
