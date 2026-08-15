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
