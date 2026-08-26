# Phase 7.24.8C — Global Rate Limiter & Self-Regulating Backfill

## Summary

Implemented a global, process-wide rate limiter for the Upstox historical backfill pipeline. Concurrency and request rate are now treated as separate concepts managed by a single shared `GlobalRateLimiter` instance. All concurrent workers share one limiter, ensuring coordinated pacing and 429 recovery.

## Architecture

```
CLI (run_backfill.py)
  --concurrency N  --universe ATM_10
         |
         v
  GlobalRateLimiter (Phase 7.24.8C)
  +-- semaphore (concurrency gate)
  +-- interval timer (pacing gate)
  +-- cooldown state (429 recovery)
  +-- metrics (observable state)
         |
         v
  BackfillOrchestrator._run_options_rate_limited()
         |
    +----+----+----+
    v    v    v    v
   W1   W2   W3   W4
    |    |    |    |
    v    v    v    v
  UpstoxClient (centralized auth/retry)
         |
         v
  Local SQLite (instrument-level transactions)
```

## Files Created/Modified

| File | Change |
|------|--------|
| `app/services/rate_limiter.py` | **NEW** — Global rate limiter with adaptive pacing, cooldown, and metrics |
| `app/services/backfill_orchestrator.py` | Integrated rate limiter; replaced old sequential/concurrent paths |
| `run_backfill.py` | Added `--rate-status` flag; rate limiter status display |
| `tests/test_phase724_8c_rate_limiter.py` | **NEW** — 41 comprehensive tests |
| `tests/test_phase724_8b_optimized_backfill.py` | Updated adaptive concurrency tests for rate limiter |
| `docs/PHASE_7_24_8C_RATE_LIMITER.md` | **NEW** — This report |

## Key Design Decisions

### 1. Concurrency ≠ Request Rate

The semaphore gates how many workers run simultaneously. The interval timer gates how frequently any worker may start a new request. Both must be satisfied before `acquire()` returns.

### 2. Conservative Start, Gradual Recovery

- **Initial concurrency**: 1 (CLI default)
- **Initial interval**: 2.0s between requests
- **Recovery**: On each success, interval decreases by 0.05s toward the minimum (0.3s)
- **No burst after cooldown**: Requests remain paced even after cooldown expires

### 3. 429 Is Not Fatal

When a 429 reaches the rate limiter (after the UpstoxClient's own retries are exhausted):

1. Global cooldown activates (all workers pause)
2. Cooldown honours `Retry-After` if present, else exponential backoff
3. Interval widens (slower throughput)
4. If 429s persist (≥3 consecutive), concurrency reduces by 1
5. The affected instrument is marked PENDING, not FAILED — it will retry on the next run

### 4. 401 Never Retried

Authentication failures propagate out of `asyncio.gather` and are caught by `run_options()`, which sets status to FAILED. Checkpoints are marked FAILED. No automatic re-authentication.

### 5. Rate Limiter Metrics

Observable via `limiter.snapshot()`:

```
concurrency: 3
interval_s: 1.25
cooldown_remaining_s: 0.0
total_requests: 150
successful_requests: 148
rate_limit_429s: 2
consecutive_429s: 0
retries_from_client: 0
total_cooldown_time_s: 30.0
instruments_completed: 148
instruments_remaining: 2010
```

## Test Results

### Phase 7.24.8C Tests: 41/41 PASSED

| Test Category | Tests | Status |
|---------------|------:|--------|
| No 429 → gradual increase | 3 | PASSED |
| First 429 → global cooldown | 2 | PASSED |
| Repeated 429 → reduced rate | 2 | PASSED |
| Retry-After handling | 2 | PASSED |
| Missing Retry-After fallback | 2 | PASSED |
| Recovery after cooldown | 3 | PASSED |
| Multiple workers shared limiter | 2 | PASSED |
| No burst after cooldown | 1 | PASSED |
| Checkpoint/resume | 2 | PASSED |
| 401 handling | 1 | PASSED |
| 5xx handling | 1 | PASSED |
| Zero duplicate candles | 1 | PASSED |
| Existing data never redownloaded | 1 | PASSED |
| Raw OHLCV/OI immutability | 1 | PASSED |
| Dry-run produces no API calls | 1 | PASSED |
| Rate limiter unit tests | 7 | PASSED |
| Failure isolation | 1 | PASSED |
| IST timestamp convention | 1 | PASSED |
| No token leakage | 2 | PASSED |
| Concurrency bounds | 2 | PASSED |
| Orchestrator integration | 3 | PASSED |

### Phase 7.24.8B Tests: 26/26 PASSED

All existing 8B tests pass with updated adaptive concurrency assertions.

### Phase 7.24.7 Production Readiness: 40/40 PASSED

No regressions in production readiness tests.

### Frontend Regression: 1357/1357 PASSED

Zero frontend regressions.

## CLI Usage

```bash
# Dry run (zero API calls)
python run_backfill.py --dry-run --options --universe ATM_10

# Benchmark (first 100 instruments, concurrency=2)
python run_backfill.py --options --universe ATM_10 --concurrency 2 --limit 100

# Full backfill with rate-limiter status display
python run_backfill.py --options --universe ATM_10 --concurrency 3 --rate-status

# Verbose logging (shows rate limiter DEBUG-level HTTP requests)
python run_backfill.py --options --universe ATM_10 --concurrency 3 --rate-status -v
```

## Rate Limiter Configuration

Default `RateLimiterConfig`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_concurrency` | 1 | Start conservatively |
| `max_concurrency` | 6 | Safe ceiling from Phase 7.24.8A |
| `min_concurrency` | 1 | Never go below 1 worker |
| `initial_interval` | 2.0s | Time between request starts |
| `min_interval` | 0.3s | Fastest sustainable rate |
| `max_interval` | 30.0s | Slowest allowed rate |
| `cooldown_base` | 15.0s | First 429 cooldown |
| `cooldown_max` | 300.0s | Maximum cooldown (5 min) |
| `cooldown_multiplier` | 2.0 | Exponential backoff |
| `reduce_concurrency_threshold` | 3 | Reduce after N consecutive 429s |
| `recovery_step` | 0.05s | Interval decrease per success |

## Logging Levels

- **INFO**: Rate limiter state changes, cooldown events, progress milestones
- **WARNING**: 429 responses, concurrency reductions, instrument failures
- **DEBUG**: Individual HTTP request completions (when `--verbose` is used)

## Acceptance

`PHASE 7.24.8C ACCEPTANCE: PASS`

- [x] Global rate limiter shared by all workers
- [x] Concurrency and request rate are separate concepts
- [x] Conservative start (concurrency=1, interval=2.0s)
- [x] Gradual increase after sustained success
- [x] 429 → global cooldown, not per-worker
- [x] Retry-After honoured when supplied
- [x] Exponential backoff without Retry-After
- [x] Concurrency reduction on persistent 429s
- [x] 401 never retried automatically
- [x] 5xx retain existing retry behavior
- [x] Rate-limited instruments remain resumable (PENDING, not FAILED)
- [x] Checkpoint/resume preserved
- [x] No duplicate candles
- [x] No raw data mutation
- [x] No existing data deleted
- [x] Metrics observable
- [x] Concise logging (DEBUG for HTTP, INFO/WARNING for events)
- [x] CLI --rate-status display
- [x] 41 new tests passing
- [x] 26 existing 8B tests passing
- [x] 40 production readiness tests passing
- [x] 1357 frontend tests passing
- [x] No deployment, commit, or push
