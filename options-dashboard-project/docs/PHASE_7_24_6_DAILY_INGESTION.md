# Phase 7.24.6 — Daily Incremental Ingestion Pipeline

## Status: PASS

## Objective

Build a daily incremental ingestion pipeline that fetches only the data
that is missing after market close, completing the Phase 7.24 permanent
data pipeline architecture.

## Files Created

| File | Purpose |
|------|---------|
| `app/services/daily_ingestion.py` | Daily incremental ingestion pipeline service |
| `run_daily.py` | CLI entry point — works without FastAPI |
| `tests/test_phase724_6_daily_ingestion.py` | 26 comprehensive tests |
| `docs/PHASE_7_24_6_DAILY_INGESTION.md` | This document |

## Files Modified

None.

## Architecture

```
run_daily.py (or cron)
      │
      ▼
DailyIngestionPipeline
      │
┌─────┴─────┐
▼           ▼
UpstoxClient  Local Database
│               │
▼               ▼
Upstox API    nifty_candles (incremental)
              contract_specs (incremental)
              option_candles (incremental)
              ingestion_log
```

### Pipeline Stages

1. **NIFTY Candles** — Fetches only the last trading day's 3-minute candles
   if not already in the database. Checks existing data before API call.

2. **Contract Metadata** — Refreshes contract metadata for the 3 most
   recent expiries. Idempotent upsert ensures no duplicates.

3. **Option Candles** — Fetches candles only for instruments that are
   missing data for the target date. One instrument at a time.

### Safety Rules

- **CLI-only**: Never runs on server startup, `init_db()`, or code reload
- **Token validation**: Checks token before any API call
- **Weekend skip**: Skips non-trading days automatically
- **Market-hours warning**: Warns if run before 16:00 IST
- **Incremental**: Only fetches genuinely missing data
- **Idempotent**: Running twice produces zero duplicates

## CLI Commands

```bash
# Run daily ingestion for the last trading day
python run_daily.py

# Ingest for a specific date
python run_daily.py --date 2026-08-24

# Dry run — see plan without API calls
python run_daily.py --dry-run

# Skip specific stages
python run_daily.py --skip-nifty
python run_daily.py --skip-options
python run_daily.py --skip-contracts

# Show current status
python run_daily.py --status

# Verbose logging
python run_daily.py --verbose
```

## Cron / Task Scheduler Integration

### Linux (cron)

```bash
# Run at 16:30 IST (11:00 UTC) every weekday
30 11 * * 1-5 cd /path/to/backend && python run_daily.py >> /var/log/daily_ingestion.log 2>&1
```

### Windows (Task Scheduler)

```
Program: python
Arguments: run_daily.py
Working Directory: C:\path\to\backend
Trigger: Weekdays at 16:30 IST
```

## Trading Day Detection

- Weekdays (Mon–Fri) are considered trading days
- Indian market holidays are NOT checked (requires a holiday calendar)
- The pipeline skips weekends automatically
- The pipeline warns if run before 16:00 IST

## Incremental Strategy

| Data Type | Strategy |
|-----------|----------|
| NIFTY candles | Check if target day exists; skip if yes |
| Contract metadata | Refresh 3 most recent expiries (idempotent upsert) |
| Option candles | Check instruments for target day; skip those with data |

## Idempotency

Running the same daily ingestion twice:
- **NIFTY candles**: second run skips (day already has data)
- **Contracts**: upsert produces zero duplicates
- **Option candles**: instruments with data are skipped
- **Ingestion log**: new entries for each run

## Test Results

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.6 daily ingestion | 26 | All pass |
| Full backend | 2,063 | 2,062 pass (1 pre-existing) |
| Full frontend | 1,357 | All pass |

### Pre-existing failure

`test_phase724_3_token_manager.py::TestSaveLoad::test_no_expiry_defaults_to_expiring_soon`
— timezone-dependent test that fails after 18:30 UTC. Not caused by Phase 7.24.6.

## Protected Files — Scope Audit

The following were **NOT modified** by Phase 7.24.6:

- Frontend
- GEX calculations
- IV calculations
- Greeks mathematics
- Research engine
- OAuth/authentication flow
- Trading/order execution
- Database schema
- Existing raw market data

## Real Upstox API Calls

**0** — all tests use mocked HTTP responses.

## Acceptance

**PHASE 7.24.6 ACCEPTANCE: PASS**
