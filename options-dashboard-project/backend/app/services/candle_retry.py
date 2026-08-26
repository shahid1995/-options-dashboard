"""Retry / backoff infrastructure — Phase 7.8D.

Provides ``fetch_with_retry`` for wrapping any async Upstox API call with
exponential backoff.  Handles HTTP 429 (rate limit), transient 5xx, and
network failures while immediately propagating permanent 4xx errors.

Design constraints (§8):
  - Maximum retry count is bounded.
  - No retry on auth errors (401/403) or client errors (400/422).
  - Exponential backoff with configurable multiplier and cap.
  - 429 responses get a minimum 2-second delay.
  - Produces useful error information when retries are exhausted.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.upstox import UpstoxError

logger = logging.getLogger(__name__)

# Defaults matching §5.3 candle_config.py
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0

# Minimum delay for 429 rate-limit responses (seconds)
RATE_LIMIT_MIN_DELAY = 2.0

# Non-retryable HTTP status codes
PERMANENT_ERROR_CODES = frozenset({400, 401, 403, 422})

# Retryable HTTP status codes
RETRYABLE_ERROR_CODES = frozenset({429, 500, 502, 503})


async def fetch_with_retry(
    fetch_fn,
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    _test_sleep=None,
    **kwargs,
) -> dict:
    """Execute an async fetch function with exponential backoff retry.

    Parameters
    ----------
    fetch_fn:
        An async callable (e.g. ``upstox.get_historical_candles``).
    *args, **kwargs:
        Forwarded to *fetch_fn*.
    max_retries:
        Maximum number of retries (default 3 → up to 4 total attempts).
    base_delay:
        Initial delay in seconds before the first retry (default 1.0).
    max_delay:
        Upper bound on delay in seconds (default 30.0).
    backoff_multiplier:
        Multiplied into the delay on each retry (default 2.0).
    _test_sleep:
        If provided, called instead of ``asyncio.sleep`` (for tests).

    Returns
    -------
    dict
        The raw response from *fetch_fn*.

    Raises
    ------
    UpstoxError
        On permanent errors (401/403/400/422) or when all retries are
        exhausted.  The final ``UpstoxError`` carries the upstream status
        code and message.
    """
    sleep_fn = _test_sleep or asyncio.sleep
    last_error: UpstoxError | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fetch_fn(*args, **kwargs)
        except UpstoxError as exc:
            last_error = exc
            status = exc.status_code

            # --- Non-retryable errors: raise immediately ---
            if status in PERMANENT_ERROR_CODES:
                raise

            # --- Retryable errors: backoff and retry ---
            if status in RETRYABLE_ERROR_CODES or status >= 500:
                delay = min(
                    base_delay * (backoff_multiplier ** attempt),
                    max_delay,
                )
                # 429: minimum 2-second delay
                if status == 429:
                    delay = max(delay, RATE_LIMIT_MIN_DELAY)

                logger.warning(
                    "Upstox error %d (attempt %d/%d), retrying in %.1fs: %s",
                    status, attempt + 1, max_retries + 1, delay, exc.message,
                )
                await sleep_fn(delay)
                continue

            # --- Unknown status: don't retry ---
            raise

    # All retries exhausted
    raise last_error  # type: ignore[misc]
