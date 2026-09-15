# Day 6 — PostgreSQL Performance Baseline

## Goal

Establish a reproducible PostgreSQL 16 performance baseline for StrikeNova's current database architecture. Identify evidence-backed bottlenecks before making targeted optimizations.

## Scope

- 26 tables across identity, paper trading, market data, and ingestion pipelines
- Representative query workloads extracted from actual service/router code
- Deterministic synthetic benchmark dataset (100K+ rows across key tables)
- EXPLAIN ANALYZE on critical query paths
- Index audit against actual workload patterns
- Connection pool baseline recording
- Before/after measurement for any optimization

## Non-Goals

- Production deployment or cutover
- Redesigning the entire schema
- Adding speculative indexes without benchmark evidence
- Optimizing for benchmark vanity numbers
- PostgreSQL production connection

## Benchmark Methodology

1. Create disposable SQLite database via Alembic migrations
2. Seed deterministic synthetic dataset representing realistic scale
3. Run representative queries with timing measurement
4. Capture EXPLAIN QUERY PLAN for each critical path
5. Identify missing composite indexes based on query patterns
6. Add Alembic migration for evidence-backed indexes
7. Re-run benchmarks for before/after comparison

## Representative Workloads

### HIGH Priority

| Workload | Table(s) | Query Pattern | Why |
|----------|----------|---------------|-----|
| Tenant portfolio read | positions, strategy_executions | WHERE user_id = ? AND status = ? | Core user-facing view |
| GEX snapshot history | gex_snapshots | WHERE symbol = ? AND owner_id = ? AND captured_at >= ? | Time-series with owner |
| Contract spec lookup | contract_specs | WHERE underlying = ? AND expiry = ? | Frequently used in chain building |
| Nifty candle time-window | nifty_candles | WHERE symbol = ? AND interval = ? AND open_time >= ? | Research queries |
| Historical GEX analytics | historical_gex | WHERE instrument_key = ? AND open_time >= ? AND status = ? | Complex filtering |
| Paper account capital | paper_accounts + paper_transactions | WHERE user_id = ? + SUM(amount) WHERE user_id = ? | Capital calculation |

### MEDIUM Priority

| Workload | Table(s) | Query Pattern |
|----------|----------|---------------|
| Ingestion log by operation+status | ingestion_log | WHERE operation = ? AND status = ? |
| Data completeness check | data_completeness | WHERE instrument_key = ? AND session_date = ? |
| Strategy template list | strategy_templates | WHERE user_id = ? |
| Leg exposures by execution | strategy_leg_exposures | WHERE user_id = ? AND execution_id = ? |

## Dataset Strategy

- 5 users, 50 strategy executions per user
- 250 positions across users
- 50 expiry dates × 20 strikes × 2 types = 2000 contract specs per expiry
- 500 nifty candles per day × 30 days = 15,000 candles
- 2000 option candles per instrument × 50 instruments = 100,000 candles
- 100,000 option greek records
- 50,000 historical GEX snapshots
- 5,000 GEX snapshots
- 1,000 ingestion log entries

## Optimization Criteria

Only optimize when:
1. EXPLAIN ANALYZE shows sequential scan on large table
2. Query pattern has clear composite index need
3. Before/after measurement shows material improvement
4. No write-path regression introduced

## Regression Criteria

- All existing tests must continue passing
- No new test failures introduced
- Write-path latency must not materially increase
- Connection pool behavior unchanged

## PostgreSQL 16 Verification

Via CI workflow `postgres-compatibility.yml` with `postgres:16` service container.
Local benchmarks run against SQLite for rapid iteration; CI validates PostgreSQL compatibility.

## Evidence Requirements

- Deterministic dataset seeded from fixed random seed
- Multiple iterations (10+) per benchmark with median/p95
- EXPLAIN QUERY PLAN captured for each critical path
- Index usage verified via query plan inspection
- Before/after tables for every optimization
