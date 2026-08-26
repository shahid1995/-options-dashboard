"""Candle ingestion — Phase 7.8B (Ingestion & Normalization).

Converts raw Upstox V3 historical-candle responses into the dict format
expected by ``nifty_candles.record_candles()``.

Three public functions:

* ``extract_candles_from_response`` — pull the candle array out of an
  Upstox API response dict, returning ``[]`` for any error or malformed
  payload.
* ``normalize_candle_timestamp`` — convert an Upstox IST timestamp
  (``"2025-01-12T15:15:00+05:30"``) to a naive IST ``datetime``
  (Phase 7.24.4 storage convention).
* ``normalize_candle`` — transform a single raw candle array
  ``[ts, O, H, L, C, V, OI]`` into the ``record_candles()`` dict.
* ``normalize_candles`` — batch wrapper over ``normalize_candle``.

Design constraints (Phase 7.24.4):
  - All timestamps are stored as naive IST (Asia/Kolkata) datetimes.
  - Volume and OI are **never** converted into lots/contracts.
  - Candle ingestion is completely independent of NIFTY option lot_size.
  - Historical lot_size is never inferred, applied, or referenced here.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.utils.market_time import to_ist_naive, IST

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYMBOL = "NIFTY"
DEFAULT_INTERVAL = "3min"


# ---------------------------------------------------------------------------
# Timestamp normalization
# ---------------------------------------------------------------------------


def normalize_candle_timestamp(ist_timestamp: str | None) -> datetime:
    """Convert an Upstox IST timestamp to a naive IST datetime.

    Parameters
    ----------
    ist_timestamp:
        An ISO 8601 timestamp as returned by the Upstox API, e.g.
        ``"2025-01-12T15:15:00+05:30"``.  May or may not carry an
        explicit offset.

    Returns
    -------
    datetime
        A **naive** (tzinfo=None) datetime in IST, suitable for SQLite
        storage via ``NiftyCandle.open_time`` / ``OptionCandle.open_time``.

    Raises
    ------
    ValueError
        If the timestamp string cannot be parsed.
    TypeError
        If *ist_timestamp* is not a string.

    Examples
    --------
    >>> normalize_candle_timestamp("2025-01-12T15:15:00+05:30")
    datetime(2025, 1, 12, 15, 15)

    >>> normalize_candle_timestamp("2025-01-12T09:45:00Z")
    datetime(2025, 1, 12, 15, 15)
    """
    if ist_timestamp is None:
        raise ValueError("Timestamp is None")

    result = to_ist_naive(ist_timestamp)
    if result is None:
        raise ValueError(f"Cannot parse timestamp: {ist_timestamp}")
    return result


# ---------------------------------------------------------------------------
# Single-candle normalization
# ---------------------------------------------------------------------------


def normalize_candle(
    raw_candle: list | tuple,
    symbol: str = DEFAULT_SYMBOL,
    interval: str = DEFAULT_INTERVAL,
) -> dict | None:
    """Convert a single Upstox raw candle array into the ``record_candles()`` format.

    Parameters
    ----------
    raw_candle:
        A list/tuple of at least 6 elements:
        ``[timestamp, open, high, low, close, volume, ...]``
        The 7th element (open_interest) is accepted but **ignored** for
        index candles — volume and OI are never converted into lots.
    symbol:
        Instrument symbol (default ``"NIFTY"``).  Stored upper-cased.
    interval:
        Candle interval (default ``"3min"``).

    Returns
    -------
    dict or None
        A dict with keys ``symbol``, ``interval``, ``openTime`` (ISO 8601
        UTC with ``Z`` suffix), ``open``, ``high``, ``low``, ``close``,
        ``volume``.  Returns ``None`` when the raw candle is structurally
        invalid (wrong type, missing fields, non-numeric prices, or
        unparseable timestamp).

    Notes
    -----
    * The open_interest field (index 6) is intentionally **not** included
      in the output — it is irrelevant for NIFTY index candles and must
      never be conflated with lot-size-dependent contract data.
    * Prices are cast to ``float``; volume defaults to ``0.0`` when
      non-numeric.
    """
    if not isinstance(raw_candle, (list, tuple)) or len(raw_candle) < 6:
        return None

    ist_timestamp = raw_candle[0]
    open_price = raw_candle[1]
    high = raw_candle[2]
    low = raw_candle[3]
    close = raw_candle[4]
    volume = raw_candle[5]
    # raw_candle[6] is open_interest — intentionally ignored for index candles

    # Validate numeric OHLC fields
    for _name, val in (("open", open_price), ("high", high), ("low", low), ("close", close)):
        if val is None or not isinstance(val, (int, float)):
            return None

    # Volume — coerce to float, default 0.0 for non-numeric
    if not isinstance(volume, (int, float)):
        volume = 0.0

    # Normalize timestamp (IST → naive UTC)
    try:
        open_time_utc = normalize_candle_timestamp(ist_timestamp)
    except (ValueError, TypeError):
        return None

    return {
        "symbol": symbol.upper().strip(),
        "interval": interval.strip(),
        "openTime": open_time_utc.isoformat(),  # naive IST, no Z suffix
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }


# ---------------------------------------------------------------------------
# Batch normalization
# ---------------------------------------------------------------------------


def normalize_candles(
    raw_candles: list[list] | list[tuple],
    symbol: str = DEFAULT_SYMBOL,
    interval: str = DEFAULT_INTERVAL,
) -> list[dict]:
    """Normalize a batch of raw Upstox candle arrays.

    Invalid candles are silently dropped (returns a shorter list).
    """
    out: list[dict] = []
    for raw in (raw_candles or []):
        normalized = normalize_candle(raw, symbol=symbol, interval=interval)
        if normalized is not None:
            out.append(normalized)
    return out


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


def extract_candles_from_response(response: dict | None) -> list[list]:
    """Extract the raw candle array from an Upstox V3 historical-candle response.

    Handles both success and error responses gracefully — returns ``[]``
    for any malformed or error payload.

    Parameters
    ----------
    response:
        The full JSON response dict from the Upstox API, e.g.
        ``{"status": "success", "data": {"candles": [[...], ...]}}``.

    Returns
    -------
    list[list]
        The candle arrays, or ``[]`` if extraction fails.
    """
    if not isinstance(response, dict):
        return []
    if response.get("status") != "success":
        return []
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    candles = data.get("candles")
    if not isinstance(candles, list):
        return []
    return candles
