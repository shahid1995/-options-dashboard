# StrikeNova — Comprehensive Architecture Audit (Through Phase 7.24.8C)

**Date:** August 25, 2026  
**Scope:** Complete codebase audit — backend, frontend, database, services, tests, security  
**Status:** Audit-only — no code changes made

---

## Executive Summary

StrikeNova is a NIFTY index options paper trading platform with historical market data ingestion, Greeks reconstruction, GEX analytics, and a sophisticated server-authoritative execution engine. The codebase has grown through 7+ major phase iterations (Phase 4.1 through 7.24.8C) and contains approximately **860 lines of models, 1400+ lines of paper execution, 600+ lines of historical Greeks, 500+ lines of backfill orchestration, 700+ lines of schemas, and 60+ test files**.

**Overall assessment:** The architecture is well-designed for its current scope (single-user/single-node SQLite deployment). The separation of concerns is strong, idempotency is thoroughly implemented, and the data pipeline is robust. However, several architectural decisions will need revisiting before scaling to multi-user production.

### Key Strengths
- Exceptional idempotency discipline (client_order_id everywhere)
- Clean three-layer data architecture (raw → model → analytics)
- Server-authoritative execution with atomic validation-before-write
- Comprehensive checkpoint/resume for backfill operations
- Well-documented phase progression with clear architectural decisions

### Critical Findings
1. **SQLite as sole database** — won't scale beyond single-user
2. **No background task queue** — backfill and daily ingestion are CLI-only
3. **Token storage is in-memory only** — lost on server restart
4. **GEX computation is client-side** — backend only stores snapshots
5. **No rate-limit middleware** — each service handles its own
6. **Duplicate auth helper patterns** across routers

---

## 1. Current Architecture Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js 14)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │Dashboard │ │ Paper    │ │ GEX      │ │ Positions│          │
│  │          │ │ Trading  │ │ Capture  │ │ & Orders │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│       │            │            │            │                  │
│       └────────────┴────────────┴────────────┘                  │
│                          │ axios + WebSocket                    │
└──────────────────────────┼──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                    BACKEND (FastAPI)                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Routers (10 files)                    │   │
│  │  auth │ paper │ chains │ gex │ candles │ templates │ ...│   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────┴────────────────────────────────┐   │
│  │                  Services (35+ files)                    │   │
│  │  paper_execution │ capital │ performance │ valuation     │   │
│  │  backfill_orchestrator │ daily_ingestion │ rate_limiter  │   │
│  │  historical_greeks │ gex_history │ iv_history            │   │
│  │  strike_selection │ contract_metadata │ option_candles   │   │
│  │  upstox_client │ upstox_token_manager │ token_store      │   │
│  │  exit_selector │ leg_exposure │ strategy_resolver        │   │
│  │  journal │ market_status │ broker_margin │ broker_profile│   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────┴────────────────────────────────┐   │
│  │              Broker Integration Layer                     │   │
│  │  gateway.py → registry.py → adapters/upstox/             │   │
│  │  domain/enums.py │ domain/errors.py                      │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────┴────────────────────────────────┐   │
│  │              Database Layer (SQLAlchemy + SQLite)          │   │
│  │  models.py (860 lines, 25+ tables)                       │   │
│  │  db.py (WAL mode, migrations via ensure_column)           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  CLI Tools:                                                     │
│  run_backfill.py │ run_daily.py │ run_greeks_pilot.py           │
└─────────────────────────────────────────────────────────────────┘
                           │
                     Upstox API v2/v3
```

---

## 2. Strengths

### 2.1 Idempotency Discipline
**Files:** `paper_execution.py`, `schemas.py`, `models.py`

Every user-facing operation uses `client_order_id` as an idempotency key. Strategy executions, position exits, and bulk exits all check for existing records before writing. This is textbook correct and prevents duplicate trades on network retries.

### 2.2 Three-Layer Data Architecture
**Files:** `models.py`, `historical_greeks.py`, `backfill_orchestrator.py`

The RAW → MODEL → ANALYTICS separation is clean:
- **RAW** (immutable): `option_candles`, `nifty_candles`, `contract_specs`
- **MODEL** (derived): `option_greeks`
- **ANALYTICS** (consumed): GEX, vega/delta exposure, IV research

Raw data is never overwritten by derived calculations.

### 2.3 Atomic Execution Model
**Files:** `paper_execution.py` (execute_strategy, exit_position, bulk_exit)

Every execution validates all preconditions (market gate, chain data, prices) BEFORE any row is written. A successful execution is FILLED with all orders filled; a failed one writes nothing. This eliminates partial-success ambiguity.

### 2.4 Checkpoint/Resume for Backfill
**Files:** `backfill_orchestrator.py`, `models.py` (IngestionCheckpoint)

The backfill pipeline has instrument-level checkpointing that survives process termination. The rate limiter marks 429-instruments as PENDING (not FAILED) for automatic retry.

### 2.5 Server-Authoritative Pricing
**Files:** `paper.py` (resolve_market_prices), `paper_execution.py`

Fill prices are resolved from the broker's chain data at execution time, not taken from the client. This prevents stale-price exploitation and ensures the server is the single source of truth.

---

## 3. Problems Found

### P0 — Critical Issues

#### 3.1 SQLite as Sole Database
**Files:** `db.py`, `config.py`

The entire application uses SQLite with WAL mode. This works for single-user but has fundamental limitations:
- No concurrent write access from multiple processes
- No network-accessible database
- No connection pooling
- No backup replication
- The `check_same_thread: False` hack is a SQLite limitation workaround

**Impact:** Cannot support multiple users or horizontal scaling.

#### 3.2 In-Memory Token Storage
**Files:** `token_store.py`

Session tokens are stored in an in-memory dict (`_tokens: dict[str, str]`). On server restart, all sessions are lost and users must re-authenticate.

**Impact:** Poor user experience on deployments/restarts.

#### 3.3 No Background Task Queue
**Files:** `backfill_orchestrator.py`, `daily_ingestion.py`, `run_backfill.py`, `run_daily.py`

All data ingestion is CLI-only. There is no Celery, no Redis queue, no APScheduler, no cron integration within the application. The daily ingestion must be triggered manually or via external cron.

**Impact:** No automated daily data refresh without external orchestration.

#### 3.4 GEX Computation is Client-Side
**Files:** `gex.py` (router), `gex_history.py` (service)

The backend only stores GEX snapshots submitted by the frontend. The actual GEX calculation (gamma × OI × spot²) happens in JavaScript on the client. The backend has no GEX computation capability.

**Impact:** Cannot compute historical GEX from stored data without the frontend.

### P1 — Important Issues

#### 3.5 Duplicate Auth Helper Patterns
**Files:** `routers/paper.py`, `routers/gex.py`, `routers/candles.py`, `routers/chains.py`

Each router defines its own `require_session()` function with slightly different implementations. `paper.py` returns `(user_id, token)`, `gex.py` returns `session_id`, `chains.py` has `require_token()`.

**Impact:** Inconsistent auth patterns, harder to maintain, risk of security drift.

#### 3.6 No Request Rate Limiting Middleware
**Files:** `main.py`

There is no FastAPI middleware for request rate limiting. The only rate limiting is in the `GlobalRateLimiter` for the backfill pipeline. API endpoints have no protection against abuse.

**Impact:** Vulnerable to API abuse in multi-user scenarios.

#### 3.7 Mixed Sync/Async in Router Layer
**Files:** `routers/paper.py`, `routers/chains.py`

Some endpoints are `async def` (requiring broker API calls) while others are `def` (database-only). The market status check (`require_market_open`) makes an async broker call inside what could be a sync endpoint, forcing the entire request to be async.

**Impact:** Suboptimal thread utilization under load.

#### 3.8 ensure_column Migration Pattern
**Files:** `db.py` (init_db)

Schema migrations are done via `ensure_column()` calls in `init_db()`. This works for additive changes but cannot handle:
- Column type changes
- Column renames
- Data migrations
- Constraint changes
- Table drops

**Impact:** Will become unmanageable as schema complexity grows.

#### 3.9 No Database Connection Pooling
**Files:** `db.py`

The SQLAlchemy engine uses default pool settings. For SQLite this is fine (single connection), but if migrated to PostgreSQL, connection pooling configuration will be needed.

#### 3.10 Large schemas.py File
**Files:** `schemas.py`

The schemas file contains 700+ lines of Pydantic models covering every API response. While well-organized with section comments, it's a single file that will grow indefinitely.

**Impact:** Merge conflicts, navigation difficulty.

### P2 — Optimization Opportunities

#### 3.11 No Caching Layer
**Files:** All service files

There is no Redis, memcached, or in-memory caching for frequently accessed data:
- Option chain data is fetched from Upstox on every request
- Portfolio summaries are computed from scratch on every request
- Analytics endpoints query the database fresh each time

**Impact:** Unnecessary API calls and database queries.

#### 3.12 N+1 Query Patterns
**Files:** `paper_execution.py` (get_portfolio_groups), `performance.py`

Some read endpoints make individual queries per execution/position instead of batched queries. The `get_positions_enriched` function correctly uses batched queries, but `get_portfolio_groups` does not.

**Impact:** Database query overhead grows with position count.

#### 3.13 No Pagination on Some Endpoints
**Files:** `routers/paper.py`

The `/paper/portfolio` and `/paper/journal` endpoints return all data without pagination. For users with many trades, this could be slow.

#### 3.14 JSON Fields for Complex Data
**Files:** `models.py` (GexSnapshot, BulkExitRecord, StrategyExecution)

Several tables store complex structured data as JSON text fields (strike_data, expiry_data, positions_json, etc.). This prevents SQL-level querying of nested data.

**Impact:** Cannot query "all snapshots where a specific strike had gamma > X" without loading and parsing JSON.

#### 3.15 No WebSocket Reconnection Logic
**Files:** `routers/chains.py`, frontend `useChainFeed.js`

The WebSocket endpoint pushes chain data every 3 seconds but has no reconnection protocol. If the connection drops, the client must manually reconnect.

### P3 — Future Enhancements

#### 3.16 No User Multi-Tenancy
**Files:** All service files

The `user_id` field exists on most tables but is always the session_id (effectively single-user). True multi-tenancy would require:
- User registration/login (not just broker OAuth)
- Row-level security
- Resource quotas
- Data isolation

#### 3.17 No Audit Trail for Data Mutations
**Files:** `paper_execution.py`

While `IngestionLog` tracks backfill operations, there is no audit trail for paper trading mutations (who changed what, when). The `execution_metadata` field on `StrategyExecution` is the closest thing.

#### 3.18 No WebSocket for Real-Time Position Updates
**Files:** `routers/chains.py`

Only option chain data is pushed via WebSocket. Position updates, order fills, and portfolio changes require polling.

#### 3.19 No API Versioning
**Files:** `main.py`

All endpoints are at the root level (`/paper/`, `/chains/`, `/gex/`). There is no `/api/v1/` prefix for backward compatibility during breaking changes.

#### 3.20 No OpenAPI/Swagger Documentation
**Files:** `main.py`

The FastAPI app has `title` set but no detailed description, version, or contact info. The auto-generated docs exist but could be more comprehensive.

---

## 4. Database Recommendations

### Current Schema (25+ tables)

**Paper Trading Core:**
- `paper_accounts` — user capital
- `trades` — legacy journal
- `legs` — legacy leg journal
- `strategy_executions` — authoritative execution records
- `paper_orders` — authoritative order records
- `positions` — netted positions
- `paper_transactions` — cash ledger
- `strategy_leg_exposures` — per-execution leg attribution
- `exit_exposure_allocations` — exit-to-exposure mapping
- `bulk_exit_records` — idempotency for bulk exits
- `strategy_templates` / `strategy_template_legs` — user templates

**Historical Data:**
- `nifty_candles` — NIFTY index candles
- `contract_specs` — expired contract metadata
- `option_candles` — expired option candles
- `option_greeks` — reconstructed Greeks

**Analytics:**
- `gex_snapshots` — GEX persistence
- `iv_observations` — IV history (unused)

**Infrastructure:**
- `ingestion_log` — pipeline audit trail
- `ingestion_checkpoint` — resume points
- `data_completeness` — data coverage tracking

### Recommendations

1. **Add composite indexes** on `paper_orders(user_id, position_id, status)` and `positions(user_id, status, strategy_execution_id)` for the enriched positions endpoint.
2. **Consider partitioning** `option_candles` by expiry date if data grows beyond 10M rows.
3. **Add `updated_at` triggers** for tables that are updated in place (positions, strategy_executions).
4. **Document the `ensure_column` migration history** in a dedicated migration file.

---

## 5. Performance Recommendations

1. **Cache option chain data** for 5-10 seconds server-side to avoid redundant Upstox API calls when multiple endpoints need the same chain.
2. **Batch the portfolio groups query** to avoid N+1 when loading executions with their positions.
3. **Add database connection pooling** config when migrating to PostgreSQL.
4. **Consider materialized views** for frequently-computed analytics (daily P&L, strategy performance).
5. **Profile the analytics endpoint** — it computes performance, equity curve, drawdown, and journal in a single request.

---

## 6. Security Recommendations

1. **Centralize auth helpers** — create a single `require_auth()` dependency in `deps.py` that returns `(user_id, access_token)`.
2. **Add request rate limiting** middleware (e.g., `slowapi`).
3. **Sanitize error messages** — some broker errors bubble up raw to the client.
4. **Add CSRF protection** for state-changing endpoints.
5. **Implement token refresh** — currently tokens expire daily at 3:30 AM with no automatic refresh.
6. **Add audit logging** for all trading operations.

---

## 7. Analytics Architecture Recommendations

### Current State
- Greeks: computed locally via Black-Scholes (Phase 7.19B)
- GEX: computed client-side, stored as snapshots
- IV: computed as part of Greeks, stored in `option_greeks`
- Strike selection: local computation from NIFTY candles + contract_specs

### Recommended Architecture for Scale

```
Raw Data (option_candles, nifty_candles, contract_specs)
    ↓
Materialized Greeks (option_greeks) — computed once, stored
    ↓
Analytics Engine (GEX, IV surface, vega/delta exposure)
    ↓
API Layer (cached, paginated)
    ↓
Frontend (charts, dashboards)
```

**Key principle:** Compute analytics once, store results, serve from cache. Don't recompute on every API request.

---

## 8. Scalability Concerns

| Concern | Current | Needed for 1000 Users |
|---------|---------|----------------------|
| Database | SQLite (single file) | PostgreSQL with read replicas |
| Auth | In-memory session store | Redis-backed sessions |
| Task Queue | CLI-only | Celery + Redis/RabbitMQ |
| Rate Limiting | None on API | Per-user rate limits |
| Caching | None | Redis for chain data, analytics |
| WebSocket | Single connection | Connection pool per user |
| File Storage | None | S3 for backups, exports |
| Monitoring | print/logging | Prometheus + Grafana |
| Deployment | Single process | Load balancer + multiple workers |

---

## 9. What Should NOT Be Changed

1. **Idempotency discipline** — the `client_order_id` pattern is correct and should be preserved everywhere.
2. **Atomic validation-before-write** — the execution model is sound.
3. **Server-authoritative pricing** — never trust client prices.
4. **Three-layer data architecture** — RAW (immutable) → MODEL (derived) → ANALYTICS (consumed).
5. **One-instrument transaction boundaries** in backfill — prevents cascade failures.
6. **Checkpoint/resume** for long-running operations.
7. **IST timestamp convention** — naive IST throughout the data pipeline.
8. **Lot-size independence** — option_candles don't store lot_size; it's in contract_specs.
9. **Raw OHLCV/OI immutability** — never overwrite historical market data.
10. **Phase progression documentation** — the docs/ directory is valuable institutional knowledge.

---

## 10. Recommended Next Phases

### Phase 8.0: Database Migration (Priority: Critical)
- Migrate from SQLite to PostgreSQL
- Add Alembic for schema migrations
- Configure connection pooling

### Phase 8.1: Authentication Overhaul (Priority: Critical)
- Centralize auth middleware
- Add token refresh
- Redis-backed session store

### Phase 8.2: Background Task Queue (Priority: High)
- Add Celery + Redis
- Automate daily ingestion
- Schedule Greeks reconstruction

### Phase 8.3: Server-Side GEX (Priority: High)
- Move GEX computation to backend
- Compute from stored Greeks + OI
- Enable historical GEX analysis

### Phase 8.4: API Caching (Priority: Medium)
- Cache option chain data (5-10s TTL)
- Cache analytics computations
- Add Redis infrastructure

### Phase 8.5: Multi-User Support (Priority: Medium)
- User registration system
- Row-level security
- Resource quotas

### Phase 8.6: Real-Time Updates (Priority: Low)
- WebSocket for position updates
- WebSocket for order fills
- Server-sent events for portfolio changes

---

## 11. Test Coverage Assessment

**60+ test files** covering:
- Paper trading execution (multiple test files)
- Greeks computation
- Candle validation and ingestion
- Contract metadata
- Backfill optimization (Phases 7.24.8A/B/C)
- Rate limiter
- Strategy templates
- Exit selectors
- Capital/margin

**Missing test coverage:**
- Frontend integration tests (only unit tests exist)
- Load/stress testing
- Database migration testing
- Token refresh failure scenarios
- Concurrent execution race conditions (only basic tests)

---

## 12. File Inventory

### Backend Core
- `app/models.py` — 860 lines, 25+ tables
- `app/schemas.py` — 700+ lines, 50+ Pydantic models
- `app/db.py` — Database setup, migrations, health checks
- `app/config.py` — Pydantic settings
- `app/main.py` — FastAPI app setup

### Backend Services (35+ files)
- `paper_execution.py` — 1400+ lines, core trading engine
- `historical_greeks.py` — 600+ lines, Black-Scholes engine
- `backfill_orchestrator.py` — 900+ lines, data pipeline
- `capital.py` — Capital/margin abstraction
- `performance.py` — Analytics computation
- `exit_selector.py` — Server-authoritative exit resolution
- `leg_exposure.py` — Strategy-leg attribution
- `rate_limiter.py` — Global rate limiter (Phase 7.24.8C)

### Backend Routers (10 files)
- `paper.py` — Paper trading endpoints
- `chains.py` — Option chain + WebSocket
- `gex.py` — GEX snapshot API
- `candles.py` — Historical candle API
- `auth.py` — OAuth flow

### Frontend
- 50+ test files
- 10+ route directories
- 15+ library modules
- WebSocket integration for chain data

### Documentation
- `docs/` — 15+ phase documentation files
- Phase progression from 4.1 through 7.24.8C

---

**Audit completed. No code changes were made.**
