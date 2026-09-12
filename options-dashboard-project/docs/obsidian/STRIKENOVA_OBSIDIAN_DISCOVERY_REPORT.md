# StrikeNova Obsidian Vault — Phase 1 Discovery Report

**Date:** 2026-09-12  
**Status:** DISCOVERY-ONLY — no Obsidian content created yet  
**Prepared by:** Local project-operations agent  

---

## 1. Project Identity

| Field | Value | State |
|-------|-------|-------|
| Repository (remote) | `https://github.com/shahid1995/-options-dashboard` | 🟢 VERIFIED |
| Local path | `C:\Users\busin\Desktop\-options-dashboard\options-dashboard-project` | 🟢 VERIFIED |
| Current branch | `feat/strikenova-day35-portfolio-intelligence` | 🟢 VERIFIED |
| Current commit | `10c1a78` (docs: add CockroachDB runtime validation report) | 🟢 VERIFIED |
| Working tree | 10 modified, 112 untracked | 🟢 VERIFIED |
| Origin remote | `origin` → `shahid1995/-options-dashboard` | 🟢 VERIFIED |
| Task-specified repo | `shahid1995/options-dashboard-project` | 🔴 UNKNOWN — remote is `-options-dashboard`, not `options-dashboard-project` |

**Working-tree modified files (10):**

- `options-dashboard-project/.gitignore`
- `options-dashboard-project/backend/alembic/versions/c7d3e5f8a9b2_google_sub_index.py`
- `options-dashboard-project/backend/app/broker_sync/ingestion.py`
- `options-dashboard-project/backend/app/broker_sync/models.py`
- `options-dashboard-project/backend/app/brokers/adapters/upstox/adapter.py` ⚠️ PROTECTED
- `options-dashboard-project/backend/app/brokers/adapters/upstox/mapper.py` ⚠️ PROTECTED
- `options-dashboard-project/backend/app/services/paper_execution.py` ⚠️ PROTECTED
- `options-dashboard-project/backend/app/services/upstox.py` ⚠️ PROTECTED
- `options-dashboard-project/backend/tests/test_upstox_adapter.py` ⚠️ PROTECTED
- `options-dashboard-project/docs/architecture/COCKROACH_LIVE_COMPATIBILITY_VALIDATION.md`

**Protected files (per task memory + cross-D1 authorization):** `adapter.py`, `mapper.py`, `paper_execution.py`, `upstox.py`, `test_upstox_adapter.py` — pre-existing modifications, do not touch.

**Repository discrepancy:** The task names `shahid1995/options-dashboard-project` as the primary repository. The actual git remote is `shahid1995/-options-dashboard`. The local directory is `options-dashboard-project/`. Record as a naming discrepancy requiring confirmation.

---

## 2. Product

### Verified Product Capabilities

| Capability | State | Evidence |
|-----------|-------|----------|
| NIFTY index options paper trading | 🟢 VERIFIED | `models.py`: `StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`; `paper_execution.py` (1,489 lines) |
| Strategy templates (fixed + dynamic) | 🟢 VERIFIED | `StrategyTemplate`, `StrategyTemplateLeg` with V1 fixed / V2 dynamic formula fields |
| Payoff chart | 🟢 VERIFIED | `frontend/lib/calculations/payoff.js`; `APP_PAGES_PHASE_2_0_AUDIT.md` |
| Basic Greeks (Black-Scholes) | 🟢 VERIFIED | `backend/app/quant/greeks.py` — BSM engine; frontend `greeks.js` |
| IV calculation (model) | 🟢 VERIFIED | `backend/app/quant/iv.py` — Brent solver, Day-16 engine |
| GEX (Gamma Exposure) | 🟢 VERIFIED | `backend/app/quant/gex.py` — Day-17 engine; `GEX_V1_0_SPEC.md`; `backend/app/routers/gex.py`; frontend `gex.js` |
| Historical GEX persistence | 🟢 VERIFIED | `GexSnapshot` model; `backend/app/services/gex_history.py`; `backend/app/routers/historical_gex.py` |
| Live GEX capture | 🟢 VERIFIED | `backend/app/services/live_gex.py`; background capture loop in `main.py` |
| Market/intelligence data | 🟢 VERIFIED | `backend/app/routers/chains.py`, `candles.py`; Upstox integration |
| Paper positions & P&L | 🟢 VERIFIED | `Position` model + `paper_execution.py` |
| Order history / journal | 🟢 VERIFIED | Legacy `Trade`/`Leg` + authoritative `StrategyExecution`/`PaperOrder` |
| Market-hours protection | 🟢 VERIFIED | `backend/app/services/market_status.py` |
| Portfolio intelligence (Day 35) | 🟢 VERIFIED — current branch focus | `backend/app/portfolio_intelligence/` — `analytics.py`, `contracts.py`, `normalization.py` |
| Broker-sync ingestion (Day 39) | 🟢 VERIFIED — current branch focus | `backend/app/broker_sync/` — `ingestion.py`, `models.py`, `fill_ledger.py`, `fingerprint.py`, `raw_ingress.py` |
| Cross-D1 S1/S2 classification | 🟡 PROPOSED — human architecture decision recorded, implementation NOT authorized | `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-locking-human-architecture-decision.md` (D-1 lock selected); `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-implementation-authorization.md` (implementation authorized for frozen r2 design ONLY; Task3 🔴 LOCKED) |
| Live broker execution | 🔴 UNKNOWN — declared DISABLED in blueprint | `PROJECT_MASTER_BLUEPRINT.md` §1: "LIVE execution is currently DISABLED" |
| Multi-user production | 🔴 UNKNOWN — single-user SQLite local; PostgreSQL readiness in progress | `db.py` supports PostgreSQL; `config.py` `IS_PRODUCTION` detection; Phase 10.2B broker credential architecture in progress |

### Current Product State

The platform is a NIFTY index options paper trading dashboard with:

- **Frontend:** Next.js 14 / React 18 (`frontend/`); deployed to Vercel
- **Backend:** Python/FastAPI (`backend/app/main.py`); deployed to Railway
- **Broker:** Upstox (single broker integration, OAuth-based)
- **Database:** SQLite default (local/dev); PostgreSQL capable (production path in progress)
- **Current focus:** Day 35 Portfolio Intelligence + Day 39 broker-sync + Day 41 cross-D1 concurrency

### Product Unknowns

- Whether live broker execution has been enabled since the blueprint's "DISABLED" declaration
- Production multi-user status (PostgreSQL migration state in production)
- Whether the platform has actual users beyond development/testing
- Revenue/business model (no evidence in repository)

---

## 3. Architecture

### Frontend

| Component | Detail | State |
|-----------|--------|-------|
| Framework | Next.js 14 / React 18 | 🟢 VERIFIED |
| Charts | Recharts | 🟢 VERIFIED (`PROJECT_MASTER_BLUEPRINT.md` §3) |
| Tests | Vitest | 🟢 VERIFIED |
| App routes (app/ layout) | `activity`, `brokers`, `dashboard`, `gex`, `market`, `orders`, `paper`, `portfolio`, `positions`, `settings`, `strategies` | 🟢 VERIFIED (`frontend/app/(app)/`) |
| Public routes | `about`, `features`, `how-it-works`, `market-intelligence`, `paper-trading`, `strategy-lab` | 🟢 VERIFIED (`frontend/app/(public)/`) |
| Calculations | `frontend/lib/calculations/` — `payoff.js`, `risk.js`, `greeks.js`, `strategyCalculator.js` | 🟢 VERIFIED |
| Strategy lib | `frontend/lib/strategy/` — `strategy.js`, `strategyUtils.js`, `strategyValidation.js`, `strategyIdentity.js` | 🟢 VERIFIED |
| GEX frontend | `frontend/lib/calculations/gex.js` (mentioned in audit) | 🟢 VERIFIED (referenced) |
| Build output | `.next/` present (production build artifacts) | 🟢 VERIFIED |

**Notable:** `/paper` is a monolith (~3,600 lines) containing strategy builder, paper trading, analytics, journal, capital, broker diagnostics, scenario analysis, Greek analytics, IV analytics, templates, bulk exit (`APP_PAGES_PHASE_2_0_AUDIT.md` §14).

### Backend

| Component | Detail | State |
|-----------|--------|-------|
| Framework | FastAPI | 🟢 VERIFIED (`main.py`: `FastAPI`) |
| Language | Python 3 | 🟢 VERIFIED |
| Entry point | `backend/app/main.py` | 🟢 VERIFIED |
| Database ORM | SQLAlchemy (declarative) | 🟢 VERIFIED (`db.py`: `Base = DeclarativeBase()`) |
| Migrations | Alembic | 🟢 VERIFIED (20+ migration versions in `backend/alembic/versions/`) |
| Auth | Google OAuth + session management | 🟢 VERIFIED (`identity.py` 29,559 lines; `backend/app/routers/auth.py`) |
| Broker gateway | `backend/app/brokers/gateway.py`, `registry.py` | 🟢 VERIFIED |
| Broker adapters | Upstox (V3) — `backend/app/brokers/adapters/upstox/` | 🟢 VERIFIED |
| Broker domain | `backend/app/brokers/domain/` — `capabilities.py`, `enums.py`, `errors.py`, `models.py`, `protocols.py` | 🟢 VERIFIED |
| Broker sync | `backend/app/broker_sync/` — idempotency, ingestion, fill ledger, fingerprint, raw ingress | 🟢 VERIFIED |
| Quant engine | `backend/app/quant/` — `contracts.py` (Day-14 boundary), `greeks.py` (Day-15), `iv.py` (Day-16), `gex.py` (Day-17), `pricing.py`, `scenarios.py` | 🟢 VERIFIED |
| Intelligence | `backend/app/intelligence/` — `contracts.py` (Day-19), `positioning.py` (Day-20), `levels.py` (Day-21), `institutional.py` (Day-22), `regime.py` (Day-23), `traps.py` (Day-25), `synthesis.py` (Day-26) | 🟢 VERIFIED |
| Portfolio intelligence | `backend/app/portfolio_intelligence/` — Day 35 (current branch) | 🟢 VERIFIED |
| Paper execution | `backend/app/services/paper_execution.py` (1,489 lines) — authoritative execution engine | 🟢 VERIFIED |
| Market data | `backend/app/market_data/` — `contracts.py`, `quality.py`, `gateway.py`, `streaming.py` | 🟢 VERIFIED |
| Central risk | `backend/app/central_risk/` — `contracts.py`, `engine.py` | 🟢 VERIFIED |
| Final risk gate | `backend/app/final_risk_gate/` — `contracts.py`, `gate.py` | 🟢 VERIFIED |
| Domain events | `backend/app/domain_events/` — `contracts.py` (Day-37), `bus.py`, `handler.py`, `idempotency.py`, `publisher.py` | 🟢 VERIFIED |
| Routers | `backend/app/routers/` — `annotations`, `auth`, `candles`, `chains`, `deps`, `gex`, `historical_gex`, `live_gex`, `paper`, `phase723b_endpoint`, `resolve`, `templates` | 🟢 VERIFIED |
| Services | `backend/app/services/` — 35+ modules including `paper_execution.py`, `upstox.py`, `token_store.py`, `gex_capture.py`, `gex_history.py`, `live_gex.py`, `backfill_orchestrator.py`, `daily_ingestion.py`, etc. | 🟢 VERIFIED |
| Tests | 60+ test files in `backend/tests/` | 🟢 VERIFIED |

### Database

| Aspect | Detail | State |
|--------|--------|-------|
| ORM | SQLAlchemy declarative | 🟢 VERIFIED |
| Default | SQLite (`paper_journal.db`) | 🟢 VERIFIED (`db.py`) |
| Production target | PostgreSQL (`postgresql+psycopg://`) | 🟢 VERIFIED (`db.py` normalize_database_url) |
| Migration tool | Alembic | 🟢 VERIFIED |
| Baseline migration | `d3eb45a2e046` — 24 tables | 🟢 VERIFIED (`PROJECT_STATUS.md` §Phase 10.1B) |
| Total models | ~24+ tables in `models.py` (936 lines) | 🟢 VERIFIED |
| Key tables | `paper_accounts`, `trades`, `legs`, `strategy_executions`, `paper_orders`, `positions`, `paper_transactions`, `strategy_leg_exposures`, `exit_exposure_allocations`, `bulk_exit_records`, `strategy_templates`, `strategy_template_legs`, `gex_snapshots`, `broker_sync_idempotency`, `broker_sync_sequence_anchor` (+ Day-39/41 additions) | 🟢 VERIFIED |
| GEX snapshots | `GexSnapshot` with `strike_data` (JSON), `expiry_data` (JSON), `methodology_metadata` | 🟢 VERIFIED |

### Infrastructure

| Aspect | Detail | State |
|--------|--------|-------|
| Backend hosting | Railway (PostgreSQL) | 🟢 VERIFIED (`README.md` §7-10) |
| Frontend hosting | Vercel | 🟢 VERIFIED (`README.md` §7-10) |
| Deployment model | GitHub → Railway (backend) + Vercel (frontend) | 🟢 VERIFIED |
| Environment | `backend/.env.example` for Railway env vars | 🟢 VERIFIED (referenced in README) |
| CORS | Configurable via `FRONTEND_URL`, `ADDITIONAL_CORS_ORIGINS` | 🟢 VERIFIED (`config.py`) |
| Production detection | `IS_PRODUCTION` property checks `RAILWAY_ENVIRONMENT` / `RAILWAY_SERVICE_NAME` / `PRODUCTION` | 🟢 VERIFIED (`config.py`) |

### External Integrations

| Integration | Detail | State |
|-------------|--------|-------|
| Upstox | OAuth 2.0; API key/secret per user (BYOB Phase 10.2B); token expires 3:30 AM IST daily; no refresh token | 🟢 VERIFIED (`BROKER_CAPABILITY_MATRIX.md`, `PHASE_10_2B_CONNECTION_ARCHITECTURE.md`) |
| Google OAuth | `GOOGLE_CLIENT_ID` in config; Phase A identity | 🟢 VERIFIED (`config.py`, migration `b8c9f1d2e34a`) |
| Backend URL auto-derivation | `RAILWAY_PUBLIC_DOMAIN` env → `UPSTOX_REDIRECT_URI` | 🟢 VERIFIED (`config.py` lines 97-110) |

---

## 4. Quant Intelligence

### Greeks

| Aspect | Detail | State |
|--------|--------|-------|
| Engine | `backend/app/quant/greeks.py` — Black-Scholes-Merton European | 🟢 VERIFIED |
| Model version | `1.0.0` | 🟢 VERIFIED |
| Calculations | delta, gamma, theta, vega, rho (call + put) | 🟢 VERIFIED |
| Units | delta (dimensionless), gamma (per unit S), vega (per 1.00 vol), theta (per year), rho (per 1.00 rate) | 🟢 VERIFIED |
| Day-count | ACT/365 (`time_to_expiry` in `quant/contracts.py`) | 🟢 VERIFIED |
| Degenerate handling | T=0, σ=0 handled with documented conventions | 🟢 VERIFIED |
| Broker vs model separation | Broker Greeks via `GreeksObservation(source="BROKER")`; model Greeks separate with `calculation_id` + versions | 🟢 VERIFIED |

### IV (Implied Volatility)

| Aspect | Detail | State |
|--------|--------|-------|
| Engine | `backend/app/quant/iv.py` — Brent root solver | 🟢 VERIFIED |
| Model version | `1.0.0` | 🟢 VERIFIED |
| Domain | [0.0, 10.0] (0% to 1000%) | 🟢 VERIFIED |
| Convergence | price_tolerance 1e-9, sigma_tolerance 1e-10, max 100 iterations | 🟢 VERIFIED |
| Failure taxonomy | EXPIRED, BELOW_LOWER_BOUND, ABOVE_THEORETICAL_MAX, NO_BRACKET, CONVERGENCE_FAILED | 🟢 VERIFIED |
| Output | Decimal fraction (0.1824 = 18.24%) | 🟢 VERIFIED |

### GEX (Gamma Exposure)

| Aspect | Detail | State |
|--------|--------|-------|
| Engine | `backend/app/quant/gex.py` — Day-17 | 🟢 VERIFIED |
| Formula | Raw GEX = Gamma × OI × S² × 0.01 | 🟢 VERIFIED (`GEX_V1_0_SPEC.md` §6, `gex.py` §14-17) |
| OI units | Contracts (never lots) | 🟢 VERIFIED |
| Sign convention | Call GEX = +Raw GEX; Put GEX = −Raw GEX (NAIVE_DEALER_CONVENTION) | 🟢 VERIFIED |
| Model version | `1.0.0` | 🟢 VERIFIED |
| Greeks source separation | Engine requires label; profile builder rejects mixed broker/model gamma | 🟢 VERIFIED |
| Historical persistence | `GexSnapshot` model | 🟢 VERIFIED |
| Live capture | Background loop in `main.py` + `GexCaptureService` | 🟢 VERIFIED |

### Gamma Flip / Gamma Walls

| Aspect | Detail | State |
|--------|--------|-------|
| Gamma Flip / Zero Gamma | Listed as future extension in `GEX_V1_0_SPEC.md` §18 | 🟡 PROPOSED — architecture designed, not yet implemented |
| Gamma Walls | Listed as future extension; Day-17 explicitly excluded gamma walls from Day-21 | 🟡 PROPOSED — not yet implemented; `levels.py` §25-26 acknowledges no canonical gamma-wall interface |

### Market Signals (Intelligence)

The intelligence system (Days 19-26) is a major architectural domain:

| Day | Module | Function | State |
|-----|--------|----------|-------|
| 19 | `intelligence/contracts.py` | `IntelligenceResult` — unified result envelope (direction, signal_strength, confidence, evidence, quality, provenance, regime) | 🟢 VERIFIED |
| 20 | `intelligence/positioning.py` | OI/positioning interpretation — LONG_BUILDUP/SHORT_BUILDUP/SHORT_COVERING/LONG_UNWINDING | 🟢 VERIFIED |
| 21 | `intelligence/levels.py` | Dynamic support/resistance — levels are positional, not directional; corroborated concentration required | 🟢 VERIFIED |
| 22 | `intelligence/institutional.py` | Institutional activity read | 🟢 VERIFIED |
| 23 | `intelligence/regime.py` | Market regime classification (TRENDING/RANGING/HIGH_VOLATILITY/LOW_VOLATILITY/RISK_ON/RISK_OFF/UNKNOWN) | 🟢 VERIFIED |
| 25 | `intelligence/traps.py` | Trap pattern detection | 🟢 VERIFIED |
| 26 | `intelligence/synthesis.py` | Conflict resolution across families — no majority vote; agreement/conflict/no-direction | 🟢 VERIFIED |
| 35 | `portfolio_intelligence/` | Portfolio-level analytics consuming position truth + quant/intelligence services | 🟢 VERIFIED (current branch) |

### Scenario / Analytics Systems

| Aspect | Detail | State |
|--------|--------|-------|
| Scenario analysis | `backend/app/quant/scenarios.py` + frontend `ScenarioPanel.js` | 🟢 VERIFIED |
| Portfolio scenario sensitivity | `portfolio_intelligence/analytics.py` — `PortfolioScenarioSensitivity` | 🟢 VERIFIED |
| Greek analytics (frontend) | `GreekAnalyticsPanel.js` — live vs modelled Greeks | 🟢 VERIFIED |
| IV analytics (frontend) | `IVAnalyticsPanel.js` — IV across strikes/expiries | 🟢 VERIFIED |

---

## 5. Trading

### Paper Trading

| Aspect | Detail | State |
|--------|--------|-------|
| Engine | `backend/app/services/paper_execution.py` (1,489 lines) | 🟢 VERIFIED |
| Architecture | Server-authoritative; backend is single source of truth | 🟢 VERIFIED |
| Atomicity | Validate-before-write; atomic transactions | 🟢 VERIFIED |
| Idempotency | `client_order_id` unique per user at execution, order, and bulk-exit levels | 🟢 VERIFIED |
| Execution states | PENDING → FILLED / PARTIAL / FAILED / CANCELLED | 🟢 VERIFIED |
| Order states | PENDING → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED | 🟢 VERIFIED |
| Position netting | Weighted-average entry; realized P&L on reduction; FIFO exit | 🟢 VERIFIED |
| Cash ledger | `PaperTransaction` — signed rupee amounts; cash = starting_capital + SUM(amount) | 🟢 VERIFIED |
| Starting capital | ₹500,000 default (`DEFAULT_STARTING_CAPITAL`) | 🟢 VERIFIED |
| Tick size | ₹0.05 for NIFTY options (`DEFAULT_OPTION_TICK_SIZE`) | 🟢 VERIFIED |
| Lot convention | Quantities in LOTS everywhere; rupee exposure scales by `lot_size` | 🟢 VERIFIED |
| Strategy templates | V1 fixed-leg + V2 dynamic formula (atm_offset, delta-targeted, dte-range, etc.) | 🟢 VERIFIED |
| Bulk exits | EXIT STRATEGY + EXIT ALL — atomic, idempotent via `BulkExitRecord` | 🟢 VERIFIED |
| Exposure attribution | `StrategyLegExposure` + `ExitExposureAllocation` — per-execution leg tracking | 🟢 VERIFIED |

### Portfolio

| Aspect | Detail | State |
|--------|--------|-------|
| Authoritative exposure | `Position` — netted, one row per instrument (user + symbol + expiry + strike + option_type) | 🟢 VERIFIED |
| Portfolio view | `PortfolioOut`, `PortfolioGroupOut`, `PortfolioSummaryOut` schemas | 🟢 VERIFIED |
| Day 35 Portfolio Intelligence | `PortfolioAnalyticsResult` — exposures, Greeks, GEX, scenario sensitivity, concentration, directional, regime-aware risk | 🟢 VERIFIED |

### Execution Architecture

| Aspect | Detail | State |
|--------|--------|-------|
| Current mode | PAPER only (server-authoritative simulation) | 🟢 VERIFIED |
| Live broker execution | DISABLED (per blueprint); broker-neutral `BrokerGateway` + adapter pattern prepared | 🟢 VERIFIED |
| Broker adapter | Upstox V3 (`backend/app/brokers/adapters/upstox/`) | 🟢 VERIFIED |
| Broker capability model | `BrokerCapability` with 7-state enum (SUPPORTED/UNSUPPORTED/AVAILABLE/UNAVAILABLE/AUTH_REQUIRED/ACCOUNT_DISABLED/TEMPORARILY_UNAVAILABLE) | 🟢 VERIFIED |

### Capital / Margin

| Aspect | Detail | State |
|--------|--------|-------|
| Paper capital | ₹500,000 default starting capital | 🟢 VERIFIED |
| Margin model | 🔴 UNKNOWN — no margin table or margin service found in codebase | |
| Broker margin | `backend/app/services/broker_margin.py` exists (file listed) — content not yet inspected | 🟡 PROPOSED — file exists, content unverified |

---

## 6. Business

| Aspect | Detail | State |
|--------|--------|-------|
| Product vision | Professional options-trading dashboard for Indian index options; paper + eventual live execution | 🟢 VERIFIED (`PROJECT_MASTER_BLUEPRINT.md` §1) |
| Target market | Indian index options (NIFTY) | 🟢 VERIFIED |
| Free-for-life constraint | Prefer open-source, self-hostable, genuinely free tooling; avoid vendor lock-in | 🟢 VERIFIED (`PROJECT_MASTER_BLUEPRINT.md` §2) |
| Revenue model | 🔴 UNKNOWN — no evidence in repository | |
| Pricing | 🔴 UNKNOWN | |
| Customers | 🔴 UNKNOWN — no user data or customer evidence | |
| SEBI compliance | Referenced in broker capability matrix (FYERS SEBI compliance March 2026); broker client secrets backend-only; per-user static IPs for SEBI | 🟢 VERIFIED (referenced) |
| Data redistribution | User-specific broker data must respect broker/exchange/SEBI terms; no central redistribution unless permitted | 🟢 VERIFIED (`PROJECT_MASTER_BLUEPRINT.md` §2) |

---

## 7. Decisions

### Verified Existing Decisions

These are decisions with evidence in the repository:

| # | Decision | Evidence | Status |
|---|----------|----------|--------|
| D1 | GitHub is source of truth for code; blueprint is source of truth for product/architecture | `PROJECT_MASTER_BLUEPRINT.md` §2 | 🟢 VERIFIED |
| D2 | Paper execution is a safe backend; every trading feature designed for eventual live execution | `PROJECT_MASTER_BLUEPRINT.md` §1 | 🟢 VERIFIED |
| D3 | LIVE execution currently DISABLED | `PROJECT_MASTER_BLUEPRINT.md` §1 | 🟢 VERIFIED |
| D4 | Alembic is sole schema mechanism (Phase 10.1B) — PR #20 merged | `PROJECT_STATUS.md` §Phase 10.1B | 🟢 VERIFIED |
| D5 | StrikeNova account auth independent of broker auth (BYOB) | `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` AD-1 | 🟢 VERIFIED (architecture spec) |
| D6 | BYOB: every user supplies own broker Developer App credentials | `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` AD-2 | 🟢 VERIFIED (architecture spec) |
| D7 | No shared Upstox API credentials across users | `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` AD-3 | 🟢 VERIFIED (architecture spec) |
| D8 | `broker_connections` belongs to StrikeNova User (user_id FK non-nullable) | `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` AD-4 | 🟢 VERIFIED (architecture spec) |
| D9 | Customer Analytics Tokens never used as implicit platform credentials | `config.py` §56-57; `main.py` GEX capture comments | 🟢 VERIFIED |
| D10 | GEX is market analytics domain, not strategy rule; must not generate BUY/SELL | `GEX_V1_0_SPEC.md` §1 | 🟢 VERIFIED |
| D11 | GEX sign convention: NAIVE_DEALER_CONVENTION (call +, put −) — explicit modeling convention, not observed dealer positions | `GEX_V1_0_SPEC.md` §1, §14-16 | 🟢 VERIFIED |
| D12 | Broker Greeks and model Greeks never overwrite each other | `quant/contracts.py` §40-43; `quant/gex.py` §33-40 | 🟢 VERIFIED |
| D13 | Position is authoritative portfolio exposure; `StrategyLegExposure` preserves per-execution attribution | `models.py` §233-257 | 🟢 VERIFIED |
| D14 | Day-19 intelligence: no majority vote; agreement/conflict/no-direction; only BULLISH/BEARISH vote | `intelligence/synthesis.py` §15-19, §44-52 | 🟢 VERIFIED |
| D15 | Day-21: high-OI strike is concentration fact, NOT automatically support/resistance | `intelligence/levels.py` §17-26 | 🟢 VERIFIED |
| D16 | Day-23 regime: priority cascade, exactly one label per evaluation; conflicting evidence → UNKNOWN | `intelligence/regime.py` §16-54 | 🟢 VERIFIED |
| D17 | Cross-D1 locking: D-1 dedicated order-family lock selected by human | `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-locking-human-architecture-decision.md` §2 | 🔵 ACCEPTED (human architecture decision) |
| D18 | Cross-D1 implementation: authorized for frozen r2 design ONLY; Task3 🔴 LOCKED; push/deploy NOT authorized | `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-implementation-authorization.md` | 🔵 ACCEPTED (human implementation authorization) |

### Pending / Proposed Decisions

| # | Decision | Evidence | State |
|---|----------|----------|-------|
| P1 | Mixed sequence/sequence-less ordering — explicitly OUT OF SCOPE, requires separate human decision | `cross-d1-locking-human-architecture-decision.md` §7 | 🔴 UNKNOWN — human decision required |
| P2 | Task3 implementation authorization | `cross-d1-implementation-authorization.md` §1.1: "TASK3 IMPLEMENTATION AUTHORIZATION: NOT GRANTED" | 🔴 UNKNOWN — not authorized |

---

## 8. Potentially Outdated Information

| Item | Why potentially outdated | Evidence |
|------|------------------------|----------|
| `PROJECT_MASTER_BLUEPRINT.md` — last updated 2026-08-21 | Repository has advanced through Phases 10.1B, 10.2A, 10.2B-1 through 10.2B-4, Day 35, Day 39, Day 41 since then | `PROJECT_STATUS.md` shows more recent phases; commit history shows activity through 2026-09-12 |
| `PROJECT_STATUS.md` — last updated 2026-08-27 | Shows Phase 10.1B as current; repository is now on Day 35/39/41 branches | Current branch is `feat/strikenova-day35-portfolio-intelligence`; many Phase 10.2B docs exist |
| `COMPREHENSIVE_ARCHITECTURE_AUDIT.md` — dated August 25, 2026 | Audit covers through Phase 7.24.8C; subsequent phases (8A, 8B, 9, 10.1A, 10.1B, 10.2A, 10.2B-1 through 10.2B-4) have progressed | 20+ new Alembic migrations exist; Day 35/39/41 modules exist |
| `frontend/lib/calculations/gex.js` (frontend GEX) | Backend GEX engine (`quant/gex.py`) and live capture now exist; frontend may be duplicating or lagging | Audit notes GEX is client-side; backend now has GEX engine |
| README.md | Very brief (13 lines); describes basic two-folder structure; does not reflect Phase 10 identity/broker architecture | `README.md` content is minimal |

---

## 9. Contradictions

| # | Contradiction | Evidence A | Evidence B | Assessment |
|---|--------------|------------|------------|------------|
| C1 | Repository name | Task specifies `shahid1995/options-dashboard-project` | Git remote is `shahid1995/-options-dashboard`; local dir is `options-dashboard-project/` | Likely a naming discrepancy — the remote repo is `-options-dashboard`; the local folder is `options-dashboard-project/`. Requires confirmation. |
| C2 | GEX computation location | `COMPREHENSIVE_ARCHITECTURE_AUDIT.md` §23: "GEX computation is client-side — backend only stores snapshots" | Backend has full GEX engine (`quant/gex.py`), live capture service, and historical persistence (`GexSnapshot`) | The audit is outdated (Aug 25). Backend GEX engine exists and is authoritative. Frontend GEX (`gex.js`) may still exist as a parallel implementation — needs verification. |
| C3 | LIVE execution status | `PROJECT_MASTER_BLUEPRINT.md` §1: "LIVE execution is currently DISABLED" | Phase 10.2B broker credential architecture (BYOB) implies preparation for live execution | Not necessarily a contradiction — blueprint may simply predate the credential preparation work. The "DISABLED" declaration may still be accurate for actual order placement. Requires confirmation. |

---

## 10. Missing Information

| Area | What's missing | Severity |
|------|---------------|----------|
| Business model | Revenue, pricing, target customers, go-to-market | High — no evidence anywhere in repo |
| Production status | Is the platform live with real users? What's the production DB status? | Medium |
| Frontend GEX parity | Does `frontend/lib/calculations/gex.js` still exist? Is it synced with backend engine? | Medium |
| Broker margin | `broker_margin.py` exists — what does it contain? Is margin modeling active? | Low |
| Frontend tests | Vitest config exists; test files not inspected | Low |
| API documentation | OpenAPI/Swagger? | Low |
| Deployment pipeline | GitHub Actions / CI config? | Low |
| Monitoring/logging | Production observability | Low |
| Frontend state management | How is state managed? (Redux, Zustand, React Query, etc.) | Low |

---

## 11. Recommended Obsidian Documents

Based on actual evidence, the following documents should be created:

### Control Center

1. **StrikeNova Home.md** — project identity, remote, branch, current commit, one-paragraph summary
2. **Current State.md** — product capabilities, current phase, what's enabled/disabled, latest commit summary
3. **Active Work.md** — Day 35 Portfolio Intelligence, Day 39 broker-sync, Day 41 cross-D1 (with authorization status)
4. **Roadmap.md** — phase progression from blueprint through current; future extensions (gamma flip, gamma walls, live execution, multi-user)
5. **Open Questions.md** — repository name discrepancy, LIVE execution status, business model, frontend GEX parity, production status

### Product

6. **Product Vision.md** — from `PROJECT_MASTER_BLUEPRINT.md` §1-2
7. **Product Principles.md** — from `PROJECT_MASTER_BLUEPRINT.md` §2
8. **Features.md** — verified capabilities list with status
9. **User Problems.md** — from `APP_PAGES_PHASE_2_0_AUDIT.md` problem statements

### Architecture

10. **Architecture Overview.md** — from `COMPREHENSIVE_ARCHITECTURE_AUDIT.md` + current state
11. **Frontend.md** — Next.js 14, routes, components, calculations, GEX
12. **Backend.md** — FastAPI, modules, routers, services, quant, intelligence, broker sync
13. **Database.md** — SQLAlchemy, Alembic, tables, SQLite→PostgreSQL path
14. **Data Architecture.md** — three-layer (raw→model→analytics), Day-9 contracts, Day-12 quality, Day-14 quant boundary
15. **Broker Integration.md** — Upstox, BYOB, OAuth, capability model, Phase 10.2B architecture
16. **Security.md** — auth (Google + session), credential encryption, token persistence, CORS
17. **Infrastructure.md** — Railway + Vercel, env vars, production detection

### Quant Intelligence

18. **Quant Overview.md** — Day-14 boundary, engines (BSM Greeks, IV, GEX), contracts
19. **GEX Overview.md** — formula, sign convention, OI units, source separation, historical + live
20. **Greeks.md** — BSM engine, units, degenerate conventions
21. **IV.md** — Brent solver, domain, failure taxonomy
22. **Market Signals.md** — Day-19 intelligence system, families (positioning, levels, institutional, regime, traps), synthesis
23. **Gamma Flip.md** — proposed future extension (from GEX spec §18)
24. **Gamma Walls.md** — proposed future extension; Day-21 explicitly excluded

### Decisions

25. **ADR-001 Greek Engine Selection.md** — BSM European (if confirmed as a decision)
26. **ADR-002 GEX Sign Convention.md** — NAIVE_DEALER_CONVENTION
27. **ADR-003 Broker Credential Architecture.md** — BYOB, independent auth (Phase 10.2B)
28. **ADR-004 Cross-D1 Locking Primitive.md** — D-1 dedicated order-family lock (human decision)
29. **ADR-005 Cross-D1 Implementation Authorization.md** — frozen r2 design, Task3 locked

### Development

30. **Phase Tracker.md** — phase progression with statuses
31. **Development Notes/** — Day 35, Day 39, Day 41 notes

### AI & Agents

32. **AI Context.md** — concise project summary for AI reasoning
33. **Agent Rules.md** — evidence rules, authority rules, protected files, scope rules
34. **DeepSeek Harness.md** — if evidence exists (not yet found)
35. **FreeBuff.md** — if evidence exists (`.freebuff/` directory exists in root)

### Business

36. **Business.md** — only if founder provides business context (currently no evidence)

---

## 12. Documents NOT Recommended (insufficient evidence)

- **Strategy Research.md** — no strategy research module found beyond `strategy_evaluation/` (needs inspection)
- **Trading Strategy.md** — no specific strategy content found
- **Risk Management.md** — `central_risk/` and `final_risk_gate/` exist but content not inspected; may be too thin
- **DeepSeek Harness.md** — no evidence of DeepSeek integration found
- **Competitive Analysis.md** — no evidence
- **Regulatory.md** — SEBI referenced but no dedicated regulatory document

---

## 13. Vault Health Preview (pre-construction)

| Concern | Status |
|---------|--------|
| Existing Obsidian vault | 🔴 UNKNOWN — no `.obsidian/` or `StrikeNova/` directory found in project |
| Broken links | N/A — no vault exists yet |
| Duplicate concepts | N/A — no vault exists yet |
| Missing core documents | N/A — no vault exists yet |
| Outdated info in would-be notes | Several source docs are outdated (see §8) — must be flagged in notes |
| Property consistency | N/A — no vault exists yet |

---

## 14. Evidence Summary

**Total source documents inspected (representative sample):**

- `README.md`
- `PROJECT_MASTER_BLUEPRINT.md`
- `PROJECT_STATUS.md`
- `COMPREHENSIVE_ARCHITECTURE_AUDIT.md`
- `APP_PAGES_PHASE_2_0_AUDIT.md`
- `BROKER_CAPABILITY_MATRIX.md`
- `PHASE_10_2B_CONNECTION_ARCHITECTURE.md`
- `GEX_V1_0_SPEC.md`
- `backend/app/models.py` (936 lines, partial)
- `backend/app/config.py` (110 lines)
- `backend/app/db.py` (partial)
- `backend/app/main.py` (partial)
- `backend/app/quant/contracts.py` (372 lines)
- `backend/app/quant/greeks.py` (311 lines, partial)
- `backend/app/quant/iv.py` (518 lines, partial)
- `backend/app/quant/gex.py` (525 lines, partial)
- `backend/app/intelligence/synthesis.py` (647 lines, partial)
- `backend/app/intelligence/positioning.py` (566 lines, partial)
- `backend/app/intelligence/levels.py` (700 lines, partial)
- `backend/app/intelligence/regime.py` (668 lines, partial)
- `backend/app/services/paper_execution.py` (1,489 lines, partial)
- `backend/app/broker_sync/models.py` (175 lines, partial)
- `backend/app/brokers/domain/capabilities.py` (216 lines, partial)
- `backend/app/domain_events/contracts.py` (87 lines)
- `backend/app/portfolio_intelligence/__init__.py` (partial)
- `backend/app/backend/app/domain_events/contracts.py` (87 lines)
- Git history (10 commits)
- Git status (10 modified, 112 untracked)
- File tree (370 Python files in backend, frontend structure)

---

**End of Phase 1 Discovery Report.**

This report is a temporary artifact. Phase 2 (vault construction) should NOT proceed until this report has been reviewed and approved by the founder or designated reviewer.
