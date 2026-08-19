# Options Dashboard — Current Project Status

_Last updated: 2026-08-18_

## Current phase

**Phase 6.6.4 — Production-Grade Positions Module & Broker-Ready Position Lifecycle**

Status: ✅ **Verified** (automated verification passed — 626 backend tests, 865 frontend tests, Next.js build — bug fix applied: All tab now correctly returns all positions including closed)

## Phase 6.5.0.4 implementation

Status: 🔄 Implemented / Pending Review (server-authoritative exit intent resolution + paper exit API — NO live execution, NO UI, NO new persistence)

### What was built

Turns the frontend Exit Selector architecture into a SERVER-AUTHORITATIVE, LEG-AWARE, IDEMPOTENT, PAPER-EXECUTABLE exit flow.

- **Server-Side Exit Selector Resolver** (`backend/app/services/exit_selector.py`): `resolve_server_exit_targets(db, user_id, scope, ...)` — independently resolves the user's exit selector against the authenticated user's current `StrategyLegExposure` and `Position` data. The client does NOT dictate which exposure is targeted.
  - Scopes: POSITION (one position), STRATEGY (one strategy_execution_id), PORTFOLIO (all user exposures)
  - Selector filters: option_type (CALL/PUT/CE/PE), action (BUY/SELL — the source strategy-leg action)
  - Quantity modes: ALL (all remaining), QUANTITY (explicit lot count)
  - Normalization: CE→CALL, PE→PUT, case-insensitive action/scope/mode
  - Individual exposure targeting via `exposure_id`
  - Deterministic ordering: `[option_type, source_action, exposure_id]`
  - Side inversion: BUY exposure → SELL execution (via `exit_side_for()`)
  - StrategyLegExposure is the authoritative attribution source
  - Position remains authoritative for NET portfolio exposure
  - User identity from authentication, never from request body
  - No broker-specific fields, no Upstox imports

- **ExitIntentRequestIn** (`backend/app/schemas.py`): request schema with `client_order_id`, `scope`, `strategy_execution_id`, `position_id`, `exposure_id`, `option_type`, `action`, `quantity_mode`, `quantity`
- **ExitIntentOut** + **ExitIntentTargetOut** (`backend/app/schemas.py`): response schemas exposing status, intent_id, targets, orders, positions, errors

- **POST /paper/exit-intent** (`backend/app/routers/paper.py`): server-authoritative exit intent endpoint that:
  1. Authenticates user
  2. Resolves selector against authoritative DB state (StrategyLegExposure + Position)
  3. Creates ExecutionTarget[] from server-resolved exposures
  4. Creates ExecutionIntent (Phase 6.5.0.3)
  5. Resolves market prices for all target positions (existing market-price resolver)
  6. Sets fill prices on targets
  7. Executes through ExecutionRouter → PAPER → existing paper execution engine
  8. Returns structured ExitIntentOut response

### Architecture

```
    User selector (scope + option_type + action + quantity_mode)
        ↓
    POST /paper/exit-intent
        ↓
    Server Exit Resolver (resolve_server_exit_targets)
        ↓
    StrategyLegExposure (authoritative per-execution/per-leg)
        ↓
    ExecutionTarget[] (with side inversion)
        ↓
    ExecutionIntent (Phase 6.5.0.3)
        ↓
    ExecutionRouter (Phase 6.5.0.3)
        ↓
    Market Price Resolver (existing)
        ↓
    Existing Paper Execution Engine
        ↓
    Position + StrategyLegExposure + Cash + P&L + Journal
```

### Schema / migration

None. No database changes.

### Automated verification (actual runs)

- Backend: **604/604 tests passed** — 73 new in `tests/test_exit_selector.py` covering: selector normalization (CE→CALL, PE→PUT, action, scope, quantity_mode), side inversion (buy→sell, sell→buy), input validation (missing scope, missing position_id, missing execution_id, missing quantity, invalid quantity), no matching targets (no exposures, wrong option type filter, wrong action filter, closed exposure, zero remaining, nonexistent strategy/position, closed position), position scope (single exposure, multiple exposures, option_type filter, action filter), strategy scope (strategy isolation, selector filter), portfolio scope (all exposures, option_type filter), individual exposure targeting (specific exposure_id), quantity mode (ALL, QUANTITY, exceeds remaining, ambiguous multiple targets, unambiguous single target), user isolation (cross-user position/strategy/portfolio), deterministic ordering (by option_type/action/exposure_id), side inversion integration (buy call→sell, sell call→buy, buy put→sell, sell put→buy), instrument identity preservation, exposure identity preservation, edge cases (partial remaining, multiple strategies same instrument, no broker fields, CE/PE filter), static architecture audit (no broker imports, no broker fields).
- Frontend: **769/769 tests passed (33 files)** — unchanged (no frontend changes in this phase)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

## Phase 6.5.0.3 implementation

## Phase 6.5.0.3 implementation

Status: 🔄 Implemented / Pending Review (execution boundary foundation only — NO live execution, NO Exit API, NO UI, NO new persistence)

### What was built

Establishes the broker-neutral execution boundary between EXIT INTENT / STRATEGY RESOLUTION and PAPER / FUTURE LIVE EXECUTION.

- **ExecutionIntent** (`backend/app/services/execution_intent.py`): broker-neutral domain object representing WHAT the system has been instructed to execute. Carries intent_id, user_id, execution_mode (PAPER | LIVE), source (EXIT_SELECTOR | MANUAL_EXIT | BULK_EXIT), targets[], idempotency_key, strategy_execution_id, reason, metadata, warnings, status. NOT persisted — existing PaperOrder / StrategyExecution / BulkExitRecord provide authoritative persistence.
- **ExecutionTarget** (frozen dataclass): canonical, broker-neutral execution target carrying position_id (authoritative net portfolio exposure), strategy_leg_exposure_id (authoritative per-execution/per-leg attribution), strategy_execution_id, canonical instrument identity (symbol/expiry/strike/option_type — NO broker-specific instrument_key), source_action (the original strategy-leg action: buy | sell), exit_side (the INVERSE transaction: buy→sell, sell→buy), quantity, remaining_quantity, lot_size, price_override. Frozen/immutable by construction.
- **ExecutionResult**: canonical result carrying intent_id, status (SUCCESS | PARTIAL | FAILED | DUPLICATE | DISABLED | REJECTED), mode, targets_attempted/succeeded/failed, per-target results, errors, duplicated flag.
- **ExecutionError / ExecutionErrorCode**: application-level execution routing errors distinct from BrokerError (which belongs below the router). Codes: INVALID_EXECUTION_INTENT, EXECUTION_TARGET_NOT_FOUND, EXECUTION_TARGET_STALE, EXECUTION_QUANTITY_INVALID, EXECUTION_QUANTITY_EXCEEDS_REMAINING, EXECUTION_IDEMPOTENCY_CONFLICT, LIVE_EXECUTION_DISABLED, PAPER_EXECUTION_FAILED, UNKNOWN_EXECUTION_MODE.
- **Side translation** (§29): `exit_side_for(source_action)` and `source_action_for_exit(exit_side)` — BUY exposure → SELL execution, SELL exposure → BUY execution. StrategyLegExposure.action remains unchanged; the exit side is the inverse.
- **Exit-intent → execution-intent conversion** (§7): `exit_intent_target_to_execution_target()` converts resolved exit-intent targets into canonical ExecutionTargets with the side inverted. `build_execution_targets_from_exposures()` builds targets from StrategyLegExposure ORM objects.
- **Stale-target protection** (§33): `validate_targets_still_valid()` revalidates targets against current DB state before execution — checks position exists, belongs to user, is open with sufficient quantity, and StrategyLegExposure (when referenced) is open with sufficient remaining. Returns structured error list; empty = all valid.
- **ExecutionRouter** (§10): routes ExecutionIntents to the appropriate execution backend.
  - PAPER: delegates to the existing Paper Execution Engine via `exit_position()` — does NOT duplicate position netting, average price, P&L, cash flow, journal, idempotency, or StrategyLegExposure maintenance. Idempotent replay check runs before stale validation (matching the existing paper engine's pattern).
  - LIVE: returns `ExecutionStatus.DISABLED` deterministically. Does NOT call BrokerGateway. Does NOT import UpstoxAdapter.
  - Unknown mode: returns FAILED.
- **Broker-neutral safety** (§18, §28, §38): ExecutionIntent module does NOT import UpstoxAdapter, app.services.upstox, or app.brokers.adapters. No broker-specific fields (instrument_key, transaction_type, access_token, etc.) in any domain object. Static AST audit tests prove this.
- **User isolation** (§26): every target is validated against the authenticated user_id. Cross-user targeting is rejected.
- **No new persistence** (§23, §40): no database table added. ExecutionIntent remains a domain/application object. Existing PaperOrder / StrategyExecution / StrategyLegExposure / BulkExitRecord provide the required persistence.
- **No financial formula duplication** (§39): no payoff, margin, capital, Greeks, or P&L calculations added.

### Architecture

```
    EXIT SELECTOR (frontend)
         ↓
    EXIT TARGET RESOLVER (frontend resolveExitTargets)
         ↓
    EXECUTION INTENT (backend domain — this phase)
         ↓
    EXECUTION ROUTER (backend — this phase)
        ↙          ↘
     PAPER         LIVE
       ↓             ↓
  Existing Paper   DISABLED
  Execution Engine
       ↓
  Position + StrategyLegExposure + Journal + Cash
```

### Schema / migration

None. No database changes.

### Automated verification (actual runs)

- Backend: **531/531 tests passed** — 95 new in `tests/test_execution_intent.py` covering: ExecutionTarget creation and validation (buy→sell, sell→buy, invalid sides, quantity/remaining validation, instrument identity, no broker fields), ExecutionIntent creation and validation (user_id required, targets required, idempotency key required, deterministic ID, random default key, metadata/reason preservation, no broker fields), side translation (§29), exit-intent → execution-target conversion (normalization, exposure ID, price override, invalid source), build targets from exposures (open/closed/zero, quantity modes, deterministic ordering, sell→buy), stale-target validation (closed position, quantity exceeds, user mismatch, missing position, closed exposure, quantity exceeds exposure, missing exposure, partial failure), ExecutionRouter PAPER routing (successful exit, position update, cash update, realized P&L, journal preservation, failed validation writes nothing, idempotent replay), ExecutionRouter LIVE disabled (deterministic disabled, no position modification, all targets failed), unknown mode, broker boundary safety (AST audit: no Upstox/upstox imports, no broker-specific fields on Intent/Target/Result), user isolation (cross-user rejected, stale validation catches cross-user), quantity safety (exceeds remaining, zero, negative), concurrency (same idempotency key replay, different keys same position), existing behavior preserved (EXIT STRATEGY through router, partial exit preserves remaining, StrategyLegExposure maintained, strategy isolation shared instrument), execution result states.
- Frontend: **769/769 tests passed (33 files)** — unchanged (no frontend changes in this phase)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

## Phase 6.5.0.2 implementation

## Phase 6.5.0 implementation

Status: 🔄 Implemented / Pending Review (foundation only — later Phase 6.5 sub-phases build on it)

Implemented (pure domain foundation ONLY — no execution, no new API, no UI, no market-gate changes):

- **Exit Intent / Selector domain** (`frontend/lib/calculations/exitIntent.js`): `EXIT_SCOPE` (POSITION / STRATEGY / PORTFOLIO), `EXIT_QUANTITY_MODE` (ALL / QUANTITY), and a normalized `ExitSelector` with optional `optionType` (CALL | PUT, accepts CE/PE), optional `action` (BUY | SELL) and optional `legId` — supporting ALL, CALL/CE, PUT/PE, BUY SIDE, SELL SIDE, BUY CE, BUY PE, SELL CE, SELL PE and individual-leg targeting
- **`resolveExitTargets(intent, exposures, options)`** — pure target resolution: uses the CURRENT remaining quantity (signed `net_quantity`, never the original order quantity), excludes closed/zero-quantity positions, respects strategy-execution identity (never mixes strategies or users), matches option type and BUY/SELL attribution exactly, supports individual-leg targeting, and returns deterministic ordering ([optionType, side, positionId])
- **Quantity safety**: ALL may resolve multiple targets; QUANTITY on multiple matches returns a structured `AMBIGUOUS_EXIT_QUANTITY` error (never guessed/silently duplicated); requested quantity > remaining returns `EXIT_QUANTITY_EXCEEDS_REMAINING` (never clamped silently)
- **Structured errors**: INVALID_INTENT, MISSING_QUANTITY, INVALID_QUANTITY, TARGET_NOT_FOUND, NO_MATCHING_TARGETS, AMBIGUOUS_EXIT_QUANTITY, EXIT_QUANTITY_EXCEEDS_REMAINING
- **Schema verdict (superseded by Phase 6.5.0.1)**: the initial 6.5.0 review concluded the netted position preserved BUY/SELL attribution and no new persistence model was needed. **Phase 6.5.0.1's deeper review overturned this**: the netted `Position` cannot represent per-execution REMAINING leg quantities (one row per instrument, first-opener `strategy_execution_id` only; entry orders store original quantity with no remaining tracking; exits carry no execution id), so a separate persistent `StrategyLegExposure` attribution model was added — see Phase 6.5.0.1 below
- **User isolation**: optional `options.userId` filter — another user's positions are never mixed, and cross-user POSITION/STRATEGY targeting reports TARGET_NOT_FOUND (never leaks)
- **No execution changes**: no new exit API, no UI buttons, no market-gate changes, no broker calls, no fill/cash/journal logic — those belong to later Phase 6.5 sub-phases

Automated tests (actual):

- Frontend: **769/769 tests passed (33 files)** — 55 new tests in `frontend/lib/calculations/exitIntent.test.js` covering ALL/CALL/PUT/BUY/SELL/BUY CALL/BUY PUT/SELL CALL/SELL PUT/legId, partial remaining quantity, zero-quantity/closed exclusion, missing strategy, mixed strategies, deterministic ordering, explicit quantity over remaining, ambiguous explicit quantity, user isolation, exposure mapping (backend + frontend shapes), selector normalization/labels, NaN/Infinity safety, input immutability, and a static audit proving the module makes no fetch/axios/WebSocket/import calls
- Backend: **353/353 tests passed** (unchanged — no backend changes)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending (exercise `resolveExitTargets` combinations against a real paper portfolio with BUY CE / SELL CE / BUY PE / SELL PE legs)
ChatGPT review: ⏳ pending

## Phase 6.5.0.1 implementation

Status: 🔄 Implemented / Pending Review (attribution foundation only — no exit endpoint, no selector execution, no UI, no market-gate changes, no new fill/P&L/cash logic)

### Schema decision

The existing schema CANNOT safely reconstruct current remaining leg quantities after partial exits / repeated partial exits / opposing fills / reversals / multiple strategies sharing one instrument / multiple executions of the same strategy:

- `Position` — one row per instrument with a single **first-opener** `strategy_execution_id`; `net_quantity` is netted across ALL executions trading that instrument (Strategy A BUY 25000 CE × 2 + Strategy B SELL 25000 CE × 1 → `net_quantity = +1`, owned by A).
- `PaperOrder` — entry orders store ORIGINAL quantity only (no `remaining_quantity`); exit orders carry `execution_id = None`.
- `strategy_execution_id` cannot be derived from `sign(net_quantity)` (the example above is net LONG while B's leg is a SELL).

**Decision: new persistent `StrategyLegExposure` model (created).** Position remains the authoritative net portfolio exposure; the exposure table adds per-execution, per-leg remaining attribution only.

### Migration decision

- New table `strategy_leg_exposures` — created automatically by `Base.metadata.create_all` on existing databases (no ALTER needed; same mechanism as every prior table).
- Conservative one-time backfill in `init_db()` (`backfill_all_exposures`): creates rows ONLY for provably unambiguous pre-existing executions (position carries an execution id, EVERY FILLED entry order for the instrument belongs to that same execution, and the instrument was never exited → remaining = original). Shared-instrument / partially-exited / legacy-standalone positions are skipped and left to the safe-skip path. Idempotent (unique per `(user_id, order_id)`).

### Model (minimal)

`strategy_leg_exposures`: id, user_id, execution_id, position_id, order_id (source entry order), symbol, expiry, strike, option_type, action (buy|sell — the executed strategy-leg action, NEVER derived from the position sign), original_quantity, remaining_quantity, status (open|closed), created_at, updated_at. No LTP / average entry / realized P&L / cash / margin — those stay owned by the execution/position/accounting layer.

### Attribution algorithm

- Entry: `execute_strategy` creates one exposure row per FILLED entry order (idempotent — a replayed `client_order_id` never duplicates rows).
- Exit: `exit_position` (single + bulk — bulk exits run through the same path) reduces the position's **dominant side** — net-long reduces buy-action exposures, net-short reduces sell-action exposures — deterministically **FIFO by exposure id**, each capped at its own remaining.
- `currentPositionSide` and `strategyLegAction` are independent concepts; the model never derives the latter from the former.

### Reconciliation algorithm

- Invariant: signed sum of exposures' remaining (buy = +, sell = −) == position `net_quantity`.
- `reconcile_position_exposures(position, exposures)` → OK / MISMATCH.
- `allocate_exit(exposures, prior_net, qty)` (pure) enforces two caps: never more than the actual position supports (`abs(prior_net)`) → `INSUFFICIENT_POSITION_CAPACITY`; never more than the dominant-side ledger can cover → `INSUFFICIENT_EXPOSURE_CAPACITY`. Ambiguous/stale attribution fails safely — never guessed, never silently duplicated.
- Positions whose ledger does not reconcile (legacy / mixed legacy+new) simply skip attribution maintenance: the position engine is authoritative and exits are never blocked or altered.

### Journal fix (regression-tested before behavior change)

`_close_journal_legs()` searched matching FILLED entry orders by instrument WITHOUT constraining the strategy execution, so an exit of a netted position shared by multiple executions could close ANOTHER execution's journal legs. Minimum safe correction: when the position carries a `strategy_execution_id`, entry orders are scoped to `PaperOrder.execution_id == position.strategy_execution_id`. Legacy standalone positions (no execution id) keep the historical instrument-wide FIFO behaviour. Regression tests prove: same-execution exits still close their own journal legs; a position owned by execution A exiting over A's quantity NEVER closes execution B's journal legs.

### User isolation

All exposure rows and all maintenance queries are scoped by `user_id` (+ `position_id`); a user's exits never touch another user's exposure rows (tested).

### Scope restrictions honoured

NO new exit endpoint, NO selector execution, NO UI, NO market-gate changes, NO broker calls, NO new fill/P&L/cash logic, NO risk guardrails. Attribution foundation only.

Automated verification (actual runs):

- Backend: **377/377 tests passed** — 24 new in `backend/tests/test_leg_exposure.py` covering one strategy / one leg, one strategy / multiple legs, multiple strategies / same instrument, BUY + SELL same instrument, CE + PE, partial exit, repeated partial exits, reversal, same strategy multiple executions, user isolation, journal attribution (scoped + same-execution regression), position-capacity reconciliation, deterministic FIFO allocation, insufficient current capacity (endpoint + pure), idempotent state updates (duplicate execution + duplicate exit), mixed legacy + new safe-skip, and conservative backfill (creates / skips shared / skips exited / idempotent / user-scoped)
- Frontend: **769/769 tests passed (33 files)** — unchanged (no frontend changes in this phase)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending (exercise multi-execution same-instrument scenarios end-to-end, then confirm exposure rows reconcile after partial exits/reversals)
ChatGPT review: ⏳ pending

## Phase 6.5.0.2 implementation

Status: 🔄 Implemented / Pending Review (abstraction foundation only — NO live execution, NO Exit API, NO UI, NO second broker, NO persistent credential vault)

### What was built

A clean broker-neutral domain boundary with the existing read-only Upstox integration migrated behind it — Upstox becomes Adapter #1; a second broker becomes Adapter #2 later without contaminating strategy / risk / capital / portfolio / Exit Intent / paper-trading domains.

- **Broker-neutral domain contracts** (`backend/app/brokers/domain/`): enums (`BrokerId`, `Side`, `OrderType`, `Product`, `Validity`, `OrderStatus`, `InstrumentType`, `OptionType`, `Segment`, `ExecutionPolicy`), error taxonomy (`BrokerError` / `BrokerErrorCode` with AUTH_REQUIRED / TOKEN_EXPIRED / RATE_LIMITED / NETWORK_ERROR / MAINTENANCE / INVALID_INSTRUMENT / INVALID_QUANTITY / INVALID_PRICE / ORDER_REJECTED / ORDER_NOT_FOUND / ORDER_ALREADY_FINAL / ACCOUNT_RESTRICTED / SEGMENT_DISABLED / STATIC_IP_REQUIRED / CAPABILITY_UNSUPPORTED / BROKER_UNKNOWN / UPSTREAM_ERROR), canonical `InstrumentIdentity` (exchange/segment/underlying/symbol/expiry/strike/option_type/instrument_type/lot_size/tick_size — broker keys NEVER the universal ID), canonical `BrokerOrderRequest` / `BrokerOrderResult` (multi broker-order-id capable — one logical order → many broker order ids), `BrokerConnectionContext` (user → broker → account), capability model (`BrokerCapabilities` distinguishing SUPPORTED vs AVAILABLE vs UNSUPPORTED vs AUTH_REQUIRED vs ACCOUNT_DISABLED vs TEMPORARILY_UNAVAILABLE — never a bare boolean), and the `BrokerAdapter` protocol covering auth / account / instruments / market data / orders / trades / portfolio
- **Broker registry + gateway** (`backend/app/brokers/registry.py`, `gateway.py`): broker selection happens in ONE controlled location (`gateway.create(...)` / `gateway.for_connection(...)`); unknown brokers fail safely with BROKER_UNKNOWN; registration is idempotent; the future Zerodha/Dhan/Angel/Fyers adapters are a one-line registration each
- **UpstoxAdapter** (`backend/app/brokers/adapters/upstox/`): all Upstox-specific concepts (base URLs, OAuth, tokens, instrument keys, transaction types, product codes, HTTP status/error strings, V3 order field names) stay inside the adapter package + the raw client (`app/services/upstox.py`); `UpstoxError` never escapes — every failure maps to canonical `BrokerError`; chain/contract methods return canonical structures (Upstox payload field names like `call_options` never reach app code)
- **Read-only migration (behavior-preserving)**: profile, funds, margin, market status, option chain, option contracts now flow through the adapter/gateway in `routers/auth.py`, `routers/chains.py`, `routers/paper.py`, `services/market_status.py`, `services/broker_margin.py`, `services/broker_profile.py`; the Phase 6.1 `MarginProvider` architecture and the Phase 6.4.1 diagnostics architecture continue to work unchanged; the public API contracts (BROKER_* structured codes, capital contract, profile contract) are byte-for-byte identical
- **Upstox V3 order preparation (NOT wired)**: canonical order contract + pure payload builder (`build_order_request_payload`) + response mapper (`map_order_result`) with tested mappings for BUY/SELL, MARKET/LIMIT/SL/SL-M, validity, AMO/after-market, market protection, disclosed quantity, tags, single/multiple order ids, and canonical order-status mapping; every adapter order/trade/portfolio method raises CAPABILITY_UNSUPPORTED with an explicit "NOT wired" message — no fake live execution
- **Native-slicing safety by construction**: one canonical `execution_policy` (AUTO / BROKER_NATIVE / PLATFORM_MANAGED / DISABLED) plus multi-id `BrokerOrderResult` — the platform can never accidentally double-slice (platform chunking of a broker-native order is impossible by construction); slicing is never a payload field
- **Security**: adapters never log, repr or return tokens (repr-safety tested); canonical models/results carry no credential fields; the frontend-facing diagnostics contracts are unchanged and never receive credentials; `disconnect()` only forgets the adapter's own token — the app auth layer owns revocation
- **Paper trading remains broker-independent**: paper execution needs NO broker connection; paper is not live execution; Exit Intent (6.5.0) and StrategyLegExposure (6.5.0.1) are untouched

### Schema / migration

None. No database changes in this phase (broker abstraction is pure application-layer).

### Automated verification (actual runs this session)

- Backend: **436/436 tests passed** — 59 new in `tests/test_broker_domain.py` + `tests/test_upstox_adapter.py` covering: canonical model field-name neutrality (no instrument_key/transaction_type/is_amo/slice), explicit None vs fabricated zero, multi-id order results, registry/gateway (UPSTOX resolves, unknown fails, deterministic, idempotent registration, connection context attachment), error taxonomy + session codes, Upstox→canonical error mapping (401/403→TOKEN_EXPIRED, 423→MAINTENANCE, 429→RATE_LIMITED, network→NETWORK_ERROR, else UPSTREAM_ERROR), instrument identity neutrality + broker-key isolation, option-type/order-type/side/validity/AMO/market-protection mappings isolated to the mapper, response mapping (single/multi id, rejected/partial/filled), capability states (SUPPORTED vs ACCOUNT_DISABLED vs AUTH_REQUIRED), NOT-wired operations raising CAPABILITY_UNSUPPORTED, token-repr/security guards, and adapter chain/contract key-resolution via the patched raw client
- Frontend: **769/769 tests passed (33 files)** — unchanged (no frontend changes in this phase)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

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
| Phase 5.2.1 — Active Positions UX, Strategy Filtering, Market Session Awareness & Option Price Precision | 🔄 Implemented | Strategy identity/filtering (strategy_execution_id, never Custom for named strategies), strategy-grouped Active Positions + EXIT STRATEGY/EXIT ALL, segment-aware market sessions (INDEX_DERIVATIVES default, CAS never conflated with index options), NIFTY ₹0.05 option tick normalization at every fill boundary, two-decimal financial display — pending review |
| Phase 6.0 — Capital & Margin Foundation | 🔄 Implemented | Source-classified capital figures, broker margin abstraction, estimated capital (premium basis), capital summary — implemented & committed, pending final market-hours verification |
| Phase 6.1 — Broker Margin Integration (Upstox) | 🔄 Implemented | Real Upstox funds + whole-strategy margin APIs behind MarginProvider, broker source/status/timestamp, caching — pending review |
| Phase 6.2 — Analytical Margin Model | 🔄 Implemented | Frontend analytical capital model — premium/risk bases, scenario capital, Strategy Review CAPITAL section, broker-vs-estimate separation — pending review |
| Phase 6.3 — Capital Efficiency & Return Metrics | 🔄 Implemented | Source-aware return metrics (Premium ROI, Return on Capital/Margin/Risk Capital, Capital Efficiency) with explicit denominators, Strategy Review + Portfolio Analytics + Journal integration — pending review |
| Phase 6.4 — Capital Allocation / Portfolio Risk Controls | 🔄 Implemented | Capital allocation, risk concentration, strategy/underlying/expiry concentration, configurable monitoring-only limits, portfolio allocation & risk dashboard — pending review |
| Phase 6.4.1 — Broker Profile & Connection Diagnostics | 🔄 Implemented | Upstox profile verification, safe profile card, connection health (profile/funds/margin/market/chain), account capabilities, user-scoped TTL cache, structured broker errors — pending review |
| Phase 6.5.0 — Exit Intent / Selector Foundation | 🔄 Implemented | Pure Exit Intent / Selector domain: EXIT_SCOPE (POSITION/STRATEGY/PORTFOLIO), selector combinations (ALL/CALL/PUT/BUY/SELL/BUY CE/BUY PE/SELL CE/SELL PE/legId), resolveExitTargets with remaining-quantity semantics, quantity safety (AMBIGUOUS_EXIT_QUANTITY, never over remaining), deterministic ordering, user isolation, no execution/network — pending review (schema verdict superseded by 6.5.0.1) |
| Phase 6.5.0.1 — Strategy Leg Attribution Architecture | 🔄 Implemented | New persistent StrategyLegExposure attribution model (per-execution, per-leg remaining), deterministic dominant-side FIFO exit allocation, position-capacity reconciliation (never over net position, never guessed), strategy-scoped journal-close fix with regression tests, conservative idempotent startup backfill, user isolation, no execution/UI — pending review |
| Phase 6.5.0.2 — Broker-Neutral Connectivity Foundation | 🔄 Implemented | Canonical broker domain (models/enums/errors/capabilities/protocols), BrokerGateway/Registry, UpstoxAdapter boundary, read-only migration (profile/funds/margin/market status/chain/contracts) behind the adapter, V3 order preparation (payload + response mappers, tested, NOT wired), native-slicing safety (execution_policy + multi-id results), no live execution / no second broker / no DB changes — pending review |
| Phase 6.5.0.3 — Execution Intent + Execution Router Foundation | 🔄 Implemented | Broker-neutral ExecutionIntent/ExecutionTarget/ExecutionResult domain objects, execution error taxonomy, side inversion (BUY→SELL, SELL→BUY), exit-intent→execution-intent conversion, stale-target protection, ExecutionRouter (PAPER→existing paper engine, LIVE→DISABLED), idempotency, user isolation, no new persistence, no live execution, no broker imports in domain — pending review |
| Phase 7 — Journal & performance analytics | ⏳ Planned | Not started |
| Phase 8 — Backtesting | ⏳ Planned | Not started |
| Phase 9 — Strategy scanner | ⏳ Planned | Not started |
| Phase 10 — Custom trading terminal/dashboard | ⏳ Planned | Not started |
| Phase 11 — Automation / alerts | ⏳ Planned | Not started |
| Phase 12 — Multi-broker expansion | ⏳ Planned | Foundation pulled forward + implemented in Phase 6.5.0.2 (broker-neutral contracts, gateway/registry, Upstox adapter). Remaining: second broker (architectural proof test), additional adapters, persistent multi-broker connections, account-management UI, broker capability matrices |
| Phase 13 — Community | ⏳ Planned | Not started |

## Latest verified implementation commit

`3d032f2` — Phase 5.1: portfolio and journal analytics (verified).

Phase 6.0 was committed via the Changes panel: implementation `01d008e` + status update `45b459e` (pending final market-hours verification).

Phase 6.1 implementation commit: `e677bb9` (audited 2026-08-17 — see "Phase 6.1 final audit" below; not yet user-verified / ChatGPT-approved).

Prior baselines: Phase 5.0 `f72b5c0fde522bf5110b125ce310d3685ffb75b4`, Phase 4.1 `22f09073749db169905fd2dd06c81c3e37794e0a`, Phase 4.0 `9ae9966ca358a716c0e53d96203103f5e717e86f`.

The Phase 4.2 implementation is committed but was never user-verified or ChatGPT-reviewed; it is superseded by later phases.

Phase 6.1 was committed via the Changes panel: implementation `e677bb9` (11 files). Phase 5.2 was committed as `27a4cd2`; Phase 5.2.1 was committed as `f0d0623`; the Recharts `Line` import fix + Vitest config landed in `8aad8c2`. All phases now exist in committed history.

Phases 6.4, 6.4.1, 6.5.0, 6.5.0.1 and 6.5.0.2 are implemented in the current working tree (uncommitted). Phase 6.4: `frontend/lib/calculations/capitalAllocation.js` + `capitalAllocation.test.js` (new), `frontend/app/paper/PortfolioAnalyticsPanel.js` + `PortfolioAnalyticsPanel.test.js` (modified). Phase 6.4.1: `backend/app/services/broker_profile.py` + `backend/tests/test_broker_profile.py` (new), `backend/app/services/upstox.py`, `backend/app/routers/paper.py`, `backend/app/schemas.py` (modified), `frontend/lib/brokerDiagnostics.js` + `brokerDiagnostics.test.js` (new), `frontend/app/paper/BrokerConnectionPanel.js` + `BrokerConnectionPanel.test.js` (new), `frontend/lib/api.js`, `frontend/app/paper/page.js` (modified). Phase 6.5.0: `frontend/lib/calculations/exitIntent.js` + `exitIntent.test.js` (new). Phase 6.5.0.1: `backend/app/models.py`, `backend/app/db.py`, `backend/app/services/paper_execution.py` (modified), `backend/app/services/leg_exposure.py` + `backend/tests/test_leg_exposure.py` (new). Phase 6.5.0.2: `backend/app/brokers/` (new — domain contracts, Upstox adapter, registry, gateway), `backend/app/routers/auth.py`, `backend/app/routers/chains.py`, `backend/app/routers/paper.py`, `backend/app/services/market_status.py`, `backend/app/services/broker_margin.py`, `backend/app/services/broker_profile.py` (modified — migrated behind the adapter/gateway), `backend/tests/test_broker_domain.py` + `backend/tests/test_upstox_adapter.py` (new), `docs/PROJECT_MASTER_BLUEPRINT.md` (updated) — plus this status update. Phases 6.2 and 6.3 were committed via the Changes panel. The project owner commits Phases 6.4 / 6.4.1 / 6.5.0 / 6.5.0.1 / 6.5.0.2 from the Changes panel — FreeBuff does not commit or push.

## Phase 5.2.1 implementation

Status: 🔄 Implemented / Pending Review (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (platform/data/UX feature — no trading methodology, no signals):

- **Strategy identity**: `GET /paper/positions` and position exits now expose `strategy_tag` (batched from `StrategyExecution`), so Long Seagull / Bull Put Spread / Bull Condor never display as "Custom"; the authoritative relationship stays `strategy_execution_id` → `StrategyExecution.strategy_tag`; legacy/missing executions fall back to "Custom"
- **Active-position invariant**: the backend `get_open_positions` enforces status == open AND net_quantity != 0 — a zero-quantity position never appears as Active
- **Strategy filter**: `ALL OPEN POSITIONS (N)` dropdown above Active Positions, built dynamically from the currently-open strategy executions with leg counts; selection filters by `strategy_execution_id` only; strategy-grouped cards show legs, ≈value and unrealized P&L with EXIT STRATEGY; EXIT ALL remains account-wide
- **Segment-aware market sessions**: `app/services/market_status.py` refactored to explicit, configurable per-segment session definitions (EQUITY_CASH, EQUITY_DERIVATIVES, INDEX_DERIVATIVES, STOCK_DERIVATIVES, CURRENCY, COMMODITY); status carries `segment` + `session_state` (OPEN | CLOSING_AUCTION | TRANSITION | CLOSED | UNKNOWN); the execution gate resolves the instrument's own segment feed (INDEX_DERIVATIVES → NSE_FO) so a cash-segment SEBI closing auction can never enable index-option execution; Upstox remains authoritative, local calendar fallback never invents sessions; badge shows session states (CLOSING AUCTION / TRANSITION) while the backend re-validates at execution time
- **Option tick-size normalization**: canonical `round_option_price` (backend) / `roundOptionPrice` (frontend) — NIFTY index options use the ₹0.05 tick; authoritative fill prices (strategy entry, single exit, bulk exit) are tick-aligned; raw broker LTPs used for analytics are never overwritten (kept as `rawLtp`); frontend position marks use the tick-aligned tradable price so fill and display boundaries agree
- **Two-decimal financial display**: paper-trading UI (LTP, entry price, premiums, P&L, cash, strategy value, estimated capital, exposure) renders with two decimals via the existing Indian `fmtIN` helper; integer fields (lot qty, strike, counts, expiry) keep natural formatting; no ₹0.05 rounding is applied to spot/IV/Greeks/P&L totals

Automated tests (actual):

- Frontend: 557/557 tests passed (27 files) — new pricing tests (tick rounding + two-decimal), strategy filter/grouping tests, session-awareness tests
- Backend: 325/325 tests passed — new tick-rounding tests, strategy-tag tests, segment/session tests (cash CAS never enables index-option execution, F&O closing is TRANSITION not auction, gate authoritative)
- `npx next build`: passed; all routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

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

Status: 🔄 Implemented / Pending Review (implementation complete — FINAL AUDIT DONE 2026-08-17, manual broker verification pending, ChatGPT review pending)

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

## Phase 6.2 implementation

Status: 🔄 **Implemented / Pending Review** (implementation complete — manual verification pending, ChatGPT review pending)

Implemented (ANALYTICAL capital infrastructure ONLY — no SPAN calculator, no broker-margin replacement, no Return on Capital / Margin, no Capital Efficiency Score, no signals, no trading methodology, no real-money execution, no new broker APIs, no new polling):

- **Analytical capital architecture**: new frontend pure domain module `frontend/lib/calculations/analyticalCapital.js` — `analyzeCapital(legs, {lotSize, multiplier})` + `scenarioCapital(...)` + `capitalEfficiencyInputs(...)`. Deterministic, dependency-light, side-effect free, broker-independent (no network, no DB writes, no Upstox/broker calls). It CONSUMES the existing authoritative engines (`calculateStrategy` → payoff.js/risk.js; `roundOptionPrice` from pricing.js) — no payoff/risk/premium/option-price formula is duplicated.
- **Result contract**: `{value, source: "ESTIMATED", basis: "premium" | "max_loss" | "risk_model" | "unavailable", status: "available" | "partial" | "unavailable", warnings[], notes[]}`. Unavailable = null (never 0); 0 is a valid estimate; no NaN/Infinity; never fabricated.
- **Premium basis**: defined-debit strategies → whole-strategy net debit (`calculateStrategy().netTotal`), e.g. Long Call / Long Put; valid for mixed-expiry net-debit (Calendar/Diagonal) — deterministic across expiries.
- **Risk basis (defined loss)**: same-expiry defined-risk strategies → `abs(maxLoss)` from the authoritative theoretical payoff engine — Bull/Bear spreads, Iron Condor, Butterfly, Long Straddle/Strangle (finite), defined ratios (finite), and Naked Short Put follows the existing Phase 2 S ≥ 0 domain result (defined, no new interpretation).
- **Unsupported/unlimited handling**: Naked Short Call / Short Straddle / Short Strangle / short ratios with open-ended risk → UNAVAILABLE + `UNLIMITED_RISK`; never a fabricated finite number.
- **Mixed-expiry handling**: Calendar/Diagonal → premium basis only when net debit is defined; risk basis UNAVAILABLE + `MIXED_EXPIRY_APPROXIMATION`; the engine's own calculation warnings are preserved in `notes` (no silent primary-expiry substitution, no fake same-expiry exactness).
- **Input validation**: zero legs / zero / negative / fractional quantity / invalid option type / invalid action / missing premium / missing lot size / invalid strike / malformed expiry → UNAVAILABLE with structured warnings (`INVALID_LEG`, `MISSING_PREMIUM`, `UNSUPPORTED_STRUCTURE`, `INSUFFICIENT_RISK_MODEL`); no exceptions leak to the UI.
- **Scenario capital**: `scenarioCapital(...)` operates on scenario-modified legs, produces the same contract, tick-aligns scenario premiums via the canonical ₹0.05 `roundOptionPrice` (capital totals are NEVER tick-rounded), and never calls the broker / paper endpoints.
- **Strategy Review UI**: the review panel gains a CAPITAL section — Premium Outlay (CALCULATED), Estimated Capital (ESTIMATED · PREMIUM BASIS / ESTIMATED · RISK BASIS · DEFINED LOSS / ESTIMATED · UNAVAILABLE + warning codes), Broker Margin (BROKER REPORTED · live refresh not performed in the builder) — both figures stay independently visible; an unavailable broker margin is never replaced by the estimate. Recomputes live on every strike/action/quantity/option-type/expiry/leg change (pure client recompute, no polling, no broker call per edit).
- **Broker separation (§2/§18)**: analytical estimates are `ESTIMATED` only; broker margin stays BROKER_REPORTED (Phase 6.1 authoritative); `GET /paper/capital` contract is untouched. New neutral "Broker vs Estimate Difference" (= broker margin − estimated capital, only when both exist) in the Capital Panel — descriptive only, never "Savings/Advantage/Efficiency/Better".
- **Future capital-efficiency inputs**: `capitalEfficiencyInputs()` returns `{pnl, capital_used, broker_margin, estimated_capital, available}` — no Return on Capital / Return on Margin / Capital Efficiency computed (Phase 6.3).
- No changes to cash ledger, realized/unrealized P&L, positions, execution, exits, `capital_used` semantics, payoff/risk/scenario/Greek/IV engines, or the backend.

Automated tests (actual):

- Frontend: 600/600 tests passed (28 files) — 43 new in `frontend/lib/calculations/analyticalCapital.test.js` (the full §23 matrix: premium/risk bases per structure, unlimited-risk safety, mixed-expiry warnings, invalid inputs, zero-vs-unavailable, no NaN/Infinity, quantity/lot/multiplier scaling, strategy mutation, scenario capital, no broker API call, broker/estimate separation, tick compatibility, two-decimal contract, capital-efficiency inputs)
- Backend: 325/325 tests passed (unchanged — no backend code modified)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

## Phase 6.3 implementation

Status: 🔄 **Implemented / Pending Review** (implementation complete — automated verification passed, manual verification pending, ChatGPT review pending)

Implemented (canonical, source-aware capital-efficiency analytics ONLY — no signals, no trading methodology, no annualized/CAGR returns, no SPAN calculator, no broker-margin replacement, no changes to Upstox API / MarginProvider / broker margin / broker funds):

- **Pure domain module**: new `frontend/lib/calculations/capitalEfficiency.js` — `calculatePremiumRoi`, `calculateReturnOnCapital`, `calculateReturnOnMargin`, `calculateReturnOnRiskCapital`, `calculateCapitalEfficiency`, `calculateCapitalEfficiencySet`. Deterministic, pure, side-effect free, dependency-light, broker-independent (consumes broker-reported values, never fetches). Reuses existing authoritative sources only (Phase 5.0/5.1 P&L, Phase 6.0 premium_outlay/estimated_capital, Phase 6.1 broker_margin, Phase 6.2 analytical capital / risk / premium bases); no payoff/risk/premium formula is duplicated.
- **Metric definitions (§1–§2)**: PREMIUM ROI = P&L / Premium Outlay; RETURN ON CAPITAL = P&L / Estimated Capital; RETURN ON MARGIN = P&L / Broker Margin (BROKER_REPORTED only); RETURN ON RISK CAPITAL = P&L / abs(Max Loss) with basis MAX_LOSS / DEFINED RISK (unlimited → null + UNLIMITED_RISK); CAPITAL EFFICIENCY = P&L / an explicitly named denominator (PREMIUM_OUTLAY | ESTIMATED_CAPITAL | BROKER_MARGIN | MAX_LOSS — never auto-selected; missing/invalid type → unavailable + DENOMINATOR_NOT_SPECIFIED). No percentage is ever displayed as a bare "ROI".
- **Result contract (§5)**: every metric returns `{value, status (available | unavailable | partial), numerator, denominator, denominatorLabel, denominatorSource, basis, pnlType (REALIZED | UNREALIZED | TOTAL | PROJECTED), period, warnings[]}`; value is a finite percentage or null. Zero P&L is a valid 0.0% (never collapsed with unavailable); unavailable = null, never 0, never NaN, never Infinity.
- **Denominator/source separation (§6/§21–§25)**: null / 0 / negative / NaN / Infinity / unavailable denominators → value null (INVALID_DENOMINATOR / MISSING_DENOMINATOR). No fallbacks in any direction — paper cash never substitutes for broker margin, estimated capital never substitutes for broker margin, max loss never substitutes for premium outlay, etc. Non-BROKER_REPORTED values are rejected as a margin denominator (SOURCE_NOT_BROKER_REPORTED). Broker vs estimate stay independently addressable.
- **Realized vs unrealized (§13)**: the numerator is always labeled REALIZED / UNREALIZED / TOTAL / PROJECTED; realized P&L is authoritative for closed trades; builder contexts use PROJECTED (at max profit) and are labeled as such, never presented as realized P&L.
- **Period (§16/§17)**: P&L period must match the capital period; a mismatch returns unavailable + MISMATCHED_PERIOD. No annualization, no CAGR, no time-normalized returns (deferred to a future phase).
- **Strategy-level (§14/§27)**: Strategy Review gains a RETURNS (AT MAX PROFIT · PROJECTED) section — Return on Capital (÷ estimated capital) and Return on Risk Capital (÷ defined max loss), with explicit denominator captions and warnings; recomputed live on every strategy edit (pure client recompute, no broker API call per edit).
- **Portfolio-level (§15/§28)**: PortfolioAnalyticsPanel gains a "Capital efficiency · since inception" section — Premium ROI, Return on Capital, Return on Margin (BROKER_REPORTED only) — each card showing its denominator and source; Return on Risk Capital stays N/A until per-strategy defined max loss exists (Phase 6.4); portfolio broker margin is used only as the broker-reported aggregate, never a sum of stale per-strategy snapshots.
- **Journal (§29)**: completed journal rows add a Premium ROI column (per-row premium outlay derived from the row's own buy-leg fills: fill_price × quantity × lot_size — the only journal-level denominator genuinely available); missing denominators render N/A, never 0%.
- **Capital-efficiency inputs (§30)**: consumes the Phase 6.0/6.2 input values (premium_outlay, estimated_capital, broker_margin, analytical basis) — no parallel input contract was introduced.
- No changes to cash ledger, realized/unrealized P&L, positions, execution, exits, payoff/risk/scenario/Greek/IV engines, Upstox API, MarginProvider, or broker margin calculations.

Automated tests (actual):

- Frontend: 636/636 tests passed (29 files) — 36 new in `frontend/lib/calculations/capitalEfficiency.test.js` (the full §31 matrix: Premium ROI 1–6, Return on Capital 7–12, Return on Margin 13–17, Return on Risk Capital 18–21, separation 22–25, period 26–27, portfolio 28–30, numeric safety 31–35, plus no NaN/Infinity leak)
- Backend: 325/325 tests passed (unchanged — no backend code modified)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

Manual verification: ⏳ pending
ChatGPT review: ⏳ pending

Overall: **Implemented / Pending Review**

## Phase 6.4 implementation

Status: 🔄 **Implemented / Pending Review** (implementation complete — automated verification passed, manual verification pending, ChatGPT review pending)

Implemented (portfolio-level capital allocation & risk-control infrastructure ONLY — no SPAN calculator, no broker-margin replacement, no Return on Capital / Margin recomputation, no Capital Efficiency Score, no trading signals, no strategy recommendations, no execution blocking, no new broker APIs, no new polling, no backtesting, no deployment):

### Capital allocation architecture

- **Pure domain module** (`frontend/lib/calculations/capitalAllocation.js`): `calculateStrategyAllocation`, `calculatePortfolioAllocation`, `calculateAllocatedCapitalRatio`, `calculateCapitalConcentration`, `calculateRiskExposure`, `calculateAllocationLimits`, `calculatePortfolioRiskControls`. Deterministic, pure, side-effect free, dependency-light, user-data agnostic, broker-independent (no network, no broker calls). It CONSUMES the Phase 6.2 analytical capital result and the authoritative theoretical max loss — no payoff/risk/premium/option-price formula is duplicated (§38, asserted by tests).
- **Source awareness (§3/§10)**: Paper Available Cash, Broker Available Funds, Premium Outlay, Estimated Capital, Broker Margin, Defined Risk / Max Loss, Capital Used, Capital Allocation and Capital Efficiency stay strictly separate — "capital used" is never a synonym for broker margin, and every figure carries its basis/source.
- **Coverage semantics (§37)**: null / NaN / Infinity members count as MISSING — an aggregate either states PARTIAL coverage or returns unavailable; nothing is silently treated as ₹0. Two small domain corrections surfaced by the tests: null members now count toward partial coverage (previously dropped), and a mixed-expiry structure preserves its `MIXED_EXPIRY_APPROXIMATION` flag even when it contributes no value to the chosen basis.

### Strategy allocation

- One logical allocation unit per OPEN strategy execution (§27) — multi-leg strategies are never double-counted by summing legs; per-strategy rows carry `executionId`, `strategyTag`, `openPositions`, `premiumOutlay`, `estimatedCapital`, `brokerMargin`, `definedRisk`, `capitalBasis`, `riskBasis`, `allocationStatus`, `warnings`.
- **Current remaining quantity (§26)**: positions/legs reflect what is still open after partial exits and reversals; closed and zero-quantity positions are excluded at the source (backend open-position invariant), never counted into current exposure.
- **Premium basis (§6)**: Phase 6.2 PREMIUM results (defined-debit strategies) flow through unchanged; **risk basis**: RISK_MODEL / MAX_LOSS for same-expiry defined-risk strategies.
- **Defined risk (§8/§28/§29)**: `abs(maxLoss)` from the authoritative theoretical payoff/risk engine for same-expiry finite-risk structures; unlimited risk → `definedRisk = null` + `UNLIMITED_RISK` (never an arbitrary large number); mixed-expiry → `null` + `MIXED_EXPIRY_APPROXIMATION` (never a fabricated cross-expiry number).

### Portfolio allocation

- Descriptive aggregates (§9): open strategy count, open position count, total premium outlay, total estimated capital, total defined risk, paper starting capital, paper available cash, broker available funds, broker-reported aggregate margin — with per-aggregate coverage.
- **Additivity rule (§10)**: only mathematically additive values are summed (premium outlay, estimated capital, defined risk); per-strategy broker margins are NEVER summed into an account figure (`BROKER_MARGIN_NOT_ADDITIVE` when only per-strategy rows exist; the broker-reported account aggregate is preferred).
- **Allocation ratio (§11/§12)**: `allocatedCapitalRatio` with an explicit denominator — the Paper Trading view defaults to Paper Starting Capital / Paper Available Cash (paper values are never relabeled as broker funds and vice versa); `PAPER_STARTING_CAPITAL | PAPER_AVAILABLE_CASH | BROKER_AVAILABLE_FUNDS | BROKER_MARGIN_CAPACITY` are all supported with labels.

### Risk exposure

- Neutral BUY/SELL and CALL/PUT contract exposure (§18) from CURRENT legs (`qty × lotSize`) — measured in contracts, never labeled bullish/bearish, never a signal.

### Concentration

- Descriptive concentration (§13/§16/§17) by strategy execution, underlying symbol, and expiry, over estimated capital / premium outlay / defined risk bases — execution identity is used internally, never merged by strategy tag (§15); no NIFTY-specific logic (§16); expiry concentration never infers directional risk.
- **Risk concentration (§14)**: finite defined-risk shares of total defined risk; unlimited-risk strategies are excluded from the finite denominator and surfaced as `unlimitedRiskStrategyCount` + `unlimitedRiskExposure = true` — never a fabricated percentage.

### Limit framework

- Configurable, pure limit rules (§21/§22/§23): `maxEstimatedCapitalAllocationPct`, `maxDefinedRiskPct`, `maxSingleStrategyAllocationPct`, `maxSingleStrategyRiskPct`, `maxUnderlyingConcentrationPct`, `maxOpenStrategies`, `allowUnlimitedRisk` — each returning `{rule, configured, threshold, actual, status, breached, warnings}` with statuses `NOT_CONFIGURED | OK | WARNING | BREACHED | UNAVAILABLE`. Default: **limits disabled** until explicitly configured; a 90% warning band is documented and overrideable.
- **Monitoring only (§24/§42)**: a breach never blocks paper execution — the market-hours gate, order execution, exit logic, bulk exit, idempotency and broker execution are untouched; missing data never auto-breaches (§22).

### Data quality handling

- Every allocation/risk output carries `AVAILABLE | PARTIAL | UNAVAILABLE`; unavailable = null (never 0), no NaN/Infinity, no fabricated broker margin / estimated capital / max loss / risk / available funds / concentration (§37/§38).

### Phase 6.2 integration

- The Phase 6.2 `analyzeCapital` result is consumed per open strategy as-is (§6) — its basis is normalized (`premium` → PREMIUM, `risk_model` → RISK_MODEL, `max_loss` → MAX_LOSS, else UNAVAILABLE) and its warnings propagate; no duplicate analytical capital formula exists (test 36).

### Phase 6.3 integration

- Portfolio totals feed the Phase 6.3 metrics (e.g. `calculateReturnOnCapital` consumes `totalEstimatedCapital` as its explicit denominator) — Premium ROI / Return on Capital / Return on Margin are never recomputed in this phase (test 37); the allocation table shows per-strategy Estimated Capital, Broker Margin and Defined Risk so the Phase 6.3 Return-on-Risk-Capital denominator is now visible per strategy.

### UI

- **PortfolioAnalyticsPanel** gains a **CAPITAL ALLOCATION & RISK · OPEN STRATEGIES** section (§32): summary cards (Paper Capital / Allocated Capital / Remaining Cash / Broker Margin / Defined Risk / Unlimited-Risk strategies / highest Capital Concentration / highest Risk Concentration), an **ALLOCATION BY STRATEGY** table (Strategy / Open Legs / Estimated Capital / Broker Margin / Defined Risk / Capital % / Risk % — unavailable renders N/A, never 0, unlimited risk renders "UNLIMITED RISK"), descriptive CONCENTRATION chips (by strategy / underlying / expiry), a CONTROL LIMITS note (monitoring only, disabled by default), neutral BUY/SELL/CALL/PUT EXPOSURE chips, a data-quality status badge and structured warnings. Pure display only — no formulas duplicated in the component.
- Standalone (non-execution) open positions form their own allocation row; the dashboard stays compact and never overcrowds.

### Files changed

- `frontend/app/paper/PortfolioAnalyticsPanel.js` (CAPITAL ALLOCATION & RISK section)
- `frontend/app/paper/PortfolioAnalyticsPanel.test.js` (2 new UI tests)
- `docs/PROJECT_STATUS.md` (this update)

### Files created

- `frontend/lib/calculations/capitalAllocation.js` (pure domain module)
- `frontend/lib/calculations/capitalAllocation.test.js` (40-test matrix)

### Tests

- Frontend: 678/678 tests passed (30 files) — 42 new (40-item Phase 6.4 domain matrix §39 + 2 panel render tests)
- Backend: 325/325 tests passed (unchanged — no backend code modified)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

### Manual verification required

- Open a paper portfolio with ≥1 defined-risk strategy and verify the ALLOCATION BY STRATEGY rows, concentration chips and data-quality badge; verify unavailable values render N/A (e.g. without a broker session) and that no value is ever shown as a fabricated ₹0; verify the section stays empty-state friendly with no open positions.
- Phase 6.1 live Upstox verification and Phase 6.3 manual verification remain pending (owner).

### Known limitations

- Control limits are not yet persisted or configurable from the UI (defaults disabled) — persistence of user-scoped settings is deferred until a demonstrated need (§35).
- Portfolio-level Return on Risk Capital remains N/A (Phase 6.3 contract) — per-strategy defined risk is now visible in the allocation table; an exit-period portfolio denominator is a future-phase decision.
- Standalone legacy positions (no strategy execution) are grouped as one "Standalone" allocation row.

### Git

No commit. No push. Implementation left in the working tree for the owner's review.

### Deployment

No deployment.

## Phase 6.4.1 implementation

Status: 🔄 **Implemented / Pending Review** (implementation complete — automated verification passed, manual verification pending, ChatGPT review pending)

Implemented (READ-ONLY broker connection/profile diagnostics — NOT a trading feature; no execution changes, no signals, no polling, no new auth flow):

### Upstox profile API

- `get_broker_profile(access_token)` in `backend/app/services/upstox.py` reuses the EXISTING Upstox HTTP client and `UpstoxError` handling for `GET /v2/user/profile` (Bearer token, server-side only). No new authentication flow; users never paste tokens into the website.

### Profile fields

- `backend/app/services/broker_profile.py` normalizes the profile to a SAFE allow-list contract: `user_name`, `email`, `user_id`, `broker`, `user_type`, `account_type` (Upstox's profile API does not report it → null, never fabricated), `is_active`, `exchanges`, `products`, `order_types`, `poa`, `ddpi`. Missing optional fields are null; the raw broker payload is never returned; `assert_no_secrets` guards the contract against credential fields.

### Backend endpoint

- `GET /paper/broker/profile` (`app/routers/paper.py`, response model `BrokerProfileOut`): authenticated session required, user-scoped, server-side broker call, structured error response, no mutation, always available regardless of market status. `?refresh=true` bypasses the short TTL cache (manual refresh).

### Connection diagnostics

- `frontend/lib/brokerDiagnostics.js` (pure/derived layer — NO network calls; receives already-fetched results): CONNECTION HEALTH items PROFILE / FUNDS / MARGIN / MARKET STATUS / OPTION CHAIN, each with `AVAILABLE | UNAVAILABLE | PARTIAL | UNKNOWN`, plus overall `CONNECTED | PARTIAL | DISCONNECTED` (§13). The broker profile call is the primary connection verification — never "connected" merely from a session cookie; margin down ≠ broker disconnected (PARTIAL, not DISCONNECTED).

### Capabilities

- `brokerCapabilities(profile)` derives ACCOUNT CAPABILITIES only from reported data (NFO segment, options products, MARKET/LIMIT/SL order types, POA, DDPI) with explicit state words (ENABLED/PERMITTED/AUTHORIZED vs DISABLED/NOT PERMITTED/NOT AUTHORIZED) — nothing is inferred that the API does not report; NFO is never hard-coded enabled.

### Cache

- Backend user-scoped TTL cache (key `profile:{user_id}`, 300 s): one user's profile is never served to another user (§18); cached responses carry `cached: true` and the ORIGINAL `generated_at` — stale data is never presented as real-time (§29); manual Refresh bypasses the cache. Profile is not tick data — the frontend never polls.

### Security

- Credentials (access_token, refresh_token, api_key, api_secret, client_secret, authorization codes) are never returned by the API nor rendered by the UI; regression tests assert their absence on both sides. Broker error messages are human-readable — never raw provider errors or stack traces.

### Error handling

- Structured codes (§9): `BROKER_AUTH_REQUIRED`, `BROKER_TOKEN_EXPIRED` (401/403 → UI shows BROKER SESSION EXPIRED + [Reconnect Broker]), `BROKER_RATE_LIMITED` (429), `BROKER_MAINTENANCE` (423), `BROKER_BAD_RESPONSE` (malformed payload), `BROKER_NETWORK_ERROR`, `BROKER_PROFILE_UNAVAILABLE` (generic).

### User isolation

- All fetches/cache entries are scoped by the authenticated session; endpoint tests verify two sessions never cross-contaminate (broker profile of user A is never served to user B).

### UI

- **BrokerConnectionPanel** (`frontend/app/paper/BrokerConnectionPanel.js`) rendered under the Capital panel on `/paper`: BROKER CONNECTION chip (🟢 UPSTOX CONNECTED / 🟡 PARTIAL / 🔴 DISCONNECTED), user / account / status / Last verified (+ CACHED marker), CONNECTION HEALTH rows, ACCOUNT CAPABILITIES chips, expandable PROFILE DETAILS, [Refresh Connection]. Unavailable state shows the structured reason (never "Unknown User"); expired session shows BROKER SESSION EXPIRED + [Reconnect Broker]. The panel consumes the ALREADY-FETCHED capital / market-status / chain state — no duplicated network calls (§22/§23/§24/§25).

### Files changed

- `backend/app/services/upstox.py` (profile fetch)
- `backend/app/routers/paper.py` (GET /paper/broker/profile)
- `backend/app/schemas.py` (BrokerProfileOut)
- `frontend/lib/api.js` (getBrokerProfile(refresh))
- `frontend/app/paper/page.js` (profile state + panel wiring)
- `docs/PROJECT_STATUS.md` (this update)

### Files created

- `backend/app/services/broker_profile.py` (normalize + structured errors + user-scoped TTL cache)
- `backend/tests/test_broker_profile.py` (backend test matrix)
- `frontend/lib/brokerDiagnostics.js` + `brokerDiagnostics.test.js` (pure diagnostics)
- `frontend/app/paper/BrokerConnectionPanel.js` + `BrokerConnectionPanel.test.js` (UI card)

### Tests

- Frontend: 714/714 tests passed (32 files) — new: 23 diagnostics unit tests + 11 panel render tests + 2 API helper tests
- Backend: 353/353 tests passed — 28 new (14-item matrix at service + endpoint level)
- `npx next build`: passed; all 6 routes generated; no type/lint errors

### Manual verification required

- Authenticated Upstox user profile appears with matching name/account/status; exchanges/capabilities match the broker response; Refresh updates Last Verified; Funds/Margin diagnostics match the Phase 6.1 capital panel state; Market-status diagnostic matches the current segment; Option-chain diagnostic matches loaded chain state; expired/invalid broker session shows disconnected/expired state; no sensitive credentials visible anywhere.
- Phase 6.1 / 6.2 / 6.3 / 6.4 manual verification remain pending (owner).

### Known limitations

- Profile caching is in-memory per backend process (restart clears it — same single-user MVP trade-off as the token store).
- `account_type` stays null because Upstox's profile API does not report it (never fabricated).
- Option-chain diagnostic is UNKNOWN until an expiry is actually required (no invented chain state).

### Git

No commit. No push. Implementation left in the working tree for the owner's review.

### Deployment

No deployment.


## Phase 6.6.4 — Production-Grade Positions Module & Broker-Ready Position Lifecycle

### Status: Implemented (working tree — pending review)

### What was built

- **Enhanced backend positions endpoint** (`GET /paper/positions`): backward-compatible; new query params (`status`, `symbol`, `option_type`, `strategy_execution_id`, `limit`, `offset`) enable server-side filtering
- **`get_positions_enriched()`** (`backend/app/services/paper_execution.py`): batched StrategyLegExposure and PaperOrder enrichment per position, with derived `side` (LONG/SHORT/CLOSED)
- **Production-grade Positions frontend** (`frontend/app/positions/page.js`):
  - Execution context banner (PAPER — Simulated)
  - Tabs: Open | Closed | All (with count badges)
  - Filters: Symbol, Option Type, Strategy
  - Summary: open count, long count, short count, realized P&L
  - Positions table: Side, Symbol, Expiry, Strike, CE/PE, Qty/Lots, Avg Entry, Realized P&L, Strategy, Status
  - Expanded detail panel: Position, Instrument, Pricing, P&L, Strategy (with leg attribution table), Order Trace (entry/exit orders), Broker
  - Loading, error, empty states with retry
- **Frontend tests** (`frontend/app/positions/Positions.test.js`): 45 new tests covering all components, edge cases, and static architecture audit
- **API function** (`getPaperPositionsFiltered()` in `frontend/lib/api.js`)

### Architecture

```
GET /paper/positions?status=open&symbol=NIFTY&option_type=call
    ↓
get_positions_enriched()
    ↓
Position (authoritative net exposure)
    +
StrategyLegExposure (batched per-position attribution)
    +
PaperOrder (batched entry/exit orders)
    +
StrategyExecution (strategy tags)
    ↓
Enriched position with side, lots, leg attribution, order trace
```

### Schema / migration

None. No database changes.

### Automated verification

- Backend: **626/626 tests passed** (unchanged)
- Frontend: **865/865 tests passed** (45 new in `tests/test_positions_page.js`)
- `npx next build`: passed; all routes generated

### Known limitations

- Current price (LTP/mark) is N/A server-side — the frontend chain cache supplies it where loaded
- Unrealized P&L requires market marks — shown as N/A
- Exit controls are not wired in this phase (future Phase 6.6.5+)
- Strategy filter dropdown is not yet dynamically populated from the backend

### Phase 6.6.5 — Unified Position & Strategy Exit Workspace

**Status: Implemented (working tree — pending review)**

**What was built:**

1. **Leg-aware exit execution** (`backend/app/services/paper_execution.py`):
   - `exit_position()` now accepts optional `exit_side` parameter — when provided, uses it instead of deriving from `Position.net_quantity`
   - `exit_position()` now accepts optional `target_exposure_id` — when provided, reduces THAT specific StrategyLegExposure instead of FIFO across dominant side
   - PaperOrder correctly records the exit_side (not the net-derived side)

2. **Targeted exposure allocation** (`backend/app/services/leg_exposure.py`):
   - `maintain_exposure_on_exit()` accepts `target_exposure_id` — directly reduces the specified exposure
   - Added `db.flush()` to `apply_exit_allocations()` for visibility within transactions
   - FIFO fallback preserved when no target_exposure_id is provided

3. **ExecutionRouter leg-aware routing** (`backend/app/services/execution_intent.py`):
   - `_execute_paper()` now passes `exit_side` and `target_exposure_id` from ExecutionTarget to exit_position()
   - Ensures the server-resolved exit_side flows through to the actual paper execution

4. **Exit Preview endpoint** (`POST /paper/exit-intent/preview`):
   - Server-authoritative preview that resolves targets WITHOUT mutating state
   - Returns resolved targets with source_action, exit_side, quantity, remaining_quantity
   - Warns that market prices will be resolved at execution time
   - Does NOT create orders, positions, cash changes, or journal entries

5. **Exit Preview schema** (`backend/app/schemas.py`):
   - Added `ExitIntentPreviewOut` with status, targets, errors, warnings

6. **Frontend Exit Workflow** (`frontend/app/positions/page.js`):
   - ExitFlow component: selector (scope, option_type, action, quantity) → preview → confirm → result
   - Exit button in position detail panel
   - Preview shows instrument, strategy, source action, exit side, quantity, remaining after
   - Confirmation flow with structured result display
   - PAPER mode indicator
   - Loading, error, empty states

7. **Frontend API** (`frontend/lib/api.js`):
   - `previewExitIntent(payload)` — POST /paper/exit-intent/preview
   - `confirmExitIntent(payload)` — POST /paper/exit-intent

**Critical defect fixed:**
- Previously, `exit_position()` derived the transaction side from `Position.net_quantity`, ignoring the target's `exit_side`. This meant a user targeting Strategy B's SELL CE exposure on a net-long position would get a SELL execution instead of the correct BUY.
- Previously, `maintain_exposure_on_exit()` used FIFO across the dominant side, meaning targeting Strategy B's exposure could reduce Strategy A's exposure instead.
- Both issues are now fixed with targeted exposure allocation.

**Shared-instrument test:**
- Strategy A: BUY CE × 2, Strategy B: BUY CE × 5 (same instrument)
- Exit Strategy B / BUY CE / ALL → B=0, A=2, Net=+2 ✅
- Strategy A: BUY CE × 2, Strategy B: SELL CE × 1 (same instrument, net=+1)
- Exit Strategy B / SELL CE / ALL → BUY CE execution, B=0, A=2, Net=+2 ✅

**BACKWARD COMPATIBILITY:**
- Legacy `POST /paper/positions/{id}/exit` unchanged (no exit_side param → auto-derives)
- Legacy `POST /paper/positions/exit-all` unchanged
- Legacy `POST /paper/executions/{id}/exit-all` unchanged
- `POST /paper/exit-intent` unchanged (already passes exit_side from targets)

**LIVE execution remains DISABLED.**

---

### Phase 6.6.6 — Live Position Valuation & P&L Workspace

**Status: Implemented (working tree — pending review)**

**What was built:**

1. **Server-authoritative valuation service** (`backend/app/services/valuation.py`):
   - `PositionValuationService` resolves live market prices (LTP) for open positions via the existing broker gateway → Upstox adapter → `get_option_chain()` pipeline
   - Calculates Live P&L: `(LTP - avg_entry) × lots × lot_size` for long; inverse for short
   - Calculates Market Value: `LTP × lots × lot_size`
   - Calculates P&L %: `(live_pnl / market_value) × 100`
   - Strategy-level and leg-level aggregation from `StrategyLegExposure` records
   - Data quality: explicit `val_status` (available / unavailable / stale) and `price_status` fields
   - Never interprets missing LTP as zero; returns `null`/`"unavailable"` explicitly
   - User isolation: only returns valuations for the authenticated user's positions

2. **Valuation endpoint** (`GET /paper/positions/valuation`):
   - Returns per-position valuation with strategy-level and leg-level breakdowns
   - Summary with total unrealized P&L, total market value, and count of open positions

3. **Valuation schemas** (`backend/app/schemas.py`):
   - `LegValuationOut`, `StrategyValuationOut`, `PositionValuationOut`, `ValuationSummaryOut`

4. **Frontend live P&L display** (`frontend/app/positions/page.js`):
   - Position row shows LTP, Live P&L with sign, P&L %, and market value
   - PositionDetails shows: Current LTP, Price Source, Live P&L, Total P&L
   - Strategy/leg-level P&L breakdown
   - Contracts display alongside lot quantity

5. **Frontend API** (`frontend/lib/api.js`):
   - `getPaperPositionsValuation()` — GET /paper/positions/valuation

6. **Comprehensive tests** (`backend/tests/test_valuation.py` — 22 tests):
   - Long/short Live P&L, lot-size, market value, P&L %, missing/stale LTP
   - Strategy/leg aggregation, shared instrument isolation
   - Closed position excluded, user isolation, auth required

**LIVE execution remains DISABLED.**

### Phase 6.6.4.y — Positions Endpoint Routing Correction

**Problem**: The "All" tab on the Positions page sent `{ limit: 500 }` with no `status` param. The backend router condition `if any([status, symbol, option_type, strategy_execution_id])` did NOT include `limit`, so the request fell through to the legacy `get_open_positions()` path — returning only open positions instead of all.

**Fix** (server-side, authoritative):
1. Added `all=true` query parameter to `GET /paper/positions` router
2. Router condition updated: `use_enriched = _all or any([status, symbol, option_type, strategy_execution_id])`
3. `get_positions_enriched()` gains `include_closed` param (signal only; the service already returns all when no status filter is set)
4. Frontend "All" tab now sends `all=true` instead of relying on `limit=500`
5. Counts fetch also uses `all=true`
6. 15 backend regression tests added proving routing, filtering, pagination, user isolation, and backward compatibility

**Backward compatibility preserved**: `GET /paper/positions` with no params still returns open positions via the legacy path.

---

## Phase 6.6.3 — Production-Grade Orders Module & Broker-Ready Order Lifecycle

### Status: Implemented (working tree — pending review)

### What was built

**1. Server-side order filtering** (`backend/app/routers/paper.py`, `paper_execution.py`)
- Enhanced `GET /paper/orders` with query parameters: `status`, `symbol`, `action`, `option_type`, `kind`, `strategy_execution_id`, `limit`, `offset`
- Backward-compatible: no parameters returns the same data as before
- `limit` defaults to 200, max 500; `offset` for pagination
- Strategy tags attached in one batched lookup

**2. Enhanced OrderOut schema** (`backend/app/schemas.py`)
- Added `updated_at` field
- Added `strategy_tag` and `strategy_execution_id` fields (resolved by service layer)

**3. Component-decomposed Orders page** (`frontend/app/orders/page.js`)
- `OrderStatusBadge`, `OrderSideBadge`, `OrderOptionBadge` — reusable badges
- `OrderTabs` — tab bar with count badges
- `OrderFilters` — server-side filter controls (symbol, side, type, kind)
- `OrderRow` — table row with expand/collapse
- `OrderDetails` — structured 6-section detail panel (Order, Instrument, Request, Execution, Attribution, Broker)
- `EmptyState`, `ErrorState` with retry
- `getPaperOrdersFiltered()` API function added

**4. Backend tests** (`backend/tests/test_orders_api.py`)
- 22 tests covering: backward compatibility, filters, pagination, strategy tags, user isolation, authentication, no broker leakage, partial execution

**5. Frontend tests** (`frontend/app/orders/Orders.test.js`)
- 51 tests covering: badges, tabs, filters, order details, row expand/collapse, broker neutrality, quantity representation, null fields

### Files created
- `backend/tests/test_orders_api.py`
- `frontend/app/orders/Orders.test.js`

### Files modified
- `backend/app/schemas.py`, `backend/app/routers/paper.py`, `backend/app/services/paper_execution.py`
- `frontend/app/orders/page.js`, `frontend/lib/api.js`, `docs/PROJECT_STATUS.md`

### Database changes
None.

### Git status
No commit. No push. Working tree.

## Phase 6.6.0–6.6.2 — Trading Workstation Foundation, Application Shell & Orders Module

### Status: Implemented (working tree — pending review)

### What was built

**1. Application Shell** (`components/Shell.js`)
- Fixed top bar with execution mode badge (PAPER / LIVE), market status indicator
- Collapsible sidebar with 9 navigation modules
- Responsive mobile drawer with overlay

**2. Information Architecture**
- `/dashboard` — Option Chain (existing)
- `/orders` — Orders module (fully functional)
- `/positions` — Positions (functional, reads existing API)
- `/strategies` — Strategies (links to Builder)
- `/portfolio`, `/market`, `/brokers`, `/settings`, `/activity` — navigation-ready placeholders

**3. Orders Module** (`app/orders/page.js`)
- Tabs: All, Open, Executed, Rejected, Cancelled with count badges
- Full order table with expandable detail rows
- Uses existing `GET /paper/orders` API

**4. Execution Context**
- Top bar shows PAPER with "Simulated — no broker orders"
- LIVE is architecturally present but disabled

**5. Documentation**
- Blueprint: product vision now describes PAPER + LIVE execution modes
- All existing functionality preserved

### Files created
- `components/Shell.js`, `app/orders/page.js`, `app/positions/page.js`, `app/portfolio/page.js`, `app/strategies/page.js`, `app/market/page.js`, `app/brokers/page.js`, `app/settings/page.js`, `app/activity/page.js`

### Files modified
- `app/layout.js`, `docs/PROJECT_MASTER_BLUEPRINT.md`, `docs/PROJECT_STATUS.md`

### Database / backend changes
None. Uses existing endpoints.

### Git status
No commit. No push. Working tree.

## Next phase objective — Phase 6.5

Phases 6.4 (Capital Allocation / Portfolio Risk Controls) and 6.4.1 (Broker Profile & Connection Diagnostics) are implemented and pending review. The next milestone is **Phase 6.5 — Portfolio Risk Controls / Optional Execution Guardrails** (optional, explicitly configured execution guardrails built on the Phase 6.4 monitoring-only limit framework). Do NOT implement Phase 6.5 until Phases 6.4 / 6.4.1 are verified and approved. Phase 6.1 (Upstox broker margin), Phase 6.2 (analytical capital model) and Phase 6.3 (capital efficiency) remain implemented / pending the owner's review.

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

**User:** Manually verify Phase 6.3 — Portfolio Analytics shows the "Capital efficiency · since inception" cards with explicit denominators (Premium ROI ÷ premium outlay, Return on Capital ÷ estimated capital, Return on Margin ÷ broker-reported margin; N/A when a denominator is genuinely unavailable — never substituted, never 0%); completed journal rows show a Premium ROI column; Strategy Review shows RETURNS (AT MAX PROFIT · PROJECTED) with Return on Capital and Return on Risk Capital (N/A + UNLIMITED_RISK for unlimited structures); no percentage is ever shown without its denominator. Then ChatGPT reviews the working-tree diff. Phase 6.3 remains in the working tree — the project owner commits it from the Changes panel (FreeBuff does not commit or push).

Also pending: **User:** Manually verify Phase 6.2 (Strategy Review CAPITAL section shows Estimated Capital with ESTIMATED · PREMIUM BASIS / RISK BASIS · DEFINED LOSS and Broker Margin as BROKER REPORTED · live refresh not performed in builder; both values stay independent). Also pending Phase 6.1 (capital panel shows live Broker Available Funds / Broker Margin Used and per-strategy Broker Margin with BROKER REPORTED badges during market hours; funds maintenance window shows UNAVAILABLE; duplicate loads reuse the cached broker snapshot) and the Phase 6.0 market-hours verification.

Also pending: **User:** Manually verify Phase 6.4.1 (the Broker Connection card shows the authenticated Upstox profile with matching name/account/status; CONNECTION HEALTH rows match the live capital panel's funds/margin, the market-status badge and the loaded option chain; Refresh Connection updates Last Verified; an expired/invalid broker session shows BROKER SESSION EXPIRED with Reconnect Broker; no credential values are visible anywhere).
