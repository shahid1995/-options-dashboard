"""Centralized market-data timestamp utility — Phase 7.24.4.

Permanent convention:

    **All persisted market-data candle timestamps are naive IST (Asia/Kolkata).**

This module provides the single canonical conversion function used by
both NIFTY and option-candle ingestion pipelines.

Architecture::

    Upstox API timestamp (IST with offset)
              │
              ▼
    to_ist_naive()   ← THIS MODULE
              │
              ▼
    naive datetime representing IST local time
              │
              ▼
    SQLite / NiftyCandle.open_time / OptionCandle.open_time

Design rules:

  - Timezone conversion occurs ONLY at ingestion boundaries.
  - The database never stores UTC or any other timezone.
  - The Greeks engine compares timestamps directly (both naive IST).
  - Display/UI may convert naive IST to any desired format.

Why naive IST?

  SQLite does not natively store timezone information. Storing naive
  IST timestamps means:

  1. The stored time is directly readable as Indian market time.
  2. No runtime conversion is needed for alignment comparisons.
  3. Trading-session queries (09:15–15:30) work naturally.
  4. Post-close candles (15:27–15:40) are directly comparable.

  The alternative (storing naive UTC) would require converting every
  comparison and display operation to IST, which is error-prone and
  was the root cause of the Phase 7.23B historical Greeks failure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
"""Indian Standard Time (UTC+05:30)."""

IST_OFFSET = timedelta(hours=5, minutes=30)
"""Timedelta representing the IST offset from UTC."""

# NSE market hours (IST)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
POST_CLOSE_START = (15, 27)
POST_CLOSE_END = (15, 40)


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def to_ist_naive(value: str | datetime | None) -> datetime | None:
    """Convert a timestamp to a naive IST datetime.

    This is the SINGLE canonical conversion function for all market-data
    timestamps. Both NIFTY and option-candle ingestion must use this.

    Parameters
    ----------
    value :
        One of:
        - An ISO 8601 timestamp string (e.g. ``"2026-08-22T09:15:00+05:30"``
          or ``"2026-08-22T09:15:00Z"``).
        - A timezone-aware datetime (IST or UTC).
        - A naive datetime (assumed to already be IST).
        - None (returns None).

    Returns
    -------
    datetime or None
        A naive (tzinfo=None) datetime representing IST local time.

    Examples
    --------
    >>> to_ist_naive("2026-08-22T09:15:00+05:30")
    datetime(2026, 8, 22, 9, 15)

    >>> to_ist_naive("2026-08-22T03:45:00Z")
    datetime(2026, 8, 22, 9, 15)

    >>> from datetime import datetime, timezone
    >>> dt_utc = datetime(2026, 8, 22, 3, 45, tzinfo=timezone.utc)
    >>> to_ist_naive(dt_utc)
    datetime(2026, 8, 22, 9, 15)
    """
    if value is None:
        return None

    # --- String input ---
    if isinstance(value, str):
        if not value.strip():
            return None
        # Handle "Z" suffix (not supported by fromisoformat in all versions)
        normalized = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
        return _aware_to_naive_ist(dt)

    # --- datetime input ---
    if isinstance(value, datetime):
        return _aware_to_naive_ist(value)

    return None


def _aware_to_naive_ist(dt: datetime) -> datetime:
    """Convert a datetime (aware or naive) to naive IST.

    If naive, assume it is already IST and return as-is.
    If aware, convert to IST and strip timezone info.
    """
    if dt.tzinfo is None:
        # Already naive — assume IST (the storage convention)
        return dt

    # Convert to IST, then strip tzinfo
    ist_dt = dt.astimezone(IST)
    return ist_dt.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Trading session helpers
# ---------------------------------------------------------------------------

def is_market_hours(dt: datetime) -> bool:
    """Check if a naive IST datetime falls within NSE trading hours (09:15–15:30).

    Does NOT check weekends/holidays.
    """
    h, m = dt.hour, dt.minute
    return (h, m) >= MARKET_OPEN and (h, m) <= MARKET_CLOSE


def is_post_close(dt: datetime) -> bool:
    """Check if a naive IST datetime is in the post-close window (15:27–15:40).

    Post-close option candles are legitimate data that should be preserved.
    """
    h, m = dt.hour, dt.minute
    return (h, m) >= POST_CLOSE_START and (h, m) <= POST_CLOSE_END


def ist_naive_to_string(dt: datetime) -> str:
    """Format a naive IST datetime as an ISO 8601 string with +05:30 suffix.

    Useful for API responses and logging.
    """
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
