"""NSE market status engine for the paper-trading platform.

This is the single source of truth for the market-hours execution gate.
Every paper order — manual BUY/SELL, strategy-generated, or automated — must
pass ``require_market_open`` in ``app/routers/paper.py`` before anything is
executed, and the check happens at the exact moment of execution, never from
a stale UI state.

Phase 5.2.1 made the engine SEGMENT-AWARE. The market is no longer a single
hard-coded 09:15–15:30 rule for every instrument: session definitions are
explicit per segment (EQUITY_CASH, EQUITY_DERIVATIVES, INDEX_DERIVATIVES,
STOCK_DERIVATIVES, CURRENCY, COMMODITY) and the resolved status carries an
explicit ``session_state`` (OPEN | CLOSING_AUCTION | TRANSITION | CLOSED |
UNKNOWN). A cash-segment SEBI closing-auction session is NEVER treated as
index-options trading time: the execution gate resolves the status for the
segment of the requested instrument (the product currently uses
INDEX_DERIVATIVES — NIFTY index options) and only an OPEN session with
``trading_allowed`` authorizes orders.

Resolution order:

1. **Upstox** is authoritative. ``GET /market/status/{exchange}`` already
   knows about trading holidays, special sessions and expiry-day timing, so
   it is always consulted first, with the exchange derived from the segment
   (INDEX_DERIVATIVES → NSE_FO, EQUITY_CASH → NSE_CASH, ...). Only
   ``NORMAL_OPEN`` authorizes orders; any other returned value (pre-open,
   closing phase, halt, unrecognized) is treated as *not open* and mapped to
   an explicit session state.

2. **Local NSE calendar** is the fallback when Upstox fails, times out or is
   unreachable. It models the segment's continuous Mon–Fri session (09:15–
   15:30 IST for derivatives/cash) and the NSE trading holiday list (2025 +
   2026) below, so a fallback never assumes the market is open on a weekend
   or a holiday. The fallback deliberately does NOT invent a closing-auction
   window for the cash segment — only the broker/exchange feed can establish
   that, and the gate stays closed outside the continuous window.

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

# ---- Segments & configurable session definitions (Phase 5.2.1) --------------
#
# One explicit, configurable session definition per segment. ``continuous_*``
# are the normal continuous-trading window in IST; ``trading_allowed`` says
# whether the segment can accept the requested paper action during its open
# session; ``session`` names the segment's regular session kind. The product
# currently trades NIFTY index options, so INDEX_DERIVATIVES is the default
# everywhere (the execution gate resolves the segment of the instrument).

INDEX_DERIVATIVES = "INDEX_DERIVATIVES"
EQUITY_CASH = "EQUITY_CASH"
EQUITY_DERIVATIVES = "EQUITY_DERIVATIVES"
STOCK_DERIVATIVES = "STOCK_DERIVATIVES"
CURRENCY = "CURRENCY"
COMMODITY = "COMMODITY"

SEGMENTS = (
    EQUITY_CASH,
    EQUITY_DERIVATIVES,
    INDEX_DERIVATIVES,
    STOCK_DERIVATIVES,
    CURRENCY,
    COMMODITY,
)

# Segment → broker/exchange market-status feed. NSE_FO covers both index and
# stock derivatives; NSE_CASH is the equity cash segment (whose SEBI closing
# auction must never be confused with index-options trading); NSE_CD is the
# currency derivatives segment; MCX_COMM the commodity exchange.
SEGMENT_EXCHANGE = {
    EQUITY_CASH: "NSE_CASH",
    EQUITY_DERIVATIVES: "NSE_FO",
    INDEX_DERIVATIVES: "NSE_FO",
    STOCK_DERIVATIVES: "NSE_FO",
    CURRENCY: "NSE_CD",
    COMMODITY: "MCX_COMM",
}


@dataclass(frozen=True)
class SessionDefinition:
    """One segment's explicit session definition (configurable, not hard-coded)."""

    segment: str
    timezone: str
    continuous_open: tuple[int, int]  # (hour, minute) IST
    continuous_close: tuple[int, int]  # (hour, minute) IST
    trading_allowed: bool = True
    session: str = "CONTINUOUS"  # NORMAL continuous-trading session kind


SESSION_DEFINITIONS: dict[str, SessionDefinition] = {
    INDEX_DERIVATIVES: SessionDefinition(INDEX_DERIVATIVES, "Asia/Kolkata", (9, 15), (15, 30)),
    EQUITY_DERIVATIVES: SessionDefinition(EQUITY_DERIVATIVES, "Asia/Kolkata", (9, 15), (15, 30)),
    STOCK_DERIVATIVES: SessionDefinition(STOCK_DERIVATIVES, "Asia/Kolkata", (9, 15), (15, 30)),
    EQUITY_CASH: SessionDefinition(EQUITY_CASH, "Asia/Kolkata", (9, 15), (15, 30)),
    CURRENCY: SessionDefinition(CURRENCY, "Asia/Kolkata", (9, 0), (17, 0)),
    COMMODITY: SessionDefinition(COMMODITY, "Asia/Kolkata", (9, 0), (23, 30)),
}


def session_definition(segment: str) -> SessionDefinition:
    """Explicit session definition for a segment (unknown → INDEX_DERIVATIVES)."""
    return SESSION_DEFINITIONS.get(segment, SESSION_DEFINITIONS[INDEX_DERIVATIVES])


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

# NSE F&O trading hours (IST) — the INDEX_DERIVATIVES continuous window.
# Kept as module constants for compatibility; per-segment times come from
# ``SESSION_DEFINITIONS``.
MARKET_OPEN_MINUTES = 9 * 60 + 15
MARKET_CLOSE_MINUTES = 15 * 60 + 30

# The only Upstox market status that authorizes order execution. Pre-open,
# closing phases, halts and any unrecognized value are never treated as open.
UPSTOX_OPEN_STATUSES = frozenset({"NORMAL_OPEN"})

# Upstox statuses that unambiguously mean the exchange is closed.
UPSTOX_CLOSED_STATUSES = frozenset({"NORMAL_CLOSE", "NORMAL_CLOSED", "CLOSED", "CLOSE"})


def session_state_for(upstream: str, segment: str = INDEX_DERIVATIVES) -> str:
    """Map an upstream (broker/exchange) status to an explicit session state.

    OPEN is the only state that authorizes orders. CLOSING_AUCTION is only
    ever derived for the cash segment (SEBI's Closing Auction Session) — an
    F&O feed's closing phase is a TRANSITION, never a cash-style auction, so
    the two are never conflated. States are only derived from broker/exchange
    status values; nothing here invents a session the feed did not report.
    """
    upstream = (upstream or "").upper()
    if upstream in UPSTOX_OPEN_STATUSES:
        return "OPEN"
    if upstream in {"PRE_OPEN", "PRE_CLOSE"}:
        return "TRANSITION"
    if upstream == "CLOSING":
        return "CLOSING_AUCTION" if segment == EQUITY_CASH else "TRANSITION"
    if upstream in UPSTOX_CLOSED_STATUSES:
        return "CLOSED"
    if upstream in {"HALT", "HALTED", "SUSPENDED"}:
        return "TRANSITION"
    return "UNKNOWN"


@dataclass(frozen=True)
class MarketStatus:
    """Resolved market status for the paper-trading execution gate.

    Phase 5.2.1: the status is resolved for ONE segment (default
    INDEX_DERIVATIVES) and carries the explicit ``session_state`` plus
    whether the segment may accept orders (``trading_allowed``). ``open``
    stays the single gate flag the router consults.
    """

    status: Literal["open", "closed", "unknown"]
    source: Literal["upstox", "calendar", "none"]
    trade_date: str | None
    checked_at: str
    message: str
    error: str | None = None
    segment: str = INDEX_DERIVATIVES
    session_state: str = "UNKNOWN"  # OPEN | CLOSING_AUCTION | TRANSITION | CLOSED | UNKNOWN
    timezone: str = "Asia/Kolkata"
    trading_allowed: bool = False

    @property
    def open(self) -> bool:
        return self.status == "open"


def ist_now() -> datetime:
    """Current wall-clock time in India Standard Time."""
    return datetime.now(IST)


def calendar_status(when: datetime | None = None, segment: str = INDEX_DERIVATIVES) -> MarketStatus:
    """Deterministic NSE calendar status (weekday + holidays + trading hours).

    The fallback used when Upstox cannot be reached. Also powers the UI
    badge's expectation while a live check is pending. Uses the segment's
    explicit session definition for its continuous window. The local
    calendar deliberately does NOT model a closing-auction window — only the
    broker/exchange feed can establish that — so the fallback reports CLOSED
    outside the continuous window for every segment.
    """
    when = when or ist_now()
    local = when.astimezone(IST)
    definition = session_definition(segment)
    open_h, open_m = definition.continuous_open
    close_h, close_m = definition.continuous_close
    day = local.date()
    # Seconds included so 15:30:00 is the last open second and 15:30:01 is closed.
    minutes = local.hour * 60 + local.minute + local.second / 60
    open_minutes = open_h * 60 + open_m
    close_minutes = close_h * 60 + close_m
    checked_at = when.isoformat()

    if local.weekday() >= 5:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            "Weekend — NSE is closed (Saturday/Sunday).",
            segment=segment, session_state="CLOSED",
        )
    if day in NSE_TRADING_HOLIDAYS:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            f"NSE trading holiday ({day.strftime('%d %b %Y')}).",
            segment=segment, session_state="CLOSED",
        )
    if minutes < open_minutes:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            f"Before the {open_h:02d}:{open_m:02d} IST market open.",
            segment=segment, session_state="CLOSED",
        )
    if minutes > close_minutes:
        return MarketStatus(
            "closed", "calendar", day.isoformat(), checked_at,
            f"After the {close_h:02d}:{close_m:02d} IST market close.",
            segment=segment, session_state="CLOSED",
        )
    return MarketStatus(
        "open", "calendar", day.isoformat(), checked_at,
        f"Within {definition.segment} market hours (Mon–Fri "
        f"{open_h:02d}:{open_m:02d}–{close_h:02d}:{close_m:02d} IST).",
        segment=segment, session_state="OPEN", trading_allowed=definition.trading_allowed,
    )


async def get_market_status(
    access_token: str | None,
    now: datetime | None = None,
    segment: str = INDEX_DERIVATIVES,
) -> MarketStatus:
    """Resolve the current market status for one segment (execution gate).

    Upstox is authoritative (using the segment's exchange feed, e.g.
    NSE_FO for INDEX_DERIVATIVES); on failure/timeout we fall back to the
    local calendar. ``unknown`` is returned only when no source can
    determine a status — callers must treat that as blocked. Only an OPEN
    session with ``trading_allowed`` marks the status open.
    """
    checked_at = (now or ist_now()).isoformat()
    default_trade_date = (now or ist_now()).astimezone(IST).date().isoformat()
    definition = session_definition(segment)
    exchange = SEGMENT_EXCHANGE[segment]

    if access_token:
        try:
            body = await upstox.get_market_status(access_token, exchange=exchange)
            data = body.get("data") or {}
            upstream = (data.get("status") or "").upper()
            trade_date = data.get("trade_date") or default_trade_date
            if upstream in UPSTOX_OPEN_STATUSES and definition.trading_allowed:
                return MarketStatus(
                    "open", "upstox", trade_date, checked_at,
                    f"Upstox reports {exchange} market status OPEN "
                    f"({definition.segment}).",
                    segment=segment, session_state="OPEN", trading_allowed=True,
                )
            if upstream in UPSTOX_CLOSED_STATUSES:
                return MarketStatus(
                    "closed", "upstox", trade_date, checked_at,
                    f"Upstox reports {exchange} market status CLOSED.",
                    segment=segment, session_state="CLOSED",
                )
            # Valid response but a non-open state (pre-open, closing auction,
            # halt, unrecognized): never treat it as open. The explicit
            # session state tells the UI exactly what that state was — e.g.
            # a cash-segment CLOSING_AUCTION never enables index-option
            # execution because the gate resolves the INDEX_DERIVATIVES
            # segment, and its feed never reports CLOSING_AUCTION.
            session_state = session_state_for(upstream, segment)
            return MarketStatus(
                "closed", "upstox", trade_date, checked_at,
                f"Upstox reports {exchange} market status '{upstream}' — "
                "orders are blocked.",
                segment=segment, session_state=session_state,
            )
        except Exception as exc:  # UpstoxError, network timeouts, ...
            logger.warning(
                "Upstox market status unavailable (%s); falling back to local calendar", exc
            )

    fallback = calendar_status(now, segment=segment)
    if fallback.status == "unknown":
        return MarketStatus(
            "unknown", "none", None, checked_at,
            "Unable to verify market status.",
            "No market-status source could be reached",
            segment=segment, session_state="UNKNOWN",
        )
    return fallback
