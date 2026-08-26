# Phase 7.24.5 — Unified Historical Backfill Orchestrator

## Status: PASS

## Objective

Build a single, reliable, resumable CLI entry point for all historical data
ingestion from Upstox into the local database.

## Files Created

| File | Purpose |
|------|---------|
| `app/services/backfill_orchestrator.py` | Core orchestrator with checkpoint/resume, dry-run, one-instrument-at-a-time |
| `run_backfill.py` | CLI entry point — works without FastAPI |
| `tests/test_phase724_5_backfill_orchestrator.py` | 33 comprehensive tests |
| `docs/PHASE_7_24_5_UNIFIED_BACKFILL_ORCHESTRATOR.md` | This document |

## Files Modified

None.

## Architecture

```
CLI (run_backfill.py)
      │
      ▼
BackfillOrchestrator
      │
┌─────┴─────┐
▼           ▼
UpstoxClient  Local Database
│               │
▼               ▼
Upstox API    contract_specs
              nifty_candles
              option_candles
              ingestion_log
              ingestion_checkpoint
              data_completeness
```

### Key Design Decisions

1. **CLI-first**: The orchestrator is invoked via `python run_backfill.py`.
   It is **never** called automatically on server startup, `init_db()`, restart,
   or code reload.

2. **Local-first**: Before requesting data from Upstox, the orchestrator checks
   the database. Only missing data is fetched.

3. **One instrument at a time**: Option candle processing handles each
   instrument independently with its own checkpoint, transaction boundary,
   and error handling.

4. **Raw data immutable**: OHLCV/OI values are never overwritten by the
   orchestrator. Upserts only occur for genuinely new data.

5. **No Greeks**: Greek reconstruction is a separate pipeline (Phase 7.23C).

## CLI Commands

```bash
# Show current database status
python run_backfill.py --status

# Dry run — see plan without API calls
python run_backfill.py --dry-run --all

# Backfill contract metadata only
python run_backfill.py --contracts

# Backfill NIFTY index candles only
python run_backfill.py --index

# Backfill option candles only
python run_backfill.py --options

# Full backfill
python run_backfill.py --all

# Specific expiry
python run_backfill.py --options --expiry 2024-10-31

# Limit instruments
python run_backfill.py --options --limit 50

# Force re-download
python run_backfill.py --all --force
```

## Token Bridge

The `TokenBridge` class connects two token sources:

1. **Persistent cache** (`UpstoxTokenManager` — Phase 7.24.3): CLI tools
   authenticate once, then reuse the cached token across restarts.

2. **In-memory store** (`token_store`): If the server is running and the
   user has an active session, the CLI can use that token via `--session-id`.

This allows the CLI to work both with and without a running FastAPI server.

## Three-Stage Pipeline

### Stage 1: Contract Metadata

- Discovers available expired expiries via `get_expiries()`
- For each expiry, fetches contract metadata via `get_contracts()`
- Upserts into `contract_specs` (idempotent)
- Rate-limited: 0.2s between requests

### Stage 2: NIFTY Index Candles

- Generates 28-day chunks covering the requested date range
- Skips chunks that already have data in the database
- Fetches via `get_historical_candles()` (V3 API)
- Normalizes to naive IST (Phase 7.24.4 convention)
- Persists via `record_candles()` (idempotent upsert)

### Stage 3: Option Candles

- Reads instruments from `contract_specs`
- Skips instruments that already have candle data
- Processes one instrument at a time
- Each instrument: independent checkpoint, transaction, error handling
- Fetches via `get_expired_historical_candles()` (V2 API)
- Normalizes to naive IST
- Persists via `record_option_candles()` (idempotent upsert)

## Checkpoint / Resume

Every option instrument gets an `ingestion_checkpoint` record:

| Field | Value |
|-------|-------|
| pipeline | `backfill_options` |
| instrument_key | `NSE_FO|...` |
| status | `RUNNING` → `COMPLETED` / `FAILED` |
| run_id | unique per invocation |

On restart, instruments with `COMPLETED` status are skipped.

## Idempotency

Running the same backfill twice:
- **Contracts**: no duplicates (upsert via unique constraint)
- **NIFTY candles**: chunks with existing data are skipped
- **Option candles**: instruments with existing data are skipped
- **Checkpoints**: updated in place (no duplicates)

## Ingestion Logging

Every stage writes to `ingestion_log`:

| Field | Content |
|-------|---------|
| run_id | unique per invocation |
| operation | `contract_metadata` / `nifty_candles` / `option_candles` |
| status | `SUCCESS` / `PARTIAL` / `FAILED` / `DRY_RUN` |
| api_calls | number of Upstox requests |
| rows_fetched | candles/contracts received |
| rows_inserted | new rows persisted |
| rows_skipped | already-existing rows |

## Dry-Run Behavior

`--dry-run` mode:
- Inspects database for current state
- Calculates missing data
- Displays planned API work
- Makes **zero** API calls
- Modifies **zero** database rows

## Security

- Access tokens are never logged, printed, or stored in the database
- Ingestion logs never contain tokens
- Checkpoints never contain tokens
- `TokenBridge` only provides the token to `UpstoxClient`

## Test Results

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.5 backfill orchestrator | 33 | All pass |
| Phase 7.24.4 timezone standardization | 42 | All pass |
| Phase 7.24.3 token manager | 50 | 49 pass, 1 pre-existing failure |
| Phase 7.24.2 upstox client | 50 | All pass |
| Phase 7.24.1 pipeline foundation | 35 | All pass |
| Full backend | 2,037 | 2,036 pass, 1 pre-existing failure |
| Full frontend | 1,357 | All pass |

### Pre-existing failure

`test_phase724_3_token_manager.py::TestSaveLoad::test_no_expiry_defaults_to_expiring_soon`
— timezone-dependent test that fails after 18:30 UTC. Not caused by Phase 7.24.5.

## Protected Files — Scope Audit

The following were **NOT modified** by Phase 7.24.5:

- Frontend
- GEX calculations
- IV calculations
- Greeks mathematics
- Research engine
- OAuth/authentication flow
- Trading/order execution
- Database schema
- Existing raw market data

## No Large Historical Download

This phase implements the architecture only. No large-scale historical
data download was performed.

## Real Upstox API Calls

**0** — all tests use mocked HTTP responses.

## Historical Data Downloaded

**0** — no live data ingestion during this phase.

## Acceptance

**PHASE 7.24.5 ACCEPTANCE: PASS**
