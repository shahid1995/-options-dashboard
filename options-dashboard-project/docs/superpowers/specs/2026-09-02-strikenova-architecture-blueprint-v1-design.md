# StrikeNova Architecture Blueprint v1.0 — Design Specification

**Date:** 2026-09-02  
**Status:** DESIGN — awaiting human approval before implementation planning  
**Repository:** `shahid1995/-options-dashboard`  
**Baseline branch:** `feat/postgres-readiness`  
**Source of truth for current-state assessment:** `docs/audits/STRIKENOVA_FULL_REPOSITORY_AUDIT_2026-09-02.md`

---

## 1. Purpose

This document converts the full repository audit and the previously approved StrikeNova architecture decisions into one coherent target architecture.

It is intentionally a design specification, not an implementation plan. No source-code restructuring, live broker execution, deployment, database cutover, or production configuration change is authorized by this document alone.

StrikeNova's product direction is:

> **Intelligence-First Trading OS, architecting toward an Agentic Trading Platform.**

The platform must first become a reliable quantitative and market-intelligence system, then expose strategy and execution capabilities on top of that foundation.

---

## 2. Current-State Baseline

The 2026-09-02 repository audit found a strong existing foundation:

- FastAPI + SQLAlchemy + Alembic backend.
- Next.js App Router frontend.
- Server-authoritative paper execution with atomic validation and idempotency.
- Clean broker adapter protocol, gateway and registry, currently validated with Upstox only.
- Strong GEX implementation including gamma flip, gamma walls and data-quality handling.
- RAW → MODEL → ANALYTICS historical-data architecture.
- Identity, BYOB broker-credential encryption and multi-user data ownership foundations.
- Large automated test suite.

The audit also identified the major gaps:

- PostgreSQL migration not yet merged/cut over.
- Partly in-memory session state.
- No durable background-job infrastructure.
- Upstox is the only operational broker adapter.
- Market data remains broker-centric rather than hybrid.
- Important quantitative calculations remain frontend-owned.
- Positioning, dynamic levels, institutional-like activity, trap/event, opportunity and several other intelligence engines are absent or shallow.
- Centralized backend risk is absent.
- Live broker order execution is absent.
- Event-driven lifecycle is absent.
- AI/ML, point-in-time backtesting and walk-forward validation are absent.
- Admin, notification, observability, mature CI/CD and E2E infrastructure need expansion.
- Repository secrets and other security hardening require P0 treatment.

These facts are architectural constraints, not reasons to rewrite the system.

---

# 3. Architectural Principles

## 3.1 Broker truth vs StrikeNova intelligence

The broker is authoritative for facts supplied by the broker, especially:

- accepted/rejected orders
- actual fills
- actual positions
- broker account state
- broker-provided market values
- broker session state

StrikeNova owns derived intelligence:

- GEX
- Greeks derived by its models
- IV analytics
- positioning interpretation
- market regime
- levels
- opportunities
- scenarios
- risk analytics
- strategy evaluation

Broker values and StrikeNova-derived values must remain distinguishable.

## 3.2 Opportunity is not an order

The platform must preserve the hierarchy:

`Observation → Signal → Setup → Opportunity → Strategy Candidate → Risk Check → User Decision → Execution`

An intelligence engine may discover an opportunity without creating an order.

## 3.3 Deterministic foundation before ML

Every major intelligence capability must have a deterministic, explainable baseline before ML is allowed to replace or augment it.

ML is an evolution layer, not a substitute for missing domain logic.

## 3.4 Evidence before conclusion

Signals and AI responses must retain the evidence that produced them. StrikeNova must not hide important uncertainty behind one opaque score.

## 3.5 Data quality is part of intelligence

Every intelligence result must be aware of:

- freshness
- completeness
- validity
- consistency
- continuity
- anomaly state
- provenance

Low-quality input must reduce confidence, flag the result, or suppress the result where appropriate.

## 3.6 Modular monolith first

The system remains a modular monolith until real scale or operational characteristics justify service extraction.

Boundaries must be explicit enough that later extraction does not require rewriting domain contracts.

## 3.7 Paper and live share domain semantics

Paper trading is not a disposable toy implementation. The same order-intent, risk, lifecycle and audit concepts should support paper and live execution while the actual execution backend differs.

---

# 4. Target System Architecture

```text
                              USER
                                │
                                ▼
                    ┌──────────────────────┐
                    │ Next.js / PWA Client │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Versioned Domain API │
                    │       FastAPI        │
                    └──────────┬───────────┘
                               │
       ┌───────────────────────┼────────────────────────┐
       ▼                       ▼                        ▼
┌───────────────┐      ┌───────────────┐       ┌────────────────┐
│ Market Data   │      │ Trading       │       │ Intelligence   │
│ Platform      │      │ Domain        │       │ Platform       │
└───────┬───────┘      └──────┬────────┘       └───────┬────────┘
        │                     │                        │
        ▼                     ▼                        ▼
┌───────────────┐      ┌───────────────┐       ┌────────────────┐
│ Data Quality  │      │ Risk Engine   │       │ Quant Engine   │
└───────┬───────┘      └──────┬────────┘       └───────┬────────┘
        │                     │                        │
        └─────────────────────┼────────────────────────┘
                              ▼
                    ┌──────────────────────┐
                    │ Intelligence         │
                    │ Synthesis / Conflict │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Opportunity Engine   │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Strategy Intelligence│
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Execution Engine     │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Broker Gateway       │
                    └──────────┬───────────┘
                               ▼
                         Broker Adapters

Cross-cutting:
  Identity • Tenancy • Provenance • Audit • Observability
  Notifications • Feature Flags • Configuration • Model Governance
```

---

# 5. Domain Boundaries

The backend should converge on these explicit domains.

## 5.1 Identity & Access

Owns:

- users
- sessions
- authentication
- OAuth
- authorization
- roles
- resource ownership
- tenant context

Must not own market intelligence or trading calculations.

## 5.2 Broker Domain

Owns:

- broker connections
- broker sessions
- adapter registry
- canonical broker models
- capabilities
- broker errors
- broker-specific translation

Broker-specific behavior must remain inside adapters.

## 5.3 Market Data Domain

Owns:

- market-data sources
- normalized observations
- streaming lifecycle
- freshness
- sequence information
- provenance
- entitlements
- data-mode semantics

## 5.4 Quantitative Domain

Owns deterministic calculations:

- pricing
- Greeks
- IV
- GEX
- gamma flip
- gamma walls
- scenarios
- sensitivity
- portfolio quantitative exposure

## 5.5 Intelligence Domain

Owns interpretation and derived state:

- positioning
- levels
- institutional-like activity signatures
- market regime
- expiry intelligence
- events
- traps
- divergences
- intelligence synthesis
- conflict resolution

## 5.6 Opportunity Domain

Transforms signals into ranked, contextual opportunities.

It does not submit orders.

## 5.7 Strategy Domain

Owns:

- strategy templates
- strategy resolution
- strategy generation
- strategy evaluation
- strike selection
- strategy simulation
- strategy performance

## 5.8 Risk Domain

Owns centralized risk decisions for:

- trade
- position
- portfolio
- execution
- user/account limits

Risk may block StrikeNova actions but cannot rewrite broker truth.

## 5.9 Execution Domain

Owns:

- execution intents
- order requests
- order lifecycle
- idempotency
- broker submission
- broker event handling
- fills
- execution audit

## 5.10 Portfolio Domain

Owns normalized portfolio state and derived analytics.

Broker state remains authoritative for actual broker positions and fills.

## 5.11 Historical Data Domain

Owns admin-controlled acquisition and durable historical datasets.

User broker connections must not become the platform's historical-data ingestion mechanism.

## 5.12 AI/ML Domain

Owns:

- feature datasets
- training datasets
- model versions
- evaluation
- model registry
- inference context
- AI capabilities

AI remains downstream of authoritative domain data.

---

# 6. Database Architecture

PostgreSQL becomes the transactional system of record.

It is not intended to be an unlimited raw-market-data warehouse.

## 6.1 PostgreSQL responsibilities

- identity
- sessions
- broker connections
- paper trading
- order/execution lifecycle
- positions
- cash ledger
- portfolio state
- intelligence snapshots
- GEX history
- operational audit
- ingestion metadata
- model metadata

## 6.2 Market-data storage tiers

Use tiered storage:

```text
HOT       → recent operational data
WARM      → active historical analytics
COLD      → compressed/archive datasets
```

Retention is configurable and driven by product, cost and licensing requirements.

## 6.3 Migration policy

All schema changes follow:

`Expand → Migrate → Contract`

Alembic remains the sole authoritative schema-management mechanism.

SQLite may remain as a local-development/test convenience only if explicitly supported; production must use PostgreSQL.

---

# 7. Market Data Architecture

StrikeNova will use a hybrid model.

```text
               Market Data Gateway
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   Broker Real-Time         StrikeNova Dataset
          │                         │
          └────────────┬────────────┘
                       ▼
              Normalized Observation
                       ▼
                 Data Quality
                       ▼
                Quant / Intelligence
```

Broker-connected users receive the fastest valid broker data available.

Users without broker data may receive StrikeNova-provided data with explicit freshness/data-mode labeling.

Delayed data must never be represented as real-time.

## 7.1 Required observation metadata

Each normalized observation should support:

- instrument identity
- market timestamp
- received timestamp
- source
- data mode
- sequence ID where available
- freshness
- quality state
- payload/version

## 7.2 Reconnection

Streaming consumers require:

- reconnect
- resubscribe
- backoff
- stale-state detection
- sequence/continuity checks
- recovery events

---

# 8. Data Quality & Provenance

A global Data Quality Engine will extend the current excellent GEX-specific quality framework.

Quality dimensions:

- freshness
- completeness
- validity
- consistency
- continuity
- anomaly detection
- source reliability
- entitlement/provenance validity

Outputs:

```text
quality_score: 0–100
classification: EXCELLENT / GOOD / DEGRADED / INSUFFICIENT
issues: structured list
```

Every intelligence result should reference the quality state of its input data.

Provenance must include:

- source
- collection mode
- collection timestamp
- transformation version
- calculation version where applicable
- entitlement/license class

---

# 9. Quantitative Engine

The current frontend calculation functions should evolve into a shared quantitative core.

The first migration targets are:

1. GEX
2. Greeks
3. IV
4. pricing
5. scenarios
6. portfolio sensitivities

Frontend calculations may remain temporarily for presentation/performance, but backend/shared implementations become authoritative for platform decisions.

## 9.1 GEX

Preserve the verified current implementation:

`raw_gex = gamma × OI × spot² × 0.01`

OI units remain contracts, not lots.

Call/put sign convention remains explicitly documented as a model assumption (`NAIVE_DEALER_CONVENTION`).

## 9.2 Model vs broker values

Broker-provided Greeks/IV and StrikeNova-calculated Greeks/IV must be stored and exposed as separate values.

## 9.3 Scenario engine

The existing Price × Time × IV scenario engine becomes a reusable quantitative service for:

- strategy evaluation
- portfolio analysis
- opportunity analysis
- backtesting
- AI context

---

# 10. Intelligence Engine Contracts

Every intelligence engine should follow a common conceptual contract:

```text
Input:
  normalized observations
  market state
  data quality
  configuration/version

Output:
  derived measurements
  signals
  evidence
  confidence
  quality
  timestamps
  calculation/model version
```

The following engines are first-class domains.

## 10.1 Positioning Intelligence

Detect:

- OI concentration
- ΔOI
- volume
- migration
- acceleration/deceleration
- persistence
- reversal
- CE/PE asymmetry
- price confirmation/conflict
- long buildup
- short buildup
- short covering
- long unwinding

Raw observation must remain separate from interpretation.

## 10.2 Dynamic Level Engine

Support/resistance is evidence-weighted, not simply highest-OI-based.

Inputs may include:

- OI
- ΔOI
- volume
- price reaction
- GEX
- flow
- historical reactions
- market regime
- persistence

Output includes level score, direction, evidence, confidence and quality.

## 10.3 Institutional-Like Activity Engine

Detect observable signatures such as:

- unusual concentration
- aggressive flow
- OI/price mismatch
- large directional shifts
- repeated behavior

The product must never claim to identify a specific institution from public data.

Preferred wording:

- "Large-player activity detected"
- "Potential aggressive call writing"
- "Potential institutional-like positioning"

## 10.4 Market Regime Engine

Market regime is multidimensional:

- direction
- trend strength
- volatility
- structure
- gamma regime
- positioning
- liquidity
- confidence

It is continuously updated and supports transition detection.

## 10.5 Event Detection Engine

Detect market events and state transitions from normalized observations and derived intelligence.

## 10.6 Trap Detection Engine

Combine price action, positioning, volatility, GEX, flow and confirmation/conflict signals to detect likely false moves.

## 10.7 Expiry Intelligence Engine

Model expiry-specific:

- positioning
- gamma behavior
- pinning pressure
- strike concentration
- time decay context
- expiry-day regime changes

## 10.8 Scalping Opportunity Engine

Dedicated short-horizon engine using market microstructure-compatible observations and strict freshness requirements.

## 10.9 Strike Ranking Engine

Rank candidate strikes using:

- liquidity
- spread quality
- IV
- Greeks
- positioning
- GEX
- distance to spot
- strategy objective
- risk
- opportunity context

## 10.10 Strategy Evaluation Engine

Evaluate strategies consistently across:

- payoff
- Greeks
- scenario behavior
- market regime
- liquidity
- risk
- historical performance

---

# 11. Intelligence Synthesis

The synthesis layer combines engine outputs without destroying evidence.

Required output model:

```text
Bull Evidence
Bear Evidence
Net Bias
Signal Strength
Confidence
Data Quality
Market Regime
Time Horizon
Evidence References
```

Signal strength is not confidence.

Confidence is not data quality.

Data quality must remain independently visible.

## 11.1 Conflict resolution

Use evidence-weighted conflict resolution initially.

Future ML conflict modeling may learn calibrated probabilities, but the deterministic evidence trail remains available.

---

# 12. Opportunity Pipeline

The opportunity engine converts intelligence into actionable candidates.

```text
Observation
    ↓
Signal
    ↓
Setup
    ↓
Opportunity
    ↓
Strategy Candidate
    ↓
Risk Check
    ↓
User Decision
    ↓
Execution
```

Opportunity records should include:

- thesis
- evidence
- market regime
- horizon
- candidate strategy
- candidate strikes
- expected behavior
- invalidation conditions
- confidence
- data quality
- risk summary

No opportunity is automatically an order.

---

# 13. Strategy Architecture

Strategy generation and execution are separate.

The lifecycle is:

`Discover → Generate → Evaluate → Simulate → Risk → User Decision → Execute`

The same strategy representation should support:

`Backtest → Paper → Live`

The existing V1/V2 templates remain useful as deterministic building blocks rather than being discarded.

---

# 14. Risk Architecture

Central Risk Engine is a mandatory gate before live execution.

## 14.1 Trade risk

- max loss
- size
- premium
- stop/target
- reward/risk

## 14.2 Position risk

- delta
- gamma
- vega
- theta
- concentration

## 14.3 Portfolio risk

- total exposure
- directional exposure
- expiry concentration
- correlated exposure
- scenario loss

## 14.4 Execution risk

- duplicate order
- stale market data
- abnormal price
- invalid quantity
- tick size
- market status
- broker capability
- permissions

Risk decisions are explicit:

`APPROVED / REJECTED / DEGRADED / REQUIRES_CONFIRMATION`

---

# 15. Execution Architecture

Target lifecycle:

```text
Idea
 ↓
Candidate
 ↓
Risk Approved
 ↓
Order Requested
 ↓
Broker Accepted
 ↓
Partially Filled
 ↓
Filled
 ↓
Modified
 ↓
Exited
```

## 15.1 Defense in depth

```text
User Intent
 → Strategy Validation
 → Risk Engine
 → Order Validation
 → Idempotency
 → Broker
 → Broker Confirmation
 → Actual Fill
```

## 15.2 Broker authority

StrikeNova never invents a fill.

A broker fill becomes authoritative only from broker-confirmed state/event data.

## 15.3 Exceptional reconciliation

Continuous polling is not the normal lifecycle mechanism.

Reconciliation is used for recovery from:

- missed events
- reconnects
- network failures
- broker outages
- application restarts

---

# 16. Broker Protocol

Canonical broker capabilities include:

- authenticate
- refresh_session
- get_profile
- get_accounts
- get_instruments
- get_quotes
- get_option_chain
- get_positions
- get_orders
- get_fills
- place_order
- modify_order
- cancel_order
- subscribe_market_data

The Upstox adapter remains the first implementation.

A second adapter is an architectural validation milestone.

Core trading code must not contain broker-specific conditionals.

---

# 17. Event Model

Introduce domain events inside the modular monolith before considering distributed infrastructure.

Representative events:

- MarketObservationReceived
- DataQualityChanged
- MarketStateChanged
- SignalGenerated
- OpportunityDetected
- StrategyEvaluated
- RiskApproved
- RiskRejected
- OrderRequested
- BrokerOrderAccepted
- BrokerOrderRejected
- OrderPartiallyFilled
- OrderFilled
- PositionChanged
- PortfolioChanged
- NotificationTriggered

Events must be versioned and auditable where material.

A future message broker may replace internal transport only when scale/operational evidence justifies it.

---

# 18. Portfolio Intelligence

Portfolio State is built from authoritative broker/paper state.

StrikeNova derives:

- Greeks
- GEX exposure
- IV exposure
- scenario loss/profit
- concentration
- regime attribution
- strategy attribution
- performance
- risk

Actual broker positions/fills are never overwritten by analytics.

---

# 19. AI Copilot

The AI Copilot is context-aware rather than a generic chatbot.

It consumes structured context from:

- Market State
- Positioning
- GEX
- Levels
- Opportunity
- Strategy
- Risk
- Portfolio
- Data Quality
- Broker State

AI responses must link back to evidence.

AI is not a source of truth.

## 19.1 AI permissions

Initial capabilities:

- read
- analyze
- explain
- simulate
- compare

Live execution requires separate capability grants and explicit safety controls. Unrestricted autonomous live execution is not part of the initial AI release.

---

# 20. ML Architecture

Initial ML architecture:

```text
Historical Data
     ↓
Feature Generation
     ↓
Point-in-Time Dataset
     ↓
Training
     ↓
Validation
     ↓
Walk-Forward / OOS
     ↓
Model Registry
     ↓
Inference
```

Governance requires versioning of:

- dataset
- feature definitions
- feature version
- model
- training configuration
- evaluation results

No lookahead is permitted in training or backtesting.

---

# 21. Backtesting Integrity

Backtesting must use point-in-time information only.

At a historical timestamp, the engine may only access information that would have been available at that timestamp.

Required validation:

- no future OI
- no future price
- no future Greeks
- no future derived state
- no future model features
- explicit transaction costs/slippage assumptions

Walk-forward validation becomes the standard for predictive models.

---

# 22. Security & Multi-Tenancy

## 22.1 Tenant isolation

All user-owned resources must be scoped to the authenticated tenant/user context.

PostgreSQL Row-Level Security should be evaluated/introduced where it materially strengthens defense in depth.

## 22.2 Credentials

Broker credentials remain encrypted at rest.

Future requirements:

- rotation
- expiration enforcement
- key-management discipline
- access auditing

## 22.3 Security baseline

Required before production SaaS:

- secret removal and rotation
- secret scanning
- rate limiting
- CSRF protection where applicable
- CSP/security headers
- dependency scanning
- security tests
- immutable audit events

The currently reported repository `.env` exposure is a P0 remediation item.

---

# 23. Audit Architecture

Audit records must cover material security and trading events.

Examples:

- authentication
- login/logout
- session revocation
- broker connection changes
- credential changes
- permission changes
- admin actions
- feature-flag changes
- order intents
- risk decisions
- broker order responses
- fills
- critical configuration changes

Trading audit records must be immutable from normal user workflows.

---

# 24. Admin Control Plane

The dedicated admin plane owns operational controls such as:

- historical-data acquisition
- instruments/contracts
- ingestion jobs
- retention
- data quality
- broker adapters
- feature flags
- model versions
- users/tenants
- audit
- health
- operational configuration

Admin functionality must be separately authorized and audited.

---

# 25. Notifications

Event-driven notification engine should support:

- in-app
- email
- future mobile/push channels

Notifications should originate from domain events rather than intelligence engines directly coupling to communication providers.

---

# 26. Observability

Production observability must include:

- structured logs
- metrics
- distributed/request tracing where useful
- error tracking
- health/readiness
- broker latency
- market-data freshness
- ingestion status
- job status
- execution latency
- risk rejection counts
- data-quality degradation

Critical domain events should have correlation IDs.

---

# 27. Frontend Architecture

Move toward feature-oriented modules:

- dashboard
- market
- GEX
- positioning
- opportunities
- strategies
- risk
- portfolio
- paper trading
- live trading
- AI copilot
- admin

The current `/paper` 3600+ line page is a refactoring target, not a reason to change the underlying domain architecture.

Frontend should increasingly consume backend domain results rather than owning authoritative business calculations.

---

# 28. API Architecture

Target API convention:

`/api/v1/...`

APIs should be:

- domain-oriented
- authenticated
- tenant-scoped
- idempotent where applicable
- paginated for collections
- rate limited
- versioned
- schema validated

Avoid endpoints that expose internal database structure directly.

---

# 29. CI/CD and Release Architecture

Target release flow:

```text
GitHub
  ↓
Static / Security Checks
  ↓
Backend Tests
  ↓
Frontend Tests
  ↓
Quant Validation
  ↓
Integration / PostgreSQL
  ↓
Build
  ↓
Preview
  ↓
Approval Gate
  ↓
Production
  ↓
Smoke / Health Verification
```

No uncontrolled production deployment by development agents.

---

# 30. Testing Strategy

Testing layers:

1. unit
2. integration
3. broker contract
4. database migration
5. quantitative golden datasets
6. invariants/property tests
7. security
8. performance
9. E2E/browser
10. production smoke

Quantitative engines require known datasets and invariant checks, not only generic unit coverage.

Execution tests must include:

- idempotency
- partial fills
- reversal
- stale data
- broker rejection
- reconnect/recovery
- duplicate events
- restart recovery

---

# 31. Phased Implementation Roadmap

This roadmap supersedes the audit's suggestion to wire live execution immediately after basic stabilization.

## Phase 0 — Security Emergency

- remove repository secrets
- rotate exposed secrets
- verify Git history
- establish secret-management policy
- add secret scanning

**Gate:** no known repository-secret exposure remains.

## Phase 1 — Infrastructure Foundation

- PostgreSQL cutover
- persistent sessions
- migration cleanup
- backup/restore verification
- rate limiting
- security headers
- OAuth async hardening
- CI expansion
- operational database visibility

**Gate:** production-grade transactional foundation.

## Phase 2 — Market Data Foundation

- Market Data Gateway
- hybrid source architecture
- provenance
- timestamps/freshness
- reconnect/recovery
- global Data Quality Engine
- admin-controlled ingestion

**Gate:** reliable normalized market observations.

## Phase 3 — Quantitative Core

- shared backend GEX
- Greeks
- IV
- pricing
- scenarios
- portfolio sensitivities
- golden quantitative datasets

**Gate:** authoritative reusable quantitative core.

## Phase 4 — Market Intelligence

- positioning
- dynamic levels
- institutional-like activity
- market regime
- expiry intelligence
- event detection
- trap detection
- flow/divergence
- intelligence synthesis
- conflict resolution

**Gate:** explainable multi-factor market intelligence.

## Phase 5 — Opportunity & Strategy Intelligence

- opportunity pipeline
- strike ranking
- scalping intelligence
- strategy evaluation
- scenario-driven strategy analysis
- strategy performance attribution

**Gate:** opportunity can be evaluated without execution.

## Phase 6 — Central Risk

- trade risk
- position risk
- portfolio risk
- execution risk
- limits
- stale-data protection
- kill switches
- confirmation policies

**Gate:** live order intent cannot bypass centralized risk.

## Phase 7 — Broker Execution

- order lifecycle
- broker events
- partial fills
- broker state synchronization
- exceptional reconciliation
- execution audit
- second broker contract validation

**Gate:** broker truth is correctly represented end-to-end.

## Phase 8 — Production SaaS

- admin control plane
- strict tenancy hardening
- notifications
- observability
- E2E
- full CI/CD
- feature flags
- quotas
- operational runbooks

**Gate:** multi-user production readiness.

## Phase 9 — Backtesting & ML

- point-in-time backtesting
- walk-forward validation
- feature pipeline
- model registry
- offline training
- inference

**Gate:** reproducible, leakage-resistant predictive intelligence.

## Phase 10 — AI Copilot

- context service
- evidence-linked responses
- simulation tools
- capability permissions
- model governance

**Gate:** AI can safely consume and explain StrikeNova intelligence.

## Phase 11 — Agentic Evolution

- agent planning
- controlled action capabilities
- autonomous monitoring
- adaptive strategy selection
- user-approved execution automation

This is an evolution target, not a prerequisite for the initial production SaaS.

---

# 32. Hard Gates Before Live Trading

Live broker execution must not be enabled until all of the following are true:

- PostgreSQL production cutover verified.
- Persistent sessions verified across process restart.
- Secrets rotated and secured.
- Rate limiting enabled.
- Central risk engine operational.
- Market-data freshness checks operational.
- Broker order lifecycle implemented.
- Broker event handling implemented.
- Partial-fill handling implemented.
- Idempotency tested end-to-end.
- Exceptional reconciliation tested.
- Execution audit trail implemented.
- Kill-switch controls implemented.
- E2E execution tests pass.
- Quantitative golden datasets pass.
- Production observability is active.
- Controlled release process exists.

---

# 33. What Must Not Be Rewritten

Preserve unless a concrete defect is demonstrated:

1. `paper_execution.py` atomic execution model.
2. Existing client-order-id idempotency.
3. Position netting/apply-fill behavior.
4. Broker canonical domain models.
5. BrokerAdapter protocol.
6. GEX formula and documented sign convention.
7. GEX data-quality framework.
8. RAW → MODEL → ANALYTICS data pattern.
9. Alembic migration discipline.
10. Existing documentation/decision-record convention.

Refactoring should improve boundaries without discarding validated behavior.

---

# 34. Architectural Success Criteria

The architecture is successful when:

1. A broker can be replaced without rewriting trading logic.
2. Market data can come from broker or StrikeNova sources without changing intelligence engines.
3. Every important intelligence result can explain its evidence and data quality.
4. Backend and historical systems can reproduce quantitative calculations independently of a browser.
5. Paper and live trading share the same domain semantics.
6. No live order can bypass risk controls.
7. Broker-confirmed execution remains authoritative.
8. Intelligence can be backtested without lookahead.
9. AI can reason over structured, evidence-linked context.
10. A second broker adapter validates the broker abstraction.
11. PostgreSQL supports multi-process production operation.
12. Operational failures are observable and recoverable.
13. New intelligence engines can be added without rewriting the platform core.
14. Future ML/agentic capabilities can be introduced without replacing deterministic foundations.

---

# 35. Final Architectural Position

StrikeNova should not be rebuilt as a collection of disconnected trading tools.

It should evolve as one coherent system:

```text
MARKET DATA
    ↓
DATA QUALITY + PROVENANCE
    ↓
QUANTITATIVE CORE
    ↓
MARKET INTELLIGENCE
    ↓
INTELLIGENCE SYNTHESIS
    ↓
OPPORTUNITY DISCOVERY
    ↓
STRATEGY INTELLIGENCE
    ↓
RISK ENGINE
    ↓
EXECUTION ENGINE
    ↓
BROKER
    ↓
ACTUAL EXECUTION TRUTH
    ↓
PORTFOLIO INTELLIGENCE
    ↓
AI / ML CONTEXT
```

The existing repository already provides several strong pieces of this architecture. The implementation strategy is therefore **incremental evolution with strict boundaries**, not a rewrite.

The central product thesis is:

> **StrikeNova's moat is not order placement. Its moat is the quality, explainability, persistence and continuous improvement of its market intelligence and opportunity-discovery system.**

Live execution is a downstream capability that must be protected by that intelligence and by a centralized risk system.

---

# 36. Approval Gate

This specification is ready for human architectural review.

**No implementation plan or source-code changes should begin until this Blueprint is explicitly approved.**

After approval, the next artifact should be an implementation plan derived from this specification, beginning with Phase 0/Phase 1 infrastructure hardening and preserving the validated paper/GEX/broker foundations.
