# Options Dashboard — Current Project Status

_Last updated: 2026-08-16_

## Current phase

**Phase 6.1 — Broker Margin Integration (Upstox)**

Status: 🔄 **Implemented / Pending Review**

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
| Phase 5.1 — Portfolio & Journal Analytics | ✅ Complete | Server-authoritative portfolio analytics: summary, performance, realized equity curve, drawdown, strategy groups, grouped journal |
| Phase 5.2 — Bulk Paper Position Exit & Exit-All Safety | 🔄 Implemented | Server-authoritative EXIT STRATEGY + EXIT ALL, atomic pre-validation, idempotent replay, strategy-grouped outcomes, double-confirmation UI — pending review |
| Phase 6.0 — Capital & Margin Foundation | 🔄 Implemented | Source-classified capital figures, broker margin abstraction, estimated capital (premium basis), capital summary — implemented & committed, pending final market-hours verification |
| Phase 6.1 — Broker Margin Integration (Upstox) | 🔄 Implemented | Real Upstox funds + whole-strategy margin APIs behind MarginProvider, broker source/status/timestamp, caching — pending review |
| Phase 6.2 — Analytical Margin Model | 🔵 Next | Not started |
| Phase 7 — Journal & performance analytics | ⏳ Planned | Not started |
| Phase 8 — Backtesting | ⏳ Planned | Not started |
| Phase 9 — Strategy scanner | ⏳ Planned | Not started |
| Phase 10 — Custom trading terminal/dashboard | ⏳ Planned | Not started |
| Phase 11 — Automation / alerts | ⏳ Planned | Not started |
| Phase 12 — Multi-broker architecture | ⏳ Planned | Not started |
| Phase 13 — Community | ⏳ Planned | Not started |

## Latest verified implementation commit

`3d032f2` — Phase 5.1: portfolio and journal analytics (verified).

Phase 6.0 was committed via the Changes panel: implementation `01d008e` + status update `45b459e` (pending final market-hours verification).

Prior baselines: Phase 5.0 `f72b5c0fde522bf5110b125ce310d3685ffb75b4`, Phase 4.1 `22f09073749db169905fd2dd06c81c3e37794e0a`, Phase 4.0 `9ae9966ca358a716c0e53d96203103f5e717e86f`.

The Phase 4.2 implementation is committed but was never user-verified or ChatGPT-reviewed; it is superseded by later phases.

The Phase 6.1 implementation is NOT committed yet: it exists only in the working tree (per the phase's commit/deployment rules) and will be committed by the project owner after review.

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

Status: ✅ Complete (verified and approved; superseded by Phase 6.0)

Implemented (portfolio & journal analytics ONLY — no real-money trading, no margin engine, no signals, no backtesting):

- **Performance analytics layer** (`backend/app/services/performance.py`): pure, independently-tested helpers for win/loss/breakeven classification, win rate, average winner/loser, profit factor (never Infinity), expectancy, largest win/loss, win/loss streaks, holding duration (seconds + user-friendly label, avg/median/shortest/longest), realized equity curve, drawdown (current/max + %), daily realized P&L, strategy grouping and position exposure
- **Server-authoritative source of truth**: a strategy execution counts as ONE completed trade once ALL its positions are closed; its realized P&L = the SUM of its positions' `realized_pnl` (positions aggregate partial AND full exits exactly; legacy journal rows are never double-counted). Open strategies, pending/rejected/cancelled orders and individual legs are never counted as trades
- **Correctness fix (proven by a regression test)**: `execution.realized_pnl` now accumulates on PARTIAL exits too (previously only full exits), so the execution total always equals the sum of its positions' realizations
- **Canonical summary**: starting capital, available cash (cash-ledger based), open exposure at entry value (explicitly NOT margin), realized/unrealized split, total P&L, return % (totalPnl / startingCapital × 100 only when startingCapital > 0 — never called ROI/margin)
- **Unrealized P&L is never fabricated**: stays `null` server-side (no live marks); `current_marks` and `historical_unrealized` are reported as `unavailable` in `data_quality`; the frontend overlays its chain-cache marks for display (the platform's existing market-data path)
- **REALIZED equity curve**: equity = starting capital + cumulative realized P&L, dated by each trade's exit day, with an explicit baseline point; labeled "Realized Equity Curve" (never presented as total historical equity); drawdown derived from it
- **Strategy-level analytics**: one row per strategy tag (reuses existing strategy identity) — trades, wins/losses, win rate, total/avg P&L, profit factor, expectancy; multi-leg executions appear as ONE journal row with legs underneath
- **Position analytics**: long/short/total exposure at entry value server-side; mark-based market value + concentration (mark value / total absolute open exposure, measurement only) computed client-side where marks exist
- **API**: ONE authoritative `GET /paper/analytics` (summary + performance + equity curve + drawdown + daily P&L + strategies + positions + journal + data quality + applied filters) with optional `date_from` / `date_to` / `strategy` filters applied server-side; read-only and always available regardless of market status; reuses Phase 5.0 reconciliation and surfaces `PORTFOLIO_DATA_INCONSISTENT` warnings without silently fixing data
- **Frontend**: compact Portfolio Analytics dashboard (`frontend/app/paper/PortfolioAnalyticsPanel.js`) — summary, performance, drawdown, realized equity curve (Recharts, no new charting library), strategy performance table, mark-based exposure/concentration chips, grouped journal (Date / Strategy / Entry / Exit / Duration / P&L / Result with WIN/LOSS/BREAKEVEN badges and date/P&L/duration sorting); pure display helpers in `frontend/lib/analytics.js` (no formulas duplicated client-side); empty states show "No completed trades" instead of 0%/NaN/Infinity
- No changes to paper execution semantics, market-hours protection, chain handling, Greek/IV analytics, reconciliation or the Phase 5.0 cash ledger

Verification:

- Frontend: 502/502 tests passed (22 files)
- Backend: 195/195 tests passed
- `npx next build`: passed; all routes generated; no type/lint errors
- User manual verification: passed
- ChatGPT code review: approved
- Implementation commit: `3d032f2`

Overall: ✅ **Complete**

## Phase 5.2 implementation

Status: 🔄 Implemented / Pending Review (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (bulk paper position exit ONLY — no redesign of the Phase 5.0 execution model, no real-money trading, no new trading signals, no changes to Phase 6.0/6.1 capital calculations):

- **Two distinct server-authoritative operations**:
  - `POST /paper/executions/{strategy_execution_id}/exit-all` — EXIT STRATEGY: closes every OPEN position of ONE strategy execution (all legs share the strategy; multi-leg strategies are treated as one logical strategy exit, no duplicate strategy records)
  - `POST /paper/positions/exit-all` — EXIT ALL: closes every OPEN position of the authenticated user across all strategies + standalone positions
- **Atomicity**: market OPEN re-checked at execution time, then ALL required (symbol, expiry) chains are fetched once and every position's own strike/side LTP is resolved BEFORE any mutation — a missing chain/quote raises `BULK_EXIT_CHAIN_DATA_MISSING` (409) and NO position is closed (no partial closure from a pre-validation failure)
- **ONE authoritative exit path**: every position exits through the existing trusted `exit_position()` (same P&L/cash/journal logic as the single-position endpoint, with a `commit=False` mode) and the whole operation commits in ONE database transaction; the single-position endpoint `POST /paper/positions/{id}/exit` is unchanged
- **Idempotency**: the whole bulk operation is keyed by `client_order_id` (stored in a new `bulk_exit_records` table); a replay returns the ORIGINAL result (`duplicated: true`) — no second exit orders, no duplicate cash-ledger entries, no duplicate journal rows (including the NO_POSITIONS case)
- **Result contract**: `{ execution_id, scope: STRATEGY | ACCOUNT, status: SUCCESS | NO_POSITIONS | FAILED | PARTIAL, requested_count, exited_count, failed_count, total_realized_pnl, cash_change, positions[], groups[], errors[] }` with per-position EXITED / ALREADY_CLOSED / FAILED outcomes and strategy-grouped summary (strategy tag + counts + realized per group); PARTIAL is only possible for a true execution-time failure after pre-validation passed (e.g. a concurrent individual exit winning the race for one position — reported ALREADY_CLOSED, never re-closed)
- **Concurrency**: the existing per-position quantity re-check inside the same transaction protects Exit All vs Exit All and Exit All vs individual Exit; the loser sees ALREADY_CLOSED (bulk) or the existing `INSUFFICIENT_POSITION` (individual); per-position keys are namespaced under the bulk key (`<bulk_key>:pos-<id>`)
- **Strategy completion correctness fix**: `StrategyExecution.exit_at` is now stamped only when ALL positions of the execution are closed (previously the first leg closing stamped it); analytics counts exactly ONE completed trade per fully-exited strategy with the exact realized sum (regression-tested)
- **Frontend** (`app/paper/page.js` + new `app/paper/BulkExit.js`): prominent but safe EXIT ALL button in the Active Positions header (disabled + "No open positions" when empty — no API call), a strategy-grouped strip with one EXIT STRATEGY per open strategy, double-confirmation modals (EXIT STRATEGY shows Positions / Approximate current value / Current unrealized P&L — informational only; EXIT ALL shows open positions/strategies), an EXITING… disabled state, and an EXIT COMPLETE / EXIT PARTIALLY COMPLETED / EXIT FAILED result banner listing failed positions; after success the page refreshes portfolio, positions, analytics, capital and journal from the existing authoritative endpoints; pure display helpers in `frontend/lib/portfolio.js` (`buildBulkExitRequest`, `openStrategyGroups`, `bulkExitDisplay`)
- **No changes** to capital formulas (Phase 6.0/6.1), market-hours protection, chain handling, Greek/IV analytics, reconciliation, or the single-position exit calculation; the Recharts `Line` import fix in `PortfolioAnalyticsPanel.js` is preserved (equity curve renders after bulk-exit refreshes)

Automated tests (actual):

- Backend: 287/287 tests passed — 29 new (`tests/test_bulk_exit.py`: single-position exit unchanged, exit strategy, exit account, multiple strategies, standalone, no positions, market closed/unknown, missing chain/quote, idempotent replay, duplicate Exit All, individual+bulk concurrency race → PARTIAL + ALREADY_CLOSED, cash ledger exactly-once, realized P&L aggregation, journal without duplicates, strategy completion, user isolation, partial reporting, reconcile/portfolio/analytics consistency)
- Frontend: 541/541 tests passed (26 files) — 20 new (bulk-exit helpers + BulkExit modal/result banner states)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

## Phase 6.0 implementation

Status: 🔄 Implemented / Pending Review (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (capital & margin foundation ONLY — no SPAN calculator, no exposure-margin calculator, no Return-on-Capital metric, no real-money execution):

- **Capital domain** (`backend/app/services/capital.py`): five concepts kept strictly separate — PREMIUM OUTLAY (gross premium paid on long entry legs, CALCULATED from the server-authoritative Phase 5.0 fill records), BROKER MARGIN (BROKER_REPORTED only; unavailable — never invented), ESTIMATED CAPITAL (model-derived; Phase 6.0 supports only the deterministic premium basis for defined-debit strategies), BROKER AVAILABLE FUNDS (BROKER_REPORTED only), and PAPER CAPITAL (paper starting capital + paper available cash derived from the Phase 5.0 cash ledger, never renamed as broker funds)
- **Source classification (§3/§4/§12)**: every figure carries its source — BROKER_REPORTED | ESTIMATED | CALCULATED | UNAVAILABLE — and its availability status — available | partial | unavailable; missing values are `null`, never 0; NaN/Infinity/negative values never become valid capital figures
- **Estimated capital (§8/§9)**: defined-debit strategies get the strategy's NET premium paid at entry labeled "Estimated Capital — Premium Basis" (whole-strategy `entry_net`, not per-leg sums); credit/naked strategies return `unavailable` — premium received is NOT capital required, and no valid analytical model exists yet
- **Broker provider abstraction (§6/§7/§18)**: `MarginProvider` interface with `get_capital_snapshot(context)` receiving the authenticated user's FULL open strategy set (multi-leg strategies are ONE capital unit, never per-leg margin numbers summed); the current Upstox integration exposes no margin/funds endpoint, so the default provider honestly returns BROKER_REPORTED = unavailable; a `StaticMarginProvider` test/example implementation proves the abstraction surfaces real broker values without broker-specific naming leaking into the domain
- **User isolation (§19)**: every query scoped by `user_id`; user B can never see user A's capital, strategies or funds (tested)
- **Future Return-on-Capital preparation (§15/§16)**: `capital_efficiency_inputs()` returns exactly `{pnl, capital_used, available}` — the metric itself is NOT computed in Phase 6.0, and `available` is False whenever an input is missing so a future phase can never divide by an unknown denominator
- **Capital data contract (§4)**: `premium_outlay`, `broker_margin`, `estimated_capital`, `broker_available_funds`, `paper_starting_capital`, `paper_available_cash`, `capital_used`, `remaining_capital`, `roc_inputs`, per-open-strategy capital units, `generated_at` timestamp and overall `status` — all with source/status; stale-cache discipline via `timestamp`/`generated_at` (§20)
- **API**: ONE read-only `GET /paper/capital` endpoint (auth required; always available regardless of market status; never mutates trading state) + `CapitalOut` / `CapitalValueOut` / `CapitalStrategyOut` / `RocInputsOut` schemas
- **UI** (`frontend/app/paper/CapitalPanel.js` + `frontend/lib/capital.js`): compact capital summary with explicit labels (Paper Starting Capital, Paper Available Cash, Premium Outlay, Broker Margin, Estimated Capital — Premium Basis, Broker Available Funds, Capital Used), per-row source/status badges, per-strategy capital-unit cards, "Return on Capital: inputs ready · not computed" chip — pure display helpers only, no financial formula duplicated client-side
- No changes to scenario calculations (§21), paper execution semantics, market-hours protection, chain handling, Greek/IV analytics or the Phase 5.0 cash ledger; the strategy review panel's Net Debit / Max Loss / Max Profit / Premium ROI fields are untouched (§22)

Automated tests (actual):

- Frontend: 512/512 tests passed (23 files) — 10 new (capital display helpers + API contract)
- Backend: 215/215 tests passed — 20 new (Phase 6.0 §23 matrix: source classification, available vs unavailable, premium vs capital separation, defined-debit estimate, credit unavailable, broker margin unavailable + available via provider, paper cash vs broker funds, user isolation, multi-leg whole-strategy context, null vs zero, no NaN/Infinity, source labels preserved, no ROI aliasing, no Return-on-Capital computation)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

## Phase 6.1 implementation

Status: 🔄 Implemented / Pending Review (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (READ-ONLY broker integration ONLY — no SPAN calculation, no homemade margin calculator, no Return on Capital, no real-money order placement, no deployment):

- **Upstox provider behind the Phase 6.0 abstraction** (`backend/app/services/broker_margin.py`): `UpstoxMarginProvider(MarginProvider)` uses the existing authenticated broker session server-side (tokens never reach the frontend) with two read-only endpoints:
  - `GET /v3/user/get-funds-and-margin` (`Api-Version: 3.0`) — account funds: available-to-trade, cash available, margin used, SPAN+exposure, premium present, pledge available (broker terminology preserved; the V3 `margin_used.span_exposure` field is labeled as the broker's combined SPAN+exposure value, never renamed "margin required")
  - `POST /v2/charges/margin` — whole-strategy broker margin: the COMPLETE multi-leg leg set (up to 20 instruments) is sent in ONE request so Upstox applies spread logic; the broker-reported `required_margin` is preserved as the authoritative figure (per-instrument rows kept raw in `broker_margin_detail`); the platform never sums per-leg margins or re-derives SPAN+exposure
- **Instrument-key resolution (§14)**: keys come from the existing option-chain API (`call_options` / `put_options` `instrument_key`, one chain fetch per expiry) — never constructed manually from strike text; a missing key → `MISSING_INSTRUMENT_KEY` with NO broker request submitted
- **Lots → contracts (§13)**: every leg converts `lots × lot_size` (1 lot NIFTY = 65 contracts) before the margin call; dedicated conversion tests
- **Product type (§12)**: documented single constant `BROKER_PRODUCT_DEFAULT = "D"` (delivery) — the paper engine simulates held positions; no silent broker-specific values
- **Source/status contract (§7/§23)**: every broker figure stays `BROKER_REPORTED` with available | partial | unavailable; missing is `null` (never 0); broker margin NEVER falls back to ESTIMATED capital and broker funds NEVER fall back to paper cash; broker available funds and strategy broker margin stay separate concepts
- **Timestamps (§8)**: each broker figure carries its capture `timestamp`; the snapshot exposes `broker_generated_at` + `expires_at` so stale broker data is never presented as real-time
- **Maintenance window (§9)**: the documented Funds maintenance window (12:00 AM – 5:30 AM IST, HTTP 423) maps to `BROKER_MAINTENANCE` → UNAVAILABLE status with a structured message — not a crash, not 0, not paper cash
- **Structured broker errors (§24)**: BROKER_AUTH_REQUIRED, BROKER_TOKEN_EXPIRED, BROKER_RATE_LIMITED, BROKER_FUNDS_UNAVAILABLE, BROKER_MARGIN_UNAVAILABLE, MISSING_INSTRUMENT_KEY, MARGIN_REQUEST_TOO_LARGE, BROKER_BAD_RESPONSE, BROKER_MAINTENANCE — no raw provider stack traces
- **Caching (§25/§26/§28)**: funds cached 60 s; strategy margin cached by `user + deterministic strategy fingerprint` (symbol/expiry/strike/option type/action/contract qty/product, leg order normalized) for 300 s; expired entries refresh; users are isolated — never a global margin cache; margin APIs are never called from the 1-second chain tick loop
- **API**: `GET /paper/capital` now wires the Upstox provider whenever an authenticated session exists and returns the extended contract: `broker_margin` (aggregate whole-strategy), `broker_available_funds` / `broker_cash_available` / `broker_margin_used` / `broker_pledge_available`, `broker_funds_detail`, `broker_margin_detail` (per-strategy rows), `broker_errors`, `broker_generated_at`, `expires_at`, and per-strategy `broker_margin` / `broker_margin_status` / `broker_margin_error` on each strategy
- **UI** (`frontend/app/paper/CapitalPanel.js` + `frontend/lib/capital.js`): Broker Margin / Broker Available Funds / Broker Cash Available / Broker Margin Used / Broker Pledge Available rows with source badges, "Broker data as of … · expires …" caption, structured error chips (incl. the Funds maintenance window), per-strategy Broker Margin with error codes — pure display helpers only
- No changes to scenario calculations, paper execution semantics, market-hours protection, chain handling, Greek/IV analytics or the Phase 5.0 cash ledger; no Return-on-Capital / Return-on-Margin metrics computed (their inputs — broker margin, realized/unrealized P&L — are preserved for Phase 6.2+)

Automated tests (actual):

- Frontend: 519/519 tests passed (23 files) — 7 new (Phase 6.1 broker display states: success, unavailable, maintenance, loading, authenticated-broker-absent, per-strategy errors, captions)
- Backend: 258/258 tests passed — 43 new (Phase 6.1 §31 matrix: funds success/mappings/timestamp/missing-field/API error/423 maintenance/token error/rate limit; single-leg, bull-call-spread, multi-leg margin as ONE request; instrument-key inputs; lots→contracts; quantity conversion; product mapping; missing key; >20 instruments; margin response mapping; BROKER_REPORTED available/unavailable; no ESTIMATED/paper-cash fallback; null vs zero; fingerprint cache reuse/miss/expiry; user cache isolation; router integration with canned broker responses)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

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
- Portfolio & journal analytics (summary, performance, equity curve, drawdown, strategy groups) ✅
- Capital & margin foundation (source-classified capital, broker margin abstraction, estimated capital, capital summary) ✅
- Upstox broker margin integration (read-only funds + whole-strategy margin, structured errors, fingerprint caching, timestamps) ✅
- Frontend unit tests ✅

### Current architecture concerns

- `frontend/app/paper/page.js` remains a large orchestration component; future domain logic should stay outside it.
- Live Greek conventions are currently based on the documented Upstox/Indian-market convention and should be revalidated if the data feed changes.
- Historical IV collection is deliberately not started (Phase 4.1 created the data model/interfaces only); IV Rank/Percentile AND Phase 4.2 z-scores/percentiles/anomaly scores stay unavailable until a reliable sample exists.
- Broker margin and broker funds now come from the real Upstox read-only APIs (Phase 6.1) and are only as good as the authenticated broker session: auth expiry, the daily Funds maintenance window (12:00 AM – 5:30 AM IST) and missing instrument keys degrade figures to UNAVAILABLE with structured codes — never estimated, never paper cash. Estimated capital still covers only the premium basis for defined-debit strategies; credit/naked strategies report unavailable until a valid analytical model exists (Phase 6.2+). Return on Capital / Return on Margin are not computed yet — only their inputs are prepared.
- Phase 5.0 made the backend authoritative for orders/positions/cash/realized P&L; unrealized P&L remains a mark-to-market display fed by the frontend chain cache (the platform's market-data path).
- Multi-expiry scenario valuation is leg-by-leg modelled and remains approximate for expiry payoff behaviour.
- Legacy journal leg-close on exits is FIFO at whole-leg granularity: for exotic partial netting across multiple executions of the same instrument, journal legs may close with realized scaled to the covered quantity (position math is exact; the journal is a secondary view).
- The legacy `/paper/fills` endpoint still writes only the journal tables (not the authoritative layer); it is retained for backward compatibility and superseded by `/paper/executions`.

## Next phase objective — Phase 6.2

Phase 6.1 (Upstox broker margin integration) is implemented and pending review. The next milestone is **Phase 6.2 — Analytical Margin Model** (model-derived estimated margin for strategies where premium-basis and broker-reported figures are not appropriate, e.g. credit/naked structures — kept strictly separate from BROKER_REPORTED figures). Do not implement Phase 6.2 until Phase 6.1 is verified and approved.

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

**User:** Manually verify Phase 5.2 (EXIT STRATEGY closes every leg of one strategy with one confirmation; EXIT ALL closes the whole account only after the double-confirmation modal; missing chain/quote rejects the whole operation with no position closed; a retried request replays the original result; the result banner shows EXIT COMPLETE with counts and realized P&L, and EXIT PARTIALLY COMPLETED lists failed positions; positions/analytics/capital/journal refresh afterwards). Then ChatGPT reviews the working-tree diff. Phase 5.2 remains in the working tree — the project owner commits it from the Changes panel (FreeBuff does not commit or push). After Phase 5.2 (and the pending 6.0/6.1 reviews) are approved, the roadmap continues with Phase 6.2 (Analytical Margin Model).

Also pending: **User:** Manually verify Phase 6.1 (capital panel shows live Broker Available Funds / Broker Margin Used and per-strategy Broker Margin with BROKER REPORTED badges and the "as of" caption during market hours; funds maintenance window shows UNAVAILABLE with the maintenance message; a strategy with 21+ legs or a missing instrument key shows the structured error; duplicate loads reuse the cached broker snapshot). Also complete the pending Phase 6.0 market-hours verification. Then ChatGPT reviews the working-tree diff. Only after approval does Phase 6.2 (Analytical Margin Model) begin. The project owner creates the Phase 6.1 commit/push from the Changes panel — FreeBuff does not commit or push this phase.
