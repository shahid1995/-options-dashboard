from datetime import datetime

import httpx
import pytest
import respx

from app.services import market_status, upstox

IST = market_status.IST


def ist(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


# ---------------- Local calendar fallback ----------------


def test_calendar_open_during_market_hours():
    # Friday 2026-08-14 10:00 IST.
    st = market_status.calendar_status(ist(2026, 8, 14, 10, 0))
    assert st.status == "open"
    assert st.source == "calendar"


def test_calendar_closed_before_open():
    assert market_status.calendar_status(ist(2026, 8, 14, 9, 14)).status == "closed"


def test_calendar_open_at_exact_open_boundary():
    assert market_status.calendar_status(ist(2026, 8, 14, 9, 15)).status == "open"


def test_calendar_open_at_exact_close_boundary():
    assert market_status.calendar_status(ist(2026, 8, 14, 15, 30)).status == "open"


def test_calendar_closed_one_second_after_close():
    assert market_status.calendar_status(ist(2026, 8, 14, 15, 30, 1)).status == "closed"


def test_calendar_closed_on_saturday():
    # 2026-08-15 is a Saturday.
    st = market_status.calendar_status(ist(2026, 8, 15, 10, 0))
    assert st.status == "closed"
    assert "Weekend" in st.message


def test_calendar_closed_on_sunday():
    assert market_status.calendar_status(ist(2026, 8, 16, 10, 0)).status == "closed"


def test_calendar_closed_on_holiday():
    # Republic Day 2026-01-26 is a Monday.
    st = market_status.calendar_status(ist(2026, 1, 26, 10, 0))
    assert st.status == "closed"
    assert "holiday" in st.message.lower()


# ---------------- Upstox is authoritative; calendar is the fallback ----------------


def _mock_upstox_status(status_value, http_status=200):
    return respx.get(f"{upstox.BASE_URL}/market/status/NSE_FO").mock(
        return_value=httpx.Response(
            http_status,
            json={"status": "success", "data": {"exchange": "NSE_FO", "status": status_value}},
        )
    )


@respx.mock
async def test_upstox_open_is_authoritative():
    _mock_upstox_status("NORMAL_OPEN")
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 14, 10, 0))
    assert st.status == "open"
    assert st.source == "upstox"


@respx.mock
async def test_upstox_closed_is_authoritative_even_during_calendar_hours():
    _mock_upstox_status("NORMAL_CLOSE")
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 14, 10, 0))
    assert st.status == "closed"
    assert st.source == "upstox"


@respx.mock
async def test_upstox_unrecognized_status_is_never_open():
    _mock_upstox_status("HALT")
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 14, 10, 0))
    assert st.status == "closed"
    assert st.source == "upstox"


@respx.mock
async def test_upstox_failure_falls_back_to_calendar_open():
    _mock_upstox_status("boom", http_status=500)
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 14, 10, 0))
    assert st.status == "open"
    assert st.source == "calendar"


@respx.mock
async def test_upstox_failure_falls_back_to_calendar_closed_on_weekend():
    _mock_upstox_status("boom", http_status=500)
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 15, 10, 0))
    assert st.status == "closed"
    assert st.source == "calendar"


@respx.mock
async def test_upstox_network_error_falls_back_to_calendar():
    respx.get(f"{upstox.BASE_URL}/market/status/NSE_FO").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    st = await market_status.get_market_status("tok-123", now=ist(2026, 8, 14, 10, 0))
    assert st.status == "open"
    assert st.source == "calendar"


async def test_no_token_uses_calendar():
    st = await market_status.get_market_status(None, now=ist(2026, 8, 14, 10, 0))
    assert st.status == "open"
    assert st.source == "calendar"


# ---------------- Phase 5.2.1: segment-aware sessions ----------------


def _mock_status(exchange: str, status_value: str):
    return respx.get(f"{upstox.BASE_URL}/market/status/{exchange}").mock(
        return_value=httpx.Response(
            200,
            json={"status": "success", "data": {"exchange": exchange, "status": status_value}},
        )
    )


def test_session_definitions_are_explicit_and_configurable():
    d = market_status.session_definition(market_status.INDEX_DERIVATIVES)
    assert d.segment == "INDEX_DERIVATIVES"
    assert d.timezone == "Asia/Kolkata"
    assert d.continuous_open == (9, 15)
    assert d.continuous_close == (15, 30)
    assert d.trading_allowed is True
    # Segment → exchange feed mapping exists for every required segment.
    assert market_status.SEGMENT_EXCHANGE[market_status.INDEX_DERIVATIVES] == "NSE_FO"
    assert market_status.SEGMENT_EXCHANGE[market_status.EQUITY_DERIVATIVES] == "NSE_FO"
    assert market_status.SEGMENT_EXCHANGE[market_status.STOCK_DERIVATIVES] == "NSE_FO"
    assert market_status.SEGMENT_EXCHANGE[market_status.EQUITY_CASH] == "NSE_CASH"
    assert market_status.SEGMENT_EXCHANGE[market_status.CURRENCY] == "NSE_CD"
    assert market_status.SEGMENT_EXCHANGE[market_status.COMMODITY] == "MCX_COMM"
    # Unknown segments fall back to the INDEX_DERIVATIVES definition.
    assert market_status.session_definition("BOGUS").segment == market_status.INDEX_DERIVATIVES


def test_session_state_mapping_is_explicit():
    # OPEN is the only state that authorizes orders.
    assert market_status.session_state_for("NORMAL_OPEN") == "OPEN"
    assert market_status.session_state_for("NORMAL_CLOSE") == "CLOSED"
    assert market_status.session_state_for("PRE_OPEN") == "TRANSITION"
    assert market_status.session_state_for("WHATEVER") == "UNKNOWN"
    # A cash-segment CLOSING phase is the SEBI closing auction; an F&O
    # CLOSING phase is NOT an auction — the two are never conflated.
    assert market_status.session_state_for("CLOSING", market_status.EQUITY_CASH) == "CLOSING_AUCTION"
    assert market_status.session_state_for("CLOSING", market_status.INDEX_DERIVATIVES) == "TRANSITION"


def test_calendar_status_is_segment_aware():
    # Cash continuous window matches index derivatives in the fallback, and
    # the fallback never invents a closing-auction window (CLOSED outside).
    open_cash = market_status.calendar_status(ist(2026, 8, 14, 10, 0), segment=market_status.EQUITY_CASH)
    assert open_cash.status == "open"
    assert open_cash.session_state == "OPEN"
    assert open_cash.trading_allowed is True
    late = market_status.calendar_status(ist(2026, 8, 14, 16, 0), segment=market_status.EQUITY_CASH)
    assert late.status == "closed"
    assert late.session_state == "CLOSED"
    assert late.trading_allowed is False


@respx.mock
async def test_index_derivatives_gate_uses_nse_fo_not_cash_feed():
    # The cash segment is inside its CLOSING auction while NSE_FO is open:
    # the index-derivatives gate must resolve from NSE_FO and stay OPEN.
    _mock_status("NSE_CASH", "CLOSING")
    _mock_status("NSE_FO", "NORMAL_OPEN")
    st = await market_status.get_market_status(
        "tok-123", now=ist(2026, 8, 14, 15, 35), segment=market_status.INDEX_DERIVATIVES
    )
    assert st.status == "open"
    assert st.session_state == "OPEN"
    assert st.source == "upstox"


@respx.mock
async def test_cash_closing_auction_is_closed_and_not_open():
    _mock_status("NSE_CASH", "CLOSING")
    st = await market_status.get_market_status(
        "tok-123", now=ist(2026, 8, 14, 15, 35), segment=market_status.EQUITY_CASH
    )
    assert st.status == "closed"
    assert st.session_state == "CLOSING_AUCTION"
    assert st.open is False


@respx.mock
async def test_fno_closing_phase_is_transition_never_auction():
    _mock_status("NSE_FO", "CLOSING")
    st = await market_status.get_market_status(
        "tok-123", now=ist(2026, 8, 14, 15, 35), segment=market_status.INDEX_DERIVATIVES
    )
    assert st.status == "closed"
    assert st.session_state == "TRANSITION"
    assert st.open is False


@respx.mock
async def test_unknown_status_is_never_open():
    _mock_status("NSE_FO", "SOME_NEW_STATUS")
    st = await market_status.get_market_status(
        "tok-123", now=ist(2026, 8, 14, 10, 0), segment=market_status.INDEX_DERIVATIVES
    )
    assert st.status == "closed"
    assert st.session_state == "UNKNOWN"
    assert st.open is False


async def test_backend_gate_remains_authoritative_for_non_open_session():
    from fastapi import HTTPException
    from unittest.mock import AsyncMock, patch

    from app.routers import paper as paper_router

    non_open = market_status.MarketStatus(
        "closed", "upstox", "2026-08-14", "2026-08-14T15:35:00+05:30",
        "orders blocked", segment=market_status.INDEX_DERIVATIVES,
        session_state="CLOSING_AUCTION",
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=non_open)):
        with pytest.raises(HTTPException) as exc:
            await paper_router.require_market_open("tok-123")
    assert exc.value.status_code == 409


async def test_backend_gate_opens_only_for_open_session():
    from fastapi import HTTPException
    from unittest.mock import AsyncMock, patch

    from app.routers import paper as paper_router

    open_status = market_status.MarketStatus(
        "open", "upstox", "2026-08-14", "2026-08-14T10:00:00+05:30",
        "NSE_FO open", segment=market_status.INDEX_DERIVATIVES,
        session_state="OPEN", trading_allowed=True,
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=open_status)):
        # No exception == gate passed.
        await paper_router.require_market_open("tok-123")
