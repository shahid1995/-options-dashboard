# StrikeNova V1.2 — Signal Field UX Correction 01 Review

**Date:** 2026-09-11
**Status:** CONDITIONAL / CORRECTIVE PATCH REQUIRED
**Base:** `4ebbc37ee3247093b5f90eff65ac31c8d1a0892b`
**Candidate:** `3dc9f1e90d2d10727803271833b7772b341f0849`

## Review result

The four requested Signal Field corrections were implemented in the candidate commit and the commit is correctly one commit after the P8 acceptance record.

GitHub comparison verifies exactly two changed files:

- `frontend/components/public/SignalField.js`
- `frontend/components/public/design-system.test.js`

GitHub Vercel status is `success`.

## Accepted corrections

### 1. Greeks readability

The tightly packed `Δ`, `Γ`, `Θ`, `ν` labels were removed from the main SVG and replaced with a responsive full-name breakdown for Delta, Gamma, Theta and Vega.

### 2. IV semantics

The ambiguous floating arc was replaced by a deterministic implied-volatility-by-strike curve with explicit demo labeling.

### 3. OI semantics

The OI visualization gained a numerical Y-axis, Call/Put labels, a contracts label and a visible baseline.

### 4. Structure connections

Support, Pivot and Resistance received vertical guides linked from their corresponding strike positions.

## Remaining finding

### OI legend / strike-label collision

The candidate places the `OPEN INTEREST · CONTRACTS` text at approximately the same SVG Y coordinate as the strike labels.

From the implementation:

- strike labels render at `pos.y + 18`;
- the strike rail baseline is at `padding.top + plotH / 2`;
- the OI legend text renders at `baseline + 16`.

Therefore the central OI legend can collide with the 25,400 / 25,500 / 25,600 strike labels.

This is a visual regression relative to the explicit goal of clear axis and strike guidance.

## Test coverage observation

The 13 added tests verify presence/content of the new OI semantics, but they do not verify SVG text geometry or collision avoidance.

## Required correction

Move the OI axis label/legend away from the strike-label row.

Preferred options:

1. Place `OPEN INTEREST · CONTRACTS` as a dedicated axis title above or beside the Y-axis; or
2. place the Call/Put legend in a dedicated row outside the strike-label row; or
3. otherwise introduce enough vertical separation to guarantee no collision at all target sizes.

Do not change the accepted visual concept.

Add a focused regression assertion for the chosen layout contract where practical, and verify the actual rendered result in a browser.

## Gate

P8 remains historically accepted, but this post-acceptance UX correction is **NOT YET ACCEPTED**.

Deployment remains blocked pending correction and re-verification.

## Evidence

- Candidate commit resolves on GitHub.
- Candidate is exactly one commit after accepted P8.
- GitHub Vercel status is `success`.
- Scope is limited to SignalField and its tests.
