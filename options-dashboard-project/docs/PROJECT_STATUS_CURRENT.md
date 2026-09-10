# StrikeNova — Current Project Status Snapshot

_Last updated: 2026-09-11_

> This file is the current Project Control Center status snapshot. `docs/PROJECT_STATUS.md` remains the historical engineering ledger. This snapshot records the active workstreams and the next controlled actions.

## Product identity

**Public product brand:** StrikeNova

**Public visual direction:** StrikeNova Signal Field

**Core product positioning:** Options intelligence for structured decisions.

## Current workstreams

| Workstream | Status | Current position | Next controlled action |
|---|---|---|---|
| Core platform / base architecture | 🔄 Ongoing | Continues independently of the public-site workstream. Latest known documented core handoff: Day 38 at commit `5094fb461e1baf9981a19ec3cd450477073c5091`. | Continue approved architecture/review work independently. |
| Public Website V1.1 | ✅ Complete | Seven public routes with shared components, dark/gold foundation, responsive behavior and accessibility foundations. | Preserve as historical implementation baseline. |
| Public Website V1.2 — Signal Field | 🟡 P1 review / corrective patch required | P0 passed. P1 design-system implementation exists on `feat/strikenova-day35-portfolio-intelligence` at commit `1eece4028ae05ed9b610c859e6c0d542e615a521`. GitHub Vercel status is successful. The implementation is presentation-only and the diff is limited to 11 intended public design-system files. | Apply the two P1 corrective findings below, re-run fresh verification, then request P2 authorization. |
| Public design system | 🟠 Corrective patch required | Tokens, motion, surfaces, buttons, metrics, visualization framing, signal primitives, layout and truth primitives are implemented. | Wire the new motion CSS into `PublicLayout` without changing auth behavior, and make the small button variant comply with the 44px effective touch-target requirement. |
| Signal Field visualization | ⏳ Planned | Signature market-native visualization remains defined but not implemented. | P2 only after P1 corrective verification is accepted. |
| Public page redesign | ⏳ Planned | Homepage, product pages and story pages remain on the V1.1 implementation baseline. | P3–P5, one gate at a time. |
| Public hardening | ⏳ Planned | Accessibility, responsive, performance, metadata and browser verification criteria defined. | P6–P8. |

## V1.2 control documents

### Design specification

`docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md`

Status: ✅ committed to `main`

Commit: `db2b7c4582c749a9864e638127c0a93fdc7f1284`

Defines the approved Signal Field visual language, StrikeNova branding, semantic colors, typography, motion, visualization contract, seven-page redesign targets, component responsibilities, content/data truth rules, accessibility, responsive requirements, performance constraints and core-platform boundaries.

### Implementation plan

`docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md`

Status: ✅ committed to `main`

Commit: `33d8488be096e8d3c019c0c43b09fec0dd6d0b98`

Execution order:

```text
P0 Baseline
  ↓
P1 Public Design System
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

### P0 baseline audit

`docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md`

Status: ✅ PASS — audit-only; no production code changes

Commit: `dd271e109d1e72f3e2aaa5b860fe02e74424dc73`

Fresh baseline evidence recorded by the implementation agent:

- 7 public routes exist, return HTTP 200 and are statically prerendered.
- Shared public components and styling were inventoried.
- Approximately 345 inline style objects were identified across the public surface.
- Existing public visualizations were classified for Signal Field evolution.
- Legacy branding occurrences and demo/research data were inventoried.
- Narrow-viewport testing exposed horizontal overflow and table overflow that must be fixed before final acceptance.
- Accessibility findings include weak heading hierarchy, color-only P&L encoding, and visualization labeling gaps.
- Public/core architecture boundary was audited as safe for presentation-only work.
- The agent reported 1,453 passing tests across 61 frontend test files and a successful build with 21 static routes.

## P0 review outcome

### Independent Project Control Center review

P0 is accepted as the baseline gate for proceeding to P1 because the committed change is documentation-only and the audit captures the required architecture, styling, branding, responsive and accessibility risks.

Two caveats remain recorded for later hardening:

1. The audit's CDP viewport measurement had a known narrow-device metrics discrepancy. Final responsive verification must use confirmed effective viewport dimensions at 390×844 and 360×800.
2. A mobile-menu link-count observation of zero must not be treated as proof that navigation is missing; the menu must be explicitly opened and its links interactively verified during P7.

The P0 audit also contains an outdated note that the V1.2 authority document was "NOT FOUND". This is a documentation inconsistency only: the approved V1.2 design specification is present in the repository at the path above and was committed before P0.

## Public V1.2 phase status

| Phase | Status |
|---|---|
| P0 — Baseline, inventory and safety fence | ✅ Complete / PASS |
| P1 — StrikeNova public design system | 🟡 Implemented / corrective patch required |
| P2 — Signal Field foundation | ⏳ Planned |
| P3 — Homepage flagship redesign | ⏳ Planned |
| P4 — Product pages | ⏳ Planned |
| P5 — Story pages | ⏳ Planned |
| P6 — Navigation, footer, metadata and cohesion | ⏳ Planned |
| P7 — Accessibility, responsive and performance hardening | ⏳ Planned |
| P8 — Final public acceptance | ⏳ Planned |

## P1 implementation record

### Implementation branch

`feat/strikenova-day35-portfolio-intelligence`

### Implementation commit

`1eece4028ae05ed9b610c859e6c0d542e615a521`

### Independent GitHub review

- Branch head resolves to the P1 commit above.
- The branch is exactly one commit ahead of the P0 baseline `dd271e109d1e72f3e2aaa5b860fe02e74424dc73`.
- The commit changes only 11 files under `frontend/components/public/`; no backend, database, broker, OAuth, execution, authenticated-app, market-data, or financial-calculation files are part of the diff.
- GitHub reports a successful Vercel status for the commit.
- The implementation agent reported fresh local verification of 1,538 passing tests and a successful Next.js build with 21 static routes. Those test/build results are treated as agent-reported evidence; they have not been independently re-executed in the Project Control Center environment.

### P1 implementation inventory

- `tokens.js` — semantic color, typography, spacing, radius, shadow, layer, motion, data-state and research-state tokens.
- `motion.js` — keyframes, utility styles, focus-visible CSS and reduced-motion CSS.
- `surfaces.js` — Surface, Panel, MetricPanel, OutlinePanel, SignalPanel.
- `buttons.js` — primary/secondary/ghost/subtle button and link primitives.
- `Metric.js` — reusable metric display and formatting helper.
- `VisualizationFrame.js` — reusable visualization frame with title/legend/caption/demo label.
- `signals.js` — SignalLine, SignalNode, StrikeRail, DataTrace, TechnicalDivider, GridOverlay.
- `layout.js` — Section, Container, TwoColumn, MetricGrid, CardGrid, BentoGrid, FlexRow, FlexColumn, Asymmetric.
- `truth.js` — DemoLabel, ResearchBadge, DataStateBadge, Eyebrow, SectionTitle.
- `design-system.test.js` — P1 primitive test suite.
- `index.js` — public design-system barrel exports.

### P1 corrective findings

#### Finding 1 — motion CSS is defined but not wired into the public layout

`frontend/components/public/motion.js` exports `PUBLIC_DS_CSS`, including the new `sn-*` keyframes, `.ds-focus-ring` rules and reduced-motion rules.

`frontend/components/public/PublicLayout.js` still injects only the legacy `PUBLIC_CSS` from `styles.js` and does not inject `PUBLIC_DS_CSS`.

Result: the new motion/focus/reduced-motion CSS is not globally active simply by installing the P1 design system.

Required correction:

- Inject `PUBLIC_DS_CSS` once from `PublicLayout` alongside the existing public CSS, or replace the legacy injection with an equivalent combined public stylesheet without changing auth behavior.
- Keep OAuth redirect handling and `AuthModalProvider` behavior unchanged.
- Verify that the new keyframes and focus/reduced-motion rules are actually available to public primitives.

#### Finding 2 — small button variant does not meet the P1 touch-target requirement

`frontend/components/public/buttons.js` defines the `sm` button size with `minHeight: "36px"` while the P1 contract requires a 44px effective touch target where practical.

Required correction:

- Preserve the visual intent of the small variant but provide at least a 44px effective interactive target, for example through min-height or equivalent hit-area treatment.
- Do not reduce the target below 44px merely to preserve visual compactness.

### P1 gate

P1 is **NOT authorized to advance to P2 yet**.

The corrective patch must:

1. address Finding 1;
2. address Finding 2;
3. add/update focused tests proving the corrected behavior;
4. run fresh frontend tests and a fresh production build;
5. verify all seven public routes still load;
6. confirm no protected application files changed;
7. commit the corrective patch on the same feature branch;
8. stop and report.

## Public pages in scope

Existing URLs remain unchanged:

- `/`
- `/features`
- `/market-intelligence`
- `/strategy-lab`
- `/paper-trading`
- `/how-it-works`
- `/about`

The `(public)` / `(app)` route-group architecture remains unchanged.

## V1.2 design target

### Current

```text
Options Dashboard
    ↓
dark + gold SaaS/trading presentation
    ↓
repeated cards + tables + restrained animation
```

### Target

```text
StrikeNova
    ↓
Options intelligence for structured decisions
    ↓
Signal Field
    ↓
market-native visual language
    ↓
computational / futuristic / premium
    ↓
credible, restrained, distinctive
```

## Strict no-touch boundary for public V1.2

Unless separately approved, V1.2 must not modify:

- backend/FastAPI code
- database/schema/migrations
- broker integrations
- OAuth/session logic
- paper/live execution semantics
- trading engine
- market-data architecture
- authenticated `(app)` routes
- financial calculation engines

## Working rule

Public V1.2 progresses in parallel with core architecture work, but every public phase is independently gated. A public visual task may not introduce backend shortcuts, fake live data, duplicated financial logic, broker coupling, or authenticated-app coupling merely to achieve a visual effect.
