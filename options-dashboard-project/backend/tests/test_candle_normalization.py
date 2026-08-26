"""Phase 7.8B / 7.24.4 — Candle ingestion / normalization tests.

Exercises the four public functions in ``candle_ingestion``:

* ``normalize_candle_timestamp``  — IST → naive IST (Phase 7.24.4)
* ``normalize_candle``            — raw array → record_candles() dict
* ``normalize_candles``           — batch wrapper
* ``extract_candles_from_response`` — pull candle array from API response

Phase 7.24.4: All timestamps are stored as naive IST.
Follows existing ``test_upstox.py`` conventions.  No live API calls.
"""

from datetime import datetime

import pytest

from app.services.candle_ingestion import (
    DEFAULT_INTERVAL,
    DEFAULT_SYMBOL,
    extract_candles_from_response,
    normalize_candle,
    normalize_candle_timestamp,
    normalize_candles,
)
from app.utils.market_time import IST


# ===================================================================
# normalize_candle_timestamp
# ===================================================================


class TestNormalizeCandleTimestamp:
    """Phase 7.24.4 — IST timestamp → naive IST datetime for SQLite storage."""

    def test_standard_ist_offset(self):
        """15:15 IST → 15:15 naive IST."""
        result = normalize_candle_timestamp("2025-01-12T15:15:00+05:30")
        assert result == datetime(2025, 1, 12, 15, 15, 0)
        assert result.tzinfo is None  # naive IST

    def test_market_open_ist(self):
        """09:15 IST → 09:15 naive IST."""
        result = normalize_candle_timestamp("2026-08-22T09:15:00+05:30")
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_market_close_ist(self):
        """15:27 IST → 15:27 naive IST."""
        result = normalize_candle_timestamp("2026-08-22T15:27:00+05:30")
        assert result == datetime(2026, 8, 22, 15, 27, 0)

    def test_midnight_ist(self):
        """00:00 IST → 00:00 naive IST."""
        result = normalize_candle_timestamp("2026-01-15T00:00:00+05:30")
        assert result == datetime(2026, 1, 15, 0, 0, 0)

    def test_end_of_day_ist(self):
        """23:59:59 IST → 23:59:59 naive IST."""
        result = normalize_candle_timestamp("2026-06-15T23:59:59+05:30")
        assert result == datetime(2026, 6, 15, 23, 59, 59)

    def test_naive_timestamp_assumes_ist(self):
        """Timestamp without offset is assumed to be IST (Phase 7.24.4)."""
        result = normalize_candle_timestamp("2025-01-12T15:15:00")
        assert result == datetime(2025, 1, 12, 15, 15, 0)

    def test_utc_offset_converts_to_ist(self):
        """UTC timestamp should be converted to IST."""
        result = normalize_candle_timestamp("2026-08-22T03:45:00+00:00")
        assert result == datetime(2026, 8, 22, 9, 15, 0)  # 03:45 UTC = 09:15 IST

    def test_z_suffix_converts_to_ist(self):
        """Z suffix (UTC) should be converted to IST."""
        result = normalize_candle_timestamp("2026-08-22T03:45:00Z")
        assert result == datetime(2026, 8, 22, 9, 15, 0)  # 03:45 UTC = 09:15 IST

    def test_with_milliseconds(self):
        """Timestamps with fractional seconds."""
        result = normalize_candle_timestamp("2026-08-22T15:27:00.123+05:30")
        assert result.year == 2026
        assert result.month == 8
        assert result.day == 22
        assert result.hour == 15
        assert result.minute == 27

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError):
            normalize_candle_timestamp(None)

    def test_invalid_string_raises(self):
        with pytest.raises((ValueError, TypeError)):
            normalize_candle_timestamp("not-a-timestamp")

    def test_non_string_raises_type_error(self):
        with pytest.raises((TypeError, ValueError)):
            normalize_candle_timestamp(12345)

    def test_result_is_naive(self):
        """SQLite stores naive datetimes — tzinfo must be None."""
        result = normalize_candle_timestamp("2026-08-22T15:27:00+05:30")
        assert result.tzinfo is None


# ===================================================================
# normalize_candle
# ===================================================================


class TestNormalizeCandle:
    """§6.2 — Raw Upstox candle array → record_candles() dict."""

    # A realistic NIFTY candle from Upstox V3
    SAMPLE_RAW = [
        "2026-08-22T15:27:00+05:30",
        25500.0,  # open
        25520.0,  # high
        25480.0,  # low
        25510.0,  # close
        15000,    # volume
        0,        # open_interest (ignored for index)
    ]

    def test_success_standard_candle(self):
        result = normalize_candle(self.SAMPLE_RAW)

        assert result is not None
        assert result["symbol"] == "NIFTY"
        assert result["interval"] == "3min"
        assert result["openTime"] == "2026-08-22T15:27:00"  # 15:27 IST → 15:27 naive IST
        assert result["open"] == 25500.0
        assert result["high"] == 25520.0
        assert result["low"] == 25480.0
        assert result["close"] == 25510.0
        assert result["volume"] == 15000.0

    def test_open_interest_is_ignored(self):
        """§12.5 — Volume and OI are never converted into lots."""
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000, 9999]
        result = normalize_candle(raw)
        assert result is not None
        # open_interest (9999) must not appear in output
        assert "open_interest" not in result
        assert "oi" not in result

    def test_volume_not_converted_to_lots(self):
        """Volume stays as raw float — never divided by lot_size."""
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 15000, 0]
        result = normalize_candle(raw)
        assert result["volume"] == 15000.0  # raw, not divided by any lot size

    def test_custom_symbol_and_interval(self):
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000]
        result = normalize_candle(raw, symbol="BANKNIFTY", interval="5min")
        assert result["symbol"] == "BANKNIFTY"
        assert result["interval"] == "5min"

    def test_symbol_is_uppercased(self):
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000]
        result = normalize_candle(raw, symbol="nifty")
        assert result["symbol"] == "NIFTY"

    def test_open_time_has_z_suffix(self):
        """Timestamp must end with Z for unambiguous UTC (§6.2)."""
        result = normalize_candle(self.SAMPLE_RAW)
        # Phase 7.24.4: timestamps no longer end with Z (they are naive IST)
        assert not result["openTime"].endswith("Z")

    def test_ohlcv_cast_to_float(self):
        """All OHLCV values are floats regardless of input type."""
        raw = ["2026-08-22T15:27:00+05:30", 25500, 25520, 25480, 25510, 15000]
        result = normalize_candle(raw)
        assert isinstance(result["open"], float)
        assert isinstance(result["high"], float)
        assert isinstance(result["low"], float)
        assert isinstance(result["close"], float)
        assert isinstance(result["volume"], float)

    def test_integer_ohlcv(self):
        """Integer prices are valid."""
        raw = ["2026-08-22T15:27:00+05:30", 100, 105, 95, 102, 5000]
        result = normalize_candle(raw)
        assert result["open"] == 100.0
        assert result["close"] == 102.0

    # --- Invalid inputs → None ---

    def test_none_returns_none(self):
        assert normalize_candle(None) is None

    def test_not_a_list_returns_none(self):
        assert normalize_candle("not a list") is None

    def test_too_short_returns_none(self):
        assert normalize_candle([1, 2, 3, 4, 5]) is None  # only 5 elements

    def test_empty_list_returns_none(self):
        assert normalize_candle([]) is None

    def test_missing_open_returns_none(self):
        raw = ["2026-08-22T15:27:00+05:30", None, 105.0, 95.0, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_missing_high_returns_none(self):
        raw = ["2026-08-22T15:27:00+05:30", 100.0, None, 95.0, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_missing_low_returns_none(self):
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, None, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_missing_close_returns_none(self):
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, None, 5000]
        assert normalize_candle(raw) is None

    def test_string_price_returns_none(self):
        raw = ["2026-08-22T15:27:00+05:30", "abc", 105.0, 95.0, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_invalid_timestamp_returns_none(self):
        raw = ["not-a-timestamp", 100.0, 105.0, 95.0, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_none_timestamp_returns_none(self):
        raw = [None, 100.0, 105.0, 95.0, 102.0, 5000]
        assert normalize_candle(raw) is None

    def test_non_numeric_volume_defaults_to_zero(self):
        """Non-numeric volume is coerced to 0.0, not rejected."""
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, "invalid"]
        result = normalize_candle(raw)
        assert result is not None
        assert result["volume"] == 0.0

    def test_none_volume_defaults_to_zero(self):
        """None volume is coerced to 0.0."""
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, None]
        result = normalize_candle(raw)
        assert result is not None
        assert result["volume"] == 0.0

    def test_tuple_input_works(self):
        """Tuples are accepted, not just lists."""
        raw = ("2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000)
        result = normalize_candle(raw)
        assert result is not None
        assert result["open"] == 100.0

    def test_7_element_array_ok(self):
        """Array with open_interest (7 elements) is accepted."""
        raw = ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000, 1234]
        result = normalize_candle(raw)
        assert result is not None

    def test_no_lot_size_inference(self):
        """The output must never contain lot_size or minimum_lot fields."""
        result = normalize_candle(self.SAMPLE_RAW)
        assert "lot_size" not in result
        assert "minimum_lot" not in result


# ===================================================================
# normalize_candles (batch)
# ===================================================================


class TestNormalizeCandles:
    """Batch wrapper — filters out invalid candles."""

    def test_all_valid(self):
        raw = [
            ["2026-08-22T15:24:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000],
            ["2026-08-22T15:27:00+05:30", 102.0, 108.0, 100.0, 106.0, 6000],
        ]
        result = normalize_candles(raw)
        assert len(result) == 2
        # Phase 7.24.4: timestamps are naive IST, no Z suffix
        assert result[0]["openTime"] == "2026-08-22T15:24:00"
        assert result[1]["openTime"] == "2026-08-22T15:27:00"

    def test_some_invalid_filtered(self):
        """Invalid candles are silently dropped."""
        raw = [
            ["2026-08-22T15:24:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000],
            ["bad-ts", 100.0, 105.0, 95.0, 102.0, 5000],  # invalid timestamp
            ["2026-08-22T15:27:00+05:30", 102.0, 108.0, 100.0, 106.0, 6000],
        ]
        result = normalize_candles(raw)
        assert len(result) == 2

    def test_empty_input(self):
        assert normalize_candles([]) == []

    def test_all_invalid(self):
        raw = [None, "bad", [1, 2]]
        result = normalize_candles(raw)
        assert result == []

    def test_none_input(self):
        """Passing None should return empty list."""
        result = normalize_candles(None)
        assert result == []

    def test_preserves_order(self):
        """Valid candles maintain their original order."""
        raw = [
            ["2026-08-22T15:27:00+05:30", 102.0, 108.0, 100.0, 106.0, 6000],
            ["2026-08-22T15:24:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000],
        ]
        result = normalize_candles(raw)
        # Phase 7.24.4: timestamps are naive IST, no Z suffix
        assert result[0]["openTime"] == "2026-08-22T15:27:00"
        assert result[1]["openTime"] == "2026-08-22T15:24:00"

    def test_symbol_and_interval_propagated(self):
        raw = [
            ["2026-08-22T15:27:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000],
        ]
        result = normalize_candles(raw, symbol="BANKNIFTY", interval="5min")
        assert result[0]["symbol"] == "BANKNIFTY"
        assert result[0]["interval"] == "5min"


# ===================================================================
# extract_candles_from_response
# ===================================================================


class TestExtractCandlesFromResponse:
    """§6.3 — Pull candle array from Upstox V3 response dict."""

    def test_success(self):
        response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }
        candles = extract_candles_from_response(response)
        assert len(candles) == 1
        assert candles[0][0] == "2026-08-22T15:27:00+05:30"

    def test_success_empty_candles(self):
        """Success with empty candle list — not an error."""
        response = {"status": "success", "data": {"candles": []}}
        assert extract_candles_from_response(response) == []

    def test_none_input(self):
        assert extract_candles_from_response(None) == []

    def test_not_a_dict(self):
        assert extract_candles_from_response("string") == []
        assert extract_candles_from_response(42) == []
        assert extract_candles_from_response([]) == []

    def test_error_status(self):
        response = {"status": "error", "errors": [{"message": "bad"}]}
        assert extract_candles_from_response(response) == []

    def test_missing_status(self):
        response = {"data": {"candles": []}}
        assert extract_candles_from_response(response) == []

    def test_data_not_a_dict(self):
        response = {"status": "success", "data": "not a dict"}
        assert extract_candles_from_response(response) == []

    def test_data_missing_candles(self):
        response = {"status": "success", "data": {"other": "field"}}
        assert extract_candles_from_response(response) == []

    def test_candles_not_a_list(self):
        response = {"status": "success", "data": {"candles": "not a list"}}
        assert extract_candles_from_response(response) == []

    def test_multiple_candles(self):
        """Typical response with many candles."""
        candles_data = [
            [f"2026-08-22T{h:02d}:{m:02d}:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000, 0]
            for h in range(9, 16)
            for m in range(0, 60, 3)
        ]
        response = {"status": "success", "data": {"candles": candles_data}}
        result = extract_candles_from_response(response)
        assert len(result) == len(candles_data)

    def test_partial_response_missing_data_key(self):
        """Response with status but no data key."""
        response = {"status": "success"}
        assert extract_candles_from_response(response) == []


# ===================================================================
# End-to-end: extract → normalize
# ===================================================================


class TestEndToEnd:
    """Combine extract + normalize to simulate the full ingestion path."""

    def test_full_pipeline(self):
        """Simulate: Upstox response → extract → normalize → record_candles format."""
        response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T15:24:00+05:30", 25490.0, 25505.0, 25475.0, 25500.0, 12000, 0],
                    ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }

        raw = extract_candles_from_response(response)
        assert len(raw) == 2

        normalized = normalize_candles(raw)
        assert len(normalized) == 2

        # Verify first candle
        c0 = normalized[0]
        assert c0["symbol"] == "NIFTY"
        assert c0["interval"] == "3min"
        assert c0["openTime"] == "2026-08-22T15:24:00"  # 15:24 IST → 15:24 naive IST
        assert c0["open"] == 25490.0
        assert c0["close"] == 25500.0
        assert c0["volume"] == 12000.0

        # Verify second candle
        c1 = normalized[1]
        assert c1["openTime"] == "2026-08-22T15:27:00"  # 15:27 IST → 15:27 naive IST
        assert c1["open"] == 25500.0
        assert c1["close"] == 25510.0

    def test_pipeline_with_invalid_candles(self):
        """Some candles in the batch are invalid — they're filtered out."""
        response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T15:24:00+05:30", 25490.0, 25505.0, 25475.0, 25500.0, 12000, 0],
                    ["bad-ts", None, 25520.0, 25480.0, 25510.0, 15000, 0],  # bad
                    ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }

        raw = extract_candles_from_response(response)
        normalized = normalize_candles(raw)
        assert len(normalized) == 2  # the bad candle is dropped

    def test_error_response_extracts_nothing(self):
        """Error response → empty raw → empty normalized."""
        response = {"status": "error", "errors": [{"message": "rate limited"}]}
        raw = extract_candles_from_response(response)
        assert raw == []
        normalized = normalize_candles(raw)
        assert normalized == []

    def test_timestamp_accuracy_across_ist(self):
        """Verify IST conversion accuracy for edge cases in the pipeline."""
        response = {
            "status": "success",
            "data": {
                "candles": [
                    # Market open: 09:15 IST → 09:15 naive IST
                    ["2026-01-15T09:15:00+05:30", 24000.0, 24010.0, 23990.0, 24005.0, 20000, 0],
                    # Market close: 15:27 IST → 15:27 naive IST
                    ["2026-01-15T15:27:00+05:30", 24100.0, 24120.0, 24080.0, 24110.0, 18000, 0],
                ]
            },
        }

        raw = extract_candles_from_response(response)
        normalized = normalize_candles(raw)

        # Phase 7.24.4: timestamps are naive IST, no Z suffix
        assert normalized[0]["openTime"] == "2026-01-15T09:15:00"
        assert normalized[1]["openTime"] == "2026-01-15T15:27:00"

    def test_lot_size_never_appears_in_output(self):
        """§12.5 — Candle ingestion is independent of NIFTY option lot_size."""
        response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }

        raw = extract_candles_from_response(response)
        normalized = normalize_candles(raw)

        for candle in normalized:
            for forbidden_key in ("lot_size", "minimum_lot", "freeze_quantity", "tick_size"):
                assert forbidden_key not in candle, f"{forbidden_key} must not appear in candle output"
