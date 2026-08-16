# Options Dashboard — Current Project Status

_Last updated: 2026-08-16_

## Current phase

**Phase 4.1 — IV Analytics**

Status: 🔵 **Next phase / prompt preparation**

## Overall progress

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Repository audit | ✅ Complete | Existing architecture and responsibilities inspected |
| Phase 0.5 — Strategy/calculation refactor | ✅ Complete | Reusable strategy and calculation domains created |
| Phase 1 — Strategy Builder 2.0 | ✅ Complete | Strategy identity, validation, leg management, review-before-trade added |
| Phase 1.1 — Risk metrics correction | ✅ Complete | Unlimited-profit handling for Reward/Risk and Premium ROI corrected |
| Phase 2 — Professional Payoff & Risk Engine | ✅ Complete | Chain-independent theoretical payoff, risk tails, exact same-expiry breakevens, S >= 0 handling |
| Phase 2.1 — Multi-expiry chain handling | ✅ Complete | Required-expiry detection, auto-loading, expiry-specific pricing and execution chain gate |
| Phase 3 — Scenario & Time Analysis | ✅ Complete | Dependency-free Black-Scholes-style model, scenario engine, scenario matrices, modelled Greeks and minimal Scenario UI |
| Phase 4.0 — Greek Foundation & Live-vs-Model Analytics | ✅ Complete | Canonical Greek units, live/model comparison, per-leg exposure, contributions and Scenario-panel integration |
| Phase 4.1 — IV Analytics | 🔵 Next | Prompt preparation / implementation not started |
| Phase 4.2 — Greek/IV Divergence & Advanced Signals | ⏳ Planned | Not started |
| Phase 5 — Paper trading / portfolio upgrade | ⏳ Planned | Not started |
| Phase 6 — Capital & margin analysis | ⏳ Planned | Not started |
| Phase 7 — Journal & performance analytics | ⏳ Planned | Not started |
| Phase 8 — Backtesting | ⏳ Planned | Not started |
| Phase 9 — Strategy scanner | ⏳ Planned | Not started |
| Phase 10 — Custom trading terminal/dashboard | ⏳ Planned | Not started |
| Phase 11 — Automation / alerts | ⏳ Planned | Not started |
| Phase 12 — Multi-broker architecture | ⏳ Planned | Not started |
| Phase 13 — Community | ⏳ Planned | Not started |

## Latest verified implementation commit

`9ae9966ca358a716c0e53d96203103f5e717e86f`

This is the verified Phase 4.0 implementation baseline.

## Phase 4.0 verification

Status: ✅ Passed / verified by user

Implemented:

- Canonical Greek unit contract:
  - Delta: exposure change per 1 underlying point
  - Gamma: exposure change in Delta per 1 underlying point
  - Theta: ₹ exposure change per calendar day
  - Vega: ₹ exposure change per 1 volatility point
- Live broker/chain Greeks kept separate from model Greeks
- Model Theta converted from per-year to per-day
- Model Vega converted from per 1.00 volatility fraction to per 1 vol point
- Explicit ZERO vs UNAVAILABLE handling
- Signed model-minus-live differences
- Per-leg Greek analytics and strategy totals
- Greek contribution/concentration view
- Own-expiry live/model Greek handling for multi-expiry strategies
- Scenario-panel live-vs-model Greek comparison using the existing scenario result without duplicate pricing calculations
- No changes to paper execution or market-hours safety

User-reported test/build verification:

- Frontend: 355 tests passed / 0 failed across 18 files
- Backend: 99 tests passed / 0 failed
- `npx next build`: passed; all 6 routes generated; no type/lint errors

## Phase 3 verification

Status: ✅ Passed

Implemented:

- Dependency-free Black-Scholes-style European pricing engine
- Normal PDF/CDF and d1/d2 helpers
- T=0 intrinsic-value handoff to Phase 2 payoff
- Edge-safe low-volatility and invalid-input handling
- Model-consistent Delta/Gamma/Theta/Vega
- Reusable scenario engine
- Spot / IV / time / rate / dividend scenarios
- Combined scenarios
- Multi-expiry leg-by-leg modelling using each leg's own expiry and IV
- Structured scenario warnings
- Scenario P&L vs entry
- Scenario change vs current live mark
- Spot×IV, Spot×Time and IV×Time scenario matrices
- Minimal Strategy Builder Scenario UI
- LIVE vs MODELLED separation
- Scenario analysis isolated from paper execution/positions/cash/market gate

User-reported verification:

- Frontend: 323 tests passed across 17 files
- Backend: 99 tests passed
- JSX parse check: PASS
- Invalid scenario spot returns null totals instead of misleading ₹0

## Phase 2.1 verification

Status: ✅ Passed

Verified behavior:

- Required expiry detection: PASS
- Secondary expiry auto-load: PASS
- Every required expiry polled/freshened: PASS
- Each leg priced from its own expiry chain: PASS
- Missing required chain blocks execution: PASS
- Market CLOSED still blocks even when chains are available: PASS

## Phase 2 verification

Status: ✅ Passed

Verified manually:

- Long Call: PASS
- Long Put: PASS
- Bull Call Spread: PASS
- Short Put: PASS
- Mixed-expiry warning: PASS

## Current architecture status

### Working foundations

- Strategy domain ✅
- Strategy identity ✅
- Strategy validation ✅
- Chain-independent expiry payoff/risk ✅
- Scenario/time pricing engine ✅
- Live-chain Greeks ✅
- Canonical live/model Greek analytics ✅
- Central strategy calculator ✅
- Strategy templates ✅
- Paper trading ✅
- Market-hours protection ✅
- Multi-expiry chain handling ✅
- Journal/database foundation ✅
- Frontend unit tests ✅

### Current architecture concerns

- `frontend/app/paper/page.js` remains a large orchestration component; future domain logic should stay outside it.
- Live Greek conventions are currently based on the documented Upstox/Indian-market convention and should be revalidated if the data feed changes.
- Phase 3/4 model IV consumes chain IV as provided; feed-percent vs model-decimal reconciliation is a Phase 4.1 responsibility.
- Full capital/margin is not yet modeled.
- Backend/database should become increasingly authoritative for persistent trading state.
- Multi-expiry scenario valuation is leg-by-leg modelled and remains approximate for expiry payoff behaviour.

## Current Phase 4.1 objective

Build IV analytics on top of the existing expiry-specific chain data and canonical Greek foundation.

Planned goals:

- Explicit IV unit normalization between live feed and model decimal representation
- ATM IV and per-leg IV views
- IV term structure by expiry
- IV skew by strike/moneyness
- IV percentile/rank only where enough historical observations exist
- IV change tracking when reliable prior observations are available
- Volatility regime views
- Volatility-shock inputs for the existing Scenario engine
- Clear separation between live IV and model/scenario IV

## Permanent project constraints

- Paper trading only for the current product stage.
- User-authorized broker/data architecture is planned; current broker integration is Upstox.
- Broker secrets remain backend-only.
- Do not centrally redistribute broker market data unless applicable permissions/terms allow it.
- Prefer genuinely free/open-source/self-hostable tooling; avoid trial/credit-dependent core services.
- Every important financial rule should have automated tests.
- Distinguish live broker data from modelled values in the UI and calculation layer.

## Current FreeBuff workflow

1. ChatGPT designs the phase and writes the implementation prompt.
2. User submits the prompt to FreeBuff.
3. FreeBuff implements one milestone and commits to GitHub.
4. User manually tests the application.
5. ChatGPT inspects the actual GitHub diff/code.
6. ChatGPT approves or supplies a corrective prompt.
7. Only after approval does the project move to the next phase.

## Next action

**User:** Wait for the Phase 4.1 prompt from ChatGPT. Do not ask FreeBuff to implement Phase 4.1 until the prompt is provided.
