# Core Content Snapshot


*** MISSING: 00 Control Center/StrikeNova Home.md ***


*** MISSING: 00 Control Center/Current State.md ***


*** MISSING: 00 Control Center/Active Work.md ***


*** MISSING: 00 Control Center/Roadmap.md ***


*** MISSING: 00 Control Center/Open Questions.md ***


*** MISSING: 00 Control Center/Source of Truth.md ***


*** MISSING: 01 Product/Product Overview.md ***


*** MISSING: 01 Product/Product Ideas.md ***


*** MISSING: 02 Architecture/Architecture Overview.md ***


*** MISSING: 02 Architecture/Application Architecture.md ***


*** MISSING: 02 Architecture/Data & Persistence.md ***


*** MISSING: 02 Architecture/Broker & Identity.md ***


*** MISSING: 02 Architecture/Security.md ***


*** MISSING: 02 Architecture/Infrastructure.md ***


*** MISSING: 03 Quant Intelligence/Quant Overview.md ***


*** MISSING: 03 Quant Intelligence/Greeks & IV.md ***


*** MISSING: 03 Quant Intelligence/GEX.md ***


*** MISSING: 03 Quant Intelligence/Market Intelligence.md ***


*** MISSING: 04 Decisions/ADR-001 BYOB & Identity Separation.md ***


*** MISSING: 04 Decisions/ADR-002 GEX Modeling Convention.md ***


*** MISSING: 04 Decisions/ADR-003 Cross-D1 Locking.md ***


*** MISSING: 06 Development/Phase Tracker.md ***


*** MISSING: 06 Development/Day 35.md ***


*** MISSING: 06 Development/Day 39.md ***


*** MISSING: 06 Development/Day 41.md ***


*** MISSING: 07 AI & Agents/AI Context.md ***


*** MISSING: 07 AI & Agents/Agent Rules.md ***


*** MISSING: 07 AI & Agents/DeepSeek Harness.md ***


*** MISSING: 07 AI & Agents/FreeBuff.md ***


*** MISSING: 07 AI & Agents/Current Handoff.md ***


*** MISSING: 08 Business/Business Model.md ***


*** MISSING: 08 Business/Pricing & Growth.md ***


*** MISSING: 08 Business/Future Products.md ***



============================================================
REMAINING FILES (small non-core notes)
============================================================


------------------------------------------------------------
FILE: 00 Control Center\Active Work.md
------------------------------------------------------------

---
type: status
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Active Work

## Current Active Work

### Day 41 — Cross-D1 Locking
- **Status:** Architecture accepted by human decision
- **Locking primitive:** D-1 dedicated order-family lock
- **Implementation authorization:** Frozen r2 design ONLY; Task 3 🔴 LOCKED
- **Source:** `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-locking-human-architecture-decision.md`

### Day 35 — Portfolio Intelligence
- **Module:** `portfolio_intelligence/analytics.py`, `contracts.py`, `normalization.py`
- **Focus:** Portfolio-level analytics consuming position truth + quant/intelligence services

### Day 39 — Broker Sync
- **Module:** `broker_sync/ingestion.py`, `models.py`, `fill_ledger.py`, `fingerprint.py`, `raw_ingress.py`
- **Focus:** Idempotent broker data ingestion with sequence anchoring

### Working Tree State
- **Branch:** `feat/strikenova-day35-portfolio-intelligence`
- **Modified files:** 10 (including protected files)
- **Protected files (do not touch):** `adapter.py`, `mapper.py`, `paper_execution.py`, `upstox.py`, `test_upstox_adapter.py`

## Source / Evidence
- Git branch: `feat/strikenova-day35-portfolio-intelligence`
- Git status: 10 modified, 112 untracked
- Discovery report: `STRIKENOVA_OBSIDIAN_DISCOVERY_REPORT.md`



------------------------------------------------------------
FILE: 00 Control Center\Current State.md
------------------------------------------------------------

---
type: status
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Current State

## Current Implementation (VERIFIED)

### Product Capabilities
- **NIFTY index options paper trading** — server-authoritative execution engine (`paper_execution.py`, 1,489 lines)
- **Strategy templates** — V1 fixed-leg + V2 dynamic formula (`StrategyTemplate`, `StrategyTemplateLeg`)
- **Payoff chart** — `frontend/lib/calculations/payoff.js`
- **Basic Greeks (Black-Scholes)** — `backend/app/quant/greeks.py` (BSM European engine)
- **IV calculation (model)** — `backend/app/quant/iv.py` (Brent root solver)
- **GEX (Gamma Exposure)** — `backend/app/quant/gex.py` (Day-17 engine)
- **Historical GEX persistence** — `GexSnapshot` model + `gex_history.py`
- **Live GEX capture** — `live_gex.py` + background capture loop in `main.py`
- **Market/intelligence data** — Upstox integration via `chains.py`, `candles.py`
- **Paper positions & P&L** — `Position` model + `paper_execution.py`
- **Order history / journal** — `StrategyExecution`/`PaperOrder` authoritative domain
- **Market-hours protection** — `market_status.py`
- **Portfolio intelligence (Day 35)** — `portfolio_intelligence/` (analytics, contracts, normalization)
- **Broker-sync ingestion (Day 39)** — `broker_sync/` (ingestion, fill ledger, fingerprint, raw ingress)
- **Cross-D1 S1/S2 classification** — 🟡 PROPOSED (human architecture decision recorded, implementation NOT authorized)

### Trading Mode
- **Current mode:** PAPER ONLY (server-authoritative simulation)
- **Live broker execution:** 🔴 UNKNOWN (declared DISABLED in blueprint)
- **Production runtime:** 🔴 UNKNOWN (not freshly verified)

### Frontend
- Next.js 14 / React 18 (`frontend/`)
- App routes: activity, brokers, dashboard, gex, market, orders, paper, portfolio, positions, settings, strategies
- Public routes: about, features, how-it-works, market-intelligence, paper-trading, strategy-lab
- Calculations: payoff, risk, greeks, strategyCalculator, gex

### Backend
- FastAPI / Python 3
- Entry: `backend/app/main.py`
- ORM: SQLAlchemy declarative
- Migrations: Alembic (20+ versions)
- Auth: Google OAuth + session management
- Quant engine: greeks, iv, gex, pricing, scenarios
- Intelligence: positioning, levels, institutional, regime, traps, synthesis

## Source / Evidence
- Repository: `shahid1995/-options-dashboard` branch `feat/strikenova-day35-portfolio-intelligence`
- Discovery report: `STRIKENOVA_OBSIDIAN_DISCOVERY_REPORT.md` (2026-09-12)



------------------------------------------------------------
FILE: 00 Control Center\Open Questions.md
------------------------------------------------------------

---
type: questions
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Open Questions

## Genuine Unresolved Questions

1. **Live execution status** — Is live broker execution still disabled? Last declared DISABLED in `PROJECT_MASTER_BLUEPRINT.md` (dated 2026-08-21), but Phase 10.2B broker credential architecture implies preparation.

2. **Production multi-user status** — No evidence of actual users beyond development/testing. PostgreSQL migration state in production unknown.

3. **Frontend GEX parity** — Backend GEX engine exists; frontend `gex.js` may duplicate or lag. Not freshly verified.

4. **Broker margin modeling** — `broker_margin.py` exists but content unverified.

5. **Business model** — Revenue, pricing, target customers, go-to-market strategy absent from repository.

## Resolved / Not Open

- Repository naming: Confirmed `shahid1995/-options-dashboard` is the authoritative remote. `options-dashboard-project/` is the local directory.
- Project directory: `options-dashboard-project/` is correct.

## Source / Evidence
- Discovery report §10 (missing information)
- Blueprint §1 (LIVE DISABLED declaration)



------------------------------------------------------------
FILE: 00 Control Center\Roadmap.md
------------------------------------------------------------

---
type: roadmap
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Roadmap

## Completed

- Day 14 — Quant boundary contracts
- Day 15 — BSM Greeks engine
- Day 16 — IV solver (Brent)
- Day 17 — GEX engine
- Day 19 — Intelligence contracts
- Day 20 — Positioning signals
- Day 21 — Dynamic support/resistance levels
- Day 22 — Institutional activity
- Day 23 — Market regime classification
- Day 25 — Trap detection
- Day 26 — Signal synthesis
- Day 35 — Portfolio intelligence
- Day 39 — Broker sync ingestion
- Phase 10.1B — Alembic schema baseline

## Current

- Day 41 — Cross-D1 locking (architecture accepted, implementation pending authorization)

## Planned

- Full cross-D1 implementation (when authorized)
- Frontend/backend GEX parity verification
- PostgreSQL production migration completion
- Live broker execution architecture completion (disabled currently)

## Proposed

- Gamma Flip / Zero Gamma
- Gamma Walls
- Multi-user production deployment
- Live trading enablement

## Source / Evidence
- Discovery report §2, §4 (verified capabilities)
- Repository module structure



------------------------------------------------------------
FILE: 00 Control Center\Source of Truth.md
------------------------------------------------------------

---
type: meta
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Source of Truth

## Authority Definitions

### GitHub = Implementation Authority
- **Repository:** [shahid1995/-options-dashboard](https://github.com/shahid1995/-options-dashboard)
- **Local path:** `C:\Users\busin\Desktop\-options-dashboard\options-dashboard-project`
- Source code, commits, and merge history define what is implemented.

### Obsidian = Knowledge/Context Authority
- **Vault:** `D:\Knowledge\StrikeNova`
- **Vault ID:** `cdabd4e67078f7ba`
- Project knowledge, architectural context, decisions, and evidence synthesis.

### Founder = Final Authority
- Strategic decisions
- Product direction
- Major architecture decisions
- Business context

### Historical Documents = Evidence, NOT Current Truth
- `PROJECT_MASTER_BLUEPRINT.md` (dated 2026-08-21) — historical snapshot
- `PROJECT_STATUS.md` (dated 2026-08-27) — historical snapshot
- `COMPREHENSIVE_ARCHITECTURE_AUDIT.md` (dated 2026-08-25) — historical audit
- These may contain outdated claims. Always verify against current implementation.

## Repository Structure

| Name | Value |
|------|-------|
| Remote | `https://github.com/shahid1995/-options-dashboard` |
| Local directory | `options-dashboard-project/` |
| Current branch | `feat/strikenova-day35-portfolio-intelligence` |

## Source / Evidence
- Repository git remote configuration
- Discovery report §1, §11



------------------------------------------------------------
FILE: 00 Control Center\StrikeNova Home.md
------------------------------------------------------------

---
type: index
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# StrikeNova Home

Welcome to the **StrikeNova** knowledge vault.

## Project Identity

| Field | Value |
|-------|-------|
| **Repository** | [shahid1995/-options-dashboard](https://github.com/shahid1995/-options-dashboard) |
| **Local Path** | `C:\Users\busin\Desktop\-options-dashboard\options-dashboard-project` |
| **Current Branch** | `feat/strikenova-day35-portfolio-intelligence` |
| **Current Commit** | `10c1a78` (docs: add CockroachDB runtime validation report) |
| **Vault Location** | `D:\Knowledge\StrikeNova` |

## Navigation

### Control Center
- [[Current State]]
- [[Active Work]]
- [[Roadmap]]
- [[Open Questions]]
- [[Source of Truth]]

### Domains
- [[Product Overview]]
- [[Architecture Overview]]
- [[Quant Overview]]
- [[Market Intelligence]]
- [[AI Context]]

### Development
- [[Phase Tracker]]
- [[Day 35]]
- [[Day 39]]
- [[Day 41]]

### Decisions
- [[ADR-001 BYOB & Identity Separation]]
- [[ADR-002 GEX Modeling Convention]]
- [[ADR-003 Cross-D1 Locking]]

## Current Status

**Mode:** PAPER ONLY  
**Production runtime:** UNKNOWN  
**Current focus:** Day 41 Cross-D1 locking (architecture accepted, Task 3 implementation NOT authorized)

## Information Key

| Symbol | Meaning |
|--------|---------|
| 🟢 | VERIFIED |
| 🔵 | ACCEPTED |
| 🟡 | PROPOSED |
| 🔴 | UNKNOWN |



------------------------------------------------------------
FILE: 01 Product\Product Ideas.md
------------------------------------------------------------

---
type: ideas
status: proposed
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Product Ideas

## Future Product Ideas

### Near-Term
- Live broker execution enablement (architecture prepared, not wired)
- PostgreSQL multi-user production deployment
- Frontend/backend GEX parity verification

### Medium-Term
- Gamma Flip / Zero Gamma modeling (🟡 PROPOSED)
- Gamma Walls detection (🟡 PROPOSED)
- Additional broker integrations
- Mobile-responsive interface

### Long-Term
- Advanced strategy backtesting
- Options flow analytics
- Social/collaborative features

## Source / Evidence
- Discovery report §11 (recommended documents)
- GEX spec §18 (future extensions)



------------------------------------------------------------
FILE: 01 Product\Product Overview.md
------------------------------------------------------------

---
type: product
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Product Overview

## What is StrikeNova?

StrikeNova is a **professional options-trading dashboard** for Indian index options (NIFTY).

## Current Product State

### Verified Capabilities
- NIFTY index options **paper trading** (server-authoritative)
- Strategy templates (fixed + dynamic)
- Payoff visualization
- BSM Greeks calculation
- Implied volatility solving
- Gamma Exposure (GEX) modeling
- Market intelligence signals
- Portfolio intelligence

### Product Principles
- Professional-grade options analytics
- Paper-first safety (all features designed for eventual live execution)
- Free-for-life preference (open-source, self-hostable tooling)
- No vendor lock-in

### Major User Problems Addressed
- Complex options strategy construction and visualization
- Real-time Greeks and exposure monitoring
- Market regime and positioning intelligence
- Paper trading without risk

### Current Boundaries
- Single broker: Upstox
- Single user (local deployment)
- PAPER ONLY (live execution disabled)
- NIFTY index options focus

## Source / Evidence
- `PROJECT_MASTER_BLUEPRINT.md` §1-2 (historical, dated 2026-08-21)
- Discovery report §2 (verified capabilities)



------------------------------------------------------------
FILE: 02 Architecture\Application Architecture.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Application Architecture

## Frontend

### Framework
- Next.js 14 / React 18
- App Router architecture

### Routes
- App: activity, brokers, dashboard, gex, market, orders, paper, portfolio, positions, settings, strategies
- Public: about, features, how-it-works, market-intelligence, paper-trading, strategy-lab

### Calculations
- `payoff.js` — strategy payoff visualization
- `risk.js` — risk analytics
- `greeks.js` — BSM Greeks (frontend)
- `strategyCalculator.js` — strategy building
- `gex.js` — GEX frontend (may duplicate backend)

### Strategy Library
- `strategy.js`, `strategyUtils.js`, `strategyValidation.js`, `strategyIdentity.js`

## Backend

### Framework
- FastAPI / Python 3
- Entry: `backend/app/main.py`

### Module Organization
- `brokers/` — broker gateway, registry, adapters
- `quant/` — greeks, iv, gex, pricing, scenarios
- `intelligence/` — positioning, levels, institutional, regime, traps, synthesis
- `portfolio_intelligence/` — Day 35 portfolio analytics
- `broker_sync/` — Day 39 ingestion, fill ledger, fingerprint, raw ingress
- `domain_events/` — Day 37 event bus, handler, idempotency
- `central_risk/` — risk engine contracts
- `final_risk_gate/` — final risk gate
- `market_data/` — quality, gateway, streaming
- `services/` — 35+ service modules
- `routers/` — FastAPI route handlers

## Source / Evidence
- Discovery report §3 (frontend, backend)
- Repository file structure



------------------------------------------------------------
FILE: 02 Architecture\Architecture Overview.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Architecture Overview

## Architectural Map

### CURRENT (Verified)
- Frontend: Next.js 14 / React 18
- Backend: FastAPI / Python 3
- Database: SQLAlchemy ORM, SQLite (default), PostgreSQL (production path)
- Auth: Google OAuth + session management
- Broker: Upstox (single broker, OAuth-based)

### IMPLEMENTED (Verified)
- Quant engine: BSM Greeks, IV solver, GEX engine
- Intelligence system: positioning, levels, institutional, regime, traps, synthesis
- Portfolio intelligence (Day 35)
- Broker-sync ingestion (Day 39)
- Paper execution engine (1,489 lines)
- Market data quality framework
- Central risk engine + final risk gate

### PLANNED
- Cross-D1 locking implementation (authorized for frozen r2 design)
- Live broker execution (disabled)
- Multi-user production deployment

### UNKNOWN
- Current production runtime status
- Live execution enablement status

## Source / Evidence
- Discovery report §3 (architecture)
- `COMPREHENSIVE_ARCHITECTURE_AUDIT.md` (historical audit, 2026-08-25)



------------------------------------------------------------
FILE: 02 Architecture\Broker & Identity.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Broker & Identity.md

## StrikeNova Identity

StrikeNova account authentication is **independent** from broker authentication.

## BYOB Architecture

- Every user supplies their own broker Developer App credentials
- No shared Upstox API credentials across users
- `broker_connections` belongs to StrikeNova User (user_id FK non-nullable)

## Broker Adapter Pattern
- `brokers/gateway.py` — broker-neutral gateway
- `brokers/registry.py` — broker adapter registry
- `brokers/adapters/upstox/` — Upstox V3 adapter
- `brokers/domain/capabilities.py` — capability model (7-state enum)

## Upstox State
- OAuth 2.0 integration
- Token expires 3:30 AM IST daily (no refresh token)
- BYOB Phase 10.2B architecture in progress

## Current Trading Mode
- **PAPER ONLY** (live execution disabled)
- Live broker execution declared DISABLED in blueprint
- Broker capability model prepared for future live execution

## Source / Evidence
- Discovery report §3 (external integrations)
- `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` (AD-1 through AD-4)
- `BROKER_CAPABILITY_MATRIX.md`



------------------------------------------------------------
FILE: 02 Architecture\Data & Persistence.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Data & Persistence

## ORM
- SQLAlchemy declarative base

## Default Database
- SQLite (`paper_journal.db`)

## Production Target
- PostgreSQL (`postgresql+psycopg://`)
- Connection via `normalize_database_url` in `db.py`

## Migrations
- Alembic (20+ migration versions in `backend/alembic/versions/`)
- Baseline: `d3eb45a2e046` — 24 tables

## Key Tables (Verified)
- `paper_accounts`, `trades`, `legs`
- `strategy_executions`, `paper_orders`, `positions`, `paper_transactions`
- `strategy_leg_exposures`, `exit_exposure_allocations`, `bulk_exit_records`
- `strategy_templates`, `strategy_template_legs`
- `gex_snapshots` (strike_data JSON, expiry_data JSON, methodology_metadata)
- `broker_sync_idempotency`, `broker_sync_sequence_anchor`

## Persistent Domains
- Paper trading (executions, orders, positions, transactions)
- Strategy templates
- GEX snapshots (historical)
- Broker sync state (Day 39)
- Domain events (Day 37)

## Source / Evidence
- Discovery report §3 (database)
- `backend/app/db.py`
- `backend/app/models.py` (936 lines)



------------------------------------------------------------
FILE: 02 Architecture\Infrastructure.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Infrastructure

## Hosting

### Backend
- Railway (PostgreSQL hosting)

### Frontend
- Vercel

## Deployment Model
- GitHub → Railway (backend)
- GitHub → Vercel (frontend)

## Environment Configuration
- `backend/.env.example` for Railway env vars
- Production detection via Railway environment variables

## Historical Deployment Checkpoints
- Phase 10.1B: Alembic baseline migration (2026-08-27, per `PROJECT_STATUS.md`)
- Phase 10.2B: Broker credential architecture (2026-08-29)
- Railway infrastructure audit (2026-09-05)

## Current Production Status
- **UNKNOWN** — not freshly verified

## Source / Evidence
- Discovery report §3 (infrastructure)
- `README.md` §7-10
- `RAILWAY_INFRASTRUCTURE_AUDIT.md` (dated 2026-09-05)



------------------------------------------------------------
FILE: 02 Architecture\Security.md
------------------------------------------------------------

---
type: architecture
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Security

## Authentication
- Google OAuth + session management
- `identity.py` (29,559 lines)
- `backend/app/routers/auth.py`

## Credential Handling
- Broker client secrets stored backend-only
- Per-user static IPs for SEBI compliance
- Customer Analytics Tokens never used as implicit platform credentials

## CORS
- Configurable via `FRONTEND_URL`, `ADDITIONAL_CORS_ORIGINS`

## Production Detection
- `IS_PRODUCTION` property checks `RAILWAY_ENVIRONMENT` / `RAILWAY_SERVICE_NAME` / `PRODUCTION`

## Important Constraint
- **No secrets are stored in this vault**

## Source / Evidence
- Discovery report §6 (security)
- `config.py` (110 lines)
- `main.py` GEX capture comments



------------------------------------------------------------
FILE: 03 Quant Intelligence\GEX.md
------------------------------------------------------------

---
type: quant
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# GEX (Gamma Exposure)

## GEX Engine

### Implementation
- `backend/app/quant/gex.py` — Day-17 engine
- Model version: `1.0.0`

### Formula
- Raw GEX = Gamma × OI × S² × 0.01

### OI Units
- Contracts (never lots)

### Sign Convention
- Call GEX = +Raw GEX
- Put GEX = −Raw GEX
- **NAIVE_DEALER_CONVENTION** (explicit modeling convention, not observed dealer positions)

### Greeks Source Separation
- Engine requires label
- Profile builder rejects mixed broker/model gamma

## Persistence
- `GexSnapshot` model (strike_data JSON, expiry_data JSON, methodology_metadata)
- Historical persistence via `gex_history.py`

## Live Capture
- Background loop in `main.py`
- `GexCaptureService` in `services/gex_capture.py`

## Frontend GEX
- `frontend/lib/calculations/gex.js` exists
- **🟡 UNVERIFIED** — not freshly verified for parity with backend

## Future Extensions (Inside This File)

### Gamma Flip / Zero Gamma
- **Status:** 🟡 PROPOSED
- Listed as future extension in `GEX_V1_0_SPEC.md` §18
- Architecture designed, not yet implemented

### Gamma Walls
- **Status:** 🟡 PROPOSED
- Day-17 explicitly excluded gamma walls from Day-21
- `levels.py` §25-26 acknowledges no canonical gamma-wall interface

## Source / Evidence
- Discovery report §4 (GEX)
- `GEX_V1_0_SPEC.md`
- `gex.py` (525 lines)



------------------------------------------------------------
FILE: 03 Quant Intelligence\Greeks & IV.md
------------------------------------------------------------

---
type: quant
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Greeks & IV

## BSM Greeks Engine

### Implementation
- `backend/app/quant/greeks.py` — Black-Scholes-Merton European
- Model version: `1.0.0`

### Calculations
- delta, gamma, theta, vega, rho (call + put)

### Units
- delta (dimensionless)
- gamma (per unit S)
- vega (per 1.00 vol)
- theta (per year)
- rho (per 1.00 rate)

### Day-Count
- ACT/365 (`time_to_expiry` in `quant/contracts.py`)

### Degenerate Handling
- T=0, σ=0 handled with documented conventions

### Broker vs Model Separation
- Broker Greeks via `GreeksObservation(source="BROKER")`
- Model Greeks separate with `calculation_id` + versions

## IV Solver

### Implementation
- `backend/app/quant/iv.py` — Brent root solver
- Model version: `1.0.0`

### Domain
- [0.0, 10.0] (0% to 1000%)

### Convergence
- price_tolerance 1e-9, sigma_tolerance 1e-10, max 100 iterations

### Failure Taxonomy
- EXPIRED, BELOW_LOWER_BOUND, ABOVE_THEORETICAL_MAX, NO_BRACKET, CONVERGENCE_FAILED

### Output
- Decimal fraction (0.1824 = 18.24%)

## Source / Evidence
- Discovery report §4 (Greeks, IV)
- `quant/greeks.py` (311 lines)
- `quant/iv.py` (518 lines)



------------------------------------------------------------
FILE: 03 Quant Intelligence\Market Intelligence.md
------------------------------------------------------------

---
type: intelligence
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Market Intelligence

## Intelligence System (Days 19-26)

### Day 19 — Contracts
- `intelligence/contracts.py` — `IntelligenceResult` unified envelope
- Fields: direction, signal_strength, confidence, evidence, quality, provenance, regime

### Day 20 — Positioning
- `intelligence/positioning.py` (566 lines)
- OI/positioning interpretation: LONG_BUILDUP/SHORT_BUILDUP/SHORT_COVERING/LONG_UNWINDING

### Day 21 — Levels
- `intelligence/levels.py` (700 lines)
- Dynamic support/resistance — levels are positional, not directional
- Corroborated concentration required
- High-OI strike is concentration fact, NOT automatically support/resistance

### Day 22 — Institutional
- `intelligence/institutional.py` — institutional activity read

### Day 23 — Regime
- `intelligence/regime.py` (668 lines)
- Market regime classification: TRENDING/RANGING/HIGH_VOLATILITY/LOW_VOLATILITY/RISK_ON/RISK_OFF/UNKNOWN
- Priority cascade, exactly one label per evaluation; conflicting evidence → UNKNOWN

### Day 25 — Traps
- `intelligence/traps.py` — trap pattern detection

### Day 26 — Synthesis
- `intelligence/synthesis.py` (647 lines)
- Conflict resolution across families
- No majority vote; agreement/conflict/no-direction
- Only BULLISH/BEARISH vote

## Relationship to Portfolio Intelligence
- Day 35 `portfolio_intelligence/` consumes position truth + quant/intelligence services

## Source / Evidence
- Discovery report §4 (market signals)
- Repository module structure (files 566-700 lines each)



------------------------------------------------------------
FILE: 03 Quant Intelligence\Quant Overview.md
------------------------------------------------------------

---
type: quant
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Quant Overview

## Shared Quantitative Engine

### Engines (Verified)
- **BSM Greeks** — `quant/greeks.py` (Day 15)
- **IV Solver** — `quant/iv.py` (Day 16, Brent root solver)
- **GEX Engine** — `quant/gex.py` (Day 17)
- **Pricing** — `quant/pricing.py`
- **Scenarios** — `quant/scenarios.py`

### Day-14 Boundary
- `quant/contracts.py` (372 lines) — unified contracts for all quant engines

## Source / Evidence
- Discovery report §4 (quant intelligence)
- Repository module structure



------------------------------------------------------------
FILE: 04 Decisions\ADR-001 BYOB & Identity Separation.md
------------------------------------------------------------

---
type: decision
status: accepted
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# ADR-001: BYOB & Identity Separation

## Status
🔵 ACCEPTED

## Decision

StrikeNova account authentication is **independent** from broker authentication.

## Details

- **StrikeNova identity** is independent from broker identity
- **BYOB architecture** — user supplies own broker Developer App credentials
- **User-specific broker relationships** — each user's broker connections belong to them (user_id FK non-nullable)
- **Separation of platform authentication and broker authentication**

## Source / Evidence
- `PHASE_10_2B_CONNECTION_ARCHITECTURE.md` AD-1 through AD-4
- `BROKER_CAPABILITY_MATRIX.md`



------------------------------------------------------------
FILE: 04 Decisions\ADR-002 GEX Modeling Convention.md
------------------------------------------------------------

---
type: decision
status: accepted
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# ADR-002: GEX Modeling Convention

## Status
🔵 ACCEPTED (Technical Convention)

## Decision

Use **NAIVE_DEALER_CONVENTION** for GEX sign convention.

## Details

- **Dealer convention** — models dealer exposure, not observed dealer positions
- **Call GEX = +Raw GEX**
- **Put GEX = −Raw GEX**
- **OI units** — contracts, never lots
- **Distinction** — modeled exposure ≠ observed dealer position

## Source / Evidence
- `GEX_V1_0_SPEC.md` §1, §14-16
- `gex.py` §14-17



------------------------------------------------------------
FILE: 04 Decisions\ADR-003 Cross-D1 Locking.md
------------------------------------------------------------

---
type: decision
status: accepted
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# ADR-003: Cross-D1 Locking

## Status
🔵 ACCEPTED

## Decision

D-1 dedicated order-family lock selected for cross-D1 concurrency control.

## Details

- **Locking primitive:** D-1 dedicated order-family lock
- **Architecture decision:** Human architecture decision recorded
- **Implementation authorization:** Frozen r2 design ONLY
- **Task 3 implementation:** 🔴 LOCKED (not authorized)

## Current Authorization State
- Task 3 implementation NOT authorized
- See [[Current State]] and [[Active Work]] for current status

## Source / Evidence
- `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-locking-human-architecture-decision.md`
- `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-implementation-authorization.md`



------------------------------------------------------------
FILE: 05 Research\Research Index.md
------------------------------------------------------------

---
type: index
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Research Index

## Research Structure

### Topics
- Brokers
- Regulation
- Competitors
- Infrastructure
- Technology
- Market Research

### Approach
Individual research notes are created when substantive evidence exists. This index organizes the research domain.

## Source / Evidence
- Discovery report §11 (recommended documents)



------------------------------------------------------------
FILE: 06 Development\Day 35.md
------------------------------------------------------------

---
type: development
status: completed
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Day 35 — Portfolio Intelligence

## Objective
Portfolio-level analytics consuming position truth + quant/intelligence services.

## Starting State
After Day 34 (central risk engine + final risk gate).

## Work Completed
- `portfolio_intelligence/analytics.py` (34,226 bytes)
- `portfolio_intelligence/contracts.py` (30,451 bytes)
- `portfolio_intelligence/normalization.py` (8,579 bytes)
- `portfolio_intelligence/__init__.py` (2,958 bytes)

## Verification
- Module structure verified via file listing
- Content not inspected in detail

## Source / Evidence
- Discovery report §2 (product capabilities)
- Repository file structure



------------------------------------------------------------
FILE: 06 Development\Day 39.md
------------------------------------------------------------

---
type: development
status: completed
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Day 39 — Broker Sync

## Objective
Idempotent broker data ingestion with sequence anchoring.

## Starting State
After Day 38 (domain events bus).

## Work Completed
- `broker_sync/ingestion.py`
- `broker_sync/models.py` (175 lines)
- `broker_sync/fill_ledger.py`
- `broker_sync/fingerprint.py`
- `broker_sync/raw_ingress.py`

## Key Lessons (from task memory)
1. Broker sequence advancement inside SAVEPOINT after projection+idempotency+lifecycle succeed
2. Concurrent sequence races reclassify through idempotency layer
3. SQLite StaticPool cannot test true concurrency — use PG for testing
4. Day38 replay preconditions require foundation events before order-level events
5. Day38 lifecycle aggregate MUST be actual execution (StrategyExecution.execution_id), NEVER broker_order_id
6. Unknown broker orders FAIL CLOSED (REJECTED)
7. Multiple broker orders can map to one execution

## Source / Evidence
- Discovery report §2 (product capabilities)
- Repository file structure
- Day39 task memory (5 rounds completed)



------------------------------------------------------------
FILE: 06 Development\Day 41.md
------------------------------------------------------------

---
type: development
status: in-progress
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Day 41 — Cross-D1 Locking

## Objective
Cross-D1 concurrency control via D-1 dedicated order-family lock.

## Starting State
After Day 40 (final identity contract correction memos).

## Architecture Decision
- **D-1 dedicated order-family lock** selected by human decision
- **Cross-D1 S1/S2 classification** — 🟡 PROPOSED

## Implementation Authorization
- **Authorized:** Frozen r2 design ONLY
- **Task 3:** 🔴 LOCKED (not authorized)
- **Push/deploy:** NOT authorized

## Current Status
Architecture accepted. Implementation pending authorization.

## Source / Evidence
- `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-locking-human-architecture-decision.md`
- `docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-implementation-authorization.md`



------------------------------------------------------------
FILE: 06 Development\Phase Tracker.md
------------------------------------------------------------

---
type: tracker
status: current
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Phase Tracker

## Phase Progression

### Completed Phases
- Day 14 — Quant boundary contracts
- Day 15 — BSM Greeks engine
- Day 16 — IV solver (Brent)
- Day 17 — GEX engine
- Day 19 — Intelligence contracts
- Day 20 — Positioning signals
- Day 21 — Dynamic support/resistance levels
- Day 22 — Institutional activity
- Day 23 — Market regime classification
- Day 25 — Trap detection
- Day 26 — Signal synthesis
- Day 35 — Portfolio intelligence
- Day 39 — Broker sync ingestion
- Phase 10.1B — Alembic schema baseline

### Current
- Day 41 — Cross-D1 locking (architecture accepted, implementation pending authorization)

## Source / Evidence
- `PROJECT_STATUS.md` (historical, dated 2026-08-27)
- Discovery report §7 (verified decisions)



------------------------------------------------------------
FILE: 07 AI & Agents\Agent Rules.md
------------------------------------------------------------

---
type: rules
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Agent Rules

## Rules

1. **Evidence before assertion.** Never invent APIs or state facts without repository support.
2. **Never invent APIs.** Use only documented interfaces.
3. **Preserve accepted decisions.** ADRs are approved; don't silently change them.
4. **No silent architecture changes.** Document any architectural modifications.
5. **Scope control.** Respect task boundaries.
6. **Protect secrets.** Never write credentials to any output.
7. **Verify before completion claims.** Actually run the tests/builds/commands.
8. **GitHub is implementation authority.** Code truth comes from the repository.
9. **Obsidian is knowledge/context authority.** This vault is the project knowledge base.
10. **Founder approval required for major decisions.** Don't commit to major changes without approval.

## Source / Evidence
- Project workflow conventions (2026-09-12)



------------------------------------------------------------
FILE: 07 AI & Agents\AI Context.md
------------------------------------------------------------

---
type: ai-context
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# AI Context

## Project Identity
StrikeNova — professional options-trading dashboard for Indian index options (NIFTY).

## Product
Paper trading dashboard with BSM Greeks, IV solver, GEX engine, market intelligence, portfolio intelligence.

## Architecture
- Frontend: Next.js 14 / React 18
- Backend: FastAPI / Python 3
- Database: SQLAlchemy, SQLite (default), PostgreSQL (production path)
- Auth: Google OAuth + session

## Quant Domains
- BSM Greeks, IV solver, GEX engine
- Market intelligence (positioning, levels, institutional, regime, traps, synthesis)

## Trading Mode
**PAPER ONLY** — live execution disabled.

## Important Constraints
- Do not modify protected files: adapter.py, mapper.py, paper_execution.py, upstox.py, test_upstox_adapter.py
- Do not install plugins or configure REST API/MCP
- Do not modify existing Obsidian Vault

## Current State
- Branch: feat/strikenova-day35-portfolio-intelligence
- Focus: Day 41 Cross-D1 locking

## Active Work
- Day 41 architecture accepted, Task 3 locked
- Day 35 Portfolio Intelligence
- Day 39 Broker Sync

## Source / Evidence
- Project context (2026-09-12)



------------------------------------------------------------
FILE: 07 AI & Agents\Current Handoff.md
------------------------------------------------------------

---
type: handoff
status: active
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Current Handoff

## Current Status

- **Branch:** `feat/strikenova-day35-portfolio-intelligence`
- **Trading mode:** PAPER ONLY
- **Production runtime:** UNKNOWN
- **Vault:** `D:\Knowledge\StrikeNova`

## Active Work

- Day 41 Cross-D1 locking (architecture accepted, Task 3 locked)
- Day 35 Portfolio Intelligence
- Day 39 Broker Sync

## Current Blockers

- Windows Defender Controlled Folder Access blocked mkdir/cmd in Documents folder (resolved by using D:\Knowledge\StrikeNova)
- Cross-D1 Task 3 implementation not authorized

## Important Constraints

- Protected files: adapter.py, mapper.py, paper_execution.py, upstox.py, test_upstox_adapter.py
- Do not install plugins or configure REST API/MCP
- Do not modify existing Obsidian Vault

## Immediate Next Actions

1. Populate vault with permanent documents
2. Verify Day 35/39 implementation against discovery report
3. Await Day 41 Task 3 authorization

## Source / Evidence
- Project workflow (2026-09-12)



------------------------------------------------------------
FILE: 07 AI & Agents\DeepSeek Harness.md
------------------------------------------------------------

---
type: note
status: unknown
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# DeepSeek Harness

## Current State

No evidence of DeepSeek integration found in repository.

## Status
🔴 UNKNOWN — no implementation evidence.

## Source / Evidence
- Discovery report §12 (documents not recommended)



------------------------------------------------------------
FILE: 07 AI & Agents\FreeBuff.md
------------------------------------------------------------

---
type: note
status: unknown
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# FreeBuff

.freebuff/ directory exists in repository root.

## Current State

No evidence of FreeBuff integration content inspected.

## Status
🔴 UNKNOWN — directory exists, content unverified.

## Source / Evidence
- Discovery report §11 (recommended documents)



------------------------------------------------------------
FILE: 08 Business\Business Model.md
------------------------------------------------------------

---
type: business
status: unknown
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Business Model

## Current State

No business model evidence found in repository.

## Status
🔴 UNKNOWN — no evidence in repository.

## Source
Source: Founder-provided project context (not in GitHub)

## Source / Evidence
- Discovery report §6 (business — missing information)



------------------------------------------------------------
FILE: 08 Business\Future Products.md
------------------------------------------------------------

---
type: ideas
status: proposed
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Future Products

.freebuff/ directory exists in repository root.

## Future Product Concepts

- Gamma Flip / Zero Gamma modeling
- Gamma Walls detection
- Additional broker integrations
- Advanced strategy backtesting
- Options flow analytics

**Status:** 🟡 PROPOSED

**Note:** These are separate from current StrikeNova product scope.

## Source / Evidence
- Discovery report §11 (recommended documents)
- GEX spec §18 (future extensions)



------------------------------------------------------------
FILE: 08 Business\Pricing & Growth.md
------------------------------------------------------------

---
type: business
status: unknown
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Pricing & Growth

.freebuff/ directory exists in repository root.

## Current State

No pricing or growth evidence found in repository.

## Status
🔴 UNKNOWN — no evidence in repository.

## Source
Source: Founder-provided project context (not in GitHub)

## Source / Evidence
- Discovery report §6 (business — missing information)



------------------------------------------------------------
FILE: Templates\Agent Handoff.md
------------------------------------------------------------

---
type: handoff
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Agent Handoff

## Current Status



## Active Work



## Current Blockers



## Important Constraints



## Immediate Next Actions



## Source / Evidence




------------------------------------------------------------
FILE: Templates\Audit.md
------------------------------------------------------------

---
type: audit
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Audit

## Scope



## Findings



## Recommendations



## Source / Evidence




------------------------------------------------------------
FILE: Templates\Concept.md
------------------------------------------------------------

---
type: concept
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Concept

## Summary



## Details



## Source / Evidence




------------------------------------------------------------
FILE: Templates\Decision.md
------------------------------------------------------------

---
type: decision
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Decision

## Status



## Decision



## Rationale



## Source / Evidence




------------------------------------------------------------
FILE: Templates\Development Day.md
------------------------------------------------------------

---
type: development
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Development Day

## Objective



## Starting State



## Work Completed



## Verification



## Findings



## Decisions



## Blockers



## Remaining Work



## Next Step



## Source / Evidence




------------------------------------------------------------
FILE: Templates\Experiment.md
------------------------------------------------------------

---
type: experiment
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Experiment

## Hypothesis



## Method



## Results



## Conclusion



## Source / Evidence



------------------------------------------------------------
FILE: Templates\Research.md
------------------------------------------------------------

---
type: research
status: template
area: StrikeNova
created: 2026-09-12
updated: 2026-09-12
---

# Research

## Question



## Findings



## Source / Evidence





============================================================
TEMPLATES
============================================================

7 template files exist (Concept, Decision, Research, Development Day, Audit, Agent Handoff, Experiment).
Template content omitted from core snapshot but included in CONTENT_HASHES.md and VAULT_INVENTORY.md.