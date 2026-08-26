# Phase 7.24.1 — Data Pipeline Foundation

## Status: PASS

## Summary

Implemented three new database tables that provide the infrastructure for observable, resumable, and safe data ingestion:

1. **`ingestion_log`** — records every ingestion operation
2. **`data_completeness`** — tracks per-instrument/session data completeness
3. **`ingestion_checkpoint`** — durable resume points for long-running ingestion

---

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_phase724_1_pipeline_foundation.py` | 35 comprehensive tests |

## Files Modified

| File | Change |
|------|--------|
| `app/models.py` | Added `IngestionLog`, `DataCompleteness`, `IngestionCheckpoint` models |
| `app/db.py` | Added idempotent `CREATE INDEX IF NOT EXISTS` in `init_db()` |

## Database Schema Added

### ingestion_log

```sql
CREATE TABLE ingestion_log (
    id INTEGER PRIMARY KEY,
    run_id VARCHAR(32) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    instrument_key VARCHAR(64),
    expiry_date VARCHAR(10),
    session_date VARCHAR(10),
    started_at VARCHAR(32) NOT NULL,
    completed_at VARCHAR(32),
    status VARCHAR(16) NOT NULL,
    api_calls INTEGER DEFAULT 0,
    rows_fetched INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    error_category VARCHAR(32),
    error_message TEXT,
    metadata_json TEXT
);
-- Indexes
CREATE INDEX ix_ingestion_log_operation_status ON ingestion_log (operation, status);
CREATE INDEX ix_ingestion_log_completed_at ON ingestion_log (completed_at);
-- Plus auto-indexes on run_id, instrument_key, session_date, status
```

### data_completeness

```sql
CREATE TABLE data_completeness (
    id INTEGER PRIMARY KEY,
    instrument_key VARCHAR(64) NOT NULL,
    session_date VARCHAR(10) NOT NULL,
    data_type VARCHAR(32) NOT NULL,
    expected_count INTEGER,
    actual_count INTEGER DEFAULT 0,
    missing_count INTEGER,
    status VARCHAR(16) NOT NULL,
    last_verified_at VARCHAR(32),
    last_attempted_at VARCHAR(32),
    reason TEXT,
    UNIQUE(instrument_key, session_date, data_type)
);
-- Indexes
CREATE INDEX ix_data_completeness_status ON data_completeness (status);
-- Plus auto-indexes on instrument_key, session_date, data_type
```

### ingestion_checkpoint

```sql
CREATE TABLE ingestion_checkpoint (
    id INTEGER PRIMARY KEY,
    pipeline VARCHAR(32) NOT NULL,
    instrument_key VARCHAR(64) NOT NULL,
    run_id VARCHAR(32),
    status VARCHAR(16) NOT NULL,
    items_processed INTEGER DEFAULT 0,
    items_total INTEGER DEFAULT 0,
    error_message TEXT,
    started_at VARCHAR(32),
    completed_at VARCHAR(32),
    updated_at VARCHAR(32),
    UNIQUE(pipeline, instrument_key)
);
-- Indexes
CREATE INDEX ix_ingestion_checkpoint_status ON ingestion_checkpoint (pipeline, status);
-- Plus auto-indexes on pipeline, instrument_key
```

---

## Migration Mechanism

The project uses SQLAlchemy's `Base.metadata.create_all()` for schema creation, which:
- Creates tables that don't exist
- Does NOT modify existing tables
- Does NOT delete data
- Is idempotent for table creation

For indexes that may already exist from partial previous runs, `init_db()` uses:
```sql
CREATE INDEX IF NOT EXISTS ...
```
This ensures idempotent index creation without errors on re-runs.

---

## Checkpoint Semantics

The `ingestion_checkpoint` table provides durable resume information:

- **Unique per (pipeline, instrument_key)** — one checkpoint per instrument per pipeline
- **Survives process termination** — stored in SQLite, not in memory
- **Survives server restart** — independent of FastAPI/uvicorn
- **Checkpoint points to last committed unit** — not merely the last attempted

**Relationship to existing `greeks_checkpoint`:**
The existing `greeks_checkpoint` table (Phase 7.23C) serves a similar purpose for Greek reconstruction specifically. `ingestion_checkpoint` generalizes the pattern for all pipelines. Both tables coexist — no migration of existing checkpoint data is needed.

---

## Completeness Semantics

The `data_completeness` table tracks whether a dataset is complete:

| Status | Meaning |
|--------|---------|
| EXPECTED | Data should exist but hasn't been fetched |
| PARTIAL | Some candles present, some missing |
| COMPLETE | All expected candles present |
| MISSING | Expected but no data found |
| UNAVAILABLE | API returned empty/error |
| FAILED | Attempted but failed |

The unique constraint on `(instrument_key, session_date, data_type)` ensures one record per instrument/session/type combination.

---

## Ingestion Log Semantics

The `ingestion_log` table provides full audit trail:

- **One row per operation** (per instrument/expiry/session)
- **Never stores secrets** — no access tokens, API keys, or session IDs
- **metadata_json** stores operational context (request counts, batch sizes)
- **Error tracking** with category and message
- **Indexed for operational queries** — latest run, failures, by instrument

---

## Existing Data Safety

Before migration:
- `nifty_candles`: 0 rows
- `contract_specs`: 0 rows
- `option_candles`: 0 rows
- `option_greeks`: 0 rows

After migration:
- All existing tables: unchanged (0 rows preserved)
- New tables: created empty
- Integrity check: ok

`init_db()` was run twice to verify idempotency — no errors, no data loss.

---

## Tests

### Phase 7.24.1 Tests (35)

| Category | Tests |
|----------|-------|
| Schema | 5 (table existence, columns) |
| Indexes | 3 (production DB indexes) |
| Ingestion log CRUD | 5 (create, update, success, failure, optional fields, metadata) |
| Data completeness CRUD | 4 (create, update, unique constraint, data types) |
| Checkpoint CRUD | 5 (create, update, resume, unique constraint, pipelines) |
| Persistence | 1 (cross-session visibility) |
| init_db safety | 3 (idempotency, data preservation, table creation) |
| Existing data protection | 1 (raw data unchanged) |
| Secret protection | 2 (no token fields, no secrets in metadata) |
| Production DB | 3 (tables exist, raw tables unmodified, integrity) |
| Workflow simulation | 2 (full workflow, failure and retry) |

All 35 tests pass.

### Regression Results

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.1 tests | 35 | All pass |
| Full backend | 1,862 | All pass |
| Full frontend | 1,357 | All pass |

---

## Protected Files

| Category | Modified? |
|----------|-----------|
| Frontend | NO |
| GEX calculations | NO |
| IV analytics | NO |
| Research engine | NO |
| OAuth/authentication | NO |
| Broker integration | NO |
| Paper trading | NO |
| Greeks engine | NO |
| Raw candle data | NO |
| Contract metadata logic | NO |

---

## Known Limitations

1. **Timestamp convention not yet standardized** — NIFTY candles are IST, option candles are UTC. This will be addressed in a future Phase 7.24.x.
2. **`greeks_checkpoint` and `ingestion_checkpoint` coexist** — no migration of existing Greek checkpoint data. Both tables serve their respective purposes.
3. **No automated backup yet** — will be implemented in Phase 7.24.9.

---

## Upstox API Calls

```
0
```

---

## Acceptance

```
PHASE 7.24.1 ACCEPTANCE: PASS
```

---

## Next Phase

Phase 7.24.2 will implement the centralized Upstox API client with:
- Access Token handling
- Retry/backoff
- 401 handling
- 429 handling
- Timeout handling
- Rate limiting
- Structured API metrics
