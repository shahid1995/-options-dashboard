# SQLite → PostgreSQL Production Cutover Runbook

**Status:** REHEARSAL COMPLETE — DO NOT EXECUTE UNTIL APPROVED
**Tool:** `backend/tools/migrate_sqlite_to_postgres.py`

---

## IMPORTANT: Zero-Write Maintenance Window Required

The final cutover MUST occur during a maintenance window where:
- Application is in read-only/maintenance mode
- No new writes are accepted
- No broker connections are active
- No GEX capture is running

This guarantees no data is lost between the final SQLite backup and the DATABASE_URL switch.

---

## Cutover Steps

### 1. Enter maintenance mode
Stop application writes. Put the backend in maintenance/read-only mode.

### 2. Create FINAL SQLite backup
Inside the production container:
```python
sqlite3.Connection.backup()  # WAL-consistent
```

### 3. Verify backup integrity
```bash
PRAGMA integrity_check(quick)  # → ok
```

### 4. Record SHA-256
```bash
sha256sum /tmp/paper_journal_final.db
```

### 5. Verify PostgreSQL schema
```bash
DATABASE_URL="postgresql://..." python -m alembic upgrade head
```

### 6. Ensure target is clean/expected
```bash
python backend/tools/migrate_sqlite_to_postgres.py \
  --validate-only \
  --sqlite /tmp/paper_journal_final.db \
  --pg-url "postgresql://..."
```

### 7. Import FINAL backup
```bash
python backend/tools/migrate_sqlite_to_postgres.py \
  --sqlite /tmp/paper_journal_final.db \
  --pg-url "postgresql://..."
```

### 8. Run full verification
```bash
python backend/tools/migrate_sqlite_to_postgres.py \
  --ready-for-cutover \
  --sqlite /tmp/paper_journal_final.db \
  --pg-url "postgresql://..."
```

### 9. Only after PASS, change DATABASE_URL
```bash
railway variables set DATABASE_URL="postgresql://..." \
  -s <backend-service-id> --skip-deploys
```

### 10. Redeploy backend
```bash
railway service restart -s <backend-service-id>
```

### 11. Smoke test authentication
Verify Google OAuth still works.

### 12. Smoke test market-data path
Verify market data loads correctly.

### 13. Smoke test user/session persistence
Verify user sessions survive page reload.

### 14. Monitor
Watch production logs for 24 hours.

### 15. Rollback if necessary
Use the preserved SQLite backup to revert DATABASE_URL.

---

## Rollback Procedure

If anything fails:
1. Revert DATABASE_URL to SQLite path
2. Redeploy backend
3. Verify production health

---

## Safety Gates (enforced by --ready-for-cutover)

| Gate | Check |
|------|-------|
| 1 | SQLite integrity = ok |
| 2 | Backup SHA-256 recorded |
| 3 | Alembic head matches expected |
| 4 | All tables migrated successfully |
| 5 | Row counts match |
| 6 | SHA-256 fingerprints match |
| 7 | PK uniqueness verified |
| 8 | FK integrity verified |
| 9 | NOT NULL integrity verified |
| 10 | Sequences correct |
| 11 | Encrypted credentials preserved |
| 12 | GEX provenance preserved |
| 13 | Multi-user ownership intact |
| 14 | No cross-user violations |

**No automatic cutover. `--ready-for-cutover` only reports readiness.**
**The actual DATABASE_URL change is a separate explicit operator action.**
