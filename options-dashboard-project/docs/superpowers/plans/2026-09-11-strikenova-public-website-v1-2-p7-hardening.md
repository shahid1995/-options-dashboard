# StrikeNova Public Website V1.2 — P7 Accessibility, Responsive & Performance Hardening

> Status: AUTHORIZED — implementation handoff
> Date: 2026-09-11
> Predecessor: P6 accepted at `665a3adc593bfd9beeac1d05e36734584910f5b4`
> Scope: Whole public-site hardening only. No feature expansion.

## Authority

Design specification:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 baseline:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

P6 execution plan:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p6-navigation-cohesion.md

Current status:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## Objective

Make the redesigned public site production-quality across accessibility, responsive behavior, runtime/browser behavior, and performance while preserving the approved StrikeNova visual direction.

P7 is a hardening phase, not a redesign phase.

Do not introduce new product capabilities or change the public information architecture.

## Public route set

- `/`
- `/features`
- `/market-intelligence`
- `/strategy-lab`
- `/paper-trading`
- `/how-it-works`
- `/about`

Authenticated `(app)` routes remain unchanged.

## P7.1 — Baseline and invariant capture

Before fixes:

- run the existing frontend test suite;
- run the production build;
- verify all seven public routes;
- record current browser console errors/warnings;
- record actual effective viewport dimensions;
- measure horizontal overflow on desktop and mobile;
- record accessibility findings and any existing failures;
- record performance/build/bundle observations.

Do not treat a nominal viewport command-line argument as proof of actual viewport geometry.

## P7.2 — Accessibility hardening

Audit and fix public pages and global public chrome for:

### Semantics

- exactly one H1 per page;
- logical H2/H3 hierarchy;
- semantic `nav`, `main`, `footer` landmarks;
- buttons vs links used correctly;
- lists/tables correctly structured where applicable.

### Keyboard

Verify:

- header dropdowns;
- mobile menu;
- auth CTA/modal trigger;
- all links/buttons;
- any interactive visual controls;
- predictable tab order;
- no keyboard traps.

### Focus

Preserve the P1 visible focus system.

Every keyboard-operable control must have a visible focus indicator.

### Visualizations

Verify:

- SignalField has a useful accessible name and text interpretation;
- payoff chart has meaningful semantics;
- decorative SVGs are hidden from assistive technology;
- critical information is not encoded only by color.

### P&L and status semantics

Replace any public presentation where positive/negative state depends solely on green/red.

Use an additional textual/sign/label cue where needed.

### Reduced motion

Verify:

`prefers-reduced-motion: reduce`

removes or materially reduces non-essential movement without removing content or structure.

Do not remove the P1 motion system unnecessarily.

### Contrast

Check text, borders, focus indicators, status badges, navigation states and data labels against the dark background.

Do not weaken visual identity merely to improve contrast; use semantic token adjustments where required.

## P7.3 — Responsive hardening

Verify actual browser geometry at:

- 1440×900
- 1280×800
- 390×844
- 360×800

At each viewport check every public route for:

- horizontal document overflow;
- clipped text;
- clipped charts/SVG;
- broken grids;
- oversized headings;
- CTA wrapping problems;
- navigation overflow;
- footer overflow;
- unusable touch targets;
- unreadable data/metric layouts.

Fix the known P0 narrow-viewport issues:

- 14–44px horizontal overflow;
- table overflow where still present;
- touch-target issues where still present.

Do not hide overflow globally with a blanket `overflow-x: hidden` unless the underlying layout cause is understood and the fix is demonstrably safe.

### Mobile navigation

Re-test:

- open;
- close;
- click outside;
- Escape;
- keyboard focus;
- actual post-open link count;
- navigation to a child route.

## P7.4 — Component/responsive cleanup

Review reusable public primitives for:

- safe width behavior;
- min-width traps;
- fixed-width visualizations;
- inconsistent mobile padding;
- touch targets;
- typography clamp behavior.

Where a problem originates in a shared primitive, fix it at the primitive level rather than patching every page separately.

Do not change authenticated shared UI primitives unless a public-only fix is impossible and the impact is proven safe.

## P7.5 — Performance hardening

Audit:

- client component count on public routes;
- unnecessary state/effects;
- unnecessary browser listeners;
- repeated rendering of static content;
- expensive SVG/DOM composition;
- animation cost;
- unused dependencies;
- duplicate style payloads;
- large assets;
- unnecessary third-party scripts.

Prefer:

- server rendering for static public content;
- CSS/SVG over heavy libraries;
- deterministic rendering;
- lightweight animations;
- reuse of existing public primitives.

Do not introduce a new performance dependency unless justified.

Do not convert static public content to client components without a concrete need.

## P7.6 — Runtime/browser hardening

Use a real browser against the local app.

For every public route verify:

- no framework error overlay;
- no unhandled runtime exception;
- no console error introduced by V1.2;
- no hydration warning where detectable;
- all global navigation works;
- all CTAs navigate correctly;
- mobile menu works;
- auth CTA still opens existing auth UI without changing auth logic.

## P7.7 — Public truth regression

Re-scan all public routes after hardening for:

- obsolete `Options Dashboard` public branding;
- obsolete `OD` public mark;
- unsupported `LIVE` claims;
- unsupported execution claims;
- unsupported performance/accuracy claims;
- future/research content without explicit status.

Do not add claims during hardening.

## P7.8 — Inline-style and technical cleanup

P0 identified approximately 345 inline style objects.

Do not attempt a full rewrite solely to reduce the count.

Remove/refactor inline styling only when:

- it directly causes a responsive/accessibility/performance problem;
- it is clearly duplicated and the shared primitive already provides the needed behavior;
- the cleanup reduces risk without changing approved page composition.

Record remaining inline-style debt for P8 or later technical work rather than expanding scope.

## Testing requirements

### Automated

- full frontend test suite;
- focused public tests;
- responsive-related tests where practical;
- accessibility-related component tests;
- metadata/header/footer tests;
- SignalField/payoff accessibility tests.

### Browser

All seven public routes.

All four target viewport classes.

Explicit interaction checks:

- desktop dropdowns;
- mobile menu;
- click-outside;
- Escape;
- keyboard navigation;
- auth modal trigger;
- all public CTAs.

## Evidence requirements

For each category report actual evidence:

```text
Tests:
Build:
Routes:
Console errors:
Horizontal overflow:
Accessibility findings:
Reduced motion:
Mobile navigation:
Performance observations:
```

Where a browser limitation or environment quirk prevents a perfect measurement, state the limitation instead of substituting an assumption.

## Strict no-touch boundary

Do NOT modify:

- backend/FastAPI;
- database/schema/migrations;
- broker integrations;
- OAuth/session internals;
- execution/trading semantics;
- trading engine;
- market-data architecture;
- financial calculation engines;
- authenticated `(app)` behavior;
- product capability scope.

Do not redesign page bodies.

Do not add features.

Do not deploy.

## Expected file scope

Public-only files are expected.

Shared public primitives may be changed when they are the root cause of a public hardening issue.

Any change outside the public surface must be justified explicitly in the final report.

## Git

Recommended commit:

`fix(public): harden StrikeNova V1.2 for accessibility responsive performance`

Keep changes focused.

## Gate P7

P7 passes only when:

- all target viewports are clean or remaining issues are explicitly documented and accepted for P8;
- accessibility findings are resolved or explicitly classified;
- runtime/browser checks are clean;
- performance remains acceptable with no unnecessary heavy dependency introduced;
- public truth/branding remains clean;
- protected platform behavior remains untouched.

P8 final acceptance remains a separate phase.

## STOP

After P7 verification:

STOP.

Do not perform P8 final acceptance.
Do not deploy.
Do not modify core platform architecture.
