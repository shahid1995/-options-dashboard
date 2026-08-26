"""Candle validation — Phase 7.8C (Validation & Quality).

Validates normalized candle dicts produced by ``candle_ingestion.py``
**before** they are persisted by ``nifty_candles.record_candles()``.

Design constraints (§9 / §12.5):
  - Hard errors → candle rejected (not persisted).
  - Soft warnings → candle stored but flagged in the report.
  - Volume and OI are **never** converted into lots/contracts.
  - Candle validation is completely independent of NIFTY option lot_size.
  - Historical lot_size is never inferred, applied, or referenced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
"""Indian Standard Time (UTC+5:30)."""

# NSE trading hours (IST)
MARKET_OPEN_MINUTE = 555   # 9:15 = 9*60+15
MARKET_CLOSE_MINUTE = 930  # 15:30 = 15*60+30

# Boundary alignment tolerance (minutes)
# First candle should be near 09:15 IST; last candle near 15:27 IST.
BOUNDARY_TOLERANCE_MINUTES = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CandleValidationResult:
    """Result of validating one candle."""
    candle_index: int
    is_valid: bool = True  # False if any hard error
    errors: list[str] = field(default_factory=list)   # hard errors → candle rejected
    warnings: list[str] = field(default_factory=list)  # soft warnings → stored but flagged


@dataclass
class GapInfo:
    """A gap (missing candles) in the time series."""
    gap_start: str   # ISO timestamp of candle before gap
    gap_end: str     # ISO timestamp of candle after gap
    expected_candles: int
    missing_count: int
    is_market_session: bool  # True if gap is during market hours


# ---------------------------------------------------------------------------
# Single-candle validation
# ---------------------------------------------------------------------------

def validate_candle(candle: dict, index: int) -> CandleValidationResult:
    """Validate a single normalized candle.

    Hard errors set ``is_valid=False`` → candle is NOT persisted.
    Soft warnings are recorded but do NOT prevent persistence.

    Parameters
    ----------
    candle:
        A dict with keys ``symbol``, ``interval``, ``openTime`` (ISO 8601
        UTC with ``Z``), ``open``, ``high``, ``low``, ``close``, ``volume``.
    index:
        Position of this candle in the batch (for error reporting).

    Returns
    -------
    CandleValidationResult
    """
    result = CandleValidationResult(candle_index=index, is_valid=True)

    open_p = candle.get("open")
    high = candle.get("high")
    low = candle.get("low")
    close = candle.get("close")
    volume = candle.get("volume", 0)
    open_time = candle.get("openTime")

    # ---- Hard errors ----

    # PRICE_NOT_POSITIVE: any of open, high, low, close is None, non-numeric, or ≤ 0
    for name, val in (("open", open_p), ("high", high), ("low", low), ("close", close)):
        if val is None or not isinstance(val, (int, float)) or val <= 0:
            result.is_valid = False
            result.errors.append(f"PRICE_NOT_POSITIVE: {name}={val}")

    # OHLC_INTEGRITY: only check if all prices are valid numbers
    if result.is_valid and all(
        isinstance(v, (int, float)) for v in (open_p, high, low, close)
    ):
        if high < max(open_p, close):
            result.is_valid = False
            result.errors.append(
                f"OHLC_INTEGRITY: high ({high}) < max(open, close) ({max(open_p, close)})"
            )
        if low > min(open_p, close):
            result.is_valid = False
            result.errors.append(
                f"OHLC_INTEGRITY: low ({low}) > min(open, close) ({min(open_p, close)})"
            )
        if high < low:
            result.is_valid = False
            result.errors.append(
                f"OHLC_INTEGRITY: high ({high}) < low ({low})"
            )

    # NEGATIVE_VOLUME
    if volume is not None and isinstance(volume, (int, float)) and volume < 0:
        result.is_valid = False
        result.errors.append(f"NEGATIVE_VOLUME: volume={volume}")

    # TIMESTAMP_MISSING
    if open_time is None:
        result.is_valid = False
        result.errors.append("TIMESTAMP_MISSING: openTime is None")

    # ---- Soft warnings (only if hard-error-free) ----

    if result.is_valid:
        # ZERO_VOLUME
        if volume is not None and isinstance(volume, (int, float)) and volume == 0:
            result.warnings.append("ZERO_VOLUME: volume is 0")

        # ABNORMAL_RANGE: (high − low) / close > 2%
        if (
            isinstance(close, (int, float)) and close > 0
            and isinstance(high, (int, float))
            and isinstance(low, (int, float))
        ):
            candle_range_pct = (high - low) / close
            if candle_range_pct > 0.02:
                result.warnings.append(
                    f"ABNORMAL_RANGE: range is {candle_range_pct:.1%} of close"
                )

    return result


# ---------------------------------------------------------------------------
# Batch validation with gap detection
# ---------------------------------------------------------------------------

def validate_candle_batch(
    candles: list[dict],
    expected_interval_minutes: int = 3,
) -> dict:
    """Validate a batch of candles and detect gaps.

    Parameters
    ----------
    candles:
        List of normalized candle dicts (from ``normalize_candles()``).
    expected_interval_minutes:
        Expected interval between consecutive candles (default 3 minutes).

    Returns
    -------
    dict
        ``total``, ``valid``, ``invalid``, ``errors`` (list of
        CandleValidationResult for invalid candles), ``gaps`` (list of
        GapInfo), ``duplicates`` (indices of duplicate openTime values),
        ``statistics`` (earliest/latest candle, gap count, etc.).
    """
    # 1. Validate individual candles
    results = [validate_candle(c, i) for i, c in enumerate(candles)]
    valid_candles = [c for c, r in zip(candles, results) if r.is_valid]
    invalid = [r for r in results if not r.is_valid]

    # 2. Detect duplicate timestamps (on valid candles only)
    seen_times: dict[str, int] = {}
    duplicates: list[int] = []
    for i, c in enumerate(valid_candles):
        t = c.get("openTime")
        if t in seen_times:
            duplicates.append(i)
        else:
            seen_times[t] = i

    # 3. Detect gaps
    gaps = _detect_time_gaps(valid_candles, expected_interval_minutes)

    # 4. Collect soft warnings from valid candles
    all_warnings: list[CandleValidationResult] = [
        r for r in results if r.is_valid and r.warnings
    ]

    # 5. Compute statistics
    if valid_candles:
        times = [c["openTime"] for c in valid_candles]
        statistics = {
            "earliest_candle": min(times),
            "latest_candle": max(times),
            "total_candles": len(valid_candles),
            "expected_candles_per_day": _compute_expected_per_day(expected_interval_minutes),
            "gap_count": len(gaps),
            "total_gap_candles": sum(g.missing_count for g in gaps),
        }
    else:
        statistics = {
            "total_candles": 0,
            "gap_count": 0,
            "total_gap_candles": 0,
        }

    return {
        "total": len(candles),
        "valid": len(valid_candles),
        "invalid": len(invalid),
        "errors": invalid,
        "warnings": all_warnings,
        "gaps": gaps,
        "duplicates": duplicates,
        "statistics": statistics,
    }


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def _detect_time_gaps(
    candles: list[dict],
    interval_minutes: int = 3,
) -> list[GapInfo]:
    """Detect gaps in the candle time series.

    A gap exists when consecutive candles are more than ``interval_minutes``
    apart.  We distinguish:

    - **Market-session gaps**: during IST 9:15–15:30 (indicates missing data)
    - **Non-market gaps**: during off-hours/weekends/holidays (expected)
    """
    gaps: list[GapInfo] = []
    if len(candles) < 2:
        return gaps

    expected_delta_ms = interval_minutes * 60 * 1000

    for i in range(len(candles) - 1):
        t1 = candles[i].get("openTime")
        t2 = candles[i + 1].get("openTime")

        if not t1 or not t2:
            continue

        try:
            dt1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        delta_ms = (dt2 - dt1).total_seconds() * 1000
        expected_multiple = delta_ms / expected_delta_ms

        # Allow small tolerance: >1.5× expected = gap of 1+ candles
        if expected_multiple > 1.5:
            missing = max(0, round(delta_ms / expected_delta_ms) - 1)
            is_market = _is_market_session(dt1)

            gaps.append(GapInfo(
                gap_start=t1,
                gap_end=t2,
                expected_candles=missing + 1,
                missing_count=missing,
                is_market_session=is_market,
            ))

    return gaps


# ---------------------------------------------------------------------------
# Market-session classification
# ---------------------------------------------------------------------------

def _is_market_session(dt: datetime) -> bool:
    """Check if a timestamp falls within NSE trading hours (IST 9:15–15:30).

    Phase 7.24.4: Accepts naive IST datetimes directly.
    This is approximate — does not account for market holidays.
    Used for gap classification, not data validation.
    """
    if dt.tzinfo is not None:
        # Convert aware datetime to naive IST
        dt = dt.astimezone(IST).replace(tzinfo=None)
    time_min = dt.hour * 60 + dt.minute
    return MARKET_OPEN_MINUTE <= time_min <= MARKET_CLOSE_MINUTE


# ---------------------------------------------------------------------------
# Expected candles per day
# ---------------------------------------------------------------------------

def _compute_expected_per_day(interval_minutes: int) -> int:
    """Compute expected number of candles per full trading day.

    NSE F&O: 9:15 to 15:30 IST = 375 minutes.
    375 / interval_minutes = expected candles.
    """
    trading_minutes = MARKET_CLOSE_MINUTE - MARKET_OPEN_MINUTE  # 375
    return trading_minutes // interval_minutes


# ---------------------------------------------------------------------------
# Chronological ordering check
# ---------------------------------------------------------------------------

def check_chronological_order(candles: list[dict]) -> list[int]:
    """Return indices where candles are out of chronological order.

    Returns a list of indices ``i`` where ``candles[i].openTime < candles[i-1].openTime``.
    Empty list means correctly ordered.
    """
    out_of_order: list[int] = []
    for i in range(1, len(candles)):
        t_prev = candles[i - 1].get("openTime", "")
        t_curr = candles[i].get("openTime", "")
        if t_curr and t_prev and t_curr < t_prev:
            out_of_order.append(i)
    return out_of_order
