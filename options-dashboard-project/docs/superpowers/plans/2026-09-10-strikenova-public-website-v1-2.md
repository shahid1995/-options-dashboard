# StrikeNova Public Website V1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the existing seven-page public marketing site from the restrained Options Dashboard V1.1 presentation into the distinctive **StrikeNova Signal Field** experience while preserving truthful product messaging, route stability, accessibility, responsive quality, and strict separation from the core platform.

**Architecture:** Keep `app/(public)` and `app/(app)` route groups unchanged. Evolve the existing `components/public` layer into a small public design system with reusable visualization primitives, Signal Field components, workflow rails, capability modules, and shared motion/tokens; do not introduce backend dependencies for public visuals.

**Tech Stack:** Next.js App Router, React, existing public components, existing CSS/style-token approach, SVG/CSS for visualizations, existing Vitest/browser verification patterns, Vercel-hosted frontend.

**Spec:** `docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md`

## Global Constraints

- **Brand:** Public product identity is `StrikeNova`; `Options Dashboard` is legacy technical naming only.
- **Visual direction:** Use the approved **StrikeNova Signal Field** concept; futuristic means computational/data-native, not crypto/gamer/neon-hype.
- **Routes:** Keep `/`, `/features`, `/market-intelligence`, `/strategy-lab`, `/paper-trading`, `/how-it-works`, `/about` unchanged.
- **Architecture boundary:** Do not modify backend, database, migrations, brokers, OAuth/session logic, execution semantics, market-data architecture, or authenticated routes.
- **Data truth:** No fabricated testimonials, users, partnerships, certifications, performance claims, accuracy claims, guaranteed returns, or unsupported prediction claims.
- **Demo data:** Numerical public-page data must be clearly labeled as illustrative/demo; never imply fictional data is live broker data.
- **Accessibility:** Preserve and extend focus-visible behavior, keyboard operation, meaningful visualization labels, reduced-motion support, and no color-only critical encoding.
- **Responsive:** Verify 1440×900, 1280×800, 390×844, and 360×800 with no horizontal overflow.
- **Motion:** Prefer CSS/SVG; reduced-motion behavior is mandatory.
- **Performance:** No unnecessary animation/data/visualization dependency; public visuals must remain lightweight.
- **Execution:** Do not deploy from this plan. Deployment remains a manual Project Control Center action.

---

## File Map

### Existing public files expected to evolve

- `frontend/app/(public)/page.js` — homepage composition and public hero/content story.
- `frontend/app/(public)/features/ClientPage.js` — Capability Atlas.
- `frontend/app/(public)/market-intelligence/ClientPage.js` — Market State/Signal Field presentation.
- `frontend/app/(public)/strategy-lab/ClientPage.js` — strategy workspace composition.
- `frontend/app/(public)/paper-trading/ClientPage.js` — rehearsal/trading-loop presentation.
- `frontend/app/(public)/how-it-works/ClientPage.js` — canonical six-step visual workflow.
- `frontend/app/(public)/about/ClientPage.js` — authentic company/mission narrative.
- `frontend/app/(public)/layout.js` — public layout metadata/integration only when necessary.
- `frontend/components/public/PublicHeader.js` — StrikeNova navigation and branding.
- `frontend/components/public/PublicFooter.js` — footer branding and link structure.
- `frontend/components/public/SectionHeading.js` — updated display hierarchy/eyebrow pattern where useful.
- `frontend/components/public/CTASection.js` — shared CTA treatment.
- `frontend/components/public/FeatureCard.js` — retained only where card semantics remain appropriate; do not force all modules through it.
- `frontend/components/public/PublicLayout.js` — public shell, unchanged architecture.
- `frontend/components/public/styles.js` — public tokens, motion, utility classes, responsive rules.

### New public primitives proposed

- `frontend/components/public/SignalField.js` — reusable signature market visualization.
- `frontend/components/public/SignalNode.js` — semantic node used by Signal Field.
- `frontend/components/public/StrikeRail.js` — strike/price rail visual.
- `frontend/components/public/WorkflowRail.js` — six-stage workflow path.
- `frontend/components/public/CapabilityModule.js` — asymmetric product capability block.
- `frontend/components/public/VisualMetric.js` — visual metric treatment for hero/product storytelling.

Exact filenames may be adjusted only when the final responsibility remains clear and documented.

---

# Phase P0 — Baseline, Inventory and Safety Fence

**Deliverable:** A documented and verified baseline for the existing public site before visual changes begin.

### Task P0.1 — Record public route/component inventory

**Files:**
- Review: `frontend/app/(public)/**`
- Review: `frontend/components/public/**`

- [ ] Enumerate the seven public routes and map each to its current client/page component.
- [ ] Identify all current shared public components and style entry points.
- [ ] Record which components are currently imported by multiple pages.
- [ ] Record the current demo-data labels and visualization components.

### Task P0.2 — Capture visual baseline

**Files:**
- Review: `options-dashboard-screenshots` repository / existing V1.1 screenshots
- Test artifacts: local screenshots only; no source changes required.

- [ ] Capture/retain desktop screenshots for all seven public routes.
- [ ] Capture/retain mobile screenshots for all seven public routes.
- [ ] Use 1440×900 and 390×844 as the primary comparison sizes.
- [ ] Record obvious baseline issues separately from redesign decisions so later visual review can distinguish regression from intentional change.

### Task P0.3 — Safety audit

- [ ] Confirm that the public pages do not import backend-only modules.
- [ ] Confirm public visuals do not require authenticated market-data calls.
- [ ] Confirm no V1.2 task changes `frontend/app/(app)/**`, `backend/**`, database/migration files, broker modules, or auth/session code.

### Gate P0

- [ ] Baseline exists.
- [ ] Route inventory is complete.
- [ ] No-touch boundary is explicit.
- [ ] Project Control Center approves P1 start.

---

# Phase P1 — StrikeNova Public Design System

**Deliverable:** A reusable visual foundation that makes later page work compositional rather than ad hoc.

### Task P1.1 — Establish brand tokens

**Files:**
- Modify: `frontend/components/public/styles.js`
- Modify: `frontend/app/layout.js` only for public-facing metadata/font loading when justified.

- [ ] Define semantic tokens for base, surface, border, muted text, live-information accent, intelligence accent, strategy/gold accent, positive, and risk.
- [ ] Keep existing gold semantics for strategy/decision emphasis.
- [ ] Define typography roles: display, body, data.
- [ ] Define spacing, radius, shadow, and layering tokens needed by public components.
- [ ] Do not alter authenticated-app theme tokens unless a shared dependency makes it unavoidable.

### Task P1.2 — Establish typography system

- [ ] Select/configure a readable display face only if the current system font is insufficient.
- [ ] Preserve reliable body rendering.
- [ ] Establish tabular/data numeral treatment.
- [ ] Verify line lengths and heading wrapping at 1440px and 390px.

### Task P1.3 — Establish motion primitives

- [ ] Add signal/data motion utilities.
- [ ] Add reduced-motion overrides.
- [ ] Keep existing fade/ticker behavior only where still useful.
- [ ] Ensure all continuous motion has a low-cost or disabled reduced-motion path.

### Task P1.4 — Add layout/visual primitives

**Files:**
- Create: `frontend/components/public/CapabilityModule.js`
- Create: `frontend/components/public/VisualMetric.js`

- [ ] Implement composition-focused modules for asymmetric capability blocks and visual metrics.
- [ ] Do not use these primitives to hide page-specific semantics.

### Verification P1

- [ ] Public tests pass.
- [ ] Build passes.
- [ ] Keyboard focus remains visible.
- [ ] Reduced-motion behavior is verified.
- [ ] No authenticated route behavior changes.

### Gate P1

- [ ] Visual tokens are stable enough for Signal Field implementation.
- [ ] Project Control Center approves P2.

---

# Phase P2 — Signal Field Foundation

**Deliverable:** StrikeNova's signature visualization, independent of live broker data.

### Task P2.1 — Build SignalNode

**Files:**
- Create: `frontend/components/public/SignalNode.js`

- [ ] Define a compact semantic API for label, value, role, position, and optional state.
- [ ] Render accessible text alongside the visual marker.
- [ ] Keep node rendering SVG/CSS based.

### Task P2.2 — Build StrikeRail

**Files:**
- Create: `frontend/components/public/StrikeRail.js`

- [ ] Render illustrative strike levels around a central spot/reference level.
- [ ] Support desktop and mobile orientation changes without horizontal overflow.
- [ ] Ensure labels remain readable.

### Task P2.3 — Build SignalField

**Files:**
- Create: `frontend/components/public/SignalField.js`

- [ ] Compose market layers: Price, OI, OI Change, IV, Greeks, Structure.
- [ ] Provide deterministic illustrative state.
- [ ] Add subtle signal motion.
- [ ] Add a text-equivalent interpretation for assistive technology.
- [ ] Add explicit demo labeling where numerical values are visible.
- [ ] Avoid a fake `LIVE` state for fictional data.

### Task P2.4 — Test Signal Field behavior

- [ ] Add focused component tests for rendering, accessibility labels, and reduced-motion mode.
- [ ] Verify no DOM/layout overflow at 390×844.
- [ ] Verify no console errors in browser runtime.

### Gate P2

- [ ] Signal Field is stable and reusable.
- [ ] Accessibility and responsive checks pass.
- [ ] Project Control Center approves P3.

---

# Phase P3 — Homepage Flagship Redesign

**Deliverable:** Homepage becomes the canonical expression of StrikeNova V1.2.

### Task P3.1 — Replace legacy hero composition

**Files:**
- Modify: `frontend/app/(public)/page.js`

- [ ] Replace the current Options Dashboard presentation with StrikeNova branding.
- [ ] Use Signal Field as the dominant hero visual.
- [ ] Use positioning such as: `OPTIONS INTELLIGENCE FOR STRUCTURED DECISIONS`.
- [ ] Keep copy short enough to preserve hero impact.
- [ ] Retain a clear primary and secondary action.

### Task P3.2 — Implement market-layer story

- [ ] Replace the current rectangular input grid with a connected visual layer story.
- [ ] Show Price → OI → OI Change → Volume → IV → Greeks → Structure → Market State.
- [ ] Use Signal Field/StrikeRail primitives where appropriate.

### Task P3.3 — Add intelligence/strategy/risk visual sections

- [ ] Market Intelligence: large system-level visual.
- [ ] Strategy Lab: market view → strategy → payoff → risk.
- [ ] Risk: payoff/Greek/scenario concept.
- [ ] Paper trading: decision → simulation → position → review.
- [ ] Avoid reproducing every dedicated-page detail.

### Task P3.4 — Add workflow rail and final CTA

**Files:**
- Create: `frontend/components/public/WorkflowRail.js`
- Modify: `frontend/app/(public)/page.js`

- [ ] Implement the six-stage rail.
- [ ] Keep the homepage as the condensed overview; dedicated How It Works remains canonical.
- [ ] Use the approved final CTA direction: `Enter the StrikeNova workflow.`

### Task P3.5 — Homepage verification

- [ ] Update homepage test expectations for new brand/content.
- [ ] Verify one H1.
- [ ] Verify CTA navigation.
- [ ] Verify mobile stacking and Signal Field scaling.
- [ ] Browser-check desktop and mobile screenshots.

### Gate P3

- [ ] Homepage visually demonstrates the new category.
- [ ] No misleading live/demo state.
- [ ] Project Control Center approves P4.

---

# Phase P4 — Product Page Redesigns

**Deliverable:** Four product pages share the new visual language without becoming clones.

## Task P4.1 — Features / Capability Atlas

**Files:**
- Modify: `frontend/app/(public)/features/ClientPage.js`

- [ ] Replace repetitive feature-card presentation with an asymmetric Capability Atlas.
- [ ] Give Market Intelligence, Strategy Lab, and Paper Trading visually distinct modules.
- [ ] Keep research/future capabilities clearly separated.
- [ ] Link to dedicated pages.
- [ ] Keep detailed feature inventory available but secondary to product storytelling.

## Task P4.2 — Market Intelligence

**Files:**
- Modify: `frontend/app/(public)/market-intelligence/ClientPage.js`

- [ ] Make Signal Field/Market State the dominant visual.
- [ ] Present positioning, volatility, Greeks and structure as connected dimensions.
- [ ] Keep demo label prominent.
- [ ] Separate research direction visually.
- [ ] Ensure future GEX/advanced positioning content remains research/future only.

## Task P4.3 — Strategy Lab

**Files:**
- Modify: `frontend/app/(public)/strategy-lab/ClientPage.js`

- [ ] Convert the current vertically stacked demo into a strategy-workspace composition.
- [ ] Place strategy legs and payoff/risk visualizations in a stronger desktop relationship.
- [ ] Preserve readable mobile stacking.
- [ ] Keep illustrative data disclaimer.
- [ ] Do not connect the public page to authenticated execution APIs.

## Task P4.4 — Paper Trading

**Files:**
- Modify: `frontend/app/(public)/paper-trading/ClientPage.js`

- [ ] Reframe page as a rehearsal/experiment loop.
- [ ] Use a visually connected capital → orders → positions → P&L → review model.
- [ ] Convert dense mobile position-table content into cards or another readable responsive format.
- [ ] Preserve simulation disclaimer.

### Gate P4

- [ ] Four pages are materially more distinctive than V1.1.
- [ ] Each page retains truthful capability scope.
- [ ] Project Control Center approves P5.

---

# Phase P5 — Story Pages

**Deliverable:** How It Works and About become brand-building experiences rather than text stacks.

## Task P5.1 — How It Works

**Files:**
- Modify: `frontend/app/(public)/how-it-works/ClientPage.js`
- Modify/reuse: `frontend/components/public/WorkflowRail.js`

- [ ] Build canonical six-step vertical signal rail.
- [ ] Give each step a compact representative visual.
- [ ] Keep exact semantics aligned with homepage workflow.
- [ ] Add reduced-motion path.

## Task P5.2 — About

**Files:**
- Modify: `frontend/app/(public)/about/ClientPage.js`

- [ ] Remove repeated philosophy language.
- [ ] Tell an authentic why/what/not-building/long-term-direction story.
- [ ] Include a concise "What StrikeNova is not" section without attacking competitors.
- [ ] Do not invent credentials, testimonials, users, or partnerships.

### Gate P5

- [ ] Both pages tell distinct stories.
- [ ] No redundant section copy remains.
- [ ] Project Control Center approves P6.

---

# Phase P6 — Navigation, Footer, Metadata and Cross-Page Cohesion

**Deliverable:** Every public route feels like one StrikeNova product.

### Task P6.1 — PublicHeader

**Files:**
- Modify: `frontend/components/public/PublicHeader.js`

- [ ] Replace Options Dashboard public identity with StrikeNova.
- [ ] Update navigation labels/grouping to match actual routes.
- [ ] Keep login and primary CTA behavior intact.
- [ ] Preserve click-outside and Escape behavior.
- [ ] Improve active states and visual hierarchy.

### Task P6.2 — PublicFooter

**Files:**
- Modify: `frontend/components/public/PublicFooter.js`

- [ ] Update branding and route labels.
- [ ] Ensure product and learning links remain accurate.
- [ ] Keep legal/disclaimer links truthful to actual routes.

### Task P6.3 — Metadata

**Files:**
- Modify: `frontend/app/layout.js`
- Modify: public route metadata files as needed.

- [ ] Change public default brand metadata to StrikeNova.
- [ ] Preserve unique page titles/descriptions.
- [ ] Remove unsupported claims such as "live & live execution" if they do not reflect the verified product state.

### Task P6.4 — Cross-page content truth audit

- [ ] Search all public pages for `Options Dashboard` brand references that should become StrikeNova.
- [ ] Search for `LIVE`, performance, accuracy, guarantee, customer-count, partnership, or certification claims.
- [ ] Search for future capabilities represented without `Research Direction`, `Coming Later`, or equivalent labeling.

### Gate P6

- [ ] Branding is consistent across all public routes.
- [ ] Metadata is truthful and unique.
- [ ] Project Control Center approves P7.

---

# Phase P7 — Accessibility, Responsive and Performance Hardening

**Deliverable:** The futuristic design is production-quality rather than only visually impressive.

### Task P7.1 — Accessibility audit

- [ ] Verify heading hierarchy and single H1 per page.
- [ ] Verify keyboard navigation across menus, links, and interactive visuals.
- [ ] Verify focus-visible treatment.
- [ ] Verify chart/Signal Field accessible labels.
- [ ] Verify important semantics do not depend on color alone.
- [ ] Verify reduced-motion behavior.

### Task P7.2 — Responsive audit

- [ ] Verify 1440×900.
- [ ] Verify 1280×800.
- [ ] Verify 390×844.
- [ ] Verify 360×800.
- [ ] Check horizontal overflow.
- [ ] Check CTA touch sizes.
- [ ] Check table/card transformations.
- [ ] Check typography wrapping.

### Task P7.3 — Performance audit

- [ ] Inspect client component count introduced by V1.2.
- [ ] Remove any unnecessary client state from static public components.
- [ ] Prefer SVG/CSS to heavy media.
- [ ] Check bundle/build impact of any newly introduced package.
- [ ] Ensure decorative animation cannot block meaningful content rendering.

### Gate P7

- [ ] All four viewport classes are clean.
- [ ] Accessibility issues are resolved or explicitly classified.
- [ ] Performance remains acceptable.
- [ ] Project Control Center approves final acceptance.

---

# Phase P8 — Final Public Acceptance

**Deliverable:** Release-ready V1.2 public site with traceable evidence.

### Task P8.1 — Automated verification

- [ ] Run the focused public test suite.
- [ ] Run the complete frontend test suite according to repository commands.
- [ ] Run production build.
- [ ] Record results and classify unrelated/pre-existing failures rather than hiding them.

### Task P8.2 — Browser verification

- [ ] Open the local public site.
- [ ] Wait for network idle.
- [ ] Capture screenshots for desktop and mobile.
- [ ] Check for framework error overlays.
- [ ] Check console errors.
- [ ] Snapshot interactive elements.
- [ ] Navigate all seven public routes.

### Task P8.3 — Regression verification

- [ ] Verify authenticated-app routes were not modified by the public task series.
- [ ] Verify no backend/API files changed.
- [ ] Verify no broker/execution behavior changed.
- [ ] Compare route availability before/after.

### Task P8.4 — Update screenshots and status

**Files:**
- Update visual baseline artifacts in `options-dashboard-screenshots` as appropriate.
- Modify: `options-dashboard-project/docs/PROJECT_STATUS.md`

- [ ] Record V1.2 completion evidence.
- [ ] Link the final design/spec/plan documents.
- [ ] Record final verification results.

---

## Public V1.2 Acceptance Checklist

### Brand

- [ ] StrikeNova is the public-facing brand.
- [ ] No accidental legacy branding remains in visible UI or metadata.

### Visual identity

- [ ] Signal Field is recognizable.
- [ ] Visual hierarchy is cinematic but restrained.
- [ ] The site does not look like a generic neon fintech template.
- [ ] Cards are used semantically rather than everywhere.

### Product truth

- [ ] Demo values are clearly illustrative.
- [ ] Research capabilities are labeled as future/research.
- [ ] No unsupported performance or prediction claims.

### UX

- [ ] Navigation is understandable.
- [ ] CTA hierarchy is clear.
- [ ] Homepage communicates the category quickly.
- [ ] Product pages tell distinct stories.

### Accessibility

- [ ] Keyboard navigation works.
- [ ] Focus is visible.
- [ ] Reduced motion works.
- [ ] Visualizations have text alternatives/labels.
- [ ] Contrast and touch targets are acceptable.

### Engineering

- [ ] Public route group remains isolated.
- [ ] Authenticated app unaffected.
- [ ] Backend/database/broker/execution code untouched.
- [ ] Build/test/browser verification evidence recorded.

---

## Execution Order

```text
P0 Baseline
   ↓
P1 Design System
   ↓
P2 Signal Field
   ↓
P3 Homepage
   ↓
P4 Product Pages
   ↓
P5 Story Pages
   ↓
P6 Navigation + Metadata + Cohesion
   ↓
P7 Accessibility + Responsive + Performance
   ↓
P8 Final Acceptance
```

Each phase is independently reviewable. No phase assumes the next phase is approved. The Project Control Center should approve the gate before FreeBuff advances.
