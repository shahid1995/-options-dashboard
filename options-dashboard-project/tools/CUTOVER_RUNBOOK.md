# SQLite → PostgreSQL Production Cutover Runbook

**Status:** REHEARSAL COMPLETE — DO NOT EXECUTE UNTIL APPROVED
**Date:** August 31, 2026

---

## Prerequisites

- [ ] Railway CLI authenticated
- [ ] PostgreSQL service online (`Postgres` service ID: `17c4d5b5-6abd-46a1-a485-7c168cbc73ee`)
- [ ] Backend service accessible (`-options-dashboard` service ID: `7e6badf4-0f65-4a4c-a731-25b464b9923a`)
- [ ] `psycopg2-binary` installed locally
- [ ] SSH key registered for Railway access
- [ ] Rehearsal migration verified successfully

## Pre-Cutover Checklist

- [ ] Back up current Railway PostgreSQL rehearsal data (for rollback evidence)
- [ ] Schedule maintenance window (5-10 minutes expected)
- [ ] Notify stakeholders
- [ ] Confirm no active trading sessions

---

## Cutover Steps

### Step 1: Stop Application Writes

```bash
# SSH into production backend
railway ssh -i ~/.ssh/railway_freebuff -s 7e6badf4-0f65-4a4c-a731-25b464b9923a

# Inside container: stop accepting new writes
# (The application uses SQLite in-memory for writes during normal operation)
# Verify no active writes:
ls -la /app/paper_journal.db*
```

### Step 2: Create FINAL SQLite Backup

```bash
# Inside production container via SSH
python3 -c "
import sqlite3, hashlib, os

src = sqlite3.connect('file:///app/paper_journal.db?mode=ro', uri=True)
dst = sqlite3.connect('/tmp/paper_journal_final.db')
src.backup(dst)
dst.close()
src.close()

# Verify
dst = sqlite3.connect('/tmp/paper_journal_final.db')
cur = dst.cursor()
cur.execute('PRAGMA integrity_check')
print(f'Integrity: {cur.fetchone()[0]}')

cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" ORDER BY name')
tables = [r[0] for r in cur.fetchall()]
print(f'Tables: {len(tables)}')
total = 0
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM [{t}]')
    cnt = cur.fetchone()[0]
    if cnt > 0:
        print(f'  {t}: {cnt} rows')
        total += cnt
print(f'Total rows: {total}')
dst.close()

# SHA-256
h = hashlib.sha256()
with open('/tmp/paper_journal_final.db', 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
print(f'SHA-256: {h.hexdigest()}')
print(f'Size: {os.path.getsize(\"/tmp/paper_journal_final.db\")} bytes')
"
```

### Step 3: Extract Backup Locally

```bash
# From local machine
railway ssh -i ~/.ssh/railway_freebuff -s 7e6badf4-0f65-4a4c-a731-25b464b9923a -- \
  bash -c "base64 /tmp/paper_journal_final.db" > /tmp/final_b64.txt

base64 -d /tmp/final_b64.txt > paper_journal_final.db

# Verify SHA-256 matches
sha256sum paper_journal_final.db
```

### Step 4: Verify Target PostgreSQL Schema

```bash
# Run Alembic migration (idempotent)
DATABASE_URL="postgresql://postgres@127.0.0.1:25432/railway" \
  python -m alembic upgrade head
```

### Step 5: Run Migration

```bash
python tools/migrate_sqlite_to_postgres.py \
  --sqlite paper_journal_final.db \
  --pg-url "postgresql://postgres@127.0.0.1:25432/railway"
```

### Step 6: Run Verification

```bash
python tools/migrate_sqlite_to_postgres.py \
  --validate-only \
  --sqlite paper_journal_final.db \
  --pg-url "postgresql://postgres@127.0.0.1:25432/railway"
```

### Step 7: Verify Application/Security Invariants

```bash
# Verify:
# - User data intact
# - Session integrity
# - Broker encrypted fields preserved
# - GEX provenance columns present
# - No plaintext credentials
# - Trading status unchanged
# - Sequences corrected
```

### Step 8: Change DATABASE_URL on Railway

```bash
# ONLY after all verifications pass
railway variables set \
  DATABASE_URL="postgresql://postgres:PASSWORD@postgres.railway.internal:5432/railway" \
  -s 7e6badf4-0f65-4a4c-a731-25b464b9923a \
  --skip-deploys
```

### Step 9: Deploy/Restart Backend

```bash
# Railway will redeploy automatically when DATABASE_URL changes
# Or manually trigger:
railway service restart -s 7e6badf4-0f65-4a4c-a731-25b464b9923a
```

### Step 10: Smoke Test

```bash
# Verify production health
curl -s https://options-dashboard-production-fb47.up.railway.app/health

# Verify Google OAuth still works
# Verify broker connections still work
# Verify market data still loads
# Verify GEX still loads
```

### Step 11: Verify Production Data

```bash
# SSH into production and verify PostgreSQL is being used
railway ssh -i ~/.ssh/railway_freebuff -s 7e6badf4-0f65-4a4c-a731-25b464b9923a

# Inside container: verify DATABASE_URL points to PostgreSQL
python3 -c "
import os
url = os.environ.get('DATABASE_URL', '')
print(f'DATABASE_URL starts with: {url[:15]}...')
print(f'Using PostgreSQL: {url.startswith(\"postgresql\")}')
"
```

---

## Rollback Procedure

If anything fails during cutover:

1. **Revert DATABASE_URL** to the original SQLite path
2. **Redeploy** the backend
3. **Verify** production health
4. **Investigate** the failure

```bash
# Rollback DATABASE_URL
railway variables set \
  DATABASE_URL="sqlite:///app/paper_journal.db" \
  -s 7e6badf4-0f65-4a4c-a731-25b464b9923a \
  --skip-deploys

# Redeploy
railway service restart -s 7e6badf4-0f65-4a4c-a731-25b464b9923a
```

---

## Post-Cutover

- [ ] Monitor production logs for 24 hours
- [ ] Verify all features work correctly
- [ ] Clean up SQLite backup files
- [ ] Update documentation
- [ ] Close PR #36

---

## Safety Gates

The migration tool will refuse cutover unless ALL of these pass:

| Gate | Check |
|------|-------|
| 1 | Final SQLite backup exists |
| 2 | SQLite integrity = ok |
| 3 | SHA-256 recorded |
| 4 | Target schema = expected Alembic head |
| 5 | Target was empty before migration |
| 6 | Row counts match |
| 7 | Fingerprints match |
| 8 | FK validation passes |
| 9 | Sequences pass |
| 10 | Security invariants pass |

**No automatic cutover. Require explicit `--cutover` flag.**
