# StrikeNova — Data

**Status:** Canonical · **Owner:** Founder · **Last reviewed:** 2026-09-18

---

## 1. Schema authority

**Alembic is the sole schema authority** ([`DECISIONS.md`](DECISIONS.md)
ADR-002). All DDL flows through `backend/alembic/versions/`. Application code
and tests never issue ad-hoc DDL; existing migrations are never edited to
satisfy tests. SQLAlchemy models (`backend/app/models.py`) mirror the migrated
schema.

## 2. Environments

| Environment | Database | Driver | Notes |
|---|---|---|---|
| Local development | SQLite (`sqlite://` / file) | built-in | Default when `DATABASE_URL` unset; zero external services |
| CI | PostgreSQL 16 (service container) | `postgresql+psycopg` | `PostgreSQL compatibility` workflow gate |
| Production | **CockroachDB Cloud** | `cockroachdb+psycopg` (+ `sqlalchemy-cockroachdb`) | Runtime-validated; Alembic migrations apply cleanly |

Portability is an invariant ([`INVARIANTS.md`](INVARIANTS.md) §6): engine
construction is `DATABASE_URL`-driven (`backend/app/db.py`), and no
production code path may depend on a single vendor dialect where portability
exists today. Railway-era PostgreSQL assumptions in historical documents are
superseded — production is CockroachDB.

## 3. Data domains

| Domain | Models | Notes |
|---|---|---|
| Identity | `User`, `UserSession` (`app/identity.py`) | Sessions hashed (`hash_session_id`), durable, revocable, TTL'd |
| Broker BYOB | `BrokerConnection`, `BrokerAuthorization`, `BrokerToken` | Encrypted credentials; connection-ownership resolution path |
| Paper trading | positions, executions, journal, templates (`app/models.py`) | Server-authoritative balances and P&L |
| Market data | option chains, candles, Greeks, GEX snapshots/history | Tier-1 backfill + live ingestion (Phases 7.x) |
| Broker sync | `app/broker_sync/` | Ingestion pipeline models |
| Templates | `StrategyTemplate` (+legs) | User-owned reusable strategy blueprints |

## 4. Conventions

- **Timestamps:** UTC storage, IST market context — standardized per
  `docs/PHASE_7_24_4_TIMEZONE_STANDARDIZATION.md`; no naive `datetime.now()`
  in production paths.
- **GEX conventions:** sign, flip/wall, and aggregation definitions are owned
  by `docs/GEX_V1_0_SPEC.md`.
- **Secrets at rest:** broker tokens Fernet-encrypted (`app/crypto.py`);
  session identifiers hashed; never logged in full.
- **Alembic contract tests** guard migration behavior in CI
  (`test_day5_alembic_authority.py`, postgres/migration suites — see
  [`TESTING.md`](TESTING.md)).

## 5. Historical data architecture

The Phase 7.x record (persistence foundation, backfill orchestrators, Greeks
reconstruction, coverage audits) lives in `options-dashboard-project/docs/` —
evidence of completed work, not open tasks.
