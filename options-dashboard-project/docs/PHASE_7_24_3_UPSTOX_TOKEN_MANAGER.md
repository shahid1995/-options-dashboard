# Phase 7.24.3 — Persistent Upstox Token Manager

## Status: ✅ COMPLETE

## Objective

Implement persistent access-token storage so that CLI tools and background processes can authenticate with Upstox without requiring browser-based OAuth each time.

## Problem Solved

The existing `token_store.py` keeps the access token in Python memory only. Every server restart, CLI invocation, or process restart requires the user to re-authenticate through the browser. This is unacceptable for long-running historical backfill jobs and daily incremental ingestion.

## Solution

A persistent token manager (`UpstoxTokenManager`) stores the access token to a JSON file at a deterministic path. CLI tools and background processes can load the token from disk without starting FastAPI.

## Architecture

```
    Upstox OAuth callback (FastAPI)
              │
              ▼
    UpstoxTokenManager.save(access_token, expires_at)
              │
              ▼
    .token_cache/upstox_token.json   ← deterministic path, CWD-independent
              │
              ▼
    UpstoxTokenManager.get_token()  ← TokenProvider protocol
              │
              ▼
    UpstoxClient (Phase 7.24.2)
              │
    ┌─────────┴─────────┐
    ▼                   ▼
Historical CLI     Daily pipeline
```

## Files Created

| File | Purpose |
|------|---------|
| `app/services/upstox_token_manager.py` | Persistent token manager with expiry handling, atomic writes, corruption handling |
| `tests/test_phase724_3_token_manager.py` | 50 comprehensive tests |

## Files Modified

| File | Change |
|------|--------|
| `.gitignore` | Added `.token_cache/` and `upstox_token.json` patterns |

## Token Storage

**Location:** `backend/.token_cache/upstox_token.json`

**Format:**
```json
{
  "access_token": "...",
  "expires_at": "2026-08-26T00:00:00+00:00",
  "updated_at": "2026-08-25T18:00:00+00:00"
}
```

**Path derivation:** Based on the backend application source location (`__file__`), not the process working directory. This eliminates the CWD-dependence bug that previously caused database data loss.

## Token Provider Interface

`UpstoxTokenManager` implements the `TokenProvider` protocol introduced in Phase 7.24.2:

```python
class TokenProvider(Protocol):
    def get_token(self) -> str | None: ...
```

This means it can be passed directly to `UpstoxClient`:

```python
manager = UpstoxTokenManager()
client = UpstoxClient(token_provider=manager)
```

## Expiry Handling

| State | Description | `get_token()` returns |
|-------|-------------|----------------------|
| `NO_TOKEN` | No cached token | `None` |
| `VALID` | Token exists and not near expiry | token string |
| `EXPIRING_SOON` | Token within safety buffer | token string |
| `EXPIRED` | Token past expiry + buffer | `None` |
| `CORRUPTED` | Invalid cache file | `None` |

**Safety buffer:** 5 minutes (configurable). A token expiring at 10:00 is considered expired at 09:55. This prevents long historical operations from starting with a nearly-expired token.

## Atomic Writes

Token persistence uses an atomic write pattern:
1. Create temporary file in same directory
2. Write JSON content
3. Flush + fsync (best-effort on Windows)
4. `os.replace()` (atomic rename)

This prevents file corruption if the process is interrupted mid-write.

## Corruption Handling

The manager gracefully handles:
- Missing file → `NO_TOKEN`
- Empty file → `NO_TOKEN`
- Invalid JSON → `CORRUPTED`
- Truncated JSON → `CORRUPTED`
- Missing `access_token` field → `CORRUPTED`
- Malformed `expires_at` → `CORRUPTED`
- Non-dict JSON → `CORRUPTED`
- Missing `expires_at` → `EXPIRING_SOON` (conservative)

No crashes, no obscure exceptions.

## Security

| Protection | Mechanism |
|-----------|-----------|
| Token not in database | Stored in JSON file, never in SQLite |
| Token not in logs | Logger never receives token values |
| Token not in exceptions | Error messages never expose tokens |
| Token not in frontend | No API endpoint returns the cached token |
| Token not in .gitignore | `.token_cache/` directory is gitignored |
| File permissions | Best-effort on Windows; safe on Linux |

## CLI Compatibility

**Workflow:**
```
# First time: browser OAuth
Browser → /auth/callback → UpstoxTokenManager.save(...)
                            → persisted to .token_cache/

# Later: CLI uses cached token
CLI → UpstoxTokenManager() → .token_cache/upstox_token.json
                           → UpstoxClient → no browser login needed
```

## OAuth Compatibility

The existing FastAPI OAuth flow is NOT modified. The `auth.py` router continues to use `token_store.py` for in-memory session management. The `UpstoxTokenManager` is a separate persistence layer that can be optionally populated by the OAuth callback in a future phase.

## Refresh Token Status

Not implemented. The existing application does not have a verified refresh-token workflow. The current Upstox OAuth flow provides access tokens that expire at 3:30 AM IST daily. Future enhancement if Upstox provides refresh tokens.

## Test Coverage (50 tests)

| Category | Tests |
|----------|------:|
| A. First-time state | 5 |
| B. Save/load | 8 |
| C. Expiry handling | 6 |
| D. Corruption handling | 8 |
| E. Clear | 4 |
| F. Atomic writes | 3 |
| G. Path determinism | 3 |
| H. Git security | 1 |
| I. Logging security | 2 |
| J. TokenProvider compatibility | 3 |
| K. Multiple instances | 3 |
| L. Process independence | 2 |
| M. Database protection | 1 |
| N. No real API calls | 1 |

## Regression

| Suite | Tests | Result |
|-------|------:|--------|
| Phase 7.24.3 | 50 | All pass |
| Phase 7.24.2 | 50 | All pass |
| Phase 7.24.1 | 35 | All pass |
| Phase 7.24 architecture | 23 | All pass |
| Full backend | 1,962 | All pass (4 skipped) |
| Full frontend | 1,357 | All pass |

## Metrics

| Metric | Value |
|--------|-------|
| Real Upstox API calls | **0** |
| Real OAuth calls | **0** |
| Historical data downloaded | **0** |
| Market-data rows modified | **0** |
| Database tables modified | **0** |

## Known Limitations

1. **No automatic refresh:** Upstox tokens expire daily at 3:30 AM IST. The token manager detects expiry but cannot auto-refresh. Users must re-authenticate through the browser after daily expiry.

2. **Single-user design:** The current design stores one token. Multi-user support would require session-based token management.

3. **Windows fsync:** `os.fsync()` is best-effort on Windows. The atomic `os.replace()` provides the primary corruption protection.

## Next Phase

Phase 7.24.4 will implement **Timezone Standardization** — converting all candle timestamps to a single canonical representation (IST) across `nifty_candles` and `option_candles`.

---

**No real Upstox API calls or OAuth calls were made during Phase 7.24.3.**
