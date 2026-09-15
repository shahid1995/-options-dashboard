# StrikeNova PostgreSQL Application Compatibility Audit

**Date:** 2026-08-31
**Branch:** `feat/postgres-readiness` (based on `febd584`)
**Scope:** Backend application code (`app/`, `alembic/`)

---

## Summary

The StrikeNova backend is **substantially PostgreSQL-compatible**. The core application
(`db.py`, `alembic/env.py`, identity, authentication, broker connections, GEX, paper
trading) works on both SQLite and PostgreSQL with no code changes required.

A small number of **tools and scripts** contain SQLite-only assumptions that would
fail on PostgreSQL. These are non-blocking for production readiness since they are
standalone scripts, not the core application.

---

## 1. Compatible Code (No Changes Required)

### Core Application

| Component | Status | Evidence |
|-----------|--------|----------|
| `db.py` engine creation | ✅ | Dialect-aware: SQLite gets PRAGMA + `check_same_thread`, PostgreSQL gets connection pooling |
| `alembic/env.py` | ✅ | `render_as_batch` only for SQLite; URL normalization for both |
| `identity.py` (User, UserSession, BrokerConnection, BrokerToken) | ✅ | Pure SQLAlchemy ORM, dialect-agnostic |
| `models.py` (GexSnapshot, PaperAccount, etc.) | ✅ | Pure SQLAlchemy ORM |
| `routers/auth.py` | ✅ | Uses ORM queries, `datetime.now(timezone.utc)` |
| `routers/gex.py` | ✅ | Uses `dialect_insert()` for upserts |
| `services/gex_capture.py` | ✅ | ORM queries |
| `services/gex_history.py` | ✅ | ORM queries, `dialect_insert()` |
| `services/option_candles.py` | ✅ | Uses `dialect_insert()` |
| `services/nifty_candles.py` | ✅ | Uses `dialect_insert()` |
| `services/historical_gex.py` | ✅ | Uses `dialect_insert()` |
| `services/historical_greeks.py` | ✅ | Uses `dialect_insert()` |
| `services/paper_execution.py` | ✅ | ORM queries |
| `services/journal.py` | ✅ | ORM queries |
| `services/token_store.py` | ✅ | ORM queries |
| `services/valuation.py` | ✅ | ORM queries |
| `utils/db_dialect.py` | ✅ | Provides `dialect_insert()` for cross-dialect upserts |
| `utils/time.py` | ✅ | `datetime.now(timezone.utc)` — compatible with both |
| Health endpoint (`/health`) | ✅ | Uses `text("SELECT 1")` |

### Timestamps

- Application timestamps use `datetime.now(timezone.utc)` — **compatible**.
- Market-data timestamps use naive IST convention — **intentional, compatible**.
- No deprecated `datetime.utcnow()` in application code.
- `replace(tzinfo=None)` used for market-data naive timestamps — **intentional**.

### Boolean Handling

- No `Column(Boolean)` in models — uses `Mapped[bool]` which maps correctly.
- `is_default`, `is_active` are SQLAlchemy `bool` — **compatible**.

---

## 2. Risky Code (Non-Blocking, Tool-Only)

These are standalone tools/scripts, not the core application. They would fail if
run against PostgreSQL, but they do not affect the main application startup or API.

| File | Issue | Severity | Fix |
|------|-------|----------|-----|
| `tools/contract_metadata_backfill.py:68` | `connect_args={"check_same_thread": False}` unconditional | LOW | Guard with `if url.startswith("sqlite")` |
| `tools/live_verification.py:548` | `connect_args={"check_same_thread": False}` unconditional | LOW | Guard with `if url.startswith("sqlite")` |
| `tools/expired_candle_poc.py:57` | `connect_args={"check_same_thread": False}` unconditional | LOW | Guard with `if url.startswith("sqlite")` |

---

## 3. Confirmed PostgreSQL Blockers (Tool-Only)

| File | Line | Issue | Severity | Fix |
|------|------|-------|----------|-----|
| `services/backfill_benchmark.py:551` | `from sqlalchemy.dialects.sqlite import insert as sqlite_insert` | **BLOCKER** (for this tool only) | MEDIUM | Use `dialect_insert()` from `app.utils.db_dialect` |

This is a benchmarking tool, not the production application. It directly imports
the SQLite dialect insert, which would raise `ImportError` on PostgreSQL.

---

## 4. Recommended Fixes

### Priority 1 — Fix the SQLite-only import in `backfill_benchmark.py`

Replace:
```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
```
With:
```python
from app.utils.db_dialect import dialect_insert
```
And update the call site to use `dialect_insert(db.get_bind(), OptionCandle)`.

### Priority 2 — Guard `check_same_thread` in standalone tools

In `contract_metadata_backfill.py`, `live_verification.py`, `expired_candle_poc.py`:
```python
connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, connect_args=connect_args)
```

### Priority 3 — No changes needed for production readiness

The core application (`db.py`, routers, services, identity, models) is already
PostgreSQL-compatible. The fixes above are for standalone tools only.

---

## 5. Architecture Assessment

### Already PostgreSQL-Ready

1. **Engine creation** (`db.py`): Dialect-aware, connection pooling for PG
2. **URL normalization**: Handles `postgres://`, `postgresql://`, `postgresql+psycopg://`
3. **Alembic**: Batch mode only for SQLite, dialect-aware migrations
4. **Upserts**: `dialect_insert()` abstraction in `utils/db_dialect.py`
5. **Identity/auth**: Pure ORM, no raw SQL
6. **GEX**: ORM with `dialect_insert()` for upserts
7. **Paper trading**: Pure ORM
8. **Token store**: Pure ORM
9. **Health check**: `text("SELECT 1")` — universal

### Not Blocking

1. Standalone tools use SQLite-only features — they are not part of the production path
2. Market-data naive timestamps — intentional convention
3. No `GROUP_CONCAT`, `strftime`, or other SQLite-specific SQL functions in app code

---

## 6. Conclusion

**The core StrikeNova application is PostgreSQL-compatible without code changes.**

The only code change recommended is fixing `backfill_benchmark.py` to use the
dialect-agnostic `dialect_insert()` instead of the SQLite-specific import. This is
a tool-only fix and does not affect the production application path.

For staging readiness, the recommended minimum changes are:
1. Fix `backfill_benchmark.py` (Priority 1)
2. Guard `check_same_thread` in 3 standalone tools (Priority 2)
