"""Centralized timestamp utilities for the StrikeNova backend.

Canonical conventions:

  - **Persistence (non-market-data):** Always use UTC-aware datetimes
    (``datetime.now(timezone.utc)``).  SQLite strips timezone info on
    storage, so the stored value is naive-UTC in the DB, but all
    application code must pass timezone-aware datetimes.

  - **Market-data candle timestamps:** Naive IST (Asia/Kolkata),
    per the Phase 7.24.4 convention in ``app.utils.market_time``.

  - **API responses:** ISO 8601 with explicit offset
    (``datetime.now(timezone.utc).isoformat()`` produces ``"+00:00"``).

  - **Frontend display:** The browser uses ``toLocaleString('en-IN')``
    which handles timezone conversion client-side.

Deprecated patterns that must NOT be used:

  - ``datetime.utcnow()`` — deprecated in Python 3.12, returns naive UTC.
  - ``datetime.now()`` — returns naive local time, timezone-dependent.
  - Manually suffixed ``"Z"`` on naive timestamps.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------
# Canonical timezone objects
# -----------------------------------------------------------------------

UTC = timezone.utc
"""UTC timezone singleton."""

IST = ZoneInfo("Asia/Kolkata")
"""Indian Standard Time as a proper IANA zone (used for display/formatting).

Note: ``app.utils.market_time.IST`` uses ``timezone(timedelta(hours=5, minutes=30))``
for naive-IST market-data storage.  This ``IST`` uses ``ZoneInfo`` for
timezone-aware display and formatting.  Both represent the same offset
but serve different purposes.
"""

# -----------------------------------------------------------------------
# Canonical "now" functions
# -----------------------------------------------------------------------


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Use this everywhere instead of ``datetime.utcnow()`` or
    ``datetime.now(timezone.utc)`` to ensure a single canonical source.
    """
    return datetime.now(UTC)


def ist_now() -> datetime:
    """Return the current IST time as a timezone-aware datetime.

    Useful for display formatting and IST-specific logic that requires
    a timezone-aware object (e.g., ``ist_now().strftime(...)``).
    """
    return datetime.now(IST)


# -----------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------


def to_iso_utc(dt: datetime | None) -> str | None:
    """Format a datetime as an ISO 8601 string with UTC offset.

    >>> to_iso_utc(datetime(2026, 8, 29, 8, 25, tzinfo=timezone.utc))
    '2026-08-29T08:25:00+00:00'
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def to_ist_display(dt: datetime | None) -> str:
    """Format a datetime for Indian user display: '29 Aug, 07:25 pm'.

    Accepts both aware and naive datetimes.  Naive datetimes are
    assumed to be UTC.
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    ist_dt = dt.astimezone(IST)
    return ist_dt.strftime("%d %b, %I:%M %p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")
