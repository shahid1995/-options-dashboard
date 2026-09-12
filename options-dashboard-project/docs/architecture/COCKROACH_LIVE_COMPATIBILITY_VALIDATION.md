# StrikeNova — Live CockroachDB Compatibility Validation

**Validation ID:** CRDB-LIVE-VALIDATION-001  
**Date:** 2026-09-12  
**Status:** 🔴 ROOT CAUSE CONFIRMED — DDL Visibility Incompatibility  
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
| Test database | test_ddl (disposable, in-memory) |
| Connection | `cockroachdb+psycopg://root@localhost:26257/test_ddl?sslmode=disable` |

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

**Fix applied:** Added `cockroachdb` branch:
```python
if dialect in ("postgresql", "cockroachdb"):
    op.execute("... WHERE is_default = true")
elif dialect == "sqlite":
    op.execute("... WHERE is_default = 1")
else:
    raise RuntimeError(...)
```

**Status:** ✅ Resolved

---

### Attempt 2 — Migration `f7a3c2d1e94b` (ROOT CAUSE CONFIRMED)

**Error:**
```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn) 
column "trading_status" does not exist

[SQL: 
        UPDATE broker_connections
        SET trading_status = 'active'
        WHERE status = 'connected'
        ]
```

**Migration:** `f7a3c2d1e94b_add_capability_separation_columns.py`  
**Failing line:** 55-61

---

## 3. Root Cause Investigation

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

**Evidence:**
- Mode A (same transaction): Column not visible to SHOW COLUMNS or UPDATE
- Mode B (separate transactions): Column visible and UPDATE succeeds
- Mode C (SQLAlchemy): Same failure as raw psycopg

This is NOT:
- A SQLAlchemy dialect issue (raw psycopg also fails)
- An Alembic configuration issue (same behavior with raw connections)
- A migration ordering issue (the column simply isn't visible yet)

---

## 4. Recommended Minimal Fix

The migration must be restructured so that:
1. All DDL (ADD COLUMN) is committed first
2. Then DML (UPDATE) runs in a separate transaction

**Option 1: Split into two migrations**
- Migration 1: Add all 4 columns
- Migration 2: UPDATE statements + CREATE INDEX

**Option 2: Use `batch_alter_table` with explicit commit**
- May not work as Alembic still wraps in single transaction

**Option 3: Use `transactional_ddl = False` in env.py**
- Would affect all migrations globally
- Not recommended without broader analysis

**Recommended: Option 1 (split migration)**

---

## 5. Status Summary

| Migration | Status |
|-----------|--------|
| `d3eb45a2e046` (baseline) | ✅ Success |
| `125e1807df8d` (broker connection foundation) | ✅ Success (after fix) |
| `a0deb75ad22f` (password hash) | ✅ Success |
| `f7a3c2d1e94b` (capability separation) | 🔴 BLOCKED — DDL visibility |

---

## 6. Findings

| Area | Status | Notes |
|------|--------|-------|
| Gap A (dialect dispatch) | 🟢 SAFE | `db_dialect.py` and `fill_ledger.py` correctly recognize CRDB |
| Gap B (fill ledger) | 🟢 SAFE | `fill_ledger.py` routes CRDB to PostgreSQL path |
| Gap C (retry boundary) | 🟡 CAUTION | `retry_on_serialization()` preserved; no broken wrappers remain |
| Migration `125e1807df8d` | 🟢 FIXED | `cockroachdb` branch added; partial index creates correctly |
| Migration `f7a3c2d1e94b` | 🔴 BLOCKED | DDL not visible to DML in same transaction |
| Full migration suite | 🔴 BLOCKED | Cannot proceed past `f7a3c2d1e94b` |

---

## 7. Final Decision

### ROOT CAUSE CONFIRMED — READY FOR TARGETED FIX

**Root cause:** CockroachDB does not make DDL changes (ALTER TABLE ADD COLUMN) visible to subsequent DML statements within the same transaction. The migration `f7a3c2d1e94b` adds columns and then immediately updates them in the same transaction, which works in PostgreSQL but fails in CockroachDB.

**Recommended fix:** Split migration `f7a3c2d1e94b` into two separate migrations:
1. First migration: Add all 4 columns (data_status, data_source, trading_status, trading_static_ip)
2. Second migration: UPDATE statements + CREATE INDEX statements

This is a validation checkpoint. No code changes were made to the failing migration.

---

*End of validation report.*
