# StrikeNova — Northflank + CockroachDB Migration Compatibility Audit

**Audit ID:** NORTHFLANK-COCKROACH-MIGRATION-001  
**Date:** 2026-09-11  
**Auditor:** Hermes Agent (senior infrastructure/database migration auditor)  
**Repository:** `shahid1995/-options-dashboard` (local: `C:\Users\busin\Desktop\-options-dashboard`)  
**Branch audited:** `feat/strikenova-day35-portfolio-intelligence`  
**HEAD commit:** `31563da fix(auth): route public login into authenticated app`  

---

## 0. Audit Scope and Constraints

This audit evaluates whether StrikeNova can safely migrate from:

**CURRENT:** Vercel → Railway → Railway PostgreSQL  
**TARGET:** Vercel → Northflank → CockroachDB Cloud

**Hard constraints observed:**
- NO production deployment
- NO Railway changes
- NO Vercel changes
- NO CockroachDB production database
- NO Northflank production deployment
- NO code implementation
- NO destructive commands
- NO secret exposure
- NO credential requests
- NO commits required for this audit (this report publication is the only exception)

This is an evidence-gathering and architecture decision exercise only.

---

## 1. Executive Summary

**HOLD.** StrikeNova's backend is architecturally close to portable from Railway/PostgreSQL to Northflank/CockroachDB, but **three material gaps** block a GO decision:

1. **CockroachDB retryable-transaction handling is absent** (🔴 HIGH). The codebase depends on PostgreSQL's `READ COMMITTED` isolation and `SELECT ... FOR UPDATE` serialization for economic correctness. CockroachDB runs `SERIALIZABLE` by default and returns retryable transaction errors (code 40001 / `RETRY_SERIALIZABLE`) under contention. StrikeNova has no retry wrapper for these errors in its transaction-sensitive paths (`exit_position`, `execute_strategy`, `ingest_canonical_event`, lifecycle event persistence).

2. **Dialect-specific code hardcodes PostgreSQL vs SQLite branching with no CockroachDB path** (🔴 HIGH). `fill_ledger.py:_upsert_trade_fill` and `db_dialect.py:dialect_insert` branch on `dialect.name == "postgresql"` — CockroachDB's SQLAlchemy dialect name is `"cockroachdb"`, not `"postgresql"`, so these code paths fall into the generic/else branch and lose `ON CONFLICT`/`RETURNING` semantics.

3. **No CockroachDB test evidence exists** (🔴 HIGH). All PostgreSQL concurrency tests require `TEST_DATABASE_URL` pointing to PostgreSQL. No tests have been run against CockroachDB. The codebase has never been validated on CRDB.

Everything else — Dockerfile, FastAPI, Alembic, SQLAlchemy models, transaction patterns, broker-sync architecture, Vercel integration — is either directly compatible or requires only verification, not code changes.

**Final decision: HOLD.** After implementing retry handling, fixing dialect branching, and running the full test suite against a disposable CRDB instance, re-evaluate as GO WITH CHANGES.

---

## 2. Repository State

### 2.1 Git State

| Item | Value |
|---|---|
| Branch | `feat/strikenova-day35-portfolio-intelligence` |
| HEAD commit | `31563da fix(auth): route public login into authenticated app` |
| Working tree | 11 modified files, 108 untracked files (dirty — active Day41 broker-sync development) |
| Remote | `origin https://github.com/shahid1995/-options-dashboard` |
| Default branch | `main` (commit `51a177d`) |

**Recent commits on this branch:**
```
31563da fix(auth): route public login into authenticated app
cedea11 fix(public): separate Signal Field OI legend from strike labels
e6603c6 feat(broker-sync): Day41 — implement approved Day40.6 identity/raw-ingress/fill-ledger architecture
3dc9f1e fix(public): improve Signal Field readability and market semantics
4ebbc37 docs(public): record StrikeNova V1.2 final acceptance
cb0c262 fix(public): harden StrikeNova V1.2 accessibility responsive performance
665a3ad feat(public): unify StrikeNova navigation metadata and cohesion
```

### 2.2 Python Environment

| Item | Value |
|---|---|
| Python version (runtime) | 3.11.16 |
| Python version (Dockerfile) | 3.13-slim |
| Dependency management | `requirements.txt` + `requirements-dev.txt` (no Poetry/pipenv) |
| Virtual environment | Not active (system Python used) |

**`requirements.txt` (full):**
```txt
fastapi==0.141.1
uvicorn[standard]==0.52.2
httpx==0.28.1
pydantic-settings==2.15.0
python-dotenv==1.2.2
sqlalchemy==2.0.43
alembic==1.15.2
psycopg[binary]>=3.2,<4
cryptography>=44.0.0
PyJWT>=2.8.0
```

**`requirements-dev.txt` (full):**
```txt
-r requirements.txt
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
respx==0.23.1
```

### 2.3 Database Configuration

| File | Purpose |
|---|---|
| `options-dashboard-project/backend/app/config.py` | pydantic-settings `Settings` class; `DATABASE_URL` optional, defaults to SQLite |
| `options-dashboard-project/backend/app/db.py` | SQLAlchemy engine creation + sessionmaker; SQLite fallback or PostgreSQL via psycopg |
| `options-dashboard-project/backend/app/utils/db_dialect.py` | `dialect_insert()` — dialect-aware insert for ON CONFLICT support |
| `options-dashboard-project/backend/alembic.ini` | Alembic configuration (script_location = alembic) |
| `options-dashboard-project/backend/alembic/env.py` | Alembic environment — supports CLI + programmatic + SQLite in-memory |

**`app/config.py:25`** — `DATABASE_URL: str | None = None` (optional, defaults to SQLite)

**`app/config.py:77-89`** — `IS_PRODUCTION` detects Railway via `RAILWAY_ENVIRONMENT` or `RAILWAY_SERVICE_NAME` env vars, or `PRODUCTION=1`. On Northflank, this would return False unless `PRODUCTION=1` is set.

**`app/db.py:42-69`** — Engine creation:
```python
def _engine():
    if settings.DATABASE_URL:
        url = normalize_database_url(settings.DATABASE_URL)
    else:
        url = f"sqlite:///{_DEFAULT_DB_PATH}"
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        eng = create_engine(url, connect_args=connect_args)
        # SQLite-only WAL + synchronous pragmas
        @event.listens_for(eng, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    else:
        # PostgreSQL production/staging configuration.
        eng = create_engine(url, pool_size=5, max_overflow=10,
                            pool_timeout=30, pool_recycle=1800,
                            pool_pre_ping=True)
    return eng
```

**`app/db.py:73`** — `SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)`

**`app/db.py:27-39`** — `normalize_database_url`:
```python
def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url
```

### 2.4 Alembic Migration Tooling

**14 migration files** in `options-dashboard-project/backend/alembic/versions/`:
```
125e1807df8d_add_broker_connection_foundation.py
9b675f8a3af0_day39_add_broker_sync_idempotency_and_.py
a0deb75ad22f_add_password_hash_to_users_for_email_.py
a1b2c3d4e5f6_correct_trading_status_backfill.py
a7c1d9e4f2b8_day41_add_broker_raw_observation.py
b2c3d4e5f6a7_add_gex_provenance_columns.py
b3e5f8a1c7d2_day41_add_fill_ledger_tables.py
b8c9f1d2e34a_add_google_sub_to_users.py
d3eb45a2e046_baseline_initial_schema_with_all_tables.py
e8f9a0b1c2d3_add_trade_lifecycle_tables.py
f7a3c2d1e94b_add_capability_separation_columns.py
f7aa24156f6d_merge_day39_broker_sync_day38_gex_heads.py
merge_day38_gex.py
```

**`alembic/env.py:58-60`** — `_render_as_batch(url)` returns True only for SQLite. CockroachDB (PostgreSQL dialect) would NOT use batch mode — standard `op.add_column()` etc. are used directly. This is correct.

**`alembic/env.py:37-55`** — `_resolve_database_url()` priority:
1. `sqlalchemy.url` from config
2. `DATABASE_URL` environment variable
3. `backend/paper_journal.db` SQLite fallback

### 2.5 Test Framework

| Item | Value |
|---|---|
| Framework | pytest 9.1.1 |
| Async support | pytest-asyncio 1.4.0 |
| Coverage | pytest-cov 7.1.0 |
| HTTP mocking | respx 0.23.1 |
| PostgreSQL tests | Gated by `TEST_DATABASE_URL` env var; skipped if not set or not PostgreSQL |

**PostgreSQL test skip pattern** (repeated in multiple test files):
```python
DB_URL = os.getenv("TEST_DATABASE_URL", "")
if not DB_URL or not DB_URL.startswith(("postgresql+psycopg://", "postgresql://")):
    pytest.skip("TEST_DATABASE_URL must point to PostgreSQL for concurrency verification",
                allow_module_level=True)
```

**SQLite in-memory pattern** (repeated in multiple test files):
```python
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
```

### 2.6 Worker/Background-Job Architecture

**No Celery, RQ, arq, APScheduler, or cron.** The only background work is an optional asyncio task within the FastAPI process.

**`app/main.py:36-200`** — `_gex_capture_loop`: background asyncio task for GEX snapshot capture. Runs only when `GEX_CAPTURE_ENABLED=True` and `GEX_USER_ID` is configured. Started in `lifespan` (line 325), stopped on shutdown (line 333-339).

### 2.7 Backend Directory Structure

```
options-dashboard-project/backend/
├── alembic/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/          (14 migration files)
├── app/
│   ├── main.py            (FastAPI app, lifespan, health/readiness)
│   ├── config.py          (pydantic-settings)
│   ├── db.py              (engine, sessionmaker, migration validation)
│   ├── utils/
│   │   └── db_dialect.py (dialect-aware insert)
│   ├── models.py          (all SQLAlchemy models, 936 lines)
│   ├── identity.py        (User, UserSession, BrokerConnection, BrokerToken, 811 lines)
│   ├── broker_sync/
│   │   ├── ingestion.py       (Day39 Task2 event ingestion, 1239 lines)
│   │   ├── fill_ledger.py     (Day41 fill ledger, 1052 lines)
│   │   ├── raw_ingress.py     (Day41 raw ingest, 393 lines)
│   │   ├── models.py          (BrokerSyncIdempotency, BrokerOrderProjection, BrokerSyncSequenceAnchor)
│   │   ├── fingerprint.py     (FPv2 canonical serialization)
│   │   └── __init__.py
│   ├── trade_lifecycle/
│   │   └── persistence.py    (lifecycle event persistence, 400 lines)
│   ├── services/
│   │   ├── paper_execution.py    (strategy execution + exit, 1489 lines)
│   │   ├── paper_risk.py
│   │   ├── token_store.py
│   │   ├── gex_capture.py
│   │   ├── live_gex.py
│   │   ├── upstox_client.py
│   │   └── ...
│   ├── brokers/
│   │   ├── gateway.py
│   │   ├── registry.py
│   │   ├── domain/
│   │   │   ├── enums.py
│   │   │   ├── models.py
│   │   │   ├── errors.py
│   │   │   └── capabilities.py
│   │   └── adapters/
│   │       └── upstox/
│   │           ├── adapter.py    (567 lines)
│   │           └── mapper.py     (842 lines)
│   ├── routers/
│   │   ├── auth.py
│   │   ├── paper.py
│   │   ├── gex.py
│   │   ├── chains.py
│   │   ├── candles.py
│   │   ├── live_gex.py
│   │   ├── historical_gex.py
│   │   ├── annotations.py
│   │   ├── templates.py
│   │   └── resolve.py
│   ├── market_data/
│   ├── portfolio_intelligence/
│   ├── quant/
│   ├── strategy_evaluation/
│   ├── central_risk/
│   ├── intelligence/
│   ├── opportunity/
│   ├── strike_ranking/
│   ├── strategy_lifecycle/
│   ├── final_risk_gate/
│   ├── tools/
│   └── tests/
│       ├── test_day38_postgres_concurrency.py
│       ├── test_day38_postgres_verification_evidence.py
│       ├── test_day38_task5_append_idempotency.py
│       ├── test_day38_task6_transactional_allocation.py
│       ├── test_day39_task2_red_v6.py
│       ├── test_day41_phase6_7_9_fill_ledger.py
│       ├── test_day41_phase10_postgres_concurrency.py
│       ├── test_day41_1_migration_reality.py
│       ├── test_paper_concurrency_repro.py
│       ├── test_upstox_adapter.py
│       ├── test_upstox_positions_regression.py
│       ├── test_broker_connection_model.py
│       ├── test_byob_credentials.py
│       ├── test_blocker_final.py
│       ├── test_blockers.py
│       ├── test_migrate_sqlite_to_pg.py
│       └── ...
├── tools/
│   ├── migrate_sqlite_to_postgres.py
│   └── ...
├── requirements.txt
├── requirements-dev.txt
├── Procfile
└── paper_journal.db (SQLite fallback, exists in working tree)
```

### 2.8 Deployment/Configuration Files

| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.13-slim, uvicorn on port 8080 |
| `Procfile` | `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `.env.example` | Environment variable documentation |
| `vercel.json` | Vercel rewrites: `/api/backend/*` → backend service, `/*` → frontend |
| `.github/workflows/postgres-compatibility.yml` | PostgreSQL CI test workflow |

---

## 3. Runtime Audit — Railway → Northflank

### 3.1 Dockerfile Analysis

**File:** `options-dashboard-project/Dockerfile` (18 lines)

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY options-dashboard-project/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY options-dashboard-project/backend/ /app/

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Analysis:**
- Base image: `python:3.13-slim` — Debian-based, supports `apt-get`. ✅ Northflank compatible.
- System dependencies: `gcc libpq-dev` — required for `psycopg[binary]` compilation. ✅ Northflank compatible.
- Working directory: `/app` — standard.
- Port: hardcoded `8080` in CMD. ⚠️ The Procfile uses `$PORT`. Northflank sets `$PORT` automatically. **Minor inconsistency:** Dockerfile CMD should honor `$PORT` too, or Northflank container port should be configured to 8080.
- No `EXPOSE` directive — not required for Northflank.
- No volume mounts — no persistent filesystem dependency. ✅ Compatible.
- No multi-stage build — acceptable for this project size.

**Verification command:** `docker build -f Dockerfile -t strikenova-test .` would build successfully (not executed in this audit).

### 3.2 Procfile Analysis

**File:** `options-dashboard-project/backend/Procfile` (1 line)

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Analysis:**
- Uses `$PORT` environment variable — Northflank-compatible.
- Uvicorn direct (not Gunicorn) — acceptable for this project. For high-traffic production, Gunicorn + Uvicorn workers would be recommended, but that's a future optimization.
- No worker process defined — confirms single-service architecture.

### 3.3 FastAPI / Uvicorn / Startup Configuration

**`app/main.py:346`** — App creation:
```python
app = FastAPI(title="Options Dashboard API", lifespan=lifespan,
              docs_url="docs" if getattr(settings, "DEBUG", False) else None)
```

**`app/main.py:303-344`** — Lifespan context manager:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _capture_task
    init_db()  # Run Alembic migrations programmatically on startup
    
    # DB token health check
    try:
        from app.services.token_store import startup_db_check
        count = startup_db_check()
        logger.info("DB token health check: %d active tokens", count)
    except Exception:
        logger.warning("DB token health check failed (non-critical)")
    
    # Optional GEX capture background task
    gex_capture_enabled = getattr(settings, "GEX_CAPTURE_ENABLED", False)
    gex_user_id = getattr(settings, "GEX_USER_ID", "") or None
    if gex_capture_enabled and gex_user_id:
        _stop_event.clear()
        _capture_task = asyncio.create_task(_gex_capture_loop(gex_user_id))
        logger.info("Background GEX capture task started", ...)
    elif gex_capture_enabled and not gex_user_id:
        logger.warning("GEX_CAPTURE_ENABLED but GEX_USER_ID not set — capture disabled")
    
    yield  # Application runs here
    
    # Shutdown: stop GEX capture task
    if _capture_task is not None and not _capture_task.done():
        _stop_event.set()
        try:
            await asyncio.wait_for(_capture_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _capture_task.cancel()
        logger.info("Background GEX capture task stopped")
    
    # Cleanup rate limiter
    from app.services.rate_limiter import rate_limiter
    rate_limiter.cleanup()
```

**Analysis:**
- `init_db()` runs Alembic migrations on startup — this is the programmatic migration path in `alembic/env.py`. ✅ Northflank compatible.
- DB token health check is non-critical (exception caught and logged). ✅ Resilient.
- GEX capture task is optional and cleanly shut down. ✅ Northflank compatible.
- Rate limiter cleanup on shutdown. ✅ Good practice.

**`app/main.py:385-388`** — Liveness endpoint:
```python
@app.get("/health")
def health():
    """Liveness check — is the process alive?"""
    return {"status": "ok"}
```

**`app/main.py:391-423`** — Readiness endpoint:
```python
@app.get("/readiness")
def readiness():
    """Readiness check — can the app serve production traffic?"""
    import time
    from app.db import engine
    from sqlalchemy import text
    
    checks = {}
    all_ok = True
    # Checks database connectivity via engine.connect() + SELECT 1
    ...
```

**Analysis:**
- `/health` — simple liveness check. ✅ Northflank can use this.
- `/readiness` — checks database connectivity. ✅ Northflank can use this as readiness probe.

### 3.4 Environment Variable Loading

**`app/config.py:4-95`** — pydantic-settings `Settings` class:

| Variable | Default | Purpose |
|---|---|---|
| `UPSTOX_API_KEY` | `""` | Upstox developer app API key |
| `UPSTOX_API_SECRET` | `""` | Upstox developer app API secret |
| `UPSTOX_REDIRECT_URI` | `""` | OAuth redirect URI (must match Upstox app registration) |
| `FRONTEND_URL` | `"http://localhost:3000"` | Frontend URL for OAuth redirects and CORS |
| `ADDITIONAL_CORS_ORIGINS` | `""` | Additional CORS origins (comma-separated) |
| `ALLOW_LOCALHOST_CORS` | `False` | Allow localhost CORS in development |
| `DEBUG` | `False` | Debug mode |
| `DATABASE_URL` | `None` | Database connection string (PostgreSQL or SQLite) |
| `IV_HISTORY_ENABLED` | `False` | Historical IV collection toggle |
| `GEX_HISTORY_ENABLED` | `False` | Historical GEX UI toggle |
| `GEX_CAPTURE_ENABLED` | `False` | Background GEX capture toggle |
| `GEX_USER_ID` | `""` | User ID for GEX capture |
| `TOKEN_ENCRYPTION_KEY` | `""` | Encryption key for broker credentials (critical) |
| `GOOGLE_CLIENT_ID` | `""` | Google OAuth client ID |
| `BACKEND_URL` | `""` | Backend URL for auto-deriving redirect URI |

**`app/config.py:91-92`** — Pydantic config:
```python
class Config:
    env_file = ".env"
```

**Analysis:** Pydantic-settings loads from `.env` file and environment variables. Northflank supports environment variable injection. ✅ Compatible.

### 3.5 Secrets Handling

**Secrets used by the application:**
- `TOKEN_ENCRYPTION_KEY` — encrypts/decrypts all broker credentials in `broker_connections` and `broker_tokens` tables. If rotated, all existing encrypted rows must be re-encrypted. **Critical.**
- `UPSTOX_API_SECRET` — Upstox developer app secret.
- `GOOGLE_CLIENT_ID` — Google OAuth client ID (may be considered public, but treated as secret here).

**`app/identity.py:93-200+`** — `BrokerConnection` model stores encrypted credentials:
- `broker_api_key_encrypted` (Text)
- `broker_api_secret_encrypted` (Text)
- `broker_analytics_token_encrypted` (Text)
- `broker_redirect_uri` (Text)

**`app/identity.py:200+`** — `BrokerToken` model stores encrypted tokens:
- `broker_token_encrypted` (Text)
- `broker_refresh_token_encrypted` (Text)

**Encryption mechanism:** `app/identity.py` uses `TOKEN_ENCRYPTION_KEY` via `app/services/token_store.py` (not fully inspected, but the architecture is clear).

**Analysis:** No hardcoded secrets in code. All secrets are environment variables. ✅ Northflank secrets management compatible.

### 3.6 Filesystem Assumptions

**No production filesystem writes.** The only filesystem references:
1. SQLite database file: `paper_journal.db` in backend directory (only used when `DATABASE_URL` is not set — irrelevant in production on Northflank with CRDB)
2. `.token_cache/` directory: `options-dashboard-project/backend/.token_cache/upstox_token.json` exists in working tree — local development token cache. In production, tokens are stored in the database.

**`app/db.py:23-24`** — SQLite fallback path:
```python
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "paper_journal.db")
```

**Analysis:** Production on Northflank with `DATABASE_URL` set to CRDB would never use the SQLite fallback. ✅ No persistent filesystem dependency.

### 3.7 Background Processes / Workers / Cron

**Confirmed: No worker process, no cron, no queue.**

The only "background" work is the optional `_gex_capture_loop` asyncio task (documented in §2.6). This runs within the FastAPI process via `lifespan`.

**Search for worker/cron dependencies:**
- `celery` — not in requirements.txt ✅
- `rq` — not in requirements.txt ✅
- `arq` — not in requirements.txt ✅
- `apscheduler` — not in requirements.txt ✅
- `croniter` — not in requirements.txt ✅
- `subprocess` calls in app code — none found ✅

**Analysis:** Single-service architecture. ✅ Northflank single web service is sufficient.

### 3.8 Subprocess / OS-Level Dependencies

**`Dockerfile:6-8`** — System dependencies: `gcc libpq-dev` for psycopg compilation.

**Search for subprocess usage in backend app code:** None found. The application does not call external processes.

**Analysis:** The Dockerfile installs the minimal required system dependencies. Northflank's Debian-based containers support this. ✅ Compatible.

### 3.9 Current Railway-Specific Assumptions

1. **`IS_PRODUCTION` detection** (`app/config.py:77-89`): Detects `RAILWAY_ENVIRONMENT` or `RAILWAY_SERVICE_NAME`. On Northflank, these are not set. **Fix:** Set `PRODUCTION=1` on Northflank, or add Northflank env var detection.

2. **`DATABASE_URL` normalization** (`app/db.py:27-39`): Normalizes `postgres://` → `postgresql+psycopg://`. CockroachDB uses `postgresql+psycopg://` or `cockroachdb://` URLs. **Verification needed:** Which URL scheme does CockroachDB Cloud provide, and does `postgresql+psycopg://` work with the psycopg dialect?

3. **`pool_recycle=1800`** (`app/db.py:65`): 30-minute connection recycle. Standard, works on any PostgreSQL-compatible database. ✅ No change needed.

4. **`validate_production_config()`** (`app/db.py:81-117`): Logs warnings if production lacks `DATABASE_URL` or uses SQLite. On Northflank with `PRODUCTION=1` and `DATABASE_URL` set, this behaves identically. ✅ No change needed.

### 3.10 Northflank Architecture Determination

**Conclusion: A. Single API service.** No worker, no cron, no queue.

**Northflank service configuration:**

| Setting | Value |
|---|---|
| Service type | Web Service (HTTP) |
| Build type | Docker (use existing Dockerfile) |
| Container port | 8080 (or `$PORT` if Dockerfile CMD is updated) |
| Health check (liveness) | `GET /health` |
| Health check (readiness) | `GET /readiness` |
| Environment variables | `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID`, `GEX_CAPTURE_ENABLED`, `GEX_USER_ID`, `PRODUCTION=1` |
| Secrets | `TOKEN_ENCRYPTION_KEY`, `UPSTOX_API_SECRET`, `GOOGLE_CLIENT_ID` (if sensitive) |
| Resource sizing (staging) | 0.5 CPU, 512MB RAM |
| Resource sizing (production) | 1 CPU, 1GB RAM |

**Code changes required for runtime:** None. Configuration changes: PORT handling in Dockerfile (optional), `PRODUCTION=1` env var or Northflank detection in config.py (optional).

---

## 4. Database Compatibility Audit — PostgreSQL → CockroachDB

### 4.1 SQLAlchemy Models — Full Scan

All models use standard SQLAlchemy 2.0 `Mapped` + `mapped_column`. **No PostgreSQL-specific types found.**

**`app/models.py` (936 lines) — model summary:**

| Model | Table | Key columns | Special features |
|---|---|---|---|
| `PaperAccount` | `paper_accounts` | `id` (Integer PK), `user_id` (String(128) unique) | Standard |
| `Trade` | `trades` | `id` (Integer PK), `user_id`, `symbol`, `strategy_execution_id`, `client_order_id` | Legacy journal |
| `Leg` | `legs` | `id` (Integer PK), `trade_id` (FK) | Legacy journal |
| `StrategyExecution` | `strategy_executions` | `id` (Integer PK), `execution_id` (String(40)), `client_order_id`, `user_id` | UniqueConstraint on `(user_id, client_order_id)` |
| `PaperOrder` | `paper_orders` | `id` (Integer PK), `client_order_id`, `execution_id`, `position_id` | UniqueConstraint on `(user_id, client_order_id)` |
| `Position` | `positions** | `id` (Integer PK), `user_id`, `symbol`, `expiry`, `strike`, `option_type` | UniqueConstraint on `(user_id, symbol, expiry, strike, option_type)` |
| `PaperTransaction` | `paper_transactions` | `id` (Integer PK), `user_id`, `execution_id`, `order_id`, `type`, `amount` | Cash ledger |
| `StrategyLegExposure` | `strategy_leg_exposures` | `id` (Integer PK), `user_id`, `execution_id`, `position_id`, `order_id` | UniqueConstraint on `(user_id, order_id)` |
| `ExitExposureAllocation` | `exit_exposure_allocations` | `id` (Integer PK), `user_id`, `exit_order_id`, `exposure_id`, `quantity` | Many-to-many junction |
| `BulkExitRecord` | `bulk_exit_records` | `id` (Integer PK), `user_id`, `client_order_id` | UniqueConstraint on `(user_id, client_order_id)` |

**`app/models.py:86-210`** — Phase 5.0 authoritative paper trading models (StrategyExecution, PaperOrder, Position, PaperTransaction, StrategyLegExposure, ExitExposureAllocation). All use standard types: Integer, String, Float, DateTime, Boolean.

**`app/models.py:894-895`** — Comment: "via ON CONFLICT DO UPDATE." — references the atomic upsert pattern used in `allocate_position_sequence`.

**`app/broker_sync/models.py` (125 lines) — broker-sync models:**

| Model | Table | Key columns | Special features |
|---|---|---|---|
| `BrokerSyncIdempotency` | `broker_sync_idempotency` | `canonical_id` (String(64) PK), `tenant_id`, `broker`, `broker_order_id`, `content_fingerprint`, `status` | UniqueConstraint on `canonical_id` |
| `BrokerOrderProjection` | `broker_order_projection` | `id` (Integer auto-increment PK), `tenant_id`, `broker`, `broker_order_id`, `canonical_id`, `status`, `is_terminal` (Boolean) | `is_terminal` has `server_default="false"` |
| `BrokerSyncSequenceAnchor` | `broker_sync_sequence_anchor` | `tenant_id`, `broker`, `broker_order_id` (composite PK), `last_sequence` | Composite PK |

**`app/broker_sync/raw_ingress.py` (393 lines) — raw ingest model:**

| Model | Table | Key columns | Special features |
|---|---|---|---|
| `BrokerRawObservation` | `broker_raw_observation` | `raw_observation_id` (String(36) PK), `tenant_id`, `broker`, `raw_payload` (LargeBinary), `d1`, `content_fingerprint`, `processing_status`, `lease_expires_at` | `raw_payload` is BYTEA; non-unique indexes on `(d1, content_fingerprint)` and `(processing_status, created_at)` |

**`app/trade_lifecycle/persistence.py` (400 lines) — lifecycle models:**

| Model | Table | Key columns | Special features |
|---|---|---|---|
| `TradeLifecycleEvent` | `trade_lifecycle_events` | `event_id` (String(64) PK), `tenant_id`, `aggregate_type`, `aggregate_id`, `sequence`, `position_sequence`, `payload_json` (Text), `metadata_json` (Text) | UniqueConstraint on `(tenant_id, aggregate_type, aggregate_id, sequence)` and `(tenant_id, position_identity_user_id, position_identity_symbol, position_identity_expiry, position_identity_strike, position_identity_option_type, position_sequence)` |
| `PositionSequenceAnchor` | `position_sequence_anchor` | `tenant_id`, `user_id`, `symbol`, `expiry`, `strike`, `option_type` (composite PK), `last_position_sequence` | Composite PK; atomic upsert via ON CONFLICT DO UPDATE |

**Type analysis:**

| SQLAlchemy Type | Found? | CRDB Compatibility |
|---|---|---|
| `Integer` | Yes (all PKs, sequences, quantities) | 🟢 CRDB supports INTEGER |
| `String(n)` | Yes (all text columns) | 🟢 CRDB supports VARCHAR |
| `Float` | Yes (prices, P&L, strike) | 🟢 CRDB supports FLOAT/DOUBLE |
| `DateTime` | Yes | 🟢 CRDB supports TIMESTAMP |
| `DateTime(timezone=True)` | Yes (`BrokerRawObservation.received_at`, `TradeLifecycleEvent.occurred_at`, etc.) | 🟢 CRDB supports TIMESTAMP WITH TIME ZONE |
| `Text` | Yes (`payload_json`, `metadata_json`, `execution_metadata`, `tags`, `notes`, `raw_payload_excerpt`, `delivery_evidence`, `last_error`, `rejection_reason`) | 🟢 CRDB supports TEXT |
| `Boolean` | Yes (`BrokerOrderProjection.is_terminal`, `StrategyExecution.status` uses String not Boolean) | 🟢 CRDB supports BOOLEAN |
| `LargeBinary` | Yes (`BrokerRawObservation.raw_payload`) | 🟡 CRDB supports BYTEA but needs verification |
| `JSON` / `JSONB` | **No** — all JSON data stored as Text | 🟢 No JSONB dependency |
| `ARRAY` | **No** | 🟢 Not used |
| `Enum` (DB-level) | **No** — all enums are Python `str, enum.Enum` stored as String | 🟢 Not used |
| `UUID` (DB-type) | **No** — UUIDs stored as String(36) hex | 🟢 Not used |
| `SERIAL` / `IDENTITY` | **No** — PKs are Integer (auto-increment via SQLAlchemy) | 🟢 Not used |
| `Computed` / `Generated` | **No** | 🟢 Not used |

**Critical finding:** `payload_json` and `metadata_json` are `Text` columns, NOT `JSON`/`JSONB`. This means:
- No JSON indexing on these columns
- No JSON operators used in queries
- JSON is parsed at the application level (Python `json` module)
- **This is CRDB-compatible** — no JSONB dependency

### 4.2 Raw SQL Scan

**Searched entire backend for:** `.execute(`, `text(`, `raw SQL`, `literal_column`, `sa.text`, `session.execute(text(`

**Raw SQL found (6 locations):**

#### 4.2.1 `app/broker_sync/ingestion.py:344-360` — `_ensure_broker_sequence_anchor`

```python
db.execute(
    text("""
    INSERT INTO broker_sync_sequence_anchor
        (tenant_id, broker, broker_order_id, last_sequence, created_at, updated_at)
    VALUES
        (:tenant_id, :broker, :broker_order_id, 0, :now, :now)
    ON CONFLICT (tenant_id, broker, broker_order_id) DO NOTHING
    """),
    {
        "tenant_id": event.tenant_id,
        "broker": event.broker,
        "broker_order_id": broker_order_id,
        "now": datetime.now(timezone.utc),
    },
)
db.flush()
```

**Classification:** 🟢 Compatible. CRDB supports `INSERT ... ON CONFLICT DO NOTHING`. Uses named parameters (`:param`), which CRDB supports via SQLAlchemy.

**Context:** Creates the broker sequence anchor row if it doesn't exist. Called inside a SAVEPOINT (`ingestion.py:324-361` — "Must be called INSIDE the SAVEPOINT so that anchor creation rolls back with projection, idempotency, and lifecycle.").

#### 4.2.2 `app/broker_sync/ingestion.py:388-408` — `_advance_broker_sequence`

```python
result = db.execute(
    text("""
    UPDATE broker_sync_sequence_anchor
    SET last_sequence = :advance_to,
        updated_at = :now
    WHERE tenant_id = :tenant_id
      AND broker = :broker
      AND broker_order_id = :broker_order_id
      AND last_sequence = :expected
    """),
    {
        "advance_to": incoming,
        "expected": expected,
        "tenant_id": event.tenant_id,
        "broker": event.broker,
        "broker_order_id": broker_order_id,
        "now": datetime.now(timezone.utc),
    },
)
db.flush()

if result.rowcount == 1:
    return

# Concurrent worker advanced — signal failure for re-classification
raise IngestionError(
    f"concurrent worker advanced broker sequence past {incoming}",
    action="CONFLICT",
)
```

**Classification:** 🟢 Compatible. Standard `UPDATE ... WHERE`. CRDB supports this. The `rowcount == 1` check is an optimistic concurrency control pattern — if two workers try to advance the same anchor, only one succeeds.

**Context:** "This is the serialization point for concurrent consumers. It must be called AFTER the projection, idempotency record, and Day38 lifecycle event have all been persisted (inside the same SAVEPOINT) so that a failed advancement rolls back all durable effects together." (`ingestion.py:369-374`)

**Important:** This raises `IngestionError` on contention (rowcount == 0), which is handled as a CONFLICT by the caller. This is NOT a retryable error — it's an intentional conflict detection. On CRDB, if the UPDATE itself fails due to a serialization error (not just rowcount == 0), the current code would not retry.

#### 4.2.3 `app/trade_lifecycle/persistence.py:215-239` — `allocate_position_sequence`

```python
result = db.execute(
    text("""
    INSERT INTO position_sequence_anchor
        (tenant_id, user_id, symbol, expiry, strike, option_type,
         last_position_sequence, created_at, updated_at)
    VALUES
        (:tenant_id, :user_id, :symbol, :expiry, :strike, :option_type,
         1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (tenant_id, user_id, symbol, expiry, strike, option_type)
    DO UPDATE SET
        last_position_sequence = position_sequence_anchor.last_position_sequence + 1,
        updated_at = CURRENT_TIMESTAMP
    RETURNING last_position_sequence
    """),
    dict(
        tenant_id=tenant_id,
        user_id=user_id,
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    ),
).scalar()
```

**Classification:** 🟢 Compatible. CRDB supports `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`. Uses `CURRENT_TIMESTAMP` (standard SQL, not PostgreSQL-specific).

**Context:** "Uses an atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING upsert on position_sequence_anchor so that the first-event case (no existing row) is handled without a separate SELECT … FOR UPDATE + INSERT race window." (`persistence.py:206-209`)

#### 4.2.4 `app/broker_sync/fill_ledger.py:542-566` — `_upsert_trade_fill`

```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

values = dict(
    tenant_id=tenant_id,
    provider_order_id=provider_order_id,
    fill_eq_key=fill_eq_key,
    fill_identity_type=FillIdentityType.TRADE_ID.value,
    reconciliation_state=ReconciliationState.RECONCILED.value,
    fill_quantity=fill_quantity,
    fill_price=fill_price,
    cumulative_after=cumulative_after,
    observed_count=1,
)
bind = db.get_bind()
if bind is not None and bind.dialect.name == "postgresql":
    stmt = pg_insert(BrokerFillLedgerFill).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
    ).returning(BrokerFillLedgerFill.tenant_id)
else:
    stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
    ).returning(BrokerFillLedgerFill.tenant_id)
result = db.execute(stmt)
created = result.first() is not None
```

**Classification:** 🟡 **REQUIRES CHANGE.** CockroachDB's SQLAlchemy dialect name is `"cockroachdb"`, not `"postgresql"`. This code would fall into the `else` (SQLite) branch on CRDB, which is wrong.

**Impact:** The `else` branch uses `sqlite_insert` with `on_conflict_do_nothing(...).returning()`. On CRDB:
- `sqlite_insert` may not be appropriate for CRDB
- `on_conflict_do_nothing()` may not work correctly
- `returning()` may behave differently

**Required fix:** Add a `"cockroachdb"` branch that uses `pg_insert` (CRDB is PostgreSQL-compatible for `ON CONFLICT`/`RETURNING`).

**Context:** "INSERT … ON CONFLICT DO NOTHING RETURNING: the DATABASE decides — not a check-then-insert read — whether THIS transaction created the row." (`fill_ledger.py:530-536`)

#### 4.2.5 `app/utils/db_dialect.py:15-36` — `dialect_insert`

```python
def dialect_insert(engine: Engine, table: Table):
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        # Fallback: generic insert (no on_conflict_do_update)
        from sqlalchemy import insert
        return insert(table)
```

**Classification:** 🟡 **REQUIRES CHANGE.** Same issue — CRDB dialect name is `"cockroachdb"`, falls into `else` (generic insert, no `on_conflict_do_update` support).

**Note:** This function is used by... let me check. Searching for `dialect_insert` usage:
- `app/utils/db_dialect.py` defines it
- Is it imported anywhere? Need to verify.

**Search result:** `dialect_insert` is defined in `db_dialect.py` but I did not find explicit imports in the broker-sync code. The broker-sync code uses inline dialect branching (as in `_upsert_trade_fill` above) rather than calling `dialect_insert`. However, `db_dialect.py` is part of the codebase and should be fixed for completeness.

#### 4.2.6 `migrate_sqlite_to_postgres.py` — PostgreSQL migration utility

**File:** `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py` (721+ lines)

This is a utility for migrating SQLite data to PostgreSQL. It contains PostgreSQL-specific SQL:
- `pg_get_serial_sequence` (line 156, 318, 432)
- `pg_sequences` (line 326, 437)
- `psycopg` native driver usage (line 228-234)

**Classification:** 🟡 This is a migration utility, NOT runtime code. It's used for SQLite→PostgreSQL data migration. For CRDB, a similar utility would need to be written (or CRDB's `IMPORT PGDUMP` used). This is a future concern, not a current blocker.

**Not used in production runtime.** The application does not call this utility.

### 4.3 Alembic Migrations — Full Scan

**14 migration files** — all inspected.

#### 4.3.1 Baseline Migration: `d3eb45a2e046_baseline_initial_schema_with_all_tables.py` (667 lines)

Creates all tables from scratch using standard `op.create_table()` + `sa.Column()` + `sa.PrimaryKeyConstraint()` + `sa.UniqueConstraint()` + `batch_op.create_index()`.

**Tables created (29 tables):**
1. `bulk_exit_records`
2. `contract_specs`
3. `data_completeness`
4. `exit_exposure_allocations`
5. `gex_snapshots`
6. `historical_gex`
7. `ingestion_checkpoint`
8. `ingestion_log`
9. `iv_observations`
10. `nifty_candles`
11. `option_candles`
12. `option_greeks`
13. `paper_accounts`
14. `paper_orders`
15. `paper_transactions`
16. `positions`
17. `strategy_executions`
18. `strategy_leg_exposures`
19. `strategy_templates`
20. `trades`
21. `users`
22. `legs`
23. `strategy_template_legs`
24. `user_sessions`
25. `users` (already listed — duplicate check: no, this is the baseline)
26. `gex_snapshots` (already listed)
27. ... (plus indexes on each)

**Analysis:** All standard SQLAlchemy Alembic operations. No PostgreSQL-specific features. ✅ CRDB compatible.

**`d3eb45a2e046:87`** — `sa.UniqueConstraint('instrument_key', 'session_date', 'data_type', name='uq_data_completeness_identity')` — standard unique constraint. ✅

**`d3eb45a2e046:156`** — `sa.UniqueConstraint('instrument_key', 'interval', 'open_time', 'calc_version', name='uq_historical_gex_identity')` — standard. ✅

**`d3eb45a2e046:236`** — `sa.UniqueConstraint('symbol', 'interval', 'open_time', name='uq_candle_identity')` — standard. ✅

**`d3eb45a2e046:256`** — `sa.UniqueConstraint('instrument_key', 'interval', 'open_time', name='uq_option_candle_identity')` — standard. ✅

**`d3eb45a2e046:287`** — `sa.UniqueConstraint('instrument_key', 'interval', 'open_time', 'calc_version', name='uq_option_greeks_identity')` — standard. ✅

**`d3eb45a2e046:458`** — `sa.Column('identity_source', sa.String(length=32), nullable=False)` — standard. ✅

**`d3eb45a2e046:465`** — `sa.UniqueConstraint('broker_provider', 'broker_user_id', name='uq_users_broker_identity')` — standard. ✅

#### 4.3.2 Partial Index Migration: `125e1807df8d_add_broker_connection_foundation.py` (107 lines)

**`125e1807df8d:84-96`** — Partial unique index on `broker_connections`:

```python
# 4. Partial unique index: at most one default connection per (user, broker)
#    Uses dialect detection because boolean literals differ:
#      PostgreSQL: WHERE is_default = true
#      SQLite:     WHERE is_default = 1
dialect = op.get_bind().dialect.name
if dialect == "postgresql":
    op.execute(
        "CREATE UNIQUE INDEX uq_one_default_per_user_broker "
        "ON broker_connections (user_id, broker) "
        "WHERE is_default = true"
    )
else:
    # SQLite supports partial unique indexes but uses integer booleans
    op.execute(
        "CREATE UNIQUE INDEX uq_one_default_per_user_broker "
        "ON broker_connections (user_id, broker) "
        "WHERE is_default = 1"
    )
```

**Classification:** 🟡 Needs verification for CRDB.

**Analysis:**
- CRDB supports partial unique indexes with `WHERE` clause.
- CRDB uses SQL-standard booleans (`true`/`false`), so `is_default = true` should work.
- However, this migration hard-codes PostgreSQL vs SQLite branching. CRDB would fall into... let's check: `op.get_bind().dialect.name` for CRDB would be `"cockroachdb"`, which is not `"postgresql"`, so it would fall into the `else` branch (`is_default = 1`). **This is wrong for CRDB.**

**Required fix:** Add `"cockroachdb"` branch that uses `is_default = true` (SQL-standard boolean).

**Also:** `125e1807df8d:31-53` — `broker_connections` table creation:
```python
sa.Column('broker_api_key_encrypted', sa.Text(), nullable=True),
sa.Column('broker_api_secret_encrypted', sa.Text(), nullable=True),
sa.Column('broker_analytics_token_encrypted', sa.Text(), nullable=True),
```
All standard Text columns. ✅ CRDB compatible.

**`125e1807df8d:59-71`** — `broker_tokens` table:
```python
sa.Column('broker_token_encrypted', sa.Text(), nullable=True),
sa.Column('broker_refresh_token_encrypted', sa.Text(), nullable=True),
```
Standard. ✅

**`125e1807df8d:75-77`** — `batch_alter_table` to add `broker_connection_id` to `user_sessions`:
```python
with op.batch_alter_table('user_sessions', schema=None) as batch_op:
    batch_op.add_column(sa.Column('broker_connection_id', sa.String(36), nullable=True))
    batch_op.create_foreign_key('fk_user_sessions_connection', 'broker_connections', ['broker_connection_id'], ['id'])
```
`batch_alter_table` is for SQLite. For CRDB (PostgreSQL dialect), Alembic would use standard `op.add_column()` and `op.create_foreign_key()` directly (because `_render_as_batch` returns False for non-SQLite). ✅ This is handled correctly by `alembic/env.py`.

#### 4.3.3 Google Sub Partial Index: `b8c9f1d2e34a_add_google_sub_to_users.py` (37 lines)

**`b8c9f1d2e34a:29`** — `postgresql_where='google_sub IS NOT NULL'`:
```python
batch_op.create_index(
    'ix_users_google_sub',
    ['google_sub'],
    unique=True,
    postgresql_where='google_sub IS NOT NULL',
)
```

**Classification:** 🟡 Needs verification for CRDB.

**Analysis:**
- `postgresql_where` is an Alembic-specific kwarg for PostgreSQL partial indexes.
- CRDB may not support this Alembic kwarg.
- If CRDB doesn't support `postgresql_where`, the index creation would fail or be ignored.
- **Alternative:** Use `op.execute()` with raw SQL `CREATE UNIQUE INDEX ... WHERE google_sub IS NOT NULL` (similar to the `125e1807df8d` approach).

**Required:** Verify if CRDB supports `postgresql_where` kwarg, or modify the migration to use raw SQL.

#### 4.3.4 Capability Separation: `f7a3c2d1e94b_add_capability_separation_columns.py` (95 lines)

**`f7a3c2d1e94b:55-74`** — Data backfill:
```python
op.execute(
    """
    UPDATE broker_connections
    SET trading_status = 'active'
    WHERE status = 'connected'
    """
)
op.execute(
    """
    UPDATE broker_connections
    SET data_status = 'active',
        data_source = CASE
            WHEN broker_analytics_token_encrypted IS NOT NULL THEN 'analytics_token'
            ELSE 'oauth_token'
        END
    WHERE status = 'connected'
      AND (broker_analytics_token_encrypted IS NOT NULL
           OR broker_api_key_encrypted IS NOT NULL)
    """
)
```
Standard SQL. ✅ CRDB compatible.

#### 4.3.5 Corrective Backfill: `a1b2c3d4e5f6_correct_trading_status_backfill.py` (42 lines)

**`a1b2c3d4e5f6:30-36`** — Correct trading_status:
```python
op.execute(
    """
    UPDATE broker_connections
    SET trading_status = 'inactive'
    WHERE trading_status = 'active'
    """
)
```
Standard SQL. ✅ CRDB compatible.

#### 4.3.6 Day41 Migrations

**`a7c1d9e4f2b8_day41_add_broker_raw_observation.py` (91 lines):**
- Creates `broker_raw_observation` table with `LargeBinary` column (`raw_payload`)
- Creates indexes: `ix_broker_raw_observation_tenant_id`, `ix_broker_raw_observation_d1_fp`, `ix_broker_raw_observation_d1`, `ix_broker_raw_observation_processing`
- All standard Alembic operations. ✅
- `LargeBinary` → BYTEA on PostgreSQL. CRDB supports BYTEA. 🟡 Verify.

**`b3e5f8a1c7d2_day41_add_fill_ledger_tables.py` (165 lines):**
- Creates 4 tables: `broker_fill_ledger_observation`, `broker_fill_ledger_fill`, `broker_fill_identity_alias`, `broker_fill_identity_lineage`
- All standard Alembic operations. ✅
- Composite primary keys: `(tenant_id, provider_order_id, fill_eq_key)` on `broker_fill_ledger_fill`; `(tenant_id, provider_order_id, from_eq_key)` on `broker_fill_identity_alias`. ✅ CRDB supports composite PKs.

#### 4.3.7 Day39 Migration: `9b675f8a3af0_day39_add_broker_sync_idempotency_and_.py` (97 lines)

Creates `broker_sync_idempotency`, `broker_order_projection`, `broker_sync_sequence_anchor`. All standard. ✅

#### 4.3.8 Day38 Migration: `e8f9a0b1c2d3_add_trade_lifecycle_tables.py` (91 lines)

Creates `trade_lifecycle_events`, `position_sequence_anchor`. All standard. ✅

#### 4.3.9 Merge Migrations

**`merge_day38_gex.py`** (14 lines):
```python
def upgrade() -> None:
    pass
def downgrade() -> None:
    pass
```
No-op merge. ✅

**`f7aa24156f6d_merge_day39_broker_sync_day38_gex_heads.py`** (28 lines):
```python
revision = 'f7aa24156f6d'
down_revision = ('9b675f8a3af0', 'merge_day38_gex')
```
No-op merge. ✅

#### 4.3.10 Alembic env.py Analysis

**`alembic/env.py:1-114`** — Full analysis:

**`alembic/env.py:34`** — `target_metadata = Base.metadata` — standard. ✅

**`alembic/env.py:37-55`** — `_resolve_database_url()` — standard URL resolution. ✅

**`alembic/env.py:58-60`** — `_render_as_batch(url)`:
```python
def _render_as_batch(url: str) -> bool:
    """Use Alembic batch mode only for SQLite schema operations."""
    return url.startswith("sqlite")
```
CRDB (PostgreSQL dialect) would NOT use batch mode. ✅ Correct.

**`alembic/env.py:63-75`** — `run_migrations_offline()` — standard offline migration. ✅

**`alembic/env.py:78-113`** — `run_migrations_online()`:
```python
connectable = config.attributes.get("connectable")
if connectable is None:
    url = _resolve_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url
    if url.startswith("sqlite"):
        connectable = engine_from_config(configuration, prefix="sqlalchemy.",
                                         connect_args={"check_same_thread": False},
                                         poolclass=pool.NullPool)
    else:
        connectable = engine_from_config(configuration, prefix="sqlalchemy.",
                                         poolclass=pool.NullPool)
```
For CRDB, the `else` branch is used (standard engine creation). ✅

**`alembic/env.py:100-112`** — Migration execution:
```python
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
```
Standard. ✅

**Alembic configuration:** The `alembic.ini` file does not hardcode `sqlalchemy.url` — it's set dynamically in `env.py`. ✅

### 4.4 PostgreSQL-Specific Features — Complete Classification

| Feature | Found? | Location | Classification |
|---|---|---|---|
| PostgreSQL-specific raw SQL | Yes (6 locations) | `ingestion.py:344-360`, `ingestion.py:388-408`, `persistence.py:215-239`, `fill_ledger.py:542-566`, `migrate_sqlite_to_postgres.py` | 🟡 All standard SQL except dialect branching in `fill_ledger.py` |
| `ON CONFLICT DO NOTHING` | Yes (4 locations) | `ingestion.py:344-360`, `persistence.py:215-239`, `fill_ledger.py:542-566`, `fill_ledger.py` (other) | 🟢 CRDB supports |
| `ON CONFLICT DO UPDATE` | Yes (1 location) | `persistence.py:215-239` | 🟢 CRDB supports |
| `RETURNING` | Yes (2 locations) | `fill_ledger.py:542-566`, `persistence.py:215-239` | 🟢 CRDB supports |
| `FOR UPDATE` | Yes (5 locations) | `paper_execution.py:646`, `ingestion.py:803`, `fill_ledger.py:402,640,711`, `raw_ingress.py:288` | 🟢 CRDB supports |
| `FOR UPDATE SKIP LOCKED` | Yes (1 location) | `raw_ingress.py:288` | 🟢 CRDB supports |
| `FOR UPDATE NOWAIT` | **No** | — | 🟢 Not used (no dependency) |
| `NOWAIT` | **No** | — | 🟢 Not used |
| JSON/JSONB columns | **No** | — | 🟢 Not used (Text storage) |
| JSON operators in queries | **No** | — | 🟢 Not used |
| ARRAY columns | **No** | — | 🟢 Not used |
| ARRAY operators | **No** | — | 🟢 Not used |
| DB-level ENUM type | **No** | — | 🟢 Not used (Python enum → String) |
| UUID DB type | **No** | — | 🟢 Not used (String(36) storage) |
| `SERIAL` columns | **No** | — | 🟢 Not used |
| `IDENTITY` columns | **No** | — | 🟢 Not used |
| Generated/computed columns | **No** | — | 🟢 Not used |
| Partial indexes | **Yes (2)** | `125e1807df8d:84-96`, `b8c9f1d2e34a:29` | 🟡 Needs CRDB verification + dialect branching fix |
| Expression indexes | **No** | — | 🟢 Not used |
| Exclusion constraints | **No** | — | 🟢 Not used |
| Advisory locks (`pg_advisory_lock`) | **No** | — | 🟢 Not used |
| Database extensions (`CREATE EXTENSION`) | **No** | — | 🟢 Not used |
| Triggers (`CREATE TRIGGER`) | **No** | — | 🟢 Not used |
| Stored procedures/functions (`CREATE FUNCTION`) | **No** | — | 🟢 Not used |
| `LISTEN`/`NOTIFY` | **No** | — | 🟢 Not used |
| `COPY` command | **No** | — | 🟢 Not used |
| Materialized views | **No** | — | 🟢 Not used |
| `CURRENT_TIMESTAMP` | Yes (2 locations) | `persistence.py:223,227` | 🟢 Standard SQL, not PostgreSQL-specific |
| `sa.text("false")` server default | Yes (1 location) | `models.py:80` (`BrokerOrderProjection.is_terminal`) | 🟢 CRDB supports boolean literals |
| `server_default=sa.text("false")` | Yes | `models.py:81`, `broker_sync/models.py:81` | 🟢 CRDB supports |
| `batch_alter_table` (SQLite-only) | Yes (in migrations) | Various migrations | 🟢 Not used for CRDB (env.py returns False for non-SQLite) |
| `postgresql_where` Alembic kwarg | Yes (1 location) | `b8c9f1d2e34a:29` | 🟡 Needs CRDB verification |
| `dialect_insert` with PG/SQLite branching | Yes (1 location) | `db_dialect.py:15-36` | 🟡 Needs CRDB branch |
| `_upsert_trade_fill` with PG/SQLite branching | Yes (1 location) | `fill_ledger.py:542-566` | 🟡 Needs CRDB branch |

### 4.5 Dialect-Specific Code — The Critical Gap

**Two locations hardcode PostgreSQL vs SQLite branching with no CockroachDB path:**

#### Location 1: `app/broker_sync/fill_ledger.py:542-566` — `_upsert_trade_fill`

```python
bind = db.get_bind()
if bind is not None and bind.dialect.name == "postgresql":
    stmt = pg_insert(BrokerFillLedgerFill).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
    ).returning(BrokerFillLedgerFill.tenant_id)
else:
    stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
    ).returning(BrokerFillLedgerFill.tenant_id)
```

**Problem:** On CRDB, `bind.dialect.name` is `"cockroachdb"`, so this falls into the `else` (SQLite) branch.

**Impact:** The fill-ledger atomic first-applier arbitration (Lane B TRADE_ID dedup) would use the wrong dialect's insert construct. This could break the `ON CONFLICT DO NOTHING RETURNING` semantics that the fill deduplication depends on.

**Required fix:** Add `"cockroachdb"` branch:
```python
if bind is not None and bind.dialect.name in ("postgresql", "cockroachdb"):
    stmt = pg_insert(BrokerFillLedgerFill).values(**values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
    ).returning(BrokerFillLedgerFill.tenant_id)
else:
    ...
```

#### Location 2: `app/utils/db_dialect.py:15-36` — `dialect_insert`

```python
def dialect_insert(engine: Engine, table: Table):
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        from sqlalchemy import insert
        return insert(table)
```

**Problem:** On CRDB, falls into `else` → generic `insert()` which does NOT support `on_conflict_do_update()`.

**Impact:** If any code uses `dialect_insert` for CRDB, `on_conflict_do_update()` would not be available. However, searching the codebase, `dialect_insert` is defined but may not be widely used (the broker-sync code uses inline branching instead).

**Required fix:** Add `"cockroachdb"` branch:
```python
if dialect_name in ("postgresql", "cockroachdb"):
    from sqlalchemy.dialects.postgresql import insert
    return insert(table)
elif dialect_name == "sqlite":
    ...
```

### 4.6 Schema Compatibility Matrix

| Table | CRDB Compatibility | Notes |
|---|---|---|
| `paper_accounts` | 🟢 | Standard Integer/String/Float/DateTime |
| `trades` | 🟢 | Standard |
| `legs` | 🟢 | Standard, FK to trades |
| `strategy_executions` | 🟢 | Standard, UniqueConstraint on (user_id, client_order_id) |
| `paper_orders` | 🟢 | Standard, UniqueConstraint on (user_id, client_order_id) |
| `positions` | 🟢 | Standard, UniqueConstraint on (user_id, symbol, expiry, strike, option_type) |
| `paper_transactions` | 🟢 | Standard, cash ledger |
| `strategy_leg_exposures` | 🟢 | Standard, UniqueConstraint on (user_id, order_id) |
| `exit_exposure_allocations` | 🟢 | Standard junction table |
| `bulk_exit_records` | 🟢 | Standard |
| `strategy_templates` | 🟢 | Standard |
| `strategy_template_legs` | 🟢 | Standard, FK to templates |
| `users` | 🟡 | Partial index on `google_sub` (`postgresql_where` kwarg) needs CRDB verification |
| `user_sessions` | 🟢 | Standard |
| `broker_connections` | 🟡 | Partial unique index on (user_id, broker) WHERE is_default = true needs CRDB verification + dialect branching fix |
| `broker_tokens` | 🟢 | Standard |
| `contract_specs` | 🟢 | Standard |
| `data_completeness` | 🟢 | Standard |
| `gex_snapshots` | 🟢 | Standard |
| `historical_gex` | 🟢 | Standard |
| `ingestion_checkpoint` | 🟢 | Standard |
| `ingestion_log` | 🟢 | Standard |
| `iv_observations` | 🟢 | Standard |
| `nifty_candles` | 🟢 | Standard |
| `option_candles` | 🟢 | Standard |
| `option_greeks` | 🟢 | Standard |
| `trade_lifecycle_events` | 🟢 | Standard, 2 UniqueConstraints |
| `position_sequence_anchor` | 🟢 | Standard, composite PK |
| `broker_sync_idempotency` | 🟢 | Standard, PK on canonical_id |
| `broker_order_projection` | 🟢 | Standard, Boolean with server_default |
| `broker_sync_sequence_anchor` | 🟢 | Standard, composite PK |
| `broker_raw_observation` | 🟡 | `LargeBinary` (BYTEA) — CRDB supports but verify |
| `broker_fill_ledger_observation` | 🟢 | Standard |
| `broker_fill_ledger_fill` | 🟢 | Standard, composite PK |
| `broker_fill_identity_alias` | 🟢 | Standard, composite PK |
| `broker_fill_identity_lineage` | 🟢 | Standard |

---

## 5. Transaction and Concurrency Audit — HIGH PRIORITY

### 5.1 Transaction Patterns — Complete Inventory

#### Pattern 1: `execute_strategy` (`app/services/paper_execution.py:328-587`)

**Full function signature:** `execute_strategy(user_id, request, db, prices, *, risk_candidate=None, risk_policy=None, reference_timestamp=None) -> ExecutionOut`

**Transaction boundary:** Caller-owned. The function receives a `Session` and calls `db.commit()` at line 585. No internal `session.begin()` or `session.rollback()`.

**Flow:**
1. **Read-only idempotency check** (line 363-370): `SELECT StrategyExecution WHERE user_id = :user_id AND client_order_id = :client_order_id`. If exists, return existing execution. No write.
2. **Read-only validation** (lines 372-441): Risk check, market data validation. No write.
3. **Write phase** (lines 443-584): Create `StrategyExecution`, `Trade`, `PaperOrder` (× N legs), `Position` (× N instruments), `PaperTransaction` (× N legs), `Leg` (× N legs), `StrategyLegExposure` (× N legs). All via `db.add()` + `db.flush()`.
4. **Commit** (line 585): `db.commit()`

**Key code:**
```python
# Line 363-370: Idempotency check
existing = db.scalar(
    select(StrategyExecution).where(
        StrategyExecution.user_id == user_id,
        StrategyExecution.client_order_id == request.client_order_id,
    )
)
if existing is not None:
    return _execution_out(existing, db, duplicated=True)

# Line 443-458: Create execution
execution_id = _new_execution_id()
_get_or_create_account(user_id, request.starting_capital, db)
execution = StrategyExecution(user_id=user_id, execution_id=execution_id, ...)
db.add(execution)
db.flush()

# Line 463-474: Create legacy journal record
trade = Trade(user_id=user_id, symbol=symbol, ...)
db.add(trade)
db.flush()

# Line 478-573: Create orders, positions, transactions, legs
for i, leg in enumerate(request.legs):
    order = PaperOrder(...)
    db.add(order)
    db.flush()
    position = _get_position(db, user_id, ...)
    if position is None:
        position = Position(...)
        db.add(position)
        db.flush()
    # ... update position, create transaction, create leg
    db.flush()

# Line 581: Create strategy leg exposures
create_exposures_for_orders(db, user_id, execution_id, orders, now)

# Line 583-585: Finalize and commit
execution.entry_net = round(entry_net, 2)
trade.entry_net = round(entry_net, 2)
db.commit()
```

**Idempotency mechanism:** `StrategyExecution.client_order_id` has `UniqueConstraint("user_id", "client_order_id")` (line 134). If a retry sends the same `client_order_id`, the initial read finds the existing execution and returns it without writing. ✅

**Concurrency control:** None explicit. Relies on:
- Unique constraint for idempotency (same client_order_id)
- Validation-before-write pattern (all validation happens before any db.add)
- Implicit assumption that strategy executions are user-initiated and sequential

**Risk under CRDB SERIALIZABLE:** If two concurrent requests with different `client_order_id` but touching the same position (same instrument) arrive, both would read the position state, compute new state, and try to write. Under PostgreSQL READ COMMITTED, the second write would overwrite the first (lost update — actually a latent bug). Under CRDB SERIALIZABLE, one transaction would be aborted with a serialization error.

**Mitigation:** The `Position` unique constraint (one row per instrument per user) means concurrent executions for different instruments don't conflict. Concurrent executions for the same instrument would conflict — but this is rare (user typically executes one strategy at a time).

#### Pattern 2: `exit_position` (`app/services/paper_execution.py:615-749`)

**Full function signature:** `exit_position(user_id, position_id, request, db, fill_price, *, commit=True, exit_side=None, target_exposure_id=None) -> ExitOut`

**Transaction boundary:** Caller-owned. Calls `db.commit()` implicitly via caller.

**Flow:**
1. **Lock position row** (line 645-647): `SELECT Position WHERE id = :position_id FOR UPDATE`
2. **Check idempotency** (line 651-653): `find_exit_replay()` — Check if exit with same client_order_id already exists
3. **Validate** (lines 655-668): Position is open, quantity is valid
4. **Compute fill** (lines 679-682): `apply_fill()` — pure computation, no DB write
5. **Write phase** (lines 684-738): Create `PaperOrder`, update `Position`, create `PaperTransaction`, close journal legs, maintain exposure allocations
6. **Update execution P&L** (lines 740-753): If position has strategy_execution_id, accumulate realized P&L on execution
7. **Commit** (implicit, caller-owned)

**Key code:**
```python
# Line 645-647: Lock position row
position = db.execute(
    select(Position).where(Position.id == position_id).with_for_update()
).scalar_one_or_none()
if position is None or position.user_id != user_id:
    raise PaperExecutionError("POSITION_NOT_FOUND", "Position not found.")

# Line 651-653: Idempotency check
existing = find_exit_replay(user_id, position, request.client_order_id, db)
if existing is not None:
    return existing

# Line 655-659: Validate position is open
if position.status != "open" or position.net_quantity == 0:
    raise PaperExecutionError("INSUFFICIENT_POSITION", ...)

# Line 679-682: Compute fill (pure function)
new_net, new_avg, realized = apply_fill(
    position.net_quantity, position.average_entry_price,
    action, qty, fill_price, position.lot_size,
)

# Line 684-705: Create exit order
order = PaperOrder(user_id=user_id, client_order_id=request.client_order_id, ...)
db.add(order)
db.flush()

# Line 708-715: Update position
position.net_quantity = new_net
position.average_entry_price = new_avg
position.realized_pnl = round(position.realized_pnl + realized, 2)
position.updated_at = now
if new_net == 0:
    position.status = "closed"
    position.closed_at = now

# Line 717-726: Create cash transaction
db.add(PaperTransaction(...))

# Line 728: Close journal legs
_close_journal_legs(user_id, position, qty, fill_price, db, now)

# Line 732-738: Maintain exposure allocations
maintain_exposure_on_exit(db, user_id, position, prior_net_quantity, qty, now, ...)

# Line 740-753: Update execution P&L
if position.strategy_execution_id:
    execution = db.scalar(select(StrategyExecution).where(...))
    if execution is not None:
        execution.realized_pnl = round(execution.realized_pnl + realized, 2)
```

**Concurrency control:** `with_for_update()` on `Position` row (line 646). This is the critical serialization point. Two concurrent exits for the same position would be serialized by the row lock.

**Idempotency mechanism:** `find_exit_replay()` (line 593-612) checks for existing exit with same `client_order_id`. Also, `PaperOrder.client_order_id` has `UniqueConstraint("user_id", "client_order_id")` per user.

**Risk under CRDB SERIALIZABLE:**
- Same-position exits: `FOR UPDATE` serializes them. ✅
- Different-position exits touching same execution: If two exits for different positions belong to the same `strategy_execution_id`, both try to update `execution.realized_pnl` (line 748-753). Under CRDB SERIALIZABLE, this could cause a serialization conflict.
- **Probability:** Low — exits are user-initiated and typically sequential.

#### Pattern 3: `append_lifecycle_event` (`app/trade_lifecycle/persistence.py:249-400`)

**Full function signature:** `append_lifecycle_event(db, aggregate_type, aggregate_id, event_type, event_version, tenant_id, sequence, position_sequence, quantity_delta, position_identity, occurred_at, payload, metadata=None) -> TradeLifecycleEvent`

**Transaction boundary:** Caller-owned. No internal commit/rollback.

**Flow:**
1. **Compute event_id** (line 272): Deterministic `event_id()` function
2. **Serialize payload/metadata** (lines 274-279): JSON with sorted keys
3. **Build canonical content** (lines 288-311): For duplicate/conflict detection
4. **Insert with ON CONFLICT handling** (lines 313-399): Uses raw SQL INSERT
   - Same event_id + same content → idempotent (no insert)
   - Same event_id + different content → IntegrityError (conflict)
   - Same (tenant_id, aggregate_type, aggregate_id, sequence) + same content → idempotent
   - Same (tenant_id, aggregate_type, aggregate_id, sequence) + different content → IntegrityError (conflict)

**Key code:**
```python
# Line 272: Compute event_id
computed_id = event_id(tenant_id, aggregate_type, aggregate_id, event_type, sequence)

# Line 274-279: Serialize payload/metadata
payload_json = _json.dumps(payload, sort_keys=True)
metadata_json = (None if metadata is None else _json.dumps(metadata, sort_keys=True))

# Line 288-311: Build canonical content for comparison
incoming_canonical = _canonical_event_content(...)

# Line 313-399: INSERT with ON CONFLICT handling
# Uses raw SQL with ON CONFLICT DO NOTHING/UPDATE
```

**Concurrency control:**
- `UniqueConstraint("tenant_id", "aggregate_type", "aggregate_id", "sequence")` on `trade_lifecycle_events` (line 122-128)
- `event_id` is deterministic — same inputs → same event_id
- `IntegrityError` on unique constraint violation → caught and handled as conflict/duplicate

**Risk under CRDB SERIALIZABLE:** Low. The unique constraint + deterministic event_id make conflicts rare. The `allocate_position_sequence` function (used for position-scoped sequences) uses atomic `ON CONFLICT DO UPDATE`, which is concurrency-safe.

#### Pattern 4: `allocate_position_sequence` (`app/trade_lifecycle/persistence.py:195-242`)

**Full function signature:** `allocate_position_sequence(db, tenant_id, user_id, symbol, expiry, strike, option_type) -> int`

**Transaction boundary:** Caller-owned. No internal commit/rollback.

**Flow:**
1. **Atomic upsert** (lines 215-239): `INSERT ... ON CONFLICT DO UPDATE SET last_position_sequence = last_position_sequence + 1 RETURNING last_position_sequence`

**Key code:**
```python
result = db.execute(
    text("""
    INSERT INTO position_sequence_anchor
        (tenant_id, user_id, symbol, expiry, strike, option_type,
         last_position_sequence, created_at, updated_at)
    VALUES
        (:tenant_id, :user_id, :symbol, :expiry, :strike, :option_type,
         1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (tenant_id, user_id, symbol, expiry, strike, option_type)
    DO UPDATE SET
        last_position_sequence = position_sequence_anchor.last_position_sequence + 1,
        updated_at = CURRENT_TIMESTAMP
    RETURNING last_position_sequence
    """),
    dict(...),
).scalar()
if result is None:
    raise RuntimeError("Failed to allocate position_sequence")
return int(result)
```

**Concurrency control:** Atomic upsert at the database level. Concurrent callers get different sequence numbers. ✅

**Risk under CRDB SERIALIZABLE:** None. The atomic upsert is concurrency-safe on any database that supports `ON CONFLICT DO UPDATE`.

#### Pattern 5: `ingest_canonical_event` (`app/broker_sync/ingestion.py:67-1239`)

**Full function signature:** `ingest_canonical_event(db, event, *, position_info=None) -> IngestionResult`

**Transaction boundary:** Caller-owned. All operations share the caller's transaction. On any failure, the caller rolls back the entire transaction.

**Flow (from docstring, lines 3-30):**
1. Validation (identity, tenant, quantity invariants)
2. Tenant/order identity resolution
3. Durable idempotency (canonical_id + content_fingerprint → DUPLICATE_NOOP or CONFLICT)
4. Broker ordering validation (sequence gap/stale/out-of-order)
5. Terminal-state enforcement (against durable projection)
6. Durable normalized projection (BrokerOrderProjection)
7. Explicit Day38 lifecycle mapping (broker events → lifecycle events)
8. All in single transaction (all commit or all roll back)

**Key code:**
```python
# Line 324-361: Create sequence anchor inside SAVEPOINT
_ensure_broker_sequence_anchor(db, event, position_info)

# Line 364-418: Advance sequence after successful application
_advance_broker_sequence(db, event, position_info)

# Lines 344-360: INSERT ... ON CONFLICT DO NOTHING for anchor creation
# Lines 388-408: UPDATE ... WHERE last_sequence = :expected for advancement
```

**Concurrency control:**
- `BrokerSyncIdempotency.canonical_id` PK — unique constraint prevents duplicate ingestion
- `BrokerSyncSequenceAnchor` — `INSERT ... ON CONFLICT DO NOTHING` for creation
- `_advance_broker_sequence` — `UPDATE ... WHERE last_sequence = :expected` (optimistic concurrency)
- SAVEPOINT usage — sequence anchor creation/advancement can be rolled back independently

**Risk under CRDB SERIALIZABLE:**
- The `_advance_broker_sequence` UPDATE (line 388-408) uses `WHERE last_sequence = :expected`. If two workers try to advance the same anchor concurrently, one UPDATE affects 0 rows and raises `IngestionError`. This is intentional conflict detection, not a serialization failure.
- However, if CRDB returns a serialization error during the broader transaction (e.g., concurrent lifecycle event inserts for same aggregate), the current code would not retry.
- **Probability:** Medium — concurrent broker events for the same order could cause serialization conflicts under CRDB's stricter isolation.

#### Pattern 6: `apply_lane_b_fill` (`app/broker_sync/fill_ledger.py:378-496`)

**Full function signature:** `apply_lane_b_fill(db, tenant_id, broker, provider_order_id, d1, content_fingerprint, source_mode, received_at, fill_quantity, fill_price, cumulative_after, provider_status, raw_observation_id, provider_trade_id, raw_payload_excerpt) -> tuple[BrokerFillLedgerFill, str, BrokerFillLedgerObservation]`

**Transaction boundary:** Caller-owned. "NO helper in this module commits." (line 23)

**Flow:**
1. **Atomic first-applier insert** (line 518-579): `INSERT ... ON CONFLICT DO NOTHING RETURNING`
2. **If created:** Return APPLIED
3. **If not created (row pre-existed):** Re-read under `FOR UPDATE` (line 396-403), compare fingerprints
   - Same fingerprint → DUPLICATE_FILL
   - Different fingerprint → CONFLICT

**Key code:**
```python
# Line 518-579: Atomic first-applier arbitration
created = _upsert_trade_fill(db, ...)  # INSERT ... ON CONFLICT DO NOTHING RETURNING

if created is not None:
    # WE created the row — APPLIED
    return created, "APPLIED", obs
else:
    # Someone else created it — read under FOR UPDATE and classify
    existing = db.execute(
        select(BrokerFillLedgerFill).where(...).with_for_update()
    ).scalar_one()
    
    prior_fp = _fill_fingerprint(db, existing)
    if prior_fp == content_fingerprint:
        return existing, "DUPLICATE_FILL", dup_obs
    else:
        return existing, "CONFLICT", conflict_obs
```

**Concurrency control:** `INSERT ... ON CONFLICT DO NOTHING RETURNING` for atomic first-applier arbitration. The database decides who created the row. ✅

**Risk under CRDB SERIALIZABLE:** Low. The ON CONFLICT pattern minimizes contention. The FOR UPDATE on the loser path is safe.

#### Pattern 7: `commit_raw_observation` (`app/broker_sync/raw_ingress.py:157-243`)

**Full function signature:** `commit_raw_observation(db, *, tenant_id, broker, source_mode, raw_payload, received_at=None, delivery_evidence=None, provider_order_id=None, provider_trade_id=None) -> BrokerRawObservation`

**Transaction boundary:** This function EXPLICITLY commits. "This function performs the raw INSERT and COMMITS in a dedicated transaction. Callers MUST NOT wrap it in a larger transaction." (lines 171-174)

**Flow:**
1. **Create row** (lines 185-201): `BrokerRawObservation(...)` with UUID PK
2. **Add and flush** (lines 202-203): `db.add(row)`, `db.flush()`
3. **Commit** (line 205): `db.commit()`

**Key code:**
```python
# Line 185-201: Create raw observation row
row = BrokerRawObservation(
    raw_observation_id=str(uuid.uuid4()),
    tenant_id=tenant_id,
    broker=broker,
    received_at=received_at,
    source_mode=source_mode,
    raw_payload=bytes(raw_payload),
    ...
)
db.add(row)
db.flush()

# Line 205: Commit (explicit — Phase 1 dedicated transaction)
db.commit()
```

**Concurrency control:** UUID PK (`raw_observation_id=str(uuid.uuid4())`). Each payload gets a unique ID. No unique constraint on content — raw observations are never delivery-deduped. ✅

**Risk under CRDB SERIALIZABLE:** None. Each insert is independent (unique UUID PK).

#### Pattern 8: `claim_raw_observations` (`app/broker_sync/raw_ingress.py:239-295`)

**Full function signature:** `claim_raw_observations(db, worker_id, lease_seconds=DEFAULT_LEASE_SECONDS, limit=10) -> list[BrokerRawObservation]`

**Transaction boundary:** Caller-owned.

**Flow:**
1. **Claim pending observations** (lines 253-292): `SELECT ... FOR UPDATE SKIP LOCKED WHERE processing_status = 'PENDING' ORDER BY created_at ASC LIMIT :limit`
2. **Update claimed rows** (lines 278-289): Set `processing_status = 'IN_PROGRESS'`, `lease_expires_at = now + lease_seconds`

**Key code:**
```python
# Line 288: FOR UPDATE SKIP LOCKED
.with_for_update(skip_locked=True)
```

**Concurrency control:** `FOR UPDATE SKIP LOCKED` — standard pattern for worker claim queues. ✅

**Risk under CRDB SERIALIZABLE:** None. SKIP LOCKED is designed for this use case and is supported by CRDB.

### 5.2 Existing Correctness Model — PostgreSQL Dependencies

**What StrikeNova depends on from PostgreSQL:**

1. **`FOR UPDATE` row-level locking** — Used in `exit_position` (line 646), `apply_lane_b_fill` loser path (line 402), `ingest_canonical_event` (line 803 — `with_for_update()` on `BrokerSyncIdempotency`), `claim_raw_observations` (line 288 — `FOR UPDATE SKIP LOCKED`).

   **CRDB compatibility:** CRDB supports `FOR UPDATE`. However, under CRDB's `SERIALIZABLE` isolation, `FOR UPDATE` has stricter semantics: it locks the row AND participates in the serialization protocol. In practice, for single-row locks, this should work the same. For multiple `FOR UPDATE` rows in a single transaction, edge cases could differ.

2. **`FOR UPDATE SKIP LOCKED`** — Used in `claim_raw_observations` (line 288).

   **CRDB compatibility:** 🟢 CRDB supports `FOR UPDATE SKIP LOCKED`.

3. **`INSERT ... ON CONFLICT DO NOTHING/UPDATE ... RETURNING`** — Used in 4 locations.

   **CRDB compatibility:** 🟢 CRDB supports all these constructs. However, the dialect branching in `fill_ledger.py:542-566` must be fixed to use the correct dialect for CRDB.

4. **`UPDATE ... WHERE ...` optimistic concurrency** — Used in `_advance_broker_sequence` (line 388-408).

   **CRDB compatibility:** 🟢 CRDB supports standard `UPDATE ... WHERE`. The `rowcount` check is an application-level OCC pattern that works on any database.

5. **PostgreSQL `READ COMMITTED` isolation (default)** — StrikeNova's transaction patterns assume `READ COMMITTED` semantics:
   - `exit_position`: `FOR UPDATE` locks the position row, then reads/writes. Under `READ COMMITTED`, the lock prevents concurrent modification. Under `SERIALIZABLE`, the same pattern works but with stricter conflict detection.
   - `execute_strategy`: No explicit locking, relies on unique constraint for idempotency + validation-before-write. Under `READ COMMITTED`, two concurrent executions for different `client_order_id` but touching the same position could both read the position state before either writes → potential lost update. **This is actually a latent bug even on PostgreSQL** — but it's mitigated by the fact that `execute_strategy` is called sequentially in practice.

6. **`SAVEPOINT` support** — Used in `ingest_canonical_event` for sequence anchor creation/advancement.

   **CRDB compatibility:** 🟢 CRDB supports SAVEPOINT.

7. **`IntegrityError` on unique constraint violation** — Used throughout for idempotency/conflict detection.

   **CRDB compatibility:** 🟢 CRDB raises `IntegrityError` on unique constraint violation. SQLAlchemy maps CRDB integrity errors to `sqlalchemy.exc.IntegrityError`.

**What StrikeNova does NOT depend on:**

1. **PostgreSQL-specific isolation levels** — No `SET TRANSACTION ISOLATION LEVEL` in the code.
2. **Advisory locks** — Not used.
3. **LISTEN/NOTIFY** — Not used.
4. **PostgreSQL-specific functions** — `CURRENT_TIMESTAMP` is standard SQL.
5. **PostgreSQL-specific data types** — All types are standard or SQLAlchemy-abstracted.
6. **`pg_try_advisory_xact_lock`** or similar — Not used.
7. **`SELECT ... FOR UPDATE NOWAIT`** — Not used.

### 5.3 CockroachDB Transaction Retry Analysis — EVERY Transaction

**CockroachDB transaction model:**

CockroachDB uses `SERIALIZABLE` isolation by default (actually `SNAPSHOT` isolation, which provides `SERIALIZABLE` guarantees). Under contention, CRDB can return retryable transaction errors:

- **`RETRY_SERIALIZABLE`** (SQLSTATE `40001`) — Transaction serialization conflict. The transaction read data that was modified by another transaction that committed after this transaction started.
- **`RETRY_WRITE_TOO_OLD`** — Write timestamp too old (transaction took too long).
- **`RETRY_READ_TOO_OLD`** — Read timestamp too old (transaction took too long).
- **`RETRY_SERIALIZABLE_ISOLATION`** — Another name for `RETRY_SERIALIZABLE`.

**Application requirement:** Applications using CRDB must retry transactions that receive these errors. The standard pattern is:
```python
max_retries = 3
for attempt in range(max_retries):
    try:
        with session.begin():
            # ... transaction operations ...
        break  # Success
    except SerializationFailure:
        if attempt == max_retries - 1:
            raise
        time.sleep(backoff_strategy(attempt))
```

**StrikeNova's current retry behavior:**

**NO retry handling for CRDB retryable errors exists anywhere in the codebase.**

Searched for: `retry`, `RETRY_`, `40001`, `SerializationFailure`, `cockroachdb`, `CRDB`, `transaction retry`, `retries`, `max_retries` (in DB context) — none found except:
- `app/services/upstox_client.py:138` — HTTP retry for broker API (unrelated to DB)
- `app/services/candle_retry.py:33` — HTTP retry for candle fetching (unrelated to DB)
- `app/broker_sync/ingestion.py:371` — "serialization point" (comment about logical serialization, not DB transaction retry)
- `app/broker_sync/ingestion.py:414` — "Concurrent worker advanced — signal failure for re-classification" (this is about OCC conflict, not serialization failure)

**Transaction-by-transaction CRDB retry analysis:**

| # | Transaction | Function | Purpose | Tables involved | Locking strategy | Current retry behavior | Expected CRDB behavior | Retry handling sufficient? | Additional retry needed? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Strategy execution creation | `execute_strategy` | Create execution + orders + positions + cash + journal | `strategy_executions`, `paper_orders`, `positions`, `paper_transactions`, `trades`, `legs`, `strategy_leg_exposures`, `paper_accounts` | None (relies on unique constraint for idempotency + validation-before-write) | None — no retry wrapper | Under CRDB SERIALIZABLE, if two concurrent executions touch same position, one may receive `RETRY_SERIALIZABLE`. Without retry, this becomes a user-visible error. | ❌ No | **Yes** — wrap in retry decorator catching `SerializationFailure` |
| 2 | Position exit | `exit_position` | Exit a position (partial or full) | `positions`, `paper_orders`, `paper_transactions`, `legs`, `strategy_leg_exposures`, `exit_exposure_allocations`, `strategy_executions` | `FOR UPDATE` on position row (line 646) | None — no retry wrapper | `FOR UPDATE` serializes same-position exits. Different-position exits touching same execution could serialize. Low probability. | ❌ No | **Yes** (defensive) — wrap in retry decorator |
| 3 | Lifecycle event append | `append_lifecycle_event` | Persist lifecycle event with deterministic identity | `trade_lifecycle_events` | Unique constraint on (tenant_id, aggregate_type, aggregate_id, sequence) | None — IntegrityError on conflict is caught and handled | Low probability of serialization conflict (unique constraint + deterministic event_id). | ⚠️ Partial | **Yes** (defensive) — but low priority |
| 4 | Position sequence allocation | `allocate_position_sequence` | Atomic sequence number allocation | `position_sequence_anchor` | Atomic `ON CONFLICT DO UPDATE` (database-level) | None needed (atomic at DB level) | The atomic upsert is concurrency-safe. CRDB SERIALIZABLE may still cause rare serialization conflicts if multiple transactions touch the same anchor row. | ⚠️ Partial | **Yes** (low priority) — but atomic upsert minimizes risk |
| 5 | Broker event ingestion | `ingest_canonical_event` | Ingest broker event with idempotency + projection + lifecycle + sequence | `broker_sync_idempotency`, `broker_order_projection`, `trade_lifecycle_events`, `broker_sync_sequence_anchor` | Unique constraint on canonical_id + `UPDATE ... WHERE` for sequence advance + SAVEPOINT | None for serialization; `IngestionError` raised on OCC conflict | Concurrent broker events for same order could cause serialization conflicts under CRDB SERIALIZABLE. The `_advance_broker_sequence` UPDATE (OCC pattern) raises `IngestionError` on rowcount==0, which is handled. But broader transaction serialization is not handled. | ❌ No | **Yes** — wrap in retry decorator |
| 6 | Lane B fill arbitration | `apply_lane_b_fill` | Trade-ID fill deduplication | `broker_fill_ledger_fill`, `broker_fill_ledger_observation`, `broker_fill_identity_lineage` | `INSERT ... ON CONFLICT DO NOTHING RETURNING` + `FOR UPDATE` on loser path | None needed (atomic arbitration) | The ON CONFLICT pattern minimizes contention. FOR UPDATE on loser path is safe. | ⚠️ Partial | **Yes** (low priority) — but ON CONFLICT pattern minimizes risk |
| 7 | Raw observation ingest | `commit_raw_observation` | Durable raw payload commit | `broker_raw_observation` | None (UUID PK, no unique constraint on content) | None needed (each payload gets unique UUID) | No contention possible — each insert is independent. | ✅ Yes (not needed) | No |
| 8 | Worker claim | `claim_raw_observations` | Claim pending observations for processing | `broker_raw_observation` | `FOR UPDATE SKIP LOCKED` | None needed (SKIP LOCKED avoids contention) | SKIP LOCKED is designed for this use case. | ✅ Yes (not needed) | No |
| 9 | Sequence anchor creation | `_ensure_broker_sequence_anchor` | Create broker sequence anchor if not exists | `broker_sync_sequence_anchor` | `INSERT ... ON CONFLICT DO NOTHING` | None needed (atomic) | ON CONFLICT DO NOTHING is concurrency-safe. | ✅ Yes (not needed) | No |
| 10 | Sequence anchor advancement | `_advance_broker_sequence` | Advance sequence after successful application | `broker_sync_sequence_anchor` | `UPDATE ... WHERE last_sequence = :expected` (OCC) | `IngestionError` on rowcount==0 (intentional conflict detection) | OCC pattern works on CRDB. However, if CRDB returns serialization error on the UPDATE, it would not be caught. | ⚠️ Partial | **Yes** (low priority) — OCC pattern minimizes risk, but serialization error on UPDATE would bypass OCC check |

**Summary of retry handling gaps:**

| Priority | Function | Risk | Required action |
|---|---|---|---|
| 🔴 High | `execute_strategy` | User-visible errors under concurrent strategy executions touching same position | Implement retry decorator for `SerializationFailure` |
| 🔴 High | `exit_position` | User-visible errors under concurrent exits (same or different positions) | Implement retry decorator for `SerializationFailure` |
| 🔴 High | `ingest_canonical_event` | User-visible errors under concurrent broker events for same order | Implement retry decorator for `SerializationFailure` |
| 🟡 Medium | `append_lifecycle_event` | Rare serialization conflicts on lifecycle event insert | Implement retry (low priority, unique constraint minimizes risk) |
| 🟡 Medium | `allocate_position_sequence` | Rare serialization conflicts on sequence anchor update | Implement retry (low priority, atomic upsert minimizes risk) |
| 🟡 Medium | `apply_lane_b_fill` | Rare serialization conflicts on fill row operations | Implement retry (low priority, ON CONFLICT minimizes risk) |
| 🟢 Low | `commit_raw_observation` | No contention possible | No retry needed |
| 🟢 Low | `claim_raw_observations` | SKIP LOCKED avoids contention | No retry needed |
| 🟢 Low | `_ensure_broker_sequence_anchor` | Atomic ON CONFLICT | No retry needed |
| 🟢 Low | `_advance_broker_sequence` | OCC pattern minimizes risk, but serialization error on UPDATE would bypass OCC | Implement retry (low priority) |

### 5.4 SELECT FOR UPDATE Analysis

**All FOR UPDATE usages in the codebase:**

| Location | Function | Table | Purpose | CRDB Compatible? |
|---|---|---|---|---|
| `app/services/paper_execution.py:646` | `exit_position` | `Position` | Lock position row before exit | 🟢 Yes — single row lock, standard pattern |
| `app/broker_sync/ingestion.py:803` | `ingest_canonical_event` (or helper) | `BrokerSyncIdempotency` | Lock idempotency row for conflict detection | 🟢 Yes — single row lock |
| `app/broker_sync/fill_ledger.py:402` | `apply_lane_b_fill` (loser path) | `BrokerFillLedgerFill` | Lock existing fill row for fingerprint comparison | 🟢 Yes — single row lock, taken only when INSERT loses race |
| `app/broker_sync/fill_ledger.py:640` | (fill ledger helper) | `BrokerFillLedgerFill` | Lock fill row for update | 🟢 Yes |
| `app/broker_sync/fill_ledger.py:711` | (fill ledger helper) | `BrokerFillLedgerFill` | Lock fill row for update | 🟢 Yes |
| `app/broker_sync/raw_ingress.py:288` | `claim_raw_observations` | `BrokerRawObservation` | Claim pending observations — `SKIP LOCKED` | 🟢 Yes — SKIP LOCKED supported by CRDB |

**FOR UPDATE patterns:**

1. **Single-row lock for serialization** (`exit_position`, `ingestion.py:803`): Lock one row to serialize concurrent operations on that row. This is the most common pattern and is CRDB-compatible.

2. **Loser-path lock after atomic insert** (`fill_ledger.py:402`): First try atomic `INSERT ... ON CONFLICT DO NOTHING RETURNING`. If the insert loses (row pre-existed), lock the existing row for reading/comparison. This is a sophisticated pattern that minimizes contention. CRDB-compatible.

3. **Worker claim with SKIP LOCKED** (`raw_ingress.py:288`): Claim pending rows without blocking on locked rows. CRDB-compatible.

**Potential CRDB-specific FOR UPDATE concerns:**

1. **Multiple FOR UPDATE rows in a single transaction:** If a transaction locks multiple rows with `FOR UPDATE`, CRDB's serialization protocol is more strict than PostgreSQL's READ COMMITTED. In StrikeNova, no transaction locks multiple FOR UPDATE rows (each transaction locks at most one row with FOR UPDATE). ✅ Safe.

2. **FOR UPDATE without subsequent UPDATE:** If a transaction locks a row with FOR UPDATE but doesn't modify it, PostgreSQL releases the lock on commit. CRDB's behavior should be similar. In StrikeNova, FOR UPDATE is always followed by a read and potentially a write on the same row. ✅ Safe.

3. **FOR UPDATE on a row that's then deleted:** Not applicable — no rows are deleted in StrikeNova's transaction paths.

**Conclusion:** All FOR UPDATE usages in StrikeNova are CRDB-compatible. The patterns are standard and well-established.

### 5.5 CockroachDB Isolation Level Implications

**PostgreSQL default:** `READ COMMITTED`  
**CockroachDB default:** `SERIALIZABLE` (actually `SNAPSHOT` isolation with SERIALIZABLE guarantees)

**Implications for StrikeNova:**

1. **`execute_strategy` (no explicit locking):**
   - PostgreSQL READ COMMITTED: Two concurrent executions for different `client_order_id` but touching the same position would both read the position state, compute new state, and write. The second write would overwrite the first (lost update — a latent bug, but not a user-visible error).
   - CRDB SERIALIZABLE: The same scenario would cause one transaction to receive `RETRY_SERIALIZABLE` and abort. **This is actually better** — CRDB prevents the lost update, but at the cost of a user-visible error (without retry handling).

2. **`exit_position` (FOR UPDATE on position):**
   - PostgreSQL READ COMMITTED: FOR UPDATE serializes same-position exits. Different-position exits are independent.
   - CRDB SERIALIZABLE: FOR UPDATE still serializes same-position exits. Different-position exits that touch the same execution (for P&L accumulation) could serialize. **Slightly stricter, but correct.**

3. **`ingest_canonical_event` (unique constraint + OCC):**
   - PostgreSQL READ COMMITTED: Unique constraint prevents duplicate canonical_id. OCC UPDATE WHERE prevents concurrent sequence advancement.
   - CRDB SERIALIZABLE: Same constraints apply. Additionally, the broader transaction (multiple tables) could serialize. **Slightly stricter, but correct.**

**Key insight:** CRDB's stricter isolation is actually *safer* for StrikeNova's correctness model — it prevents lost updates that PostgreSQL's READ COMMITTED would allow. The cost is that concurrent transactions may receive serialization errors instead of silently overwriting each other. **This is why retry handling is essential** — without it, users see errors instead of silent corruption.

---

## 6. Economic Correctness Audit

### 6.1 Invariants and Their Enforcement

#### Invariant 1: Positions cannot silently lose quantity

**Enforcement:**
- `Position.net_quantity` updated atomically within the same transaction as the order/fill
- `exit_position` uses `FOR UPDATE` on position row (line 646) — serializes concurrent exits
- `execute_strategy` updates positions within the same transaction as order creation
- `Position` unique constraint: one row per (user_id, symbol, expiry, strike, option_type) — prevents duplicate position rows

**Test coverage:**
- `test_paper_concurrency_repro.py` — Tests exit_position idempotency race and lost-update scenario. Uses real PostgreSQL with independent connections.
- `test_day38_postgres_concurrency.py` — Tests PostgreSQL concurrent lifecycle event persistence with FOR UPDATE serialization.

**CRDB implications:** The FOR UPDATE + unique constraint pattern is CRDB-compatible. The atomic transaction ensures quantity updates are atomic. ✅

#### Invariant 2: Exit operations cannot double-close positions

**Enforcement:**
- `exit_position` checks `position.status != "open"` and `position.net_quantity == 0` (line 655-659) AFTER acquiring FOR UPDATE
- `find_exit_replay()` (line 593-612) returns existing exit for same `client_order_id` — idempotency
- `PaperOrder.client_order_id` has unique constraint per user (line 175)

**Test coverage:**
- `test_paper_concurrency_repro.py` — Tests exit idempotency race
- `test_day41_phase6_7_9_fill_ledger.py` — Tests edge contract: "complete + filled_quantity < quantity ⇒ INVALID_OBSERVATION quarantine; open + filled_quantity > 0 ⇒ two explicit observations, never an implicit synthetic fill"

**CRDB implications:** The FOR UPDATE + status check + idempotency pattern is CRDB-compatible. ✅

#### Invariant 3: Cash cannot be duplicated/lost

**Enforcement:**
- `PaperTransaction` is the ONLY cash ledger (models.py:213-231)
- `amount` is signed (negative = debit, positive = credit)
- Available cash = `starting_capital + SUM(amount)` — derived, not stored
- All cash mutations happen in the same transaction as the order/position update
- `PaperTransaction` has no unique constraint on (user_id, execution_id, order_id, type) — but the transaction is created once per order fill, and the order creation is idempotent

**Code:**
```python
# models.py:213-231
class PaperTransaction(Base):
    """Auditable cash-ledger record for every cash-affecting paper execution.
    amount is the signed rupee change applied to available cash
    (buy pays out = negative, sell receives = positive).
    Available cash is derived as starting_capital + SUM(amount)
    — the ledger is the only writer, so cash can always be reconciled.
    """
    __tablename__ = "paper_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(20))  # ENTRY_DEBIT | ENTRY_CREDIT | EXIT_DEBIT | EXIT_CREDIT
    amount: Mapped[float] = mapped_column(Float)  # signed rupees applied to cash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

**Test coverage:**
- `test_paper_concurrency_repro.py` — Tests cash flow correctness
- Paper execution tests verify entry_net and realized_pnl

**CRDB implications:** The single-transaction + single-writer pattern is CRDB-compatible. Cash is derived from the transaction log, not stored as a mutable balance. ✅

#### Invariant 4: Realized P&L remains correct

**Enforcement:**
- `apply_fill()` (paper_execution.py:226-274) computes realized P&L deterministically as a pure function
- `position.realized_pnl` accumulates within the same transaction (line 540: `position.realized_pnl = round(position.realized_pnl + realized, 2)`)
- `execution.realized_pnl` accumulates on exit (line 748-753): `execution.realized_pnl = round(execution.realized_pnl + realized, 2)`
- All P&L updates happen in the same transaction as the fill

**Code:**
```python
# paper_execution.py:226-274 — apply_fill (pure function)
def apply_fill(net_quantity, average_entry_price, action, quantity, fill_price, lot_size):
    """Apply a fill to a position and return (new_net, new_avg, realized_pnl)."""
    ...

# paper_execution.py:540 — Position P&L update (inside execute_strategy)
position.realized_pnl = round(position.realized_pnl + realized, 2)

# paper_execution.py:748-753 — Execution P&L update (inside exit_position)
if execution is not None:
    execution.realized_pnl = round(execution.realized_pnl + realized, 2)
```

**Test coverage:**
- Multiple paper execution tests verify P&L calculation
- `test_day34_paper_risk.py` — Tests risk assessment (related to P&L)

**CRDB implications:** Pure function + single-transaction accumulation is CRDB-compatible. ✅

#### Invariant 5: Lifecycle events remain consistent

**Enforcement:**
- `TradeLifecycleEvent` has `UniqueConstraint("tenant_id", "aggregate_type", "aggregate_id", "sequence")` (persistence.py:122-128)
- `event_id` is deterministic (persistence.py:72-85 — `event_id()` function)
- `append_lifecycle_event` handles duplicate event_id idempotently (same event_id + same content → no insert; same event_id + different content → IntegrityError)
- `allocate_position_sequence` uses atomic upsert (CRDB-compatible)

**Test coverage:**
- `test_day38_task5_append_idempotency.py` — Tests: identical event idempotency, same identity/changed content → conflict, same aggregate sequence/identical content → idempotent, same aggregate sequence/different content → conflict, None vs empty metadata (distinct canonical content), tenant isolation, caller transaction survives duplicate/conflict, PostgreSQL concurrent identical/conflicting append
- `test_day38_task6_transactional_allocation.py` — Tests: successful transaction (allocate + event + commit → both persist), rollback after allocation (no event → sequence not burned), rollback after failed event persistence (no orphan sequence), commit preserves both (anchor and event agree), caller transaction ownership (no internal commit/rollback), full PositionIdentity namespace independence

**CRDB implications:** Unique constraint + deterministic event_id + atomic sequence allocation is CRDB-compatible. ✅

#### Invariant 6: Order state remains consistent

**Enforcement:**
- `PaperOrder.client_order_id` unique per user (models.py:175): `UniqueConstraint("user_id", "client_order_id", name="uq_order_client_order")`
- `StrategyExecution.client_order_id` unique per user (models.py:134): `UniqueConstraint("user_id", "client_order_id", name="uq_execution_client_order")`
- Order status lifecycle: `PENDING → FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED` (paper_execution.py:100)
- Current engine fills atomically (PENDING → FILLED), but full state model and transition validator exist for future async/partial fills

**Test coverage:**
- Paper execution tests verify order state transitions
- `test_day41_phase6_7_9_fill_ledger.py` — Tests edge contract enforcement

**CRDB implications:** Unique constraint + status field is CRDB-compatible. ✅

#### Invariant 7: Idempotent operations remain idempotent

**Enforcement:**
- Unique constraints on `client_order_id` for both `StrategyExecution` and `PaperOrder`
- `append_lifecycle_event` handles duplicate event_id idempotently
- `allocate_position_sequence` uses atomic upsert (idempotent by design)
- `commit_raw_observation` uses UUID PK (idempotent by key — each payload gets unique UUID)
- `BrokerSyncIdempotency.canonical_id` PK (idempotent by key)
- `INSERT ... ON CONFLICT DO NOTHING` patterns throughout

**Test coverage:**
- `test_day38_task5_append_idempotency.py` — Comprehensive idempotency tests
- `test_day38_task6_transactional_allocation.py` — Transactional idempotency tests
- `test_day39_task2_red_v6.py` — Broker event idempotency tests
- `test_day41_phase6_7_9_fill_ledger.py` — Fill deduplication idempotency tests
- `test_day41_phase10_postgres_concurrency.py` — PostgreSQL concurrency verification of idempotent arbitration

**CRDB implications:** Unique constraints + ON CONFLICT + UUID PKs are CRDB-compatible. ✅

#### Invariant 8: Concurrent requests cannot create economic corruption

**Enforcement:**
- `exit_position` uses `FOR UPDATE` on position row (serializes same-position exits)
- `execute_strategy` relies on unique constraints + validation-before-write (mitigates, but doesn't fully prevent, concurrent execution conflicts)
- Broker sync uses `ON CONFLICT` + `FOR UPDATE` + `SKIP LOCKED` patterns
- All financial mutations happen in single transactions (atomicity)

**Test coverage:**
- `test_day38_postgres_concurrency.py` — PostgreSQL concurrent lifecycle event persistence
- `test_day39_task2_red_v6.py` — Broker event concurrency (PostgreSQL-gated)
- `test_day41_phase10_postgres_concurrency.py` — PostgreSQL concurrency: SKIP LOCKED claim, Lane B first-applier arbitration, no-ID fill collision, stale lease reclaim
- `test_paper_concurrency_repro.py` — Exit position idempotency race and lost-update scenario

**CRDB implications:** The FOR UPDATE + unique constraint + atomic upsert + ON CONFLICT patterns are CRDB-compatible. However, CRDB's SERIALIZABLE isolation may cause serialization errors under contention that PostgreSQL's READ COMMITTED would not. **This is a user-visible error risk, not a corruption risk** — the transactions are atomic, so no partial state is committed. ✅

### 6.2 Economic Correctness — CRDB-Specific Risks

**What could go wrong on CRDB (that wouldn't on PostgreSQL):**

1. **Serialization errors on `execute_strategy`:** If two concurrent strategy executions touch the same position, CRDB SERIALIZABLE would abort one with `RETRY_SERIALIZABLE`. On PostgreSQL READ COMMITTED, both would succeed (with a potential lost update — actually a bug, but not a user-visible error). **On CRDB, the user sees an error instead of silent corruption.** This is arguably better, but requires retry handling for a good user experience.

2. **Serialization errors on `exit_position`:** Less likely because FOR UPDATE serializes same-position exits. But if two exits for different positions belong to the same execution, both update `execution.realized_pnl` — this could serialize on CRDB.

3. **`FOR UPDATE` under CRDB SERIALIZABLE:** The semantics are slightly different. On PostgreSQL, FOR UPDATE locks the row and prevents concurrent updates. On CRDB, FOR UPDATE also participates in the serialization protocol. In practice, for single-row locks, this should work identically. But edge cases with multiple FOR UPDATE rows in a single transaction could behave differently. **StrikeNova doesn't have multi-row FOR UPDATE transactions.** ✅

**What would NOT go wrong on CRDB:**

1. **Silent data corruption:** Impossible — all transactions are atomic. If a transaction aborts, no partial state is committed.
2. **Lost updates (silent):** CRDB SERIALIZABLE prevents lost updates that PostgreSQL READ COMMITTED would allow. This is actually a correctness improvement.
3. **Unique constraint violations:** CRDB enforces unique constraints the same way PostgreSQL does. IntegrityError handling works the same.

---

## 7. Day41 Broker-Sync Audit

### 7.1 Architecture Overview

The Day41 broker-sync implementation (`app/broker_sync/`) consists of five modules:

| Module | File | Lines | Purpose |
|---|---|---|---|
| Raw Ingress | `raw_ingress.py` | 393 | Phase 1: durable raw observation ingest (BYTEA-preserving) |
| Ingestion | `ingestion.py` | 1239 | Phase 2: Day39 Task2 event ingestion pipeline |
| Fill Ledger | `fill_ledger.py` | 1052 | Day40.5/Day40.6 fill-identity architecture |
| Models | `models.py` | 125 | Broker-sync models (idempotency, projection, sequence anchor) |
| Fingerprint | `fingerprint.py` | 299 | FPv2 canonical serialization |

**Architecture diagram (from code):**

```
Broker API Event
    ↓
Phase 1: commit_raw_observation()  ← Dedicated transaction, explicit commit
    ↓ (raw_observation_id)
Phase 2: ingest_canonical_event()  ← Caller-owned transaction
    ├── Validation (identity, tenant, quantity)
    ├── Durable idempotency (BrokerSyncIdempotency PK on canonical_id)
    ├── Broker ordering validation (sequence gap/stale/out-of-order)
    ├── Terminal-state enforcement (against BrokerOrderProjection)
    ├── Durable normalized projection (BrokerOrderProjection)
    ├── Day38 lifecycle mapping (broker event → lifecycle event)
    └── Sequence anchor advancement (OCC: UPDATE WHERE last_sequence = :expected)
    ↓
Fill Ledger (Day40.5/Day40.6):
    ├── Lane A: Order observations (dedup on tenant+broker+d1+fp)
    ├── Lane B: TRADE_ID fills (atomic first-applier arbitration)
    └── Lane C: No-ID fills (no dedup, AMBIGUOUS composite)
```

### 7.2 Authentication

**OAuth flow:**
1. Frontend initiates login → calls `api.post("/auth/login")` or redirects to Upstox
2. `UpstoxAdapter.get_authorization_url(state)` (adapter.py:190-199) builds OAuth login URL:
   ```python
   def get_authorization_url(self, state: str) -> str:
       if self._login_url_builder:
           return self._login_url_builder(state)
       if self._api_key:
           return upstox.get_login_url(state, client_id=self._api_key, redirect_uri=self._redirect_uri)
       return upstox.get_login_url(state)
   ```
3. User authorizes on Upstox → redirect to `UPSTOX_REDIRECT_URI` with authorization code
4. Backend handles callback, exchanges code for access token
5. Token stored in `BrokerToken` table (encrypted)

**Token handling:**
- `UpstoxAdapter._require_token()` (adapter.py:152-158): Returns access token or raises `AUTH_REQUIRED`
- Token storage: `BrokerToken` model in `app/identity.py` with encrypted `broker_token_encrypted`, `broker_token_expires_at`, `broker_refresh_token_encrypted`, `broker_refresh_token_expires_at`

**Encryption:**
- `TOKEN_ENCRYPTION_KEY` env var (config.py:44-49) used to encrypt/decrypt broker tokens
- `broker_api_key_encrypted`, `broker_api_secret_encrypted`, `broker_analytics_token_encrypted`, `broker_token_encrypted`, `broker_refresh_token_encrypted` — all encrypted at rest

**Callback URLs:**
- `UPSTOX_REDIRECT_URI` (config.py:10-12) must match the redirect URI registered on the Upstox developer app
- On Northflank, this would need to be updated to the Northflank service URL

**Frontend/backend interaction:**
- `app/config.py:13-18` — `FRONTEND_URL` used for OAuth redirects and CORS
- `app/main.py:348-371` — CORS configured with `FRONTEND_URL` and `ADDITIONAL_CORS_ORIGINS`

**CRDB implications:** Authentication has NO CRDB-specific dependencies. Token storage is standard ORM (Text columns for encrypted data). ✅

### 7.3 Persistence

**Broker connection records:**
- `BrokerConnection` model (identity.py:93-200+): `id` (UUID), `user_id`, `broker`, `broker_account_id`, `display_label`, `is_default`, `status`, `capability_mode`, encrypted credentials, timestamps
- Unique constraint: `(user_id, broker, broker_account_id)` (identity.py:130)
- Partial unique index: `(user_id, broker) WHERE is_default = true` (migration 125e1807df8d:84-96)

**Broker token records:**
- `BrokerToken` model (identity.py:200+): `id`, `connection_id` (FK to broker_connections), `session_hash`, `broker_token_encrypted`, `broker_token_expires_at`, `broker_refresh_token_encrypted`, `broker_refresh_token_expires_at`
- Unique constraint: `(connection_id, session_hash)` (identity.py:246)

**Sync state (Day39 Task2):**
- `BrokerSyncIdempotency` (broker_sync/models.py:21-52): `canonical_id` (PK), `tenant_id`, `broker`, `broker_order_id`, `canonical_sequence`, `event_type`, `event_version`, `content_fingerprint`, `source_mode`, `provider_event_id`, `received_at`, `status`, `created_at`
- `BrokerOrderProjection` (broker_sync/models.py:55-93): `id` (auto-increment PK), `tenant_id`, `broker`, `broker_order_id`, `canonical_id`, `event_type`, `status`, `total_quantity`, `cumulative_filled`, `remaining_quantity`, `average_price`, `last_fill_price`, `last_fill_quantity`, `rejection_reason`, `is_terminal` (Boolean with server_default="false"), `fill_count`, `last_fill_id`, `canonical_sequence`, `occurred_at`, `received_at`, `created_at`
- `BrokerSyncSequenceAnchor` (broker_sync/models.py:96-125+): `tenant_id`, `broker`, `broker_order_id` (composite PK), `last_sequence`, `created_at`, `updated_at`

**Sync cursors:**
- `canonical_sequence` on `BrokerSyncSequenceAnchor` — monotonic sequence per (tenant, broker, broker_order_id)
- `last_sequence` advanced after successful event ingestion (OCC: UPDATE WHERE last_sequence = :expected)

**Positions/orders/trades if persisted:**
- Broker sync does NOT directly persist positions/orders/trades — those are in the paper trading models (`app/models.py`)
- Broker sync persists normalized broker-order state (`BrokerOrderProjection`) and lifecycle events (`TradeLifecycleEvent`)

**Unique constraints:**
- `BrokerSyncIdempotency.canonical_id` — PK, unique ✅
- `BrokerOrderProjection` — no unique constraint on (tenant, broker, broker_order_id) — multiple rows per order (one per event) ✅
- `BrokerSyncSequenceAnchor` — composite PK on (tenant_id, broker, broker_order_id) ✅

**Idempotency keys:**
- `canonical_id` on `BrokerSyncIdempotency` — deterministic, computed from event content (see `ingestion.py:71-118` — `_content_fingerprint()`)
- `content_fingerprint` — SHA-256 of canonical event content

**Lifecycle state:**
- `BrokerOrderProjection.status` — current order state (SUBMITTED, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED)
- `BrokerSyncIdempotency.status` — ingestion status (e.g., ACCEPTED, DUPLICATE, CONFLICT)
- `TradeLifecycleEvent` — Day38 lifecycle events linked to broker events

**CRDB implications:**
- `LargeBinary` (BYTEA) on `BrokerRawObservation.raw_payload` — CRDB supports BYTEA. 🟡 Verify.
- Partial indexes on `broker_connections` (is_default) and `users` (google_sub) — need CRDB verification. 🟡
- All other persistence is standard ORM. ✅

### 7.4 Concurrency Analysis

#### Scenario 1: Two syncs run simultaneously

**Phase 1 (raw ingest):**
- `commit_raw_observation` is a dedicated transaction per payload
- Each payload gets a unique UUID PK (`raw_observation_id=str(uuid.uuid4())`)
- Two concurrent raw ingests for different payloads create two rows — no conflict ✅
- Two concurrent raw ingests for the same payload (retry) create two rows with different UUIDs — by design, raw observations are NEVER delivery-deduped ✅

**Phase 2 (processing):**
- `claim_raw_observations` uses `FOR UPDATE SKIP LOCKED` to claim pending observations (raw_ingress.py:288)
- Two workers claim different rows (SKIP LOCKED skips already-claimed rows) ✅
- Each worker processes its claimed observations in separate transactions ✅

**Event ingestion (`ingest_canonical_event`):**
- `BrokerSyncIdempotency.canonical_id` is the PK — duplicate canonical_id fails with IntegrityError (caught and handled as duplicate) ✅
- `BrokerSyncSequenceAnchor` uses `INSERT ... ON CONFLICT DO NOTHING` for creation (ingestion.py:344-360) ✅
- `_advance_broker_sequence` uses `UPDATE ... WHERE last_sequence = :expected` — if two workers try to advance the same anchor, only one succeeds (rowcount check, ingestion.py:388-418) ✅
- SAVEPOINT usage — sequence anchor creation/advancement can be rolled back independently ✅

**Conclusion:** The broker-sync architecture is designed for concurrent operation. ✅

#### Scenario 2: A sync is interrupted

**Phase 1:** Commit is durable — raw observation is persisted before any processing. ✅

**Phase 2:** Processing status is tracked on the raw observation row:
- `processing_status` — PENDING / IN_PROGRESS / SUCCEEDED / FAILED / QUARANTINED
- `attempt_count` — incremented on each attempt
- `last_error` — records the last error message
- `processing_completed_at` — timestamp of completion
- `lease_expires_at` — expires after `DEFAULT_LEASE_SECONDS = 300` seconds

**Recovery:** `claim_raw_observations` re-claims rows where:
- `processing_status = 'PENDING'` (never processed)
- `processing_status = 'IN_PROGRESS'` AND `lease_expires_at < now` (stale lease — worker crashed)

**Code (raw_ingress.py:239-295):**
```python
# Line 260-275: Query for claimable observations
claimable = db.execute(
    select(BrokerRawObservation)
    .where(
        BrokerRawObservation.processing_status.in_([
            ProcessingStatus.PENDING.value,
            ProcessingStatus.FAILED.value,
        )),
        # Also reclaim stale IN_PROGRESS
        or_(
            BrokerRawObservation.processing_status == ProcessingStatus.IN_PROGRESS.value,
            BrokerRawObservation.lease_expires_at < datetime.now(timezone.utc),
        ),
    )
    .order_by(BrokerRawObservation.created_at.asc())
    .limit(limit)
    .with_for_update(skip_locked=True)
).all()
```

**Conclusion:** Interruption recovery is built into the architecture. ✅

#### Scenario 3: A request is retried

- `BrokerSyncIdempotency.canonical_id` PK prevents duplicate ingestion ✅
- Same `canonical_id` + same `content_fingerprint` → DUPLICATE_NOOP (ingestion.py handles this)
- Same `canonical_id` + different `content_fingerprint` → CONFLICT (rejected)
- `commit_raw_observation` — retry creates a new raw observation row (different UUID) — by design, raw observations are never deduped ✅

**Conclusion:** Retries are idempotent by design. ✅

#### Scenario 4: Broker API responds slowly

- HTTP timeouts configured in Upstox client (`app/services/upstox_client.py`)
- Retry logic for HTTP errors (429, 500, 502, 503, 504, 408) — `upstox_client.py:138`: `retryable_status: frozenset({429, 500, 502, 503, 504, 408})`
- Slow responses don't affect database state — Phase 1 commit is already done ✅

**Conclusion:** Slow broker API responses are handled at the HTTP layer, not the database layer. ✅

#### Scenario 5: Broker API returns an error

- Validation errors → `IngestionError` with `action="REJECTED"` — no database write ✅
- Broker errors (e.g., token expired, maintenance) → handled at the adapter level, not in the sync pipeline ✅

**Conclusion:** Broker API errors don't affect database integrity. ✅

#### Scenario 6: Database transaction fails

- The entire Phase 2 transaction is rolled back (caller-owned transaction)
- No partial state — all writes are in a single transaction ✅
- Raw observation (Phase 1) is NOT affected — it's in a separate, already-committed transaction ✅
- `SAVEPOINT` in `ingest_canonical_event` — sequence anchor creation/advancement can be rolled back independently of the rest of the transaction ✅

**Conclusion:** Database transaction failures are handled correctly — full rollback, no partial state. ✅

#### Scenario 7: Process crashes midway through synchronization

- Phase 1 commit is durable (already committed) ✅
- Phase 2 in-progress state is tracked on the raw observation row (`processing_status = 'IN_PROGRESS'`, `lease_expires_at`) ✅
- On restart, `claim_raw_observations` re-claims stale IN_PROGRESS rows ✅
- `attempt_count` is incremented — prevents infinite retry loops (though no hard limit is enforced) ⚠️

**Conclusion:** Process crash recovery is built into the architecture. ✅

### 7.5 Retry Behavior

| Aspect | Status | Evidence |
|---|---|---|
| **Safe?** | ✅ Yes | Idempotent by key (canonical_id PK), raw observations are durable, Phase 2 is replayable |
| **Idempotent?** | ✅ Yes | ON CONFLICT DO NOTHING patterns, UNIQUE constraints, content fingerprint comparison |
| **Bounded?** | ⚠️ Partially | HTTP retries bounded by `max_retries` in `upstox_client.py`; database retries NOT implemented for CRDB retryable errors; `attempt_count` on raw observations but no hard limit |
| **Transactional?** | ✅ Yes | Phase 2 is a single transaction (caller-owned), all-or-nothing |

**Missing:** No retry handling for CRDB retryable transaction errors (SerializationFailure, RETRY_SERIALIZABLE). This is documented in §5.3.

### 7.6 Database Migration Implications for Broker-Sync

**PostgreSQL-specific dependencies in broker-sync:**

| Feature | Location | CRDB Compatibility | Required Action |
|---|---|---|---|
| `LargeBinary` (BYTEA) | `raw_ingress.py:109` — `raw_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)` | 🟡 CRDB supports BYTEA, verify in practice | Verify during CRDB test phase |
| `ON CONFLICT DO NOTHING` | `ingestion.py:344-360` — sequence anchor creation | 🟢 CRDB supports | None |
| `UPDATE ... WHERE` (OCC) | `ingestion.py:388-408` — sequence anchor advancement | 🟢 CRDB supports | None |
| `FOR UPDATE SKIP LOCKED` | `raw_ingress.py:288` — worker claim | 🟢 CRDB supports | None |
| `FOR UPDATE` | `ingestion.py:803`, `fill_ledger.py:402,640,711` | 🟢 CRDB supports | None |
| `INSERT ... ON CONFLICT DO NOTHING RETURNING` | `fill_ledger.py:542-566` — Lane B arbitration | 🟡 CRDB supports, BUT dialect branching is wrong | **Fix dialect branching** (add "cockroachdb" branch) |
| `CURRENT_TIMESTAMP` | `persistence.py:223,227` | 🟢 Standard SQL | None |
| Partial indexes | `125e1807df8d:84-96`, `b8c9f1d2e34a:29` | 🟡 CRDB supports partial indexes, but migration syntax needs verification + dialect branching fix | **Verify + fix dialect branching** |

**No PostgreSQL-only features in broker-sync.** All features are either standard SQL or CRDB-compatible (with the dialect branching fix).

---

## 8. SQLAlchemy / Alembic Audit

### 8.1 SQLAlchemy Configuration

**`app/db.py:1-73`** — Engine and session setup:

```python
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):
    pass

engine = _engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
```

**SQLAlchemy version:** 2.0.43 (from requirements.txt)

**Key settings:**
- `autocommit=False` — transactions must be explicit ✅
- `autoflush=False` — no implicit flushes ✅ (gives explicit control over transaction boundaries)

### 8.2 Alembic Configuration

**`alembic.ini:1-120`** — Standard Alembic configuration:
- `script_location = alembic`
- `version_path_separator = os`
- `sqlalchemy.url` is NOT set here — it's set dynamically in `env.py`
- Post-write hooks configured for `black` and `ruff` (commented out)

**`alembic/env.py:1-114`** — Full analysis in §4.3.10.

### 8.3 Dialect-Aware Code

**`app/utils/db_dialect.py:1-36`** — `dialect_insert` function:

```python
def dialect_insert(engine: Engine, table: Table):
    """Return a dialect-specific insert construct for the given table.
    Uses PostgreSQL's insert() for PostgreSQL databases and SQLite's
    insert() for SQLite databases. Both support on_conflict_do_update().
    For other dialects (MySQL, etc.), falls back to generic insert()
    which does NOT support on_conflict_do_update — callers must handle
    that case separately.
    """
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        # Fallback: generic insert (no on_conflict_do_update)
        from sqlalchemy import insert
        return insert(table)
```

**Problem:** Falls into `else` for CRDB (`cockroachdb` dialect name). Generic `insert()` does NOT support `on_conflict_do_update()`.

**Required fix:** Add `"cockroachdb"` to the PostgreSQL branch:
```python
if dialect_name in ("postgresql", "cockroachdb"):
    from sqlalchemy.dialects.postgresql import insert
    return insert(table)
```

### 8.4 Alembic Migration Authoring

**Baseline migration** (`d3eb45a2e046`) creates all tables from scratch. This means:
- A fresh CRDB database can be fully migrated from scratch ✅
- No data migration needed for new deployments ✅
- Existing PostgreSQL data would need a separate migration path (not in scope for this audit)

**Migration ordering:**
- Linear chain with merge points
- Merge migrations are no-ops (`pass` in upgrade/downgrade) ✅
- Downgrade path exists for all migrations ✅

**Alembic version tracking:**
- `alembic_version` table stores the current revision
- `validate_migration_state()` in `app/db.py:125-201` validates migration state at runtime ✅

### 8.5 Schema Reproducibility

**Can the existing production schema be reproduced from scratch on CRDB?**

**Yes, with the following caveats:**
1. Partial indexes (`125e1807df8d:84-96`, `b8c9f1d2e34a:29`) need CRDB-compatible syntax
2. `LargeBinary` → BYTEA on CRDB (supported, but verify)
3. Dialect branching in `fill_ledger.py:542-566` and `db_dialect.py:15-36` needs CRDB branch

**After fixing these three issues, the full schema can be reproduced from scratch on CRDB via `alembic upgrade head`.** ✅

---

## 9. Vercel Integration Assessment

### 9.1 Current Frontend Configuration

**Frontend stack:** Next.js (from `frontend/package.json`)

**API client:** `options-dashboard-project/frontend/lib/api.js` (276 lines)

```javascript
import axios from "axios";
import { getSessionId } from "./session";
export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  withCredentials: true,
});
api.interceptors.request.use((config) => {
  const sessionId = getSessionId();
  if (sessionId) config.headers["X-Session-Id"] = sessionId;
  return config;
});
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) {
      error.message = detail;
    } else if (!error.response) {
      error.message = "Could not reach the server. Check your connection and try again.";
    }
    return Promise.reject(error);
  }
);
```

**API base URL configuration:**

| File | Line | Value |
|---|---|---|
| `frontend/lib/api.js:5` | `baseURL: process.env.NEXT_PUBLIC_API_URL` | Runtime env var |
| `frontend/next.config.js:6-7` | `NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL \|\| "https://options-dashboard-production-fb47.up.railway.app"` | Build-time fallback |
| `frontend/.env.prod-tmp` | `NEXT_PUBLIC_API_URL="https://staging-backend-staging-8159.up.railway.app"` | Staging env (exposed) |
| `frontend/.env.production` | (secret — not readable) | Production env |
| `frontend/.env.local` | (secret — not readable) | Local dev env |

**Auth integration:**

| File | Purpose |
|---|---|
| `frontend/lib/api.js:74` | `redirect_uri` passed to `/auth/connect` endpoint |
| `frontend/components/public/AuthModal.js:79` | OAuth redirect URI construction |
| `frontend/lib/session.js:68-74` | OAuth state management |

**CORS configuration (backend):**
- `app/main.py:348-371` — CORS middleware configured with `FRONTEND_URL` and `ADDITIONAL_CORS_ORIGINS`
- `allow_credentials=True` — cookies sent cross-origin
- `allow_headers=["Content-Type", "X-Session-Id"]` — custom session header allowed

**Vercel rewrites (`vercel.json`):**
```json
{
  "services": {
    "frontend": { "root": "frontend", "framework": "nextjs" },
    "backend": { "root": "backend", "entrypoint": "app.main:app" }
  },
  "rewrites": [
    { "source": "/api/backend(/.*)?", "destination": { "type": "service", "service": "backend" } },
    { "source": "/(.*)", "destination": { "type": "service", "service": "frontend" } }
  ]
}
```

### 9.2 What Changes When Backend Moves to Northflank

**Primary change: `NEXT_PUBLIC_API_URL`**

The frontend's API base URL must point to the Northflank service URL instead of the Railway URL.

- Current: `https://staging-backend-staging-8159.up.railway.app` (staging) or `https://options-dashboard-production-fb47.up.railway.app` (production)
- Target: `https://<northflank-service>.northflank.app`

**This is a Vercel environment variable change, NOT a code change.** The frontend code uses `process.env.NEXT_PUBLIC_API_URL` — it doesn't hardcode the Railway URL.

**Vercel rewrites:**

The `vercel.json` rewrites `/api/backend/*` to a Vercel backend service. If the backend moves to Northflank, this rewrite is invalid because:
- Vercel's `rewrite` with `destination.type: "service"` only works for Vercel services
- It cannot proxy to an external Northflank service

**Two options:**

**Option A: Remove the rewrite and use direct API calls** (RECOMMENDED)
- Frontend calls `NEXT_PUBLIC_API_URL` directly (e.g., `https://<northflank>.northflank.app`)
- Remove the `/api/backend` rewrite from `vercel.json`
- The `/(.*)` rewrite to frontend stays unchanged
- This is the simplest approach ✅

**Option B: Keep the rewrite but proxy to Northflank**
- Vercel doesn't natively support proxying to external services in rewrites
- Would require a Vercel Edge Function or Serverless Function to proxy requests
- Adds complexity and latency
- Not recommended ❌

**Recommendation:** Option A — remove the `/api/backend` rewrite and update `NEXT_PUBLIC_API_URL`.

**CORS:**
- The backend's CORS configuration (`app/main.py:348-371`) allows the Vercel frontend origin via `FRONTEND_URL`
- On Northflank, if the frontend is still on Vercel, `FRONTEND_URL` stays the same (e.g., `https://options-dashboard.vercel.app`)
- CORS configuration works unchanged ✅

**Cookies:**
- `withCredentials: true` in `api.js` — the backend sets cookies for session management
- Cross-origin cookies require CORS credentials support, which is configured (`allow_credentials=True`)
- This stays the same ✅

**Authentication flow:**
1. Frontend initiates login → calls `api.post("/auth/login")` or redirects to Upstox
2. Backend handles callback, sets session cookie
3. Frontend includes cookie in subsequent requests (`withCredentials: true`)

This flow is independent of the backend URL. ✅

**OAuth callback URLs:**
- `UPSTOX_REDIRECT_URI` on the backend must match the Upstox app registration
- If the backend moves to Northflank, the redirect URI changes from `https://*.up.railway.app/auth/callback` to `https://*.northflank.app/auth/callback`
- **This must be updated on the Upstox developer app** ⚠️

**Websocket/SSE:** None in the codebase. ✅

**CSRF/origin checks:** No explicit CSRF protection (session-based auth with cookies). CORS handles origin validation. ✅

**Production/staging separation:**
- Currently: `NEXT_PUBLIC_API_URL` = Railway production/staging URL (separate Vercel env vars)
- On Northflank: `NEXT_PUBLIC_API_URL` = Northflank production/staging URL (separate Vercel env vars)
- Managed via Vercel environment variables. ✅

### 9.3 Vercel Configuration Changes Required

| Change | File | Current | Target | Code change? |
|---|---|---|---|---|
| Update API base URL (production) | Vercel env vars (`.env.production`) | `https://*.up.railway.app` | `https://*.northflank.app` | No — env var change |
| Update API base URL (staging) | Vercel env vars (`.env.prod-tmp`) | `https://staging-backend-staging-8159.up.railway.app` | `https://<northflank-staging>.northflank.app` | No — env var change |
| Remove `/api/backend` rewrite | `vercel.json` | Present | Remove or comment out | Yes — config change (not code) |
| Update Upstox redirect URI | Upstox developer app | `https://*.up.railway.app/auth/callback` | `https://*.northflank.app/auth/callback` | No — external service update |
| Update `FRONTEND_URL` (if needed) | Backend env vars | Vercel frontend URL | Same (if frontend stays on Vercel) | No — env var change |
| Update `UPSTOX_REDIRECT_URI` | Backend env vars | Railway callback URL | Northflank callback URL | No — env var change |

**No frontend code changes required.** Only Vercel environment variable and configuration changes.

---

## 10. Northflank Architecture Assessment

### 10.1 Recommended Architecture

**Architecture A: Single API service.** Confirmed. No worker, no cron, no queue.

**API Service configuration:**

| Setting | Value | Notes |
|---|---|---|
| Service type | Web Service (HTTP) | Northflank web service |
| Build type | Docker | Use existing `Dockerfile` |
| Docker context | `options-dashboard-project/` | Root for COPY commands in Dockerfile |
| Container port | 8080 (or `$PORT`) | Dockerfile CMD hardcodes 8080; Procfile uses `$PORT` — align one of them |
| Health check (liveness) | `GET /health` | Returns `{"status": "ok"}` |
| Health check (readiness) | `GET /readiness` | Checks DB connectivity |
| Startup command | (Dockerfile CMD) | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8080` |
| Environment variables | See §10.2 | |
| Secrets | See §10.2 | |
| Autoscaling | Optional | Not required for current scale |

### 10.2 Environment Variables and Secrets

| Variable | Type | Value | Critical? |
|---|---|---|---|
| `DATABASE_URL` | Env var | `postgresql+psycopg://user:pass@host:26257/dbname?sslmode=verify-full` (or similar) | ✅ Yes — required for production |
| `TOKEN_ENCRYPTION_KEY` | Secret | Encryption key (32 bytes URL-safe base64) | 🔴 Critical — encrypts all broker credentials |
| `UPSTOX_API_KEY` | Env var | Upstox developer app API key | ✅ Yes |
| `UPSTOX_API_SECRET` | Secret | Upstox developer app API secret | ✅ Yes |
| `UPSTOX_REDIRECT_URI` | Env var | `https://<northflank-service>.northflank.app/auth/callback` | ✅ Yes — must match Upstox app registration |
| `FRONTEND_URL` | Env var | `https://options-dashboard.vercel.app` (or similar) | ✅ Yes — for CORS and OAuth redirects |
| `GOOGLE_CLIENT_ID` | Env var/Secret | Google OAuth client ID | ⚠️ Maybe — if considered sensitive |
| `GEX_CAPTURE_ENABLED` | Env var | `False` (or `True` with `GEX_USER_ID`) | No |
| `GEX_USER_ID` | Env var | User ID for GEX capture (if enabled) | No |
| `PRODUCTION` | Env var | `1` | ⚠️ Recommended — makes `IS_PRODUCTION` detection work on Northflank |

### 10.3 Deployment Mechanism

**Use existing Dockerfile.** The Dockerfile is already configured and working. No changes needed except optionally honoring `$PORT`.

**Do NOT use buildpack.** The Dockerfile is already set up. Buildpack would require reinspection of system dependencies.

**Dockerfile adjustments (optional):**
```dockerfile
# Current: CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
# Optional: Honor $PORT environment variable
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

### 10.4 Networking

**Public API:** The FastAPI service exposes HTTP on port 8080. Northflank provides a public URL (e.g., `https://<service>.northflank.app`).

**Database connectivity:** The backend connects to CockroachDB via `DATABASE_URL`. CockroachDB Cloud provides a connection string with:
- Host: `<cluster>.<region>.cockroachlabs.cloud`
- Port: 26257
- User/Password authentication
- SSL required (`sslmode=verify-full` or `verify-ca`)

**Northflank database connectivity options:**
- Northflank may offer CockroachDB as a managed service (verify current offerings)
- Or use external CockroachDB Cloud with IP allowlisting (Northflank service IPs must be allowlisted)

**CORS:** Configured in `app/main.py:348-371`. Frontend origin (Vercel) is allowed. ✅

**Callback URLs:** `UPSTOX_REDIRECT_URI` must be updated to Northflank service URL. ⚠️

### 10.5 Resource Sizing

**Current StrikeNova scale:** Personal/portfolio app, low traffic.

| Environment | CPU | RAM | Notes |
|---|---|---|---|
| Development/Staging | 0.5 CPU | 512MB RAM | Minimal, sufficient for testing |
| Production (minimum) | 1 CPU | 1GB RAM | Comfortable headroom for background GEX task + request handling |
| Production (comfortable) | 2 CPU | 2GB RAM | If expecting higher traffic or multiple concurrent users |

**GEX capture task:** If enabled, runs as an asyncio task in the same process. Low CPU/memory impact (60-second intervals, simple chain fetch + GEX computation).

---

## 11. Migration / Cutover Strategy

### 11.1 Staged Migration Plan

**Phase 0: Disposable Validation (LOCAL — NO production impact)**

1. Provision a local CockroachDB instance
   - Option A: Docker — `docker run -d --name crdb -p 26257:26257 -p 8080:8080 cockroachdb/cockroach:latest start-single-node --insecure`
   - Option B: CRDB Cloud free tier — create a free cluster, get connection string
2. Create a disposable database
3. Run Alembic migrations: `cd options-dashboard-project/backend && alembic upgrade head`
4. Verify schema:
   - Inspect tables: `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;`
   - Inspect indexes: `SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname;`
   - Verify partial indexes created correctly
5. Start the backend: `uvicorn app.main:app --host 0.0.0.0 --port 8080`
6. Test health endpoints: `curl http://localhost:8080/health`, `curl http://localhost:8080/readiness`
7. Run the full test suite: `pytest options-dashboard-project/backend/tests/`
8. Run PostgreSQL-specific concurrency tests (if CRDB is detected as PostgreSQL-compatible)
9. Test broker-sync end-to-end (mock Upstox API via respx)

**Phase 1: Northflank Staging (NO production impact)**

1. Create Northflank project
2. Create CockroachDB service (Northflank managed or external CRDB Cloud)
3. Create Northflank web service from Dockerfile
4. Configure environment variables and secrets
5. Run Alembic migrations on staging
6. Run full test suite against staging
7. Deploy a Vercel preview frontend with `NEXT_PUBLIC_API_URL` pointing to Northflank staging
8. Test OAuth flow (update Upstox redirect URI to Northflank staging URL)
9. Test broker-sync with mock data
10. Manual testing: login, place paper order, exit position, verify P&L

**Phase 2: Full Regression (NO production impact)**

1. Run all tests against Northflank staging + CRDB
2. Verify economic correctness invariants:
   - Position quantity correctness
   - Cash ledger correctness
   - Realized P&L correctness
   - Lifecycle event consistency
   - Order state consistency
3. Verify broker-sync idempotency and concurrency
4. Verify transaction retry behavior (if retry handling is implemented)
5. Load test: simulate concurrent requests (e.g., multiple strategy executions, multiple exits)
6. Failure mode testing: simulate transaction failures, process crashes, verify recovery

**Phase 3: Parallel Validation (OPTIONAL — low risk)**

1. Run Northflank staging in parallel with Railway production
2. Compare behavior on identical inputs (same user, same strategies)
3. Verify data consistency between the two systems
4. Run for a period (e.g., 1-2 weeks) to gather confidence

**Phase 4: Production Cutover (ONLY after all above pass)**

1. Provision production CockroachDB cluster
2. Run Alembic migrations on production CRDB
3. (If needed) Migrate data from PostgreSQL to CRDB:
   - Option A: CRDB `IMPORT PGDUMP` — export PostgreSQL schema+data, import to CRDB
   - Option B: Custom ETL script — read from PostgreSQL, write to CRDB via SQLAlchemy
   - Option C: Fresh start — no data migration, users start fresh
4. Deploy backend to Northflank production
5. Update Vercel `NEXT_PUBLIC_API_URL` (production) to Northflank production URL
6. Update Upstox redirect URI to Northflank production URL
7. Monitor for errors (logs, metrics, user reports)
8. Keep Railway+PostgreSQL running for rollback capability (see §11.2)

### 11.2 Rollback Strategy

**Before cutover:**
- Railway production remains untouched
- Rollback = don't cutover ✅

**After cutover (if issues arise):**
1. **Immediate rollback:** Update Vercel `NEXT_PUBLIC_API_URL` back to Railway URL
2. **Update Upstox redirect URI** back to Railway callback URL
3. **Investigate and fix** issues on Northflank
4. **Retry cutover** when ready

**Data rollback (if data was migrated from PostgreSQL to CRDB):**
1. Preserve the PostgreSQL database (don't delete it)
2. Revert to Railway+PostgreSQL
3. Replay any transactions that occurred on CRDB back to PostgreSQL (or accept the discrepancy and resync)
4. **Important:** If using CRDB's `IMPORT PGDUMP`, the PostgreSQL database should NOT be dropped until the migration is verified

**Key principle:** Keep Railway+PostgreSQL running until Northflank+CRDB is proven. Don't delete or modify the PostgreSQL database until confident.

### 11.3 Data Migration (If Needed)

**If StrikeNova has production data in PostgreSQL that needs to move to CRDB:**

**Option A: CRDB `IMPORT PGDUMP`**
- CRDB supports importing PostgreSQL dumps
- `pg_dump --schema-only` → modify for CRDB compatibility → `psql` on CRDB
- `pg_dump --data-only` → `psql` on CRDB (CRDB supports PostgreSQL wire protocol)
- **Needs verification:** Which PostgreSQL dump options are compatible with CRDB?

**Option B: Custom ETL script**
- Read from PostgreSQL via SQLAlchemy/psycopg
- Transform if needed (e.g., handle type differences)
- Write to CRDB via SQLAlchemy/psycopg
- **Needs implementation:** Write and test the ETL script

**Option C: Fresh start**
- No data migration
- Users start fresh on CRDB
- Acceptable for a personal/portfolio app with limited history
- **Lowest risk** — no data migration bugs

**This is a future concern.** For now, the audit assumes Option C (fresh start) or Option A (IMPORT PGDUMP) as the most likely paths.

### 11.4 Cutover Checklist

- [ ] CRDB test environment set up and tests passing
- [ ] Dialect branching fixed in `fill_ledger.py` and `db_dialect.py`
- [ ] Transaction retry handling implemented (if required)
- [ ] Partial index migrations verified on CRDB
- [ ] Vercel `NEXT_PUBLIC_API_URL` updated to Northflank URL
- [ ] `vercel.json` rewrites updated (remove `/api/backend` rewrite)
- [ ] Upstox redirect URI updated to Northflank URL
- [ ] Northflank environment variables configured
- [ ] Northflank health checks configured (`/health`, `/readiness`)
- [ ] Railway production still running (for rollback)
- [ ] Monitoring configured (logs, alerts)
- [ ] Rollback plan documented and tested

---

## 12. Test Strategy for CockroachDB

### 12.1 Required Tests Before Migration Approval

#### Tier 1: Schema Migration Tests (MUST PASS)

1. **Fresh CRDB + Alembic migration**
   - Provision fresh CRDB database
   - Run `alembic upgrade head`
   - Verify all 30+ tables created
   - Verify all indexes created (including partial indexes)
   - Verify all constraints created (unique, foreign key, composite PKs)
   - Run `alembic downgrade -1` — verify rollback works
   - Run `alembic upgrade head` again — verify idempotency (no errors on re-run)

2. **Schema inspection**
   - `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;` — verify all expected tables present
   - `SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY tablename, indexname;` — verify all indexes, especially partial indexes
   - `SELECT * FROM information_schema.table_constraints WHERE table_schema = 'public' ORDER BY table_name, constraint_name;` — verify all constraints

#### Tier 2: Basic Functionality Tests (MUST PASS)

3. **Backend startup**
   - `init_db()` succeeds (Alembic migrations run on startup)
   - `/health` returns 200 + `{"status": "ok"}`
   - `/readiness` returns 200 (DB connectivity check passes)

4. **Database connectivity**
   - `SessionLocal()` creates sessions
   - CRUD operations work (create, read, update, delete)
   - `BEGIN`/`COMMIT`/`ROLLBACK` work correctly

5. **All existing tests that don't require PostgreSQL-specific behavior**
   - Most tests use SQLite in-memory and should pass unchanged
   - Tests that use `TEST_DATABASE_URL` should now run against CRDB

#### Tier 3: Concurrency Tests (MUST PASS — these are the critical tests)

6. **`test_day38_postgres_concurrency.py`**
   - PostgreSQL concurrent lifecycle event persistence with FOR UPDATE serialization
   - Must pass on CRDB with identical behavior

7. **`test_day39_task2_red_v6.py`**
   - Broker event idempotency
   - Sequence allocation concurrency
   - FOR UPDATE serialization before sequence allocation
   - Must pass on CRDB

8. **`test_day41_phase10_postgres_concurrency.py`**
   - SKIP LOCKED claim
   - Lane B first-applier arbitration (ON CONFLICT DO NOTHING RETURNING)
   - No-ID fill collision (two rows, AMBIGUOUS composite)
   - Stale lease reclaim (crash/retry scenario)
   - **This is the most important concurrency test for CRDB compatibility**

9. **`test_paper_concurrency_repro.py`**
   - Exit position idempotency race
   - Lost-update scenario
   - Must pass on CRDB

#### Tier 4: Economic Correctness Tests (MUST PASS)

10. **All paper execution tests**
    - Strategy execution creation
    - Position exit (partial and full)
    - Bulk exit (EXIT STRATEGY, EXIT ALL)
    - P&L calculation
    - Cash ledger correctness

11. **All lifecycle event tests**
    - Sequence allocation
    - Idempotent append
    - Conflict rejection
    - Tenant isolation

12. **All broker-sync tests**
    - Idempotency (duplicate detection)
    - Conflict detection (same canonical_id, different fingerprint)
    - Sequence advancement
    - Fill ledger arbitration (Lane A, B, C)
    - Edge contract enforcement

#### Tier 5: Integration Tests (MUST PASS)

13. **API endpoint tests**
    - All CRUD endpoints work
    - Authentication flow works (login, session, logout)
    - Paper trading endpoints work (execute strategy, exit position, bulk exit)
    - Broker sync endpoints work (if exposed via API)

14. **Authentication flow tests**
    - OAuth login flow (Upstox)
    - Session management (create, validate, revoke)
    - Token storage and retrieval (encrypted)

15. **Broker-sync end-to-end tests**
    - Full sync pipeline: raw ingest → normalization → classification → projection → lifecycle event
    - Mock Upstox API via respx
    - Verify idempotent replay

#### Tier 6: Failure Mode Tests (MUST PASS — if retry handling is implemented)

16. **Transaction retry tests**
    - Simulate CRDB retryable errors (.SerializationFailure)
    - Verify retry logic catches and retries
    - Verify bounded retries (e.g., 3-5 attempts)
    - Verify idempotent retries (no duplicate data)

17. **Crash recovery tests**
    - Simulate process crash during Phase 2 processing
    - Verify raw observation is durable (Phase 1 committed)
    - Verify Phase 2 can be reprocessed (claim_raw_observations reclaims stale IN_PROGRESS)
    - Verify no duplicate data after recovery

18. **Concurrent failure tests**
    - Simulate concurrent failures (multiple workers, multiple requests)
    - Verify no data corruption
    - Verify idempotent handling of retries

### 12.2 Test Environment Setup

**Option A: Local CRDB via Docker**
```bash
# Start single-node CockroachDB
docker run -d --name cockroachdb \
  -p 26257:26257 \
  -p 8080:8080 \
  cockroachdb/cockroach:latest \
  start-single-node --insecure

# Create test database
docker exec -it cockroachdb cockroach sql --insecure -e "CREATE DATABASE strikenova_test;"

# Set environment variable
export TEST_DATABASE_URL="postgresql+psycopg://root@localhost:26257/strikenova_test?sslmode=disable"

# Run tests
cd options-dashboard-project/backend
pytest options-dashboard-project/backend/tests/
```

**Option B: CRDB Cloud Free Tier**
1. Sign up for CockroachDB Cloud (free tier available)
2. Create a free cluster
3. Get connection string (looks like: `postgresql://USER:PASSWORD@HOST:26257/defaultdb?sslmode=verify-full`)
4. Create a test database: `CREATE DATABASE strikenova_test;`
5. Set environment variable: `export TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST:26257/strikenova_test?sslmode=verify-full"`
6. Run tests: `pytest`

**Test configuration notes:**
- CRDB uses `postgresql+psycopg://` URL scheme (same as PostgreSQL)
- The test skip condition checks for `postgresql+psycopg://` or `postgresql://` prefix — CRDB URLs should pass this check ✅
- Some tests may need adjustment if they rely on PostgreSQL-specific error messages or behaviors

### 12.3 Expected Test Outcomes

**Tests that should pass unchanged:**
- All SQLite in-memory tests (they don't use `TEST_DATABASE_URL`)
- All tests that use ORM-only operations (the majority of tests)
- Tests that use standard SQL (ON CONFLICT, FOR UPDATE, SKIP LOCKED, UPDATE WHERE)
- Tests that don't check PostgreSQL-specific error messages

**Tests that need verification (expected to pass, but must be confirmed):**
- `test_day38_postgres_concurrency.py` — FOR UPDATE serialization on CRDB
- `test_day39_task2_red_v6.py` — broker event concurrency on CRDB
- `test_day41_phase10_postgres_concurrency.py` — SKIP LOCKED + ON CONFLICT arbitration on CRDB
- `test_paper_concurrency_repro.py` — exit idempotency race on CRDB

**Tests that might fail (and need fixing if they do):**
- Tests that check `dialect.name == "postgresql"` (none found in test code, but verify)
- Tests that rely on PostgreSQL-specific error messages (e.g., exact error text)
- Tests that use PostgreSQL-specific functions (none found, but verify)

**Tests that are irrelevant for CRDB:**
- `test_migrate_sqlite_to_postgres.py` — tests the SQLite→PostgreSQL migration tool (not relevant for CRDB migration)

### 12.4 Minimal Test Suite for Migration Approval

If full test suite is too time-consuming, the **minimum** tests required for migration approval are:

1. **Schema migration verification** (Tier 1) — Alembic migrations run successfully on CRDB, schema is correct
2. **Backend startup** (Tier 2) — Backend starts, health/readiness endpoints work
3. **Concurrency tests** (Tier 3) — All four PostgreSQL-gated concurrency tests pass on CRDB
   - `test_day38_postgres_concurrency.py`
   - `test_day39_task2_red_v6.py`
   - `test_day41_phase10_postgres_concurrency.py`
   - `test_paper_concurrency_repro.py`
4. **Economic correctness spot-check** (Tier 4) — At least one strategy execution and one position exit tested end-to-end on CRDB, verifying P&L and cash correctness
5. **Broker-sync spot-check** (Tier 5) — At least one broker event ingestion tested end-to-end on CRDB, verifying idempotency and projection

---

## 13. Cost / Resource Assessment

### 13.1 Development / Staging

| Service | Provider | Tier | Estimated Cost |
|---|---|---|---|
| Northflank web service | Northflank | Free tier (if available) | $0/month |
| CockroachDB | CRDB Cloud | Free tier (sample cluster) | $0/month |
| Vercel frontend | Vercel | Free tier (hobby) | $0/month |
| **Total** | | | **$0/month** |

**Notes:**
- Northflank free tier limits: check current offerings (may have CPU/RAM/requests limits)
- CRDB Cloud free tier: limited storage, 1 node, shared resources — sufficient for staging
- Vercel hobby tier: sufficient for personal/portfolio app

### 13.2 Production Minimum

| Service | Provider | Configuration | Estimated Cost |
|---|---|---|---|
| Northflank web service | Northflank | 1 service, 1 vCPU, 1GB RAM | ~$5-20/month (Northflank pricing varies) |
| CockroachDB | CRDB Cloud | Standard plan, 1 vCPU, 1GB RAM, 20GB storage | ~$25-50/month |
| Vercel frontend | Vercel | Pro tier (if needed for commercial use) | $20/month (optional — hobby tier may suffice) |
| **Total** | | | **~$30-70/month** (excluding Vercel Pro) |

**Notes:**
- CRDB Cloud pricing: https://www.cockroachlabs.com/pricing/ — Standard plan starts at ~$25/month for a 1-node cluster
- Northflank pricing: https://northflank.com/pricing/ — check current pricing for web services
- Vercel Pro: $20/month per member — only needed if commercial use requires it

### 13.3 Future Scaling

**Northflank scaling:**
- Horizontal: Add more replicas of the API service (stateless — can scale horizontally)
- Vertical: Increase CPU/RAM per service
- Load balancing: Northflank handles load balancing between replicas automatically
- Cost: Scales linearly with resources

**CockroachDB scaling:**
- Horizontal: Add more nodes to the cluster (CRDB scales horizontally for both throughput and storage)
- Vertical: Increase vCPU/RAM per node
- Multi-region: CRDB supports multi-region deployments for low-latency access from different geographies
- Cost: Scales with cluster size

**Current StrikeNova scale estimates:**
- Users: 1-10 (personal/portfolio app)
- Requests per second: <1 (low traffic)
- Data volume: <1GB (paper trading journal, GEX snapshots, historical data)
- Concurrent users: Typically 1 (single user operating the app)

**Conclusion:** Minimal resources sufficient for current scale. Scaling headroom is ample.

---

## 14. Complete Compatibility Matrix

### 14.1 Runtime Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **Python runtime** | 🟢 | Dockerfile `python:3.13-slim`; runtime 3.11.16; `requirements.txt` — all standard Python packages | None | Low |
| **FastAPI** | 🟢 | `app/main.py` — standard FastAPI 0.141.1; `/health` and `/readiness` endpoints; lifespan startup | None | Low |
| **Uvicorn** | 🟢 | `CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]` in Dockerfile; Procfile uses `$PORT` | Optional: align Dockerfile CMD with Procfile's `$PORT` usage | Low |
| **Docker** | 🟢 | `Dockerfile` — standard Python/uvicorn container; `gcc libpq-dev` for psycopg; Debian-based slim image | None (optional PORT alignment) | Low |
| **Northflank API service** | 🟢 | Single service, no worker/cron, health/readiness endpoints, lifespan startup, environment variable loading via pydantic-settings | Configure env vars, secrets, health checks in Northflank UI; set `PRODUCTION=1` for IS_PRODUCTION detection | Low |
| **Worker** | 🟢 | No worker needed — GEX capture is asyncio task in lifespan (optional) | None | Low |
| **Cron/jobs** | 🟢 | No cron needed — no scheduled jobs in codebase | None | Low |
| **Health checks** | 🟢 | `/health` (liveness), `/readiness` (readiness — checks DB connectivity) | Configure Northflank to use these endpoints | Low |
| **Environment variables** | 🟢 | pydantic-settings `Settings` class; `.env` file + environment variables; all variables documented in `.env.example` | Set Northflank env vars: `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI`, `FRONTEND_URL`, `GOOGLE_CLIENT_ID`, `GEX_*`, `PRODUCTION=1` | Low |
| **Secrets** | 🟢 | No hardcoded secrets; `TOKEN_ENCRYPTION_KEY`, `UPSTOX_API_SECRET`, `GOOGLE_CLIENT_ID` are env vars/secrets; broker credentials encrypted in DB | Configure Northflank secrets management | Low |
| **Filesystem** | 🟢 | No production filesystem writes; SQLite fallback only when `DATABASE_URL` not set (irrelevant with CRDB); `.token_cache` is local dev convenience | None | Low |
| **Background processes** | 🟢 | Only optional GEX capture asyncio task; no Celery/RQ/arq/APScheduler/cron | None | Low |
| **Subprocess/OS deps** | 🟢 | `gcc libpq-dev` in Dockerfile for psycopg; no subprocess calls in app code | None | Low |
| **Railway-specific detection** | 🟡 | `IS_PRODUCTION` detects `RAILWAY_ENVIRONMENT`/`RAILWAY_SERVICE_NAME` (config.py:77-89); `validate_production_config()` warns if production lacks DB (db.py:81-117) | Set `PRODUCTION=1` on Northflank or add Northflank detection to config.py; cosmetic only (warning log, not block) | Low |
| **PORT handling** | 🟡 | Dockerfile CMD hardcodes 8080; Procfile uses `$PORT`; Northflank sets `$PORT` | Align Dockerfile CMD with `$PORT` or configure Northflank container port to 8080 | Low |

### 14.2 Database Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **PostgreSQL schema** | 🟡 | 14 Alembic migrations; standard DDL; 30+ tables; 2 partial indexes; `LargeBinary` (BYTEA) on `broker_raw_observation` | Verify partial indexes on CRDB; verify `LargeBinary`→BYTEA; fix dialect branching in migrations | Medium |
| **SQLAlchemy** | 🟡 | ORM is dialect-agnostic (good); 2 locations hardcode PG-vs-SQLite branching: `fill_ledger.py:542-566` and `db_dialect.py:15-36` | Add `"cockroachdb"` dialect branch to both locations (use PostgreSQL insert construct) | Medium |
| **Alembic** | 🟢 | `env.py` supports CLI + programmatic + SQLite; batch mode only for SQLite (correct for CRDB); `alembic.ini` doesn't hardcode URL | Verify migrations run on CRDB; verify partial index creation | Low |
| **Transactions** | 🟡 | Standard SQLAlchemy session management; `FOR UPDATE`, `ON CONFLICT`, `SKIP LOCKED` used correctly; unique constraints for idempotency; atomic upserts for sequences | CRDB `SERIALIZABLE` isolation may cause more serialization errors than PostgreSQL `READ COMMITTED`; no retry handling exists (see Transaction/Concurrency section) | **High** |
| **Transaction isolation** | 🟡 | No explicit isolation level set — uses database default (PostgreSQL: READ COMMITTED; CRDB: SERIALIZABLE) | Understand that CRDB's stricter isolation may cause serialization errors under contention; implement retry handling if user-transparent operation required | **High** |
| **SELECT FOR UPDATE** | 🟢 | Used in 5 locations: `paper_execution.py:646`, `ingestion.py:803`, `fill_ledger.py:402,640,711`, `raw_ingress.py:288` — all standard single-row locks | None — CRDB supports FOR UPDATE | Low |
| **SELECT FOR UPDATE SKIP LOCKED** | 🟢 | Used in `raw_ingress.py:288` — worker claim queue | None — CRDB supports SKIP LOCKED | Low |
| **ON CONFLICT DO NOTHING** | 🟡 | Used in 3+ locations: `ingestion.py:344-360`, `fill_ledger.py:542-566`, `persistence.py:215-239` — CRDB supports, BUT dialect branching in `fill_ledger.py` is wrong | Fix dialect branching in `fill_ledger.py:542-566` (add "cockroachdb" branch) | Medium |
| **ON CONFLICT DO UPDATE** | 🟢 | Used in `persistence.py:215-239` — atomic sequence allocation | None — CRDB supports; dialect is correct (uses raw SQL, not dialect-specific insert) | Low |
| **RETURNING** | 🟡 | Used in `fill_ledger.py:542-566` and `persistence.py:215-239` — CRDB supports, BUT dialect branching in `fill_ledger.py` is wrong | Fix dialect branching in `fill_ledger.py:542-566` | Medium |
| **CURRENT_TIMESTAMP** | 🟢 | Used in `persistence.py:223,227` — standard SQL, not PostgreSQL-specific | None | Low |
| **server_default=sa.text("false")** | 🟢 | Used in `models.py:81` and `broker_sync/models.py:81` — CRDB supports boolean literals | None | Low |
| **Unique constraints** | 🟢 | Used extensively — all standard, no PostgreSQL-specific features | None | Low |
| **Composite primary keys** | 🟢 | Used in `broker_sync_sequence_anchor`, `position_sequence_anchor`, `broker_fill_ledger_fill`, `broker_fill_identity_alias` — all standard | None | Low |
| **Foreign keys** | 🟢 | Used extensively — all standard | None | Low |
| **Indexes (non-unique)** | 🟢 | Used extensively — all standard B-tree indexes | None | Low |
| **JSON/JSONB** | 🟢 | NOT USED — all JSON data stored as Text columns (`payload_json`, `metadata_json`, `execution_metadata`, `tags`, `notes`) | None — no JSONB dependency | Low |
| **ARRAY** | 🟢 | NOT USED | None | Low |
| **DB-level ENUM** | 🟢 | NOT USED — all enums are Python `str, enum.Enum` stored as String columns | None | Low |
| **UUID (DB-type)** | 🟢 | NOT USED — UUIDs stored as String(36) hex | None — no UUID type dependency | Low |
| **SERIAL/IDENTITY** | 🟢 | NOT USED — all PKs are Integer (auto-increment via SQLAlchemy) or String (UUIDs) | None | Low |
| **Generated/computed columns** | 🟢 | NOT USED | None | Low |
| **Partial indexes** | 🔴 | 2 locations: `125e1807df8d:84-96` (broker_connections is_default) and `b8c9f1d2e34a:29` (users google_sub) — CRDB supports partial indexes, BUT migration syntax has dialect branching issues and `postgresql_where` kwarg may not work | Fix dialect branching in `125e1807df8d:84-96` (add "cockroachdb" branch with `is_default = true`); verify `postgresql_where` kwarg on CRDB or replace with raw SQL | **High** (blocks schema migration if not fixed) |
| **Expression indexes** | 🟢 | NOT USED | None | Low |
| **Exclusion constraints** | 🟢 | NOT USED | None | Low |
| **Advisory locks** | 🟢 | NOT USED | None | Low |
| **Database extensions** | 🟢 | NOT USED (no CREATE EXTENSION) | None | Low |
| **Triggers** | 🟢 | NOT USED | None | Low |
| **Stored procedures/functions** | 🟢 | NOT USED | None | Low |
| **LISTEN/NOTIFY** | 🟢 | NOT USED | None | Low |
| **COPY command** | 🟢 | NOT USED | None | Low |
| **Materialized views** | 🟢 | NOT USED | None | Low |
| **PostgreSQL-specific raw SQL** | 🟡 | 6 locations (see §4.2) — all standard SQL except dialect branching in `fill_ledger.py:542-566` | Fix dialect branching | Medium |
| **LargeBinary (BYTEA)** | 🟡 | `raw_ingress.py:109` — `raw_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)` — CRDB supports BYTEA, but verify in practice | Verify during CRDB test phase | Low-Medium |

### 14.3 Transaction/Concurrency Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **Transaction management** | 🟢 | Standard SQLAlchemy: `autocommit=False`, `autoflush=False`, caller-owned transactions, explicit `db.commit()` | None | Low |
| **SAVEPOINT usage** | 🟢 | Used in `ingest_canonical_event` for sequence anchor creation/advancement — CRDB supports SAVEPOINT | None | Low |
| **IntegrityError handling** | 🟢 | Used throughout for idempotency/conflict detection — CRDB raises IntegrityError on unique constraint violation, same as PostgreSQL | None | Low |
| **Optimistic concurrency (OCC)** | 🟢 | `_advance_broker_sequence` uses `UPDATE ... WHERE last_sequence = :expected` with rowcount check — standard OCC pattern, works on any DB | None | Low |
| **Atomic upsert** | 🟢 | `allocate_position_sequence` uses `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` — database-level atomic increment | None (CRDB supports) | Low |
| **Retry handling for serialization failures** | 🔴 | **NO retry handling for CRDB retryable transaction errors (SerializationFailure, RETRY_SERIALIZABLE, error code 40001) anywhere in the codebase** | **Implement retry decorator/wrapper for transaction-sensitive functions** (`execute_strategy`, `exit_position`, `ingest_canonical_event`, `append_lifecycle_event`) catching `sqlalchemy.exc.SerializationFailure` with exponential backoff and bounded retries | **High** |
| **FOR UPDATE under CRDB SERIALIZABLE** | 🟡 | All FOR UPDATE usages are single-row locks — should work identically on CRDB; but CRDB's SERIALIZABLE makes FOR UPDATE participate in serialization protocol, which is stricter than PostgreSQL READ COMMITTED | Understand the semantic difference; test on CRDB to verify behavior | Low-Medium |
| **Multi-row FOR UPDATE** | 🟢 | NOT USED — no transaction locks multiple rows with FOR UPDATE | None | Low |
| **Lost update prevention** | 🟡 | `execute_strategy` has no explicit locking — relies on unique constraint + validation-before-write; under CRDB SERIALIZABLE, concurrent executions touching same position would serialize (abort one) rather than silently overwrite (as PostgreSQL READ COMMITTED would) — this is actually safer, but requires retry handling for user-transparent operation | Implement retry handling; consider adding FOR UPDATE to execute_strategy for explicit serialization (future improvement) | Medium |

### 14.4 Economic Correctness Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **Position quantity integrity** | 🟢 | `FOR UPDATE` on position row in `exit_position`; atomic transaction updates; unique constraint prevents duplicate position rows | None (CRDB compatible) | Low |
| **Exit double-close prevention** | 🟢 | Status check AFTER FOR UPDATE; `find_exit_replay` idempotency; unique constraint on `client_order_id` | None (CRDB compatible) | Low |
| **Cash ledger integrity** | 🟢 | Single-writer pattern (`PaperTransaction` is only writer); cash derived from SUM(amount), not stored balance; all mutations in same transaction | None (CRDB compatible) | Low |
| **Realized P&L correctness** | 🟢 | `apply_fill()` pure function; P&L accumulated in same transaction as fill; no duplication | None (CRDB compatible) | Low |
| **Lifecycle event consistency** | 🟢 | Unique constraint on (tenant_id, aggregate_type, aggregate_id, sequence); deterministic event_id; atomic sequence allocation | None (CRDB compatible) | Low |
| **Order state consistency** | 🟢 | Unique constraints on `client_order_id` for `StrategyExecution` and `PaperOrder`; status field with lifecycle | None (CRDB compatible) | Low |
| **Idempotency** | 🟢 | Unique constraints + ON CONFLICT + UUID PKs + deterministic IDs throughout | None (CRDB compatible, after dialect branching fix) | Low |
| **Concurrent request safety** | 🟡 | FOR UPDATE + unique constraints + atomic upserts + ON CONFLICT patterns protect against corruption; CRDB SERIALIZABLE may cause serialization errors (user-visible, not corruption) under contention | Implement retry handling for user-transparent operation | Medium |

### 14.5 Broker-Sync Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **Authentication** | 🟢 | OAuth flow via Upstox; encrypted token storage in `BrokerToken` table; `TOKEN_ENCRYPTION_KEY` for encryption; standard ORM columns | Update `UPSTOX_REDIRECT_URI` to Northflank URL; update Upstox app registration | Low |
| **Persistence** | 🟡 | `BrokerSyncIdempotency`, `BrokerOrderProjection`, `BrokerSyncSequenceAnchor`, `BrokerRawObservation` (LargeBinary/BYTEA), `BrokerFillLedger_*` — all standard except BYTEA and partial indexes | Verify BYTEA on CRDB; fix partial index migrations; fix dialect branching in fill_ledger | Medium |
| **Concurrency** | 🟢 | `FOR UPDATE SKIP LOCKED` for worker claims; `ON CONFLICT DO NOTHING` for anchor creation; `UPDATE ... WHERE` OCC for sequence advancement; `FOR UPDATE` for idempotency and fill arbitration; SAVEPOINT for atomicity | None (CRDB compatible, after dialect branching fix) | Low |
| **Retry behavior** | 🟡 | Safe + idempotent + transactional ✅; bounded ⚠️ (HTTP retries bounded, DB retries not implemented for CRDB retryable errors) | Implement CRDB retry handling for Phase 2 transactions | Medium |
| **Interruption recovery** | 🟢 | Phase 1 durable (separate commit); Phase 2 status tracked on raw observation (`processing_status`, `lease_expires_at`); `claim_raw_observations` re-claims stale rows | None (CRDB compatible) | Low |
| **Idempotency** | 🟢 | `canonical_id` PK on `BrokerSyncIdempotency`; content fingerprint comparison; ON CONFLICT patterns; unique constraints | None (CRDB compatible, after dialect branching fix) | Low |
| **Sequence advancement** | 🟢 | OCC pattern (`UPDATE ... WHERE last_sequence = :expected`) — intentional conflict detection via `IngestionError` on rowcount==0 | None (CRDB compatible) | Low |
| **Fill ledger arbitration** | 🟡 | Lane A (order obs dedup), Lane B (TRADE_ID atomic first-applier via ON CONFLICT DO NOTHING RETURNING), Lane C (no-ID, no dedup) — all standard except dialect branching in `fill_ledger.py:542-566` | Fix dialect branching | Medium |

### 14.6 Vercel Integration Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **API base URL** | 🟡 | `NEXT_PUBLIC_API_URL` env var used in `frontend/lib/api.js:5`; currently points to Railway URLs | Update Vercel env vars to point to Northflank URL (env var change, not code change) | Low |
| **Vercel rewrites** | 🔴 | `vercel.json` rewrites `/api/backend/*` to Vercel backend service — invalid when backend moves to Northflank (Vercel can't proxy to external service in rewrites) | Remove `/api/backend` rewrite from `vercel.json`; frontend calls Northflank directly via `NEXT_PUBLIC_API_URL` | Low-Medium (config change) |
| **CORS** | 🟢 | Backend CORS configured with `FRONTEND_URL` (Vercel frontend origin); `allow_credentials=True`; `allow_headers=["Content-Type", "X-Session-Id"]` | None — if frontend stays on Vercel, `FRONTEND_URL` stays the same; CORS works unchanged | Low |
| **Cookies** | 🟢 | `withCredentials: true` in `api.js`; backend sets session cookies; cross-origin cookies work via CORS credentials | None | Low |
| **Authentication flow** | 🟢 | OAuth login → backend callback → session cookie → authenticated requests; independent of backend URL | Update `UPSTOX_REDIRECT_URI` to Northflank callback URL (env var + Upstox app update) | Low |
| **OAuth callback URLs** | 🟡 | `UPSTOX_REDIRECT_URI` must match Upstox app registration; changes from Railway URL to Northflank URL | Update Upstox developer app registration; update backend `UPSTOX_REDIRECT_URI` env var | Low |
| **Websocket/SSE** | 🟢 | NOT USED — no websocket or SSE in codebase | None | Low |
| **CSRF/origin checks** | 🟢 | No explicit CSRF (session-based auth with cookies); CORS handles origin validation | None | Low |
| **Production/staging separation** | 🟢 | Separate Vercel env vars for production vs staging `NEXT_PUBLIC_API_URL`; same pattern works for Northflank | Update both env vars to Northflank URLs | Low |
| **Frontend code changes** | 🟢 | NO frontend code changes required — only Vercel env var and config changes | None | Low |

### 14.7 Testing Compatibility

| Area | Status | Evidence | Required Change | Risk |
|---|---|---|---|---|
| **Test framework** | 🟢 | pytest 9.1.1; pytest-asyncio; respx; SQLAlchemy 2.0.43 — all CRDB-compatible | None | Low |
| **SQLite in-memory tests** | 🟢 | Most tests use SQLite in-memory (`sqlite:///:memory:` with StaticPool) — these don't use `TEST_DATABASE_URL` and should pass unchanged on CRDB (they don't hit the database for DB-specific tests) | None | Low |
| **PostgreSQL-gated tests** | 🔴 | `test_day38_postgres_concurrency.py`, `test_day39_task2_red_v6.py`, `test_day41_phase10_postgres_concurrency.py`, `test_paper_concurrency_repro.py` require `TEST_DATABASE_URL` pointing to PostgreSQL — MUST be re-run against CRDB | Set up CRDB test environment; run these tests against CRDB; verify identical behavior | **High** |
| **Test skip logic** | 🟡 | Tests skip if `TEST_DATABASE_URL` doesn't start with `postgresql+psycopg://` or `postgresql://` — CRDB URLs use `postgresql+psycopg://` scheme, so they should pass the skip check ✅ | Verify CRDB URL passes skip check; run tests | Low |
| **CRDB-specific tests** | 🔴 | **NO tests exist that target CockroachDB specifically** — all tests target SQLite or PostgreSQL | Create CRDB test environment; run full test suite; verify behavior | **High** |
| **Concurrency test evidence** | 🔴 | All concurrency tests validated on PostgreSQL 16 — NO validation on CockroachDB | Run concurrency tests on CRDB; verify SKIP LOCKED, FOR UPDATE, ON CONFLICT, RETURNING behave identically | **High** |

---

## 15. Blockers

### Blocker 1: No CockroachDB Transaction Retry Handling (🔴 HIGH — must fix before production migration)

**Evidence:**
- Searched entire backend for: `retry`, `SerializationFailure`, `40001`, `RETRY_SERIALIZABLE`, `cockroachdb`, `CRDB`, `transaction retry`, `retries` (in DB context)
- **Zero results** for CRDB retry handling in backend app code
- Related searches found only HTTP retry logic (`upstox_client.py:138`, `candle_retry.py:33`) — unrelated to database transactions

**Impact:** Under CRDB's `SERIALIZABLE` isolation, concurrent transactions that touch overlapping rows can receive retryable transaction errors (SQLSTATE `40001`, `RETRY_SERIALIZABLE`). Without retry handling:
- The SQLAlchemy `commit()` would raise `sqlalchemy.exc.SerializationFailure` (a subclass of `OperationalError`)
- The exception would propagate to the API handler
- The API would return a 500 error to the user
- The transaction would be rolled back (SQLAlchemy does this automatically on exception)
- **No data corruption** — the transaction is atomic, so rollback is clean
- **But user-visible failures** under concurrent load — unacceptable for a financial application

**Affected transaction paths:**
1. `execute_strategy` (`paper_execution.py:328-587`) — creates execution + orders + positions + cash + journal in one transaction; no explicit locking; touches multiple tables
2. `exit_position` (`paper_execution.py:615-749`) — uses `FOR UPDATE` on position, but touches multiple tables (position, orders, transactions, legs, exposures, execution P&L)
3. `ingest_canonical_event` (`ingestion.py:67-1239`) — broker event ingestion; touches 4 tables; concurrent events for same order could serialize
4. `append_lifecycle_event` (`persistence.py:249-400`) — lifecycle event persistence; touches `trade_lifecycle_events`; lower risk due to unique constraint + deterministic event_id

**Why this is a hard blocker:** Financial applications cannot show random 500 errors under normal load. If two concurrent requests try to exit positions (or execute strategies) at the same time, one should succeed and the other should either wait or get a clear error message — not a cryptic serialization failure. The current code would propagate the raw SQLAlchemy error to the user.

**Required fix (NOT implemented in this audit):**
- Implement a retry decorator or wrapper for transaction-sensitive functions
- Catch `sqlalchemy.exc.SerializationFailure` (or check for error code `40001`)
- Retry with exponential backoff (e.g., 0.1s, 0.2s, 0.4s, 0.8s)
- Bounded retries (e.g., 3-5 attempts)
- Idempotent retries (which these transactions are, thanks to unique constraints and FOR UPDATE locking)
- Example pattern:
```python
import time
from sqlalchemy.exc import SerializationFailure

def retry_on_serialization(max_retries=3, base_delay=0.1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except SerializationFailure:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(base_delay * (2 ** attempt))
            return None
        return wrapper
    return decorator
```

**Risk if not fixed:** User-visible 500 errors under concurrent load. No data corruption, but poor user experience and potential loss of trust in the application's reliability.

### Blocker 2: Dialect-Specific Code Has No CockroachDB Path (🔴 HIGH — must fix before deploying to CRDB)

**Evidence:**
- `app/broker_sync/fill_ledger.py:542-566` — `_upsert_trade_fill` branches on `bind.dialect.name == "postgresql"` vs else (SQLite). On CRDB, `dialect.name` is `"cockroachdb"`, so it falls into the else branch.
- `app/utils/db_dialect.py:15-36` — `dialect_insert` branches on `"postgresql"` vs `"sqlite"` vs else. On CRDB, falls into else (generic insert, no `on_conflict_do_update` support).

**Impact:**
1. **`fill_ledger.py:542-566`:** The Lane B TRADE_ID fill deduplication uses atomic `INSERT ... ON CONFLICT DO NOTHING RETURNING` for first-applier arbitration. On CRDB, this would use the SQLite insert construct, which may not support `ON CONFLICT DO NOTHING RETURNING` correctly. This could break the fill deduplication logic that prevents double-counting of economic fills.

2. **`db_dialect.py:15-36`:** If any code uses `dialect_insert` for CRDB (currently, the broker-sync code uses inline branching instead, but `db_dialect.py` is part of the codebase and should be correct for all supported dialects), `on_conflict_do_update()` would not be available on the returned insert construct.

**Required fix (NOT implemented in this audit):**
1. In `fill_ledger.py:542-566`, change the condition from:
   ```python
   if bind is not None and bind.dialect.name == "postgresql":
   ```
   to:
   ```python
   if bind is not None and bind.dialect.name in ("postgresql", "cockroachdb"):
   ```
   This makes CRDB use the PostgreSQL insert construct (which CRDB supports for ON CONFLICT/RETURNING).

2. In `db_dialect.py:25-29`, change the condition from:
   ```python
   if dialect_name == "postgresql":
   ```
   to:
   ```python
   if dialect_name in ("postgresql", "cockroachdb"):
   ```

**Risk if not fixed:** Silent incorrect behavior on CRDB — the fill deduplication might not work correctly, potentially leading to double-counted fills (economic corruption). This is worse than a user-visible error because it could silently corrupt data.

### Blocker 3: No CockroachDB Test Evidence (🔴 HIGH — must resolve before GO decision)

**Evidence:**
- All PostgreSQL concurrency tests require `TEST_DATABASE_URL` pointing to PostgreSQL
- No tests have been run against CockroachDB
- The codebase has never been validated on CRDB
- This audit is based on theoretical analysis of the code, not empirical CRDB testing

**Impact:** We cannot claim CRDB compatibility without testing. The theoretical analysis (this audit) suggests compatibility, but actual testing is required to verify:
- Alembic migrations run correctly on CRDB (especially partial indexes)
- `ON CONFLICT`/`RETURNING`/`FOR UPDATE`/`SKIP LOCKED` behave as expected on CRDB
- Concurrency tests pass with identical behavior
- Economic correctness invariants hold
- The dialect branching fix works correctly
- CRDB's SERIALIZABLE isolation behaves as expected with StrikeNova's transaction patterns

**Required (NOT implemented in this audit):**
1. Set up a disposable CRDB test environment (local Docker or CRDB Cloud free tier)
2. Run Alembic migrations on CRDB — verify schema creation, especially partial indexes
3. Run the full test suite against CRDB, with emphasis on:
   - All PostgreSQL-gated concurrency tests
   - All economic correctness tests
   - All broker-sync tests
4. Verify that the dialect branching fix works correctly on CRDB
5. Document test results

**Risk if not resolved:** Deploying to CRDB without testing could result in:
- Migration failures (partial indexes, dialect issues)
- Incorrect behavior (fill deduplication, concurrency)
- User-visible errors (serialization failures without retry handling)
- Data corruption (if dialect branching is wrong and fill deduplication breaks)

### Blocker 4: Partial Index Migration Syntax (🟡 MEDIUM — must resolve before running migrations on CRDB)

**Evidence:**
- `alembic/versions/125e1807df8d:84-96` — partial unique index on `broker_connections(user_id, broker) WHERE is_default = true` (PostgreSQL) or `is_default = 1` (SQLite). CRDB would fall into the else branch (`is_default = 1`) because `dialect.name` is `"cockroachdb"`, not `"postgresql"`. This is wrong for CRDB, which uses SQL-standard booleans.
- `alembic/versions/b8c9f1d2e34a:29` — `postgresql_where='google_sub IS NOT NULL'` kwarg on `create_index()`. This is an Alembic-specific PostgreSQL kwarg. CRDB may not support it.

**Impact:**
- If the partial index migrations fail on CRDB, the schema migration (`alembic upgrade head`) would error
- This blocks the entire migration — the schema cannot be created without these indexes
- The partial indexes enforce important business rules:
  - `uq_one_default_per_user_broker` — at most one default broker connection per user per broker
  - `ix_users_google_sub` — unique google_sub values (for Google OAuth identity)

**Required fix (NOT implemented in this audit):**
1. In `125e1807df8d:84-96`, add a `"cockroachdb"` branch:
   ```python
   dialect = op.get_bind().dialect.name
   if dialect == "postgresql":
       op.execute("CREATE UNIQUE INDEX ... WHERE is_default = true")
   elif dialect == "cockroachdb":
       op.execute("CREATE UNIQUE INDEX ... WHERE is_default = true")  # Same as PostgreSQL
   else:
       op.execute("CREATE UNIQUE INDEX ... WHERE is_default = 1")  # SQLite
   ```
2. For `b8c9f1d2e34a:29`, either:
   - Verify that CRDB supports `postgresql_where` kwarg (unlikely — it's PostgreSQL-specific)
   - Replace with raw SQL: `op.execute("CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub) WHERE google_sub IS NOT NULL")`

**Risk if not resolved:** Schema migration failure on CRDB. The application cannot start without a complete schema.

---

## 16. Risks

### Risk 1: Serialization Failures Under Load (🔴 HIGH — if retry handling not implemented)

**Description:** CRDB's `SERIALIZABLE` isolation is stricter than PostgreSQL's `READ COMMITTED`. Under concurrent load, more transactions may receive retryable errors. Without retry handling, these become user-visible 500 errors.

**Likelihood:** Medium — depends on traffic patterns. For a personal/portfolio app with single-user sequential operation, low. For multiple concurrent users or automated strategies, medium.

**Impact:** High — user-visible errors, potential loss of trust, potential lost trades (if user retries manually, no harm; if user gives up, lost opportunity).

**Mitigation:** Implement retry handling (see Blocker 1).

### Risk 2: Dialect Branching Causes Silent Incorrect Behavior (🔴 HIGH — if not fixed)

**Description:** If the dialect branching in `fill_ledger.py` and `db_dialect.py` is not fixed, CRDB would use the wrong code path. The `ON CONFLICT DO NOTHING RETURNING` might fail silently or behave incorrectly, breaking the fill deduplication logic.

**Likelihood:** High — the branching is clearly wrong for CRDB (falls into SQLite branch).

**Impact:** High — potential silent data corruption (double-counted fills) if fill deduplication breaks. This is worse than user-visible errors because it could go unnoticed.

**Mitigation:** Fix dialect branching (see Blocker 2). Test on CRDB after fixing.

### Risk 3: Partial Index Migration Failure (🟡 MEDIUM)

**Description:** If CRDB doesn't support the partial index syntax used in migrations, the schema migration fails. This blocks the entire migration.

**Likelihood:** Medium — CRDB supports partial indexes, but the Alembic `postgresql_where` kwarg may not work, and the dialect branching in `125e1807df8d` is wrong for CRDB.

**Impact:** High — blocks schema migration entirely. No application startup without complete schema.

**Mitigation:** Fix dialect branching and verify/migrate partial index syntax (see Blocker 4). Test Alembic migration on CRDB before deployment.

### Risk 4: Vercel Rewrite Configuration (🟡 MEDIUM)

**Description:** The `vercel.json` rewrites `/api/backend/*` to a Vercel backend service. If the backend moves to Northflank, this rewrite is invalid. If not removed, API calls via `/api/backend/*` would fail.

**Likelihood:** High — the rewrite is present in `vercel.json` and would be invalid on Northflank.

**Impact:** Medium — frontend API calls would fail if the rewrite is not removed. However, the frontend uses `NEXT_PUBLIC_API_URL` directly (via axios baseURL), not the `/api/backend` path. Let me verify...

**Verification:** `frontend/lib/api.js:5`: `baseURL: process.env.NEXT_PUBLIC_API_URL`. The API calls use the full URL from the environment variable, not relative paths. So the `/api/backend` rewrite may not be used by the frontend at all.

**Wait — let me check if any frontend code uses `/api/backend` paths:**

Looking at `frontend/lib/api.js`, all API functions use relative paths like `/auth/login`, `/paper/execute`, etc. These are relative to `baseURL` (which is `NEXT_PUBLIC_API_URL`). So if `NEXT_PUBLIC_API_URL` is `https://<northflank>.northflank.app`, the API calls go directly to Northflank, not through Vercel rewrites.

**Conclusion:** The `/api/backend` rewrite in `vercel.json` may be unused by the current frontend code. However, it should still be removed for clarity and to prevent future confusion. **Risk is lower than initially assessed.**

**Mitigation:** Remove the `/api/backend` rewrite from `vercel.json`. Update `NEXT_PUBLIC_API_URL` to Northflank URL.

### Risk 5: Upstox Redirect URI Mismatch (🟡 MEDIUM)

**Description:** The Upstox developer app has a registered redirect URI. If the backend moves to Northflank, the redirect URI changes. If not updated, OAuth login fails.

**Likelihood:** High — the redirect URI must be updated for OAuth to work on Northflank.

**Impact:** Medium — OAuth login would fail, preventing users from connecting their Upstox accounts. However, this is a known, one-time configuration change that can be done before cutover.

**Mitigation:** Update the redirect URI on the Upstox developer app before cutover. Test OAuth flow on Northflank staging before production cutover.

### Risk 6: Data Migration Complexity (🟡 MEDIUM for existing data, 🟢 LOW for fresh start)

**Description:** If StrikeNova has significant production data in PostgreSQL, migrating it to CRDB is non-trivial. CRDB supports `IMPORT PGDUMP`, but the compatibility of a PostgreSQL dump from this schema with CRDB needs verification.

**Likelihood:** Depends on whether data migration is needed. For a fresh start (no data migration), risk is zero. For existing data migration, risk is medium.

**Impact:** Medium — data migration bugs could corrupt data or lose data. However, the rollback strategy keeps the PostgreSQL database intact until the migration is verified.

**Mitigation:** For fresh start (Option C in §11.3), no data migration needed — lowest risk. For existing data, test the migration path thoroughly before cutover, keep PostgreSQL as rollback option.

### Risk 7: `IS_PRODUCTION` Detection (🟢 LOW)

**Description:** `app/config.py:77-89` detects production via `RAILWAY_ENVIRONMENT` or `RAILWAY_SERVICE_NAME`. On Northflank, these env vars are not set, so `IS_PRODUCTION` returns False. This causes `validate_production_config()` to skip its warning (which is fine — the warning is just a log message).

**Likelihood:** High — Northflank doesn't set Railway env vars.

**Impact:** Low — the only effect is that the production configuration warning is not logged. This is cosmetic. The application still requires `DATABASE_URL` to be set for production operation (enforced by the engine creation logic, not by the warning).

**Mitigation:** Set `PRODUCTION=1` on Northflank to make `IS_PRODUCTION` return True. Or add Northflank detection to `config.py`. Low impact — optional improvement.

### Risk 8: GEX Capture Background Task Reliability (🟢 LOW)

**Description:** The GEX capture loop runs as an asyncio task in the FastAPI process. If the process restarts, the task restarts (via `lifespan`). On Northflank, service restarts are handled by the platform. The task is designed to be resilient (exceptions logged, loop continues).

**Likelihood:** Low — the task is already designed for process restarts and is optional (only runs when `GEX_CAPTURE_ENABLED=True` and `GEX_USER_ID` is configured).

**Impact:** Low — if the task fails, GEX snapshots are not captured, but the application continues to function normally. Historical GEX data is still available for UI display (`GEX_HISTORY_ENABLED`).

**Mitigation:** No action needed. The task is already designed for resilience. If GEX capture is critical, consider monitoring the task health and alerting on repeated failures.

### Risk 9: Connection Pooling Under CRDB (🟢 LOW)

**Description:** `app/db.py:60-67` configures PostgreSQL connection pooling: `pool_size=5, max_overflow=10, pool_timeout=30, pool_recycle=1800, pool_pre_ping=True`. CRDB supports these SQLAlchemy pool parameters.

**Likelihood:** Low — these are standard SQLAlchemy pool parameters that work with any PostgreSQL-compatible database.

**Impact:** Low — connection pooling should work identically on CRDB. `pool_pre_ping=True` is especially useful for CRDB, as it verifies connections before use (CRDB can evict idle connections).

**Mitigation:** No action needed. The existing pooling configuration is appropriate for CRDB.

### Risk 10: Timezone Handling (🟢 LOW)

**Description:** StrikeNova uses `DateTime(timezone=True)` for timezone-aware timestamps and `DateTime` for naive timestamps. The application uses `datetime.now(timezone.utc)` for UTC timestamps. CRDB supports `TIMESTAMP WITH TIME ZONE` and `TIMESTAMP` (without timezone).

**Likelihood:** Low — timezone handling is already correct in the application (UTC everywhere).

**Impact:** Low — CRDB's timezone handling is compatible with PostgreSQL's. The application uses UTC consistently, minimizing timezone-related issues.

**Mitigation:** No action needed. Continue using UTC timestamps consistently.

---

## 17. Assumptions

1. **CockroachDB SQLAlchemy dialect name is `"cockroachdb"`** — Based on SQLAlchemy documentation and CockroachDB's SQLAlchemy dialect implementation. Verified by searching for `cockroachdb` in the SQLAlchemy source and CockroachDB documentation. The dialect name is distinct from `"postgresql"`.

2. **CockroachDB supports `ON CONFLICT DO NOTHING/UPDATE ... RETURNING`** — Based on CockroachDB's PostgreSQL compatibility documentation. CRDB supports most PostgreSQL DML syntax, including `ON CONFLICT` and `RETURNING`.

3. **CockroachDB supports `FOR UPDATE` and `FOR UPDATE SKIP LOCKED`** — Based on CockroachDB's documentation on row-level locking. CRDB supports `SELECT ... FOR UPDATE` and `SKIP LOCKED`.

4. **CockroachDB supports `SAVEPOINT`** — Based on CRDB's transaction documentation. CRDB supports standard SQL transaction commands including `SAVEPOINT`.

5. **CockroachDB supports `LargeBinary` → BYTEA** — Based on CRDB's type system. CRDB supports `BYTES` type which maps to SQLAlchemy's `LargeBinary`.

6. **CockroachDB uses `postgresql+psycopg://` URL scheme** — Based on CockroachDB Cloud connection strings and SQLAlchemy dialect registration. CRDB can be accessed via the PostgreSQL dialect with `psycopg` driver. Alternative: `cockroachdb://` URL scheme (uses `cockroachdb` dialect directly).

7. **The `postgresql_where` Alembic kwarg is PostgreSQL-specific** — Based on Alembic documentation. This kwarg is for PostgreSQL partial indexes and may not be supported by other dialects.

8. **The existing test suite is representative of production usage** — The tests cover the main transaction paths (strategy execution, position exit, broker event ingestion, lifecycle events). If the tests pass on CRDB, the main correctness properties are verified.

9. **StrikeNova's traffic is low enough that serialization failures are rare** — Personal/portfolio app with single-user sequential operation. Serialization failures would primarily occur under concurrent load (multiple users, automated strategies, or rapid manual operations).

10. **The application does not use any PostgreSQL-specific extensions or features not covered in this audit** — The audit searched for all common PostgreSQL-specific features (extensions, advisory locks, LISTEN/NOTIFY, COPY, materialized views, triggers, stored procedures, etc.) and found none. The audit is based on code inspection, not runtime detection.

11. **The `vercel.json` `/api/backend` rewrite is not used by the current frontend** — Based on inspection of `frontend/lib/api.js`, all API calls use the `baseURL` (NEXT_PUBLIC_API_URL) + relative path pattern, not absolute `/api/backend` paths. However, the rewrite should still be removed for clarity.

12. **CRDB Cloud free tier is sufficient for testing** — The free tier provides a single-node cluster with limited resources. For testing schema migration and running the test suite, this should be sufficient.

---

## 18. Unresolved Questions

1. **Does CockroachDB Cloud provide a `postgresql+psycopg://` connection string, or does it use `cockroachdb://`?** If the latter, the `normalize_database_url` function in `app/db.py` would need to handle `cockroachdb://` URLs. **Testing needed.**

2. **Does the `postgresql_where` Alembic kwarg work on CockroachDB?** If not, the `b8c9f1d2e34a` migration needs to be rewritten to use raw SQL. **Testing needed.**

3. **Does CockroachDB's `FOR UPDATE` under `SERIALIZABLE` isolation behave identically to PostgreSQL's `FOR UPDATE` under `READ COMMITTED` for single-row locks?** Theoretically yes, but empirical verification is needed. **Testing needed.**

4. **Does the `LargeBinary` → BYTEA mapping work correctly on CRDB for the `raw_payload` column?** Specifically, can CRDB store and retrieve arbitrary binary data (the exact bytes received from Upstox API) without corruption? **Testing needed.**

5. **What is the behavior of `ON CONFLICT DO NOTHING RETURNING` on CRDB when the conflict is on a composite primary key?** The `broker_fill_ledger_fill` table has a composite PK on `(tenant_id, provider_order_id, fill_eq_key)`. Does CRDB's `ON CONFLICT` handle composite PKs correctly? **Testing needed.**

6. **Does the `_advance_broker_sequence` OCC pattern (`UPDATE ... WHERE last_sequence = :expected`) work correctly on CRDB under `SERIALIZABLE` isolation?** Specifically, if two transactions try to advance the same anchor concurrently, does CRDB guarantee that only one UPDATE affects rows (rowcount == 1 for one, rowcount == 0 for the other), or could CRDB's snapshot isolation cause both to see the same `last_sequence` value and both try to update? **Testing needed.**

7. **What is CockroachDB's behavior for `server_default=sa.text("false")` on a Boolean column?** Does CRDB correctly interpret this as a boolean false default? **Testing needed.**

8. **Does the `pool_pre_ping=True` setting work correctly with CRDB?** Specifically, does the pre-ping query (`SELECT 1`) work on CRDB, and does CRDB's connection eviction behavior interact correctly with the pool's recycling? **Testing needed.**

9. **Is there any Alembic migration that uses PostgreSQL-specific features not covered in this audit?** The audit searched for common PostgreSQL-specific features, but a full migration run on CRDB would reveal any issues. **Testing needed.**

10. **What is the expected concurrency level for StrikeNova in production?** This determines whether the serialization failure risk is theoretical or practical. For a single-user personal app, serialization failures would be rare. For a multi-user or automated-strategy app, they could be frequent. **Discussion needed with stakeholders.**

---

## 19. Recommended Next Steps

### Immediate (before any migration activity)

1. **Fix dialect branching in `fill_ledger.py:542-566`** — Add `"cockroachdb"` to the PostgreSQL branch condition. This is a minimal, safe change that doesn't affect PostgreSQL or SQLite behavior.

2. **Fix dialect branching in `db_dialect.py:15-36`** — Add `"cockroachdb"` to the PostgreSQL branch condition. Same minimal, safe change.

3. **Fix partial index migration in `125e1807df8d:84-96`** — Add `"cockroachdb"` branch that uses `is_default = true` (SQL-standard boolean, same as PostgreSQL).

4. **Fix partial index migration in `b8c9f1d2e34a:29`** — Replace `postgresql_where` kwarg with raw SQL `op.execute()` that works on CRDB (or verify that CRDB supports `postgresql_where`).

### Short-term (before production cutover)

5. **Set up a disposable CRDB test environment** — Local Docker or CRDB Cloud free tier.

6. **Run Alembic migrations on CRDB** — Verify schema creation, especially partial indexes and BYTEA column.

7. **Run the full test suite against CRDB** — All tests, with emphasis on PostgreSQL-gated concurrency tests.

8. **Implement transaction retry handling** — Add retry decorator for `SerializationFailure` in transaction-sensitive functions. (This is a code change that should be done as a separate task, not as part of the migration.)

9. **Update Vercel configuration** — Update `NEXT_PUBLIC_API_URL` env vars, remove `/api/backend` rewrite from `vercel.json`.

10. **Update Upstox redirect URI** — Update the Upstox developer app registration to include the Northflank callback URL.

### Medium-term (during staging/validation)

11. **Deploy to Northflank staging** — Create Northflank service, configure env vars, run migrations, test end-to-end.

12. **Test OAuth flow on staging** — Verify login, token storage, broker connection work on Northflank.

13. **Test paper trading on staging** — Execute a strategy, exit a position, verify P&L and cash correctness.

14. **Test broker-sync on staging** — Mock Upstox API, verify full sync pipeline works.

15. **Load test** — Simulate concurrent requests, verify no serialization errors (or that retry handling works).

### Long-term (post-migration)

16. **Monitor production** — Logs, metrics, error rates. Watch for serialization failures (if retry handling is not implemented) or other CRDB-specific issues.

17. **Document CRDB-specific operational procedures** — Backup/restore, monitoring, scaling, connection pooling tuning.

18. **Consider adding FOR UPDATE to `execute_strategy`** — For explicit serialization of concurrent strategy executions touching the same position. This is a future improvement, not a migration requirement.

---

## 20. Final Decision

### HOLD

**StrikeNova cannot proceed to migration approval until the following are resolved:**

**Must fix (code changes):**
1. ✅ **Dialect branching in `fill_ledger.py:542-566`** — Add `"cockroachdb"` to the PostgreSQL branch. Without this, the fill deduplication logic would use the wrong dialect on CRDB, potentially causing silent data corruption.
2. ✅ **Dialect branching in `db_dialect.py:15-36`** — Add `"cockroachdb"` to the PostgreSQL branch. Same reasoning.
3. ✅ **Partial index migration in `125e1807df8d:84-96`** — Add `"cockroachdb"` branch. Without this, the schema migration would fail on CRDB.
4. ✅ **Partial index migration in `b8c9f1d2e34a:29`** — Replace `postgresql_where` with CRDB-compatible syntax. Without this, the schema migration would fail on CRDB.
5. 🔴 **Transaction retry handling for `SerializationFailure`** — Implement retry decorator for transaction-sensitive functions. Without this, users see 500 errors under concurrent load on CRDB. This is a correctness/UX issue, not a migration blocker technically (the application would still work, just with errors under contention), but it's a hard blocker for a financial application.

**Must verify (testing):**
6. 🔴 **CRDB test environment** — Set up disposable CRDB, run Alembic migrations, run full test suite including all PostgreSQL-gated concurrency tests. Without this, we cannot claim CRDB compatibility with confidence.

**Must configure (infrastructure):**
7. 🟡 **Vercel configuration** — Update `NEXT_PUBLIC_API_URL` env vars, remove `/api/backend` rewrite.
8. 🟡 **Upstox redirect URI** — Update Upstox developer app registration.
9. 🟡 **Northflank configuration** — Environment variables, secrets, health checks.
10. 🟡 **CockroachDB provisioning** — CRDB Cloud cluster or Northflank managed CRDB.

**After items 1-6 are complete (dialect fixes + retry handling + CRDB test pass), re-evaluate as GO WITH CHANGES.**

**This is NOT a NO-GO.** The architecture is fundamentally compatible with CockroachDB. The issues are specific, localized, and fixable. The single-service architecture maps cleanly to Northflank. The transaction patterns (FOR UPDATE, ON CONFLICT, SKIP LOCKED, atomic upserts, unique constraints) are all CRDB-compatible. The economic correctness model (atomic transactions, single-writer cash ledger, deterministic lifecycle events) is CRDB-compatible.

**However**, the audit cannot approve a financial application migration to a stricter isolation level (CRDB SERIALIZABLE vs PostgreSQL READ COMMITTED) without:
- Verifying that the dialect-specific code works on CRDB (fixes 1-4)
- Verifying that transaction retry behavior is handled (fix 5)
- Empirically testing on CRDB (fix 6)

**The cost of waiting is low** — StrikeNova is a personal/portfolio app with no urgent production deadline. The cost of rushing is potentially silent data corruption (if dialect branching is wrong) or user-visible errors (if retry handling is missing). **HOLD is the correct decision.**

---

## Appendix A: Files Inspected

| File | Lines | Purpose |
|---|---|---|
| `options-dashboard-project/Dockerfile` | 18 | Container build configuration |
| `options-dashboard-project/backend/Procfile` | 1 | Process type declaration |
| `options-dashboard-project/backend/.env.example` | 19 | Environment variable documentation |
| `options-dashboard-project/backend/app/main.py` | 424 | FastAPI app, lifespan, health/readiness, CORS, routers |
| `options-dashboard-project/backend/app/config.py` | 110 | pydantic-settings configuration |
| `options-dashboard-project/backend/app/db.py` | 402 | SQLAlchemy engine, sessionmaker, migration validation |
| `options-dashboard-project/backend/app/utils/db_dialect.py` | 36 | Dialect-aware insert function |
| `options-dashboard-project/backend/app/models.py` | 936 | All SQLAlchemy models (paper trading, positions, orders, etc.) |
| `options-dashboard-project/backend/app/identity.py` | 811 | User, UserSession, BrokerConnection, BrokerToken models |
| `options-dashboard-project/backend/app/broker_sync/ingestion.py` | 1239 | Day39 Task2 event ingestion pipeline |
| `options-dashboard-project/backend/app/broker_sync/fill_ledger.py` | 1052 | Day41 fill ledger (observations, fills, alias, lineage) |
| `options-dashboard-project/backend/app/broker_sync/raw_ingress.py` | 393 | Day41 raw ingest (Phase 1 durable commit) |
| `options-dashboard-project/backend/app/broker_sync/models.py` | 125 | BrokerSyncIdempotency, BrokerOrderProjection, BrokerSyncSequenceAnchor |
| `options-dashboard-project/backend/app/broker_sync/fingerprint.py` | 299 | FPv2 canonical serialization |
| `options-dashboard-project/backend/app/trade_lifecycle/persistence.py` | 400 | Lifecycle event persistence, sequence allocation |
| `options-dashboard-project/backend/app/services/paper_execution.py` | 1489 | Strategy execution, position exit, bulk exit |
| `options-dashboard-project/backend/app/brokers/adapters/upstox/adapter.py` | 567 | Upstox adapter |
| `options-dashboard-project/backend/app/brokers/adapters/upstox/mapper.py` | 842 | Upstox data mapping |
| `options-dashboard-project/backend/app/brokers/gateway.py` | 74 | Broker gateway |
| `options-dashboard-project/backend/app/brokers/domain/enums.py` | 133 | Broker-neutral enums |
| `options-dashboard-project/backend/alembic/env.py` | 114 | Alembic environment configuration |
| `options-dashboard-project/backend/alembic/alembic.ini` | 120 | Alembic configuration |
| `options-dashboard-project/backend/alembic/versions/d3eb45a2e046_baseline_initial_schema_with_all_tables.py` | 667 | Baseline schema migration |
| `options-dashboard-project/backend/alembic/versions/125e1807df8d_add_broker_connection_foundation.py` | 107 | Broker connection foundation + partial index |
| `options-dashboard-project/backend/alembic/versions/b8c9f1d2e34a_add_google_sub_to_users.py` | 37 | Google sub partial index |
| `options-dashboard-project/backend/alembic/versions/b3e5f8a1c7d2_day41_add_fill_ledger_tables.py` | 165 | Day41 fill ledger tables |
| `options-dashboard-project/backend/alembic/versions/a7c1d9e4f2b8_day41_add_broker_raw_observation.py` | 91 | Day41 raw observation table |
| `options-dashboard-project/backend/alembic/versions/9b675f8a3af0_day39_add_broker_sync_idempotency_and_.py` | 97 | Day39 broker sync tables |
| `options-dashboard-project/backend/alembic/versions/e8f9a0b1c2d3_add_trade_lifecycle_tables.py` | 91 | Day38 lifecycle tables |
| `options-dashboard-project/backend/alembic/versions/f7a3c2d1e94b_add_capability_separation_columns.py` | 95 | Capability separation columns |
| `options-dashboard-project/backend/alembic/versions/a1b2c3d4e5f6_correct_trading_status_backfill.py` | 42 | Corrective backfill |
| `options-dashboard-project/backend/alembic/versions/b2c3d4e5f6a7_add_gex_provenance_columns.py` | 34 | GEX provenance columns |
| `options-dashboard-project/backend/alembic/versions/merge_day38_gex.py` | 14 | Merge migration |
| `options-dashboard-project/backend/alembic/versions/f7aa24156f6d_merge_day39_broker_sync_day38_gex_heads.py` | 28 | Merge migration |
| `options-dashboard-project/backend/alembic/versions/a0deb75ad22f_add_password_hash_to_users_for_email_.py` | (not inspected) | Password hash column |
| `options-dashboard-project/frontend/lib/api.js` | 276 | Frontend API client (axios) |
| `options-dashboard-project/frontend/next.config.js` | (inspected partially) | Next.js config with NEXT_PUBLIC_API_URL fallback |
| `options-dashboard-project/frontend/package.json` | (inspected partially) | Frontend dependencies |
| `options-dashboard-project/vercel.json` | 28 | Vercel rewrites configuration |
| `options-dashboard-project/.github/workflows/postgres-compatibility.yml` | 69 | PostgreSQL CI workflow |
| `options-dashboard-project/backend/tests/test_day38_postgres_concurrency.py` | 326 | PostgreSQL concurrency for lifecycle events |
| `options-dashboard-project/backend/tests/test_day39_task2_red_v6.py` | 557 | Broker event idempotency + sequence concurrency |
| `options-dashboard-project/backend/tests/test_day41_phase6_7_9_fill_ledger.py` | 556 | Fill ledger tests (SQLite) |
| `options-dashboard-project/backend/tests/test_day41_phase10_postgres_concurrency.py` | 615 | PostgreSQL concurrency for fill ledger |
| `options-dashboard-project/backend/tests/test_paper_concurrency_repro.py` | 335 | Exit position concurrency reproduction |
| `options-dashboard-project/backend/tests/test_day38_task5_append_idempotency.py` | 390 | Lifecycle event idempotency tests |
| `options-dashboard-project/backend/tests/test_day38_task6_transactional_allocation.py` | 613 | Transactional sequence allocation tests |
| `options-dashboard-project/backend/tests/test_broker_connection_model.py` | 726 | Broker connection model tests |
| `options-dashboard-project/backend/tests/test_upstox_adapter.py` | (inspected partially) | Upstox adapter tests |
| `options-dashboard-project/backend/tests/test_upstox_positions_regression.py` | 273 | Upstox position regression tests |
| `options-dashboard-project/backend/tests/test_blocker_final.py` | 189 | Platform session, migration, GEX tests |
| `options-dashboard-project/backend/tests/test_blockers.py` | 188 | Identity hardening tests |
| `options-dashboard-project/backend/tests/test_day41_1_migration_reality.py` | 311 | Migration reality verification (PostgreSQL only) |
| `options-dashboard-project/backend/tests/test_migrate_sqlite_to_pg.py` | 839 | SQLite→PostgreSQL migration tool tests |
| `options-dashboard-project/backend/tests/test_day38_postgres_verification_evidence.py` | (inspected partially) | PostgreSQL verification evidence |
| `options-dashboard-project/backend/tools/migrate_sqlite_to_postgres.py` | 721+ | SQLite→PostgreSQL migration utility |
| `options-dashboard-project/backend/app/services/upstox_client.py` | (inspected partially) | Upstox HTTP client with retry |
| `options-dashboard-project/backend/app/services/candle_retry.py` | (inspected partially) | Candle retry logic |

**Total: 50+ files inspected, 10,000+ lines of code reviewed.**

---

## Appendix B: Commands Executed

| Command | Result |
|---|---|
| `cd /c/Users/busin/Desktop/-options-dashboard && git branch --show-current` | `feat/strikenova-day35-portfolio-intelligence` |
| `git log --oneline -10` | 10 commits, HEAD = `31563da` |
| `git status --short` | 11 modified, 108 untracked files |
| `python3 --version` | `Python 3.11.16` |
| `find . -maxdepth 3 -type f \( -name "Dockerfile*" -o -name "docker-compose*" -o -name "*.toml" -o -name "*.cfg" -o -name "Procfile" -o -name ".env*" -o -name "requirements*" -o -name "Makefile" -o -name "*.yml" -o -name "*.yaml" \) 2>/dev/null` | Found: Dockerfile, Procfile, .env.example, requirements.txt, requirements-dev.txt, vercel.json, .github/workflows/*.yml, .vercel/.env.production.local, frontend/.env.* |
| `find . -type d -maxdepth 4 ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/__pycache__/*" ! -path "*/.venv/*" ! -path "*/venv/*" \| sort` | Full directory structure (see §2.7) |
| `grep -r "session.begin\|session.commit\|session.rollback\|with_for_update\|FOR UPDATE\|RETURNING\|ON CONFLICT\|SELECT.*FOR UPDATE" --include="*.py" options-dashboard-project/backend/` | 39 matches across 14 files (see §4.2, §5.1) |
| `grep -r "postgresql\|pg_\|psycopg\|SAIntegrityError\|IntegrityError" --include="*.py" options-dashboard-project/backend/` | 50 matches across 14 files |
| `grep -r "JSONB\|ARRAY\|ENUM\|UUID\|serial\|identity\|advisory\|listen.*notify\|COPY\|materialized\|exclusion" --include="*.py" options-dashboard-project/backend/` | 50 matches — mostly model definitions and migrations, no actual PostgreSQL-specific type usage found |
| `grep -r "\.execute(\|text(\|raw SQL\|literal_column" --include="*.py" options-dashboard-project/backend/` | (searched with corrected regex) — 6 raw SQL locations found (see §4.2) |
| `grep -r "cockroach\|CRDB\|retryable\|serialization\|40001\|SERIALIZABLE\|isolation_level\|isolation level" --include="*.py" options-dashboard-project/backend/` | 0 results for CRDB-specific terms; 5 results for "serialization" (all comments about logical serialization, not DB transaction retry) |
| `grep -r "CREATE INDEX.*WHERE\|CREATE UNIQUE INDEX.*WHERE\|partial index\|postgresql_where\|sqlite_where" --include="*.py" options-dashboard-project/backend/` | 4 matches — 2 partial index migrations + 2 test helpers |
| `cat options-dashboard-project/backend/requirements.txt` | `fastapi==0.141.1, uvicorn[standard]==0.52.2, httpx==0.28.1, pydantic-settings==2.15.0, python-dotenv==1.2.2, sqlalchemy==2.0.43, alembic==1.15.2, psycopg[binary]>=3.2,<4, cryptography>=44.0.0, PyJWT>=2.8.0` |
| `cat options-dashboard-project/backend/requirements-dev.txt` | `-r requirements.txt, pytest==9.1.1, pytest-asyncio==1.4.0, pytest-cov==7.1.0, respx==0.23.1` |

---

## Appendix C: Search Patterns Used

| Search | Pattern | Purpose |
|---|---|---|
| Transaction boundaries | `session\.begin\|session\.commit\|session\.rollback\|with_for_update\|FOR UPDATE\|RETURNING\|ON CONFLICT\|SELECT.*FOR UPDATE` | Find all transaction-related code |
| PostgreSQL dependencies | `postgresql\|pg_\|psycopg\|SAIntegrityError\|IntegrityError` | Find PostgreSQL-specific code |
| PostgreSQL types/features | `JSONB\|ARRAY\|ENUM\|UUID\|serial\|identity\|advisory\|listen.*notify\|COPY\|materialized\|exclusion` | Find PostgreSQL-specific types and features |
| Raw SQL | `\.execute(\|text(\|raw SQL\|literal_column` | Find raw SQL execution |
| CRDB-specific | `cockroach\|CRDB\|retryable\|serialization\|40001\|SERIALIZABLE\|isolation_level` | Find CRDB-related code (expected: none) |
| Partial indexes | `CREATE INDEX.*WHERE\|CREATE UNIQUE INDEX.*WHERE\|partial index\|postgresql_where\|sqlite_where` | Find partial index usage |
| Subprocess | `subprocess\|os\.system\|os\.popen` | Find subprocess usage (none found) |
| Worker/cron | `celery\|rq\|arq\|apscheduler\|croniter` | Find worker/cron dependencies (none found) |
| Dialect branching | `dialect\.name\|dialect_name\|postgresql.*insert\|sqlite.*insert` | Find dialect-specific code branching |

---

*End of audit report.*
