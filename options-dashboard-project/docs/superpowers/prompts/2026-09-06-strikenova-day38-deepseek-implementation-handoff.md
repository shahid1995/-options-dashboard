# StrikeNova Day 38 — DeepSeek/FreeBuff Implementation Handoff

## Authority

Implement ONLY Day 38 Trade Lifecycle State Machine from the approved implementation plan:
`options-dashboard-project/docs/superpowers/plans/2026-09-06-strikenova-day38-trade-lifecycle-implementation-plan.md`

Design authority:
`options-dashboard-project/docs/superpowers/specs/2026-09-05-strikenova-day38-trade-lifecycle-design.md`

Branch:
`feat/strikenova-day35-portfolio-intelligence`

## Mandatory operating rules

1. Use TDD for every behavior: RED → verify failure → minimal GREEN implementation → focused verification → regression verification.
2. Inspect current repository state before editing. Preserve unrelated work.
3. Do not replace or duplicate the authoritative paper-trading engine.
4. `StrategyExecution`, `PaperOrder`, `Position`, `PaperTransaction`, `StrategyLegExposure`, `ExitExposureAllocation`, and `BulkExitRecord` remain authoritative.
5. Lifecycle events are an append-only audit/reconstruction layer only.
6. Execution replay and position reconstruction are separate concerns.
7. Position identity is `(user_id, symbol, expiry, strike, option_type)`; position is user/instrument-netted, not execution-owned.
8. `position_sequence` is scoped to the full PositionIdentity and allocation must be concurrency-safe.
9. `quantity_delta` and `position_sequence` must be relational columns, not payload-only values.
10. Duplicate `event_id` with identical canonical content is idempotent; different content is rejected.
11. Duplicate aggregate sequence with different canonical content is rejected.
12. Replay rejects sequence gaps, tenant mismatches, invalid transitions, and terminal mutations.
13. Zero crossing is never represented as one PositionUpdated event; decompose close-to-zero then open-remainder.
14. `PositionClosed` must carry the final signed delta that makes lifecycle-instance net quantity exactly zero.
15. Lifecycle persistence failure must fail closed and roll back the surrounding transaction. No `ImportError: pass` degradation.
16. SQLite tests do not prove concurrency. PostgreSQL integration tests must prove allocation, rollback, and concurrent first-event behavior.
17. Do not add broker acceptance/rejection/communication semantics. Those belong to Days 39–42.
18. Do not deploy, modify Railway production DB, merge, cut over, or push to shared production infrastructure.

## Required deliverables

- Lifecycle ORM persistence model(s) following repository conventions.
- Alembic migration using existing revision conventions.
- Immutable lifecycle event envelope and deterministic canonical representation.
- Execution lifecycle state machine and deterministic replay.
- Position lifecycle replay, zero-crossing decomposition, and sequence allocator.
- Append/idempotency/conflict/tenant/transaction semantics.
- Minimal integration with existing paper execution so material lifecycle facts are recorded without duplicating authoritative accounting/netting.
- Deterministic unit tests plus PostgreSQL integration tests.
- Verification report containing exact commands, exit statuses, changed files, test counts, migration verification, and remaining risks.

## Important implementation detail

Before choosing exact table/model names or integration points, inspect `app/models.py`, `app/services/paper_execution.py`, current Alembic head/revision chain, and existing test fixtures. Adapt names to repository conventions while preserving the approved semantics.

## Completion gate

Do not claim Day 38 complete merely because tests pass. The final report must demonstrate:

- deterministic execution replay;
- deterministic position reconstruction;
- invalid transitions rejected;
- sequence gaps rejected;
- duplicate-idempotency/conflict behavior verified;
- tenant isolation verified;
- zero-crossing semantics verified;
- PostgreSQL concurrency and rollback semantics verified;
- lifecycle persistence failure rolls back safely;
- existing paper-engine regression remains green;
- no unrelated files or frontend changes were introduced;
- no production deployment or DB mutation occurred.

If any required verification cannot run, report it as UNVERIFIED rather than assuming success.
