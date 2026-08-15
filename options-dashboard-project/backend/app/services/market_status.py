"""NSE market status engine for the paper-trading platform.

This is the single source of truth for the market-hours execution gate.
Every paper order — manual BUY/SELL, strategy-generated, or automated — must
pass ``require_market_open`` in ``app/routers/paper.py`` before anything is
executed, and the check happens at the exact moment of execution, never from
a stale UI state.

Resolution order:

1. **Upstox** ``GET /v2/market/status/NSE_FO`` is authoritative. It already
   knows about trading holidays, special sessions and expiry-day timing, so
   it is always consulted first. Only ``NORMAL_OPEN`` authorizes orders; any
   other returned value (pre-open, closing phase, halt, unrecognized) is
   treated as *not open*.

2. **Local NSE calendar** is the fallback when Upstox fails, times out or is
   unreachable. It models Mon–Fri 09:15–15:30 IST and the NSE trading
   holiday list (2025 + 2026) below, so a fallback never assumes the market
   is open on a weekend or a holiday.

3. **Unknown** is returned only if neither source can determine a status.
   Callers must block the order: an unknown status is NEVER treated as open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from app.services import upstox

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# NSE (Equity Derivatives / F&O segment) trading holidays. Used only by the
# local-calendar fallback when Upstox is unreachable, so the engine still
# knows holidays are closed. Weekends are handled by the weekday rule.
NSE_TRADING_HOLIDAYS: frozenset[date] = frozenset(
    {
        # ---- 2025 ----
        date(2025, 2, 26),  # Maha Shivratri
        date(2025, 3, 14),  # Holi
        date(2025, 3, 31),  # Id-Ul-Fitr
        date(2025, 4, 10),  # Shri Mahavir Jayanti
        date(2025, 4, 14),  # Dr. Ambedkar Jayanti
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 1),   # Maharashtra Day
        date(2025, 5, 12),  # Buddha Purnima
        date(2025, 8, 15),  # Independence Day
        date(2025, 8, 27),  # Muharram
        date(2025, 10, 2),  # Gandhi Jayanti
        date(2025, 10, 21),  # Diwali Laxmi Puja
        date(2025, 10, 22),  # Diwali Balipratipada
        date(2025, 11, 5),  # Guru Nanak Jayanti
        date(2025, 12, 25),  # Christmas
        # ---- 2026 ----
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 3),   # Holi
        date(2026, 3, 26),  # Ram Navami
        date(2026, 3, 31),  # Mahavir Jayanti
        date(2026, 4, 3),   # Good Friday
        date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
        date(2026, 5, 1),   # Maharashtra Day
        date(2026, 5, 28),  # Bakri Id / Eid ul-Adha
        date(2026, 6, 26),  # Muharram
        date(2026, 9, 14),  # Ganesh Chaturthi
        date(2026, 10, 2),  # Mahatma Gandhi Jayanti
        date(2026, 10, 20),  # Dasara
        date(2026, 11, 8),  # Diwali Laxmi Pujan (Sunday — Muhurat trading only)
        date(2026, 11, 10),  # Diwali Balipratipada
        date(2026, 11, 24),  # Guru Nanak Jayanti
        date(2026, 12, 25),  # Christmas
    }
)

# NSE F&O trading hours (IST). Index options trade 09:15–15:30, Mon–Fri.
MARKET_OPEN_MINUTES = 9 * 60 + 15
MARKET_CLOSE_MINUTES = 15 * 60 + 30

# The only Upstox market status that authorizes order execution. Pre-open,
# closing phases, halts and any unrecognized value are never treated as open.
UPSTOX_OPEN_STATUSES = frozenset({"NORMAL_OPEN"})


@dataclass(frozen=True)
class MarketStatus:
    """Resolved market status for the paper-trading execution gate."""

    status: Literal["open", "closed", "unknown"]
    source: Literal["upstox", "calendar", "none"]
    trade_date: str | None
    checked_at: str
    message: str
    error: str | None = None

    @property
    def open(self) -> bool:
        return self.status == "open"


def ist_now() -> datetime:
    """Current wall-clock time in India Standard Time."""
    return datetime.now(IST)


def calendar_status(when: datetime | None = None) -> MarketStatus:
    """Deterministic NSE calendar status (weekday + holidays + trading hours).

    The fallback used when Upstox cannot be reached. Also powers the UI
    badge's expectation while a live check is pending.
    """
    when = when or ist_now()
    local = when.astimezone(IST)
    day = local.date()
    # Seconds included so 15:30:00 is the last open second and 15:30:01 is closed.
    minutes = local.hour * 60 + local.minute + local.second / 60
    checked_at = when.isoformat()

    if local.weekday() >= 5:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            "Weekend — NSE is closed (Saturday/Sunday).",
        )
    if day in NSE_TRADING_HOLIDAYS:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            f"NSE trading holiday ({day.strftime('%d %b %Y')}).",
        )
    if minutes < MARKET_OPEN_MINUTES:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            "Before the 09:15 IST market open.",
        )
    if minutes > MARKET_CLOSE_MINUTES:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            "After the 15:30 IST market close.",
        )
    return MarketStatus(
        "open", "calendar", day.isoformat(), checked_at,
        "Within NSE market hours (Mon–Fri 09:15–15:30 IST).",
    )


async def get_market_status(access_token: str | None, now: datetime | None = None) -> MarketStatus:
    """Resolve the current NSE market status for the execution gate.

    Upstox is authoritative; on failure/timout we fall back to the local
    calendar. ``unknown`` is returned only when no source can determine a
    status — callers must treat that as blocked.
    """
    checked_at = (now or ist_now()).isoformat()
    default_trade_date = (now or ist_now()).astimezone(IST).date().isoformat()

    if access_token:
        try:
            body = await upstox.get_market_status(access_token)
            data = body.get("data") or {}
            upstream = (data.get("status") or "").upper()
            trade_date = data.get("trade_date") or default_trade_date
            if upstream in UPSTOX_OPEN_STATUSES:
                return MarketStatus(
                    "open", "upstox", trade_date, checked_at,
                    "Upstox reports NSE F&O market OPEN.",
                )
            if upstream in {"NORMAL_CLOSE", "NORMAL_CLOSED", "CLOSED", "CLOSE"}:
                return MarketStatus(
                    "closed", "upstox", trade_date, checked_at,
                    "Upstox reports NSE F&O market CLOSED.",
                )
            # Valid response but an unrecognized/non-open state (halt,
            # pre-open, closing auction, ...): never treat it as open.
            return MarketStatus(
                "closed", "upstox", trade_date, checked_at,
                f"Upstox reports NSE market status '{upstream}' — orders are blocked.",
            )
        except Exception as exc:  # UpstoxError, network timeouts, ...
            logger.warning(
                "Upstox market status unavailable (%s); falling back to local calendar", exc
            )

    fallback = calendar_status(now)
    if fallback.status == "unknown":
        return MarketStatus(
            "unknown", "none", None, checked_at,
            "Unable to verify market status.",
            "No market-status source could be reached",
        )
    return fallback
