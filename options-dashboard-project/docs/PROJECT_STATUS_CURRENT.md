# StrikeNova — Current Project Status Snapshot

_Last updated: 2026-09-11_

> This file is the current Project Control Center status snapshot. `docs/PROJECT_STATUS.md` remains the historical engineering ledger. This snapshot records accepted phase history, current release state, and controlled maintenance changes.

## Product identity

**Public product brand:** StrikeNova  
**Public visual direction:** StrikeNova Signal Field  
**Core product positioning:** Options intelligence for structured decisions.

## Current workstreams

| Workstream | Status | Current position | Next controlled action |
|---|---|---|---|
| Core platform / base architecture | 🔄 Ongoing | Continues independently. Day41 broker-sync architecture work was committed separately on the shared feature branch between public-site maintenance commits. | Continue approved architecture/review work independently. |
| Public Website V1.1 | ✅ Complete | Historical seven-route V1.1 baseline. | Preserve as historical baseline. |
| Public Website V1.2 — Signal Field | ✅ DEPLOYED | P0–P8 accepted historically. Signal Field UX Correction 01 and 02 reviewed and accepted. Approved candidate `cedea111dd400e72c4a57a468d6d994417a1cc6f` was promoted to Vercel production, then the committed auth-handoff correction `31563dad542651f47ab53d1106748a0ff90908c4` was promoted to the same public production project. | Monitor production; future changes use a new controlled maintenance/change-set record. |
| Public design system | ✅ Complete | P1 semantic design system and motion foundation accepted. | Preserve/reuse. |
| Signal Field visualization | ✅ UX CORRECTION 01 + 02 ACCEPTED | Greeks, IV-by-strike curve, OI scale/legend, and strike-connected structure guides are implemented. Final OI legend/strike-label spacing correction accepted and deployed. | Preserve/reuse. |
| Public homepage redesign | ✅ P3 accepted | `/` is the flagship StrikeNova public experience. | Preserve. |
| Public product pages | ✅ P4 accepted | Features, Market Intelligence, Strategy Lab and Paper Trading redesigned. | Preserve. |
| Public story pages | ✅ P5 accepted | How It Works and About redesigned. | Preserve. |
| Public navigation/cohesion | ✅ P6 accepted | Header, footer, metadata, active states, mobile menu and public branding/truth sweep completed. | Preserve. |
| Public hardening | ✅ P7 accepted | Accessibility, responsive, browser/runtime and performance hardening accepted. | Preserve. |

## V1.2 control documents

### Design specification
`docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md`  
Commit: `db2b7c4582c749a9864e638127c0a93fdc7f1284`

### Master implementation plan
`docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md`  
Commit: `33d8488be096e8d3c019c0c43b09fec0dd6d0b98`

### P8 final acceptance audit
`docs/superpowers/audits/2026-09-11-strikenova-public-website-v1-2-p8-final-acceptance.md`  
Historical acceptance commit: `4ebbc37ee3247093b5f90eff65ac31c8d1a0892b`

### Signal Field UX Correction 01
`docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-signalfield-ux-correction.md`  
Candidate: `3dc9f1e90d2d10727803271833b7772b341f0849`

### Signal Field UX Correction 01 review
`docs/superpowers/audits/2026-09-11-strikenova-public-website-v1-2-signalfield-ux-correction-review.md`  
Review commit: `15c1b7e3f1b281052ef1952d0a7788351d8c0786`

### Signal Field UX Correction 02
`docs/superpowers/plans/2026-09-11-strikenova-public-website-v1-2-signalfield-ux-correction-02.md`  
Plan commit: `95c7189fe6ba4dcaf2f3557aa1b7a58406a39e45`

### Signal Field UX Correction 02 review
`docs/superpowers/audits/2026-09-11-strikenova-public-website-v1-2-signalfield-ux-correction-02-review.md`  
Acceptance review commit: `60e866f17fb08ba5799c854d14505bcc288e9e25`

## Phase implementation records

| Phase | Implementation / acceptance commit | Status |
|---|---|---|
| P0 — Baseline | `dd271e109d1e72f3e2aaa5b860fe02e74424dc73` | ✅ PASS |
| P1 — Design system | `1eece4028ae05ed9b610c859e6c0d542e615a521` + corrective `17492609dfb031f2b23e6566798e4c787caba669` | ✅ ACCEPTED |
| P2 — Signal Field | `9f86412345cd49c25351491d6541a7aaba9950e2` | ✅ ACCEPTED |
| P3 — Homepage | `6d901c4a8e8063daf758ecabe29b3e8f0aeac227` | ✅ ACCEPTED |
| P4 — Product pages | `9b22eec2d0e56387379a8fb19b06e5f044254b6a` + corrective `c008386d0ac2d1800f675f1cb7570de7c2df67fe` | ✅ ACCEPTED |
| P5 — Story pages | `4a2eda84589609da54f151f80ae87289acda3f1e` | ✅ ACCEPTED |
| P6 — Navigation/cohesion | `665a3adc593bfd9beeac1d05e36734584910f5b4` | ✅ ACCEPTED |
| P7 — Hardening | `cb0c2621cf8ded658b611d8e506042e0d4349260` | ✅ ACCEPTED |
| P8 — Final acceptance | `4ebbc37ee3247093b5f90eff65ac31c8d1a0892b` | ✅ PASS / RELEASE-READY (historical) |
| UX Correction 01 | `3dc9f1e90d2d10727803271833b7772b341f0849` | ✅ ACCEPTED after review |
| UX Correction 02 | `cedea111dd400e72c4a57a468d6d994417a1cc6f` | ✅ ACCEPTED after review |
| Auth Handoff Correction | `31563dad542651f47ab53d1106748a0ff90908c4` | ✅ ACCEPTED — production deployed |

## Post-V1.2 Signal Field correction state

**Current Signal Field candidate:** `cedea111dd400e72c4a57a468d6d994417a1cc6f`

Correction 02 resolves the final identified layout collision by placing the `OPEN INTEREST · CONTRACTS` title and CALL/PUT OI labels in dedicated upper SVG space, separate from the strike-label row. Focused tests verify the legend labels precede strike labels in the rendered SVG structure. Browser verification was reported clean at 1440×900, 1280×800, 390×844 and 360×800.

GitHub independently confirms the correction commit modifies only:

- `frontend/components/public/SignalField.js`;
- `frontend/components/public/design-system.test.js`.

### History integrity note

GitHub records `e6603c64cdb08ec4eaca27aac644a76a835bf7fb` as the direct parent of Correction 02. This is a separately committed Day41 core broker-sync architecture change that landed between Correction 01 and Correction 02 on the shared feature branch. The Correction 02 commit itself remains scoped to the two Signal Field public files and did not modify the core architecture.

This history is preserved as-is; no force-rewrite or hidden rebase is authorized.

## Current release state

**Historical P8 V1.2 acceptance:** RELEASE-READY.

**Post-V1.2 Signal Field UX Correction 01:** ACCEPTED.

**Post-V1.2 Signal Field UX Correction 02:** ACCEPTED.

**Production deployment:** COMPLETE.

**Public production deployment ID:** `dpl_7ZfCychuzJ1UgCZuudiCAxF6FCxt`

**Public production URL:** https://options-dashboard-sigma-coral.vercel.app

**Public production candidate SHA:** `31563dad542651f47ab53d1106748a0ff90908c4`

**Public production state:** READY.

**Authenticated application:** Separate Vercel project `frontend`, serving `https://frontend-zeta-gray-75.vercel.app` and its authenticated routes.

**NEXT_PUBLIC_APP_URL:** `https://frontend-zeta-gray-75.vercel.app`

**NEXT_PUBLIC_API_URL:** `https://options-dashboard-production-fb47.up.railway.app`

The committed auth-handoff correction is present in the public production deployment. `AuthModal.js` and `PublicLayout.js` use `NEXT_PUBLIC_APP_URL` and place the returned `session_id` in the URL fragment for cross-origin navigation to `/dashboard`.

### End-to-end auth evidence status

The code path and production deployment were independently verified. The exact real-user email/password and Google OAuth transactions were **not executed in the verification environment because test credentials/OAuth test flow were not available**. Therefore they are recorded as **not end-to-end tested**, not as failed.

The authenticated application's existing fragment session-capture mechanism remains the target handoff contract.

The public and authenticated Vercel projects remain intentionally separate.

## Authentication handoff review

`docs/superpowers/audits/2026-09-11-strikenova-production-auth-handoff-review.md`

The earlier review correctly blocked the old `cedea11` public deployment because it lacked the committed cross-origin handoff. That finding is now superseded by the committed `31563dad542651f47ab53d1106748a0ff90908c4` correction and its production promotion.

## Production deployment evidence

Vercel independently confirms production deployment `dpl_7ZfCychuzJ1UgCZuudiCAxF6FCxt` is `READY`, targets production, and points to GitHub commit `31563dad542651f47ab53d1106748a0ff90908c4`. It was promoted from preview deployment `dpl_DpVwYoeDM3eFNQTh3T9xuBMdhDhZ`.

GitHub confirms commit `31563dad542651f47ab53d1106748a0ff90908c4` contains the intended auth-handoff changes in `AuthModal.js`, `PublicLayout.js`, and its focused auth tests.

Vercel runtime-error aggregation for the public project reports no runtime errors in the selected verification window.

## Strict no-touch boundary

The public V1.2 redesign and public auth-handoff correction did not intentionally modify:

- backend/FastAPI business logic;
- database/schema/migrations;
- broker integrations;
- execution/trading semantics;
- trading engine;
- market-data architecture;
- financial calculation engines;
- authenticated application business logic.

The authenticated app remains a separate deployment target. The public correction only establishes the cross-origin navigation contract needed to reach it.

## Operating rule after V1.2

The P0–P8 redesign workstream is closed historically.

Post-acceptance public UX and integration corrections are separately controlled maintenance changes and do not silently alter the P0–P8 acceptance history.

Future public changes should start as a new controlled maintenance/change-set record.
