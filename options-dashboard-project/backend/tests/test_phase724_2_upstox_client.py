"""Phase 7.24.2 — Centralized Upstox API Client Tests.

Comprehensive mocked tests covering:
  - Authentication
  - Success responses
  - Rate limiting (429)
  - Server errors (5xx)
  - Network errors
  - Permanent client errors (400, 403, 404)
  - Malformed responses
  - Metrics
  - Logging security
  - Retry behavior
  - Token never exposed

All tests use mocked HTTP responses.  No real Upstox calls are made.
"""

import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.upstox_client import (
    UpstoxClient,
    UpstoxAuthenticationError,
    UpstoxRateLimitError,
    UpstoxValidationError,
    UpstoxNotFoundError,
    UpstoxServerError,
    UpstoxNetworkError,
    UpstoxResponseError,
    UpstoxClientError,
    ErrorCategory,
    RetryPolicy,
    ApiMetrics,
    _validate_upstox_envelope,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockTokenProvider:
    """In-memory token provider for testing."""
    def __init__(self, token: str | None = "test-access-token-123"):
        self._token = token

    def get_token(self) -> str | None:
        return self._token

    def set_token(self, token: str | None):
        self._token = token


@pytest.fixture()
def token_provider():
    return MockTokenProvider()


@pytest.fixture()
def client(token_provider):
    """UpstoxClient with fast retry (no real sleeps in tests)."""
    policy = RetryPolicy(
        max_attempts=3, base_delay=0.01, max_delay=0.1,
        jitter=0.0, retry_on_network_error=True,
    )
    return UpstoxClient(
        token_provider=token_provider,
        retry_policy=policy,
        sleep_fn=lambda x: None,  # No real sleep in tests
    )


def _mock_response(status_code: int = 200, json_data: dict | None = None,
                    text: str = "", headers: dict | None = None) -> httpx.Response:
    """Create a mock httpx.Response."""
    if json_data is not None:
        content = json.dumps(json_data).encode()
    else:
        content = text.encode()

    resp = httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.upstox.com/v2/test"),
    )
    return resp


def _upstox_success(data=None):
    """Create a standard Upstox success envelope."""
    return {"status": "success", "data": data if data is not None else []}


def _upstox_error(errors: list):
    """Create a standard Upstox error envelope."""
    return {"status": "error", "errors": errors}


# ---------------------------------------------------------------------------
# A1: Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    @pytest.mark.asyncio
    async def test_valid_token(self, client):
        """Request with valid token succeeds."""
        mock_resp = _mock_response(200, _upstox_success(["2026-07-28"]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == ["2026-07-28"]

    @pytest.mark.asyncio
    async def test_missing_token(self, token_provider):
        """Request with no token raises AuthenticationError."""
        token_provider.set_token(None)
        policy = RetryPolicy(max_attempts=1, base_delay=0.01)
        c = UpstoxClient(token_provider=token_provider, retry_policy=policy)
        with pytest.raises(UpstoxAuthenticationError):
            await c.get_expiries("NSE_INDEX|Nifty 50")

    @pytest.mark.asyncio
    async def test_401_response(self, client):
        """HTTP 401 raises AuthenticationError."""
        mock_resp = _mock_response(401, _upstox_error([{"message": "Invalid token"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(UpstoxAuthenticationError) as exc_info:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert exc_info.value.category == ErrorCategory.AUTH_EXPIRED
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_no_retry(self, client):
        """401 is never retried."""
        mock_resp = _mock_response(401, _upstox_error([{"message": "Invalid token"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            with pytest.raises(UpstoxAuthenticationError):
                await client.get_expiries("NSE_INDEX|Nifty 50")
            # Should be called exactly once (no retry)
            assert mock_req.call_count == 1

    @pytest.mark.asyncio
    async def test_token_never_in_logs(self, client, caplog):
        """Access token must never appear in log output."""
        mock_resp = _mock_response(401, _upstox_error([{"message": "Invalid token"}]))
        with caplog.at_level(logging.DEBUG):
            with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
                try:
                    await client.get_expiries("NSE_INDEX|Nifty 50")
                except UpstoxAuthenticationError:
                    pass

        for record in caplog.records:
            assert "test-access-token-123" not in record.message
            assert "Bearer" not in record.message


# ---------------------------------------------------------------------------
# A2: Success responses
# ---------------------------------------------------------------------------

class TestSuccessResponses:
    @pytest.mark.asyncio
    async def test_valid_200_response(self, client):
        """Valid 200 with data returns parsed data."""
        mock_resp = _mock_response(200, _upstox_success(["2026-07-28", "2026-08-28"]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == ["2026-07-28", "2026-08-28"]

    @pytest.mark.asyncio
    async def test_empty_response(self, client):
        """Empty data returns empty list (not an error)."""
        mock_resp = _mock_response(200, _upstox_success([]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []

    @pytest.mark.asyncio
    async def test_contracts_with_instruments_wrapper(self, client):
        """Contracts response wrapped in {"instruments": [...]} is handled."""
        data = {"instruments": [{"instrument_key": "NSE_FO|123|28-07-2026"}]}
        mock_resp = _mock_response(200, _upstox_success(data))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_contracts("NSE_INDEX|Nifty 50", "2026-07-28")
            assert len(result) == 1
            assert result[0]["instrument_key"] == "NSE_FO|123|28-07-2026"

    @pytest.mark.asyncio
    async def test_historical_candles(self, client):
        """Historical candles response returns candle arrays."""
        candles = [
            ["2026-07-28T09:15:00+05:30", 24000, 24010, 23990, 24005, 100000, 0],
            ["2026-07-28T09:18:00+05:30", 24005, 24015, 23995, 24010, 110000, 0],
        ]
        mock_resp = _mock_response(200, _upstox_success({"candles": candles}))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_historical_candles(
                "NSE_INDEX|Nifty 50", "2026-07-28", from_date="2026-07-28"
            )
            assert len(result) == 2
            assert result[0][1] == 24000  # open price


# ---------------------------------------------------------------------------
# A3: Rate limiting (429)
# ---------------------------------------------------------------------------

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_429_with_retry_after(self, client):
        """429 with Retry-After header retries after the specified delay."""
        resp_429 = _mock_response(429, _upstox_error([{"message": "Rate limit"}]),
                                   headers={"Retry-After": "0.01"})
        resp_200 = _mock_response(200, _upstox_success(["2026-07-28"]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_429
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == ["2026-07-28"]
            assert client.metrics.rate_limit_count == 1
            assert client.metrics.retry_count == 1

    @pytest.mark.asyncio
    async def test_429_without_retry_after(self, client):
        """429 without Retry-After uses exponential backoff."""
        resp_429 = _mock_response(429, _upstox_error([{"message": "Rate limit"}]))
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return resp_429
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []
            assert client.metrics.rate_limit_count == 2

    @pytest.mark.asyncio
    async def test_429_retry_limit_exceeded(self, client):
        """429 after all retries raises RateLimitError."""
        resp_429 = _mock_response(429, _upstox_error([{"message": "Rate limit"}]))

        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=resp_429):
            with pytest.raises(UpstoxRateLimitError) as exc_info:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert exc_info.value.category == ErrorCategory.RATE_LIMIT
            assert client.metrics.retry_count >= 1


# ---------------------------------------------------------------------------
# A4: Server errors (5xx)
# ---------------------------------------------------------------------------

class TestServerErrors:
    @pytest.mark.asyncio
    async def test_500_retry_succeeds(self, client):
        """500 followed by success retries correctly."""
        resp_500 = _mock_response(500, _upstox_error([{"message": "Internal error"}]))
        resp_200 = _mock_response(200, _upstox_success(["ok"]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_500
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == ["ok"]
            assert client.metrics.retry_count == 1

    @pytest.mark.asyncio
    async def test_500_retry_limit_exceeded(self, client):
        """500 after all retries raises ServerError."""
        resp_500 = _mock_response(500, _upstox_error([{"message": "Internal error"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=resp_500):
            with pytest.raises(UpstoxServerError) as exc_info:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_502_retry_succeeds(self, client):
        """502 (Bad Gateway) is retried."""
        resp_502 = _mock_response(502)
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_502
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []

    @pytest.mark.asyncio
    async def test_503_retry_succeeds(self, client):
        """503 (Service Unavailable) is retried."""
        resp_503 = _mock_response(503)
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_503
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []

    @pytest.mark.asyncio
    async def test_504_retry_succeeds(self, client):
        """504 (Gateway Timeout) is retried."""
        resp_504 = _mock_response(504)
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_504
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []


# ---------------------------------------------------------------------------
# A5: Network errors
# ---------------------------------------------------------------------------

class TestNetworkErrors:
    @pytest.mark.asyncio
    async def test_connection_timeout_retry_succeeds(self, client):
        """Connection timeout retries and eventually succeeds."""
        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectTimeout("Connection timed out")
            return _mock_response(200, _upstox_success(["ok"]))

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == ["ok"]
            assert client.metrics.network_failures == 1

    @pytest.mark.asyncio
    async def test_read_timeout_retry_succeeds(self, client):
        """Read timeout retries and eventually succeeds."""
        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("Read timed out")
            return _mock_response(200, _upstox_success([]))

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []

    @pytest.mark.asyncio
    async def test_connection_error_retry_succeeds(self, client):
        """Connection error retries and eventually succeeds."""
        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return _mock_response(200, _upstox_success([]))

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []

    @pytest.mark.asyncio
    async def test_network_error_limit_exceeded(self, client):
        """Network error after all retries raises NetworkError."""
        async def mock_request(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            with pytest.raises(UpstoxNetworkError):
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert client.metrics.network_failures >= 3


# ---------------------------------------------------------------------------
# A6: Permanent client errors (no retry)
# ---------------------------------------------------------------------------

class TestPermanentErrors:
    @pytest.mark.asyncio
    async def test_400_no_retry(self, client):
        """400 raises ValidationError immediately (no retry)."""
        mock_resp = _mock_response(400, _upstox_error([{"message": "Bad request"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            with pytest.raises(UpstoxValidationError):
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert mock_req.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_403_no_retry(self, client):
        """403 raises Forbidden error immediately."""
        mock_resp = _mock_response(403, _upstox_error([{"message": "Forbidden"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            with pytest.raises(UpstoxClientError) as exc_info:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert exc_info.value.status_code == 403
            assert mock_req.call_count == 1

    @pytest.mark.asyncio
    async def test_404_no_retry(self, client):
        """404 raises NotFoundError immediately."""
        mock_resp = _mock_response(404, _upstox_error([{"message": "Not found"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            with pytest.raises(UpstoxNotFoundError):
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# A7: Malformed responses
# ---------------------------------------------------------------------------

class TestMalformedResponses:
    @pytest.mark.asyncio
    async def test_invalid_json(self, client):
        """Non-JSON response raises ResponseError."""
        mock_resp = _mock_response(200, text="not json at all")
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(UpstoxResponseError) as exc_info:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            assert "Non-JSON" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_data_field(self, client):
        """Response without data field returns empty data (graceful)."""
        mock_resp = _mock_response(200, json_data={"status": "success"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []  # Graceful fallback

    @pytest.mark.asyncio
    async def test_wrong_data_type(self, client):
        """Response with wrong data type is handled gracefully."""
        mock_resp = _mock_response(200, _upstox_success("not a list"))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []  # Graceful fallback

    @pytest.mark.asyncio
    async def test_upstox_error_envelope(self, client):
        """Upstox error envelope is parsed correctly."""
        mock_resp = _mock_response(400, _upstox_error([{"message": "Invalid instrument"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(UpstoxValidationError) as exc_info:
                await client.get_expiries("INVALID_KEY")
            assert "Invalid instrument" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_list_response(self, client):
        """Empty list response is valid."""
        mock_resp = _mock_response(200, json_data=[])
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert result == []


# ---------------------------------------------------------------------------
# A8: Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    @pytest.mark.asyncio
    async def test_request_count(self, client):
        """Metrics track total requests."""
        mock_resp = _mock_response(200, _upstox_success([]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            await client.get_expiries("NSE_INDEX|Nifty 50")
            await client.get_expiries("NSE_INDEX|Nifty 50")
            m = client.get_metrics()
            assert m["total_requests"] == 2
            assert m["successful_requests"] == 2

    @pytest.mark.asyncio
    async def test_failure_count(self, client):
        """Metrics track failures."""
        mock_resp = _mock_response(400, _upstox_error([{"message": "Bad"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            try:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            except UpstoxValidationError:
                pass
            m = client.get_metrics()
            assert m["failed_requests"] == 1

    @pytest.mark.asyncio
    async def test_retry_count(self, client):
        """Metrics track retries."""
        resp_500 = _mock_response(500)
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_500
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            await client.get_expiries("NSE_INDEX|Nifty 50")
            m = client.get_metrics()
            assert m["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_rate_limit_count(self, client):
        """Metrics track 429 occurrences."""
        resp_429 = _mock_response(429)
        resp_200 = _mock_response(200, _upstox_success([]))

        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_429
            return resp_200

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            await client.get_expiries("NSE_INDEX|Nifty 50")
            m = client.get_metrics()
            assert m["rate_limit_count"] == 1

    @pytest.mark.asyncio
    async def test_auth_failure_count(self, client):
        """Metrics track authentication failures."""
        mock_resp = _mock_response(401, _upstox_error([{"message": "Invalid token"}]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            try:
                await client.get_expiries("NSE_INDEX|Nifty 50")
            except UpstoxAuthenticationError:
                pass
            m = client.get_metrics()
            assert m["authentication_failures"] == 1

    def test_reset_metrics(self, client):
        """Metrics can be reset."""
        client.metrics.total_requests = 10
        client.metrics.successful_requests = 8
        client.reset_metrics()
        m = client.get_metrics()
        assert m["total_requests"] == 0
        assert m["successful_requests"] == 0


# ---------------------------------------------------------------------------
# A9: Response validation
# ---------------------------------------------------------------------------

class TestResponseValidation:
    def test_valid_envelope(self):
        """Valid Upstox envelope extracts data."""
        data = _validate_upstox_envelope(
            {"status": "success", "data": ["2026-07-28"]}, "GET", "/test"
        )
        assert data == ["2026-07-28"]

    def test_envelope_without_status(self):
        """Envelope without status field extracts data."""
        data = _validate_upstox_envelope(
            {"data": ["2026-07-28"]}, "GET", "/test"
        )
        assert data == ["2026-07-28"]

    def test_error_envelope(self):
        """Error envelope raises ResponseError."""
        with pytest.raises(UpstoxResponseError):
            _validate_upstox_envelope(
                {"status": "error", "errors": [{"message": "Bad"}]},
                "GET", "/test"
            )

    def test_non_dict_response(self):
        """Non-dict response raises ResponseError."""
        with pytest.raises(UpstoxResponseError):
            _validate_upstox_envelope("not a dict", "GET", "/test")


# ---------------------------------------------------------------------------
# A10: Retry policy
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_default_policy(self):
        """Default retry policy has sensible values."""
        p = RetryPolicy()
        assert p.max_attempts == 3
        assert p.base_delay == 1.0
        assert p.max_delay == 30.0
        assert 429 in p.retryable_status
        assert 500 in p.retryable_status
        assert 503 in p.retryable_status

    def test_custom_policy(self):
        """Custom retry policy overrides defaults."""
        p = RetryPolicy(max_attempts=5, base_delay=2.0, max_delay=60.0)
        assert p.max_attempts == 5
        assert p.base_delay == 2.0
        assert p.max_delay == 60.0


# ---------------------------------------------------------------------------
# A11: Logging security
# ---------------------------------------------------------------------------

class TestLoggingSecurity:
    @pytest.mark.asyncio
    async def test_token_not_in_error_logs(self, client, caplog):
        """Access token never appears in any log output."""
        mock_resp = _mock_response(500, _upstox_error([{"message": "Server error"}]))
        with caplog.at_level(logging.DEBUG):
            with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
                try:
                    await client.get_expiries("NSE_INDEX|Nifty 50")
                except UpstoxServerError:
                    pass

        for record in caplog.records:
            assert "test-access-token-123" not in record.message
            assert "Bearer" not in record.message

    @pytest.mark.asyncio
    async def test_token_not_in_success_logs(self, client, caplog):
        """Access token never appears in success logs."""
        mock_resp = _mock_response(200, _upstox_success([]))
        with caplog.at_level(logging.DEBUG):
            with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
                await client.get_expiries("NSE_INDEX|Nifty 50")

        for record in caplog.records:
            assert "test-access-token-123" not in record.message

    @pytest.mark.asyncio
    async def test_secret_not_in_logs(self, client, caplog):
        """Client secret never appears in logs."""
        mock_resp = _mock_response(200, _upstox_success([]))
        with caplog.at_level(logging.DEBUG):
            with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
                await client.get_expiries("NSE_INDEX|Nifty 50")

        for record in caplog.records:
            assert "client_secret" not in record.message.lower()


# ---------------------------------------------------------------------------
# A12: API method signatures
# ---------------------------------------------------------------------------

class TestApiMethods:
    @pytest.mark.asyncio
    async def test_get_expiries(self, client):
        """get_expiries calls correct endpoint."""
        mock_resp = _mock_response(200, _upstox_success(["2026-07-28"]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            await client.get_expiries("NSE_INDEX|Nifty 50")
            call_args = mock_req.call_args
            assert "/expired-instruments/expiries" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_contracts(self, client):
        """get_contracts calls correct endpoint."""
        mock_resp = _mock_response(200, _upstox_success([]))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            await client.get_contracts("NSE_INDEX|Nifty 50", "2026-07-28")
            call_args = mock_req.call_args
            assert "/expired-instruments/option/contract" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_historical_candles(self, client):
        """get_historical_candles calls V3 endpoint."""
        mock_resp = _mock_response(200, _upstox_success({"candles": []}))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            await client.get_historical_candles(
                "NSE_INDEX|Nifty 50", "2026-07-28", from_date="2026-07-01"
            )
            call_args = mock_req.call_args
            url = str(call_args)
            assert "v3" in url or "/historical-candle/" in url

    @pytest.mark.asyncio
    async def test_get_expired_historical_candles(self, client):
        """get_expired_historical_candles calls V2 endpoint."""
        mock_resp = _mock_response(200, _upstox_success({"candles": []}))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            await client.get_expired_historical_candles(
                "NSE_FO|123|28-07-2026", "3minute", "2026-07-28", "2026-07-01"
            )
            call_args = mock_req.call_args
            assert "/expired-instruments/historical-candle/" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_intraday_candles(self, client):
        """get_intraday_candles calls V3 intraday endpoint."""
        mock_resp = _mock_response(200, _upstox_success({"candles": []}))
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp) as mock_req:
            await client.get_intraday_candles("NSE_INDEX|Nifty 50")
            call_args = mock_req.call_args
            url = str(call_args)
            assert "intraday" in url or "/historical-candle/intraday/" in url


# ---------------------------------------------------------------------------
# A13: End-to-end workflow
# ---------------------------------------------------------------------------

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_workflow(self, client):
        """Simulate a full ingestion workflow: expiries -> contracts -> candles."""
        resp_expiries = _mock_response(200, _upstox_success(["2026-07-28"]))
        resp_contracts = _mock_response(200, _upstox_success([
            {"instrument_key": "NSE_FO|123|28-07-2026", "lot_size": 75},
            {"instrument_key": "NSE_FO|456|28-07-2026", "lot_size": 75},
        ]))
        resp_candles = _mock_response(200, _upstox_success({
            "candles": [
                ["2026-07-28T09:15:00+05:30", 100, 105, 95, 102, 500, 10000],
            ]
        }))

        responses = [resp_expiries, resp_contracts, resp_candles]
        call_idx = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_idx
            r = responses[call_idx]
            call_idx += 1
            return r

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            expiries = await client.get_expiries("NSE_INDEX|Nifty 50")
            assert expiries == ["2026-07-28"]

            contracts = await client.get_contracts("NSE_INDEX|Nifty 50", "2026-07-28")
            assert len(contracts) == 2

            candles = await client.get_expired_historical_candles(
                "NSE_FO|123|28-07-2026", "3minute", "2026-07-28", "2026-07-01"
            )
            assert len(candles) == 1

            m = client.get_metrics()
            assert m["total_requests"] == 3
            assert m["successful_requests"] == 3
            assert m["failed_requests"] == 0
