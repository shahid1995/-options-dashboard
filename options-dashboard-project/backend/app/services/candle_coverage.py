"""Candle coverage & quality audit — Phase 7.8E.

Generates comprehensive coverage reports for stored NIFTY candle data.
Distinguishes expected closed days (weekends/holidays) from genuine
data-quality problems (missing trading-day data).

Design constraints (§11 / §12.5):
  - Coverage is completely independent of NIFTY option lot_size.
  - Historical lot_size is never inferred, applied, or referenced here.
  - Candle data is pure OHLCV — no lot-size-dependent fields.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import NiftyCandle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# NSE trading session (IST)
MARKET_OPEN_MINUTE_IST = 9 * 60 + 15   # 09:15
MARKET_CLOSE_MINUTE_IST = 15 * 60 + 30  # 15:30
EXPECTED_CANDLES_PER_DAY = 125           # 375 min / 3 min

# Research readiness thresholds (§11.2)
MIN_OBSERVATIONS = 200
MIN_VALIDATION = 500
MIN_ROBUST = 3000

# Known NSE holidays (2024–2026) — approximate, not exhaustive.
# Used for classification, not validation.
KNOWN_HOLIDAYS: set[date] = {
    # 2024
    date(2024, 1, 26), date(2024, 3, 25), date(2024, 3, 29),
    date(2024, 4, 11), date(2024, 4, 17), date(2024, 5, 1),
    date(2024, 6, 17), date(2024, 7, 17), date(2024, 8, 15),
    date(2024, 10, 2), date(2024, 11, 1), date(2024, 11, 15),
    date(2024, 12, 25),
    # 2025
    date(2025, 1, 26), date(2025, 3, 14), date(2025, 3, 31),
    date(2025, 4, 10), date(2025, 4, 14), date(2025, 5, 1),
    date(2025, 6, 27), date(2025, 8, 15), date(2025, 10, 2),
    date(2025, 10, 21), date(2025, 11, 5), date(2025, 12, 25),
    # 2026
    date(2026, 1, 26), date(2026, 3, 20), date(2026, 4, 2),
    date(2026, 4, 14), date(2026, 5, 1), date(2026, 6, 19),
    date(2026, 8, 15), date(2026, 10, 2), date(2026, 10, 20),
    date(2026, 11, 6), date(2026, 12, 25),
}


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5  # Mon–Fri


def _is_trading_day(d: date) -> bool:
    """Weekday that is not a known holiday."""
    return _is_weekday(d) and d not in KNOWN_HOLIDAYS


# ---------------------------------------------------------------------------
# Timestamp helpers (Phase 7.24.4: timestamps are naive IST)
# ---------------------------------------------------------------------------


def _utc_to_ist_minute(dt: datetime) -> int:
    """Extract IST minutes-since-midnight from a naive IST datetime.

    Phase 7.24.4: timestamps are stored as naive IST, so this function
    directly extracts the hour/minute without timezone conversion.
    """
    if dt.tzinfo is not None:
        from app.utils.market_time import IST
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt.hour * 60 + dt.minute


def _utc_to_date_ist(dt: datetime) -> date:
    """Extract the IST calendar date from a naive IST datetime.

    Phase 7.24.4: timestamps are stored as naive IST, so this function
    directly returns the date without timezone conversion.
    """
    if dt.tzinfo is not None:
        from app.utils.market_time import IST
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt.date()


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


def generate_coverage_report(
    db: Session,
    symbol: str = "NIFTY",
    interval: str = "3min",
) -> dict[str, Any]:
    """Generate a comprehensive coverage report for stored candle data.

    Returns
    -------
    dict
        Full coverage report with daily coverage, summary statistics,
        gap analysis, and research-readiness assessment.
    """
    symbol = symbol.upper()

    # 1. Fetch all candles for the symbol/interval
    stmt = (
        select(NiftyCandle)
        .where(NiftyCandle.symbol == symbol)
        .where(NiftyCandle.interval == interval)
        .order_by(NiftyCandle.open_time.asc())
    )
    rows = list(db.scalars(stmt))

    if not rows:
        return _empty_report(symbol, interval)

    # 2. Build daily coverage
    daily = _build_daily_coverage(rows)

    # 3. Compute summary
    summary = _compute_summary(daily)

    # 4. Detect gaps
    gaps = _detect_gaps(rows, interval)

    # 5. Research readiness
    readiness = _research_readiness(summary)

    return {
        "symbol": symbol,
        "interval": interval,
        "total_candles": len(rows),
        "date_range": {
            "earliest": rows[0].open_time.isoformat() if rows[0].open_time else None,
            "latest": rows[-1].open_time.isoformat() if rows[-1].open_time else None,
            "span_days": (rows[-1].open_time - rows[0].open_time).days if rows[0].open_time and rows[-1].open_time else 0,
        },
        "daily_coverage": daily,
        "summary": summary,
        "gaps": gaps,
        "research_readiness": readiness,
    }


# ---------------------------------------------------------------------------
# Daily coverage builder
# ---------------------------------------------------------------------------


def _build_daily_coverage(rows: list[NiftyCandle]) -> list[dict]:
    """Group candles by IST date and compute per-day coverage."""
    by_day: dict[date, list[NiftyCandle]] = defaultdict(list)
    for row in rows:
        if row.open_time:
            day = _utc_to_date_ist(row.open_time)
            by_day[day].append(row)

    result = []
    for day in sorted(by_day.keys()):
        candles = by_day[day]
        count = len(candles)

        # First/last candle timestamps (UTC)
        first_ts = candles[0].open_time.isoformat() if candles[0].open_time else None
        last_ts = candles[-1].open_time.isoformat() if candles[-1].open_time else None

        completeness = min(100.0, (count / EXPECTED_CANDLES_PER_DAY) * 100)

        result.append({
            "date": day.isoformat(),
            "candle_count": count,
            "expected": EXPECTED_CANDLES_PER_DAY,
            "completeness_pct": round(completeness, 1),
            "is_complete": count >= EXPECTED_CANDLES_PER_DAY,
            "first_candle": first_ts,
            "last_candle": last_ts,
        })

    return result


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------


def _compute_summary(daily: list[dict]) -> dict:
    """Compute aggregate statistics from daily coverage."""
    if not daily:
        return _empty_summary()

    total_candles = sum(d["candle_count"] for d in daily)
    complete_days = sum(1 for d in daily if d["is_complete"])
    partial_days = sum(1 for d in daily if 0 < d["candle_count"] < EXPECTED_CANDLES_PER_DAY)
    empty_days = 0  # empty_days don't appear in daily (no candles = no entry)

    total_trading_days = len(daily)
    avg_completeness = total_candles / (total_trading_days * EXPECTED_CANDLES_PER_DAY) * 100 if total_trading_days else 0.0

    dates = [d["date"] for d in daily]
    data_start = min(dates) if dates else None
    data_end = max(dates) if dates else None

    # Identify missing date ranges (weekdays in span with no data)
    missing_ranges = _find_missing_ranges(data_start, data_end, daily)

    return {
        "total_trading_days": total_trading_days,
        "complete_days": complete_days,
        "partial_days": partial_days,
        "empty_days": empty_days,
        "average_completeness_pct": round(avg_completeness, 1),
        "expected_total_candles": total_trading_days * EXPECTED_CANDLES_PER_DAY,
        "actual_total_candles": total_candles,
        "coverage_pct": round(avg_completeness, 1),
        "data_start_date": data_start,
        "data_end_date": data_end,
        "missing_date_ranges": missing_ranges,
    }


def _empty_summary() -> dict:
    return {
        "total_trading_days": 0,
        "complete_days": 0,
        "partial_days": 0,
        "empty_days": 0,
        "average_completeness_pct": 0.0,
        "expected_total_candles": 0,
        "actual_total_candles": 0,
        "coverage_pct": 0.0,
        "data_start_date": None,
        "data_end_date": None,
        "missing_date_ranges": [],
    }


def _find_missing_ranges(
    start: str | None,
    end: str | None,
    daily: list[dict],
) -> list[dict]:
    """Find ranges of missing trading days within the data span."""
    if not start or not end:
        return []

    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    present = {d["date"] for d in daily}

    ranges = []
    range_start = None

    current = start_d
    while current <= end_d:
        ds = current.isoformat()
        if ds not in present and _is_trading_day(current):
            if range_start is None:
                range_start = ds
        else:
            if range_start is not None:
                prev = current - timedelta(days=1)
                ranges.append({
                    "from": range_start,
                    "to": prev.isoformat(),
                    "reason": "missing_data",
                })
                range_start = None
        current += timedelta(days=1)

    if range_start is not None:
        ranges.append({
            "from": range_start,
            "to": end,
            "reason": "missing_data",
        })

    return ranges


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------


def _detect_gaps(rows: list[NiftyCandle], interval: str = "3min") -> dict:
    """Detect intraday gaps, duplicates, and out-of-order timestamps."""
    if len(rows) < 2:
        return {
            "intraday_gaps": [],
            "duplicate_timestamps": 0,
            "out_of_order": 0,
        }

    interval_minutes = _parse_interval_minutes(interval)
    expected_delta_ms = interval_minutes * 60 * 1000

    intraday_gaps = []
    duplicates = 0
    out_of_order = 0

    seen_times: dict[str, int] = {}

    for i, row in enumerate(rows):
        if not row.open_time:
            continue

        ts = row.open_time.isoformat()

        # Duplicate check
        if ts in seen_times:
            duplicates += 1
        else:
            seen_times[ts] = i

        # Out-of-order check
        if i > 0 and rows[i - 1].open_time and row.open_time < rows[i - 1].open_time:
            out_of_order += 1

        # Intraday gap check
        if i > 0 and rows[i - 1].open_time and row.open_time:
            delta_ms = (row.open_time - rows[i - 1].open_time).total_seconds() * 1000
            if delta_ms > expected_delta_ms * 1.5:
                # Check if both candles are in the same trading session
                day1 = _utc_to_date_ist(rows[i - 1].open_time)
                day2 = _utc_to_date_ist(row.open_time)
                if day1 == day2:
                    # Same-day gap → intraday
                    missing = max(0, round(delta_ms / expected_delta_ms) - 1)
                    intraday_gaps.append({
                        "gap_start": ts,
                        "gap_end": rows[i].open_time.isoformat(),
                        "missing_candles": missing,
                    })

    return {
        "intraday_gaps": intraday_gaps,
        "duplicate_timestamps": duplicates,
        "out_of_order": out_of_order,
    }


def _parse_interval_minutes(interval: str) -> int:
    """Parse interval string like '3min' to integer minutes."""
    if isinstance(interval, int):
        return interval
    s = str(interval).lower().strip()
    if "min" in s:
        return int(s.replace("min", "").strip())
    if "hour" in s:
        return int(s.replace("hour", "").strip()) * 60
    return 3  # default


# ---------------------------------------------------------------------------
# Research readiness
# ---------------------------------------------------------------------------


def _research_readiness(summary: dict) -> dict:
    """Assess whether candle data meets Phase 7.7 research thresholds."""
    actual = summary.get("actual_total_candles", 0)
    complete_days = summary.get("complete_days", 0)
    coverage_pct = summary.get("coverage_pct", 0.0)

    min_obs_met = actual >= MIN_OBSERVATIONS
    full_val_met = actual >= MIN_VALIDATION
    robust_met = actual >= MIN_ROBUST

    # Determine status with reasons
    if robust_met and coverage_pct >= 80.0:
        status = "READY"
        reasons = ["Sufficient continuous trading-day coverage for robust research"]
    elif full_val_met and coverage_pct >= 60.0:
        status = "PARTIAL"
        reasons = [
            f"Meets full-validation threshold ({actual} candles)",
            f"Coverage: {coverage_pct:.0f}% — adequate but not robust",
        ]
    elif min_obs_met:
        status = "PARTIAL"
        reasons = [
            f"Meets basic threshold ({actual} candles)",
            "Insufficient for full validation or walk-forward analysis",
        ]
    else:
        status = "NOT_READY"
        reasons = [
            f"Only {actual} candles — below minimum {MIN_OBSERVATIONS}",
            "Need more historical data for any statistical analysis",
        ]

    return {
        "status": status,
        "reasons": reasons,
        "min_observations_met": min_obs_met,
        "full_validation_met": full_val_met,
        "robust_research_met": robust_met,
        "recommended_data_range": "6-12 months",
    }


# ---------------------------------------------------------------------------
# Empty report
# ---------------------------------------------------------------------------


def _empty_report(symbol: str, interval: str) -> dict:
    return {
        "symbol": symbol,
        "interval": interval,
        "total_candles": 0,
        "date_range": {
            "earliest": None,
            "latest": None,
            "span_days": 0,
        },
        "daily_coverage": [],
        "summary": _empty_summary(),
        "gaps": {
            "intraday_gaps": [],
            "duplicate_timestamps": 0,
            "out_of_order": 0,
        },
        "research_readiness": {
            "status": "NOT_READY",
            "reasons": ["No candle data stored"],
            "min_observations_met": False,
            "full_validation_met": False,
            "robust_research_met": False,
            "recommended_data_range": "6-12 months",
        },
    }
