# Phase 7.24 — Permanent Historical + Daily Market Data Pipeline Architecture

## Status: DESIGN (no implementation)

---

## 1. Current Architecture Audit

### 1.1 Database Layer

| Component | Current State | Assessment |
|-----------|--------------|------------|
| Engine | `app/db.py` → `create_engine` with WAL mode | WORKING |
| Path resolution | `_DEFAULT_DB_PATH` = `backend/paper_journal.db` (absolute, from `__file__`) | WORKING |
| `init_db()` | `Base.metadata.create_all` + `ensure_column` migrations | SAFE (no data loss) |
| Health check | `check_database_health()` in `db.py` | EXISTS |
| Session factory | `SessionLocal = sessionmaker(bind=engine)` | WORKING |
| Backup | Manual `shutil.copy2` in Phase 7.23C CLI | FRAGILE |
| WAL mode | Set via `@event.listens_for(eng, "connect")` | WORKING |

**Tables:**

| Table | Purpose | Mutable? |
|-------|---------|----------|
| `contract_specs` | Historical contract metadata | Immutability enforced by `upsert_contract_spec` |
| `nifty_candles` | NIFTY index OHLCV candles | Immutable after insert |
| `option_candles` | Option/future contract OHLCV candles | Immutable after insert |
| `option_greeks` | Derived Greeks (IV, Delta, Gamma, Vega, Theta) | Regenerable from raw data |
| `greeks_checkpoint` | Temporary Phase 7.23C checkpoint | Temporary (should be removed after consolidation) |

### 1.2 Data Ingestion Pipeline

| Pipeline | Service Module | CLI Tool | Status |
|----------|---------------|----------|--------|
| Contract metadata | `contract_metadata.py` | `contract_metadata_backfill.py` | EXISTS |
| NIFTY candles | `nifty_candles.py` | (inline in `phase723b_endpoint.py`) | FRAGMENTED |
| Option candles | `option_candles.py` | `option_candle_backfill.py` | EXISTS |
| Historical Greeks | `historical_greeks.py` | `run_greeks_pilot.py` | EXISTS |
| Strike selection | `strike_selection.py` | (inline) | EXISTS |

**Key problem:** No unified ingestion orchestrator. Each pipeline is standalone.

### 1.3 Authentication & Token Handling

| Component | Implementation | Limitation |
|-----------|---------------|------------|
| Token store | `token_store.py` → in-memory `_state` dict | Lost on server restart |
| OAuth flow | `auth.py` → `/auth/login` → `/auth/callback` | WORKING |
| Token lifetime | ~1 day (expires 3:30 AM IST) | Requires daily re-auth |
| CLI access to token | Requires session_id from HTTP | No CLI-native auth |
| Token persistence | None | By design (single-user MVP) |

**Critical:** CLI tools (backfill, Greeks) cannot authenticate independently. They require a running server with an active session.

### 1.4 Timezone Architecture

| Component | Stored As | Convention |
|-----------|----------|------------|
| `nifty_candles.open_time` | Naive IST | e.g. `2026-07-28 15:27:00` = 15:27 IST |
| `option_candles.open_time` | Naive UTC | e.g. `2026-07-28 09:57:00` = 15:27 IST |
| `option_greeks.open_time` | Naive UTC | Matches option_candles |
| Upstox V3 API response | IST timestamps | e.g. `2026-07-28T15:27:00+05:30` |
| Upstox V2 expired API | IST timestamps | e.g. `2026-07-28T15:27:00+05:30` |
| `normalize_candle_timestamp()` | IST → naive UTC | Used by option_candles ingestion |
| `record_candles()` (NIFTY) | IST string → naive IST | Does NOT convert to UTC |

**Root cause of past failures:** The two candle tables store timestamps in different timezone conventions. This required manual IST conversion in the Greeks engine (`_calculate_single` method).

### 1.5 Windows/SQLite Safety

| Issue | Status | Details |
|-------|--------|---------|
| WAL mode | FIXED (Phase 7.23B) | Crash-safe for normal process termination |
| uvicorn --reload data loss | KNOWN BUG | Editing any imported file triggers reload, which kills WAL data |
| Deterministic path | FIXED (Phase 7.21) | Absolute path from `__file__` |
| `init_db()` safety | VERIFIED SAFE | Only `create_all` + `ensure_column` (no deletes) |
| Multiple DB files | PREVENTED | Single deterministic path |

### 1.6 Existing Tools

| Tool | Location | Purpose | Server Required? |
|------|----------|---------|-----------------|
| `run_greeks_pilot.py` | `backend/` | Greeks reconstruction CLI | NO |
| `option_candle_backfill.py` | `app/tools/` | Option candle backfill CLI | YES (token) |
| `contract_metadata_backfill.py` | `app/tools/` | Contract metadata backfill | YES (token) |
| `candle_backfill.py` | `app/tools/` | NIFTY candle backfill | YES (token) |
| `live_verification.py` | `app/tools/` | Phase 7.9 verification | YES (token) |
| `expired_candle_poc.py` | `app/tools/` | Phase 7.11 POC | YES (token) |

---

## 2. Problems Found (Verified)

### P1 — TIMEZONE INCONSISTENCY (CRITICAL)

**Root cause:** `nifty_candles` stores timestamps as naive IST, while `option_candles` converts IST to UTC before storage.

**Impact:**
- Greeks engine requires manual IST conversion in `_calculate_single`
- Spot alignment fails if conversion is forgotten
- Future analytics will face the same alignment issue

**Fix required:** Establish ONE canonical timezone for all candle tables.

### P2 — NO CENTRALIZED API CLIENT

**Root cause:** Each service function creates its own `httpx.AsyncClient()` and handles errors independently.

**Impact:**
- No unified retry/backoff logic
- No rate-limit tracking across endpoints
- No request counting or logging
- Error handling duplicated everywhere

### P3 — TOKEN NOT AVAILABLE TO CLI TOOLS

**Root cause:** Token is stored in-memory on the FastAPI server process. CLI tools run in separate processes.

**Impact:**
- Backfill tools require a running server
- Long-running backfills depend on server uptime
- Cannot run overnight backfills without keeping server alive
- Token expiry stops all CLI operations

### P4 — NO INGESTION STATUS TRACKING

**Root cause:** No database table tracks ingestion progress, completeness, or failures.

**Impact:**
- Cannot determine data completeness without querying raw tables
- No structured ingestion logs
- Cannot distinguish "not attempted" from "attempted and failed"
- No observability into ingestion health

### P5 — FRAGMENTED INGESTION SCRIPTS

**Root cause:** Each data type has its own backfill script with different patterns.

**Impact:**
- Inconsistent error handling
- Duplicate retry logic
- No unified checkpoint mechanism
- Hard to add new data types

### P6 — NO AUTOMATED BACKUP

**Root cause:** Backup is manual (`shutil.copy2` in CLI tool).

**Impact:**
- File copy while SQLite is writing may be unsafe
- No backup rotation
- No backup verification
- No backup before destructive operations

### P7 — NO DAILY INGESTION PIPELINE

**Root cause:** Only historical backfill exists. No mechanism for daily incremental updates.

**Impact:**
- Must manually re-run full backfill each day
- No gap detection
- No completeness verification
- Cannot grow the database incrementally

---

## 3. Proposed Architecture

### 3.1 Core Principle

```
ONE-TIME HISTORICAL ACQUISITION
        ↓
  LOCAL DATABASE (Source of Truth)
        ↓
  ┌─────┴──────┐
  ↓            ↓
DAILY        GREEKS /
INGESTION    GEX / IV
  ↓            ↓
  └─────┬──────┘
        ↓
    ANALYTICS
```

### 3.2 Data Flow Diagram

```
                 UPSTOX API
                     │
              ┌──────┴──────┐
              │   TOKEN     │
              │  MANAGER    │
              └──────┬──────┘
                     │
         ┌───────────┼───────────┐
         ↓           ↓           ↓
    ┌─────────┐ ┌─────────┐ ┌─────────┐
    │CONTRACT │ │ NIFTY   │ │ OPTION  │
    │METADATA │ │ CANDLES │ │ CANDLES │
    │INGESTION│ │INGESTION│ │INGESTION│
    └────┬────┘ └────┬────┘ └────┬────┘
         │           │           │
         └───────────┼───────────┘
                     ↓
         ┌───────────────────────┐
         │    LOCAL DATABASE     │
         │    (Source of Truth)  │
         │                       │
         │  contract_specs       │
         │  nifty_candles        │
         │  option_candles       │
         │  ingestion_log        │
         │  data_completeness    │
         └───────────┬───────────┘
                     │
              ┌──────┴──────┐
              │   GREEKS    │
              │   ENGINE    │
              └──────┬──────┘
                     ↓
         ┌───────────────────────┐
         │  option_greeks        │
         │  (derived, regenerable)│
         └───────────────────────┘
```

### 3.3 Database Flow Diagram

```
RAW DATA (Immutable)
┌─────────────────────────────┐
│  contract_specs             │ ← from Upstox expired contracts API
│  nifty_candles              │ ← from Upstox V3 historical candles
│  option_candles             │ ← from Upstox V2 expired candles
└──────────────┬──────────────┘
               │
          [read-only]
               │
               ↓
DERIVED DATA (Regenerable)
┌─────────────────────────────┐
│  option_greeks              │ ← from historical_greeks.py
└──────────────┬──────────────┘
               │
          [read-only]
               │
               ↓
ANALYTICS (Future)
┌─────────────────────────────┐
│  GEX / IV / Research        │
└─────────────────────────────┘

OPERATIONAL DATA
┌─────────────────────────────┐
│  ingestion_log              │ ← tracks all ingestion operations
│  data_completeness          │ ← tracks per-instrument/session status
│  greeks_checkpoint          │ ← tracks Greek reconstruction progress
└─────────────────────────────┘
```

---

## 4. Proposed Database Additions

### 4.1 `ingestion_log` Table

Tracks every data ingestion operation for observability.

```sql
CREATE TABLE ingestion_log (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,           -- unique per ingestion run
    operation TEXT NOT NULL,        -- 'contract_metadata' | 'nifty_candles' | 'option_candles'
    instrument_key TEXT,            -- specific instrument (nullable for batch ops)
    expiry_date TEXT,               -- specific expiry (nullable)
    session_date TEXT,              -- trading session date (nullable)
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,           -- 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED'
    api_calls INTEGER DEFAULT 0,
    rows_fetched INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    error_category TEXT,            -- 'AUTH_EXPIRED' | 'RATE_LIMIT' | 'API_ERROR' | 'NETWORK' | null
    error_message TEXT,
    metadata TEXT                   -- JSON blob for additional context
);
```

### 4.2 `data_completeness` Table

Tracks per-instrument/session data completeness.

```sql
CREATE TABLE data_completeness (
    id INTEGER PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    session_date TEXT NOT NULL,     -- YYYY-MM-DD
    data_type TEXT NOT NULL,        -- 'option_candles' | 'nifty_candles'
    expected_count INTEGER,
    actual_count INTEGER,
    status TEXT NOT NULL,           -- 'COMPLETE' | 'PARTIAL' | 'MISSING' | 'UNAVAILABLE'
    last_verified_at TEXT,
    UNIQUE(instrument_key, session_date, data_type)
);
```

---

## 5. Historical Backfill Design

### 5.1 Unified Backfill CLI

Replace fragmented scripts with a single orchestrator:

```
backend/app/tools/backfill.py

Commands:
  --status              Show overall backfill status
  --discover            Discover what data is missing
  --backfill-contracts  Fetch missing contract metadata
  --backfill-nifty      Fetch missing NIFTY candles
  --backfill-options    Fetch missing option candles
  --backfill-all        Run all three in sequence
  --verify              Verify data completeness
  --backup              Create database backup
  --dry-run             Show what would be done
```

### 5.2 Backfill Flow

```
1. Backup database (safety)
2. Integrity check
3. Discover missing data:
   a. Which expiries are missing from contract_specs?
   b. Which trading sessions are missing from nifty_candles?
   c. Which instruments/sessions are missing from option_candles?
4. For each missing item:
   a. Check if data was previously attempted and failed
   b. Check if token is available
   c. Fetch from Upstox
   d. Normalize and validate
   e. Persist with idempotent upsert
   f. Record completeness
   g. Log ingestion operation
   h. Commit (per-instrument transaction)
   i. Checkpoint progress
5. Verify completeness
6. Report results
```

### 5.3 Local-First Rule

Before every API request:

```python
def needs_fetch(instrument_key: str, session_date: str) -> bool:
    """Check if data already exists locally."""
    existing = db.execute(
        select(func.count(OptionCandle.id))
        .where(OptionCandle.instrument_key == instrument_key)
        .where(func.date(OptionCandle.open_time) == session_date)
    ).scalar()
    return existing < expected_count
```

---

## 6. Daily Ingestion Design

### 6.1 Daily Workflow

```
End of trading day (after 15:40 IST):
  1. Authenticate (or verify existing token)
  2. Discover today's active contracts
  3. Store new contract metadata (if any)
  4. Fetch today's NIFTY candles (if not already complete)
  5. For each active contract:
     a. Check local completeness
     b. Fetch only missing candles
     c. Persist and commit
  6. Verify completeness
  7. Record ingestion status
```

### 6.2 Gap Detection

```python
def detect_gaps(instrument_key: str) -> list[dict]:
    """Find missing sessions for an instrument."""
    expected_sessions = get_trading_sessions(start_date, end_date)
    existing_sessions = get_existing_sessions(instrument_key)
    return [s for s in expected_sessions if s not in existing_sessions]
```

---

## 7. Access Token Design

### 7.1 Token Manager

Create `app/services/token_manager.py`:

```python
class TokenManager:
    """Manages Upstox access tokens with persistence."""
    
    def get_token(self) -> str | None:
        """Get current valid token. Returns None if expired/unavailable."""
        
    def set_token(self, token: str) -> None:
        """Store a new token."""
        
    def is_valid(self) -> bool:
        """Check if current token is still valid."""
        
    def request_cli_token(self) -> str:
        """For CLI tools: prompt user to authenticate via browser."""
```

### 7.2 Token Persistence

For CLI tools, persist the token to a local file (NOT in source control):

```
backend/.token_cache  (gitignored)
```

Format:
```json
{
  "access_token": "...",
  "obtained_at": "2026-08-24T23:00:00Z",
  "expires_at": "2026-08-25T03:30:00+05:30"
}
```

### 7.3 CLI Authentication Flow

```
1. Check .token_cache
2. If valid → use it
3. If expired/missing:
   a. Start temporary HTTP server on localhost
   b. Print URL for user to open in browser
   c. Wait for OAuth callback
   d. Store token in .token_cache
   e. Stop temporary server
4. Use token for API calls
```

---

## 8. API Client Design

### 8.1 Centralized Client

Create `app/services/upstox_client.py`:

```python
class UpstoxClient:
    """Centralized Upstox API client with retry, rate limiting, and logging."""
    
    def __init__(self, token: str):
        self.token = token
        self.request_count = 0
        self.retry_count = 0
        
    async def request(self, method: str, path: str, **kwargs) -> dict:
        """Make an API request with automatic retry and rate limiting."""
        
    def get_historical_candles(self, instrument_key, to_date, from_date=None):
        """Fetch historical candles with retry."""
        
    def get_expired_contracts(self, instrument_key, expiry_date):
        """Fetch expired contract metadata with retry."""
        
    def get_expired_candles(self, instrument_key, interval, to_date, from_date):
        """Fetch expired historical candles with retry."""
```

### 8.2 Retry/Backoff

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1.0,      # seconds
    "max_delay": 30.0,      # seconds
    "backoff_factor": 2.0,
    "retryable_status": [429, 500, 502, 503, 504],
    "rate_limit_delay": 1.0, # seconds after 429
}
```

### 8.3 Error Categories

```python
class ErrorCategory(Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"       # 401 → stop, re-auth
    RATE_LIMIT = "RATE_LIMIT"           # 429 → backoff
    API_ERROR = "API_ERROR"             # 4xx → log, skip
    NETWORK = "NETWORK"                 # timeout/connection → retry
    TRANSIENT = "TRANSIENT"             # 5xx → retry
    PERMANENT = "PERMANENT"             # 404, 400 → record, skip
```

---

## 9. Checkpoint Design

### 9.1 Checkpoint Table

Replace the temporary `greeks_checkpoint` with a general-purpose `ingestion_checkpoint`:

```sql
CREATE TABLE ingestion_checkpoint (
    id INTEGER PRIMARY KEY,
    pipeline TEXT NOT NULL,          -- 'greeks' | 'backfill_contracts' | 'backfill_nifty' | 'backfill_options'
    instrument_key TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
    items_processed INTEGER DEFAULT 0,
    items_total INTEGER DEFAULT 0,
    error_message TEXT,
    run_id TEXT,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(pipeline, instrument_key)
);
```

### 9.2 Resume Logic

```python
def get_pending_items(pipeline: str) -> list[str]:
    """Get instruments that need processing."""
    return db.execute(text("""
        SELECT oc.instrument_key
        FROM option_candles oc
        WHERE NOT EXISTS (
            SELECT 1 FROM ingestion_checkpoint ic
            WHERE ic.pipeline = :pipeline
              AND ic.instrument_key = oc.instrument_key
              AND ic.status = 'COMPLETED'
        )
        GROUP BY oc.instrument_key
    """), {"pipeline": pipeline}).scalars().all()
```

---

## 10. Idempotency Design

### 10.1 Raw Data

All raw data tables use unique constraints:

| Table | Unique Key |
|-------|-----------|
| `contract_specs` | `instrument_key` |
| `nifty_candles` | `symbol, interval, open_time` |
| `option_candles` | `instrument_key, interval, open_time` |

Upsert operations (INSERT ON CONFLICT DO UPDATE) ensure idempotency.

### 10.2 Derived Data

| Table | Unique Key |
|-------|-----------|
| `option_greeks` | `instrument_key, interval, open_time, calc_version` |

Re-running with the same `calc_version` updates existing rows (idempotent).
Re-running with a new `calc_version` creates parallel rows (versioned).

### 10.3 Checkpoint

Checkpoint uses `INSERT OR REPLACE` (SQLite) / `ON CONFLICT DO UPDATE` (Postgres).

---

## 11. Timezone Policy

### 11.1 Canon: All candle timestamps stored as naive IST

**Decision:** Standardize all candle tables to store timestamps as naive IST datetimes.

**Rationale:**
- Upstox API returns IST timestamps
- Indian market hours are IST
- No DST complications
- Single convention eliminates alignment bugs

**Migration path:**
1. New option candles: store as naive IST (stop converting to UTC)
2. Existing option candles: bulk convert UTC → IST (one-time migration)
3. Greeks engine: remove the IST conversion workaround
4. Display layer: no conversion needed (already IST)

### 11.2 Timestamp Convention

```python
# At ingestion boundary:
api_timestamp = "2026-07-28T15:27:00+05:30"  # Upstox returns IST
naive_ist = datetime(2026, 7, 28, 15, 27)     # Strip timezone, store as IST

# At display boundary:
# No conversion needed — already IST
display_time = naive_ist.strftime("%H:%M IST")
```

### 11.3 Post-Close Handling

```python
# Option candles after 15:27 IST
option_time = datetime(2026, 7, 28, 15, 35)  # 15:35 IST (naive)

# NIFTY close candle
nifty_close_time = datetime(2026, 7, 28, 15, 27)  # 15:27 IST (naive)

# Alignment: find latest NIFTY candle <= option time
# Both in same timezone → direct comparison works
```

---

## 12. Data Completeness Model

### 12.1 Statuses

```python
class CompletenessStatus(Enum):
    EXPECTED = "EXPECTED"       # Data should exist but hasn't been fetched
    PARTIAL = "PARTIAL"         # Some candles present, some missing
    COMPLETE = "COMPLETE"       # All expected candles present
    MISSING = "MISSING"         # Expected but no data found
    UNAVAILABLE = "UNAVAILABLE" # API returned empty/error
    FAILED = "FAILED"           # Attempted but failed
```

### 12.2 Expected Candle Count

For NIFTY (3-minute, 09:15-15:27 IST):
```
126 candles per session (21 trading hours × 20 candles/hour... 
Actually: 09:15 to 15:27 = 6h12m = 372 minutes / 3 = 124 candles + 1 = 125 candles
```

For options (3-minute, 09:15-15:39 IST):
```
129 candles per session (09:15 to 15:39 = 6h24m = 384 minutes / 3 = 128 + 1 = 129 candles)
```

### 12.3 Completeness Check

```python
def check_completeness(instrument_key: str, session_date: str) -> dict:
    """Check data completeness for one instrument/session."""
    expected = expected_candle_count(instrument_key, session_date)
    actual = count_existing_candles(instrument_key, session_date)
    
    if actual == 0:
        status = "MISSING"
    elif actual >= expected:
        status = "COMPLETE"
    else:
        status = "PARTIAL"
    
    return {
        "instrument_key": instrument_key,
        "session_date": session_date,
        "expected": expected,
        "actual": actual,
        "status": status,
    }
```

---

## 13. Backup & Recovery Strategy

### 13.1 Backup Before Operations

Before any large ingestion:
```python
def safe_backup(db_path: str) -> str:
    """Create a safe backup using SQLite backup API."""
    import sqlite3
    backup_path = f"{db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Use SQLite backup API (safe even during writes)
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(backup_path)
    source.backup(dest)
    dest.close()
    source.close()
    
    # Verify
    verify_backup(backup_path)
    return backup_path
```

### 13.2 Recovery Procedures

| Scenario | Recovery |
|----------|----------|
| Token expired | Re-authenticate via OAuth |
| Network failure | Resume from checkpoint |
| Process termination | Resume from checkpoint |
| Partial write | Idempotent upsert handles duplicates |
| Database corruption | Restore from backup |
| Accidental data loss | Restore from backup |

### 13.3 Backup Rotation

Keep last 5 backups, auto-delete older ones:
```python
def rotate_backups(db_dir: str, keep: int = 5):
    """Keep only the most recent N backups."""
    backups = sorted(glob(f"{db_dir}/*.backup.*"))
    for old in backups[:-keep]:
        os.remove(old)
```

---

## 14. Server Independence Strategy

### 14.1 CLI Tools

All ingestion tools must work WITHOUT a running server:

```
backend/app/tools/
    backfill.py              # Unified backfill orchestrator
    daily_ingestion.py       # Daily incremental ingestion
    greeks_reconstruction.py # Greek calculation from local data
    token_helper.py          # CLI authentication helper
```

### 14.2 Token for CLI

The `token_helper.py` provides:
```bash
# Check if token is available and valid
python -m app.tools.token_helper --check

# Authenticate (opens browser, waits for callback)
python -m app.tools.token_helper --auth

# Show token status (without exposing token)
python -m app.tools.token_helper --status
```

### 14.3 Web Server Role

The web server provides:
- OAuth login/callback endpoints
- Read-only status endpoints
- Live data endpoints (option chains, etc.)

The web server does NOT:
- Run long-running ingestion
- Manage historical data acquisition
- Calculate Greeks (that's the CLI tool's job)

---

## 15. Windows/SQLite Safety Strategy

### 15.1 Rules

1. **NEVER use `uvicorn --reload`** during data operations
2. **Always backup before large operations**
3. **Use SQLite backup API** instead of file copy
4. **Verify integrity** before and after operations
5. **Use WAL mode** (already implemented)
6. **One deterministic database path** (already implemented)
7. **`init_db()` never deletes data** (already verified)

### 15.2 Process Isolation

```
Historical backfill:
  python -m app.tools.backfill --backfill-all
  
  (separate process, no server, no uvicorn)

Daily ingestion:
  python -m app.tools.daily_ingestion
  
  (separate process, no server, no uvicorn)

Greeks reconstruction:
  python run_greeks_pilot.py --missing
  
  (separate process, no server, no uvicorn)
```

### 15.3 Safe Development Workflow

```
1. Make code changes
2. Run tests (pytest)
3. Start server WITHOUT --reload
4. Verify database integrity
5. Run any needed data operations
6. Stop server
```

---

## 16. Testing Strategy

### 16.1 Architecture Tests

| Test | Purpose |
|------|---------|
| `test_database_path_deterministic` | DB path resolves to same location regardless of CWD |
| `test_init_db_never_deletes` | `init_db()` does not truncate or delete any table |
| `test_wal_mode_active` | SQLite WAL journal mode is active |
| `test_upsert_idempotent` | Inserting same data twice creates no duplicates |
| `test_raw_data_immutable` | Greeks calculation does not modify option_candles |
| `test_timezone_consistency` | All candle timestamps are in the same convention |
| `test_post_close_alignment` | Post-close option candles use last NIFTY close |
| `test_checkpoint_resume` | Interrupted processing can resume from checkpoint |
| `test_failed_instrument_isolation` | Failed instrument does not block others |
| `test_backup_readable` | Backup file is valid SQLite and readable |
| `test_integrity_check` | PRAGMA integrity_check returns ok |

### 16.2 Ingestion Tests

| Test | Purpose |
|------|---------|
| `test_local_first_check` | Existing data is not re-fetched |
| `test_empty_response_handled` | API returning [] is not an error |
| `test_auth_failure_stops_safely` | 401 stops ingestion without data loss |
| `test_rate_limit_backoff` | 429 triggers backoff and retry |
| `test_instrument_failure_isolation` | One instrument failure doesn't corrupt others |
| `test_daily_ingestion_idempotent` | Re-running daily ingestion adds no duplicates |

### 16.3 Greeks Tests

| Test | Purpose |
|------|---------|
| `test_greeks_from_local_data` | Greeks engine makes zero API calls |
| `test_iv_round_trip` | Calculated IV reproduces market price |
| `test_ce_delta_positive` | CE delta is positive |
| `test_pe_delta_negative` | PE delta is negative |
| `test_gamma_non_negative` | Gamma is non-negative |
| `test_spot_alignment` | NIFTY spot correctly aligned to option timestamp |
| `test_greeks_persist_after_restart` | Greeks survive server restart |
| `test_greeks_idempotent` | Re-running creates no duplicates |

---

## 17. Performance Strategy

### 17.1 Baseline (Phase 7.23C)

| Metric | Value |
|--------|-------|
| Per instrument | ~0.4s |
| Per candle | ~0.3ms |
| Total (466 instruments) | ~200s |
| Total candles | 539,195 |

### 17.2 Optimization Targets

| Optimization | Expected Improvement |
|-------------|---------------------|
| Batch NIFTY queries | 20% faster |
| Connection pooling | 10% faster |
| Parallel instrument processing | 3x faster (with careful rate limiting) |
| Incremental daily ingestion | Only process new data |

### 17.3 Rate Limit Strategy

Upstox rate limits (approximate):
- 50 requests/second
- 500 requests/minute

Strategy:
```python
RATE_LIMIT = {
    "requests_per_second": 40,    # 80% of limit
    "requests_per_minute": 400,   # 80% of limit
    "backoff_base": 1.0,          # seconds
    "backoff_max": 30.0,          # seconds
}
```

---

## 18. Migration Strategy

### 18.1 Timezone Migration

Phase 1: New code stores all candles as naive IST
Phase 2: One-time migration of existing UTC option candles to IST
Phase 3: Remove IST conversion workarounds from Greeks engine

### 18.2 Checkpoint Migration

Phase 1: Create `ingestion_checkpoint` table
Phase 2: Migrate data from `greeks_checkpoint` if present
Phase 3: Drop `greeks_checkpoint` table

### 18.3 Tool Consolidation

Phase 1: Create unified `backfill.py` orchestrator
Phase 2: Deprecate individual backfill scripts
Phase 3: Remove deprecated scripts

---

## 19. Exact Files to Create/Modify

### 19.1 New Files

| File | Purpose |
|------|---------|
| `app/services/token_manager.py` | Token persistence and CLI auth |
| `app/services/upstox_client.py` | Centralized API client with retry |
| `app/services/data_completeness.py` | Completeness tracking |
| `app/tools/backfill.py` | Unified backfill orchestrator |
| `app/tools/daily_ingestion.py` | Daily incremental ingestion |
| `app/tools/token_helper.py` | CLI authentication helper |
| `tests/test_phase724_pipeline_architecture.py` | Architecture tests |

### 19.2 Modified Files

| File | Change |
|------|--------|
| `app/models.py` | Add `ingestion_log`, `data_completeness`, `ingestion_checkpoint` tables |
| `app/db.py` | Add SQLite backup helper, safety checks |
| `app/services/nifty_candles.py` | Update to store IST consistently |
| `app/services/option_candles.py` | Stop converting to UTC, store IST |
| `app/services/historical_greeks.py` | Remove IST conversion workaround |
| `app/services/upstox.py` | Refactor to use centralized client |
| `.gitignore` | Add `.token_cache` |

### 19.3 Protected Files

| Category | Files |
|----------|-------|
| Frontend | `frontend/` (entire directory) |
| GEX | `app/services/gex.py`, GEX research modules |
| IV | `app/services/iv_history.py`, IV analytics |
| Research | Research engine modules |
| Auth | `app/routers/auth.py` (OAuth flow) |
| Broker | `app/brokers/` (broker integration) |
| Paper Trading | `app/routers/paper.py`, `app/services/paper_execution.py` |
| Templates | `app/routers/templates.py` |

---

## 20. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Timezone migration breaks existing queries | Medium | High | Phase migration carefully, test exhaustively |
| Token persistence security | Low | Medium | Encrypt at rest, gitignore, never log |
| Rate limit exceeded during backfill | Medium | Low | Conservative limits, exponential backoff |
| SQLite performance with large datasets | Low | Medium | Already handling 500K+ rows efficiently |
| Backward compatibility with existing data | Medium | High | Migration scripts with rollback capability |

---

## 21. Acceptance Criteria

- [ ] Single deterministic database path
- [ ] `init_db()` never deletes data
- [ ] WAL mode active
- [ ] All candle timestamps in consistent timezone (IST)
- [ ] Centralized API client with retry/backoff
- [ ] Token persistence for CLI tools
- [ ] Unified backfill orchestrator
- [ ] Daily incremental ingestion
- [ ] Checkpoint/resume for all pipelines
- [ ] Idempotent operations
- [ ] Raw data immutability
- [ ] Data completeness tracking
- [ ] Ingestion logging
- [ ] Automated backup before operations
- [ ] CLI tools work without server
- [ ] Zero Upstox calls during Greeks calculation
- [ ] All regression tests pass
- [ ] No protected functionality modified

---

## 22. Recommended Implementation Sequence

| Phase | Description | Estimated Effort |
|-------|-------------|-----------------|
| 7.24.1 | Add new tables (ingestion_log, data_completeness, ingestion_checkpoint) | Small |
| 7.24.2 | Create centralized API client with retry/backoff | Medium |
| 7.24.3 | Create token manager with persistence | Medium |
| 7.24.4 | Standardize timezone to IST across all candle tables | Medium (migration) |
| 7.24.5 | Create unified backfill orchestrator | Large |
| 7.24.6 | Create daily incremental ingestion | Medium |
| 7.24.7 | Add data completeness tracking | Small |
| 7.24.8 | Add ingestion logging | Small |
| 7.24.9 | Add automated backup with SQLite backup API | Small |
| 7.24.10 | Create CLI token helper | Small |
| 7.24.11 | Write comprehensive tests | Medium |
| 7.24.12 | Remove deprecated/temporary code | Small |

---

## 23. Summary

This design establishes a permanent, reliable data pipeline where:

1. **Historical data is downloaded once** when genuinely required
2. **The local database is the source of truth** for all historical data
3. **Daily ingestion adds only new data** — never re-downloads existing data
4. **All calculations operate from local data** — no unnecessary API calls
5. **All operations are resumable** — interruption never loses progress
6. **All operations are idempotent** — re-running is always safe
7. **Raw data is immutable** — derived data can be regenerated
8. **CLI tools work independently** — no server dependency for data operations
9. **Observability is built-in** — ingestion status is always known
10. **Data safety is enforced** — backups, integrity checks, and recovery procedures
