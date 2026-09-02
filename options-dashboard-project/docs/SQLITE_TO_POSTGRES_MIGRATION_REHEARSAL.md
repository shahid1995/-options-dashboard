# SQLite → PostgreSQL Migration Rehearsal Report

**Date:** August 31, 2026
**Railway Project:** efficient-curiosity
**Production Environment:** 23d61e12-442a-4a46-8932-486a6da7abb9
**Backend Service:** -options-dashboard (7e6badf4-0f65-4a4c-a731-25b464b9923a)
**PostgreSQL Service:** Postgres (17c4d5b5-6abd-46a1-a485-7c168cbc73ee)

---

## Executive Summary

The SQLite → PostgreSQL migration rehearsal was completed successfully. All 27 application tables were created in PostgreSQL via Alembic. The production SQLite data (1 user, 4 sessions) was migrated and verified with row-count matching, fingerprint comparison, and primary-key uniqueness checks. Production was NOT modified, deployed, or restarted.

---

## Backup

| Property | Value |
|----------|-------|
| Source | `/app/paper_journal.db` (production container) |
| Method | `sqlite3.Connection.backup()` (transaction-consistent) |
| Integrity | ok |
| Size | 487,424 bytes |
| SHA-256 | `de83a7785e78a54303bce6e4b88a03405bfb0955370e325f84fa484d828efa71` |
| Tables | 27 |
| Non-empty | 3 (users: 1, user_sessions: 4, alembic_version: 1) |
| Local path | `backend/paper_journal_production_fresh.db` |

---

## PostgreSQL Schema

| Property | Value |
|----------|-------|
| Alembic head | `b2c3d4e5f6a7` |
| Tables created | 27 |
| Sequences | 24 |
| Migrations applied | All 7 historical migrations |

---

## Migration Results

| Table | Source | Target | Status |
|-------|--------|--------|--------|
| users | 1 | 1 | OK |
| user_sessions | 4 | 4 | OK |
| broker_connections | 0 | 0 | empty |
| broker_tokens | 0 | 0 | empty |
| paper_accounts | 0 | 0 | empty |
| strategy_templates | 0 | 0 | empty |
| strategy_template_legs | 0 | 0 | empty |
| trades | 0 | 0 | empty |
| legs | 0 | 0 | empty |
| strategy_executions | 0 | 0 | empty |
| paper_orders | 0 | 0 | empty |
| positions | 0 | 0 | empty |
| paper_transactions | 0 | 0 | empty |
| strategy_leg_exposures | 0 | 0 | empty |
| exit_exposure_allocations | 0 | 0 | empty |
| bulk_exit_records | 0 | 0 | empty |
| gex_snapshots | 0 | 0 | empty |
| historical_gex | 0 | 0 | empty |
| contract_specs | 0 | 0 | empty |
| nifty_candles | 0 | 0 | empty |
| option_candles | 0 | 0 | empty |
| option_greeks | 0 | 0 | empty |
| data_completeness | 0 | 0 | empty |
| ingestion_checkpoint | 0 | 0 | empty |
| ingestion_log | 0 | 0 | empty |
| iv_observations | 0 | 0 | empty |
| alembic_version | 1 | 1 | OK (pre-populated by Alembic) |

---

## Validation Results

| Check | Result |
|-------|--------|
| Row count comparison | ALL MATCH |
| Fingerprint comparison | ALL MATCH |
| Primary key uniqueness | ALL UNIQUE |
| Alembic version | MATCH (b2c3d4e5f6a7) |
| Sequence correctness | ALL OK |

---

## Security Invariants Verified

| Invariant | Status |
|-----------|--------|
| Platform Identity ≠ Broker Token | VERIFIED (1 user, 0 broker connections) |
| No plaintext broker credentials | VERIFIED (all columns encrypted type) |
| GEX provenance columns present | VERIFIED (owner_id, connection_id, data_source) |
| User data integrity | VERIFIED (1 Google user, timestamps preserved) |
| Session integrity | VERIFIED (4 active sessions, all belong to same user) |
| Capability columns present | VERIFIED (data_status, trading_status, is_default) |

---

## Production Isolation

| Check | Status |
|-------|--------|
| Production DATABASE_URL changed | NO |
| Production backend redeployed | NO |
| Production backend restarted | NO |
| Production SQLite modified | NO |
| Production traffic switched | NO |
| Production health | OK |
| Production still on SQLite | YES |
| PostgreSQL populated | YES (rehearsal data) |

---

## Artifacts

| Artifact | Path |
|----------|------|
| SQLite backup | `backend/paper_journal_production_fresh.db` |
| Migration script | `tools/migrate_sqlite_to_pg.py` |
| This report | `docs/SQLITE_TO_POSTGRES_MIGRATION_REHEARSAL.md` |
| Backup SHA-256 | `de83a7785e78a54303bce6e4b88a03405bfb0955370e325f84fa484d828efa71` |

---

## Remaining Risks

1. **SQLite backup is from Aug 31 04:30 UTC** — any production changes since then are not captured.
2. **Market data tables are empty** — the production instance had been recently reset. A rehearsal with a data-heavy backup should be done when market data is available.
3. **PostgreSQL is not yet wired to production** — the `DATABASE_URL` must not be changed until the full migration plan is approved.
4. **Sequences for empty tables have `last_value=None`** — this is normal for PostgreSQL sequences that haven't been used yet.

---

## Next Steps

1. Approve this rehearsal as successful.
2. Plan a production cutover window with data sync.
3. Decide whether to keep the SQLite backup as rollback evidence.
4. When ready: set `DATABASE_URL` on Railway to the PostgreSQL connection string.
5. Run Alembic migrations on the new PostgreSQL database.
6. Migrate remaining data (if any production data accumulated since the backup).
7. Verify production health after cutover.

---

*This is a rehearsal only. No production changes were made.*
