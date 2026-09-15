# StrikeNova SQLite → PostgreSQL Production Cutover Runbook

**Status:** REHEARSAL COMPLETE — DO NOT EXECUTE UNTIL EXPLICITLY APPROVED
**Tool:** `backend/tools/migrate_sqlite_to_postgres.py`
**Production state:** SQLite remains the production database. This document is a future operator runbook only.

---

## 0. Non-negotiable safety rules

1. Do not execute this runbook without explicit approval for the production cutover window.
2. Never migrate directly from the live SQLite database. Always create and verify a final online backup first.
3. Never expose, commit, log, paste, or store PostgreSQL credentials in repository files.
4. Never use `--skip-verify` for a production migration.
5. Never proceed after a failed gate. Stop, preserve evidence, and investigate.
6. Do not delete the final SQLite backup until the PostgreSQL deployment has passed post-cutover validation and the rollback-retention period has been approved.
7. The migration tool must not change Railway/Vercel routing automatically. The `DATABASE_URL` change is a separate, explicit operator action.
8. The final migration window must prevent writes to the SQLite source. Otherwise PostgreSQL cannot be guaranteed to contain the final production state.
9. If PostgreSQL has accepted writes after cutover, do not blindly switch back to the old SQLite copy; follow the rollback decision tree below.

---

## 1. Preconditions — GO / NO-GO

All of these must be **GO** before entering the maintenance window:

| Gate | Required evidence | Decision |
|---|---|---|
| Production backup access | Operator can read the live SQLite database through an approved controlled environment | GO / NO-GO |
| PostgreSQL target | Correct PostgreSQL service/database identified; target credentials available securely | GO / NO-GO |
| Target capacity | Current PostgreSQL storage capacity and free space measured; sufficient margin remains after rehearsal | GO / NO-GO |
| Rehearsal | Latest PostgreSQL compatibility workflow is green | GO / NO-GO |
| Schema | Target is at the current Alembic head | GO / NO-GO |
| Rollback | Final SQLite backup can be restored/reused and prior routing configuration is documented | GO / NO-GO |
| Maintenance window | No application/data writes will occur during final backup + migration + validation | GO / NO-GO |
| Monitoring | Production logs/health checks are available during and after cutover | GO / NO-GO |

If any item is NO-GO: **STOP.**

---

## 2. Stage A — Enter maintenance / freeze writes

Before taking the final backup:

- Put the application in maintenance/read-only mode.
- Stop scheduled jobs that write to SQLite.
- Stop GEX capture/ingestion.
- Stop administrative jobs that can modify database state.
- Ensure no broker/session workflow can create database writes.
- Record the maintenance start timestamp.

**GO gate:** confirmed zero-write window.

Do not continue if writes are still occurring.

---

## 3. Stage B — Create and verify the final SQLite backup

Create the backup from the controlled environment:

```bash
cd options-dashboard-project/backend
python tools/migrate_sqlite_to_postgres.py backup \
  --source /path/to/live/paper_journal.db \
  --backup /path/to/backups/strikenova-final-YYYYMMDD-HHMM.db
```

The backup workflow uses SQLite's online backup API and verifies SQLite integrity.

Record:

- source path
- backup path
- creation timestamp
- backup file size
- SHA-256 checksum

```bash
sha256sum /path/to/backups/strikenova-final-YYYYMMDD-HHMM.db
```

**GO gate:** backup integrity = `ok`, checksum recorded, backup readable.

If backup creation or integrity verification fails: **STOP.**

---

## 4. Stage C — Prepare and preflight PostgreSQL

Apply the current Alembic schema to the intended PostgreSQL target in the controlled environment:

```bash
DATABASE_URL='postgresql+psycopg://...' python -m alembic upgrade head
```

Do not place the real credential in a committed file.

Run read-only preflight against the final backup and target:

```bash
python tools/migrate_sqlite_to_postgres.py preflight \
  --source sqlite:////path/to/backups/strikenova-final-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  --target-budget-mib <verified-target-capacity-mib>
```

Preflight must confirm:

- source is file-backed SQLite
- target is PostgreSQL
- target is reachable
- every source application table exists on target
- every source column exists on target
- source size is within the configured safety budget
- target is suitable for a clean import

**GO gate:** all preflight checks pass.

If any check fails: **STOP.**

---

## 5. Stage D — Confirm target is disposable/empty

The production import target must contain no unrelated application data.

Do not merge the final production dataset into an unknown or previously used database.

**GO gate:** target emptiness/ownership is explicitly verified.

If the target contains unexpected rows: **STOP.**

---

## 6. Stage E — Import the final backup

Run the migration against the verified backup:

```bash
python tools/migrate_sqlite_to_postgres.py migrate \
  --source sqlite:////path/to/backups/strikenova-final-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  --batch-size 1000 \
  --target-budget-mib <verified-target-capacity-mib>
```

The migration must:

1. validate source/target compatibility
2. refuse an unexpected non-empty target
3. copy in foreign-key dependency order
4. use bounded batches
5. remain inside one PostgreSQL transaction
6. repair sequence state
7. commit only after import/sequence operations succeed
8. run verification

If migration fails before commit, PostgreSQL must roll back completely.

**GO gate:** migration exits successfully and verification reports `ok=true`.

If migration fails: **STOP. Do not switch production routing.**

---

## 7. Stage F — Independent post-import verification

Run verification separately and archive the sanitized JSON report:

```bash
python tools/migrate_sqlite_to_postgres.py verify \
  --source sqlite:////path/to/backups/strikenova-final-YYYYMMDD-HHMM.db \
  --target 'postgresql+psycopg://...' \
  > /path/to/reports/strikenova-postgres-verify-YYYYMMDD-HHMM.json
```

Required gates:

1. SQLite backup integrity = `ok`
2. Alembic head matches current expected head
3. every source application table exists on target
4. every source table row count matches
5. deterministic fingerprints match
6. primary-key uniqueness passes
7. foreign-key integrity passes
8. NOT NULL integrity passes
9. PostgreSQL sequences are at least the imported maximum
10. encrypted credential fields are preserved
11. GEX provenance is preserved
12. user/session/broker ownership is preserved
13. cross-user violation count = `0`
14. target storage remains within the approved capacity budget

**GO gate:** every required gate passes.

---

## 8. Stage G — Application validation before routing switch

Run the backend against PostgreSQL in a non-production/staging environment first whenever possible.

Validate at minimum:

- application startup
- Alembic startup path
- authentication/login/logout
- session persistence
- broker connection storage/retrieval
- encrypted credential retrieval/decryption path
- paper trading persistence
- GEX snapshot reads/writes and provenance
- historical-data reads
- WebSocket/session authorization
- core dashboard API requests

**GO gate:** all critical flows pass against PostgreSQL.

Do not switch production routing if the application falls back to SQLite or any critical PostgreSQL flow fails.

---

## 9. Stage H — Production DATABASE_URL switch

Only after all previous gates are green:

1. Preserve the final SQLite backup.
2. Record the current production database configuration so it can be restored.
3. Change the production backend `DATABASE_URL` to the approved PostgreSQL connection/service reference using the platform's secure configuration mechanism.
4. Explicitly restart/redeploy the backend as approved for the maintenance window.

**Important:** the migration repository code does not perform this routing change automatically.

**GO gate:** backend starts successfully against PostgreSQL and does not initialize/fall back to SQLite.

---

## 10. Stage I — Post-cutover smoke tests

Immediately after startup, verify:

- health endpoint
- `/auth/status`
- login/logout
- existing user session behavior
- broker connection retrieval
- GEX data loading
- paper-trading state
- core dashboard pages/API calls
- background jobs are pointed at PostgreSQL
- no database connection errors in logs

Record timestamp and result for each check.

**GO gate:** all critical smoke tests pass.

---

## 11. Stage J — Observation period

For the approved observation period:

- monitor backend logs
- monitor PostgreSQL connections/errors
- monitor database size
- monitor application latency/error rates
- monitor authentication/session failures
- monitor GEX ingestion and paper-trading persistence

Keep the final SQLite backup untouched throughout the rollback-retention period.

Only after the observation period passes should the migration be considered operationally complete.

---

# Rollback decision tree

## A. Failure before DATABASE_URL switch

**Action:** do not switch production routing.

- Leave production on SQLite.
- Preserve the failed PostgreSQL target for investigation if useful.
- Preserve the final SQLite backup.
- Fix the issue and rehearse again.

**Expected production impact:** none.

---

## B. Failure immediately after switch, before any PostgreSQL writes

**Action:**

1. Stop/restrict the PostgreSQL-backed application.
2. Confirm no production writes were accepted by PostgreSQL.
3. Restore the previous SQLite `DATABASE_URL` configuration.
4. Restart the backend.
5. Run health/auth/core smoke tests.
6. Keep the final SQLite backup.

**GO gate for rollback:** confirmed zero PostgreSQL production writes after the switch.

---

## C. PostgreSQL accepted production writes after cutover

**Do NOT blindly switch back to SQLite.**

The old SQLite backup does not contain those PostgreSQL writes and reverting immediately can lose user data.

Instead:

1. Stop/restrict further writes.
2. Preserve PostgreSQL state.
3. Determine exactly what writes occurred after cutover.
4. Decide whether the issue can be fixed forward on PostgreSQL.
5. If reverting is mandatory, define and execute an explicit data-reconciliation/export plan before restoring SQLite routing.
6. Validate the reconciled SQLite state independently.
7. Only then restore SQLite routing.

This is a controlled recovery procedure, not an automatic rollback.

---

## D. Data-integrity problem discovered after cutover

Treat as a **SEV-1 migration integrity incident**:

1. Freeze writes.
2. Preserve both SQLite backup and PostgreSQL state.
3. Do not destroy evidence.
4. Compare archived verification report with live PostgreSQL state.
5. Determine whether the issue is migration-only, application behavior, or post-cutover writes.
6. Prefer forward correction when safe.
7. Use SQLite rollback only after data reconciliation is understood.

---

# Final production Go/No-Go checklist

The operator should not declare cutover successful unless every item below is checked:

- [ ] Approved maintenance window active
- [ ] SQLite writes frozen
- [ ] Final SQLite backup created
- [ ] Backup integrity = `ok`
- [ ] Backup SHA-256 recorded
- [ ] PostgreSQL target identified and secured
- [ ] PostgreSQL capacity verified
- [ ] Alembic schema at current head
- [ ] Target empty/approved
- [ ] Preflight passed
- [ ] Migration completed
- [ ] Migration verification `ok=true`
- [ ] Counts match
- [ ] Fingerprints match
- [ ] PK/FK/NOT NULL checks pass
- [ ] Sequences pass
- [ ] Security/ownership checks pass
- [ ] Cross-user violations = 0
- [ ] Application PostgreSQL smoke tests pass
- [ ] Production DATABASE_URL change explicitly approved
- [ ] Backend restarted/redeployed explicitly
- [ ] Post-cutover smoke tests pass
- [ ] Monitoring active
- [ ] Final SQLite backup retained

**Any unchecked item = NO-GO.**

**No automatic cutover is implemented by this repository.**
