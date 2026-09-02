# PostgreSQL Compatibility Implementation Plan

## Goal

Prepare the StrikeNova backend for Railway PostgreSQL without switching production off SQLite, migrating production data, or changing broker/authentication behavior.

## Current verified architecture

- Production Railway backend uses file-backed SQLite because `DATABASE_URL` is unset.
- Railway production has no persistent volume on the backend service.
- A separate Railway PostgreSQL service now exists with persistent storage.
- The application uses SQLAlchemy + Alembic and already resolves `DATABASE_URL` when present.
- PostgreSQL driver support is not currently present in `requirements.txt`.
- Historical migrations include SQLite/PostgreSQL-sensitive details such as partial unique index boolean predicates.

## Stage 1 — PostgreSQL compatibility

1. Add the PostgreSQL SQLAlchemy driver using the project's existing dependency-management conventions.
2. Audit `app/db.py` so SQLite-only PRAGMAs/listeners are never registered on PostgreSQL engines and the engine configuration remains correct for both dialects.
3. Audit `alembic/env.py` for dialect-safe online/offline migration behavior and avoid SQLite-specific assumptions for PostgreSQL.
4. Audit the full Alembic chain for PostgreSQL compatibility, including partial unique indexes, batch operations, defaults, foreign keys, text/JSON fields, and corrective/provenance migrations.
5. Search production Python and migration code for SQLite-only SQL constructs and isolate or replace them where they affect PostgreSQL execution.
6. Add a PostgreSQL compatibility test harness driven by `TEST_DATABASE_URL`, while retaining isolated SQLite tests as the fast/default suite.
7. Add migration smoke tests that create a clean PostgreSQL schema and run `alembic upgrade head` from the repository baseline.
8. Add schema/integrity assertions covering identity, sessions, broker connections/tokens, GEX snapshots/provenance, paper trading, and key indexes/constraints.
9. Add timestamp compatibility assertions to ensure UTC-aware application timestamps still serialize correctly after PostgreSQL round-trips.
10. Verify rollback/downgrade behavior for newly added migrations where supported; do not alter historical migrations.

## Stage 2 — Verification

- Run SQLite regression suite.
- Run PostgreSQL compatibility suite when `TEST_DATABASE_URL` is supplied.
- Run auth/security suites and verify Google OAuth invariants are unchanged.
- Run frontend tests/build.
- Run `git diff --check` and inspect semantic diff for unrelated changes.

## Stage 3 — Production migration (deferred)

No production switchover is part of this plan. After compatibility is proven, a separate migration phase will:

- export/backup current SQLite data;
- provision/validate PostgreSQL schema;
- migrate data with row-count/integrity reconciliation;
- connect the backend using `${{Postgres.DATABASE_URL}}`;
- verify production endpoints and data;
- keep SQLite as rollback backup until PostgreSQL is proven stable.

## Stage 4 — Analytics Token UX (deferred)

Only after PostgreSQL migration is complete should the next application phase implement Upstox Analytics Token onboarding using the already-hardened user/connection/capability model.

## Constraints

- No production `DATABASE_URL` change in Stage 1.
- No production database migration in Stage 1.
- No production deployment in Stage 1.
- No Google OAuth redesign.
- No trading capability activation.
- No new broker adapter.
- No modification of historical Alembic migrations.
