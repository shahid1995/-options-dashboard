"""Phase 7.9 -- Live verification tool tests (mocked).

Tests the verification tool's logic using mocked Upstox API responses.
The tool itself is designed to be run manually against real APIs; these
tests verify its correctness in a sandbox.

No live API calls are made.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio
import io
import sys

import pytest

from app.tools.live_verification import (
    _sanitize,
    _type_matches,
    generate_report,
    verify_candle_api,
    verify_contract_api,
    verify_db_roundtrip,
    NIFTY_INDEX_KEY,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_CANDLE_RESPONSE = {
    "status": "success",
    "data": {
        "candles": [
            ["2025-08-20T09:15:00+05:30", 25000.0, 25020.0, 24990.0, 25010.0, 15000.0, 0.0],
            ["2025-08-20T09:18:00+05:30", 25010.0, 25030.0, 25005.0, 25025.0, 12000.0, 0.0],
            ["2025-08-20T09:21:00+05:30", 25025.0, 25040.0, 25015.0, 25035.0, 11000.0, 0.0],
        ],
    },
}

MOCK_EXPIRIES_RESPONSE = {
    "status": "success",
    "data": ["2025-04-17", "2025-05-15", "2025-06-19", "2025-07-10"],
}

MOCK_CONTRACTS_RESPONSE = {
    "status": "success",
    "data": [
        {
            "instrument_key": "NSE_FO|47983|17-04-2025",
            "trading_symbol": "NIFTY 20400 PE 17 APR 25",
            "expiry": "2025-04-17",
            "strike_price": 20400.0,
            "instrument_type": "PE",
            "lot_size": 75,
            "minimum_lot": 75,
            "freeze_quantity": 1800,
            "tick_size": 5.0,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_symbol": "NIFTY",
            "segment": "INDICES",
            "exchange": "NSE_FO",
            "weekly": False,
        },
        {
            "instrument_key": "NSE_FO|47982|17-04-2025",
            "trading_symbol": "NIFTY 20400 CE 17 APR 25",
            "expiry": "2025-04-17",
            "strike_price": 20400.0,
            "instrument_type": "CE",
            "lot_size": 75,
            "minimum_lot": 75,
            "freeze_quantity": 1800,
            "tick_size": 5.0,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_symbol": "NIFTY",
            "segment": "INDICES",
            "exchange": "NSE_FO",
            "weekly": False,
        },
    ],
}


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_removes_bearer_token(self):
        text = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456ghi789"
        result = _sanitize(text)
        assert "eyJ" not in result
        assert "[REDACTED" in result

    def test_removes_bare_jwt(self):
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9." + "A" * 30 + "." + "B" * 31
        text = f"Token: {fake_jwt}"
        result = _sanitize(text)
        assert "eyJ" not in result

    def test_preserves_normal_text(self):
        text = "Candle data for NIFTY on 2025-08-20"
        assert _sanitize(text) == text


# ---------------------------------------------------------------------------
# Type matching tests
# ---------------------------------------------------------------------------

class TestTypeMatches:
    def test_str_matches_str(self):
        assert _type_matches("str", "str") is True

    def test_int_matches_number(self):
        assert _type_matches("int", "number") is True

    def test_float_matches_number(self):
        assert _type_matches("float", "number") is True

    def test_int_matches_int(self):
        assert _type_matches("int", "int") is True

    def test_bool_matches_bool(self):
        assert _type_matches("bool", "bool") is True

    def test_str_does_not_match_number(self):
        assert _type_matches("str", "number") is False

    def test_int_does_not_match_str(self):
        assert _type_matches("int", "str") is False


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------

class TestReportGeneration:
    def test_report_contains_all_sections(self):
        results = [
            {"section": "Section A", "status": "success", "key1": "value1"},
            {"section": "Section B", "status": "error", "error": "something failed"},
        ]
        report = generate_report(results)
        assert "Section A" in report
        assert "Section B" in report
        assert "success" in report
        assert "error" in report

    def test_report_no_credentials(self):
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9." + "A" * 30 + "." + "B" * 31
        results = [
            {"section": "Test", "status": "success", "token": f"Bearer {fake_jwt}"},
        ]
        report = generate_report(results)
        assert "eyJ" not in report

    def test_report_shows_pass_when_all_success(self):
        results = [{"section": "A", "status": "success"}]
        report = generate_report(results)
        assert "PASS" in report

    def test_report_shows_issues_when_any_fail(self):
        results = [
            {"section": "A", "status": "success"},
            {"section": "B", "status": "error", "error": "fail"},
        ]
        report = generate_report(results)
        assert "ISSUES FOUND" in report


# ---------------------------------------------------------------------------
# Candle verification tests (mocked)
# ---------------------------------------------------------------------------

class TestVerifyCandleAPI:
    @pytest.mark.asyncio
    async def test_success(self):
        """Basic candle verification passes with ascending mock data."""
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE) as mock_fetch:
            result = await verify_candle_api("test-token", "2025-08-20")

        assert result["status"] == "success"
        assert result["raw_candle_count"] == 3
        assert result["normalized_count"] == 3
        assert result["validation"]["valid"] == 3
        assert result["validation"]["invalid"] == 0
        assert result["api_native_order"] == "ascending"
        assert result["api_order_is_valid"] is True
        assert result["has_duplicates"] is False
        # Verify from_date was passed to the API
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs.get("from_date") == "2025-08-20"

    @pytest.mark.asyncio
    async def test_descending_api_order_accepted(self):
        """Upstox returns candles newest-first. This is valid, not a failure."""
        descending_response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2025-08-20T09:21:00+05:30", 25025.0, 25040.0, 25015.0, 25035.0, 11000.0, 0.0],
                    ["2025-08-20T09:18:00+05:30", 25010.0, 25030.0, 25005.0, 25025.0, 12000.0, 0.0],
                    ["2025-08-20T09:15:00+05:30", 25000.0, 25020.0, 24990.0, 25010.0, 15000.0, 0.0],
                ],
            },
        }
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=descending_response):
            result = await verify_candle_api("test-token", "2025-08-20")

        assert result["status"] == "success"
        assert result["api_native_order"] == "descending"
        assert result["api_order_is_valid"] is True
        # Normalized candles preserve the raw order (normalization does not reorder)
        # The database queries always use .order_by(.asc()), so downstream is always ascending
        assert result["normalized_order"] == "descending"
        assert result["normalized_is_ascending"] is False

    @pytest.mark.asyncio
    async def test_warning_categorization(self):
        """Warnings should be categorized by type with examples."""
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE):
            result = await verify_candle_api("test-token", "2025-08-20")

        validation = result["validation"]
        assert "warning_total" in validation
        assert "warning_counts_by_type" in validation
        assert "warning_examples" in validation
        # Mock data has no warnings (normal candles)
        assert validation["warning_total"] == 0
        assert validation["warning_counts_by_type"] == {}
        assert validation["warning_examples"] == []

    @pytest.mark.asyncio
    async def test_warning_examples_contain_candle_index(self):
        """When warnings exist, examples should include candle_index."""
        abnormal_candles = {
            "status": "success",
            "data": {
                "candles": [
                    ["2025-08-20T09:15:00+05:30", 25000.0, 26000.0, 24000.0, 25000.0, 15000.0, 0.0],
                ],
            },
        }
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=abnormal_candles):
            result = await verify_candle_api("test-token", "2025-08-20")

        validation = result["validation"]
        assert validation["warning_total"] >= 1
        assert "ABNORMAL_RANGE" in validation["warning_counts_by_type"]
        assert len(validation["warning_examples"]) >= 1
        assert "candle_index" in validation["warning_examples"][0]

    @pytest.mark.asyncio
    async def test_timestamp_format(self):
        """Verify timestamp format detection from raw Upstox response."""
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE):
            result = await verify_candle_api("test-token", "2025-08-20")

        assert result["has_plus_0530"] is True
        assert "field_types" in result
        assert result["field_types"]["open"] == "float"

    @pytest.mark.asyncio
    async def test_from_date_always_passed(self):
        """Verify that from_date is always passed to prevent 1-month fetch."""
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE) as mock_fetch:
            await verify_candle_api("test-token", "2025-08-20")

        call_kwargs = mock_fetch.call_args
        assert "from_date" in call_kwargs.kwargs
        assert call_kwargs.kwargs["from_date"] == "2025-08-20"
        assert call_kwargs.kwargs["to_date"] == "2025-08-20"

    @pytest.mark.asyncio
    async def test_upstox_error(self):
        from app.services.upstox import UpstoxError
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, side_effect=UpstoxError(401, "Unauthorized")):
            result = await verify_candle_api("test-token", "2025-08-20")

        assert result["status"] == "error"
        assert "401" in result["http_status"]

    @pytest.mark.asyncio
    async def test_dry_run(self):
        result = await verify_candle_api("test-token", "2025-08-20", dry_run=True)
        assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Contract verification tests (mocked)
# ---------------------------------------------------------------------------

class TestVerifyContractAPI:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
             patch("app.tools.live_verification.get_expired_option_contracts",
                    new_callable=AsyncMock, return_value=MOCK_CONTRACTS_RESPONSE):
            result = await verify_contract_api("test-token", "2025-04-17")

        assert result["status"] == "success"
        assert result["contract_count"] == 2
        assert result["ce_count"] == 1
        assert result["pe_count"] == 1
        assert 75 in result["unique_lot_sizes"]

    @pytest.mark.asyncio
    async def test_field_verification(self):
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
             patch("app.tools.live_verification.get_expired_option_contracts",
                    new_callable=AsyncMock, return_value=MOCK_CONTRACTS_RESPONSE):
            result = await verify_contract_api("test-token", "2025-04-17")

        fv = result["field_verification"]
        assert fv["instrument_key"]["present"] is True
        assert fv["lot_size"]["present"] is True
        assert fv["lot_size"]["example_value"] == 75
        assert fv["minimum_lot"]["present"] is True
        assert fv["freeze_quantity"]["present"] is True
        # freeze_quantity is now expected as "number" (accepts int or float)
        assert fv["freeze_quantity"]["matches_expected_type"] is True
        assert fv["tick_size"]["present"] is True
        assert fv["weekly"]["present"] is True

    @pytest.mark.asyncio
    async def test_freeze_quantity_float_accepted(self):
        """Upstox API may return freeze_quantity as float. Should still match 'number'."""
        float_contracts = {
            "status": "success",
            "data": [
                {
                    "instrument_key": "NSE_FO|47983|17-04-2025",
                    "trading_symbol": "NIFTY 20400 PE 17 APR 25",
                    "expiry": "2025-04-17",
                    "strike_price": 20400.0,
                    "instrument_type": "PE",
                    "lot_size": 75,
                    "minimum_lot": 75,
                    "freeze_quantity": 1800.0,  # float from real Upstox API
                    "tick_size": 5.0,
                    "underlying_key": "NSE_INDEX|Nifty 50",
                    "underlying_symbol": "NIFTY",
                    "segment": "INDICES",
                    "exchange": "NSE_FO",
                    "weekly": False,
                },
            ],
        }
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
             patch("app.tools.live_verification.get_expired_option_contracts",
                    new_callable=AsyncMock, return_value=float_contracts):
            result = await verify_contract_api("test-token", "2025-04-17")

        fv = result["field_verification"]
        assert fv["freeze_quantity"]["actual_type"] == "float"
        assert fv["freeze_quantity"]["matches_expected_type"] is True  # "number" accepts float

    @pytest.mark.asyncio
    async def test_lot_size_note_when_single_lot_size(self):
        """When only one lot_size is found, a context note should be provided."""
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
             patch("app.tools.live_verification.get_expired_option_contracts",
                    new_callable=AsyncMock, return_value=MOCK_CONTRACTS_RESPONSE):
            result = await verify_contract_api("test-token", "2025-04-17")

        assert "lot_size_note" in result
        assert isinstance(result["lot_size_note"], str)
        assert len(result["lot_size_note"]) > 0

    @pytest.mark.asyncio
    async def test_expiry_not_found_uses_fallback(self):
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
             patch("app.tools.live_verification.get_expired_option_contracts",
                    new_callable=AsyncMock, return_value=MOCK_CONTRACTS_RESPONSE):
            result = await verify_contract_api("test-token", "2025-99-99")

        assert result["requested_expiry_not_found"] is True
        assert result["used_expiry"] == "2025-07-10"

    @pytest.mark.asyncio
    async def test_upstox_error_403(self):
        from app.services.upstox import UpstoxError
        with patch("app.tools.live_verification.get_expired_expiries",
                    new_callable=AsyncMock, side_effect=UpstoxError(403, "Plus plan required")):
            result = await verify_contract_api("test-token", "2025-04-17")

        assert result["status"] == "error"
        assert "403" in result["http_status"]

    @pytest.mark.asyncio
    async def test_dry_run(self):
        result = await verify_contract_api("test-token", "2025-04-17", dry_run=True)
        assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Database round-trip tests (mocked)
# ---------------------------------------------------------------------------

class TestVerifyDbRoundtrip:
    @pytest.mark.asyncio
    async def test_candle_roundtrip(self):
        with patch("app.tools.live_verification.get_historical_candles",
                    new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE) as mock_fetch:
            result = await verify_db_roundtrip("test-token", "2025-08-20")

        assert result["status"] == "success"
        assert result["round_trip_candles"] == 3
        assert result["round_trip_contracts"] == 3
        assert result["immutability_verified"] is True
        assert result["openTime_has_z"] is True
        # Verify from_date was passed
        call_kwargs = mock_fetch.call_args
        assert call_kwargs.kwargs.get("from_date") == "2025-08-20"

    @pytest.mark.asyncio
    async def test_dry_run(self):
        result = await verify_db_roundtrip("test-token", "2025-08-20", dry_run=True)
        assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Windows encoding regression tests
# ---------------------------------------------------------------------------

class TestWindowsEncoding:
    """Verify that verification output is ASCII-safe for Windows cp1252 consoles."""

    def test_no_unicode_in_print_statements(self):
        """All print() calls must use only ASCII characters."""
        import ast
        with open("app/tools/live_verification.py", "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        problems = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    for arg in node.args:
                        if isinstance(arg, ast.JoinedStr):
                            for value in arg.values:
                                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                                    for ch in value.value:
                                        if ord(ch) > 127:
                                            problems.append(f"Line {node.lineno}: U+{ord(ch):04X}")
                        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            for ch in arg.value:
                                if ord(ch) > 127:
                                    problems.append(f"Line {node.lineno}: U+{ord(ch):04X}")

        assert not problems, f"Unicode in print statements: {problems}"

    def test_generate_report_ascii_safe(self):
        """Report generation must produce cp1252-encodable output."""
        results = [
            {"section": "Test", "status": "success", "key": "value"},
            {"section": "Test2", "status": "error", "error": "fail"},
        ]
        report = generate_report(results)
        report.encode("cp1252")  # Must not raise

    def test_generate_report_no_unicode_symbols(self):
        """Report must not contain checkmark/cross symbols."""
        results = [
            {"section": "A", "status": "success"},
            {"section": "B", "status": "error"},
        ]
        report = generate_report(results)
        assert "\u2705" not in report  # no green checkmark
        assert "\u274C" not in report  # no red cross
        assert "\u2713" not in report  # no checkmark
        assert "\u2717" not in report  # no cross

    @pytest.mark.asyncio
    async def test_candle_verify_output_cp1252_safe(self):
        """Candle verification stdout must be cp1252-safe."""
        old_stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        try:
            with patch("app.tools.live_verification.get_historical_candles",
                        new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE):
                await verify_candle_api("test-token", "2025-08-20")
        except UnicodeEncodeError as e:
            pytest.fail(f"Candle verify output not cp1252 safe: {e}")
        finally:
            sys.stdout = old_stdout

    @pytest.mark.asyncio
    async def test_contract_verify_output_cp1252_safe(self):
        """Contract verification stdout must be cp1252-safe."""
        old_stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        try:
            with patch("app.tools.live_verification.get_expired_expiries",
                        new_callable=AsyncMock, return_value=MOCK_EXPIRIES_RESPONSE), \
                 patch("app.tools.live_verification.get_expired_option_contracts",
                        new_callable=AsyncMock, return_value=MOCK_CONTRACTS_RESPONSE):
                await verify_contract_api("test-token", "2025-04-17")
        except UnicodeEncodeError as e:
            pytest.fail(f"Contract verify output not cp1252 safe: {e}")
        finally:
            sys.stdout = old_stdout

    @pytest.mark.asyncio
    async def test_roundtrip_verify_output_cp1252_safe(self):
        """Round-trip verification stdout must be cp1252-safe."""
        old_stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        try:
            with patch("app.tools.live_verification.get_historical_candles",
                        new_callable=AsyncMock, return_value=MOCK_CANDLE_RESPONSE):
                await verify_db_roundtrip("test-token", "2025-08-20")
        except UnicodeEncodeError as e:
            pytest.fail(f"Round-trip verify output not cp1252 safe: {e}")
        finally:
            sys.stdout = old_stdout
