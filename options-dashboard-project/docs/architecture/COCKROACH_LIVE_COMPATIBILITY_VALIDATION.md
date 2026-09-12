# StrikeNova — Live CockroachDB Compatibility Validation

**Validation ID:** CRDB-LIVE-VALIDATION-001  
**Date:** 2026-09-12  
**Status:** 🟢 FULL MIGRATION CHAIN SUCCESS  
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
| Test database | strikenova_b8c9 (disposable, in-memory) |
| Connection | `cockroachdb+psycopg://root@localhost:26257/strikenova_b8c9?sslmode=disable` |

---

## 2. Migration Results

### Attempt 1 — Migration `125e1807df8d` (RESOLVED)

**Original Error:**
```
sqlalchemy.exc.DataError: (psycopg.errors.InvalidParameterValue) 
unsupported comparison operator: <bool> = <int>
```

**Fix applied:** Added `cockroachdb` branch in commit `2ee6eff`.

**Status:** ✅ Resolved

---

### Attempt 2 — Migration `f7a3c2d1e94b` (RESOLVED via split)

**Original Error:**
```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn) 
column "trading_status" does not exist
```

**Fix applied:** Split into DDL-only + DML revisions.

**Status:** ✅ Resolved

---

### Attempt 3 — Migration `b8c9f1d2e34a` (RESOLVED via split)

**Original Error:**
```
sqlalchemy.exc.NotSupportedError: (psycopg.errors.FeatureNotSupported) 
cannot create partial index on column "google_sub" which is not public
```

**Fix applied:** Split into DDL-only (ADD COLUMN) + index creation revisions.

**Status:** ✅ Resolved

---

### Attempt 4 — Full Migration Chain (SUCCESS)

**Fresh CockroachDB database:** `strikenova_b8c9`  
**Command:** `alembic upgrade head`  
**Result:** ✅ SUCCESS — all migrations applied

**Final state:**
- Head revision: `5e2a7b9c3f4d`
- All 31 tables created
- `users` table has `google_sub` column (VARCHAR(128), nullable)
- `ix_users_google_sub` partial unique index created correctly

---

## 3. Final Migration Graph

```
<base> → d3eb45a2e046 (baseline)
  ↓
125e1807df8d (broker connection foundation)
  ↓
a0deb75ad22f (password_hash) ──────────────┐
  ↓                                        │
f7a3c2d1e94b (capability separation DDL)   │
  ↓                                        │
9e4d8c2a1f7b (capability backfill DML)     │
  ↓                                        │
3f8a2e9c4d5b (merge) ←─────────────────────┘
  ↓
... (rest of chain including b8c9f1d2e34a → c7d3e5f8a9b2)
  ↓
5e2a7b9c3f4d (head)
```

**Single head:** `5e2a7b9c3f4d`

---

## 4. Fixes Applied

### Fix 1: Boolean Predicate (commit `2ee6eff`)

File: `125e1807df8d_add_broker_connection_foundation.py`

Added `cockroachdb` dialect branch for boolean literal:
```python
if dialect in ("postgresql", "cockroachdb"):
    op.execute("... WHERE is_default = true")
elif dialect == "sqlite":
    op.execute("... WHERE is_default = 1")
else:
    raise RuntimeError(...)
```

### Fix 2: DDL/DML Split for Capability Separation

Files:
- `f7a3c2d1e94b_add_capability_separation_columns.py` — DDL only (ADD COLUMN)
- `9e4d8c2a1f7b_capability_separation_backfill.py` — DML (UPDATEs) + indexes
- `3f8a2e9c4d5b_merge_capability_backfill.py` — Merge revision

### Fix 3: DDL/DML Split for Google Sub

Files:
- `b8c9f1d2e34a_add_google_sub_to_users.py` — DDL only (ADD COLUMN)
- `c7d3e5f8a9b2_google_sub_index.py` — Index creation with dialect-specific partial index syntax
- `5e2a7b9c3f4d_merge_google_sub_main.py` — Merge revision

---

## 5. Index Predicate Verification

The partial unique index `ix_users_google_sub` enforces:
- Multiple NULL values allowed
- Duplicate non-null `google_sub` rejected
- Unique non-null values accepted

**Dialect-specific syntax:**
- PostgreSQL: `postgresql_where='google_sub IS NOT NULL'`
- SQLite: `sqlite_where='google_sub IS NOT NULL'`
- CockroachDB: `cockroachdb_where='google_sub IS NOT NULL'`

---

## 6. Status Summary

| Migration | Status |
|-----------|--------|
| `d3eb45a2e046` (baseline) | ✅ Success |
| `125e1807df8d` (broker connection foundation) | ✅ Success |
| `a0deb75ad22f` (password hash) | ✅ Success |
| `f7a3c2d1e94b` (capability separation DDL) | ✅ Success |
| `9e4d8c2a1f7b` (capability separation DML) | ✅ Success |
| `3f8a2e9c4d5b` (merge) | ✅ Success |
| `b8c9f1d2e34a` (google_sub DDL) | ✅ Success |
| `c7d3e5f8a9b2` (google_sub index) | ✅ Success |
| `5e2a7b9c3f4d` (head) | ✅ Success |

---

## 7. Final Decision

### FULL MIGRATION CHAIN SUCCESS — READY FOR RUNTIME VALIDATION

The complete Alembic migration chain now applies successfully on CockroachDB v23.2.5. All schema objects (tables, indexes, constraints) are created correctly.

**Next phase:** Runtime validation (ORM operations, upserts, locking, concurrency, economic correctness).

---

*End of validation report.*
