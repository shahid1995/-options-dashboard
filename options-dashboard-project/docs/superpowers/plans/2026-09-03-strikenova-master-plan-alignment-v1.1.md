# StrikeNova Master Plan v1.1 — Blueprint Alignment Addendum

**Date:** 2026-09-03  
**Status:** ACTIVE ALIGNMENT CONTROL  
**Applies to:** `docs/superpowers/plans/2026-09-02-strikenova-architecture-blueprint-v1-master-implementation-plan.md`  
**Architecture authority:** `docs/superpowers/specs/2026-09-02-strikenova-architecture-blueprint-v1-design.md`  
**Traceability authority:** `docs/superpowers/traceability/STRIKENOVA_BLUEPRINT_TRACEABILITY_MATRIX.md`  
**Branch:** `feat/strikenova-day1-security`

> This addendum is a binding alignment layer for the existing Master Implementation Plan. It closes the traceability gaps identified by the Blueprint audit without rewriting or weakening the original 60-day dependency sequence.

## 1. Alignment rule

The Blueprint remains the architectural authority. The Master Plan remains the sequencing authority. This addendum makes previously implicit Blueprint requirements explicit in the Master Plan.

No item below authorizes implementation outside the normal day gate, TDD, security review, or human approval controls.

**Day 7 remains LOCKED.** This document does not authorize Day 7 or any later implementation day.

## 2. Corrected traceability map

| Blueprint requirement | Master Plan placement | Required interpretation |
|---|---|---|
| Flow/Divergence Intelligence | Day 20–26, primarily Day 20 and Day 26 | Treat CE/PE flow, Delta divergence, Vega divergence and related flow measurements as a first-class deterministic intelligence capability, not merely an input to other engines. |
| Second broker validation | Day 40–42 | Add an explicit adapter-contract validation milestone before Execution Gate. The second broker is a validation target for the abstraction; it must not be selected or implemented without an approved broker decision. |
| Central risk kill switch | Day 33–36 semantics; Day 59 operational rehearsal | Risk owns the decision contract and kill-switch semantics; Day 59 proves operational/admin controls. |
| Risk confirmation policies | Day 33–36 | Model confirmation requirements as explicit risk policy/configuration, including when user confirmation is mandatory. |
| API rate limiting | Day 43 and Day 46 | Rate limiting is part of the versioned API security boundary and must be observable. |
| API pagination | Day 43 | List endpoints must use stable, documented pagination semantics rather than unbounded result sets. |
| CSP/security headers | Day 43 and Day 59 | Define and verify production browser security headers, including CSP appropriate to the deployed frontend/API architecture. |
| CSRF where applicable | Day 43 | Explicitly assess every cookie/session-authenticated mutation path and apply CSRF protection where applicable. |
| Credential lifecycle | Day 45 and Day 59 | Include credential creation/rotation/expiration/revocation/access-audit semantics in the admin and operational control plane. Secrets remain encrypted and never exposed to frontend/logs. |
| Immutable audit semantics | Day 38, Day 42, Day 45–46 | Execution and administrative audit records must be append-only/tamper-evident according to the selected implementation, with privileged access itself auditable. |
| PostgreSQL RLS decision | Day 4–8, with final decision recorded before SaaS gate | Explicitly evaluate PostgreSQL Row-Level Security versus application-layer tenant isolation. Record adopt / not-needed / deferred with rationale; do not silently assume either. |
| Strategy/portfolio performance attribution | Day 31 and Day 35 | Add attribution dimensions needed to explain strategy and portfolio performance, while keeping broker truth authoritative. |
| Phase-1 deferred controls | Day 59 | Backup/restore, release rehearsal, emergency controls and other later operational controls must be explicitly labeled deferred rather than omitted from the architecture. |
| Agentic Evolution | Post-Day-60 evolution track | Preserve as an approved future evolution target; it is not a prerequisite for the first 60-day production SaaS sequence. |

## 3. Day-level corrections

### Day 20 — Positioning and Flow/Divergence Intelligence

Add the following explicit scope to the existing Day 20 positioning objective:

- Treat flow intelligence as a first-class deterministic capability covering CE/PE net flow and relevant directional flow measures.
- Add Delta divergence and Vega divergence measurements where required by the approved intelligence contract.
- Separate raw broker observations, normalized flow measurements, model-derived divergence, interpretation, confidence and data quality.
- Preserve evidence references so a later synthesis result can show which flow/divergence observations support or conflict with the conclusion.

**Gate addition:** Flow/divergence outputs are deterministic, evidence-linked and quality-aware and can be consumed independently by synthesis, opportunity and strategy layers.

### Day 26 — Intelligence synthesis

Add explicit handling for flow/divergence evidence:

- Flow and divergence signals participate in evidence-weighted conflict resolution.
- Conflict between price, positioning, GEX, flow, Delta and Vega must remain visible.
- No divergence metric is allowed to become an opaque standalone probability.

### Day 31 — Strategy evaluation

Add performance attribution requirements:

- Attribute strategy outcomes to strategy template, strike selection, entry/exit behavior, regime, volatility, positioning and material risk drivers where data permits.
- Preserve evidence/version metadata so attribution is reproducible.

### Day 33 — Central risk engine

Add:

- Define kill-switch semantics as a central risk control that can block new execution intents and, where explicitly authorized by the execution design, invoke emergency controls.
- Define confirmation policies as explicit risk policy/configuration, including mandatory user confirmation boundaries.
- Define precedence between kill switch, hard risk block, confirmation requirement, user decision and broker capability checks.

### Day 35 — Portfolio intelligence

Add:

- Define portfolio performance attribution and exposure attribution contracts.
- Ensure attribution uses broker-confirmed positions/fills where applicable and shared quant calculations for derived exposures.

### Day 38 / Day 42 — Auditability

Add:

- Define append-only/tamper-evident audit semantics for order lifecycle and execution transitions.
- Verify audit records include tenant context, actor/source, event ID, timestamp, version and relevant correlation/idempotency identifiers.

### Day 40–42 — Second broker validation

Add an explicit execution-boundary validation task:

- Validate the canonical BrokerAdapter contract against a second broker implementation or contract-compatible test adapter before declaring the execution abstraction proven.
- The second broker must exercise authentication/session, market-data separation where relevant, order mapping, status/error normalization and lifecycle differences.
- Do not assume Upstox compatibility proves broker replaceability.

**Gate addition:** Second-broker validation either passes or produces a documented architectural exception approved before the Execution Gate is closed.

### Day 43 — Production API security boundary

Add:

- Rate limiting by appropriate identity/resource dimensions.
- Stable pagination for list APIs.
- CSP and production security headers.
- CSRF analysis and protection where cookie/session authentication makes it applicable.
- Authorization and tenant checks before pagination/filtering can expose cross-tenant data.
- Security telemetry for rate-limit violations and rejected authorization/security requests.

### Day 45 — Admin control plane

Add credential lifecycle controls:

- credential creation/connection state
- rotation
- expiration/revocation
- last-used/access metadata where appropriate
- administrative access audit
- safe failure when credentials expire or are revoked

Admin must never be able to read plaintext broker secrets through normal UI/API responses.

### Day 46 — SaaS gate

Add verification for:

- rate limiting
- security headers/CSP
- CSRF where applicable
- tenant isolation under paginated/list endpoints
- credential lifecycle/audit behavior
- immutable/tamper-evident audit semantics

### Day 59 — Operational rehearsal

Explicitly verify the controls that were intentionally deferred from earlier phases:

- backup/restore rehearsal
- release rollback
- deployment-managed secrets and rotation readiness
- admin emergency controls
- execution kill switch
- operational observability and alerting

These are not omissions from the Blueprint; they are deliberately sequenced here.

## 4. PostgreSQL tenant-isolation decision record

Before the Infrastructure/SaaS boundary is declared fully aligned, the implementation sequence must produce an explicit decision record covering PostgreSQL RLS:

1. threat model and tenant-isolation requirements;
2. application-layer isolation already present;
3. whether RLS materially reduces residual risk;
4. operational/testing complexity;
5. connection/session context requirements;
6. decision: **ADOPT**, **NOT NEEDED**, or **DEFER WITH EXPLICIT ACCEPTANCE**.

No silent assumption is permitted.

## 5. Agentic evolution track

The Blueprint's Agentic Evolution remains intentionally outside the first 60-day implementation sequence.

After Day 60, the roadmap may add an **Agentic Evolution Track** covering:

- agent planning/orchestration;
- controlled action capabilities;
- autonomous monitoring;
- adaptive strategy selection;
- user-approved execution automation;
- stronger model governance and capability policy.

This is a deferred evolution target, not a missing Day 56–60 deliverable.

## 6. Updated hard-gate interpretation

The existing Hard Gates Before Live Trading remain unchanged and are strengthened by these explicit requirements:

- Security Gate includes API security controls and credential lifecycle evidence as applicable.
- Infrastructure Gate includes the documented PostgreSQL tenant-isolation/RLS decision.
- Intelligence Gate includes first-class flow/divergence evidence.
- Risk Gate includes kill-switch and confirmation-policy semantics.
- Execution Gate includes second-broker contract validation and immutable/tamper-evident audit evidence.
- Production SaaS Gate includes rate limiting, pagination, CSP/security headers, CSRF assessment, credential lifecycle and tenant-safe administrative controls.
- Final Release Gate verifies all of the above with fresh evidence.

## 7. Scope and sequencing protection

- This addendum does not change the modular-monolith architecture.
- This addendum does not authorize microservice decomposition.
- This addendum does not authorize production deployment, PostgreSQL cutover, or live trading.
- This addendum does not authorize Day 7.
- No requirement may be removed from the Blueprint merely because it is absent from an existing day's checklist.
- If implementation evidence demonstrates that the Blueprint itself must change, stop at the affected gate and use formal architecture change control.

## 8. Alignment completion criterion

The Master Plan and Blueprint are considered traceable when every Blueprint requirement is in one of these states:

- **MAPPED** — explicit day/task/gate exists;
- **PARTIAL** — explicit follow-up task and closure criterion exists;
- **DEFERRED** — intentionally scheduled outside the 60-day sequence with rationale;
- **MISSING** — prohibited at gate review.

The target state before Day 7 is: **no P0/MISSING traceability item**.

## 9. Current project state

- Day 4: PASS
- Day 5: PASS
- Day 6: PASS
- Day 7: **LOCKED**
- Blueprint traceability matrix: created and committed
- This alignment addendum: created and committed
- Production deployment/cutover: not performed
- Live trading: disabled/not authorized by this document
