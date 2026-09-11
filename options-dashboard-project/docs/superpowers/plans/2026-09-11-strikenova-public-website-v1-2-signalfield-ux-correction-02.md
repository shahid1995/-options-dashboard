# StrikeNova Public Website V1.2 — Signal Field UX Correction 02

## Objective

Close the remaining post-V1.2 Signal Field visual defect identified during Project Control Center review of UX Correction 01.

This is a micro-correction only. Do not redesign Signal Field or reopen the V1.2 page workstream.

## Base

P8 historical acceptance candidate:

`4ebbc37ee3247093b5f90eff65ac31c8d1a0892b`

UX Correction 01 candidate:

`3dc9f1e90d2d10727803271833b7772b341f0849`

Branch:

`feat/strikenova-day35-portfolio-intelligence`

## Finding

`OPEN INTEREST · CONTRACTS` is positioned approximately at the same vertical level as the strike labels in `SignalField.js`.

This can cause visual collision between the OI legend and strike labels.

The existing tests verify that the legend exists, but do not verify its spatial relationship to the strike-label row.

## Required correction

Move the OI axis title/legend into dedicated vertical space so the hierarchy is clearly separated:

1. OI axis / scale title
2. OI bars and Call/Put legend
3. strike labels
4. support/pivot/resistance structure annotations

Do not solve this with arbitrary global overflow suppression.

Prefer a stable SVG layout change that reserves an intentional row for the axis title/legend.

The exact geometry is implementation-dependent, but the final rendered output must never place the OI title/legend on top of the strike labels.

## Requirements

- preserve Call OI / Put OI semantics;
- preserve `OPEN INTEREST · CONTRACTS` wording or an equivalent explicit label;
- preserve the Y-axis scale;
- preserve strike labels;
- preserve structure guide connections;
- preserve the new IV-by-strike curve;
- preserve the readable Greek breakdown;
- preserve deterministic illustrative data;
- preserve accessibility semantics;
- preserve reduced-motion behavior;
- no network/live-data dependency.

## Responsive requirement

Verify effective browser dimensions:

- 1440 × 900
- 1280 × 800
- 390 × 844
- 360 × 800

The OI axis/legend must remain separated from strike labels at every viewport.

## Tests

Update `frontend/components/public/design-system.test.js` with a focused regression contract for the chosen layout implementation where practical.

At minimum retain tests proving:

- OI axis title exists;
- Call OI / Put OI semantics exist;
- strike labels exist;
- the previous UX Correction 01 contracts remain intact.

Where geometry itself cannot be reliably proven in static markup, rely on browser verification and do not create misleading pixel-coordinate unit tests.

## Browser verification

Use a real browser and visually inspect SignalField at all four target viewports.

Check specifically:

- zero OI-label/strike-label overlap;
- zero Greek/OI collision;
- IV curve remains clear;
- structure guides remain connected;
- no horizontal overflow;
- no console errors.

## Scope

Expected files only:

- `frontend/components/public/SignalField.js`
- `frontend/components/public/design-system.test.js`

Do not modify:

- backend;
- database/schema/migrations;
- broker integrations;
- OAuth/session;
- execution/trading engine;
- market-data architecture;
- financial calculations;
- authenticated `(app)` routes;
- other public page bodies;
- global navigation/footer.

## Git

Recommended commit:

`fix(public): separate Signal Field OI legend from strike labels`

Do not force-push.

Do not deploy.

## Final report

Return:

- exact commit SHA;
- parent SHA;
- files changed;
- tests and counts;
- build result;
- all seven public routes;
- browser result for all four viewports;
- explicit OI/strike overlap result;
- console result;
- protected-scope verification;
- deployment status.

Then STOP and return the evidence for Project Control Center review.
