# StrikeNova — Live CockroachDB Compatibility Validation

**Validation ID:** CRDB-LIVE-VALIDATION-001  
**Date:** 2026-09-12  
**Status:** 🟢 Migration split SUCCESS — NEW BLOCKER FOUND  
**Baseline commit:** `55ab353e5da1ba1f1a18c7a3c66a845e5d326252`  
**Validation commit:** `2ee6effacd07ca5b330fc7d8af5b42aca5f52f02`

---

## 1. Environment

| Component | Version |
|-----------|---------|
| CockroachDB | v23.2.5 (CCL) |
| SQLAlchemy | 2.0.52 |
| psycopg | 3.3.5 |
| sqlalchemy-cockroachdb | 2.0.4 |
| Python | 3.11.16 |
| Test database | strikenova_validation (disposable, in-memory) |
| Connection | `cockroachdb+psycopg://root@localhost:26257/strikenova_validation?sslmode=disable` |

---

## 2. Migration Results

### Attempt 1 — Migration `125e1807df8d` (RESOLVED)

**Original Error:**
```
sqlalchemy.exc.DataError: (psycopg.errors.InvalidParameterValue) 
unsupported comparison operator: <bool> = <int>

[SQL: CREATE UNIQUE INDEX uq_one_default_per_user_broker 
      ON broker_connections (user_id, broker) 
      WHERE is_default = 1]
```

**Root cause:** Migration used `dialect == "postgresql"` which excluded CockroachDB, falling into the SQLite branch with `WHERE is_default = 1`. CockroachDB rejects integer comparison against BOOL columns.

**Fix applied:** Added `cockroachdb` branch in commit `2ee6eff`.

**Status:** ✅ Resolved

---

### Attempt 2 — Migration `f7a3c2d1e94b` (RESOLVED via split)

**Original Error:**
```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn) 
column "trading_status" does not exist
```

**Root cause:** CockroachDB does not expose DDL changes to subsequent DML within the same transaction.

**Investigation:** See Section 3 below for full evidence.

**Fix applied:** Split migration `f7a3c2d1e94b` into:
- `f7a3c2d1e94b` — DDL only (ADD COLUMN operations)
- `9e4d8c2a1f7b` — DML (backfill UPDATEs) + CREATE INDEX
- `3f8a2e9c4d5b` — Merge revision to rejoin migration chain

**Verification:** Schema now contains all four new columns:
- data_status (VARCHAR(20), NOT NULL, DEFAULT 'inactive')
- data_source (VARCHAR(20), nullable)
- trading_status (VARCHAR(20), NOT NULL, DEFAULT 'inactive')
- trading_static_ip (VARCHAR(45), nullable)

**Status:** ✅ Resolved

---

### Attempt 3 — Migration `b8c9f1d2e34a` (NEW BLOCKER)

**Error:**
```
sqlalchemy.exc.NotSupportedError: (psycopg.errors.FeatureNotSupported) 
cannot create partial index on column "google_sub" (12) which is not public

[SQL: CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub) 
      WHERE google_sub IS NOT NULL]
```

**Migration:** `b8c9f1d2e34a_add_google_sub_to_users.py`  
**Failing line:** 23-30

**Root cause:** CockroachDB does not support partial indexes on columns that are not yet public (i.e., the column was just added in the same transaction). The `postgresql_where` parameter creates a partial index, which requires the column to be committed first.

**Classification:** 🔴 CONFIRMED BLOCKER

---

## 3. Root Cause Investigation (Attempt 2)

### 3.1 Migration Sequence

The migration performs:
1. `op.add_column("broker_connections", sa.Column("data_status", ...))`
2. `op.add_column("broker_connections", sa.Column("data_source", ...))`
3. `op.add_column("broker_connections", sa.Column("trading_status", ...))`
4. `op.add_column("broker_connections", sa.Column("trading_static_ip", ...))`
5. `op.execute("UPDATE broker_connections SET trading_status = 'active' WHERE status = 'connected'")` ← FAILS

### 3.2 Alembic Transaction Model

From `alembic/env.py`:
- `transaction_per_migration` is not explicitly set (default: True)
- `context.begin_transaction()` wraps `run_migrations()`
- All operations within a migration run on the same connection within the same transaction

### 3.3 Minimal Reproduction

Created test table:
```sql
CREATE TABLE test_table (id INT PRIMARY KEY, status STRING);
INSERT INTO test_table VALUES (1, 'connected'), (2, 'disconnected');
```

#### Mode A: Same Transaction (psycopg raw)

```python
conn.autocommit = False
cur = conn.cursor()
cur.execute('ALTER TABLE test_table ADD COLUMN trading_status_new STRING')
# Check visibility
cur.execute('SHOW COLUMNS FROM test_table')
# Result: Only shows id, status (NOT trading_status_new!)
cur.execute("UPDATE test_table SET trading_status_new = 'active' WHERE status = 'connected'")
# FAILS: column "trading_status_new" does not exist
```

**Result:** ❌ FAILED — Column not visible to subsequent DML in same transaction

#### Mode B: Separate Transactions (psycopg raw)

```python
conn.autocommit = False
cur = conn.cursor()
cur.execute('ALTER TABLE test_table ADD COLUMN data_status_new STRING')
conn.commit()  # Commit ALTER

conn.autocommit = False
cur.execute("UPDATE test_table SET data_status_new = 'active' WHERE status = 'connected'")
# SUCCEEDS
conn.commit()
```

**Result:** ✅ SUCCESS — Column visible after separate commit

#### Mode C: SQLAlchemy Path

```python
conn = engine.connect()
trans = conn.begin()
conn.execute(text('ALTER TABLE test_table ADD COLUMN sa_trading_status STRING'))
# Check visibility
result = conn.execute(text('SHOW COLUMNS FROM test_table'))
# Result: Does NOT show sa_trading_status
conn.execute(text("UPDATE test_table SET sa_trading_status = 'active' WHERE status = 'connected'"))
# FAILS: column "sa_trading_status" does not exist
```

**Result:** ❌ FAILED — Same behavior as raw psycopg

### 3.4 Schema Visibility Evidence

After `ALTER TABLE ADD COLUMN` within a transaction:
- `SHOW COLUMNS FROM test_table` does NOT show the new column
- `UPDATE` referencing the new column fails with `UndefinedColumn`
- The column becomes visible only after `COMMIT` and a new transaction begins

### 3.5 Root Cause Classification

**ROOT CAUSE CONFIRMED: Possibility A**

CockroachDB genuinely does not expose the new schema version to subsequent DML within the same transaction. This is a fundamental difference from PostgreSQL where DDL is transactional and immediately visible.

---

## 4. Status Summary

| Migration | Status |
|-----------|--------|
| `d3eb45a2e046` (baseline) | ✅ Success |
| `125e1807df8d` (broker connection foundation) | ✅ Success (after fix) |
| `a0deb75ad22f` (password hash) | ✅ Success |
| `f7a3c2d1e94b` (capability separation DDL) | ✅ Success (after split) |
| `9e4d8c2a1f7b` (capability separation DML) | ✅ Success |
| `3f8a2e9c4d5b` (merge) | ✅ Success |
| `b8c9f1d2e34a` (google_sub) | 🔴 BLOCKED — Partial index on non-public column |

---

## 5. Findings

| Area | Status | Notes |
|------|--------|-------|
| Gap A (dialect dispatch) | 🟢 SAFE | `db_dialect.py` and `fill_ledger.py` correctly recognize CRDB |
| Gap B (fill ledger) | 🟢 SAFE | `fill_ledger.py` routes CRDB to PostgreSQL path |
| Gap C (retry boundary) | 🟡 CAUTION | `retry_on_serialization()` preserved; no broken wrappers remain |
| Migration `125e1807df8d` | 🟢 FIXED | `cockroachdb` branch added; partial index creates correctly |
| Migration `f7a3c2d1e94b` | 🟢 FIXED | Split into DDL-only + DML migrations |
| Migration `b8c9f1d2e34a` | 🔴 BLOCKED | Partial index on column added in same transaction |

---

## 6. Final Decision

### Migration split SUCCESS — READY TO CONTINUE CRDB VALIDATION

The targeted fix for migration `f7a3c2d1e94b` has been implemented and verified. The DDL/DML split approach works correctly on CockroachDB.

**Next blocker:** Migration `b8c9f1d2e34a` (add google_sub) fails because CockroachDB does not support partial indexes (`postgresql_where`) on columns that were added in the same transaction. This requires a similar split approach.

---

*End of validation report.*
