# StrikeNova Visual Design System V1 — Phase F Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved StrikeNova V1 design system to Strategy Lab, Paper Trading, and Trading Journal surfaces without changing trading, execution, backend, broker, API, or quantitative behavior.

**Architecture:** Phase F is divided into independently reviewable UI tracks over the existing application shell. The current repository has a single large `/paper` page that contains the strategy builder, paper-trading controls, portfolio/analytics panels, and journal state, so the plan sequences work by user-facing responsibility while preserving shared component boundaries. Phase D primitives and canonical design tokens remain the only visual foundation; existing calculations, APIs, state machines, and execution paths are consumed unchanged.

**Tech Stack:** Next.js 14.2.35, React 18.3.1, JavaScript, Recharts 2.12.7, Vitest, existing StrikeNova `components/app/core.js`, canonical `components/public/tokens.js`, and legacy compatibility layer `lib/ui.js`.

**Spec:** `docs/superpowers/specs/2026-09-13-strikenova-design-system-v1-design.md`

## Global Constraints

- Read the full V1 design specification before each implementation track.
- Read the full implementation plan before editing Phase F surfaces.
- Preserve the established canonical token source at `frontend/components/public/tokens.js`.
- Reuse Phase D primitives from `frontend/components/app/core.js`; do not create a competing design-token or primitive system.
- Preserve null as unavailable; never replace unavailable quantitative values with zero.
- Preserve quantitative meaning, units, formulas, calculations, API contracts, and execution semantics exactly.
- No backend, API, broker, order-execution, strategy-calculation, payoff, Greeks, margin, P&L, or risk-model changes.
- No dependency/package changes.
- No public website work; public pages remain Phase G scope.
- No direct deployment.
- Preserve unrelated working-tree changes.
- Do not begin Phase G after Phase F; stop after the Phase F audit.

---

## Files and Responsibilities

### Shared foundation

- `frontend/components/app/core.js` — canonical application primitives. Modify only when a missing primitive behavior is demonstrated by Phase F evidence.
- `frontend/components/public/tokens.js` — canonical visual tokens. Modify only when a true shared token gap is demonstrated.
- `frontend/lib/ui.js` — compatibility bridge/legacy UI utilities. Do not create a second token source.
- `frontend/components/app/styles.js` — legacy compatibility layer. Preserve unless a Phase F surface needs a narrowly-scoped migration.

### Strategy Lab / Paper Trading

- `frontend/app/(app)/paper/page.js` — current integrated strategy-builder/paper-trading/journal surface; Phase F UI changes are limited to Strategy Lab, Paper Trading, and Journal sections.
- `frontend/app/(app)/paper/ScenarioPanel.js` — scenario presentation.
- `frontend/app/(app)/paper/GreekAnalyticsPanel.js` — strategy Greeks presentation.
- `frontend/app/(app)/paper/IVAnalyticsPanel.js` — IV presentation.
- `frontend/app/(app)/paper/AnalyticsPanel.js` — strategy/portfolio analytics presentation.
- `frontend/app/(app)/paper/PortfolioAnalyticsPanel.js` — portfolio analytics presentation.
- `frontend/app/(app)/paper/CapitalPanel.js` — capital/margin presentation.
- `frontend/app/(app)/paper/BrokerConnectionPanel.js` — connection-state presentation only; broker behavior untouched.
- `frontend/app/(app)/paper/BulkExit.js` — exit-flow presentation only; execution behavior untouched.
- `frontend/lib/strategies.js` — existing strategy definitions; read-only reference unless a UI-only label is proven necessary.
- `frontend/lib/strategy/` — existing strategy helpers/validation; read-only reference.
- `frontend/lib/calculations/` — existing payoff/Greeks/scenario/capital calculations; read-only during Phase F.
- Existing component test files adjacent to the modified components; add focused tests rather than weakening existing assertions.

### Phase F audit

- `docs/superpowers/audits/2026-09-14-strikenova-design-system-phase-f-strategy-paper-journal.md`

---

# Track A — Strategy Lab

### Task 1: Inventory the existing Strategy Lab surface

**Files:**
- Read: `frontend/app/(app)/paper/page.js`
- Read: `frontend/app/(app)/paper/ScenarioPanel.js`
- Read: `frontend/app/(app)/paper/GreekAnalyticsPanel.js`
- Read: `frontend/app/(app)/paper/IVAnalyticsPanel.js`
- Read: `frontend/app/(app)/paper/AnalyticsPanel.js`
- Read: `frontend/lib/strategy/strategy.js`
- Read: `frontend/lib/strategy/strategyValidation.js`
- Read: `frontend/lib/calculations/payoff.js`
- Read: `frontend/lib/calculations/strategyCalculator.js`

**Interfaces:**
- Consumes existing strategy-builder state, calculated payoff/Greeks/scenario values, and execution-preview data.
- Produces an implementation map identifying visual boundaries without changing those interfaces.

- [ ] **Step 1: Inspect the current builder hierarchy**
  Record the actual order and responsibility of symbol/expiry selection, strategy templates, leg editor, payoff, analytics, scenario, review/preview, save/draft controls, and execute controls.

- [ ] **Step 2: Identify existing visual duplication**
  Mark inline styles, duplicated cards/metrics, legacy `Stat`/`TopNav` usage, and Recharts wrappers that can safely adopt Phase D primitives without moving logic.

- [ ] **Step 3: Record semantic risk points**
  Explicitly identify payoff, max profit/loss, breakeven, Greeks, IV, capital, scenario, and execution-preview values whose labels/units must remain unchanged.

- [ ] **Step 4: Commit inventory notes with the implementation plan only**
  Do not modify application behavior during inventory.

### Task 2: Establish Strategy Lab page hierarchy

**Files:**
- Modify: `frontend/app/(app)/paper/page.js`
- Test: existing `/paper` page/component tests plus a focused Strategy Lab render test where test infrastructure permits

**Interfaces:**
- Consumes existing builder state and helper outputs.
- Produces visual sections with unchanged state/event handlers and unchanged calculation inputs/outputs.

- [ ] **Step 1: Write failing assertions for the intended hierarchy**
  Assert stable semantic headings/labels for:
  1. market/instrument context;
  2. strategy construction and legs;
  3. payoff/risk summary;
  4. analytical context;
  5. review/preview/action controls.

- [ ] **Step 2: Run focused tests and capture the expected failure**
  Use the repository's existing Vitest command for the affected test file(s).

- [ ] **Step 3: Implement the minimal hierarchy change**
  Use existing containers/primitives and preserve all existing event handlers, state variables, and helper calls.

- [ ] **Step 4: Replace only appropriate metric/card presentations**
  Use `Metric`, `Badge`, `SegmentedControl`, `ActionButton`, `ChartContainer`, and state primitives where they directly map to an existing responsibility. Do not invent new strategy semantics.

- [ ] **Step 5: Run focused tests**
  Expected: all affected tests pass.

- [ ] **Step 6: Commit**
  `git commit -m "refactor(ui): structure StrikeNova strategy lab"`

### Task 3: Refine strategy-leg editing and action hierarchy

**Files:**
- Modify: `frontend/app/(app)/paper/page.js`
- Read/modify only if needed: `frontend/app/(app)/paper/BulkExit.js`
- Test: affected focused tests

**Interfaces:**
- Consumes existing leg mutation functions such as `addLeg`, `updateLeg`, `removeLeg`, `duplicateLegIn`, `reverseLegIn`, and existing validation results.
- Produces clearer UI grouping without changing those functions or their arguments.

- [ ] **Step 1: Add tests for keyboard/semantic labels on strategy controls**
  Verify primary controls have meaningful accessible names and that unavailable actions remain disabled/clearly explained.

- [ ] **Step 2: Implement leg-editor hierarchy**
  Separate leg identity, side/type, strike/expiry, quantity, price, and derived information visually while preserving existing controls.

- [ ] **Step 3: Implement explicit action hierarchy**
  Distinguish construction actions, save/draft actions, review/preview, and paper-execution actions. Do not visually imply live trading.

- [ ] **Step 4: Preserve validation/error/loading states**
  Use `ErrorState`, `LoadingState`, and inline status semantics where existing state already exists; do not fabricate new business states.

- [ ] **Step 5: Run focused tests and commit**
  `git commit -m "refactor(ui): refine StrikeNova strategy controls"`

### Task 4: Refine Strategy Lab analytical panels

**Files:**
- Modify: `frontend/app/(app)/paper/ScenarioPanel.js`
- Modify: `frontend/app/(app)/paper/GreekAnalyticsPanel.js`
- Modify: `frontend/app/(app)/paper/IVAnalyticsPanel.js`
- Modify: `frontend/app/(app)/paper/AnalyticsPanel.js`
- Test: affected panel test files or focused render tests

**Interfaces:**
- Consumes existing calculated values exactly as supplied by current callers.
- Produces clearer analytical hierarchy, units, captions, and unavailable states.

- [ ] **Step 1: Add failing tests for titles, units, null handling, and state variants**
- [ ] **Step 2: Convert appropriate top-line values to `Metric`**
- [ ] **Step 3: Wrap meaningful charts with `ChartContainer` while preserving Recharts configuration**
- [ ] **Step 4: Keep Greek/IV/scenario semantics neutral and explicitly labeled**
- [ ] **Step 5: Preserve no-data/loading/error states using existing values**
- [ ] **Step 6: Run focused tests and commit**
  `git commit -m "refactor(ui): refine strategy analytics panels"`

---

# Track B — Paper Trading

### Task 5: Inventory and restructure Paper Trading state hierarchy

**Files:**
- Read/modify: `frontend/app/(app)/paper/page.js`
- Modify when presentation-only: `frontend/app/(app)/paper/PortfolioAnalyticsPanel.js`
- Modify when presentation-only: `frontend/app/(app)/paper/CapitalPanel.js`
- Modify when presentation-only: `frontend/app/(app)/paper/BrokerConnectionPanel.js`

**Interfaces:**
- Consumes existing portfolio/capital/broker data from `frontend/lib/api.js` and existing frontend adapters.
- Produces UI hierarchy only; API response shapes and execution handlers remain unchanged.

- [ ] **Step 1: Add tests for paper-trading section headings and status states**
- [ ] **Step 2: Establish hierarchy as session/account state → positions/orders → P&L/risk → actions**
- [ ] **Step 3: Use `Metric`, `Badge`, `Table`, `ActionButton`, and state primitives where appropriate**
- [ ] **Step 4: Keep broker connection state informational and avoid introducing credential-entry behavior**
- [ ] **Step 5: Preserve paper-only language and existing market-open/closed semantics**
- [ ] **Step 6: Run focused tests and commit**
  `git commit -m "refactor(ui): structure StrikeNova paper trading"`

### Task 6: Refine portfolio, capital, and exit presentation

**Files:**
- Modify: `frontend/app/(app)/paper/PortfolioAnalyticsPanel.js`
- Modify: `frontend/app/(app)/paper/CapitalPanel.js`
- Modify: `frontend/app/(app)/paper/BulkExit.js`
- Modify only the relevant `/paper/page.js` integration points

**Interfaces:**
- Consumes existing portfolio/capital/exit display models.
- Produces clearer hierarchy with unchanged values, formulas, quantities, and execution calls.

- [ ] **Step 1: Add tests for null/unavailable values and semantic status badges**
- [ ] **Step 2: Apply `Metric` to summary values with explicit units**
- [ ] **Step 3: Apply `Table` to dense position/order-style datasets where an existing table is already present**
- [ ] **Step 4: Keep P&L/risk colors semantically justified and never use traffic-light colors for neutral structural ratios**
- [ ] **Step 5: Keep exit controls visually distinct from analytics without changing their behavior**
- [ ] **Step 6: Run focused tests and commit**
  `git commit -m "refactor(ui): refine paper portfolio analytics"`

---

# Track C — Trading Journal

### Task 7: Inventory and restructure Journal presentation

**Files:**
- Modify: `frontend/app/(app)/paper/page.js` journal portions only
- Read: existing `getPaperJournal`, `historyToCsv`, `fmtJournalDate`, journal filtering/pagination state

**Interfaces:**
- Consumes existing DB-backed paper journal results and CSV/history helpers.
- Produces journal UI hierarchy without changing persistence or journal data models.

- [ ] **Step 1: Add failing tests for journal heading, empty state, pagination/filter labels, and date formatting**
- [ ] **Step 2: Establish hierarchy as performance summary → filters → entries → entry detail/actions**
- [ ] **Step 3: Use `Table`, `Badge`, `Metric`, `SegmentedControl`, and `EmptyState` where they correspond to existing behavior**
- [ ] **Step 4: Keep journal values descriptive rather than prescriptive**
- [ ] **Step 5: Preserve CSV export and pagination/filter behavior unchanged**
- [ ] **Step 6: Run focused tests and commit**
  `git commit -m "refactor(ui): structure StrikeNova trading journal"`

### Task 8: Refine Journal detail and responsive behavior

**Files:**
- Modify: `frontend/app/(app)/paper/page.js` journal portions only
- Test: focused journal render/interaction tests

**Interfaces:**
- Consumes existing journal rows/details.
- Produces desktop/tablet/mobile presentation while preserving journal behavior.

- [ ] **Step 1: Add tests for mobile-safe labels and empty/loading/error states**
- [ ] **Step 2: Implement responsive journal layout**
- [ ] **Step 3: Ensure dense columns do not create silent horizontal overflow**
- [ ] **Step 4: Preserve keyboard access and visible focus for journal controls**
- [ ] **Step 5: Run focused tests and commit**
  `git commit -m "refactor(ui): refine StrikeNova journal responsiveness"`

---

# Track D — Shared UI and Accessibility Consolidation

### Task 9: Extract only proven shared Phase F presentation patterns

**Files:**
- Modify: `frontend/components/app/core.js` only for a demonstrated missing shared primitive behavior
- Modify: `frontend/components/public/tokens.js` only for a demonstrated shared token gap
- Read/modify: affected Phase F components
- Test: `frontend/components/app/core.test.js` plus affected tests

**Interfaces:**
- Consumes existing Phase D primitives.
- Produces only minimal shared behavior proven by repeated Phase F use.

- [ ] **Step 1: Review repeated Phase F patterns after Tracks A–C**
- [ ] **Step 2: Add a failing primitive test only if the same behavior appears in at least two Phase F surfaces**
- [ ] **Step 3: Implement the smallest reusable primitive extension**
- [ ] **Step 4: Update consumers without changing semantics**
- [ ] **Step 5: Run core and affected tests**
- [ ] **Step 6: Commit only if shared extraction is justified**
  `git commit -m "refactor(ui): consolidate Phase F primitives"`

### Task 10: Accessibility and responsive pass

**Files:**
- All Phase F files modified by Tasks 2–9

**Interfaces:**
- Consumes final Phase F UI.
- Produces evidence for semantic HTML, focus behavior, keyboard controls, responsive hierarchy, and non-color status communication.

- [ ] **Step 1: Add/adjust tests for accessible names, headings, table headers, selected-state semantics, and unavailable-state text**
- [ ] **Step 2: Verify keyboard focus and interaction for segmented controls, strategy controls, journal filters, and action buttons**
- [ ] **Step 3: Verify desktop/tablet/mobile widths without changing authentication**
- [ ] **Step 4: Record browser observations separately from unit/static test evidence**
- [ ] **Step 5: Fix only Phase F defects found during the pass**
- [ ] **Step 6: Run focused tests after each correction**

---

# Track E — Final Verification and Audit

### Task 11: Full Phase F verification

**Files:**
- Test: all existing affected tests
- Build: repository frontend build

**Interfaces:**
- Consumes all Phase F implementation work.
- Produces a clean verification baseline for audit.

- [ ] **Step 1: Run focused Strategy Lab tests**
- [ ] **Step 2: Run focused Paper Trading tests**
- [ ] **Step 3: Run focused Journal tests**
- [ ] **Step 4: Run core primitive tests**
- [ ] **Step 5: Run the complete suite**
  `cd options-dashboard-project/frontend && npx vitest run`
  Expected: all baseline tests pass; any increase is from intentional Phase F regression coverage.

- [ ] **Step 6: Run production build**
  `cd options-dashboard-project/frontend && npm run build`
  Expected: successful production build; no accidental route additions after cleanup.

- [ ] **Step 7: Inspect repository scope**
  `git status --short`
  `git diff --stat`
  `git diff`
  Confirm no backend/API/broker/execution/quantitative/dependency/public-site changes.

### Task 12: Browser verification and Phase F audit

**Files:**
- Create: `docs/superpowers/audits/2026-09-14-strikenova-design-system-phase-f-strategy-paper-journal.md`
- Temporary browser harness only if required: `frontend/app/phase-f-verification/page.js`

**Interfaces:**
- Consumes the final authenticated application UI.
- Produces the Phase F evidence/audit and final gate decision.

- [ ] **Step 1: Verify `/paper` at desktop width**
  Check Strategy Lab, Paper Trading, and Journal hierarchy, interaction, no obvious runtime/console errors, and preservation of existing behavior.

- [ ] **Step 2: Verify `/paper` at mobile width**
  Check meaningful hierarchy, no clipping/overflow, usable controls, readable charts/tables, and visible state communication.

- [ ] **Step 3: Verify representative interaction paths**
  Exercise strategy-builder controls, payoff/analytics tab changes, paper-trading state controls, and journal filtering/pagination where authentication/data allow it.

- [ ] **Step 4: If authentication prevents an interaction, document the exact limitation**
  Never call an unauthenticated HTTP 200 check equivalent to authenticated visual verification.

- [ ] **Step 5: Delete any temporary browser harness**
  Re-run the final build after deletion.

- [ ] **Step 6: Write the Phase F audit**
  Include:
  - implementation scope;
  - files changed;
  - design-system primitives adopted;
  - semantic quantitative safeguards;
  - responsive/accessibility evidence;
  - test results;
  - build result;
  - browser evidence and limitations;
  - scope integrity;
  - exact implementation commit SHAs and full GitHub URLs;
  - exact audit commit SHA and full GitHub URL.

- [ ] **Step 7: Final gate decision**
  Use exactly one:
  - `PHASE F CLOSED — PHASE G READY`
  - `PHASE F NOT CLOSED — BLOCKED`

  Do not mark READY when a critical/high UI regression remains, when quantitative semantics changed, or when code/test evidence contradicts the audit.

- [ ] **Step 8: Commit the audit**
  Preferred implementation commits remain focused per track. Preferred final audit message:
  `docs(audit): record StrikeNova design system phase F`

  Push only `feat/strikenova-day35-portfolio-intelligence`.
  Do not merge.
  Do not deploy.

---

## Phase F Semantic Rules

### Strategy Lab

- Payoff charts explain modeled payoff, not guaranteed outcome.
- Max profit/max loss/breakeven values must retain their existing definitions and units.
- Greeks remain analytics, not standalone trading signals.
- Scenario outputs must identify modeled assumptions where already supported by existing copy.
- Execution-preview UI must remain clearly paper execution and must not visually imply live-money execution.

### Paper Trading

- Paper P&L and capital states retain existing meaning.
- Broker connection is a prerequisite/status concept, not an invitation to expose credentials in the UI.
- Market-closed/unknown states remain explicit.
- Exit/bulk-exit controls remain action-oriented but do not change backend execution semantics.

### Trading Journal

- Historical entries are records, not recommendations.
- Performance values retain existing calculation/source semantics.
- Empty/unavailable journal states use explicit unavailable messaging rather than invented zeros.
- Filters and pagination remain behaviorally identical.

---

## Final Scope Guard

Before declaring Phase F complete, verify all of the following:

- no backend files changed;
- no API contracts changed;
- no broker/execution behavior changed;
- no strategy/payoff/Greeks/capital formulas changed;
- no package/dependency changes;
- no public-site pages changed;
- no Phase G work started;
- no direct deployment performed;
- existing routes/functionality remain intact;
- canonical design-token system remains singular;
- all meaningful metrics retain correct semantics and units;
- browser verification is reported honestly and separately from static/source evidence;
- the audit contains exact commit SHAs and full GitHub URLs;
- no unresolved critical/high Phase F findings remain.

**STOP after Phase F.**
