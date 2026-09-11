# StrikeNova Public Website V1.2 — P5 Story Pages

> **Status:** Authorized — implementation handoff
> **Date:** 2026-09-11
> **Scope:** `/how-it-works` and `/about` only. Turn the two story pages into brand-building experiences while preserving truthful product messaging and the strict public/core architecture boundary.
> **Predecessors:** P1 accepted at `17492609dfb031f2b23e6566798e4c787caba669`; P2 accepted at `9f86412345cd49c25351491d6541a7aaba9950e2`; P3 accepted at `6d901c4a8e8063daf758ecabe29b3e8f0aeac227`; P4 accepted after corrective patch at `c008386d0ac2d1800f675f1cb7570de7c2df67fe`.

## Authority

Design specification:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 audit:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

P4 product pages:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p4-product-pages.md

Current status:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## P5 objective

Transform the two remaining story pages from text-heavy V1.1 pages into distinctive StrikeNova brand experiences:

```text
/how-it-works
→ CANONICAL WORKFLOW / SIGNAL RAIL

/about
→ WHY STRIKENOVA / WHAT WE BELIEVE / WHAT WE ARE NOT BUILDING
```

These pages must complement the flagship homepage and product pages rather than repeating them.

## Global constraints

- Keep URLs unchanged.
- Use the accepted P1 design system and P2 Signal Field language where appropriate.
- Reuse existing public primitives; do not create duplicate systems.
- No backend/API/database changes.
- No live broker or market-data calls.
- No authenticated-app coupling.
- No fabricated users, customers, testimonials, partnerships, certifications, performance claims, accuracy claims, or guarantees.
- Demo values, if any, must be explicitly illustrative.
- Preserve keyboard focus, reduced motion, semantic headings, and accessible labels.
- Do not deploy.

---

# P5.1 — How It Works

**File:**

`frontend/app/(public)/how-it-works/ClientPage.js`

## Goal

Make this page the canonical visual explanation of the StrikeNova workflow.

It should answer:

> How does StrikeNova take a market observation and turn it into a structured decision?

## Hero

Use a concise hero such as:

**HOW IT WORKS**

**From market observation to structured decision.**

Supporting copy should explain that StrikeNova separates observation, analysis, strategy construction, testing, rehearsal and review.

Avoid repeating the full homepage hero.

## Canonical workflow

Implement a strong six-stage vertical or adaptive rail:

```text
01 OBSERVE
     ↓
02 ANALYZE
     ↓
03 BUILD
     ↓
04 TEST
     ↓
05 PAPER TRADE
     ↓
06 REVIEW
```

Each stage should have:

- number
- title
- concise description
- one representative visual cue
- semantic status/accent

## Visual approach

Prefer a continuous rail/trace over six unrelated cards.

The rail may use:

- SignalLine
- SignalNode
- DataTrace
- TechnicalDivider
- GridOverlay
- Motion primitives

A subtle signal should appear to travel through the workflow where motion is enabled.

With reduced motion, the same structure must remain fully understandable.

## Stage semantics

### Observe

Price, option chain, OI, volume, IV, Greeks.

### Analyze

Positioning, volatility, structure and market relationships.

### Build

Construct an options strategy around the market view.

### Test

Payoff, risk, Greeks and scenarios.

### Paper Trade

Simulate the decision without placing real broker orders.

### Review

Study the outcome, execution quality and journal context.

Do not claim that these steps guarantee profitability.

## CTA

Logical links to:

- `/market-intelligence`
- `/strategy-lab`
- `/paper-trading`

## Truthfulness

Do not imply that all six stages are live automated workflows if that is not the verified product behavior.

Use language such as “workflow”, “process”, “environment”, “analysis” and “simulation” accurately.

---

# P5.2 — About

**File:**

`frontend/app/(public)/about/ClientPage.js`

## Goal

Make About feel authentic and founder/product-led without inventing company history or credentials.

The page should answer:

- Why does StrikeNova exist?
- What problem is it trying to solve?
- What principles guide it?
- What is StrikeNova explicitly not trying to be?
- Where is the product heading?

## Hero

Suggested direction:

**ABOUT STRIKENOVA**

**Built to make options analysis more structured.**

Keep the message grounded in the actual product direction.

## Why StrikeNova exists

A concise narrative around the core problem:

Raw option-chain data is rich but difficult to turn into a coherent, repeatable decision process.

StrikeNova aims to connect:

```text
DATA
 ↓
INTELLIGENCE
 ↓
STRATEGY
 ↓
RISK
 ↓
REHEARSAL
 ↓
REVIEW
```

Avoid unsupported market-size or business claims.

## Product philosophy

Use a small number of strong principles, not repeated cards full of nearly identical copy.

Potential themes:

- Data first
- Risk first
- Structured analysis
- Transparency

Each principle should have concise, distinct language.

## What StrikeNova is not

Introduce a clear trust-building section:

```text
NOT A SIGNAL-SELLING SERVICE
NOT A GUARANTEED-PROFIT SYSTEM
NOT A BLACK BOX
NOT A SUBSTITUTE FOR RISK MANAGEMENT
```

Do not attack competitors.

Do not make legal/regulatory claims unless already verified.

## What we are building

Provide a concise forward-looking direction using only capabilities and research directions already documented.

Research/future items must be labeled clearly as:

- Research Direction
- Coming Later
- Future Extension

Do not invent dates or promises.

## Authenticity rule

Do not create:

- fake founder biography
- fake years of experience
- fake customer logos
- fake testimonials
- fake investor/partner references
- fake user counts
- fake certifications

Use only verified repository/project facts.

---

# P5.3 — Shared design language

Both pages should use the established StrikeNova system:

```text
obsidian foundation
cyan information
violet intelligence
gold strategy / decision
green positive
red risk
technical lines
signal nodes
asymmetric composition
restrained motion
```

Avoid excessive card grids.

Avoid generic corporate illustrations.

Avoid stock imagery.

Avoid generic AI imagery.

Avoid excessive neon/glassmorphism/parallax.

---

# P5.4 — Reuse / component boundaries

Reuse:

- `tokens.js`
- `motion.js`
- `signals.js`
- `SignalField.js` where appropriate
- `VisualizationFrame.js`
- `layout.js`
- `surfaces.js`
- `buttons.js`
- `truth.js`
- existing workflow primitives if available

Only create a new shared component when it has legitimate reuse value beyond a single page.

If a workflow rail will also be needed for future pages, create a small reusable `WorkflowRail` rather than duplicating the implementation.

Do not create duplicate SignalField, SignalNode, StrikeRail or token systems.

---

# P5.5 — Responsive

Verify actual effective viewport sizes:

- 1440×900
- 1280×800
- 390×844
- 360×800

Requirements:

- no horizontal overflow;
- readable workflow labels;
- no clipped rail or trace;
- clean mobile stacking;
- touch-safe links/buttons;
- no tiny body copy created by the redesign.

The P0 viewport-override caveat remains relevant: verify the actual effective dimensions in the browser.

---

# P5.6 — Accessibility

Verify:

- one H1 per page;
- logical heading progression;
- keyboard focus visibility;
- semantic links/buttons;
- workflow content available as text;
- decorative visuals hidden when appropriate;
- color is not the only carrier of important meaning;
- reduced-motion mode preserves the complete workflow.

P7 remains the final whole-site hardening gate.

---

# P5.7 — Tests

Add/update focused tests for both pages.

## How It Works

Verify:

- page identity;
- six workflow stages;
- correct order;
- CTA destinations;
- text equivalents;
- no legacy visible branding.

## About

Verify:

- page identity;
- Why StrikeNova section;
- philosophy principles;
- What StrikeNova is not;
- future/research labeling;
- no fabricated claims;
- no legacy visible branding.

Tests must not use network or authenticated services.

---

# P5.8 — Browser verification

Use a real browser against a local development server.

Verify both pages for:

- correct rendering;
- no console errors;
- responsive layout;
- keyboard focus;
- workflow readability;
- reduced-motion behavior where practical;
- CTA navigation;
- absence of unsupported claims.

---

# P5.9 — Regression

Verify all seven public routes:

`/`

`/features`

`/market-intelligence`

`/strategy-lab`

`/paper-trading`

`/how-it-works`

`/about`

P3 homepage and P4 product pages must remain intact.

---

# P5.10 — Strict no-touch boundary

Do not modify:

- backend/FastAPI
- database/schema/migrations
- broker integrations
- OAuth/session logic
- execution/trading engine
- market-data architecture
- financial engines
- authenticated `(app)` routes
- homepage unless a shared-component regression must be corrected
- product pages unless a shared-component regression must be corrected
- deployment configuration

Do not deploy.

---

# P5.11 — Commit

Recommended commit:

`feat(public): redesign StrikeNova story pages`

Keep the commit focused.

---

# P5.12 — Required final report

Return:

## P5 RESULT

`PASS` or `BLOCKED`

## FILES CHANGED

Exact paths.

## HOW IT WORKS INVENTORY

Actual hero, workflow rail, stage visuals, CTAs.

## ABOUT INVENTORY

Actual narrative sections, philosophy, “What StrikeNova is not”, future direction.

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
Homepage: NOT REDESIGNED
Product pages: NOT REDESIGNED
Navigation/footer: NOT REDESIGNED
Deployment: NOT PERFORMED
```

## BOUNDARY

```text
P6 navigation/footer/metadata: NOT IMPLEMENTED
P7 final hardening: NOT IMPLEMENTED
P8 final acceptance: NOT IMPLEMENTED
```

## STOP

After P5 verification:

STOP.

Do not continue to P6.
Do not redesign navigation/footer.
Do not perform final metadata migration.
Do not perform whole-site hardening.
Do not deploy.
