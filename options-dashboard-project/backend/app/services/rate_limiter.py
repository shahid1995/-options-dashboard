"""Lightweight per-session rate limiter (Phase 9B).

Provides session-scoped rate limiting for authenticated endpoints.
Designed for the current single-process architecture with a clear
migration path to Redis for multi-process deployment.

Architecture:
    session_id → {endpoint → [timestamps]}
    
Memory: O(active_sessions × endpoints × window_entries)
For 100 users × 5 endpoints × 60 entries = 30,000 floats ≈ 240KB

Limits are configurable per endpoint. Default: 60 requests/minute.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request


@dataclass
class RateLimitRule:
    """Configuration for a rate-limited endpoint."""
    max_requests: int = 60
    window_seconds: int = 60


# Default rules for GEX/market-data endpoints
DEFAULT_RULES: dict[str, RateLimitRule] = {
    "/gex/live": RateLimitRule(max_requests=30, window_seconds=60),
    "/gex/capture": RateLimitRule(max_requests=10, window_seconds=60),
    "/gex/snapshots": RateLimitRule(max_requests=60, window_seconds=60),
    "/chains": RateLimitRule(max_requests=30, window_seconds=60),
}


class SessionRateLimiter:
    """Per-session rate limiter.

    Each session gets independent limits. One user's rate limit
    never affects another user.

    Usage in a FastAPI dependency::

        limiter = SessionRateLimiter()

        @router.get("/gex/live")
        async def get_live_gex(request: Request, session_id: str = Depends(get_session_id)):
            limiter.check(session_id, "/gex/live")
            ...
    """

    def __init__(self, rules: dict[str, RateLimitRule] | None = None):
        self._rules = rules or DEFAULT_RULES
        # session_id → endpoint → list of timestamps
        self._hits: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    def check(self, session_id: str | None, endpoint: str) -> None:
        """Check rate limit. Raises HTTPException 429 if exceeded.

        Args:
            session_id: The authenticated session ID.
            endpoint: The endpoint path (used for rule lookup).

        Raises:
            HTTPException: 429 Too Many Requests if rate limit exceeded.
        """
        if not session_id:
            return  # Unauthenticated requests handled by auth middleware

        rule = self._get_rule(endpoint)
        if rule is None:
            return  # No rate limit configured for this endpoint

        now = time.time()
        window_start = now - rule.window_seconds

        # Get hits for this session+endpoint
        hits = self._hits[session_id][endpoint]

        # Remove expired entries
        self._hits[session_id][endpoint] = [t for t in hits if t > window_start]

        # Check limit
        if len(self._hits[session_id][endpoint]) >= rule.max_requests:
            retry_after = int(rule.window_seconds - (now - self._hits[session_id][endpoint][0]))
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "endpoint": endpoint,
                    "limit": rule.max_requests,
                    "window_seconds": rule.window_seconds,
                    "retry_after_seconds": max(1, retry_after),
                },
                headers={"Retry-After": str(max(1, retry_after))},
            )

        # Record this hit
        self._hits[session_id][endpoint].append(now)

    def cleanup(self, max_age_seconds: int = 600) -> int:
        """Remove stale entries for sessions inactive beyond max_age.

        Returns the number of session entries cleaned up.
        """
        now = time.time()
        cleaned = 0
        empty_sessions = []

        for session_id, endpoints in self._hits.items():
            session_active = False
            for endpoint, hits in list(endpoints.items()):
                # Remove old hits
                fresh = [t for t in hits if t > now - max_age_seconds]
                if fresh:
                    endpoints[endpoint] = fresh
                    session_active = True
                else:
                    del endpoints[endpoint]
            if not session_active:
                empty_sessions.append(session_id)
                cleaned += 1

        for sid in empty_sessions:
            del self._hits[sid]

        return cleaned

    def _get_rule(self, endpoint: str) -> RateLimitRule | None:
        """Find the matching rate limit rule for an endpoint."""
        # Exact match first
        if endpoint in self._rules:
            return self._rules[endpoint]
        # Prefix match (e.g. "/chains/NIFTY" matches "/chains")
        for prefix, rule in self._rules.items():
            if endpoint.startswith(prefix):
                return rule
        return None


# Global instance — scoped to the process
rate_limiter = SessionRateLimiter()


# ---------------------------------------------------------------------------
# Backward-compatible aliases (Phase 7.24 backfill_orchestrator)
# ---------------------------------------------------------------------------
import asyncio as _asyncio


class _BackfillRateConfig:
    """Minimal config shim for backward-compat with backfill_orchestrator."""
    def __init__(self, **kwargs: object):
        self.max_concurrency: int = int(kwargs.get("max_concurrency", 5))


RateLimiterConfig = _BackfillRateConfig  # type: ignore[misc]


class GlobalRateLimiter:
    """Async concurrency limiter used by the backfill orchestrator.

    This is NOT the same as ``SessionRateLimiter`` which throttles
    per-user HTTP requests.  ``GlobalRateLimiter`` controls the
    maximum number of concurrent Upstox API fetches during bulk
    historical backfills.
    """

    def __init__(self, max_concurrency: int = 5, **_kwargs: object):
        self._concurrency = max_concurrency
        self._semaphore: _asyncio.Semaphore = _asyncio.Semaphore(max_concurrency)
        self._total_instruments: int = 0

    # -- properties used by backfill_orchestrator --------------------------------

    @property
    def concurrency(self) -> int:
        return self._concurrency

    async def set_total_instruments(self, count: int) -> None:
        self._total_instruments = count

    # -- acquire / release used by worker tasks -----------------------------------

    async def acquire(self) -> None:
        await self._semaphore.acquire()

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass  # release when nothing acquired



class RateLimiterMetrics:
    """Stub metrics container for backward compat with Phase 7.24 tests."""

    def __init__(self) -> None:
        self.api_calls: int = 0
        self.rate_limit_hits: int = 0
        self.concurrency: int = 5
        self.total_instruments: int = 0
        self.instruments_completed: int = 0
        self.instruments_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "rate_limit_hits": self.rate_limit_hits,
            "concurrency": self.concurrency,
            "total_instruments": self.total_instruments,
            "instruments_completed": self.instruments_completed,
            "instruments_failed": self.instruments_failed,
        }
