# INVARIANTS

> Non-negotiable system rules for StrikeNova. These rules protect architectural boundaries, correctness, security, compliance posture, and user-visible behavior.
>
> **Authority:** Founder-approved constraints are authoritative. Implementation must conform to these invariants unless an explicit decision changes them.

## 1. How to Use This Document

An invariant is a rule that must remain true across implementations, refactors, and feature additions.

Agents must:

1. Check relevant invariants before changing code.
2. Treat violations as blockers, not as opportunities for silent redesign.
3. Identify the affected invariant in the implementation plan.
4. Add or update tests when a change could weaken an invariant.
5. Escalate conflicts instead of choosing a convenient interpretation.

If a proposed change intentionally breaks an invariant, it requires an explicit architectural decision recorded in `DECISIONS.md`.

---

## 2. Authority and Source of Truth

- **GitHub is the implementation authority.**
- **Obsidian is the knowledge/context authority.**
- **Founder decisions are the final authority.**
- Historical documents and old commits are evidence, not current truth.
- Code does not automatically override an accepted architectural decision.
- Documentation must not describe a deployment, capability, or boundary that is no longer current.

---

## 3. Deployment Topology

The current production topology is:

```
User Browser
    |
    v
Vercel
    |
    v
Render
    |
    v
CockroachDB
```

Invariants:

- The frontend is hosted on Vercel.
- The backend is hosted on Render.
- The production database is CockroachDB.
- Railway must not be treated as the current production hosting platform.
- Local development may use SQLite where the repository configuration permits it.
- Production schema evolution is governed by Alembic migrations; application startup must not substitute ad-hoc schema creation for migration authority.

---

## 4. Identity and User Isolation

- A user identity is distinct from broker credentials and broker connectivity.
- Authentication state must not be used as a substitute for broker authorization.
- User-scoped resources must be authorized server-side.
- A request must never be allowed to access another user's paper-trading or account-scoped data merely because an identifier is known.
- Session lifecycle and logout behavior must invalidate the server-side authorization state expected by the security model.
- OAuth callback handling must validate the expected state/security controls.
- Authentication secrets, tokens, and broker credentials must not be exposed to the browser unnecessarily.

---

## 5. Broker Boundary

- StrikeNova uses a **BYOB (Bring Your Own Broker)** model.
- A customer's broker connection belongs to that customer and must remain isolated from other customers.
- Broker credentials/tokens are security-sensitive and must be protected at rest and in transit.
- Broker integrations must pass through the defined broker abstraction rather than leaking provider-specific assumptions throughout the application.
- Provider-specific behavior belongs in the provider adapter/domain boundary.
- The application must not silently treat broker data as StrikeNova-owned distributable data.
- Customer broker connections must not be used as an implicit shared historical-data collection mechanism.

---

## 6. Paper Trading Authority

- Paper trading is server-authoritative.
- Client-side calculations may support presentation and interaction, but the server remains authoritative for execution state, fills, positions, orders, portfolio state, and related persistence.
- A UI state change is not an execution until the server accepts and records it.
- Position and order transitions must preserve domain consistency.
- Exit operations must not permit partial or duplicate state transitions that violate the execution model.
- Concurrency-sensitive execution paths must use appropriate transactional/locking controls.

---

## 7. Market and Quantitative Correctness

- Quantitative formulas must be explicit, reviewable, and testable.
- The current GEX convention is:

```
raw_gex = gamma × open_interest × spot² × 0.01
```

- GEX open interest is interpreted as contracts under the current model.
- The current GEX calculation does not add a lot-size multiplier.
- A change to the GEX convention requires explicit review and documentation.
- IV normalization must preserve unit correctness; broker percentage values such as 18.24 must not silently be interpreted as decimal 18.24.
- Greeks, pricing, scenario, and projection logic must not silently mix incompatible units, instruments, expiries, or timestamps.
- Quantitative behavior that materially affects user decisions requires automated verification.

---

## 8. Market Data Identity and Provenance

- Market data must retain enough instrument/contract identity to avoid ambiguous interpretation.
- Expiry, strike, option type, underlying, and relevant timestamp/session context must be preserved where required by the data model.
- Derived analytics must be traceable to their input assumptions and source data where practical.
- Missing market data must not be silently converted into fabricated zero values when null/unknown is the correct semantic state.
- Data-quality problems must remain distinguishable from genuine market values.
- Historical data must not be represented as live data merely because it has been persisted.

---

## 9. Historical Data Collection

Historical collection is intentionally controlled because storage, operational complexity, and data ownership matter.

Current defaults include:

- `IV_HISTORY_ENABLED=false`
- `GEX_HISTORY_ENABLED=false`
- `GEX_CAPTURE_ENABLED=false`
- `CANDLE_BACKFILL_ENABLED=false`

Invariants:

- Historical collection must be explicitly enabled rather than silently activated by a feature.
- A feature must not introduce continuous historical storage merely because historical data would be convenient.
- Customer broker connections must not become an implicit historical-ingestion pipeline.
- If historical collection is enabled, retention, provenance, ownership, and operational cost must be understood first.
- Admin-controlled collection may be used where the architecture explicitly permits it.

---

## 10. Database and Migration Integrity

- SQLAlchemy ORM models describe application persistence structures.
- Alembic is the authoritative mechanism for production schema evolution.
- Schema changes require migrations.
- Migrations must be reviewed for forward correctness and compatibility with the supported deployment database.
- Destructive schema changes require explicit review.
- Startup backfills or repair logic must remain idempotent.
- SQLite-specific behavior must not be assumed to work unchanged in CockroachDB production.

---

## 11. API and Backend Boundaries

- Backend authorization must not rely solely on frontend route protection.
- Request validation belongs at the API boundary.
- Business invariants must be enforced in the backend domain/service path, not only in UI controls.
- Provider-specific APIs must not become accidental public contracts.
- Error responses must not disclose secrets, tokens, or unnecessary sensitive implementation details.
- New externally reachable behavior requires corresponding tests and documentation where material.

---

## 12. Frontend Boundaries

- The frontend must respect backend authority for protected state.
- Public routes must not depend on authenticated application state unless explicitly designed to do so.
- Shared UI primitives and canonical design tokens should be reused rather than duplicated.
- Accessibility semantics are part of correctness, not optional decoration.
- Interactive elements must expose appropriate keyboard and semantic behavior.
- Visual changes must not silently alter interaction semantics.
- A refactor must preserve route behavior unless the change explicitly includes a route change.

---

## 13. Testing and Verification

- A change is not complete merely because it compiles or appears correct in a browser.
- Verification must be proportional to the risk and scope of the change.
- Security-sensitive, execution-sensitive, database-sensitive, and quantitative changes require targeted automated tests.
- Regression tests should protect previously verified behavior when the risk justifies them.
- Browser verification is required when behavior depends materially on rendered UI, interaction, routing, or runtime integration.
- Fresh verification evidence must be reported for substantive work.
- Existing test counts are not proof that a new change is correct.

---

## 14. AI Agent Operating Rules

AI coding agents must:

- Read `AI.md`, `AGENTS.md`, `PROJECT-CONTROL.md`, and relevant context documents before substantive work.
- Treat these invariants as constraints, not suggestions.
- Avoid broad refactors when the task has a narrower scope.
- Avoid inventing architecture from stale memory.
- Inspect the repository before assuming a component, endpoint, model, deployment, or dependency exists.
- Preserve unrelated behavior.
- Prefer incremental, test-backed changes.
- Never silently weaken security, data isolation, compliance boundaries, or quantitative conventions.
- Report uncertainty and conflicts instead of guessing.
- Update relevant documentation when a material architectural invariant changes.

---

## 15. Change Control

When a proposed change conflicts with an invariant:

1. Stop before implementing the conflicting behavior.
2. Identify the invariant and the proposed conflict.
3. Explain the concrete architectural or operational consequence.
4. Determine whether the requirement itself has changed.
5. If the requirement has changed, record the new decision in `DECISIONS.md`.
6. Update this document only after the new rule is explicitly accepted.
7. Add or update verification that proves the new invariant.

This prevents an AI agent, refactor, dependency upgrade, or urgent feature request from silently changing the system's governing rules.

---

## 16. Maintenance

Update this document when:

- A non-negotiable architectural rule is added or removed.
- A security boundary changes.
- The production topology changes.
- The broker/data ownership model changes.
- A quantitative convention changes.
- A persistence or migration rule changes.
- A critical testing or verification requirement changes.
- An accepted decision creates a new permanent constraint.

Do not turn this into a general project status document. Current implementation details belong in `CONTEXT.md` and `ARCHITECTURE.md`; rationale belongs in `DECISIONS.md`.
