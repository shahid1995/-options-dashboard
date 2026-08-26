# Phase 7.24.2 — Centralized Upstox API Client

## Status: PASS

## Summary

Created a single, reusable Upstox API client (`UpstoxClient`) that provides centralized retry, rate-limit handling, error normalization, metrics, and safe logging. All 50 mocked tests pass. Zero real Upstox API calls were made.

---

## Files Created

| File | Purpose |
|------|---------|
| `app/services/upstox_client.py` | Centralized Upstox API client |
| `tests/test_phase724_2_upstox_client.py` | 50 comprehensive mocked tests |
| `docs/PHASE_7_24_2_UPSTOX_CLIENT.md` | This report |

## Files Modified

None. No existing files were modified.

---

## Client Architecture

```
TokenProvider (interface)
       ↓
  UpstoxClient
       ↓
  _request() [single retry entry point]
       ↓
  ┌─────┼─────┐
  ↓     ↓     ↓
401    429   5xx
fail   backoff retry
       ↓
  httpx.AsyncClient
       ↓
  Upstox API
```

One centralized request mechanism. One retry policy. One metrics tracker.

---

## Supported Endpoints

| Method | Endpoint | API Version |
|--------|----------|------------|
| `get_expiries(instrument_key)` | `/v2/expired-instruments/expiries` | V2 |
| `get_contracts(instrument_key, expiry_date)` | `/v2/expired-instruments/option/contract` | V2 |
| `get_historical_candles(key, to_date, from_date)` | `/v3/historical-candle/...` | V3 |
| `get_expired_historical_candles(key, interval, to_date, from_date)` | `/v2/expired-instruments/historical-candle/...` | V2 |
| `get_intraday_candles(instrument_key)` | `/v3/historical-candle/intraday/...` | V3 |

All methods return parsed data (list/dict). Empty responses return empty lists (not errors).

---

## Authentication

- Uses `Authorization: Bearer <token>` header
- Token obtained via `TokenProvider.get_token()` interface
- 401 → `UpstoxAuthenticationError`, never retried
- Token never logged, printed, or exposed in errors

### TokenProvider Protocol

```python
class TokenProvider(Protocol):
    def get_token(self) -> str | None: ...
```

Phase 7.24.3 will implement persistent token caching. The existing `token_store.get_token()` can be wrapped to satisfy this protocol.

---

## Retry Policy

```python
RetryPolicy(
    max_attempts=3,      # Total attempts (including first)
    base_delay=1.0,      # Base delay in seconds
    max_delay=30.0,      # Maximum delay cap
    jitter=0.5,          # ±50% randomization
    retryable_status={429, 500, 502, 503, 504, 408},
    retry_on_network_error=True,
)
```

**Backoff formula:** `min(base_delay * 2^(attempt-1), max_delay)` ± jitter

---

## Rate-Limit Handling (429)

1. Detect 429 response
2. Parse `Retry-After` header (if present)
3. If no `Retry-After`, use exponential backoff
4. Retry up to `max_attempts`
5. If all retries exhausted, raise `UpstoxRateLimitError`

---

## Error Categories

| Exception | Category | Status | Retry? |
|-----------|----------|--------|--------|
| `UpstoxAuthenticationError` | AUTH_EXPIRED | 401 | No |
| `UpstoxRateLimitError` | RATE_LIMIT | 429 | Yes |
| `UpstoxValidationError` | BAD_REQUEST | 400 | No |
| `UpstoxNotFoundError` | NOT_FOUND | 404 | No |
| `UpstoxClientError` | FORBIDDEN | 403 | No |
| `UpstoxServerError` | SERVER_ERROR | 5xx | Yes |
| `UpstoxNetworkError` | NETWORK | — | Yes |
| `UpstoxResponseError` | MALFORMED_RESPONSE | — | No |

---

## Metrics

```python
client.get_metrics() → {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "rate_limit_count": 0,
    "authentication_failures": 0,
    "retry_count": 0,
    "network_failures": 0,
    "total_elapsed_time": 0.0,
}
```

In-memory only. The ingestion orchestrator will connect these to `ingestion_log` later.

---

## Logging Security

Logs contain:
- HTTP method
- Endpoint/path
- Status code
- Elapsed time
- Attempt number
- Retry reason

Logs MUST NOT contain:
- Access token
- Authorization header
- Client secret
- Refresh token
- OAuth code

---

## Response Validation

- HTTP status checked first
- JSON parsing validated
- Upstox envelope (`{"status": "success", "data": ...}`) validated
- Bare list responses handled gracefully
- Empty data returns empty list (not an error)

---

## Test Coverage (50 tests)

| Category | Tests |
|----------|-------|
| Authentication | 4 (valid, missing, 401, no retry) |
| Success responses | 5 (valid, empty, wrapper, candles, raw) |
| Rate limiting | 3 (with Retry-After, without, limit exceeded) |
| Server errors | 4 (500, 502, 503, 504) |
| Network errors | 4 (connect timeout, read timeout, connection error, limit) |
| Permanent errors | 3 (400, 403, 404) |
| Malformed responses | 5 (invalid JSON, missing data, wrong type, error envelope, empty) |
| Metrics | 6 (request, failure, retry, rate-limit, auth, reset) |
| Response validation | 4 (valid, no status, error, non-dict) |
| Retry policy | 2 (default, custom) |
| Logging security | 3 (token not in errors, not in success, secret not in logs) |
| API methods | 5 (expiries, contracts, candles, expired, intraday) |
| End-to-end | 1 (full workflow) |

All 50 tests pass.

---

## Regression Results

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.2 client tests | 50 | All pass |
| Full backend | 1,912 | All pass |
| Full frontend | 1,357 | All pass |

---

## Limitations

1. **No persistent token cache** — Phase 7.24.3 will implement `TokenProvider` with file-based persistence for CLI tools
2. **Existing callers not migrated** — `app/services/upstox.py` still contains the old individual functions. Migration will happen in a later phase.
3. **No automatic token refresh** — If the token expires, the caller must re-authenticate. Future phases may add refresh-token support.
4. **Metrics in-memory only** — Not yet persisted to `ingestion_log`. The ingestion orchestrator will connect metrics to logging later.

---

## Future Integration

### Phase 7.24.3 — Token Manager

```python
class PersistentTokenProvider:
    """Token provider with file-based persistence."""
    def __init__(self, cache_path: str = ".token_cache"):
        self._cache_path = cache_path

    def get_token(self) -> str | None:
        # Read from .token_cache if valid
        ...
```

### Phase 7.24.5 — Backfill Orchestrator

```python
client = UpstoxClient(token_provider=provider)
for expiry in await client.get_expiries(NIFTY_KEY):
    contracts = await client.get_contracts(NIFTY_KEY, expiry)
    for contract in contracts:
        candles = await client.get_expired_historical_candles(...)
        # Persist to database
```

---

## Upstox API Calls During Phase 7.24.2

```
0
```

All tests use mocked HTTP responses. No real Upstox service was contacted.

---

## Acceptance

```
PHASE 7.24.2 ACCEPTANCE: PASS
```
