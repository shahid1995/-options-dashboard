"""Phase 7.8C — Candle validation / quality tests.

Exercises the full validation pipeline:

* ``validate_candle``        — single-candle hard errors + soft warnings
* ``validate_candle_batch``  — batch validation with gap/duplicate detection
* ``_detect_time_gaps``      — gap detection + market-session classification
* ``_is_market_session``     — IST 9:15–15:30 classification
* ``check_chronological_order`` — ordering verification

Follows existing ``test_upstox.py`` conventions.  No live API calls.
"""

from datetime import datetime, timezone

import pytest

from app.services.candle_validation import (
    GapInfo,
    CandleValidationResult,
    check_chronological_order,
    validate_candle,
    validate_candle_batch,
    _detect_time_gaps,
    _is_market_session,
    _compute_expected_per_day,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candle(**overrides) -> dict:
    """Build a valid normalized candle dict with sensible defaults."""
    base = {
        "symbol": "NIFTY",
        "interval": "3min",
        "openTime": "2026-08-22T09:57:00Z",
        "open": 25500.0,
        "high": 25520.0,
        "low": 25480.0,
        "close": 25510.0,
        "volume": 15000.0,
    }
    base.update(overrides)
    return base


def _market_candle(hour: int, minute: int, day: int = 22, **overrides) -> dict:
    """Build a candle at a specific IST time, converted to UTC openTime."""
    # IST → UTC: subtract 5h30m
    utc_hour = hour - 5
    utc_minute = minute - 30
    if utc_minute < 0:
        utc_minute += 60
        utc_hour -= 1
    if utc_hour < 0:
        utc_hour += 24
    ts = f"2026-08-{day:02d}T{utc_hour:02d}:{utc_minute:02d}:00Z"
    return _candle(openTime=ts, **overrides)


def _consecutive_candles(
    count: int = 5,
    interval_minutes: int = 3,
    start_ist_hour: int = 9,
    start_ist_minute: int = 15,
    day: int = 22,
) -> list[dict]:
    """Build a sequence of consecutive candles at the given interval."""
    candles = []
    total_minutes = start_ist_hour * 60 + start_ist_minute
    for i in range(count):
        h = (total_minutes + i * interval_minutes) // 60
        m = (total_minutes + i * interval_minutes) % 60
        candles.append(_market_candle(h, m, day=day))
    return candles


# ===================================================================
# validate_candle — Hard Errors
# ===================================================================


class TestValidateCandleHardErrors:
    """§9.1 — Hard errors → candle rejected (not persisted)."""

    def test_valid_candle_passes(self):
        r = validate_candle(_candle(), 0)
        assert r.is_valid is True
        assert r.errors == []

    # --- PRICE_NOT_POSITIVE ---

    def test_open_zero(self):
        r = validate_candle(_candle(open=0), 0)
        assert r.is_valid is False
        assert any("PRICE_NOT_POSITIVE" in e and "open" in e for e in r.errors)

    def test_open_negative(self):
        r = validate_candle(_candle(open=-100), 0)
        assert r.is_valid is False

    def test_high_zero(self):
        r = validate_candle(_candle(high=0), 0)
        assert r.is_valid is False

    def test_low_none(self):
        r = validate_candle(_candle(low=None), 0)
        assert r.is_valid is False
        assert any("PRICE_NOT_POSITIVE" in e and "low=None" in e for e in r.errors)

    def test_close_non_numeric(self):
        r = validate_candle(_candle(close="abc"), 0)
        assert r.is_valid is False

    def test_open_none(self):
        r = validate_candle(_candle(open=None), 0)
        assert r.is_valid is False

    # --- OHLC_INTEGRITY ---

    def test_high_less_than_open(self):
        r = validate_candle(_candle(high=25400), 0)  # high < open=25500
        assert r.is_valid is False
        assert any("OHLC_INTEGRITY" in e for e in r.errors)

    def test_high_less_than_close(self):
        r = validate_candle(_candle(high=25400, close=25500), 0)
        assert r.is_valid is False

    def test_low_greater_than_open(self):
        r = validate_candle(_candle(low=25600), 0)  # low > open=25500
        assert r.is_valid is False

    def test_low_greater_than_close(self):
        r = validate_candle(_candle(low=25600, close=25500), 0)
        assert r.is_valid is False

    def test_high_less_than_low(self):
        r = validate_candle(_candle(high=25400, low=25600), 0)
        assert r.is_valid is False

    def test_high_equals_low_is_valid(self):
        """High == low == open == close is a doji — valid."""
        r = validate_candle(_candle(open=25500, high=25500, low=25500, close=25500), 0)
        assert r.is_valid is True

    # --- NEGATIVE_VOLUME ---

    def test_negative_volume(self):
        r = validate_candle(_candle(volume=-100), 0)
        assert r.is_valid is False
        assert any("NEGATIVE_VOLUME" in e for e in r.errors)

    def test_zero_volume_is_not_hard_error(self):
        """Zero volume is a soft warning, not a hard error."""
        r = validate_candle(_candle(volume=0), 0)
        assert r.is_valid is True

    # --- TIMESTAMP_MISSING ---

    def test_none_timestamp(self):
        r = validate_candle(_candle(openTime=None), 0)
        assert r.is_valid is False
        assert any("TIMESTAMP_MISSING" in e for e in r.errors)

    def test_missing_timestamp_key(self):
        c = _candle()
        del c["openTime"]
        r = validate_candle(c, 0)
        assert r.is_valid is False

    # --- Multiple hard errors ---

    def test_multiple_errors(self):
        r = validate_candle(_candle(open=0, high=0, low=None, close=-1), 0)
        assert r.is_valid is False
        assert len(r.errors) >= 3  # at least 3 PRICE_NOT_POSITIVE errors


# ===================================================================
# validate_candle — Soft Warnings
# ===================================================================


class TestValidateCandleSoftWarnings:
    """§9.1 — Soft warnings → candle stored but flagged."""

    def test_zero_volume_warning(self):
        r = validate_candle(_candle(volume=0), 0)
        assert r.is_valid is True
        assert any("ZERO_VOLUME" in w for w in r.warnings)

    def test_normal_volume_no_warning(self):
        r = validate_candle(_candle(volume=15000), 0)
        assert r.is_valid is True
        assert not any("ZERO_VOLUME" in w for w in r.warnings)

    def test_abnormal_range_warning(self):
        """Range (high - low) / close > 2% → ABNORMAL_RANGE."""
        # open=close=25000, high=25300, low=24700 → range=600/25000=2.4% > 2%
        r = validate_candle(_candle(open=25000, high=25300, low=24700, close=25000), 0)
        assert r.is_valid is True
        assert any("ABNORMAL_RANGE" in w for w in r.warnings)

    def test_normal_range_no_warning(self):
        """Range = 40/25510 ≈ 0.16% → no warning."""
        r = validate_candle(_candle(high=25520, low=25480, close=25510), 0)
        assert r.is_valid is True
        assert not any("ABNORMAL_RANGE" in w for w in r.warnings)

    def test_exactly_2pct_range_no_warning(self):
        """Range = exactly 2% → not > 2% → no warning."""
        # close=100, high=101, low=99 → range=2/100=2.0%
        r = validate_candle(_candle(high=101, low=99, close=100, open=100), 0)
        assert r.is_valid is True
        assert not any("ABNORMAL_RANGE" in w for w in r.warnings)

    def test_soft_warnings_not_generated_for_invalid_candles(self):
        """Hard errors take precedence — no soft warnings for invalid candles."""
        r = validate_candle(_candle(volume=0, open=0), 0)
        assert r.is_valid is False
        assert r.warnings == []  # no ZERO_VOLUME warning when PRICE_NOT_POSITIVE


# ===================================================================
# validate_candle_batch
# ===================================================================


class TestValidateCandleBatch:
    """§9.3 — Batch validation with gap detection and statistics."""

    def test_all_valid(self):
        candles = _consecutive_candles(5)
        report = validate_candle_batch(candles)
        assert report["total"] == 5
        assert report["valid"] == 5
        assert report["invalid"] == 0
        assert report["errors"] == []

    def test_some_invalid(self):
        candles = _consecutive_candles(3)
        candles[1] = _candle(open=0)  # invalid
        report = validate_candle_batch(candles)
        assert report["total"] == 3
        assert report["valid"] == 2
        assert report["invalid"] == 1
        assert report["errors"][0].candle_index == 1

    def test_empty_batch(self):
        report = validate_candle_batch([])
        assert report["total"] == 0
        assert report["valid"] == 0
        assert report["statistics"]["total_candles"] == 0

    def test_statistics_computed(self):
        candles = _consecutive_candles(10)
        report = validate_candle_batch(candles)
        stats = report["statistics"]
        assert stats["total_candles"] == 10
        assert stats["expected_candles_per_day"] == 125
        assert "earliest_candle" in stats
        assert "latest_candle" in stats

    def test_warnings_collected(self):
        """Soft warnings from valid candles are collected."""
        candles = _consecutive_candles(3)
        candles[0] = _candle(volume=0)  # ZERO_VOLUME warning
        report = validate_candle_batch(candles)
        assert len(report["warnings"]) == 1
        assert any("ZERO_VOLUME" in w.warnings[0] for w in report["warnings"])


# ===================================================================
# Duplicate detection
# ===================================================================


class TestDuplicateDetection:
    """§9.5 — Duplicate openTime values detected."""

    def test_no_duplicates(self):
        candles = _consecutive_candles(5)
        report = validate_candle_batch(candles)
        assert report["duplicates"] == []

    def test_duplicate_detected(self):
        candles = _consecutive_candles(3)
        candles.append(_candle(openTime=candles[0]["openTime"]))  # duplicate
        report = validate_candle_batch(candles)
        assert 3 in report["duplicates"]  # index of the duplicate

    def test_multiple_duplicates(self):
        candles = _consecutive_candles(2)
        candles.append(_candle(openTime=candles[0]["openTime"]))
        candles.append(_candle(openTime=candles[1]["openTime"]))
        report = validate_candle_batch(candles)
        assert len(report["duplicates"]) == 2


# ===================================================================
# Gap detection
# ===================================================================


class TestGapDetection:
    """§9.4 — Gap detection with market-session classification."""

    def test_no_gaps_consecutive(self):
        candles = _consecutive_candles(10)
        report = validate_candle_batch(candles)
        assert report["gaps"] == []

    def test_gap_detected(self):
        """Missing 1 candle between two consecutive candles."""
        candles = _consecutive_candles(3)  # 09:15, 09:18, 09:21
        # Add a candle at 09:30 (gap of 2 missing candles: 09:24, 09:27)
        candles.append(_market_candle(9, 30))
        report = validate_candle_batch(candles)
        assert len(report["gaps"]) == 1
        gap = report["gaps"][0]
        assert gap.missing_count == 2
        assert gap.is_market_session is True

    def test_gap_at_boundary(self):
        """Gap crossing from market to non-market session."""
        candles = _consecutive_candles(3, start_ist_hour=9, start_ist_minute=15)
        # Next candle is next day (big gap)
        candles.append(_market_candle(9, 15, day=23))
        report = validate_candle_batch(candles)
        assert len(report["gaps"]) == 1
        # Gap spans overnight — classified as non-market (starts at 09:21)
        gap = report["gaps"][0]
        assert gap.missing_count > 0

    def test_single_candle_no_gaps(self):
        candles = _consecutive_candles(1)
        report = validate_candle_batch(candles)
        assert report["gaps"] == []

    def test_two_candles_no_gap(self):
        candles = _consecutive_candles(2)
        report = validate_candle_batch(candles)
        assert report["gaps"] == []


# ===================================================================
# Market-session classification
# ===================================================================


class TestMarketSession:
    """§9.7 — IST 9:15–15:30 classification."""

    def test_market_open(self):
        """09:15 IST = 03:45 UTC → in market session."""
        dt = datetime(2026, 8, 22, 3, 45, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is True

    def test_market_close(self):
        """15:30 IST = 10:00 UTC → in market session."""
        dt = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is True

    def test_before_market(self):
        """09:14 IST = 03:44 UTC → not in market session."""
        dt = datetime(2026, 8, 22, 3, 44, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is False

    def test_after_market(self):
        """15:31 IST = 10:01 UTC → not in market session."""
        dt = datetime(2026, 8, 22, 10, 1, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is False

    def test_midday(self):
        """12:00 IST = 06:30 UTC → in market session."""
        dt = datetime(2026, 8, 22, 6, 30, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is True

    def test_midnight(self):
        """00:00 IST = 18:30 UTC (prev day) → not in market session."""
        dt = datetime(2026, 8, 21, 18, 30, 0, tzinfo=timezone.utc)
        assert _is_market_session(dt) is False


# ===================================================================
# Chronological ordering
# ===================================================================


class TestChronologicalOrdering:
    """Verify out-of-order detection."""

    def test_ordered(self):
        candles = _consecutive_candles(5)
        assert check_chronological_order(candles) == []

    def test_one_out_of_order(self):
        candles = _consecutive_candles(3)
        # Swap candles 1 and 2
        candles[1], candles[2] = candles[2], candles[1]
        result = check_chronological_order(candles)
        assert 2 in result

    def test_empty_list(self):
        assert check_chronological_order([]) == []


# ===================================================================
# Expected candles per day
# ===================================================================


class TestExpectedPerDay:
    def test_3min(self):
        assert _compute_expected_per_day(3) == 125

    def test_5min(self):
        assert _compute_expected_per_day(5) == 75

    def test_1min(self):
        assert _compute_expected_per_day(1) == 375


# ===================================================================
# Integration: validation + batch together
# ===================================================================


class TestIntegration:
    """End-to-end validation scenarios."""

    def test_full_valid_batch(self):
        """10 consecutive market candles — all valid, no gaps."""
        candles = _consecutive_candles(10)
        report = validate_candle_batch(candles)
        assert report["total"] == 10
        assert report["valid"] == 10
        assert report["invalid"] == 0
        assert report["gaps"] == []
        assert report["duplicates"] == []

    def test_mixed_valid_invalid_with_gaps(self):
        """Some valid, some invalid, with a gap."""
        candles = _consecutive_candles(5)
        candles[2] = _candle(open=0)  # invalid
        # Insert a gap after candle 3 (09:21 → 09:30 = gap of 2 missing)
        candles.insert(4, _market_candle(9, 30))
        report = validate_candle_batch(candles)
        assert report["total"] == 6
        assert report["invalid"] == 1
        assert len(report["gaps"]) >= 1  # at least one gap detected

    def test_lot_size_not_in_candle_output(self):
        """§12.5 — Validation never touches lot_size."""
        c = _candle()
        r = validate_candle(c, 0)
        # The validation result should never mention lot_size
        for err in r.errors:
            assert "lot_size" not in err
        for warn in r.warnings:
            assert "lot_size" not in warn

    def test_volume_not_converted_to_lots(self):
        """Volume stays as raw float — never divided by lot_size."""
        c = _candle(volume=15000)
        r = validate_candle(c, 0)
        assert r.is_valid is True
        # Volume 15000 is valid (not zero, not negative)
        assert not any("VOLUME" in w for w in r.warnings)

    def test_batch_report_has_all_expected_keys(self):
        candles = _consecutive_candles(3)
        report = validate_candle_batch(candles)
        for key in ("total", "valid", "invalid", "errors", "warnings",
                     "gaps", "duplicates", "statistics"):
            assert key in report
