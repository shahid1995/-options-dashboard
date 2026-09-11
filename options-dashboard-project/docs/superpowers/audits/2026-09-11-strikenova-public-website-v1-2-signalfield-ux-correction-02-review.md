# StrikeNova — Signal Field UX Correction 02 Review

_Last updated: 2026-09-11_

## Result

**PASS / ACCEPTED**

The Signal Field UX Correction 02 candidate `cedea111dd400e72c4a57a468d6d994417a1cc6f` resolves the remaining identified OI legend / strike-label spatial collision.

## Candidate

- Commit: `cedea111dd400e72c4a57a468d6d994417a1cc6f`
- Branch: `feat/strikenova-day35-portfolio-intelligence`
- Direct GitHub parent: `e6603c64cdb08ec4eaca27aac644a76a835bf7fb`
- Historical UX Correction 01 candidate: `3dc9f1e90d2d10727803271833b7772b341f0849`

### History note

The reported parent in the implementation handoff was `3dc9f1e`, but GitHub records `e6603c64` as the direct parent of `cedea11`. The intervening `e6603c64` commit contains the separately approved Day41 core broker-sync architecture work. This does not change the focused Correction 02 diff: the `cedea11` commit itself modifies only the Signal Field component and its focused tests.

## Focused diff review

The Correction 02 commit modifies exactly:

- `frontend/components/public/SignalField.js`
- `frontend/components/public/design-system.test.js`

No backend, database, broker, authentication, execution, trading-engine, market-data, financial-calculation, or authenticated-app files are changed by the Correction 02 commit.

## Findings

### OI legend / strike-label separation

PASS. `OPEN INTEREST · CONTRACTS` is moved into dedicated upper SVG space, with CALL OI / PUT OI labels positioned above the bars and before the strike-label row.

The regression tests isolate the SVG and verify the OI legend labels appear before the strike labels in the rendered markup.

### Greeks

PASS. Correction 01 full-name Greeks remain preserved.

### IV curve

PASS. The implied-volatility-by-strike curve remains preserved and explicitly labeled as demo data.

### Structure connections

PASS. Support, pivot, and resistance guide-line relationships remain preserved.

## Evidence

Implementation-session evidence reported:

- 71 test files / 1,653 tests passed;
- production build succeeded;
- 21 routes generated;
- all seven public routes returned HTTP 200;
- browser checks reported clean at 1440x900, 1280x800, 390x844, and 360x800;
- no console errors;
- no horizontal overflow.

GitHub evidence independently verified:

- candidate commit resolves on GitHub;
- Correction 02 commit contains only the two expected public Signal Field files;
- GitHub branch/history is consistent with the recorded candidate;
- the candidate remains outside the protected backend/data/trading/authenticated-app scope.

The test/build/browser figures above are treated as implementation-reported evidence unless independently reproduced.

## Release state

Historical P8 acceptance remains valid as the V1.2 acceptance record.

Correction 02 is now **accepted as a post-V1.2 maintenance correction**.

Current Signal Field state is **RE-ACCEPTED** for the previously identified UX findings.

Deployment remains a separate explicit decision and has not been performed.

## Protected scope

The public Signal Field correction did not modify:

- backend/FastAPI code;
- database/schema/migrations;
- broker integrations;
- OAuth/session internals;
- execution/trading semantics;
- trading engine;
- market-data architecture;
- financial calculation engines;
- authenticated `(app)` behavior.

## Next action

Return the public-site release candidate to the deployment decision gate. Do not silently append further changes to V1.2; future public UX changes should be separately controlled.
