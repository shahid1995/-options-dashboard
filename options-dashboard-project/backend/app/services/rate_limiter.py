"""Global Upstox Rate Limiter — Phase 7.24.8C.

A shared, process-wide rate-limit scheduler for all concurrent backfill
workers.  Concurrency and request rate are *separate* concepts: the
limiter controls both how many workers run simultaneously and how
frequently requests may be issued.

Design principles:
  - **Single global instance** — all workers share one limiter.
  - **Conservative start** — begin at concurrency=1, widen slowly.
  - **429 is not fatal** — global cooldown, exponential backoff, resume.
  - **Gradual recovery** — successful requests widen the window again.
  - **Retry-After honoured** — when Upstox supplies it, obey it.
  - **Metrics** — every decision is observable.
  - **Thread-safe** — asyncio.Lock serialises state mutations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RateLimiterConfig:
    """Immutable configuration for the global rate limiter."""

    # Concurrency
    initial_concurrency: int = 1
    min_concurrency: int = 1
    max_concurrency: int = 6

    # Request pacing (seconds between requests across ALL workers)
    initial_interval: float = 2.0
    min_interval: float = 0.3
    max_interval: float = 30.0

    # Recovery — how aggressively we widen the window after success
    recovery_step: float = 0.05      # subtract this many seconds on success
    recovery_floor_pct: float = 0.7  # stop recovering at interval_pct of min

    # 429 cooldown
    cooldown_base: float = 15.0      # first 429: pause this long
    cooldown_max: float = 300.0      # never pause longer than 5 minutes
    cooldown_multiplier: float = 2.0 # exponential backoff multiplier

    # Concurrency reduction
    reduce_concurrency_threshold: int = 3   # reduce after N consecutive 429s
    reduce_cooldown: float = 10.0           # pause when reducing concurrency


# ---------------------------------------------------------------------------
# Public metrics snapshot
# ---------------------------------------------------------------------------

@dataclass
class RateLimiterMetrics:
    """Observable state of the rate limiter at one instant."""

    current_concurrency: int = 0
    current_interval_s: float = 0.0
    cooldown_remaining_s: float = 0.0
    total_requests: int = 0
    successful_requests: int = 0
    rate_limit_429s: int = 0
    consecutive_429s: int = 0
    retries_from_client: int = 0
    total_cooldown_time_s: float = 0.0
    instruments_completed: int = 0
    instruments_remaining: int = 0

    def to_dict(self) -> dict:
        return {
            "concurrency": self.current_concurrency,
            "interval_s": round(self.current_interval_s, 3),
            "cooldown_remaining_s": round(max(0, self.cooldown_remaining_s), 1),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "rate_limit_429s": self.rate_limit_429s,
            "consecutive_429s": self.consecutive_429s,
            "retries_from_client": self.retries_from_client,
            "total_cooldown_time_s": round(self.total_cooldown_time_s, 1),
            "instruments_completed": self.instruments_completed,
            "instruments_remaining": self.instruments_remaining,
        }


# ---------------------------------------------------------------------------
# Global rate limiter
# ---------------------------------------------------------------------------

class GlobalRateLimiter:
    """Process-wide rate limiter for concurrent backfill workers.

    Lifecycle::

        limiter = GlobalRateLimiter(config)

        # Before starting work
        await limiter.set_total_instruments(3000)

        # Each worker loop:
        while work remains:
            await limiter.acquire()          # block until it's our turn
            try:
                result = await api_call()    # do the work
                limiter.on_success()
            except UpstoxRateLimitError as e:
                limiter.on_429(retry_after=e.retry_after)
                # instrument stays resumable via checkpoint
            except Exception:
                limiter.on_error()           # count but don't change pacing

    The semaphore gates concurrency; the interval gates request rate.
    Both must be satisfied before ``acquire()`` returns.
    """

    def __init__(self, config: RateLimiterConfig | None = None):
        self._cfg = config or RateLimiterConfig()

        # --- concurrency ---
        self._concurrency = self._cfg.initial_concurrency
        self._semaphore = asyncio.Semaphore(self._concurrency)

        # --- request pacing ---
        self._interval = self._cfg.initial_interval
        self._last_request_time = 0.0

        # --- cooldown state ---
        self._cooldown_until = 0.0
        self._consecutive_429s = 0
        self._cooldown_total = 0.0

        # --- counters ---
        self._total_requests = 0
        self._successful_requests = 0
        self._rate_limit_count = 0
        self._retries_from_client = 0

        # --- instrument tracking ---
        self._instruments_completed = 0
        self._instruments_remaining = 0

        # --- serialization ---
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - time.monotonic())

    # ------------------------------------------------------------------
    # Instrument bookkeeping
    # ------------------------------------------------------------------

    async def set_total_instruments(self, total: int) -> None:
        async with self._lock:
            self._instruments_remaining = total - self._instruments_completed

    async def mark_instrument_done(self) -> None:
        async with self._lock:
            self._instruments_completed += 1
            self._instruments_remaining = max(
                0, self._instruments_remaining - 1,
            )

    # ------------------------------------------------------------------
    # Core: acquire permission to make a request
    # ------------------------------------------------------------------

    async def acquire(self) -> None:
        """Block until a new request is permitted.

        Satisfies two constraints:
          1. The semaphore ensures at most ``concurrency`` workers are
             in-flight simultaneously.
          2. The pacing timer ensures at least ``interval`` seconds
             elapse between successive request *starts*.
        """
        # 1. Wait for a semaphore slot (concurrency gate)
        await self._semaphore.acquire()

        # 2. Honour global cooldown (429 recovery)
        now = time.monotonic()
        if self._cooldown_until > now:
            wait = self._cooldown_until - now
            logger.info(
                "Rate limiter: cooling down %.1fs (consecutive 429s=%d)",
                wait, self._consecutive_429s,
            )
            await asyncio.sleep(wait)

        # 3. Pace requests (interval gate)
        async with self._lock:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_request_time = time.monotonic()
            self._total_requests += 1

    def release(self) -> None:
        """Release a semaphore slot after a request completes."""
        self._semaphore.release()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_success(self) -> None:
        """Called after a successful API response.

        - Clears 429 streak.
        - Gradually decreases interval (increases throughput).
        """
        async with self._lock:
            self._successful_requests += 1
            self._consecutive_429s = 0

            # Gradual recovery: shrink interval toward minimum
            floor = self._cfg.min_interval * self._cfg.recovery_floor_pct
            if self._interval > floor:
                old = self._interval
                self._interval = max(floor, self._interval - self._cfg.recovery_step)
                if self._interval != old:
                    logger.debug(
                        "Rate limiter: interval %.2fs -> %.2fs (recovery)",
                        old, self._interval,
                    )

    async def on_429(self, retry_after: float | None = None) -> None:
        """Called when a 429 is NOT resolved by the client's own retries.

        - Pauses all workers globally.
        - Increases interval (slows request rate).
        - May reduce concurrency if 429s are persistent.
        """
        async with self._lock:
            self._rate_limit_count += 1
            self._consecutive_429s += 1

            # Decide cooldown duration
            if retry_after is not None and retry_after > 0:
                cooldown = min(retry_after, self._cfg.cooldown_max)
            else:
                cooldown = min(
                    self._cfg.cooldown_base * (
                        self._cfg.cooldown_multiplier ** (self._consecutive_429s - 1)
                    ),
                    self._cfg.cooldown_max,
                )

            now = time.monotonic()
            self._cooldown_until = max(self._cooldown_until, now) + cooldown
            self._cooldown_total += cooldown

            logger.warning(
                "Rate limiter: 429 #%d — cooldown %.1fs, interval %.2fs",
                self._consecutive_429s, cooldown, self._interval,
            )

            # Widen interval (slow down)
            self._interval = min(
                self._cfg.max_interval,
                self._interval * 1.5,
            )

        # Possibly reduce concurrency (outside the lock to avoid deadlocks)
        await self._maybe_reduce_concurrency()

    async def on_client_retry(self) -> None:
        """Called when the UpstoxClient retries internally (counted but no pacing change)."""
        async with self._lock:
            self._retries_from_client += 1

    async def on_error(self) -> None:
        """Called on non-429 errors.  Does not change pacing."""
        pass  # No-op; available for future metrics

    # ------------------------------------------------------------------
    # Adaptive concurrency
    # ------------------------------------------------------------------

    async def _maybe_reduce_concurrency(self) -> None:
        """Reduce concurrency if 429s are persistent.

        Only reduces; never increases.  Increasing happens only in
        ``_maybe_increase_concurrency`` after a sustained cool-down.
        """
        async with self._lock:
            if self._consecutive_429s < self._cfg.reduce_concurrency_threshold:
                return
            if self._concurrency <= self._cfg.min_concurrency:
                return

            old = self._concurrency
            self._concurrency -= 1

        # Rebuild semaphore with new concurrency.
        # We create a NEW semaphore.  Workers that already hold a slot
        # will finish; new acquires use the tighter limit.
        self._semaphore = asyncio.Semaphore(self._concurrency)
        logger.warning(
            "Rate limiter: concurrency %d -> %d (consecutive 429s=%d)",
            old, self._concurrency, self._consecutive_429s,
        )

        # Extra cooldown when reducing concurrency
        async with self._lock:
            self._cooldown_until = time.monotonic() + self._cfg.reduce_cooldown
            self._cooldown_total += self._cfg.reduce_cooldown

    async def _maybe_increase_concurrency(self) -> None:
        """Increase concurrency after a sustained period of successful requests.

        Called internally after the cooldown clears and requests succeed.
        Only increases if we are below the configured maximum.
        """
        async with self._lock:
            if self._consecutive_429s > 0:
                return  # Don't increase if we've recently seen 429s
            if self._concurrency >= self._cfg.max_concurrency:
                return

            old = self._concurrency
            self._concurrency += 1

        self._semaphore = asyncio.Semaphore(self._concurrency)
        logger.info(
            "Rate limiter: concurrency %d -> %d (recovery)",
            old, self._concurrency,
        )

    # ------------------------------------------------------------------
    # Metrics snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> RateLimiterMetrics:
        """Return an observable snapshot of the limiter state."""
        return RateLimiterMetrics(
            current_concurrency=self._concurrency,
            current_interval_s=self._interval,
            cooldown_remaining_s=self.cooldown_remaining,
            total_requests=self._total_requests,
            successful_requests=self._successful_requests,
            rate_limit_429s=self._rate_limit_count,
            consecutive_429s=self._consecutive_429s,
            retries_from_client=self._retries_from_client,
            total_cooldown_time_s=self._cooldown_total,
            instruments_completed=self._instruments_completed,
            instruments_remaining=self._instruments_remaining,
        )

    def log_status(self, level: int = logging.INFO) -> None:
        """Emit a concise status line at the given log level."""
        m = self.snapshot()
        logger.log(
            level,
            "Rate limiter: workers=%d interval=%.2fs cooldown=%.0fs "
            "429s=%d (streak=%d) completed=%d remaining=%d",
            m.current_concurrency,
            m.current_interval_s,
            m.cooldown_remaining_s,
            m.rate_limit_429s,
            m.consecutive_429s,
            m.instruments_completed,
            m.instruments_remaining,
        )

    # ------------------------------------------------------------------
    # Reset (for testing)
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Reset all internal state.  For test isolation only."""
        async with self._lock:
            self._concurrency = self._cfg.initial_concurrency
            self._interval = self._cfg.initial_interval
            self._cooldown_until = 0.0
            self._consecutive_429s = 0
            self._cooldown_total = 0.0
            self._total_requests = 0
            self._successful_requests = 0
            self._rate_limit_count = 0
            self._retries_from_client = 0
            self._last_request_time = 0.0
            self._instruments_completed = 0
            self._instruments_remaining = 0
        self._semaphore = asyncio.Semaphore(self._concurrency)
