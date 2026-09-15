# StrikeNova SQLite → PostgreSQL Migration Runbook

## Purpose

This runbook describes how to migrate the StrikeNova backend database from the current Railway SQLite file to the Railway PostgreSQL service without losing data and without making the production cutover automatic.

## Current infrastructure state

- Production backend service: `-options-dashboard`
- Production backend branch: `main`
- Production backend `DATABASE_URL`: **not configured**; backend therefore remains on its file-backed SQLite database.
- PostgreSQL service: `Postgres`
- PostgreSQL persistent mount: `/var/lib/postgresql/data`
- Current Railway Hobby Postgres volume ceiling observed during the Stage 2 audit: **500 MB**.
- PostgreSQL service is healthy and suitable for migration rehearsal.
- PostgreSQL service is private-networked; production application connectivity can use Railway service references after an explicit cutover.

## Non-negotiable safety rules

1. Never migrate directly from the live SQLite file. First create a SQLite online-backup copy.
2. Never delete or overwrite the SQLite source backup before post-cutover validation is complete.
3. Run migration tooling with explicit `--source` and `--target` values.
4. The source for migration should be the verified backup copy, not the live application file.
5. Target schema creation is performed by Alembic, not `Base.metadata.create_all()`.
6. The migration refuses to merge into non-empty target tables.
7. The migration uses foreign-key dependency order and bounded batches.
8. A verification report must show matching row counts and fingerprints before cutover.
9. The PostgreSQL volume must retain a safe margin below its actual storage ceiling.
10. No script in this repository changes Railway variables or switches production database routing automatically.

## Stage A — Backup the SQLite source

On an operator workstation or controlled migration environment where the production SQLite file can be read:

```bash
cd options-dashboard-project/backend
python tools/migrate_sqlite_to_postgres.py backup \
  --source /path/to/live/paper_journal.db \
  --backup /path/to/backups/strikenova-pre-postgres-YYYYMMDD-HHMM.db
```

The backup command uses SQLite's online backup API and runs `PRAGMA integrity_check` against the resulting copy.

Record:
- backup path
- file size
- SHA-256 of the backup file
- backup creation timestamp

Example checksum command:

```bash
sha256sum /path/to/backups/strikenova-pre-postgres-YYYYMMDD-HHMM.db
```

## Stage B — Prepare the PostgreSQL target

Use the existing Railway PostgreSQL service. Obtain its `DATABASE_URL` through the Railway dashboard or service reference in the controlled environment. Do not paste credentials into repository files or commit them.

Apply the current Alembic schema to the target:

```bash
cd options-dashboard-project/backend
DATABASE_URL='postgresql+psycopg://...' alembic upgrade head
```

Then run a read-only preflight against the backup and target:

```bash
python tools/migrate_sqlite_to_postgres.py preflight \
  --source sqlite:////path/to/backups/strikenova-pre-postgres-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  --target-budget-mib 500
```

A successful preflight must report:
- source is a file-backed SQLite database
- target is PostgreSQL
- target is reachable
- every source application table exists on target
- every source column exists on target
- estimated source file size is no more than 80% of the configured target budget

If preflight fails, stop. Do not import data.

## Stage C — Migration rehearsal

The preferred rehearsal target is a fresh PostgreSQL database or a disposable database on the same PostgreSQL service. Do not rehearse by overwriting an environment that already contains unrelated data.

Run:

```bash
python tools/migrate_sqlite_to_postgres.py migrate \
  --source sqlite:////path/to/backups/strikenova-pre-postgres-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  --batch-size 1000 \
  --target-budget-mib 500
```

The command:
1. checks the source size safety gate
2. applies Alembic to the target
3. re-checks target connectivity and schema compatibility
4. refuses to write if target tables already contain rows
5. copies data in foreign-key dependency order
6. copies in 1000-row batches
7. repairs PostgreSQL sequences for sequence-backed integer primary keys
8. verifies counts and fingerprints unless `--skip-verify` is explicitly supplied

Never use `--skip-verify` for the final migration.

## Stage D — Independent verification

Run verification separately after a successful import and archive the JSON report:

```bash
python tools/migrate_sqlite_to_postgres.py verify \
  --source sqlite:////path/to/backups/strikenova-pre-postgres-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  > /path/to/reports/strikenova-postgres-verify-YYYYMMDD-HHMM.json
```

Acceptance criteria:
- top-level `ok` is `true`
- every source application table has the same row count on target
- every table fingerprint matches
- representative identity/broker/GEX records can be loaded from PostgreSQL
- sequence-backed IDs continue from the imported maximum

## Stage E — Backend validation against PostgreSQL

Before production cutover, run the backend in a non-production environment configured with the PostgreSQL `DATABASE_URL`.

Validate at minimum:
- platform login/logout
- Google OAuth/session separation
- broker connection storage and retrieval
- paper trading persistence
- GEX snapshot reads/writes and provenance
- historical data reads
- application startup and Alembic upgrade path
- WebSocket/session authorization

The backend must not accidentally fall back to SQLite while `DATABASE_URL` is configured.

## Stage F — Production cutover

Production cutover is intentionally a separate manual change.

1. Freeze write-producing administrative/data jobs that could modify the SQLite source during the final migration window.
2. Create a final online SQLite backup.
3. Run final preflight against that final backup and the production PostgreSQL target.
4. Run final migration against the final backup.
5. Run final verification and archive the report.
6. Confirm actual PostgreSQL storage use remains comfortably below the Railway volume ceiling.
7. Configure the production backend's `DATABASE_URL` to the Railway PostgreSQL connection string/service reference.
8. Deploy the backend explicitly.
9. Confirm startup completes Alembic without errors.
10. Confirm `/auth/status`, login, GEX, paper-trading, and core dashboard flows against PostgreSQL.
11. Keep the final SQLite backup untouched until post-cutover validation is complete.

## Rollback

Rollback is performed by restoring the backend's database configuration to the prior SQLite path only after confirming the PostgreSQL-backed deployment is stopped or isolated. The preserved SQLite backup is the rollback source; it must not be deleted as part of the cutover.

## Railway capacity warning

The current observed Railway Hobby PostgreSQL volume limit is 500 MB. The migration process therefore defaults to an 80% safety threshold. If the final SQLite backup is larger than roughly 400 MB, or PostgreSQL's actual imported footprint leaves insufficient margin, do not proceed with cutover until the storage plan is increased.

For a larger historical-data footprint, measure actual PostgreSQL storage after rehearsal and size the paid Railway volume before production cutover.

## Commands summary

```bash
# 1) Backup
python tools/migrate_sqlite_to_postgres.py backup \
  --source /path/to/live/paper_journal.db \
  --backup /path/to/backups/strikenova.db

# 2) Preflight
python tools/migrate_sqlite_to_postgres.py preflight \
  --source sqlite:////path/to/backups/strikenova.db \
  --target 'postgresql+psycopg://...'

# 3) Migrate + verify
python tools/migrate_sqlite_to_postgres.py migrate \
  --source sqlite:////path/to/backups/strikenova.db \
  --target 'postgresql+psycopg://...'

# 4) Verify independently
python tools/migrate_sqlite_to_postgres.py verify \
  --source sqlite:////path/to/backups/strikenova.db \
  --target 'postgresql+psycopg://...'
```
