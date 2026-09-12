# StrikeNova — Live CockroachDB Compatibility Validation

**Validation ID:** CRDB-LIVE-VALIDATION-001  
**Date:** 2026-09-12  
**Status:** 🟢 MIGRATION FIXED — READY TO RESUME FULL VALIDATION  
**Baseline commit:** `55ab353e5da1ba1f1a18c7a3c66a845e5d326252`  

---

## 1. Environment

| Component | Version |
|-----------|---------|
| CockroachDB | v23.2.5 (CCL) |
| SQLAlchemy | 2.0.52 |
| psycopg | 3.3.5 |
| sqlalchemy-cockroachdb | 2.0.4 |
| Python | 3.11.16 |
| Test database | strikenova_test (disposable, in-memory) |
| Connection | `cockroachdb+psycopg://root@localhost:26257/strikenova_test?sslmode=disable` |

---

## 2. Migration Results

### Original Failure (Resolved)

**Error:**
```
sqlalchemy.exc.DataError: (psycopg.errors.InvalidParameterValue) 
unsupported comparison operator: <bool> = <int>

[SQL: CREATE UNIQUE INDEX uq_one_default_per_user_broker 
      ON broker_connections (user_id, broker) 
      WHERE is_default = 1]
```

**Root cause:** Migration `125e1807df8d` used `dialect == "postgresql"` which excluded CockroachDB, causing it to fall into the SQLite branch with `WHERE is_default = 1`. CockroachDB rejects integer comparison against `BOOL` columns.

**Fix applied** in `125e1807df8d_add_broker_connection_foundation.py`:
```python
if dialect in ("postgresql", "cockroachdb"):
    op.execute("... WHERE is_default = true")
elif dialect == "sqlite":
    op.execute("... WHERE is_default = 1")
else:
    raise RuntimeError(...)
```

### Verification

Migration now succeeds on CockroachDB. The partial index is created with the correct predicate:

```sql
UNIQUE INDEX uq_one_default_per_user_broker (user_id ASC, broker ASC) WHERE is_default = true
```

Confirmed via `SHOW CREATE TABLE broker_connections`.

---

## 3. Schema Creation Status

Migrations verified to apply on CockroachDB:
- `d3eb45a2e046` — baseline ✅
- `125e1807df8d` — broker connection foundation ✅
- `a0deb75ad22f` — password hash ✅

Remaining migrations (`f7a3c2d1e94b` and beyond) have **not yet been tested** on CockroachDB. The fix resolves the first blocker; full migration validation is still pending.

---

## 4. Next Steps

1. Continue running `alembic upgrade head` against CockroachDB
2. Identify and fix any additional migration incompatibilities
3. Run SQL compatibility tests (ON CONFLICT, FOR UPDATE, etc.)
4. Run broker-sync integration tests
5. Run concurrency and serialization failure tests
6. Validate economic correctness

---

## 5. Findings

| Area | Status | Notes |
|------|--------|-------|
| Gap A (dialect dispatch) | 🟢 SAFE | `db_dialect.py` and `fill_ledger.py` correctly recognize CRDB |
| Gap B (fill ledger) | 🟢 SAFE | `fill_ledger.py` routes CRDB to PostgreSQL path |
| Gap C (retry boundary) | 🟡 CAUTION | `retry_on_serialization()` preserved; no broken wrappers remain |
| Migration `125e1807df8d` | 🟢 FIXED | `cockroachdb` branch added; partial index creates correctly |
| Schema creation (partial) | 🟢 Partial | First 3 migrations succeed; remaining not yet tested |
| Full migration suite | ⚠️ Pending | Need to test `f7a3c2d1e94b` and beyond |

---

## 6. Final Decision

### MIGRATION FIXED — READY TO RESUME FULL VALIDATION

The targeted fix for migration `125e1807df8d` has been applied and verified. The first blocker is cleared. Full CockroachDB validation can now proceed to test the remaining migrations and runtime SQL behavior.

---

*End of validation report.*
