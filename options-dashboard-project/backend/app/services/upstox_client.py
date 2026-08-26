"""Centralized Upstox API client — Phase 7.24.2.

Provides a single, reusable HTTP client for all Upstox API interactions.
Designed for the historical backfill and daily ingestion pipelines.

Key properties:
  - **One retry policy** — centralized, not duplicated per method
  - **Rate-limit aware** — detects 429, respects Retry-After, exponential backoff
  - **Error normalization** — structured exceptions for every failure mode
  - **Metrics** — tracks request counts, retries, failures in memory
  - **Safe logging** — never logs tokens, secrets, or authorization headers
  - **Token-agnostic** — accepts a token provider, not a hard-coded token

Architecture:

    TokenProvider (interface)
           ↓
      UpstoxClient
           ↓
    Ingestion Layer (future)
           ↓
      Local SQLite DB

This module does NOT contain knowledge of whether data is already in the
database.  That decision belongs to the ingestion/orchestration layer.

No real Upstox API calls are made by this module during Phase 7.24.2.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    """Structured error categories for Upstox API failures."""
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMIT = "RATE_LIMIT"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Structured exceptions
# ---------------------------------------------------------------------------

class UpstoxClientError(Exception):
    """Base exception for all UpstoxClient errors."""

    def __init__(self, category: ErrorCategory, message: str, status_code: int | None = None):
        self.category = category
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{category.value}] {message}")


class UpstoxAuthenticationError(UpstoxClientError):
    """Access token is invalid or expired (HTTP 401)."""

    def __init__(self, message: str = "Access token is invalid or expired"):
        super().__init__(ErrorCategory.AUTH_EXPIRED, message, status_code=401)


class UpstoxRateLimitError(UpstoxClientError):
    """Rate limit exceeded (HTTP 429)."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float | None = None):
        super().__init__(ErrorCategory.RATE_LIMIT, message, status_code=429)
        self.retry_after = retry_after


class UpstoxValidationError(UpstoxClientError):
    """Bad request / validation error (HTTP 400)."""

    def __init__(self, message: str = "Bad request"):
        super().__init__(ErrorCategory.BAD_REQUEST, message, status_code=400)


class UpstoxNotFoundError(UpstoxClientError):
    """Resource not found (HTTP 404)."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(ErrorCategory.NOT_FOUND, message, status_code=404)


class UpstoxServerError(UpstoxClientError):
    """Upstox server error (HTTP 5xx)."""

    def __init__(self, message: str = "Upstox server error", status_code: int = 500):
        super().__init__(ErrorCategory.SERVER_ERROR, message, status_code=status_code)


class UpstoxNetworkError(UpstoxClientError):
    """Network / connection error."""

    def __init__(self, message: str = "Network error"):
        super().__init__(ErrorCategory.NETWORK, message)


class UpstoxResponseError(UpstoxClientError):
    """Unexpected response structure."""

    def __init__(self, message: str = "Unexpected response", status_code: int | None = None):
        super().__init__(ErrorCategory.MALFORMED_RESPONSE, message, status_code=status_code)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Centralized retry configuration."""
    max_attempts: int = 3
    base_delay: float = 1.0        # seconds
    max_delay: float = 30.0        # seconds
    jitter: float = 0.5            # ±50% randomization
    retryable_status: frozenset[int] = frozenset({429, 500, 502, 503, 504, 408})
    retry_on_network_error: bool = True


# ---------------------------------------------------------------------------
# API metrics
# ---------------------------------------------------------------------------

@dataclass
class ApiMetrics:
    """In-memory request statistics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_count: int = 0
    authentication_failures: int = 0
    retry_count: int = 0
    network_failures: int = 0
    total_elapsed_time: float = 0.0

    def snapshot(self) -> dict:
        """Return a copy of current metrics."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rate_limit_count": self.rate_limit_count,
            "authentication_failures": self.authentication_failures,
            "retry_count": self.retry_count,
            "network_failures": self.network_failures,
            "total_elapsed_time": round(self.total_elapsed_time, 3),
        }


# ---------------------------------------------------------------------------
# Token provider protocol
# ---------------------------------------------------------------------------

class TokenProvider(Protocol):
    """Interface for providing access tokens.

    Phase 7.24.2 defines the interface.  Phase 7.24.3 will implement
    persistent token caching.  The existing token_store.get_token()
    can be wrapped to satisfy this protocol.
    """
    def get_token(self) -> str | None: ...


# ---------------------------------------------------------------------------
# Upstox API endpoints
# ---------------------------------------------------------------------------

V2_BASE = "https://api.upstox.com/v2"
V3_BASE = "https://api.upstox.com/v3"


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _validate_upstox_envelope(data: Any, method: str, path: str) -> Any:
    """Validate the Upstox response envelope structure.

    Upstox responses follow: {"status": "success", "data": ...}
    Returns the ``data`` field contents.
    Raises UpstoxResponseError if the envelope is invalid.
    """
    # Bare list is a valid edge case (some endpoints return [] directly)
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        raise UpstoxResponseError(
            f"Expected dict or list response from {method} {path}, got {type(data).__name__}"
        )

    status = data.get("status")
    if status not in ("success", None):
        # Some endpoints don't include status; treat missing status as ok
        errors = data.get("errors")
        if errors:
            error_msg = str(errors)[:200]
            raise UpstoxResponseError(
                f"Upstox returned status={status} with errors: {error_msg}",
                status_code=400,
            )

    return data.get("data", data)


# ---------------------------------------------------------------------------
# Centralized Upstox API Client
# ---------------------------------------------------------------------------

class UpstoxClient:
    """Centralized Upstox API client with retry, rate limiting, and metrics.

    Usage::

        provider = MyTokenProvider()
        client = UpstoxClient(token_provider=provider)

        expiries = await client.get_expiries("NSE_INDEX|Nifty 50")
        contracts = await client.get_contracts("NSE_INDEX|Nifty 50", "2026-07-28")
        candles = await client.get_historical_candles(
            "NSE_INDEX|Nifty 50", "2026-08-20", from_date="2026-08-01"
        )

    The client does NOT contain knowledge of whether data already exists
    locally.  That decision belongs to the ingestion layer.
    """

    def __init__(
        self,
        token_provider: TokenProvider,
        retry_policy: RetryPolicy | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self._token_provider = token_provider
        self._retry = retry_policy or RetryPolicy()
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._sleep = sleep_fn or time.sleep
        self.metrics = ApiMetrics()

    # ------------------------------------------------------------------
    # Core request method (single retry entry point)
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        base_url: str = V2_BASE,
        params: dict | None = None,
        json_body: dict | None = None,
        extra_headers: dict | None = None,
    ) -> dict:
        """Make an HTTP request with centralized retry and error handling.

        This is the ONLY method that creates httpx requests.  All API
        methods delegate here.
        """
        token = self._token_provider.get_token()
        if not token:
            raise UpstoxAuthenticationError("No access token available")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if extra_headers:
            headers.update(extra_headers)

        url = f"{base_url}{path}"
        last_exception: Exception | None = None

        for attempt in range(1, self._retry.max_attempts + 1):
            self.metrics.total_requests += 1
            attempt_start = time.monotonic()

            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        self._read_timeout,
                        connect=self._connect_timeout,
                        read=self._read_timeout,
                        write=self._connect_timeout,
                        pool=self._connect_timeout,
                    ),
                ) as client:
                    resp = await client.request(
                        method, url, headers=headers,
                        params=params, json=json_body,
                    )

                elapsed = time.monotonic() - attempt_start
                self.metrics.total_elapsed_time += elapsed

                # --- Success ---
                if resp.status_code < 400:
                    self.metrics.successful_requests += 1
                    self._log_request(method, path, resp.status_code, elapsed, attempt)
                    try:
                        data = resp.json()
                    except ValueError:
                        raise UpstoxResponseError(
                            f"Non-JSON response from {method} {path}"
                        )
                    return _validate_upstox_envelope(data, method, path)

                # --- 401: Authentication failure (never retry) ---
                if resp.status_code == 401:
                    self.metrics.authentication_failures += 1
                    self.metrics.failed_requests += 1
                    self._log_request(method, path, resp.status_code, elapsed, attempt)
                    raise UpstoxAuthenticationError(
                        self._extract_error_message(resp)
                    )

                # --- 429: Rate limit ---
                if resp.status_code == 429:
                    self.metrics.rate_limit_count += 1
                    retry_after = self._parse_retry_after(resp)
                    self._log_request(method, path, resp.status_code, elapsed, attempt,
                                       retry_after=retry_after)
                    if attempt < self._retry.max_attempts:
                        self.metrics.retry_count += 1
                        delay = retry_after or self._compute_backoff(attempt)
                        self._sleep(delay)
                        continue
                    self.metrics.failed_requests += 1
                    raise UpstoxRateLimitError(
                        f"Rate limit exceeded after {attempt} attempts",
                        retry_after=retry_after,
                    )

                # --- 400, 403, 404: Permanent client errors (no retry) ---
                if resp.status_code in (400, 403, 404):
                    self.metrics.failed_requests += 1
                    self._log_request(method, path, resp.status_code, elapsed, attempt)
                    msg = self._extract_error_message(resp)
                    if resp.status_code == 400:
                        raise UpstoxValidationError(msg)
                    elif resp.status_code == 403:
                        raise UpstoxClientError(ErrorCategory.FORBIDDEN, msg, 403)
                    else:
                        raise UpstoxNotFoundError(msg)

                # --- 5xx / 408: Transient server errors (retry) ---
                if resp.status_code in self._retry.retryable_status:
                    self._log_request(method, path, resp.status_code, elapsed, attempt)
                    if attempt < self._retry.max_attempts:
                        self.metrics.retry_count += 1
                        delay = self._compute_backoff(attempt)
                        self._sleep(delay)
                        continue
                    self.metrics.failed_requests += 1
                    raise UpstoxServerError(
                        f"Server error {resp.status_code} after {attempt} attempts",
                        status_code=resp.status_code,
                    )

                # --- Other 4xx: fail immediately ---
                self.metrics.failed_requests += 1
                self._log_request(method, path, resp.status_code, elapsed, attempt)
                raise UpstoxClientError(
                    ErrorCategory.UNKNOWN,
                    f"HTTP {resp.status_code}: {self._extract_error_message(resp)}",
                    status_code=resp.status_code,
                )

            except httpx.TimeoutException as e:
                elapsed = time.monotonic() - attempt_start
                self.metrics.total_elapsed_time += elapsed
                self.metrics.network_failures += 1
                last_exception = UpstoxNetworkError(f"Timeout: {e}")
                self._log_request(method, path, None, elapsed, attempt, error=str(e))
                if attempt < self._retry.max_attempts and self._retry.retry_on_network_error:
                    self.metrics.retry_count += 1
                    delay = self._compute_backoff(attempt)
                    self._sleep(delay)
                    continue

            except httpx.RequestError as e:
                elapsed = time.monotonic() - attempt_start
                self.metrics.total_elapsed_time += elapsed
                self.metrics.network_failures += 1
                last_exception = UpstoxNetworkError(f"Connection error: {e}")
                self._log_request(method, path, None, elapsed, attempt, error=str(e))
                if attempt < self._retry.max_attempts and self._retry.retry_on_network_error:
                    self.metrics.retry_count += 1
                    delay = self._compute_backoff(attempt)
                    self._sleep(delay)
                    continue

            except (UpstoxAuthenticationError, UpstoxValidationError,
                    UpstoxNotFoundError, UpstoxClientError) as e:
                raise  # Already structured, propagate immediately

            except UpstoxResponseError:
                raise

            except Exception as e:
                self.metrics.failed_requests += 1
                raise UpstoxClientError(
                    ErrorCategory.UNKNOWN, f"Unexpected error: {e}"
                ) from e

        # All attempts exhausted
        self.metrics.failed_requests += 1
        if last_exception:
            raise last_exception
        raise UpstoxServerError(f"All {self._retry.max_attempts} attempts failed")

    # ------------------------------------------------------------------
    # Backoff computation
    # ------------------------------------------------------------------

    def _compute_backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(
            self._retry.base_delay * (2 ** (attempt - 1)),
            self._retry.max_delay,
        )
        jitter_range = delay * self._retry.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return max(0.1, delay)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_error_message(resp: httpx.Response) -> str:
        """Extract a safe error message from Upstox response."""
        try:
            body = resp.json()
        except ValueError:
            return resp.text.strip()[:300] or f"HTTP {resp.status_code}"
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            message = errors[0].get("message", "")
            if message:
                return str(message)[:300]
        return str(body)[:300]

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        """Parse Retry-After header."""
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass
        return None

    # ------------------------------------------------------------------
    # Safe logging
    # ------------------------------------------------------------------

    @staticmethod
    def _log_request(
        method: str, path: str, status: int | None,
        elapsed: float, attempt: int, *,
        retry_after: float | None = None, error: str | None = None,
    ) -> None:
        """Log request details without exposing tokens or secrets.

        Logs MUST NOT contain:
          - access_token
          - Authorization header
          - client_secret
          - refresh_token
          - OAuth code
        """
        parts = [f"{method} {path}"]
        if status is not None:
            parts.append(f"status={status}")
        parts.append(f"elapsed={elapsed:.3f}s")
        if attempt > 1:
            parts.append(f"attempt={attempt}")
        if retry_after is not None:
            parts.append(f"retry_after={retry_after}")
        if error:
            parts.append(f"error={error[:100]}")

        msg = "Upstox API: " + " ".join(parts)
        if status and status >= 500:
            logger.warning(msg)
        elif status and status >= 400:
            logger.warning(msg)
        else:
            logger.debug(msg)

    # ------------------------------------------------------------------
    # API methods — Expiries
    # ------------------------------------------------------------------

    async def get_expiries(self, instrument_key: str) -> list[str]:
        """Fetch all available expiry dates for expired instruments.

        ``GET /v2/expired-instruments/expiries?instrument_key={instrument_key}``

        Returns a list of YYYY-MM-DD strings.  Returns empty list when
        no expiries are available (not an error).
        """
        data = await self._request(
            "GET",
            "/expired-instruments/expiries",
            params={"instrument_key": instrument_key},
        )
        if isinstance(data, list):
            return data
        return []

    # ------------------------------------------------------------------
    # API methods — Contracts
    # ------------------------------------------------------------------

    async def get_contracts(
        self, instrument_key: str, expiry_date: str,
    ) -> list[dict]:
        """Fetch expired option contract metadata for a given expiry.

        ``GET /v2/expired-instruments/option/contract?instrument_key=...&expiry_date=...``

        Returns a list of contract dicts.  Returns empty list when no
        contracts are available (not an error — the expiry may not
        have expired yet or may not exist).
        """
        data = await self._request(
            "GET",
            "/expired-instruments/option/contract",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Some responses wrap in {"instruments": [...]}
            instruments = data.get("instruments", data.get("data", []))
            if isinstance(instruments, list):
                return instruments
        return []

    # ------------------------------------------------------------------
    # API methods — Historical candles (V3)
    # ------------------------------------------------------------------

    async def get_historical_candles(
        self,
        instrument_key: str,
        to_date: str,
        from_date: str | None = None,
        unit: str = "minutes",
        interval: int = 3,
    ) -> list[list]:
        """Fetch historical candle data from Upstox V3.

        ``GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}[/{from_date}]``

        Returns a list of candle arrays:
        ``[timestamp, open, high, low, close, volume, open_interest]``

        Timestamps are IST (UTC+5:30).

        For 3-minute candles the maximum retrieval window is 1 month.
        Returns empty list when no data is available.
        """
        path = f"/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}"
        if from_date:
            path += f"/{from_date}"

        data = await self._request("GET", path, base_url=V3_BASE)
        if isinstance(data, dict):
            candles = data.get("candles", [])
            return candles if isinstance(candles, list) else []
        return []

    # ------------------------------------------------------------------
    # API methods — Expired historical candles (V2)
    # ------------------------------------------------------------------

    async def get_expired_historical_candles(
        self,
        expired_instrument_key: str,
        interval: str,
        to_date: str,
        from_date: str,
    ) -> list[list]:
        """Fetch historical candle data for an expired option/future contract.

        ``GET /v2/expired-instruments/historical-candle/{key}/{interval}/{to_date}/{from_date}``

        Returns a list of candle arrays:
        ``[timestamp, open, high, low, close, volume, open_interest]``

        Timestamps are IST (UTC+5:30).
        Returns empty list when no data is available.
        """
        path = (
            f"/expired-instruments/historical-candle/{expired_instrument_key}"
            f"/{interval}/{to_date}/{from_date}"
        )

        data = await self._request("GET", path)
        if isinstance(data, dict):
            candles = data.get("candles", [])
            return candles if isinstance(candles, list) else []
        return []

    # ------------------------------------------------------------------
    # API methods — Intraday candles (V3)
    # ------------------------------------------------------------------

    async def get_intraday_candles(
        self,
        instrument_key: str,
        unit: str = "minutes",
        interval: int = 3,
    ) -> list[list]:
        """Fetch current trading day's intraday candle data from Upstox V3.

        ``GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}``

        Returns a list of candle arrays.
        Returns empty list when no data is available.
        """
        path = f"/historical-candle/intraday/{instrument_key}/{unit}/{interval}"
        data = await self._request("GET", path, base_url=V3_BASE)
        if isinstance(data, dict):
            candles = data.get("candles", [])
            return candles if isinstance(candles, list) else []
        return []

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict:
        """Return current API metrics snapshot."""
        return self.metrics.snapshot()

    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self.metrics = ApiMetrics()
