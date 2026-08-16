# Options Dashboard — Current Project Status

_Last updated: 2026-08-16_

## Current phase

**Phase 5.1 — Portfolio & Journal Analytics**

Status: 🔵 **Next**

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
| Phase 4.1 — IV Analytics | ✅ Complete | Canonical IV units, ATM/curve/skew/term-structure analytics, scenario IV normalization, IV-history foundation |
| Phase 4.2 — Generic Greek/IV Analytics & Statistical Condition Engine | 🔄 Implemented | Generic statistics + market analytics engine, neutral Analytics UI — pending review |
| Phase 5.0 — Paper Trading & Portfolio Foundation | ✅ Complete | Server-authoritative orders/positions/cash/P&L, idempotency, netting, exits, portfolio UI |
| Phase 5.1 — Portfolio & Journal Analytics | 🔵 Next | Not started |
| Phase 6 — Capital & margin analysis | ⏳ Planned | Not started |
| Phase 7 — Journal & performance analytics | ⏳ Planned | Not started |
| Phase 8 — Backtesting | ⏳ Planned | Not started |
| Phase 9 — Strategy scanner | ⏳ Planned | Not started |
| Phase 10 — Custom trading terminal/dashboard | ⏳ Planned | Not started |
| Phase 11 — Automation / alerts | ⏳ Planned | Not started |
| Phase 12 — Multi-broker architecture | ⏳ Planned | Not started |
| Phase 13 — Community | ⏳ Planned | Not started |

## Latest verified implementation commit

`f72b5c0fde522bf5110b125ce310d3685ffb75b4`

This is the verified Phase 5.0 implementation baseline (the Phase 4.1 baseline remains `22f09073749db169905fd2dd06c81c3e37794e0a`, and the Phase 4.0 baseline remains `9ae9966ca358a716c0e53d96203103f5e717e86f`).

The Phase 4.2 implementation is committed in the same commit as its status update but is NOT yet user-verified or ChatGPT-reviewed; it will be recorded here once approved.

## Phase 4.2 implementation

Status: 🔄 Implemented / Pending Review (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (generic analytics + statistical measurements ONLY — no trading methodology, no signals, no buy/sell advice):

- Generic pure statistics module (`frontend/lib/calculations/statistics.js`): rolling mean/median/std-dev/min/max, z-score, mean-rank percentile, neutral 0–100 anomaly measurement — empty/insufficient/constant-history handling, invalid entries ignored safely, nothing fabricated
- Generic market analytics module (`frontend/lib/calculations/marketAnalytics.js`): canonical observation model (symbol + expiry + strike identity, CE/PE sides with price, canonical decimal IV, per-unit delta/gamma/thetaPerDay/vegaPerVolPoint, OI, volume, optional VIX), safe change helpers (absolute/percent/vol-point/direction/ratio — no NaN/Infinity), CE-vs-PE comparisons with dominant side (numeric only), price/IV and price/Greek relationships, Pearson correlation, data-quality status (available/partial/unavailable), neutral condition framework with strictly separate strength vs confidence, multi-expiry isolation (never mixes expiries), VIX handling that never substitutes ATM/average IV
- Historical baselines are NOT collected in this phase: IV/greek z-scores, percentiles and anomaly scores stay null with structured INSUFFICIENT_HISTORY warnings rather than fabricated values
- Neutral Analytics UI (`frontend/app/paper/AnalyticsPanel.js`, new "Analytics" tab): CE vs PE table, price/IV relationship, statistics (unavailable until history exists), expandable IV detail, VIX status, provenance legend (LIVE / DERIVED / STATISTICS) — no buy/sell buttons or signals
- Reuses the existing chain cache and poll architecture — no new polling loop, no new market-data request
- No changes to paper execution, market-hours protection, scenario engine or Greek/IV canonical units

Automated tests (actual):

- Frontend: 461/461 tests passed (21 files) — 70 new (23 statistics + 47 market analytics)
- Backend: 104/104 tests passed
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

## Phase 5.0 verification

Status: ✅ Passed / verified

Implemented (paper trading only — no real-money execution, no margin engine, no signals):

- **Server-authoritative paper trading layer** (`backend/app/services/paper_execution.py` + new `strategy_executions`, `paper_orders`, `positions`, `paper_transactions` tables): the backend now decides fills, position quantities, cash and realized P&L; the frontend only displays backend state
- **Order lifecycle**: PENDING / FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED with a pure transition validator (no CANCELLED→FILLED etc.); execution states PENDING / FILLED / PARTIAL / FAILED / CANCELLED
- **Idempotency**: `client_order_id` unique per user at the execution AND exit boundaries — retries/double-clicks/browser retries return the ORIGINAL result, never a second execution, double-counted cash or duplicate journal record (tested)
- **Fill prices from authoritative market data**: the backend fetches each required expiry chain itself and uses the LTP of each leg's own strike/side; missing chain/strike/quote blocks execution (no stale client values, no cross-expiry fallback)
- **Netted positions**: same user + symbol + expiry + strike + option type net into one row (BUY = +, SELL = −); weighted-average entry on adds; realized P&L on reductions against the average; partial/full exits; reversals; zero quantity marks CLOSED but keeps the record
- **Realized vs unrealized P&L kept separate**: realized is server-computed from exits; unrealized is a mark-to-market display using the existing chain-cache market-data path (never fabricated server-side — stays null without a mark)
- **Cash ledger**: every cash-affecting execution writes a `paper_transactions` record (ENTRY_DEBIT/CREDIT, EXIT_DEBIT/CREDIT); available cash = starting capital + ledger sum — fully auditable and reconcilable
- **Multi-leg grouping**: all orders of one strategy share `strategy_execution_id`; execution is ATOMIC (validated fully before writing, so a failure writes nothing — never a misleading partial success); strategy-grouped portfolio view
- **Exits**: full or partial, idempotent, market-gated, chain-price-resolved, closes journal legs FIFO and closes the legacy journal trade when fully exited
- **Portfolio API**: GET `/paper/portfolio` (summary + strategy groups), GET `/paper/positions`, GET `/paper/orders`, GET `/paper/reconcile`, POST `/paper/executions`, POST `/paper/positions/{id}/exit`, POST `/paper/portfolio/reset`
- **Structured errors** (MARKET_CLOSED, CHAIN_DATA_MISSING, INVALID_QUANTITY, POSITION_NOT_FOUND, INSUFFICIENT_POSITION, INVALID_STATE_TRANSITION, EXECUTION_FAILED) with human-readable messages, no stack traces
- **Concurrency protection**: unique (user_id, client_order_id) constraints as the hard backstop against double fills, with the available-quantity re-check performed inside the same transaction as the position update (SQLite file locking / Postgres transaction isolation serialize writers)
- **User isolation**: all queries scoped by `user_id`; user B can never read or exit user A's positions/orders (tested)
- **Persistence**: SQLAlchemy models + `init_db()` — new tables via `create_all`, plus an idempotent `ensure_column` migration for the two new nullable columns on the pre-existing `trades` table; state survives restart
- **Frontend**: portfolio/positions/cash mirror the backend (localStorage simulator removed as a source of truth); execution and exits call the new idempotent endpoints and reload authoritative state; partial-exit quantity control in the active-positions table; legacy `/paper/fills` + leg-close endpoints retained for backward compatibility
- **Pure frontend helpers** (`frontend/lib/portfolio.js`): idempotency keys, position shaping, mark P&L, exit-quantity validation, structured error messages, request builders

Verification:

- Frontend: 481/481 tests passed
- Backend: 148/148 tests passed
- `npx next build`: passed
- User manual verification: passed
- ChatGPT code review: approved

Overall: ✅ **Complete**

## Phase 5.1 implementation

Status: 🔵 **Next — NOT implemented yet**

Objective — Portfolio & Journal Analytics:

- portfolio dashboard
- realized/unrealized P&L analytics
- position exposure and concentration
- strategy-grouped performance
- trade journal improvements
- win rate
- average winner/loser
- profit factor
- expectancy
- drawdown
- holding duration

## Phase 4.1 verification

Status: ✅ Passed

Implemented:

- Canonical IV unit contract: internal representation = decimal fraction (0.1824 = 18.24%), UI display = percent, 1 volatility point = 0.01
- Pure normalization helpers: normalizeIv / decimalToIvPercent / formatIvPercent / volPointsToDecimal / decimalToVolPoints
- Broker chain IV (percent, e.g. 18.24 = 18.24%) normalized to canonical decimal once, before the pricing model consumes it — fixes the Phase 3 feed-vs-model unit issue
- Per-leg IV analytics resolved against each leg's own expiry chain
- ATM IV using the nearest strike to spot, same strike for CE and PE; ATM average only when both sides exist (partial/unavailable states otherwise)
- IV curve by strike with moneyness (same formula for calls and puts)
- Descriptive IV skew (OTM call/put IV vs ATM IV, in vol points) — analytical only, no signals
- IV term structure across every loaded expiry (each expiry uses its own chain) with a descriptive slope in vol points/day
- IV change tracking (vol-point change + relative %) with missing-observation handling
- Historical IV foundation: IVObservation data model, guarded IV Rank/Percentile helpers (return null below 30 observations), backend `iv_observations` table + repository; collection DISABLED (IV_HISTORY_ENABLED=False) to avoid uncontrolled database growth
- Compact IV Analytics UI: ATM summary, session IV change, ATM skew, IV-vs-strike curve chart, ATM-IV-vs-DTE term structure chart, structured warnings
- No changes to paper execution or market-hours safety

Verification:

- Frontend: 391/391 tests passed (19 files)
- Backend: 104/104 tests passed
- `npx next build`: passed; all routes generated; no type/lint errors
- User verification: passed
- ChatGPT review: approved

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
- Canonical IV analytics (ATM, curve, skew, term structure, change) ✅
- Generic statistics + market analytics (neutral measurements, CE/PE comparisons, relationships, correlation) ✅
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
- Historical IV collection is deliberately not started (Phase 4.1 created the data model/interfaces only); IV Rank/Percentile AND Phase 4.2 z-scores/percentiles/anomaly scores stay unavailable until a reliable sample exists.
- Full capital/margin is not yet modeled.
- Phase 5.0 made the backend authoritative for orders/positions/cash/realized P&L; unrealized P&L remains a mark-to-market display fed by the frontend chain cache (the platform's market-data path).
- Multi-expiry scenario valuation is leg-by-leg modelled and remains approximate for expiry payoff behaviour.
- Legacy journal leg-close on exits is FIFO at whole-leg granularity: for exotic partial netting across multiple executions of the same instrument, journal legs may close with realized scaled to the covered quantity (position math is exact; the journal is a secondary view).
- The legacy `/paper/fills` endpoint still writes only the journal tables (not the authoritative layer); it is retained for backward compatibility and superseded by `/paper/executions`.

## Next phase objective — Phase 5.1

Phase 5.0 (server-authoritative paper trading & portfolio foundation) is ✅ complete. The next milestone is **Phase 5.1 — Portfolio & Journal Analytics**:

- portfolio dashboard
- realized/unrealized P&L analytics
- position exposure and concentration
- strategy-grouped performance
- trade journal improvements
- win rate
- average winner/loser
- profit factor
- expectancy
- drawdown
- holding duration

Phase 5.1 is NOT implemented yet. Wait for the implementation prompt from ChatGPT.

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

Wait for ChatGPT to provide the Phase 5.1 implementation prompt.
