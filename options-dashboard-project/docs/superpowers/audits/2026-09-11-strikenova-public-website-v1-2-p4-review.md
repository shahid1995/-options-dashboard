# StrikeNova Public Website V1.2 — P4 Review

_Date: 2026-09-11_

## Review result

**P4: CONDITIONAL / CORRECTIVE PATCH REQUIRED**

The P4 implementation is correctly scoped to the four product pages, but the phase is not accepted yet because three evidence/quality findings must be closed.

## Findings

### 1. Paper Trading references `DataStateBadge` without showing the symbol in the imported public barrel list

`frontend/app/(public)/paper-trading/ClientPage.js` uses `<DataStateBadge state="DEMO" />` while the visible import block does not include `DataStateBadge`.

This must be explicitly resolved and runtime-verified. Do not assume a successful build proves this render path is safe.

### 2. P4 did not add/update focused tests for the four redesigned pages

The P4 commit diff from the accepted P3 baseline contains the four page files but no page test files or test updates. The P4 contract required focused tests covering branding, page structure, CTAs, demo/research truth, SignalField usage, and mobile-safe behavior.

Add focused tests before P4 can be accepted.

### 3. Features page contains live-style wording that can conflict with the public demo/truth contract

Examples include:

- `Live positioning. Real-time signals.`
- `LIVE CHAIN`
- `P&L = LIVE`

These are presented inside the public capability atlas and can be read as the displayed public data being live, while P4 is presentation-only and must not add live market data solely for presentation.

Rewrite these labels so they describe the actual capability without implying the static capability-card values are live data. Keep legitimate product capability claims only where they are accurate and clearly separated from the illustrative visualization state.

## Verified scope

From P3 commit `6d901c4a8e8063daf758ecabe29b3e8f0aeac227` to P4 commit `9b22eec2d0e56387379a8fb19b06e5f044254b6a`, GitHub reports only these changed files:

- `frontend/app/(public)/features/ClientPage.js`
- `frontend/app/(public)/market-intelligence/ClientPage.js`
- `frontend/app/(public)/strategy-lab/ClientPage.js`
- `frontend/app/(public)/paper-trading/ClientPage.js`

No backend, database, broker, OAuth, execution, trading-engine, market-data, financial-calculation, authenticated-app, or other public-page files were included in the P4 diff.

## Required corrective gate

P4 may be accepted after:

1. resolving the `DataStateBadge` import/runtime issue;
2. adding focused tests for all four redesigned pages;
3. removing or clarifying misleading live-style capability-card wording;
4. running the full frontend test suite;
5. running a production build;
6. verifying all seven public routes;
7. browser-verifying the four redesigned pages and their actual narrow viewports;
8. inspecting the final diff;
9. confirming no protected files changed;
10. making no deployment.

P5 is not authorized until this corrective gate passes.
