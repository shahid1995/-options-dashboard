# StrikeNova Visual Design System V1 — Implementation Plan

**Date:** 2026-09-13  
**Status:** Approved design-system implementation plan  
**Design contract:** `docs/superpowers/specs/2026-09-13-strikenova-design-system-v1-design.md`  
**Target branch:** `feat/strikenova-day35-portfolio-intelligence`

## 1. Objective

Translate the approved StrikeNova Visual Design System V1 into the existing frontend without replacing the current application architecture, changing backend behavior, or introducing a new design framework unnecessarily.

The implementation must improve visual consistency and product hierarchy while preserving existing routes, functionality, data contracts, trading semantics, accessibility, and test coverage.

## 2. Non-goals

- No backend/API changes.
- No broker/execution behavior changes.
- No redesign of quantitative formulas or market-intelligence methodology.
- No replacement of Next.js or the current component stack.
- No HorizonX/template dependency.
- No broad visual rewrite before an inventory and baseline audit.
- No direct deployment.

## 3. Phase A — Frontend inventory and baseline

1. Identify the actual frontend package/app and its framework/component structure.
2. Inventory routes, layouts, navigation, global styles, theme/tokens, reusable components, charts, tables, forms, dialogs and current public pages.
3. Identify existing shadcn/Radix/Tailwind or equivalent primitives before adding anything.
4. Record current screenshots/build/test status where available.
5. Map current UI surfaces to the design-system sections.
6. Produce a gap matrix: `existing / adapt / create / defer`.

**Gate A:** No implementation changes until the inventory and gap matrix are complete and consistent with the approved design specification.

## 4. Phase B — Foundation tokens

Implement or normalize only the tokens required by the approved specification:

- typography hierarchy;
- semantic foreground/background/border tokens;
- market-state semantic colors;
- spacing/radius/shadow conventions;
- focus/interaction states;
- chart semantic tokens;
- light/dark behavior if already supported.

Prefer existing CSS variables/design-token infrastructure. Do not introduce duplicate token systems.

**Gate B:** Existing components continue to render correctly and token changes do not alter application semantics.

## 5. Phase C — Application shell

Refine the authenticated application shell:

- primary navigation;
- page header/context bar;
- content width and grid;
- responsive sidebar/navigation behavior;
- page-level spacing;
- active/selected states;
- loading/empty/error states.

The shell should establish the "market intelligence command center" hierarchy without forcing every page into the same layout.

**Gate C:** All existing app routes remain reachable and functional.

## 6. Phase D — Core data components

Standardize reusable primitives before page-specific redesign:

- metric/KPI blocks;
- intelligence cards;
- data tables;
- filters and segmented controls;
- badges/status indicators;
- tooltips and contextual explanations;
- chart containers;
- empty/loading/error states;
- action controls.

Each component must have a clear semantic purpose and avoid decorative-only variants.

## 7. Phase E — Market Intelligence

Prioritize the Market Intelligence surface because it represents StrikeNova's primary differentiation.

Apply the governing question rule:

- GEX: dealer-positioning/volatility context;
- Gamma Flip: modeled regime transition;
- Walls: relevant positioning concentration;
- OI: concentration/structure;
- IV/Vega/Delta: volatility and directional context;
- regime/signal panels: interpretation with confidence and caveats.

Charts must retain readable axes, legends, units, tooltips, responsive behavior and reduced-motion compatibility.

Do not visually imply that GEX or any single metric is a guaranteed directional predictor.

## 8. Phase F — Strategy Lab, Paper Trading and Journal

Apply the system to workflow surfaces in this order:

1. Strategy Lab — thesis, legs, payoff, risk and scenario hierarchy.
2. Paper Trading — order/position state clarity and action hierarchy.
3. Trading Journal — performance analytics, history and review workflow.

Preserve all existing trading/economic behavior. This phase is presentation-only unless an existing UI bug is directly exposed by the visual work.

## 9. Phase G — Public website

Refine the public pages after the application foundation is stable.

Priority:

1. Home.
2. Features.
3. Market Intelligence/product storytelling.
4. Strategy Lab.
5. Paper Trading.
6. How It Works.
7. About.

Use premium visual storytelling selectively. Avoid generic crypto/AI aesthetics, excessive glassmorphism, gratuitous 3D, and animation without explanatory value.

## 10. Phase H — Motion and responsive polish

Add motion only where it communicates state, hierarchy or continuity:

- navigation/page transitions;
- metric state changes;
- strategy-leg changes;
- order/position lifecycle states;
- progressive disclosure.

Respect `prefers-reduced-motion`. Avoid animation loops that distract from live market information.

Responsive behavior must be verified at desktop, tablet and mobile breakpoints appropriate to the existing application.

## 11. Phase I — Accessibility and visual QA

Verify:

- keyboard navigation;
- visible focus states;
- semantic controls;
- color contrast;
- non-color indicators for market state;
- table readability;
- chart alternatives/tooltips;
- reduced motion;
- responsive overflow;
- loading/error/empty states.

Use browser-based verification against the actual running application. Capture representative screenshots for comparison against the design contract.

## 12. Phase J — Independent audit

Before declaring implementation complete, run an independent read-only audit against:

- approved design-system requirements;
- route preservation;
- component consistency;
- accessibility;
- responsive behavior;
- visual hierarchy;
- quantitative-label integrity;
- performance risks;
- regression tests/build.

The audit must report evidence, not aesthetic opinion alone.

## 13. AI-agent guardrails

Any coding agent implementing this plan must:

1. Read the approved design specification first.
2. Inspect existing components before creating replacements.
3. Reuse existing primitives where appropriate.
4. Keep changes scoped to the current phase.
5. Never invent market-data semantics or quantitative claims.
6. Never modify backend/trading behavior as part of visual work.
7. Never add a paid visual dependency without explicit approval.
8. Never import a HorizonX or other commercial template wholesale.
9. Maintain existing tests and add focused UI tests where behavior changes.
10. Provide a concise change summary, verification evidence and remaining gaps.
11. Do not deploy changes directly.

## 14. Suggested execution order

`A inventory → B tokens → C shell → D primitives → E Market Intelligence → F workflow surfaces → G public pages → H motion/responsive → I accessibility QA → J independent audit`

Phases may be split into smaller commits, but dependency order must be preserved. Independent read-only audits may run between major phases.

## 15. Acceptance criteria

The implementation is ready for final review only when:

- the approved design-system contract is traceably implemented;
- no duplicate design-token system was introduced without justification;
- existing functionality/routes remain intact;
- Market Intelligence is clearly the product's visual center of gravity;
- quantitative information is presented with correct semantics and units;
- responsive and accessibility requirements are verified;
- build/tests pass at the appropriate project level;
- browser verification shows no material console/runtime/UI regressions;
- no direct deployment was performed;
- the independent audit has no unresolved critical or high-severity findings.
