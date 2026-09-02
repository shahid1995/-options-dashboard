# StrikeNova Architecture Blueprint v1.0 — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the current StrikeNova modular monolith into the approved Intelligence-First Trading OS architecture through a controlled, dependency-ordered, test-backed day-by-day implementation sequence without premature live execution or architectural drift.

**Architecture:** Keep the existing FastAPI + SQLAlchemy + Alembic backend and Next.js App Router frontend, progressively strengthening explicit domain boundaries inside a modular monolith. PostgreSQL becomes the production transactional system of record; normalized market data feeds a shared quantitative core; deterministic intelligence precedes ML; centralized risk precedes live execution; broker adapters remain the execution boundary; paper and live share domain semantics.

**Tech Stack:** Python 3.13, FastAPI 0.141.1, SQLAlchemy 2.0.43, Alembic 1.15.2, psycopg 3, PostgreSQL 16, Next.js 14.2.35, React 18.3.1, JavaScript, Vitest 4.1.10, pytest/pytest-asyncio, Recharts 2.12.7, Axios 1.19.0, httpx 0.28.1, Railway backend, Vercel frontend, GitHub Actions.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-02-strikenova-architecture-blueprint-v1-design.md`

## Global Constraints

- PostgreSQL is the production transactional system of record; SQLite remains only where explicitly supported for local development/test compatibility.
- Alembic is the sole authoritative schema-management mechanism.
- Production schema changes use `Expand → Migrate → Contract`.
- Broker truth remains authoritative for actual broker orders, fills, positions, account state and broker-provided values.
- StrikeNova owns derived intelligence and must distinguish broker-provided values from calculated/model values.
- Opportunity discovery never directly implies an order; preserve `Observation → Signal → Setup → Opportunity → Strategy Candidate → Risk Check → User Decision → Execution`.
- Deterministic, explainable intelligence must exist before ML augmentation.
- Evidence, confidence and data quality remain separate concepts; no opaque single score replaces the evidence trail.
- Every intelligence result must carry freshness, completeness, validity, consistency, continuity, anomaly and provenance context as applicable.
- User broker connections are not the platform's historical-data acquisition mechanism; historical acquisition remains admin-controlled.
- Broker credentials must be encrypted at rest and never logged or exposed to frontend code.
- Strict tenant isolation and resource ownership are mandatory.
- AI begins read/analyze/simulate only; unrestricted live execution is not an initial capability.
- Live execution cannot be enabled until all hard gates in this plan are passed and explicitly approved.
- No uncontrolled production deployment, merge, or production cutover is performed by the implementation agent.
- Each day ends with tests, verification, a short evidence record, and a gate. A failed gate keeps that day open; the calendar does not override correctness.
- Each implementation task follows TDD: failing test → minimal implementation → focused test pass → broader regression test → commit.
- Existing strong foundations must be preserved unless a concrete defect requires change: paper execution semantics, broker canonical objects, BrokerAdapter boundary, GEX math/sign convention, GEX quality framework, RAW→MODEL→ANALYTICS historical architecture, and Alembic discipline.
- This plan is a sequencing contract, not permission to skip the approval gate for individual implementation batches.

---

# 0. How to Execute This Plan

## Daily operating loop

Every implementation day follows the same sequence:

1. Read the relevant Blueprint sections and this day's objective.
2. Inspect current code before changing it.
3. Identify the smallest testable task boundary.
4. Write the failing test(s) first.
5. Implement the minimum change that satisfies the test and Blueprint.
6. Run focused tests.
7. Run the relevant backend/frontend regression suite.
8. Inspect the diff for scope creep and architectural drift.
9. Record verification evidence and unresolved risks.
10. Commit the day's coherent work.
11. Evaluate the day's exit gate.
12. Only after a PASS does the next day become active.

## Daily status states

- `NOT STARTED` — not yet active.
- `IN PROGRESS` — work is active.
- `BLOCKED` — an external dependency or unresolved design issue prevents completion.
- `GATE FAILED` — implementation exists but verification requirements are not met.
- `PASS` — all required evidence exists and the next day may start.

## Daily Definition of Done

A day is complete only when:

- all listed deliverables are implemented or the day is explicitly marked documentation/review-only;
- focused tests pass;
- relevant regression tests pass;
- no new unexplained failures remain;
- changed interfaces are documented;
- migration changes, if any, are tested against PostgreSQL;
- security-sensitive changes receive an explicit review;
- no unrelated files were changed;
- the day's verification evidence is recorded;
- the phase gate is satisfied when the day is a phase boundary.

## Recovery rule

If a test, migration, broker contract, quant invariant, security check, or production-readiness gate fails, stop advancing the sequence and diagnose the root cause before continuing. Do not stack later work on an unstable foundation.

---

# 1. Master Roadmap

| Phase | Days | Objective | Exit Gate |
|---|---:|---|---|
| Phase 0 | 1–3 | Security emergency and repository hygiene | Security Gate |
| Phase 1 | 4–8 | PostgreSQL/infrastructure foundation | Infrastructure Gate |
| Phase 2 | 9–13 | Market-data foundation and provenance | Market Data Gate |
| Phase 3 | 14–18 | Shared quantitative core | Quant Gate |
| Phase 4 | 19–27 | Deterministic market intelligence | Intelligence Gate |
| Phase 5 | 28–32 | Opportunity + strategy intelligence | Opportunity Gate |
| Phase 6 | 33–36 | Central risk + portfolio intelligence | Risk Gate |
| Phase 7 | 37–42 | Event lifecycle + broker execution | Execution Gate |
| Phase 8 | 43–46 | Production SaaS control plane | Production SaaS Gate |
| Phase 9 | 47–51 | Backtesting + ML foundation | Research Gate |
| Phase 10 | 52–55 | AI Copilot | AI Gate |
| Phase 11 | 56–60 | Hardening, scale, release readiness | Final Release Gate |

**Planning horizon:** 60 focused implementation days. This is intentionally a sequence, not a promise that every calendar day will contain identical workload. Complex verification days may consume more than one calendar day without violating the plan.

---

# Phase 0 — Security Emergency

## Day 1 — Repository secret containment

**Objective:** Remove the P0 repository-secret risk before adding new architecture.

**Files/areas:** `.env*`, `backend/.env*`, frontend environment files, GitHub Actions workflows, `.gitignore`, repository history, deployment configuration documentation.

**Tasks:**
- [ ] Inventory tracked and ignored environment/secret files.
- [ ] Identify whether any credential-like values or encryption keys were committed.
- [ ] Remove secrets from tracked files without exposing replacements in source.
- [ ] Strengthen ignore rules for environment and local-secret files.
- [ ] Add secret-scanning/credential-pattern CI checks appropriate to the repository.
- [ ] Document required deployment-secret names without storing values.
- [ ] Rotate any credential that was actually exposed in repository history through the appropriate provider/broker account.

**Tests/verification:** Git tracked-file scan; secret-pattern scan; CI workflow validation; application startup with test environment values.

**Gate:** No active credential remains in tracked source; required rotations are complete or explicitly recorded as an external action; CI detects newly introduced secret patterns.

## Day 2 — Security baseline and dependency hygiene

**Objective:** Establish repeatable baseline security checks.

**Files/areas:** dependency manifests, GitHub Actions, auth/config modules, security documentation.

**Tasks:**
- [ ] Audit dependency versions and known security-sensitive packages.
- [ ] Verify JWT, cryptography, OAuth and HTTP client configuration boundaries.
- [ ] Add CI checks for dependency/security regressions that do not require paid services.
- [ ] Verify no secrets appear in logs, test output, exception payloads or API responses.
- [ ] Document security invariants and protected configuration requirements.

**Tests/verification:** dependency audit; auth/security regression suite; log/response assertions.

**Gate:** Security baseline is reproducible in CI and no known high-risk configuration regression is left unexplained.

## Day 3 — Tenant and credential safety review

**Objective:** Validate existing identity, ownership and encrypted broker-credential foundations before database hardening.

**Files/areas:** `backend/app/identity.py`, `backend/app/crypto.py`, user/session/broker models and related tests.

**Tasks:**
- [ ] Trace authentication → user context → resource ownership for protected routes.
- [ ] Add tests proving one user cannot access another user's broker connections, paper accounts, orders or portfolio records.
- [ ] Verify broker credentials are encrypted before persistence and never returned through normal API schemas.
- [ ] Verify administrative access is explicit rather than inferred from ownership.

**Tests/verification:** cross-tenant negative tests; credential serialization tests; auth integration tests.

**Gate:** Tenant isolation and credential secrecy are demonstrated by tests.

---

# Phase 1 — Infrastructure Foundation

## Day 4 — PostgreSQL production baseline

**Objective:** Make PostgreSQL the explicit production database target.

**Files/areas:** `backend/app/db.py`, `backend/app/config.py`, Alembic configuration, deployment configuration and tests.

**Tasks:**
- [ ] Verify production database URL parsing and PostgreSQL driver behavior.
- [ ] Separate local SQLite convenience configuration from production PostgreSQL configuration.
- [ ] Validate connection pool settings against expected SaaS concurrency assumptions.
- [ ] Add startup/readiness checks that fail clearly when required production configuration is invalid.

**Verification:** PostgreSQL 16 integration tests; application startup against disposable/test PostgreSQL.

**Gate:** Production configuration unambiguously selects PostgreSQL and the application can connect safely.

## Day 5 — Alembic authority and schema drift

**Objective:** Eliminate ambiguity between application initialization and migrations.

**Files/areas:** Alembic migrations, `backend/app/db.py`, model metadata, migration tests.

**Tasks:**
- [ ] Inventory schema objects created outside Alembic.
- [ ] Move production-required indexes/constraints into migrations where they are currently created only during initialization.
- [ ] Add migration-from-empty-database verification.
- [ ] Add migration upgrade/downgrade or supported rollback verification where appropriate.
- [ ] Document unsupported downgrade cases explicitly rather than silently relying on them.

**Gate:** A clean PostgreSQL database can be constructed solely through Alembic and matches expected application metadata.

## Day 6 — PostgreSQL performance baseline

**Objective:** Establish safe connection, transaction and index behavior for expected workload.

**Files/areas:** database models, Alembic indexes, DB integration tests.

**Tasks:**
- [ ] Review high-frequency tables and query paths.
- [ ] Add missing composite indexes identified by actual query patterns.
- [ ] Validate transaction boundaries for paper trading and future execution lifecycle.
- [ ] Verify connection pool exhaustion behavior.

**Verification:** representative query plans; concurrency tests; PostgreSQL integration tests.

**Gate:** No known critical query path is unindexed or dependent on SQLite-specific behavior.

## Day 7 — Session persistence hardening

**Objective:** Remove production fragility caused by in-memory session state.

**Files/areas:** session/auth services, user/session models, OAuth flow, auth tests.

**Tasks:**
- [ ] Define durable session lifecycle and expiration semantics.
- [ ] Persist the state required for multi-instance authentication.
- [ ] Remove production reliance on process-local session state.
- [ ] Replace blocking OAuth network work inside async request paths with an async-safe approach or isolated execution boundary.

**Verification:** restart persistence tests; multi-process/multi-instance behavior tests; OAuth integration tests.

**Gate:** Restarting the backend does not invalidate valid persistent sessions unexpectedly and async request paths do not contain known blocking OAuth calls.

## Day 8 — Infrastructure phase gate

**Objective:** Prove the infrastructure foundation as a coherent unit.

**Tasks:**
- [ ] Run full backend regression suite.
- [ ] Run migration safety suite against PostgreSQL 16.
- [ ] Run security checks.
- [ ] Review changed migrations and indexes.
- [ ] Document current PostgreSQL readiness status and remaining cutover blockers.

**Gate:** **Infrastructure Gate PASS.** PostgreSQL + Alembic + durable sessions + security baseline are stable. No production cutover occurs yet.

---

# Phase 2 — Market Data Foundation

## Day 9 — Canonical market-data contracts

**Objective:** Establish normalized market-data domain contracts independent of any broker.

**Files/areas:** `backend/app/brokers/`, new market-data domain modules, schemas, tests.

**Tasks:**
- [ ] Define canonical observation structures for instrument, quote, option chain and market snapshot.
- [ ] Include market timestamp, received timestamp, source, data mode, sequence ID where available, freshness and quality state.
- [ ] Preserve broker payloads separately from normalized fields where required for diagnostics.
- [ ] Add contract tests for normalization invariants.

**Gate:** Broker-specific market payloads can map into a stable canonical contract.

## Day 10 — Upstox quote/chain adapter completion

**Objective:** Complete the missing read-side market-data capabilities in the Upstox adapter.

**Files/areas:** `backend/app/brokers/adapters/upstox/`, gateway/registry, adapter tests.

**Tasks:**
- [ ] Implement canonical quote retrieval.
- [ ] Implement batch quote retrieval where the broker supports it.
- [ ] Normalize option-chain responses into canonical contracts.
- [ ] Preserve broker-provided Greeks/IV as broker values rather than silently replacing them.
- [ ] Add mocked contract tests for success, stale data, malformed payload and broker error cases.

**Gate:** Upstox market-data read path passes contract tests without leaking broker-specific structures upward.

## Day 11 — Market-data gateway and provenance

**Objective:** Introduce a source-neutral gateway above broker adapters.

**Files/areas:** market-data service/gateway, broker gateway, provenance schemas, tests.

**Tasks:**
- [ ] Define source selection and data-mode semantics.
- [ ] Normalize timestamps and freshness calculations.
- [ ] Attach provenance metadata to every normalized observation.
- [ ] Ensure delayed data is never labeled real-time.

**Gate:** Consumers can request normalized market data without knowing which source supplied it.

## Day 12 — Data quality engine

**Objective:** Generalize the existing GEX-specific quality discipline into a reusable quality engine.

**Files/areas:** new data-quality domain module, GEX quality integration, tests.

**Tasks:**
- [ ] Define quality dimensions: freshness, completeness, validity, consistency, continuity, anomaly state and source reliability.
- [ ] Produce `quality_score` and `EXCELLENT/GOOD/DEGRADED/INSUFFICIENT` classification.
- [ ] Define structured quality issues.
- [ ] Make GEX consume the shared quality contract without changing its established mathematical sign convention.

**Gate:** Quality output is deterministic, explainable and reusable across market-data consumers.

## Day 13 — Streaming lifecycle and market-data phase gate

**Objective:** Harden real-time ingestion behavior and close the phase.

**Tasks:**
- [ ] Define reconnect/resubscribe/backoff behavior.
- [ ] Detect stale streams and sequence discontinuity where supported.
- [ ] Emit recovery/data-quality events for downstream consumers.
- [ ] Run market-data contract, quality and regression suites.

**Gate:** **Market Data Gate PASS.** StrikeNova has a source-neutral, provenance-aware market-data boundary with explicit quality semantics.

---

# Phase 3 — Shared Quantitative Core

## Day 14 — Quantitative domain boundary

**Objective:** Create the shared quantitative core that becomes authoritative for platform decisions.

**Files/areas:** new backend quant domain, existing frontend `frontend/lib/calculations/`, tests.

**Tasks:**
- [ ] Define backend quantitative service boundaries.
- [ ] Define model-vs-broker value semantics.
- [ ] Establish deterministic numeric precision/tolerance policy.
- [ ] Create golden-test fixtures for representative option contracts.

**Gate:** Quant consumers have a stable backend contract without prematurely deleting frontend calculations.

## Day 15 — Greeks core

**Objective:** Move Black-Scholes/Greek calculations into a tested shared quantitative implementation.

**Tasks:**
- [ ] Port supported Greek calculations with explicit units and conventions.
- [ ] Add edge-case tests for near-expiry, zero/near-zero volatility, deep ITM/OTM and invalid inputs.
- [ ] Compare against existing trusted frontend behavior using golden fixtures.
- [ ] Keep broker-provided Greeks separate from model Greeks.

**Gate:** Backend Greeks match the established model within declared tolerances.

## Day 16 — IV and pricing core

**Objective:** Establish authoritative implied-volatility and pricing calculations.

**Tasks:**
- [ ] Define IV solver contract and failure classifications.
- [ ] Add price/IV round-trip tests.
- [ ] Add convergence and invalid-market-input tests.
- [ ] Expose calculation version metadata.

**Gate:** IV/pricing behavior is deterministic, bounded and explainable.

## Day 17 — GEX and gamma analytics consolidation

**Objective:** Consolidate existing Phase 7.1/7.2 GEX behavior under the shared quant core without changing validated semantics.

**Files/areas:** existing GEX implementations, `gexPhase72.js`, backend live GEX service, GEX tests/specs.

**Tasks:**
- [ ] Preserve `raw_gex = gamma × OI × spot² × 0.01`.
- [ ] Preserve OI-as-contracts semantics.
- [ ] Preserve `NAIVE_DEALER_CONVENTION` as an explicit model assumption.
- [ ] Reuse shared gamma calculations for gamma flip and gamma walls.
- [ ] Add cross-language golden tests comparing backend and frontend outputs.

**Gate:** Existing GEX suite remains green and backend/frontend divergence is eliminated or explicitly explained.

## Day 18 — Scenario/sensitivity core and quant gate

**Objective:** Make the scenario engine reusable by strategy, portfolio, opportunity, backtest and AI domains.

**Tasks:**
- [ ] Define Price × Time × IV scenario service contract.
- [ ] Add portfolio sensitivity aggregation.
- [ ] Verify scenario calculations against existing frontend behavior.
- [ ] Run full quant golden dataset and regression suite.

**Gate:** **Quant Gate PASS.** Shared quantitative services are authoritative, tested and reusable.

---

# Phase 4 — Deterministic Market Intelligence

## Day 19 — Intelligence contract and evidence model

**Objective:** Establish the common contract all intelligence engines must produce.

**Tasks:**
- [ ] Define normalized input envelope.
- [ ] Define output fields for derived measurements, signals, evidence, confidence, quality, timestamps and calculation/model version.
- [ ] Define evidence reference format.
- [ ] Define signal strength vs confidence vs data quality semantics.

**Gate:** Intelligence engines can compose without losing provenance or uncertainty.

## Day 20 — Positioning intelligence foundation

**Objective:** Build OI/positioning interpretation as a first-class domain.

**Tasks:**
- [ ] Track OI concentration, ΔOI, volume and migration.
- [ ] Add acceleration/deceleration, persistence and reversal metrics.
- [ ] Add CE/PE asymmetry and price confirmation/conflict.
- [ ] Add deterministic classifications for long buildup, short buildup, short covering and long unwinding.

**Gate:** Raw observation, derived metric, classification and contextual interpretation remain separate.

## Day 21 — Dynamic support/resistance engine

**Objective:** Build evidence-weighted dynamic levels.

**Tasks:**
- [ ] Combine OI, ΔOI, volume, price reaction, GEX, flow, historical reactions and regime context.
- [ ] Produce level score, direction, evidence, confidence and quality.
- [ ] Ensure highest OI alone cannot automatically become support/resistance.
- [ ] Add historical-reaction persistence tests.

**Gate:** Levels are multi-factor and explainable.

## Day 22 — Institutional-like activity engine

**Objective:** Detect observable large-player signatures without claiming to identify institutions.

**Tasks:**
- [ ] Detect unusual concentration and aggressive flow signatures.
- [ ] Detect OI/price mismatches and large directional shifts.
- [ ] Detect repeated behavior patterns.
- [ ] Use compliant language such as "large-player activity detected" rather than naming institutions.

**Gate:** Outputs describe observable behavior, evidence and uncertainty only.

## Day 23 — Market regime engine

**Objective:** Build a multidimensional continuously updated market state.

**Tasks:**
- [ ] Model direction, trend strength, volatility, structure, gamma regime, positioning and liquidity.
- [ ] Produce confidence and transition indicators.
- [ ] Add deterministic regime classification tests.

**Gate:** Regime state is multidimensional and transition-aware.

## Day 24 — Expiry intelligence and market events

**Objective:** Add expiry-specific intelligence and event detection.

**Tasks:**
- [ ] Build expiry context: positioning, gamma, pinning pressure, strike concentration and time-decay context.
- [ ] Build event detection for significant market-state transitions.
- [ ] Add timestamped event evidence and quality metadata.

**Gate:** Expiry and event outputs can be consumed by opportunity and AI layers.

## Day 25 — Trap/false-move detection

**Objective:** Detect likely traps through confirmation/conflict rather than one indicator.

**Tasks:**
- [ ] Combine price action, positioning, volatility, GEX and flow.
- [ ] Model confirmation vs conflict.
- [ ] Output trap evidence, invalidation and confidence.
- [ ] Add adversarial historical fixtures for false positives.

**Gate:** Trap detection is multi-factor and does not assert certainty.

## Day 26 — Intelligence synthesis and conflict resolution

**Objective:** Combine engine outputs into transparent market intelligence.

**Tasks:**
- [ ] Implement evidence-weighted conflict resolution.
- [ ] Produce Bull Evidence, Bear Evidence, Net Bias, Signal Strength, Confidence, Data Quality, Regime, Horizon and Evidence References.
- [ ] Ensure signal strength cannot overwrite confidence or quality.
- [ ] Add deterministic conflict fixtures.

**Gate:** Conflicting signals remain visible and explainable.

## Day 27 — Intelligence phase gate

**Objective:** Validate the complete deterministic intelligence layer.

**Tasks:**
- [ ] Run all intelligence unit/integration/golden tests.
- [ ] Verify data-quality propagation through each engine.
- [ ] Verify evidence references are preserved end-to-end.
- [ ] Review outputs for claims that exceed observable data.

**Gate:** **Intelligence Gate PASS.** Deterministic intelligence is reliable enough to feed opportunities and strategies.

---

# Phase 5 — Opportunity and Strategy Intelligence

## Day 28 — Opportunity domain

**Objective:** Formalize the opportunity pipeline.

**Tasks:**
- [ ] Implement `Observation → Signal → Setup → Opportunity` domain transitions.
- [ ] Store thesis, evidence, regime, horizon, expected behavior and invalidation conditions.
- [ ] Ensure opportunity creation never submits an order.

**Gate:** Opportunities are distinct from execution intents.

## Day 29 — Scalping opportunity engine

**Objective:** Build a short-horizon opportunity engine with strict freshness requirements.

**Tasks:**
- [ ] Define short-horizon input window and freshness thresholds.
- [ ] Combine price, flow, positioning, GEX, regime and event state.
- [ ] Rank opportunities by evidence and quality.
- [ ] Suppress stale/insufficient data opportunities.

**Gate:** Scalping signals degrade or suppress safely under stale data.

## Day 30 — Best-strike ranking

**Objective:** Build multi-factor strike selection.

**Tasks:**
- [ ] Rank liquidity, spread quality, IV, Greeks, positioning, GEX, distance to spot, strategy objective and risk.
- [ ] Separate ranking score from confidence and quality.
- [ ] Add deterministic ranking fixtures.

**Gate:** Same inputs produce stable ranking and explanations identify why a strike ranked higher.

## Day 31 — Strategy evaluation engine

**Objective:** Unify strategy evaluation across simulation contexts.

**Tasks:**
- [ ] Evaluate payoff, Greeks, scenarios, regime, liquidity, risk and historical behavior.
- [ ] Reuse shared scenario and risk contracts.
- [ ] Define strategy-evaluation result schema with evidence.

**Gate:** Strategy evaluation is consistent across paper/backtest/opportunity contexts.

## Day 32 — Strategy lifecycle and opportunity gate

**Objective:** Connect opportunity discovery to strategy candidates without coupling to execution.

**Tasks:**
- [ ] Add `Strategy Candidate` transition.
- [ ] Connect ranked strikes to strategy templates.
- [ ] Verify user decision remains a mandatory boundary before execution.
- [ ] Run opportunity and strategy integration tests.

**Gate:** **Opportunity Gate PASS.** Opportunity and strategy intelligence can produce explainable candidates without creating broker orders.

---

# Phase 6 — Central Risk and Portfolio Intelligence

## Day 33 — Central risk engine contract

**Objective:** Create one risk authority shared by Strategy, Backtest, Paper, Live, Portfolio, Opportunity and AI.

**Tasks:**
- [ ] Define trade, position, portfolio and execution risk contracts.
- [ ] Define risk decision: allow, warn, block with reasons/evidence.
- [ ] Define limits and configuration ownership.
- [ ] Keep broker truth immutable.

**Gate:** All downstream domains can ask the same risk engine for decisions.

## Day 34 — Paper trading integration with centralized risk

**Objective:** Make the existing server-authoritative paper execution the golden execution laboratory.

**Files/areas:** `backend/app/services/paper_execution.py`, paper models/services/tests.

**Tasks:**
- [ ] Route paper order intents through centralized risk checks.
- [ ] Preserve atomic validation, idempotency, tick-size normalization and position netting.
- [ ] Add tests proving risk blocks are authoritative before paper fills.
- [ ] Keep fill semantics server-side.

**Gate:** Paper execution uses central risk without regressing existing execution correctness.

## Day 35 — Portfolio intelligence

**Objective:** Build multidimensional portfolio state and analytics.

**Tasks:**
- [ ] Normalize positions, exposures, Greeks, GEX and scenario sensitivities.
- [ ] Add concentration, directional and regime-aware risk views.
- [ ] Keep actual broker positions authoritative where applicable.
- [ ] Add portfolio risk tests.

**Gate:** Portfolio analytics consume shared quant/risk services and do not invent broker truth.

## Day 36 — Risk gate

**Objective:** Prove risk is downstream-independent and ready to protect execution.

**Tasks:**
- [ ] Run trade/position/portfolio/execution risk tests.
- [ ] Test limit breaches, stale data, missing data and conflicting signals.
- [ ] Verify paper and future live intent use the same risk decision contract.

**Gate:** **Risk Gate PASS.** No live execution work proceeds before this gate passes.

---

# Phase 7 — Event Lifecycle and Broker Execution

## Day 37 — Domain event foundation

**Objective:** Introduce internal domain events inside the modular monolith before considering distributed services.

**Tasks:**
- [ ] Define event envelope with event ID, type, aggregate, timestamp, tenant context and version.
- [ ] Define publishing/handling boundaries.
- [ ] Add idempotent handler semantics.
- [ ] Keep event architecture in-process initially.

**Gate:** Core domains can emit and consume typed domain events without circular coupling.

## Day 38 — Trade lifecycle state machine

**Objective:** Implement event-sourced trade lifecycle semantics.

**Tasks:**
- [ ] Define intent → order request → broker response → order state → fill → position lifecycle.
- [ ] Define valid and invalid state transitions.
- [ ] Store lifecycle/audit events.
- [ ] Add replay/state-reconstruction tests.

**Gate:** Lifecycle state is deterministic and invalid transitions are rejected.

## Day 39 — Order-state synchronization

**Objective:** Build event-driven broker state updates with exceptional recovery only.

**Tasks:**
- [ ] Consume broker order/fill events where supported.
- [ ] Update local normalized state idempotently.
- [ ] Define reconnect/restart recovery for missed events.
- [ ] Do not introduce continuous polling reconciliation as the normal path.

**Gate:** Normal operation is event-driven; recovery paths are explicit and exceptional.

## Day 40 — Upstox order execution adapter

**Objective:** Wire canonical order requests/results to the Upstox adapter.

**Files/areas:** Upstox adapter, canonical broker models, gateway, execution service, contract tests.

**Tasks:**
- [ ] Implement place/modify/cancel order mapping.
- [ ] Implement order/trade/position/holding retrieval required for recovery.
- [ ] Normalize broker statuses and errors.
- [ ] Never expose raw broker secrets or opaque broker payloads to domain consumers.

**Gate:** Adapter passes canonical broker contract tests including rejected, partial and malformed responses.

## Day 41 — Execution safety and paper/live semantic parity

**Objective:** Apply defense-in-depth before any live execution enablement.

**Tasks:**
- [ ] Validate user authorization, strategy state, risk state, instrument validity, quantity/tick-size, idempotency and broker session before submission.
- [ ] Add duplicate-order protection.
- [ ] Add stale-price/data-quality safeguards where required by strategy.
- [ ] Compare paper and live lifecycle semantics using shared fixtures.

**Gate:** Execution safety invariants are enforced independently at multiple layers.

## Day 42 — Execution gate

**Objective:** Validate execution without enabling production live trading.

**Tasks:**
- [ ] Run broker contract tests.
- [ ] Run paper/live semantic parity tests.
- [ ] Run failure injection for broker rejection, timeout, duplicate request, reconnect and partial fill.
- [ ] Verify broker remains source of truth.
- [ ] Verify audit trail captures every execution transition.

**Gate:** **Execution Gate PASS.** Live execution code may exist behind explicit feature controls, but production live trading remains disabled until final release gates.

---

# Phase 8 — Production SaaS Control Plane

## Day 43 — Versioned API boundary

**Objective:** Converge backend endpoints around versioned domain APIs.

**Tasks:**
- [ ] Define API versioning convention.
- [ ] Separate domain schemas from persistence models.
- [ ] Normalize error envelopes.
- [ ] Add authorization checks at the domain boundary.

**Gate:** New domains expose stable versioned contracts.

## Day 44 — Frontend feature architecture

**Objective:** Organize Next.js around feature domains while reducing frontend ownership of platform decisions.

**Tasks:**
- [ ] Map current routes/components to market data, intelligence, opportunity, strategy, risk, portfolio and execution features.
- [ ] Move authoritative calculations toward backend APIs while retaining presentation helpers where appropriate.
- [ ] Standardize loading/error/stale-data states.
- [ ] Preserve responsive web as the primary client.

**Gate:** Frontend is a consumer/presentation layer for authoritative platform decisions.

## Day 45 — Admin control plane

**Objective:** Build dedicated administration for platform operations.

**Tasks:**
- [ ] Add admin authorization boundary.
- [ ] Add historical-data acquisition controls.
- [ ] Add instrument/configuration/retention controls.
- [ ] Add ingestion health, adapters, feature flags, model metadata and audit views.
- [ ] Ensure admin actions are audited.

**Gate:** Operational controls are separated from ordinary user workflows.

## Day 46 — Notifications, observability and SaaS gate

**Objective:** Make production operations observable and user-facing events actionable.

**Tasks:**
- [ ] Add event-driven notification abstraction for supported channels.
- [ ] Add structured logging and correlation IDs.
- [ ] Add health/readiness metrics and key latency/error telemetry.
- [ ] Add alerts for data staleness, broker failures, execution errors and background-job failures.
- [ ] Run E2E smoke tests.

**Gate:** **Production SaaS Gate PASS.** Identity, tenancy, admin, notifications and observability are production-grade enough for controlled release testing.

---

# Phase 9 — Historical, Backtesting and ML Foundation

## Day 47 — Durable background jobs

**Objective:** Replace CLI-only operational work with durable job execution where production scheduling is required.

**Tasks:**
- [ ] Define job model and idempotency semantics.
- [ ] Add durable queue/worker boundary appropriate to the modular-monolith architecture.
- [ ] Migrate historical ingestion orchestration into jobs.
- [ ] Add retries/backoff/dead-letter behavior.

**Gate:** Historical ingestion can survive process restart and retry safely.

## Day 48 — Historical data governance

**Objective:** Make admin-controlled historical data acquisition auditable and entitlement-aware.

**Tasks:**
- [ ] Add source/license/usage/redistribution/retention metadata.
- [ ] Track ingestion checkpoints and completeness.
- [ ] Preserve raw observations sufficiently to recompute derived intelligence.
- [ ] Enforce retention policies by dataset tier.

**Gate:** Historical datasets have explicit provenance and lifecycle metadata.

## Day 49 — Point-in-time backtesting

**Objective:** Prevent lookahead bias and future-data leakage.

**Tasks:**
- [ ] Define point-in-time dataset interface.
- [ ] Enforce timestamp cutoffs for all features.
- [ ] Add tests that deliberately attempt future-data leakage.
- [ ] Connect strategy evaluation and shared risk/scenario engines.

**Gate:** Backtests cannot access information after the simulated decision timestamp.

## Day 50 — Walk-forward and OOS validation

**Objective:** Establish honest model/strategy evaluation.

**Tasks:**
- [ ] Define train/validation/test windows.
- [ ] Implement walk-forward splits.
- [ ] Track out-of-sample metrics.
- [ ] Preserve dataset and feature versions.

**Gate:** Every research result can identify its dataset, feature and evaluation window.

## Day 51 — ML governance and research gate

**Objective:** Introduce ML only after deterministic intelligence is stable.

**Tasks:**
- [ ] Create versioned feature/dataset/model registry metadata.
- [ ] Define model evaluation and promotion criteria.
- [ ] Add deterministic-vs-ML comparison harness.
- [ ] Ensure ML cannot silently replace deterministic signals.

**Gate:** **Research Gate PASS.** ML is governed, reproducible and downstream of authoritative deterministic data.

---

# Phase 10 — AI Copilot

## Day 52 — AI context model

**Objective:** Give the AI Copilot structured access to authoritative market and trading context.

**Tasks:**
- [ ] Define AI context envelope containing market state, intelligence evidence, opportunity state, strategy state, risk state, portfolio state and data quality.
- [ ] Ensure context references versions/timestamps.
- [ ] Prevent AI from reading raw secrets or unauthorized tenant data.

**Gate:** AI receives structured authoritative context rather than scraping frontend state.

## Day 53 — Evidence-linked AI responses

**Objective:** Make AI explanations traceable.

**Tasks:**
- [ ] Require evidence references for market claims where applicable.
- [ ] Distinguish observed facts, calculated metrics, interpretation and uncertainty.
- [ ] Add tests for unsupported claims and missing evidence.

**Gate:** Copilot responses can be traced back to platform evidence.

## Day 54 — Capability-based AI permissions

**Objective:** Implement safe AI capabilities.

**Tasks:**
- [ ] Define read/analyze/simulate capabilities.
- [ ] Keep live execution capability disabled by default.
- [ ] Require explicit authorization for any future execution capability.
- [ ] Audit AI tool calls and decisions.

**Gate:** AI cannot bypass authorization or central risk.

## Day 55 — AI gate

**Objective:** Validate Copilot behavior against the platform architecture.

**Tasks:**
- [ ] Run tenant-isolation tests.
- [ ] Run evidence-link tests.
- [ ] Run permission-boundary tests.
- [ ] Run stale/low-quality-data scenarios.
- [ ] Verify AI never becomes the source of broker truth.

**Gate:** **AI Gate PASS.** Context-aware AI is safe, evidence-linked and capability-limited.

---

# Phase 11 — Final Hardening and Release Readiness

## Day 56 — Full-system testing pyramid

**Objective:** Close testing gaps across the entire platform.

**Tasks:**
- [ ] Run backend unit suite.
- [ ] Run frontend unit suite.
- [ ] Run integration tests.
- [ ] Run broker contract tests.
- [ ] Run quant golden/invariant tests.
- [ ] Run API/E2E tests.
- [ ] Add missing regression tests for material findings.

**Gate:** No unexplained test failures; critical domains have explicit regression coverage.

## Day 57 — Failure injection and graceful degradation

**Objective:** Prove the system behaves safely under partial failure.

**Tasks:**
- [ ] Simulate market-data staleness.
- [ ] Simulate broker timeout/rejection/disconnect.
- [ ] Simulate database interruption.
- [ ] Simulate background-job retry.
- [ ] Simulate frontend/backend version skew.
- [ ] Verify safe suppression/blocking behavior.

**Gate:** Failure modes degrade safely and recover without corrupting broker or trading truth.

## Day 58 — Performance and scalability rehearsal

**Objective:** Establish evidence for the modular-monolith scaling boundary.

**Tasks:**
- [ ] Load-test API and key market-data paths.
- [ ] Measure PostgreSQL connection utilization.
- [ ] Measure quant/intelligence computation latency.
- [ ] Test concurrent paper execution.
- [ ] Identify the first components that would justify service extraction at real scale.

**Gate:** Performance characteristics are measured rather than guessed; no premature microservice split is introduced.

## Day 59 — Release, security and operational rehearsal

**Objective:** Rehearse production release without enabling uncontrolled live trading.

**Tasks:**
- [ ] Verify GitHub Actions pipeline: test → build → security → preview → approval → production.
- [ ] Verify controlled rollback procedure.
- [ ] Verify database migration rehearsal and backup/restore process.
- [ ] Verify secrets are deployment-managed.
- [ ] Verify observability dashboards/alerts.
- [ ] Verify admin emergency controls and execution kill switch.

**Gate:** Controlled release can be performed with an explicit human approval step.

## Day 60 — Final architecture and live-trading readiness gate

**Objective:** Determine whether the implemented system satisfies the Blueprint and is eligible for controlled production activation.

**Tasks:**
- [ ] Re-run the full repository audit against the implemented architecture.
- [ ] Compare every Blueprint requirement against implementation evidence.
- [ ] Verify PostgreSQL production readiness.
- [ ] Verify security and tenant isolation.
- [ ] Verify market-data provenance and quality.
- [ ] Verify quant golden tests and backend/frontend parity.
- [ ] Verify intelligence evidence/confidence/quality separation.
- [ ] Verify centralized risk enforcement.
- [ ] Verify broker truth/execution lifecycle.
- [ ] Verify auditability and observability.
- [ ] Verify AI permissions and ML governance.
- [ ] Record all residual risks and explicit acceptance decisions.

**Final Gate:** **FINAL RELEASE GATE.** The implementation may be declared release-ready only if all hard gates below are PASS and the remaining production actions have explicit human approval.

---

# 2. Hard Gates Before Live Trading

Live trading is **not** enabled merely because Day 42 succeeds.

All of the following must be independently PASS:

1. **Security Gate** — no active repository secrets; credential rotation complete; tenant isolation tested; broker credentials encrypted.
2. **Infrastructure Gate** — PostgreSQL production path stable; Alembic authoritative; durable sessions; tested migrations.
3. **Market Data Gate** — canonical data contracts, provenance, freshness and quality controls operational.
4. **Quant Gate** — golden datasets pass; model/broker values remain distinct; critical calculations have deterministic tolerances.
5. **Intelligence Gate** — deterministic intelligence is evidence-linked and quality-aware.
6. **Opportunity Gate** — opportunity and strategy layers cannot bypass user decision boundaries.
7. **Risk Gate** — centralized risk can block trade/position/portfolio/execution actions.
8. **Execution Gate** — broker order lifecycle is idempotent, audited and failure-tested.
9. **Production SaaS Gate** — identity, RBAC/ownership, admin, observability, notifications and controlled deployment exist.
10. **Research Gate** — backtests are point-in-time; ML is versioned and governed.
11. **AI Gate** — AI is tenant-safe, evidence-linked and capability-limited.
12. **Final Release Gate** — fresh full-system verification and human approval.

A failed gate blocks the next dependent phase.

---

# 3. Explicit Non-Goals During This Sequence

The following are deliberately excluded unless a later approved change modifies the Blueprint:

- Immediate microservice decomposition.
- Unbounded raw-market-data warehousing in PostgreSQL.
- Using customer broker connections as the historical-data ingestion mechanism.
- Identifying specific institutions from public market data.
- An opaque AI-generated market score replacing evidence.
- ML replacing deterministic domain calculations before validation.
- AI receiving unrestricted live-order authority.
- Continuous reconciliation as the normal execution path.
- Premature native mobile development before responsive web/PWA needs are proven.
- Uncontrolled auto-deployment.
- Rewriting strong existing paper-execution and GEX foundations without evidence of a defect.

---

# 4. Daily Control Ledger

At the start of each day, copy the day's entry into the project control record and update:

```text
Day: N
Objective:
Status: NOT STARTED | IN PROGRESS | BLOCKED | GATE FAILED | PASS
Changes:
Tests added:
Focused verification:
Regression verification:
Security/quant/data-quality considerations:
Known risks:
Commit(s):
Gate result:
Next eligible day:
```

This ledger is intentionally separate from the implementation itself. It is the operational memory of the sequence.

---

# 5. Change-Control Rules

## If a new feature is requested during execution

1. Do not insert it directly into the current day.
2. Classify it against the Blueprint.
3. Determine dependencies and security/quant/execution impact.
4. Add it to the appropriate future day or create a separately approved sub-plan.
5. Preserve the existing dependency order.

## If implementation reveals a Blueprint defect

1. Stop at the affected gate.
2. Document the evidence.
3. Propose the smallest architectural correction.
4. Obtain approval.
5. Update the Blueprint and this plan before implementing downstream work.

## If a task takes longer than one day

Do not compress or skip verification. Mark the day `IN PROGRESS` or `GATE FAILED`, split the remaining work into a continuation day if necessary, and preserve the original sequence.

## If an unrelated improvement is discovered

Record it as a backlog item. Do not mix it into the active day's scope unless it is required to satisfy the current gate.

---

# 6. Success Criteria

At completion, StrikeNova should have:

- A production-grade PostgreSQL transactional foundation.
- Durable identity/session and strict tenant isolation.
- A source-neutral, provenance-aware hybrid market-data architecture.
- A shared authoritative quantitative engine.
- Core GEX/Greek/IV/scenario intelligence with validated semantics.
- Evidence-driven positioning, levels, institutional-like activity, regime, expiry, event and trap intelligence.
- A transparent intelligence synthesis layer separating strength, confidence and data quality.
- Opportunity and strategy intelligence separated from execution.
- Centralized multi-layer risk.
- Shared paper/live trading semantics with broker truth preserved.
- Event-driven order/fill lifecycle with exceptional recovery paths.
- A production SaaS admin, notification and observability control plane.
- Point-in-time backtesting and walk-forward evaluation.
- Governed offline ML.
- Evidence-linked, capability-limited AI Copilot.
- Controlled CI/CD and release procedures.
- A complete verification record demonstrating that the architecture has been implemented without uncontrolled scope drift.

The product position remains:

> **Intelligence-First Trading OS, architecting toward an Agentic Trading Platform.**

---

# 7. Approval and Execution Boundary

This document is the **master sequencing plan** derived from the approved Blueprint. It does not itself authorize production deployment, database cutover, or live trading.

Before implementation begins, the implementation plan must be accepted as the execution sequence. Once accepted, execution proceeds one day at a time with the daily gate mechanism above.
