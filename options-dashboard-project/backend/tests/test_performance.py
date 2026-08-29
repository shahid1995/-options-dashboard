"""Phase 5.1 tests — portfolio & journal analytics.

Covers the spec's §38 matrix: portfolio summary, trade classification,
win rate, average winner/loser, profit factor, expectancy, largest win/loss,
streaks, holding duration, drawdown, strategy grouping, position exposure,
data quality, user isolation — plus the grouped-journal API and filters.

Pure helpers are tested directly; the API paths go through the router with
the same fixtures as test_paper_execution.py (market gate open, mocked
chain data, in-memory SQLite).
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.services import token_store
from tests.test_helpers import create_test_identity
from app.services.performance import (
    average_loser,
    average_winner,
    classify_result,
    daily_pnl,
    drawdown,
    duration_stats,
    equity_curve,
    expectancy,
    format_duration,
    holding_duration_seconds,
    largest_loser,
    largest_winner,
    profit_factor,
    streaks,
    strategy_grouping,
    win_rate,
)

LOT = 65
EXPIRY = "2026-08-27"
EXPIRY2 = "2026-09-03"

DEFAULT_CHAIN = {
    EXPIRY: {
        24350: {"call": 125.25, "put": 90.0},
        24550: {"call": 35.60, "put": 200.0},
        25000: {"call": 200.0, "put": 80.0},
    },
    EXPIRY2: {24350: {"call": 130.0, "put": 95.0}},
}


def chain_payload(expiry, quotes):
    data = []
    for strike, sides in quotes.items():
        item = {"strike_price": strike, "underlying_spot_price": 24000.0}
        item["call_options"] = {"market_data": {"ltp": sides["call"]}, "option_greeks": {}}
        item["put_options"] = {"market_data": {"ltp": sides["put"]}, "option_greeks": {}}
        data.append(item)
    return {"data": data}


@pytest.fixture(autouse=True)
def market_open_gate():
    status = SimpleNamespace(
        status="open", source="test", trade_date="2026-08-14",
        checked_at="2026-08-14T10:00:00+05:30", message="open", error=None,
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=status)):
        yield


@pytest.fixture
def chain_quotes():
    return deepcopy(DEFAULT_CHAIN)


@pytest.fixture(autouse=True)
def chain_mock(chain_quotes):
    async def fake(token, instrument_key, expiry):
        return chain_payload(expiry, chain_quotes.get(expiry, {}))

    with patch("app.services.upstox.get_option_chain", new=AsyncMock(side_effect=fake)) as m:
        yield m


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client, db_session):
    session_id, _ = create_test_identity(db_session, "tok-phase51")
    return session_id


def headers(session_id):
    return {"X-Session-Id": session_id}


# ---- payload builders -------------------------------------------------------

_counter = {"n": 0}


def next_id(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:06d}"


def single_leg_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Long Call",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24350,
                "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
            }
        ],
    }
    payload.update(overrides)
    return payload


def spread_payload(**overrides):
    payload = {
        "client_order_id": next_id("exec"),
        "symbol": "NIFTY",
        "strategy_tag": "Bull Call Spread",
        "starting_capital": 500000,
        "legs": [
            {"symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24350,
             "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT},
            {"symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24550,
             "option_type": "call", "action": "sell", "quantity": 1, "lot_size": LOT},
        ],
    }
    payload.update(overrides)
    return payload


def execute(client, session_id, payload):
    return client.post("/paper/executions", headers=headers(session_id), json=payload)


def exit_position(client, session_id, position_id, payload):
    return client.post(
        f"/paper/positions/{position_id}/exit", headers=headers(session_id), json=payload
    )


def get_analytics(client, session_id, params=None):
    return client.get("/paper/analytics", headers=headers(session_id), params=params or {})


def open_position_ids(db_session):
    from app.models import Position

    return [p.id for p in db_session.query(Position).filter(Position.status == "open").all()]


def close_all_positions(client, session_id, db_session):
    """Full-exit every open position (each exit gets its own idempotency key)."""
    for pid in open_position_ids(db_session):
        resp = exit_position(client, session_id, pid, {"client_order_id": next_id("exit")})
        assert resp.status_code == 200, resp.text
    assert open_position_ids(db_session) == []


def completed_trades(analytics):
    return analytics["performance"]["total_completed_trades"]


# =============================================================================
# Pure classification helpers
# =============================================================================


def test_classify_win_loss_breakeven():
    assert classify_result(100.0) == "WIN"
    assert classify_result(-10.0) == "LOSS"
    assert classify_result(0.0) == "BREAKEVEN"
    assert classify_result(None) is None


def test_win_rate_normal_and_empty():
    assert win_rate(3, 10) == 30.0
    assert win_rate(10, 10) == 100.0
    assert win_rate(0, 10) == 0.0
    assert win_rate(0, 0) is None  # never display 0% for no trades


def test_average_winner_and_loser():
    assert average_winner([100, 200, 300]) == 200.0
    assert average_loser([-100, -300]) == -200.0
    assert average_winner([-100, 0]) is None  # no winners
    assert average_loser([100, 0]) is None  # no losers
    assert average_winner([]) is None
    assert average_loser([]) is None


def test_profit_factor():
    assert profit_factor([100, 200, -50, -150]) == pytest.approx(300 / 200, abs=1e-4)
    assert profit_factor([100, 50]) is None  # no losses -> never Infinity
    assert profit_factor([]) is None
    assert profit_factor([-10]) is None  # no gross profit


def test_expectancy():
    # 2 wins @200, 2 losses @-100, 1 breakeven: 0.4*200 + 0.4*(-100) + 0.2*0 = 40
    assert expectancy([200, 200, -100, -100, 0]) == pytest.approx(40.0, abs=1e-4)
    assert expectancy([100]) == pytest.approx(100.0, abs=1e-4)  # single win
    assert expectancy([-100]) == pytest.approx(-100.0, abs=1e-4)  # single loss
    assert expectancy([]) is None


def test_largest_winner_loser():
    assert largest_winner([100, 500, -50]) == 500.0
    assert largest_loser([100, 500, -50, -900]) == -900.0
    assert largest_winner([]) is None
    assert largest_loser([]) is None


def test_streaks_current_and_max():
    s = streaks(["WIN", "WIN", "LOSS", "WIN", "WIN", "WIN"])
    assert s == {
        "current_win_streak": 3,
        "current_loss_streak": 0,
        "max_win_streak": 3,
        "max_loss_streak": 1,
    }
    s2 = streaks(["LOSS", "LOSS", "WIN", "LOSS", "LOSS", "LOSS"])
    assert s2["current_loss_streak"] == 3
    assert s2["max_loss_streak"] == 3
    assert s2["max_win_streak"] == 1
    assert streaks([])["current_win_streak"] == 0


def test_streaks_breakeven_breaks_runs():
    s = streaks(["WIN", "WIN", "BREAKEVEN", "WIN"])
    assert s["max_win_streak"] == 2  # breakeven broke the run
    assert s["current_win_streak"] == 1  # trailing win after breakeven
    s2 = streaks(["WIN", "BREAKEVEN"])
    assert s2["current_win_streak"] == 0  # breakeven ends the current streak
    assert s2["current_loss_streak"] == 0


def test_holding_duration_seconds():
    entry = datetime(2026, 8, 16, 9, 30, tzinfo=timezone.utc)
    exit_ = entry + timedelta(hours=2, minutes=14)
    assert holding_duration_seconds(entry, exit_) == pytest.approx(2 * 3600 + 14 * 60)
    assert holding_duration_seconds(None, exit_) is None
    assert holding_duration_seconds(entry, None) is None
    # negative (bad data) -> None, never a fabricated duration
    assert holding_duration_seconds(exit_, entry) is None
    # naive datetimes (SQLite) treated as UTC
    naive = datetime(2026, 8, 16, 9, 30)
    assert holding_duration_seconds(naive, naive + timedelta(minutes=5)) == 300.0


def test_duration_stats():
    stats = duration_stats([3600, 7200, 10800])
    assert stats["average_holding_duration"] == 7200.0
    assert stats["median_holding_duration"] == 7200.0
    assert stats["shortest_holding_duration"] == 3600.0
    assert stats["longest_holding_duration"] == 10800.0
    empty = duration_stats([])
    assert all(v is None for v in empty.values())


def test_format_duration():
    assert format_duration(30) == "30s"
    assert format_duration(45 * 60) == "45m"
    assert format_duration(2 * 3600 + 14 * 60) == "2h 14m"
    assert format_duration(3 * 86400 + 4 * 3600) == "3d 4h"
    assert format_duration(None) is None


# =============================================================================
# Equity curve / drawdown / daily P&L / grouping
# =============================================================================


def _trades(pnls, dates):
    out = []
    for pnl, date in zip(pnls, dates):
        out.append(
            {
                "exit_date": date,
                "realized_pnl": pnl,
                "strategy": "Long Call",
                "exit_at": datetime.fromisoformat(f"{date}T10:00:00+00:00"),
                "entry_at": datetime.fromisoformat(f"{date}T09:30:00+00:00"),
            }
        )
    return out


def test_equity_curve_realized_only():
    curve = equity_curve(500000, _trades([1000, -400, 900], ["2026-08-14", "2026-08-15", "2026-08-18"]))
    assert curve[0] == {"date": "2026-08-14", "pnl": 0.0, "cumulative_pnl": 0.0, "equity": 500000.0}
    assert curve[1]["equity"] == 501000.0
    assert curve[2]["equity"] == 500600.0
    assert curve[3]["equity"] == 501500.0
    assert curve[3]["cumulative_pnl"] == 1500.0
    assert equity_curve(500000, []) == []


def test_drawdown_current_and_max():
    curve = [
        {"date": "d1", "equity": 100000},
        {"date": "d2", "equity": 120000},
        {"date": "d3", "equity": 90000},
        {"date": "d4", "equity": 110000},
        {"date": "d5", "equity": 105000},
    ]
    dd = drawdown(curve)
    assert dd["max_drawdown"] == pytest.approx(-30000.0)
    assert dd["max_drawdown_pct"] == pytest.approx(-25.0)
    assert dd["current_drawdown"] == pytest.approx(-15000.0)
    assert dd["current_drawdown_pct"] == pytest.approx(-12.5)
    empty = drawdown([])
    assert all(v is None for v in empty.values())


def test_daily_pnl_groups_by_date():
    rows = daily_pnl(_trades([100, 50, -30], ["2026-08-14", "2026-08-14", "2026-08-15"]))
    assert rows[0]["date"] == "2026-08-14"
    assert rows[0]["realized_pnl"] == 150.0
    assert rows[0]["unrealized_pnl"] is None  # historical marks never stored
    assert rows[0]["total_pnl"] == 150.0
    assert rows[1]["realized_pnl"] == -30.0


def test_strategy_grouping_one_row_per_strategy():
    trades = _trades([100, 200, -50], ["2026-08-14", "2026-08-15", "2026-08-16"])
    trades[0]["strategy"] = "Long Call"
    trades[1]["strategy"] = "Long Call"
    trades[2]["strategy"] = "Iron Condor"
    rows = strategy_grouping(trades)
    by_name = {r["strategy"]: r for r in rows}
    assert set(by_name) == {"Long Call", "Iron Condor"}
    assert by_name["Long Call"]["trades"] == 2
    assert by_name["Long Call"]["wins"] == 2
    assert by_name["Long Call"]["win_rate"] == 100.0
    assert by_name["Long Call"]["total_pnl"] == 300.0
    assert by_name["Long Call"]["average_pnl"] == 150.0
    assert by_name["Iron Condor"]["profit_factor"] is None  # no wins
    assert rows[0]["strategy"] == "Long Call"  # sorted by total P&L desc


# =============================================================================
# API integration — portfolio summary
# =============================================================================


def test_summary_before_any_trade(client, logged_in):
    body = get_analytics(client, logged_in).json()
    summary = body["summary"]
    assert summary["starting_capital"] == 500000
    assert summary["available_cash"] == 500000
    assert summary["realized_pnl"] == 0
    assert summary["unrealized_pnl"] is None  # never 0 for unavailable
    assert summary["total_pnl"] == 0
    assert summary["return_pct"] == 0.0
    assert summary["open_position_count"] == 0
    assert body["data_quality"]["completed_trades"] == "none"


def test_summary_after_trades_and_exits(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, single_leg_payload())  # entry @125.25
    chain_quotes[EXPIRY][24350]["call"] = 100.0
    close_all_positions(client, logged_in, db_session)  # exit at 100.0

    body = get_analytics(client, logged_in).json()
    summary = body["summary"]
    # Bought @125.25, exited @100.0 -> realized (100-125.25)*1*65 = -1641.25
    assert summary["realized_pnl"] == pytest.approx(-1641.25)
    assert summary["unrealized_pnl"] is None
    assert summary["total_pnl"] == pytest.approx(-1641.25)
    assert summary["return_pct"] == pytest.approx(round(-1641.25 / 500000 * 100, 2))
    assert summary["available_cash"] == pytest.approx(500000 - 125.25 * LOT + 100.0 * LOT)
    assert summary["open_position_count"] == 0


def test_summary_with_open_positions(client, logged_in):
    execute(client, logged_in, spread_payload())
    body = get_analytics(client, logged_in).json()
    summary = body["summary"]
    assert summary["open_position_count"] == 2
    assert summary["open_strategy_count"] == 1
    assert summary["invested_value"] == pytest.approx(125.25 * LOT + 35.60 * LOT)
    assert summary["unrealized_pnl"] is None  # marks are a frontend concern
    assert body["data_quality"]["current_marks"] == "unavailable"


# =============================================================================
# Trade classification & counting
# =============================================================================


def test_win_loss_breakeven_classification(client, logged_in, db_session, chain_quotes):
    # WIN: 24350 entry @125.25, exit @140
    execute(client, logged_in, single_leg_payload(strategy_tag="Winner"))
    chain_quotes[EXPIRY][24350]["call"] = 140.0
    close_all_positions(client, logged_in, db_session)

    # LOSS: 24550 entry @35.60, exit @20
    execute(client, logged_in, single_leg_payload(strategy_tag="Loser", legs=[{
        "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24550,
        "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
    }]))
    chain_quotes[EXPIRY][24550]["call"] = 20.0
    close_all_positions(client, logged_in, db_session)

    # BREAKEVEN: 25000 entry @200, exit @200
    execute(client, logged_in, single_leg_payload(strategy_tag="Flat", legs=[{
        "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 25000,
        "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
    }]))
    close_all_positions(client, logged_in, db_session)

    body = get_analytics(client, logged_in).json()
    perf = body["performance"]
    assert perf["total_completed_trades"] == 3
    assert perf["winning_trades"] == 1
    assert perf["losing_trades"] == 1
    assert perf["breakeven_trades"] == 1
    results = {j["strategy"]: j["result"] for j in body["journal"]}
    assert results == {"Winner": "WIN", "Loser": "LOSS", "Flat": "BREAKEVEN"}


def test_incomplete_trade_excluded_open_leg(client, logged_in, db_session):
    execute(client, logged_in, spread_payload())
    # Exit only the 24350 leg; the 24550 leg stays open.
    pid = open_position_ids(db_session)[0]
    exit_position(client, logged_in, pid, {"client_order_id": next_id("exit")})
    body = get_analytics(client, logged_in).json()
    assert body["performance"]["total_completed_trades"] == 0  # strategy still running
    assert body["summary"]["open_position_count"] == 1


# =============================================================================
# Win rate / averages / profit factor / expectancy via API
# =============================================================================


# Entry prices from DEFAULT_CHAIN: 24350 CE=125.25, 24550 CE=35.60, 25000 CE=200.
# Each spec uses a DIFFERENT strike so every execution owns its own position row
# (same-instrument fills net into one row and would collapse into a single trade).
def _seed_trades(client, logged_in, db_session, chain_quotes, specs):
    """Creates completed single-leg trades. ``specs`` = [(strike, exit_price)]."""
    for strike, exit_price in specs:
        execute(client, logged_in, single_leg_payload(legs=[{
            "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": strike,
            "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
        }]))
        chain_quotes[EXPIRY][strike]["call"] = exit_price
        close_all_positions(client, logged_in, db_session)


def test_win_rate_via_api(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 150.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["total_completed_trades"] == 3
    assert perf["winning_trades"] == 2
    assert perf["losing_trades"] == 1
    assert perf["win_rate"] == pytest.approx(66.67, abs=0.01)


def test_win_rate_no_completed_trades(client, logged_in):
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["total_completed_trades"] == 0
    assert perf["win_rate"] is None  # not 0%


def test_win_rate_all_wins(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 205.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["win_rate"] == 100.0
    assert perf["winning_trades"] == 3
    assert perf["profit_factor"] is None  # no losses -> never Infinity


def test_win_rate_all_losses(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 100.0), (24550, 30.0), (25000, 150.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["win_rate"] == 0.0
    assert perf["winning_trades"] == 0
    assert perf["average_winner"] is None  # no winners


def test_average_winner_loser_via_api(client, logged_in, db_session, chain_quotes):
    # Wins: 24350 (+14.75/lot), 24550 (+9.40/lot); Loss: 25000 (-50/lot)
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 150.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["average_winner"] == pytest.approx((14.75 + 9.40) / 2 * LOT, abs=0.01)
    assert perf["average_loser"] == pytest.approx(-50.0 * LOT, abs=0.01)
    assert perf["largest_winner"] == pytest.approx(14.75 * LOT, abs=0.01)
    assert perf["largest_loser"] == pytest.approx(-50.0 * LOT, abs=0.01)


def test_profit_factor_and_expectancy_via_api(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 150.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    gross_profit = (14.75 + 9.40) * LOT
    gross_loss = 50.0 * LOT
    assert perf["profit_factor"] == pytest.approx(gross_profit / gross_loss, abs=1e-4)
    expected = (2 / 3) * ((14.75 + 9.40) / 2 * LOT) + (1 / 3) * (-50.0 * LOT)
    assert perf["expectancy"] == pytest.approx(expected, abs=0.01)


def test_profit_factor_no_losses_via_api(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 205.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["profit_factor"] is None  # never Infinity


# =============================================================================
# Streaks / duration / drawdown via API
# =============================================================================


def test_streaks_via_api(client, logged_in, db_session, chain_quotes):
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 45.0), (25000, 150.0)])
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["current_win_streak"] == 0  # chronological order: win, win, loss
    assert perf["current_loss_streak"] == 1
    assert perf["max_win_streak"] == 2
    assert perf["max_loss_streak"] == 1


def test_holding_duration_via_api(client, logged_in, db_session):
    from app.models import StrategyExecution

    execute(client, logged_in, single_leg_payload())
    close_all_positions(client, logged_in, db_session)
    # Backdate the entry so a real duration exists (execution + exit happen
    # within the same second in tests otherwise).
    ex = db_session.query(StrategyExecution).first()
    ex.entry_at = ex.entry_at - timedelta(hours=2)
    db_session.commit()

    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["average_holding_duration"] == pytest.approx(7200.0, abs=5)
    assert perf["median_holding_duration"] == pytest.approx(7200.0, abs=5)
    assert perf["shortest_holding_duration"] == pytest.approx(7200.0, abs=5)
    assert perf["longest_holding_duration"] == pytest.approx(7200.0, abs=5)
    journal = get_analytics(client, logged_in).json()["journal"]
    assert journal[0]["duration_label"] == "2h 0m"


def test_open_trade_excluded_from_duration(client, logged_in):
    execute(client, logged_in, single_leg_payload())  # still open
    perf = get_analytics(client, logged_in).json()["performance"]
    assert perf["total_completed_trades"] == 0
    assert perf["average_holding_duration"] is None


def test_drawdown_via_api(client, logged_in, db_session, chain_quotes):
    # t1: 24350 +14.75/lot win; t2: 24550 -15.60/lot loss; t3: 25000 +5/lot win
    _seed_trades(client, logged_in, db_session, chain_quotes, [(24350, 140.0), (24550, 20.0), (25000, 205.0)])
    body = get_analytics(client, logged_in).json()
    dd = body["drawdown"]
    assert dd["max_drawdown"] == pytest.approx(-15.60 * LOT, abs=0.01)
    # Current drawdown = last equity − peak equity (peak was after trade 1).
    assert dd["current_drawdown"] == pytest.approx((4.15 - 14.75) * LOT, abs=0.01)
    assert body["equity_curve"][0]["equity"] == 500000.0
    assert body["equity_curve"][-1]["equity"] == pytest.approx(500000 + (14.75 - 15.60 + 5.0) * LOT)
    assert body["data_quality"]["historical_unrealized"] == "unavailable"


# =============================================================================
# Strategy grouping / journal
# =============================================================================


def test_multi_leg_strategy_is_one_journal_row(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, spread_payload())  # Bull Call Spread, 2 legs
    # 24350 long exits at 150 (+24.75/lot); 24550 short exits at 30 (+5.60/lot).
    chain_quotes[EXPIRY][24350]["call"] = 150.0
    chain_quotes[EXPIRY][24550]["call"] = 30.0
    close_all_positions(client, logged_in, db_session)

    body = get_analytics(client, logged_in).json()
    perf = body["performance"]
    assert perf["total_completed_trades"] == 1  # ONE strategy trade, not 2 legs
    assert len(body["journal"]) == 1
    row = body["journal"][0]
    assert row["strategy"] == "Bull Call Spread"
    assert len(row["legs"]) == 2  # legs ride underneath the grouped trade
    assert {l["action"] for l in row["legs"]} == {"buy", "sell"}
    # Grouped realized = both positions' realizations.
    assert row["realized_pnl"] == pytest.approx((24.75 + 5.60) * LOT, abs=0.01)
    assert row["result"] == "WIN"


def test_strategy_groups_multiple_strategies(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, single_leg_payload(strategy_tag="Long Call"))  # 24350 @125.25
    chain_quotes[EXPIRY][24350]["call"] = 140.0
    close_all_positions(client, logged_in, db_session)

    execute(client, logged_in, single_leg_payload(strategy_tag="Iron Condor", legs=[{
        "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24550,
        "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
    }]))  # 24550 @35.60
    chain_quotes[EXPIRY][24550]["call"] = 30.0
    close_all_positions(client, logged_in, db_session)

    strategies = get_analytics(client, logged_in).json()["strategies"]
    by_name = {s["strategy"]: s for s in strategies}
    assert set(by_name) == {"Long Call", "Iron Condor"}
    assert by_name["Long Call"]["win_rate"] == 100.0
    assert by_name["Iron Condor"]["win_rate"] == 0.0
    assert by_name["Iron Condor"]["profit_factor"] is None  # no wins
    assert strategies[0]["strategy"] == "Long Call"  # sorted by P&L desc


# =============================================================================
# Positions / exposure / data quality / isolation / filters
# =============================================================================


def test_position_analytics_exposure(client, logged_in):
    execute(client, logged_in, spread_payload())  # long 24350, short 24550
    body = get_analytics(client, logged_in).json()
    positions = body["positions"]
    assert positions["long_exposure"] == pytest.approx(125.25 * LOT, abs=0.01)
    assert positions["short_exposure"] == pytest.approx(35.60 * LOT, abs=0.01)
    assert positions["total_exposure"] == pytest.approx((125.25 + 35.60) * LOT, abs=0.01)
    assert len(positions["items"]) == 2
    item = positions["items"][0]
    assert item["current_price"] is None  # marks unavailable server-side
    assert item["unrealized_pnl"] is None
    assert item["market_value"] is None
    assert item["strategy_execution_id"] is not None


def test_position_analytics_zero_exposure(client, logged_in):
    body = get_analytics(client, logged_in).json()
    positions = body["positions"]
    assert positions["long_exposure"] == 0
    assert positions["short_exposure"] == 0
    assert positions["items"] == []


def test_data_quality_marks_and_history(client, logged_in):
    body = get_analytics(client, logged_in).json()
    assert body["data_quality"]["current_marks"] == "unavailable"
    assert body["data_quality"]["historical_unrealized"] == "unavailable"
    assert body["data_quality"]["completed_trades"] == "none"


def test_data_quality_inconsistent_warning(client, logged_in, db_session):
    from app.models import PaperTransaction

    execute(client, logged_in, single_leg_payload())
    close_all_positions(client, logged_in, db_session)
    txn = db_session.query(PaperTransaction).first()
    db_session.delete(txn)
    db_session.commit()

    body = get_analytics(client, logged_in).json()
    codes = [w["code"] for w in body["data_quality"]["warnings"]]
    assert "PORTFOLIO_DATA_INCONSISTENT" in codes


def test_user_isolation(client, db_session):
    session_a, user_a = create_test_identity(db_session, "tok-user-a")
    execute(client, session_a, single_leg_payload(strategy_tag="UserA"))
    close_all_positions(client, session_a, db_session)

    session_b, user_b = create_test_identity(db_session, "tok-user-b")
    body = get_analytics(client, session_b).json()
    assert body["performance"]["total_completed_trades"] == 0
    assert body["journal"] == []
    assert body["summary"]["available_cash"] == 500000


def test_analytics_requires_login(client):
    assert client.get("/paper/analytics").status_code == 401


def test_filters_strategy_and_dates(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, single_leg_payload(strategy_tag="Alpha"))  # 24350 @125.25
    chain_quotes[EXPIRY][24350]["call"] = 140.0
    close_all_positions(client, logged_in, db_session)

    execute(client, logged_in, single_leg_payload(strategy_tag="Beta", legs=[{
        "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24550,
        "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
    }]))  # 24550 @35.60
    chain_quotes[EXPIRY][24550]["call"] = 30.0
    close_all_positions(client, logged_in, db_session)

    body = get_analytics(client, logged_in).json()
    assert body["performance"]["total_completed_trades"] == 2

    filtered = get_analytics(client, logged_in, {"strategy": "alpha"}).json()
    assert filtered["performance"]["total_completed_trades"] == 1
    assert filtered["journal"][0]["strategy"] == "Alpha"

    # date filter: everything happened today, so a tomorrow range yields none
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    dated = get_analytics(client, logged_in, {"date_from": tomorrow}).json()
    assert dated["performance"]["total_completed_trades"] == 0
    assert dated["data_quality"]["completed_trades"] == "none"
