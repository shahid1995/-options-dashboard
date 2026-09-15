# StrikeNova Blueprint → Master Implementation Plan Traceability Matrix

**Date:** 2026-09-03  
**Blueprint:** `docs/superpowers/specs/2026-09-02-strikenova-architecture-blueprint-v1-design.md`  
**Master Plan:** `docs/superpowers/plans/2026-09-02-strikenova-architecture-blueprint-v1-master-implementation-plan.md`  
**Branch:** `feat/strikenova-day1-security`

## Purpose

This document is the explicit bridge between the StrikeNova Architecture Blueprint and the Master Implementation Plan.

The Blueprint is the **architectural authority**: it defines what StrikeNova must become, the boundaries it must preserve, and the architectural constraints that must not be silently changed.

The Master Implementation Plan is the **execution/sequencing authority**: it decomposes the Blueprint into dependency-ordered implementation phases and days.

This matrix prevents a Blueprint requirement from disappearing when the architecture is decomposed into implementation tasks.

## Traceability rule

Every material Blueprint requirement must map to one of:

- `MAPPED` — explicitly represented in the Master Plan.
- `PARTIAL` — represented, but one or more material details need an explicit task or stronger verification.
- `MISSING` — not currently represented and requires plan correction.
- `DEFERRED` — intentionally outside the current sequence; target phase/release must be recorded.

A requirement must not be silently removed, redefined, or weakened by the implementation plan. If implementation evidence requires an architectural change, the Blueprint must be updated through an explicit architecture decision.

---

## 1. Architectural principles

| Blueprint area | Requirement | Master Plan mapping | Status |
|---|---|---|---|
| §3.1 | Broker truth vs StrikeNova intelligence | Global constraints; Days 9–18; 33–42 | MAPPED |
| §3.2 | Opportunity is not an order | Global constraints; Days 28–32 | MAPPED |
| §3.3 | Deterministic foundation before ML | Global constraints; Days 19–27; 49–55 | MAPPED |
| §3.4 | Evidence before conclusion | Days 19, 26–27, 53 | MAPPED |
| §3.5 | Data quality is part of intelligence | Days 12, 19, 27, 29 | MAPPED |
| §3.6 | Modular monolith first | Architecture + explicit non-goal | MAPPED |
| §3.7 | Paper/live share domain semantics | Days 34, 41–42 | MAPPED |

## 2. Domain boundaries

| Blueprint domain | Master Plan mapping | Status |
|---|---|---|
| Identity & Access | Days 1–3, 7, 43–46 | MAPPED |
| Broker | Days 9–11, 40–42 | PARTIAL — second-adapter validation needs explicit placement |
| Market Data | Days 9–13 | MAPPED |
| Quantitative | Days 14–18 | MAPPED |
| Intelligence | Days 19–27 | MAPPED |
| Opportunity | Days 28–29 | MAPPED |
| Strategy | Days 30–32 | MAPPED |
| Risk | Days 33–36 | PARTIAL — kill-switch/confirmation semantics need stronger explicit mapping |
| Execution | Days 37–42 | MAPPED |
| Portfolio | Day 35 | MAPPED |
| Historical Data | Days 45, 47–50 | MAPPED |
| AI/ML | Days 47–55 | MAPPED |

## 3. Database architecture

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| PostgreSQL transactional system of record | Phase 1 / Days 4–8 | MAPPED |
| PostgreSQL not unlimited raw-market-data warehouse | Global constraints; historical storage days 47–48 | MAPPED |
| HOT/WARM/COLD storage model | Historical governance / retention | PARTIAL — storage-tier implementation needs explicit task if not already represented by existing architecture |
| Alembic sole schema authority | Day 5 | MAPPED |
| Expand → Migrate → Contract | Global constraints | MAPPED |
| SQLite only as local/test convenience | Global constraints | MAPPED |
| Backup/restore verification | Day 59 | PARTIAL — intentionally later than Blueprint Phase 1; should be explicitly marked as deferred infrastructure verification |

## 4. Market data

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Hybrid broker + StrikeNova data model | Days 9–13 | MAPPED |
| Canonical normalized observation | Day 9 | MAPPED |
| Source/data mode semantics | Day 11 | MAPPED |
| Market/received timestamps | Days 9, 11 | MAPPED |
| Sequence continuity | Day 13 | MAPPED |
| Freshness | Days 9, 11–13 | MAPPED |
| Provenance | Day 11 | MAPPED |
| Broker payload preservation for diagnostics | Day 9 | MAPPED |
| Reconnect/resubscribe/backoff | Day 13 | MAPPED |
| Delayed data cannot be labelled real-time | Day 11 | MAPPED |
| Entitlement/licensing validity | Blueprint §8; historical governance Day 48 | PARTIAL — real-time market-data entitlement enforcement needs explicit verification |

## 5. Data quality & provenance

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Freshness | Day 12 | MAPPED |
| Completeness | Day 12 | MAPPED |
| Validity | Day 12 | MAPPED |
| Consistency | Day 12 | MAPPED |
| Continuity | Day 12–13 | MAPPED |
| Anomaly state | Day 12 | MAPPED |
| Source reliability | Day 12 | MAPPED |
| Entitlement/provenance validity | Day 12; Day 48 | PARTIAL |
| Quality score 0–100 | Day 12 | MAPPED |
| EXCELLENT/GOOD/DEGRADED/INSUFFICIENT | Day 12 | MAPPED |
| Structured quality issues | Day 12 | MAPPED |
| Transformation/calculation version | Days 19, 51 | MAPPED |

## 6. Quantitative engine

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Backend/shared quantitative boundary | Day 14 | MAPPED |
| Greeks | Day 15 | MAPPED |
| IV | Day 16 | MAPPED |
| Pricing | Day 16 | MAPPED |
| GEX | Day 17 | MAPPED |
| Gamma flip | Day 17 | MAPPED |
| Gamma walls | Day 17 | MAPPED |
| Scenarios | Day 18 | MAPPED |
| Portfolio sensitivities | Day 18 | MAPPED |
| Broker vs model values remain separate | Days 14–17 | MAPPED |
| GEX formula/sign convention preserved | Day 17 | MAPPED |
| Golden quantitative fixtures | Days 14–18 | MAPPED |

## 7. Intelligence engines

| Blueprint capability | Master Plan mapping | Status |
|---|---|---|
| Common intelligence contract | Day 19 | MAPPED |
| Positioning Intelligence | Day 20 | MAPPED |
| Dynamic Level Engine | Day 21 | MAPPED |
| Institutional-Like Activity | Day 22 | MAPPED |
| Market Regime | Day 23 | MAPPED |
| Event Detection | Day 24 | MAPPED |
| Expiry Intelligence | Day 24 | MAPPED |
| Trap Detection | Day 25 | MAPPED |
| Intelligence Synthesis | Day 26 | MAPPED |
| Conflict Resolution | Day 26 | MAPPED |
| Flow/Divergence Intelligence | Days 20–26 only as inputs/implicit behavior | PARTIAL — explicit flow/divergence contract/task should be added |
| Evidence references | Days 19, 26–27 | MAPPED |
| Signal strength separate from confidence | Days 19, 26 | MAPPED |
| Confidence separate from data quality | Days 19, 26 | MAPPED |

## 8. Opportunity & strategy

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Observation → Signal → Setup → Opportunity | Day 28 | MAPPED |
| Opportunity does not submit order | Day 28 | MAPPED |
| Scalping Opportunity Engine | Day 29 | MAPPED |
| Strict freshness for scalping | Day 29 | MAPPED |
| Strike Ranking Engine | Day 30 | MAPPED |
| Strategy Evaluation Engine | Day 31 | MAPPED |
| Strategy Candidate boundary | Day 32 | MAPPED |
| User Decision before execution | Day 32 | MAPPED |
| Discover → Generate → Evaluate → Simulate → Risk → User Decision → Execute | Days 28–32 + 33 | MAPPED |
| Strategy performance attribution | Day 31 mentions historical behavior; explicit attribution is not stated | PARTIAL |

## 9. Risk

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Central Risk Engine | Day 33 | MAPPED |
| Trade risk | Day 33 | MAPPED |
| Position risk | Day 33 | MAPPED |
| Portfolio risk | Days 33, 35 | MAPPED |
| Execution risk | Day 33 | MAPPED |
| Risk decisions: allow/warn/block semantics | Day 33 | MAPPED |
| Stale-data protection | Day 36; Day 41 | MAPPED |
| Duplicate-order protection | Day 41 | MAPPED |
| Quantity/tick-size validation | Day 41 | MAPPED |
| Market status/broker capability checks | Day 41 | MAPPED |
| Kill switch | Day 59 | PARTIAL — should be explicitly linked to Risk/Execution gate |
| Confirmation policies | Phase 6 roadmap mentions confirmation policies but no dedicated task | PARTIAL |
| Risk cannot rewrite broker truth | Global constraints; Day 33 | MAPPED |

## 10. Execution & broker protocol

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Canonical broker protocol | Days 9–11, 40 | MAPPED |
| Upstox first implementation | Days 10, 40 | MAPPED |
| Place/modify/cancel | Day 40 | MAPPED |
| Orders/fills/positions/holdings retrieval | Day 40 | MAPPED |
| Broker event handling | Day 39 | MAPPED |
| Partial-fill lifecycle | Days 38–42 | MAPPED |
| Idempotency | Days 38, 41 | MAPPED |
| Broker remains execution truth | Days 40–42 | MAPPED |
| Exceptional reconciliation | Days 39, 42 | MAPPED |
| Second broker validates abstraction | Blueprint §16; not explicit in current day tasks | MISSING |
| Live execution disabled until hard gates | Global constraints; Day 42; final gates | MAPPED |

## 11. Event model

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| In-process domain events first | Day 37 | MAPPED |
| Versioned event envelope | Day 37 | MAPPED |
| Idempotent handlers | Day 37 | MAPPED |
| Trade lifecycle events | Days 38–39 | MAPPED |
| Notification events | Days 46 | MAPPED |
| Future message broker only when justified | Explicit non-goal / modular monolith | MAPPED |

## 12. Portfolio

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Broker/paper state authoritative | Day 35 | MAPPED |
| Greeks/GEX/IV exposure | Day 35 | MAPPED |
| Scenario P/L | Day 35 | MAPPED |
| Concentration/directional/regime risk | Day 35 | MAPPED |
| Performance/strategy attribution | Day 35 + Day 31 | PARTIAL — explicit attribution implementation needs confirmation |

## 13. Historical data / backtesting

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Admin-controlled acquisition | Days 45, 47–48 | MAPPED |
| User broker connections not historical ingestion mechanism | Global constraint | MAPPED |
| Provenance/license/usage metadata | Day 48 | MAPPED |
| Durable jobs | Day 47 | MAPPED |
| Point-in-time datasets | Day 49 | MAPPED |
| No future-data leakage | Day 49 | MAPPED |
| Walk-forward/OOS | Day 50 | MAPPED |
| Dataset/feature/model versioning | Day 50–51 | MAPPED |

## 14. AI / ML

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Feature/dataset/model governance | Day 51 | MAPPED |
| Deterministic before ML | Global constraints; Day 51 | MAPPED |
| Structured AI context | Day 52 | MAPPED |
| Evidence-linked AI | Day 53 | MAPPED |
| Read/analyze/simulate capabilities | Day 54 | MAPPED |
| AI cannot bypass risk/authorization | Day 54–55 | MAPPED |
| Tenant-safe AI context | Day 52, 55 | MAPPED |
| AI is not source of truth | Global constraints; Day 55 | MAPPED |

## 15. Security & tenancy

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Secret removal | Day 1 | MAPPED |
| Secret rotation | Day 1 | MAPPED |
| Secret scanning | Day 1 | MAPPED |
| Tenant isolation | Day 3; Days 43–46 | MAPPED |
| Credential encryption | Day 3 | MAPPED |
| Credential rotation/expiration/access auditing | Day 3 conceptually | PARTIAL |
| Rate limiting | Blueprint §22; not explicit in current day tasks | MISSING |
| CSRF where applicable | Blueprint §22; not explicit | MISSING |
| CSP/security headers | Blueprint §22; not explicit | MISSING |
| Dependency scanning | Day 2 / security baseline | MAPPED |
| Security tests | Days 2–3; gates | MAPPED |
| Immutable audit events | Blueprint §23; audit work distributed | PARTIAL |
| PostgreSQL RLS evaluated where useful | Blueprint §22 | PARTIAL — requires explicit decision/evidence |

## 16. Admin, notifications & observability

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Admin authorization | Day 45 | MAPPED |
| Historical acquisition controls | Day 45 | MAPPED |
| Instrument/configuration/retention controls | Day 45 | MAPPED |
| Feature flags/model metadata/audit | Day 45 | MAPPED |
| Notifications abstraction | Day 46 | MAPPED |
| Structured logging/correlation IDs | Day 46 | MAPPED |
| Health/readiness | Day 46 | MAPPED |
| Market-data freshness telemetry | Day 46 | MAPPED |
| Broker/execution/error telemetry | Day 46 | MAPPED |
| Alerting | Day 46 | MAPPED |

## 17. Frontend & API

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Feature-oriented frontend | Day 44 | MAPPED |
| Backend authoritative decisions | Day 44 | MAPPED |
| Responsive web/PWA primary client | Blueprint + non-goal | MAPPED |
| `/api/v1/...` convention | Day 43 | MAPPED |
| Domain-oriented API | Day 43 | MAPPED |
| Authentication/tenant scoping | Day 43 | MAPPED |
| Idempotency where applicable | Global constraints / execution | PARTIAL — API-wide rule should be explicit |
| Pagination | Blueprint §28; not explicit in day tasks | MISSING |
| Rate limiting | Blueprint §28; not explicit | MISSING |
| Schema validation | Day 43 domain schemas | MAPPED |
| No direct DB-structure exposure | Day 43 intent; not explicit verification | PARTIAL |

## 18. CI/CD & release

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Static/security checks | Days 1–2; Day 59 | MAPPED |
| Backend/frontend tests | Days 56, 59 | MAPPED |
| Quant validation | Days 14–18, 56 | MAPPED |
| PostgreSQL integration | Phase 1 / CI | MAPPED |
| Build/preview/approval/production flow | Day 59 | MAPPED |
| Controlled deployment | Global constraints; Day 59 | MAPPED |
| Smoke/health verification | Days 46, 59 | MAPPED |
| No uncontrolled deployment | Global constraints | MAPPED |

## 19. Testing strategy

| Blueprint requirement | Master Plan mapping | Status |
|---|---|---|
| Unit tests | Every day / Day 56 | MAPPED |
| Integration tests | Daily/gates / Day 56 | MAPPED |
| Broker contract tests | Days 10, 40, 42 | MAPPED |
| Migration tests | Day 5 / Phase 1 | MAPPED |
| Quant golden datasets | Days 14–18, 56 | MAPPED |
| Invariant/property tests | Day 56; quant foundation | MAPPED |
| Security tests | Days 1–3, 8, 56–59 | MAPPED |
| Performance tests | Day 6, Day 58 | MAPPED |
| E2E/browser tests | Days 46, 56 | MAPPED |
| Production smoke | Day 59 | MAPPED |
| Execution failure injection | Days 41–42, 57 | MAPPED |

## 20. Explicit non-goals

| Blueprint non-goal | Master Plan treatment | Status |
|---|---|---|
| Immediate microservice decomposition | Explicit non-goal | MAPPED |
| Unlimited PostgreSQL raw-data warehouse | Explicit constraint | MAPPED |
| Customer brokers as historical ingestion | Explicit global constraint | MAPPED |
| Institution identification claims | Day 22 | MAPPED |
| Opaque AI market score | Global AI constraints | MAPPED |
| ML replacing deterministic foundations prematurely | Global constraints | MAPPED |
| Unrestricted AI live execution | Days 54–55 | MAPPED |
| Continuous polling as normal execution path | Days 39, 42 | MAPPED |
| Premature native mobile | Explicit non-goal | MAPPED |
| Uncontrolled auto-deployment | Global constraints | MAPPED |
| Rewriting validated paper/GEX foundations | Explicit non-goal | MAPPED |

## 21. Blueprint roadmap vs 60-day plan

The Blueprint includes an **Agentic Evolution** target after the initial production architecture. It contains agent planning, controlled action capabilities, autonomous monitoring, adaptive strategy selection and user-approved execution automation.

The current 60-day Master Plan does not contain a corresponding implementation phase. This is acceptable only if it is explicitly recorded as a **post-60-day deferred evolution track**, not treated as a forgotten requirement.

| Blueprint phase | Master Plan phase | Status |
|---|---|---|
| Phase 0 Security Emergency | Phase 0 Days 1–3 | MAPPED |
| Phase 1 Infrastructure | Phase 1 Days 4–8 | PARTIAL — some Blueprint Phase 1 controls are sequenced later |
| Phase 2 Market Data | Phase 2 Days 9–13 | MAPPED |
| Phase 3 Quant | Phase 3 Days 14–18 | MAPPED |
| Phase 4 Intelligence | Phase 4 Days 19–27 | MAPPED |
| Phase 5 Opportunity/Strategy | Phase 5 Days 28–32 | MAPPED |
| Phase 6 Central Risk | Phase 6 Days 33–36 | PARTIAL — some controls are later |
| Phase 7 Broker Execution | Phase 7 Days 37–42 | PARTIAL — second-broker milestone absent |
| Phase 8 Production SaaS | Phase 8 Days 43–46 | MAPPED |
| Phase 9 Backtesting/ML | Phase 9 Days 47–51 | MAPPED |
| Phase 10 AI Copilot | Phase 10 Days 52–55 | MAPPED |
| Phase 11 Agentic Evolution | No 60-day implementation | DEFERRED — post-60-day evolution track |

## 22. Required Master Plan corrections identified by this audit

These are **traceability findings**, not authorization to start Day 7 or implement the features immediately.

### P0 — Must be represented before final architecture traceability is considered closed

1. **Second broker validation milestone** — add an explicit task/gate in Phase 7 or a clearly identified post-60 validation milestone.
2. **Rate limiting** — add explicit security/API tasks and verification.
3. **Security headers/CSP** — add explicit task and verification.
4. **CSRF where applicable** — add explicit task/verification based on the actual auth/session mechanism.
5. **Flow/Divergence Intelligence** — add explicit intelligence contract/task rather than treating flow/divergence only as an input to other engines.
6. **Agentic Evolution** — record explicitly as a post-60-day deferred roadmap item.

### P1 — Should be strengthened

7. **Risk kill switch** — explicitly connect the operational kill switch to the Risk/Execution architecture and final execution gates.
8. **Risk confirmation policies** — define the semantics and implementation location.
9. **API pagination and rate limiting** — make collection and abuse-control requirements explicit.
10. **Immutable audit semantics** — define what makes trading/security audit records immutable and how this is verified.
11. **Credential rotation/expiration/access auditing** — make lifecycle requirements explicit.
12. **PostgreSQL RLS decision** — record an explicit evaluate/adopt/not-needed decision with evidence.
13. **Strategy/portfolio performance attribution** — make attribution a named implementation capability.
14. **Blueprint Phase 1 deferred controls** — label later-sequenced controls such as backup/restore as deliberate deferrals rather than omissions.

## 23. Control rule for future days

Before beginning a future implementation day:

1. Identify the relevant Blueprint sections.
2. Identify the corresponding matrix row(s).
3. Confirm the Master Plan day is the intended implementation location.
4. Confirm required downstream consumers and tests are known.
5. Implement only after the day's gate/authorization is satisfied.
6. Update the matrix when a capability changes status.

**Critical rule:** A green day gate does not override a red/missing Blueprint traceability item. Architecture drift must be resolved explicitly.

---

## Current audit conclusion

The Master Implementation Plan is **substantially derived from the Blueprint**, and the major architecture is represented. The principal weakness was not architectural disagreement; it was insufficient explicit traceability.

The matrix closes that documentation gap and identifies the remaining alignment corrections needed before the Blueprint and Master Plan can be treated as a fully traceable pair.

**Current overall traceability assessment: ~90% mapped, with material gaps explicitly recorded above.**

**Day 7 remains LOCKED.**
