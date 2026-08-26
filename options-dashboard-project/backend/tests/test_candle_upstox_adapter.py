"""Phase 7.8A — Upstox adapter tests for historical candle and expired-instruments APIs.

All tests mock HTTP via ``respx`` — no live API calls.  The tests verify:
  - Correct URL construction (base URL, path, query params)
  - Correct headers (Authorization, Accept)
  - Response passthrough (raw dict returned)
  - Error propagation (UpstoxError raised for 4xx/5xx)
  - Edge cases (optional params, missing fields)
  - candle_config constants are sane

Follows the existing ``test_upstox.py`` conventions.
"""

import httpx
import pytest
import respx

from app.services import upstox
from app.services.candle_config import (
    CANDLE_INTERVAL,
    CANDLE_UNIT,
    CANDLES_PER_TRADING_DAY,
    EXPIRED_NIFTY_INSTRUMENT_KEY,
    MARKET_CLOSE_IST,
    MARKET_OPEN_IST,
    MAX_CHUNK_DAYS,
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL_SECONDS,
    NIFTY_INSTRUMENT_KEY,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOKEN = "test-access-token-78A"
NIFTY_KEY = "NSE_INDEX|Nifty 50"


# ---------------------------------------------------------------------------
# candle_config sanity checks
# ---------------------------------------------------------------------------


class TestCandleConfig:
    """Verify that the pipeline constants are internally consistent."""

    def test_instrument_keys_are_nonempty(self):
        assert NIFTY_INSTRUMENT_KEY
        assert EXPIRED_NIFTY_INSTRUMENT_KEY

    def test_instrument_keys_match(self):
        """Both V2 and V3 APIs use the same NIFTY instrument key."""
        assert NIFTY_INSTRUMENT_KEY == EXPIRED_NIFTY_INSTRUMENT_KEY

    def test_candle_interval_is_3(self):
        assert CANDLE_INTERVAL == 3

    def test_candle_unit_is_minutes(self):
        assert CANDLE_UNIT == "minutes"

    def test_candles_per_trading_day(self):
        # NIFTY index: 09:15-15:27 IST = 6h12m = 372min / 3 = 124
        assert CANDLES_PER_TRADING_DAY == 124

    def test_max_chunk_days_is_reasonable(self):
        assert 1 <= MAX_CHUNK_DAYS <= 31

    def test_retry_params_are_positive(self):
        assert MAX_RETRIES >= 1
        assert RETRY_BASE_DELAY_SECONDS > 0
        assert RETRY_MAX_DELAY_SECONDS > RETRY_BASE_DELAY_SECONDS
        assert RETRY_BACKOFF_MULTIPLIER > 1.0

    def test_min_request_interval_is_nonnegative(self):
        assert MIN_REQUEST_INTERVAL_SECONDS >= 0

    def test_market_hours_are_valid(self):
        assert MARKET_OPEN_IST == "09:15"
        # NIFTY index closes at 15:27 IST
        assert MARKET_CLOSE_IST == "15:27"


# ---------------------------------------------------------------------------
# get_historical_candles
# ---------------------------------------------------------------------------


class TestGetHistoricalCandles:
    """Tests for the V3 historical candle endpoint."""

    @respx.mock
    async def test_success_with_date_range(self):
        """GET /v3/historical-candle/.../to_date/from_date with correct headers."""
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22/2026-08-01"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "candles": [
                            ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                            ["2026-08-22T15:24:00+05:30", 25490.0, 25505.0, 25475.0, 25500.0, 12000, 0],
                        ]
                    },
                },
            )
        )

        data = await upstox.get_historical_candles(
            TOKEN, NIFTY_KEY, to_date="2026-08-22", from_date="2026-08-01"
        )

        assert data["status"] == "success"
        assert len(data["data"]["candles"]) == 2
        # Verify first candle structure
        c = data["data"]["candles"][0]
        assert c[0] == "2026-08-22T15:27:00+05:30"
        assert c[1] == 25500.0  # open
        assert c[5] == 15000  # volume

        # Verify request
        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/json"

    @respx.mock
    async def test_success_single_day(self):
        """When from_date is omitted the path has only to_date."""
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        data = await upstox.get_historical_candles(
            TOKEN, NIFTY_KEY, to_date="2026-08-22"
        )

        assert data["data"]["candles"] == []
        # Path should NOT contain a from_date segment
        request = route.calls.last.request
        assert "/2026-08-01" not in str(request.url)

    @respx.mock
    async def test_custom_unit_and_interval(self):
        """Unit and interval are embedded in the URL path."""
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/days/1/2026-08-22/2026-08-01"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        await upstox.get_historical_candles(
            TOKEN, NIFTY_KEY, to_date="2026-08-22", from_date="2026-08-01",
            unit="days", interval=1,
        )
        assert route.called

    @respx.mock
    async def test_raises_on_401(self):
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22"
        ).mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_historical_candles(TOKEN, NIFTY_KEY, to_date="2026-08-22")
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_raises_on_500(self):
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22"
        ).mock(return_value=httpx.Response(500, json={"error": "server error"}))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_historical_candles(TOKEN, NIFTY_KEY, to_date="2026-08-22")
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_empty_candles_array(self):
        """API returns success with empty candles — not an error."""
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-01-01"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        data = await upstox.get_historical_candles(TOKEN, NIFTY_KEY, to_date="2026-01-01")
        assert data["data"]["candles"] == []

    @respx.mock
    async def test_url_encoding_of_pipe_in_instrument_key(self):
        """Instrument key with pipe character is properly URL-encoded."""
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        await upstox.get_historical_candles(TOKEN, NIFTY_KEY, to_date="2026-08-22")
        # The pipe in NIFTY_KEY should be URL-encoded in the actual request
        request = route.calls.last.request
        # httpx encodes the pipe as %7C in the URL
        assert "%7C" in str(request.url) or "Nifty%2050" in str(request.url)


# ---------------------------------------------------------------------------
# get_intraday_candles
# ---------------------------------------------------------------------------


class TestGetIntradayCandles:
    """Tests for the V3 intraday candle endpoint."""

    @respx.mock
    async def test_success(self):
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/3"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "candles": [
                            ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                        ]
                    },
                },
            )
        )

        data = await upstox.get_intraday_candles(TOKEN, NIFTY_KEY)

        assert data["status"] == "success"
        assert len(data["data"]["candles"]) == 1

        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/json"

    @respx.mock
    async def test_custom_unit_and_interval(self):
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/5"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        await upstox.get_intraday_candles(TOKEN, NIFTY_KEY, unit="minutes", interval=5)
        assert route.called

    @respx.mock
    async def test_raises_on_401(self):
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/3"
        ).mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_intraday_candles(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_raises_on_500(self):
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/3"
        ).mock(return_value=httpx.Response(500, json={"error": "internal error"}))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_intraday_candles(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_uses_v3_base_url(self):
        """Intraday candles must hit V3, not V2."""
        route = respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/3"
        ).mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": {"candles": []}}
            )
        )

        await upstox.get_intraday_candles(TOKEN, NIFTY_KEY)
        assert "api.upstox.com/v3" in str(route.calls.last.request.url)


# ---------------------------------------------------------------------------
# get_expired_expiries
# ---------------------------------------------------------------------------


class TestGetExpiredExpiries:
    """Tests for the V2 expired-instruments expiries endpoint."""

    @respx.mock
    async def test_success(self):
        expiry_dates = [
            "2024-10-03", "2024-10-10", "2024-10-17", "2024-10-24",
            "2024-10-31", "2024-11-07", "2024-11-14", "2024-11-21",
            "2024-11-28", "2024-12-05", "2024-12-12", "2024-12-19",
            "2024-12-26", "2025-01-02", "2025-01-09", "2025-01-16",
        ]
        route = respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": expiry_dates})
        )

        data = await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)

        assert data["status"] == "success"
        assert data["data"] == expiry_dates
        assert len(data["data"]) == 16

        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/json"
        params = dict(httpx.QueryParams(request.url.query))
        assert params == {"instrument_key": NIFTY_KEY}

    @respx.mock
    async def test_uses_v2_base_url(self):
        """Expired instruments are V2, not V3."""
        route = respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )

        await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert "api.upstox.com/v2" in str(route.calls.last.request.url)

    @respx.mock
    async def test_empty_expiries(self):
        """No expired expiries available — returns empty list, not an error."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )

        data = await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert data["data"] == []

    @respx.mock
    async def test_raises_on_401(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_raises_on_403(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(403, json={"error": "forbidden"})
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_raises_on_plus_plan_required(self):
        """UDAPI1149 = Upstox Plus plan required."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(
                403,
                json={
                    "errors": [
                        {
                            "errorCode": "UDAPI1149",
                            "message": "This API is available exclusively with an Upstox Plus plan subscription",
                        }
                    ]
                },
            )
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 403
        assert "Plus plan" in exc_info.value.message

    @respx.mock
    async def test_raises_on_500(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_expired_option_contracts
# ---------------------------------------------------------------------------


class TestGetExpiredOptionContracts:
    """Tests for the V2 expired-option-contracts endpoint.

    This is the critical endpoint that returns authoritative per-instrument
    metadata including lot_size, minimum_lot, freeze_quantity, and tick_size.
    Historical lot_size values must be preserved exactly as returned.
    """

    # Realistic response based on Upstox documentation for NIFTY 2025-04-17
    SAMPLE_CONTRACTS = [
        {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47983|17-04-2025",
            "exchange_token": "47983",
            "trading_symbol": "NIFTY 20400 PE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "PE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 20400,
            "minimum_lot": 75,
            "weekly": True,
        },
        {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47982|17-04-2025",
            "exchange_token": "47982",
            "trading_symbol": "NIFTY 20400 CE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "CE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 20400,
            "minimum_lot": 75,
            "weekly": True,
        },
    ]

    @respx.mock
    async def test_success_full_response(self):
        route = respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(
            TOKEN, NIFTY_KEY, "2025-04-17"
        )

        assert data["status"] == "success"
        assert len(data["data"]) == 2

        # Verify request
        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/json"
        params = dict(httpx.QueryParams(request.url.query))
        assert params == {"instrument_key": NIFTY_KEY, "expiry_date": "2025-04-17"}

    @respx.mock
    async def test_preserves_lot_size_exactly(self):
        """Historical lot_size is stored exactly as returned — never inferred."""
        # lot_size=75 for April 2025 NIFTY (pre-reduction to 25)
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")

        pe_contract = data["data"][0]
        assert pe_contract["lot_size"] == 75
        assert pe_contract["minimum_lot"] == 75
        assert pe_contract["instrument_key"] == "NSE_FO|47983|17-04-2025"

    @respx.mock
    async def test_preserves_minimum_lot_separately(self):
        """lot_size and minimum_lot are separate fields — never assumed equal."""
        # Construct a response where minimum_lot != lot_size
        contracts = [
            {
                **self.SAMPLE_CONTRACTS[0],
                "lot_size": 75,
                "minimum_lot": 1,  # deliberately different
            }
        ]
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": contracts})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        contract = data["data"][0]
        assert contract["lot_size"] == 75
        assert contract["minimum_lot"] == 1

    @respx.mock
    async def test_preserves_freeze_quantity(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        contract = data["data"][0]
        assert contract["freeze_quantity"] == 1800

    @respx.mock
    async def test_preserves_tick_size(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        contract = data["data"][0]
        assert contract["tick_size"] == 5

    @respx.mock
    async def test_preserves_instrument_key_as_identity(self):
        """The instrument_key is the unique lookup identity for the registry."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        keys = {c["instrument_key"] for c in data["data"]}
        assert keys == {"NSE_FO|47983|17-04-2025", "NSE_FO|47982|17-04-2025"}

    @respx.mock
    async def test_preserves_strike_price_and_option_type(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        pe = [c for c in data["data"] if c["instrument_type"] == "PE"][0]
        ce = [c for c in data["data"] if c["instrument_type"] == "CE"][0]
        assert pe["strike_price"] == 20400
        assert ce["strike_price"] == 20400
        assert pe["trading_symbol"] == "NIFTY 20400 PE 17 APR 25"
        assert ce["trading_symbol"] == "NIFTY 20400 CE 17 APR 25"

    @respx.mock
    async def test_preserves_underlying_metadata(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                200, json={"status": "success", "data": self.SAMPLE_CONTRACTS}
            )
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        for c in data["data"]:
            assert c["underlying_key"] == "NSE_INDEX|Nifty 50"
            assert c["underlying_symbol"] == "NIFTY"
            assert c["underlying_type"] == "INDEX"
            assert c["segment"] == "NSE_FO"
            assert c["exchange"] == "NSE"
            assert c["weekly"] is True

    @respx.mock
    async def test_uses_v2_base_url(self):
        route = respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )

        await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert "api.upstox.com/v2" in str(route.calls.last.request.url)

    @respx.mock
    async def test_empty_contracts(self):
        """Some expiry dates may have no contracts — not an error."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert data["data"] == []

    @respx.mock
    async def test_raises_on_401(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_raises_on_plus_plan_required(self):
        """UDAPI1149 = Upstox Plus plan required for expired instruments."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                403,
                json={
                    "errors": [
                        {
                            "errorCode": "UDAPI1149",
                            "message": "This API is available exclusively with an Upstox Plus plan subscription",
                        }
                    ]
                },
            )
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_raises_on_invalid_instrument_key(self):
        """UDAPI100011 = invalid instrument key."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "errorCode": "UDAPI100011",
                            "message": "Invalid Instrument key",
                        }
                    ]
                },
            )
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, "INVALID_KEY", "2025-04-17")
        assert exc_info.value.status_code == 400

    @respx.mock
    async def test_raises_on_invalid_date(self):
        """UDAPI1088 = invalid date format."""
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "errorCode": "UDAPI1088",
                            "message": "Invalid date",
                        }
                    ]
                },
            )
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "not-a-date")
        assert exc_info.value.status_code == 400

    @respx.mock
    async def test_raises_on_500(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_many_contracts_per_expiry(self):
        """A typical NIFTY weekly expiry has 50+ strikes × 2 sides = 100+ contracts."""
        # Generate a realistic number of contracts
        contracts = []
        for strike in range(24000, 26000, 50):  # 40 strikes
            for side in ("CE", "PE"):
                contracts.append({
                    "name": "NIFTY",
                    "segment": "NSE_FO",
                    "exchange": "NSE",
                    "expiry": "2025-04-17",
                    "instrument_key": f"NSE_FO|{10000 + strike}|17-04-2025",
                    "exchange_token": str(10000 + strike),
                    "trading_symbol": f"NIFTY {strike} {side} 17 APR 25",
                    "tick_size": 5,
                    "lot_size": 75,
                    "instrument_type": side,
                    "freeze_quantity": 1800,
                    "underlying_key": "NSE_INDEX|Nifty 50",
                    "underlying_type": "INDEX",
                    "underlying_symbol": "NIFTY",
                    "strike_price": strike,
                    "minimum_lot": 75,
                    "weekly": True,
                })

        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": contracts})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        expected = len(range(24000, 26000, 50)) * 2  # 40 strikes × 2 sides = 80
        assert len(data["data"]) == expected

        # Every contract should have the same lot_size (all from same expiry)
        lot_sizes = {c["lot_size"] for c in data["data"]}
        assert lot_sizes == {75}


# ---------------------------------------------------------------------------
# Historical lot-size preservation across different expiry periods
# ---------------------------------------------------------------------------


class TestHistoricalLotSizePreservation:
    """Verify that different historical expiry dates return different lot_sizes.

    NIFTY lot sizes have changed over time:
      - Before ~Oct 2024: 75
      - Oct 2024 – present: 25 (reduced by SEBI)

    The adapter must return whatever the Upstox API provides for each
    specific instrument.  We test that the adapter does NOT alter or
    normalize lot_size values.
    """

    @respx.mock
    async def test_pre_reduction_lot_size_75(self):
        """April 2025 contracts had lot_size=75 (before reduction)."""
        contract = {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47983|17-04-2025",
            "exchange_token": "47983",
            "trading_symbol": "NIFTY 24000 CE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "CE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 24000,
            "minimum_lot": 75,
            "weekly": True,
        }
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": [contract]})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert data["data"][0]["lot_size"] == 75

    @respx.mock
    async def test_post_reduction_lot_size_25(self):
        """Post-reduction contracts would have lot_size=25."""
        contract = {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-01-09",
            "instrument_key": "NSE_FO|50001|09-01-2025",
            "exchange_token": "50001",
            "trading_symbol": "NIFTY 24000 CE 09 JAN 25",
            "tick_size": 5,
            "lot_size": 25,
            "instrument_type": "CE",
            "freeze_quantity": 600,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 24000,
            "minimum_lot": 25,
            "weekly": True,
        }
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": [contract]})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-01-09")
        assert data["data"][0]["lot_size"] == 25

    @respx.mock
    async def test_adapter_does_not_modify_lot_size(self):
        """The adapter returns raw API data — no transformation of lot_size."""
        # Use an unusual lot_size to verify no normalization
        contract = {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2024-09-26",
            "instrument_key": "NSE_FO|99999|26-09-2024",
            "exchange_token": "99999",
            "trading_symbol": "NIFTY 25000 CE 26 SEP 24",
            "tick_size": 5,
            "lot_size": 65,  # hypothetical intermediate lot size
            "instrument_type": "CE",
            "freeze_quantity": 1500,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 25000,
            "minimum_lot": 65,
            "weekly": False,
        }
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": [contract]})
        )

        data = await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2024-09-26")
        # Adapter must NOT change lot_size to 25 or 75 — keep whatever API returns
        assert data["data"][0]["lot_size"] == 65


# ---------------------------------------------------------------------------
# Network / edge-case tests
# ---------------------------------------------------------------------------


class TestNetworkEdgeCases:
    """Verify behaviour under network-level failure conditions."""

    @respx.mock
    async def test_historical_candles_network_error(self):
        """httpx.RequestError is wrapped as UpstoxError(502)."""
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/{NIFTY_KEY}/minutes/3/2026-08-22"
        ).mock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_historical_candles(TOKEN, NIFTY_KEY, to_date="2026-08-22")
        assert exc_info.value.status_code == 502

    @respx.mock
    async def test_expired_expiries_network_error(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/expiries").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_expiries(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 502

    @respx.mock
    async def test_expired_contracts_network_error(self):
        respx.get(f"{upstox.BASE_URL}/expired-instruments/option/contract").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_expired_option_contracts(TOKEN, NIFTY_KEY, "2025-04-17")
        assert exc_info.value.status_code == 502

    @respx.mock
    async def test_intraday_candles_network_error(self):
        respx.get(
            f"{upstox.V3_BASE_URL}/historical-candle/intraday/{NIFTY_KEY}/minutes/3"
        ).mock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(upstox.UpstoxError) as exc_info:
            await upstox.get_intraday_candles(TOKEN, NIFTY_KEY)
        assert exc_info.value.status_code == 502
