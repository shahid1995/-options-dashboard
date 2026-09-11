# StrikeNova V1.2 — P4 Corrective Handoff

## Status

**P4 implementation review: CONDITIONAL — corrective patch required.**

This is a narrow repair pass. Do not redesign the pages again.

## Authority

P4 product-page plan:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-p4-product-pages.md

P4 review audit:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-11-strikenova-public-website-v1-2-p4-review.md

Current status:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## Base implementation

P4 commit:
`9b22eec2d0e56387379a8fb19b06e5f044254b6a`

Branch:
`feat/strikenova-day35-portfolio-intelligence`

## Finding 1 — resolve and verify `DataStateBadge`

File:
`frontend/app/(public)/paper-trading/ClientPage.js`

The component renders `DataStateBadge`, but the visible import block does not show that symbol.

Required:

- Resolve the import/reference correctly using the existing public design-system export.
- Do not create a duplicate badge component.
- Do not change the auth modal or page architecture.
- Add a focused runtime/render test that actually exercises the relevant Paper Trading path enough to prove the symbol resolves.
- A successful compilation alone is not sufficient evidence.

## Finding 2 — add required focused page tests

The P4 diff contains no page test updates. Add focused tests for all four redesigned pages.

Required minimum coverage:

### Features
- StrikeNova branding
- Capability Atlas sections
- CTA destinations
- research-direction labeling
- no legacy visible product branding

### Market Intelligence
- SignalField rendered
- core analytical dimensions represented
- demo labeling
- research-direction labeling
- accessible visualization presence

### Strategy Lab
- Strategy Forge structure
- payoff/risk content
- illustrative/demo labeling
- CTA destination
- mobile-safe composition contract where practical

### Paper Trading
- Rehearsal sequence
- simulated/demo messaging
- positions/orders presentation
- absence of live execution dependency
- responsive-safe card composition
- DataStateBadge/render path

Tests must be deterministic and must not require network, broker credentials, authentication, or live data.

## Finding 3 — remove misleading live-style capability-card wording

File:
`frontend/app/(public)/features/ClientPage.js`

Current examples include:

- `Live positioning. Real-time signals.`
- `LIVE CHAIN`
- `P&L` with value `LIVE`

These can be interpreted as the public capability-card data itself being live. P4 is presentation-only and must not introduce live market-data presentation solely for marketing visuals.

Required:

- Keep accurate capability claims where they describe the actual product.
- Rewrite the metric/card labels so they do not imply that the static public-card value is live data.
- Prefer capability wording such as `STREAMING`, `PER-STRIKE`, `TRACKED`, `SIMULATED`, or another accurate label supported by the actual product contract.
- Do not replace one misleading live claim with another unsupported claim.
- Numerical demo content must remain clearly demo/illustrative.

## Scope

Only the files required to close the three findings may change.

Expected scope:

- `frontend/app/(public)/paper-trading/ClientPage.js`
- `frontend/app/(public)/features/ClientPage.js`
- focused public page test files under the relevant public route directories

Do not modify:

- homepage `/` except if a shared-component bug absolutely requires it;
- `/how-it-works`;
- `/about`;
- backend;
- database/schema/migrations;
- broker integrations;
- OAuth/session logic;
- execution/trading engine;
- market-data architecture;
- financial-calculation engines;
- authenticated `(app)` routes;
- deployment configuration.

## Verification

Run fresh:

1. full frontend test suite;
2. production Next.js build;
3. all seven public routes;
4. browser verification of all four P4 pages;
5. actual effective viewport checks at 1440×900, 1280×800, 390×844, and 360×800;
6. runtime check confirming Paper Trading `DataStateBadge` renders;
7. console-error check;
8. final diff inspection.

Report actual results.

## Git

Recommended commit:
`fix(public): close P4 review findings`

Do not deploy.

## Stop condition

After corrective verification, STOP.

Do not start P5.
Do not redesign story pages.
Do not redesign navigation/footer.
