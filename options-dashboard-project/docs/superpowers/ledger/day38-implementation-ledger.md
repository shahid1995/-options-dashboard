# StrikeNova Day 38 — Implementation Ledger

Status: IN PROGRESS
Branch: `feat/strikenova-day35-portfolio-intelligence`
Approved plan: `docs/superpowers/plans/2026-09-06-strikenova-day38-trade-lifecycle-implementation-plan.md`
Design authority: `docs/superpowers/specs/2026-09-05-strikenova-day38-trade-lifecycle-design.md`

## Scope

Implement the Day 38 lifecycle/audit event layer beside the existing authoritative paper-trading state. No live broker execution, production deployment, Railway DB mutation, cutover, or merge.

## Rulings

- Ruling: Preserve `StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, and related paper-engine state as authoritative — the Day 38 design explicitly forbids replacement or competing write paths.
- Ruling: Treat execution replay and position reconstruction as separate projections — execution is scoped by execution identity; position is tenant/instrument-netted.
- Ruling: Use PostgreSQL for concurrency/rollback proof; SQLite may cover deterministic domain behavior only.
- Ruling: Existing paper-execution transition helpers remain authoritative; lifecycle replay must not silently replace them.

## Execution Ledger

- [ ] Task 1 — Persistence model + Alembic expansion
- [ ] Task 2 — Immutable event envelope + canonical identity
- [ ] Task 3 — Execution lifecycle state machine + replay
- [ ] Task 4 — Position lifecycle + sequence semantics
- [ ] Task 5 — Append/idempotency/transaction semantics
- [ ] Task 6 — Integration with authoritative paper execution
- [ ] Task 7 — Regression, PostgreSQL concurrency, migration, scope verification
- [ ] Day 38 gate

## Verification Evidence

To be populated only from fresh command output. Agent reports are not evidence by themselves.
