import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.services import token_store


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
def logged_in(client):
    return token_store.set_token("tok-xyz")


def headers(session_id):
    return {"X-Session-Id": session_id}


# Bear call spread: sell 25000 CE @ 200, buy 25100 CE @ 80 (NIFTY, lot 65).
# Net credit received at entry = (200 - 80) * 65 = 7,800 -> entry_net = -7800.
def spread_order(**overrides):
    payload = {
        "symbol": "NIFTY",
        "strategy_tag": "Bear Call Spread",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY",
                "expiration_date": "2026-08-27",
                "strike_price": 25000,
                "option_type": "call",
                "action": "sell",
                "premium": 200.0,
                "quantity": 1,
                "lot_size": 65,
            },
            {
                "symbol": "NIFTY",
                "expiration_date": "2026-08-27",
                "strike_price": 25100,
                "option_type": "call",
                "action": "buy",
                "premium": 80.0,
                "quantity": 1,
                "lot_size": 65,
            },
        ],
    }
    payload.update(overrides)
    return payload


def single_leg_order(**overrides):
    payload = {
        "symbol": "NIFTY",
        "strategy_tag": "Long Call",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY",
                "expiration_date": "2026-08-27",
                "strike_price": 26000,
                "option_type": "call",
                "action": "buy",
                "premium": 100.0,
                "quantity": 1,
                "lot_size": 65,
            }
        ],
    }
    payload.update(overrides)
    return payload


def fill(client, session_id, order):
    return client.post("/paper/fills", headers=headers(session_id), json=order)


def close_leg(client, session_id, trade_id, leg_id, exit_price):
    return client.post(
        f"/paper/trades/{trade_id}/legs/{leg_id}/close",
        headers=headers(session_id),
        json={"exit_price": exit_price},
    )


# ---------- handlePaperOrderFill controller ----------


def test_handlePaperOrderFill_inserts_trade_and_legs(db_session):
    from app.models import Leg, Trade
    from app.schemas import OrderFillIn
    from app.services.journal import handlePaperOrderFill

    order = OrderFillIn(**spread_order())
    trade = handlePaperOrderFill("user-1", order, db_session)

    assert trade.symbol == "NIFTY"
    assert trade.strategy_tag == "Bear Call Spread"
    assert trade.status == "open"
    assert trade.entry_net == -7800.0  # net credit received for the spread
    assert trade.realized_pnl is None
    assert len(trade.legs) == 2
    assert db_session.query(Trade).count() == 1
    assert db_session.query(Leg).count() == 2
    assert [l.action for l in trade.legs] == ["sell", "buy"]


def test_handlePaperOrderFill_net_debit_for_long_spread(db_session):
    from app.schemas import OrderFillIn
    from app.services.journal import handlePaperOrderFill

    # Long call spread (debit): buy 25000 CE @ 200, sell 25100 CE @ 80.
    order = OrderFillIn(**spread_order(strategy_tag="Bull Call Spread"))
    order.legs[0].action = "buy"
    order.legs[1].action = "sell"
    trade = handlePaperOrderFill("user-1", order, db_session)

    assert trade.entry_net == 7800.0  # net debit paid


# ---------- API: fills ----------


def test_fill_requires_login(client):
    resp = client.post("/paper/fills", json=spread_order())
    assert resp.status_code == 401
    assert "Not logged in" in resp.json()["detail"]


def test_fill_rejects_empty_legs(client, logged_in):
    resp = fill(client, logged_in, {**spread_order(), "legs": []})
    assert resp.status_code == 422


def test_fill_creates_trade_and_legs(client, logged_in):
    resp = fill(client, logged_in, spread_order())

    assert resp.status_code == 201
    body = resp.json()
    assert body["symbol"] == "NIFTY"
    assert body["strategy_tag"] == "Bear Call Spread"
    assert body["status"] == "open"
    assert body["entry_net"] == -7800.0
    assert body["realized_pnl"] is None
    assert len(body["legs"]) == 2
    assert [l["action"] for l in body["legs"]] == ["sell", "buy"]
    assert body["legs"][0]["strike_price"] == 25000
    assert body["legs"][0]["premium"] == 200.0


# ---------- API: closing (multi-leg net credit/debit math) ----------


def test_close_partial_then_full_spread(client, logged_in):
    trade = fill(client, logged_in, spread_order()).json()
    trade_id = trade["id"]
    sell_leg, buy_leg = trade["legs"][0]["id"], trade["legs"][1]["id"]

    # Close only the short leg: buy it back @ 50 -> realized +150*65 = +9750.
    resp = close_leg(client, logged_in, trade_id, sell_leg, 50.0)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "open"
    assert body["realized_pnl"] is None
    assert body["legs"][0]["realized_pnl"] == 9750.0
    assert body["legs"][1]["exit_price"] is None

    # Close the long leg @ 30 -> realized -50*65 = -3250; trade closes.
    resp = close_leg(client, logged_in, trade_id, buy_leg, 30.0)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "closed"
    assert body["exit_at"] is not None
    assert body["realized_pnl"] == 6500.0  # 9750 - 3250
    assert body["legs"][1]["realized_pnl"] == -3250.0


def test_close_trade_twice_returns_400(client, logged_in):
    trade = fill(client, logged_in, single_leg_order()).json()
    leg_id = trade["legs"][0]["id"]

    assert close_leg(client, logged_in, trade["id"], leg_id, 50.0).status_code == 200
    resp = close_leg(client, logged_in, trade["id"], leg_id, 40.0)
    assert resp.status_code == 400
    assert "already closed" in resp.json()["detail"]


def test_close_unknown_trade_returns_404(client, logged_in):
    resp = close_leg(client, logged_in, 99999, 1, 50.0)
    assert resp.status_code == 404


def test_close_leg_of_another_session_returns_404(client):
    session_a = token_store.set_token("tok-a")
    trade = fill(client, session_a, single_leg_order()).json()

    session_b = token_store.set_token("tok-b")  # replaces the active session
    resp = close_leg(client, session_b, trade["id"], trade["legs"][0]["id"], 50.0)
    assert resp.status_code == 404


# ---------- Journal: account, win rate, profit factor ----------


def test_journal_requires_login(client):
    resp = client.get("/paper/journal")
    assert resp.status_code == 401


def test_journal_empty(client, logged_in):
    resp = client.get("/paper/journal", headers=headers(logged_in))
    assert resp.status_code == 200
    body = resp.json()
    assert body["account"] == {
        "starting_capital": 500000,
        "balance": 500000,
        "net_pnl": 0.0,
    }
    assert body["stats"]["total_trades"] == 0
    assert body["stats"]["win_rate"] is None
    assert body["stats"]["profit_factor"] is None
    assert body["trades"] == []


def test_journal_stats_win_rate_and_profit_factor(client, logged_in):
    # Winning spread: +6500 (closed above).
    trade = fill(client, logged_in, spread_order()).json()
    sell_leg, buy_leg = trade["legs"][0]["id"], trade["legs"][1]["id"]
    close_leg(client, logged_in, trade["id"], sell_leg, 50.0)
    close_leg(client, logged_in, trade["id"], buy_leg, 30.0)

    # Losing long call: buy @ 100, exit @ 80 -> -20*65 = -1300.
    trade2 = fill(client, logged_in, single_leg_order()).json()
    close_leg(client, logged_in, trade2["id"], trade2["legs"][0]["id"], 80.0)

    resp = client.get("/paper/journal", headers=headers(logged_in))
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"] == {
        "total_trades": 2,
        "open_trades": 0,
        "closed_trades": 2,
        "wins": 1,
        "win_rate": 0.5,
        "profit_factor": 5.0,  # 6500 / 1300
        "gross_profit": 6500.0,
        "gross_loss": 1300.0,
    }
    assert body["account"]["net_pnl"] == 5200.0
    assert body["account"]["balance"] == 505200.0

    # Newest trade first; both carry their legs and a status.
    assert [t["strategy_tag"] for t in body["trades"]] == ["Long Call", "Bear Call Spread"]
    assert body["trades"][1]["status"] == "closed"
    assert len(body["trades"][1]["legs"]) == 2


def test_journal_counts_open_trades_and_skips_them_in_stats(client, logged_in):
    fill(client, logged_in, spread_order())  # stays open

    resp = client.get("/paper/journal", headers=headers(logged_in))
    body = resp.json()

    assert body["stats"]["total_trades"] == 1
    assert body["stats"]["open_trades"] == 1
    assert body["stats"]["closed_trades"] == 0
    assert body["stats"]["win_rate"] is None
    assert body["stats"]["profit_factor"] is None
    assert body["account"]["net_pnl"] == 0.0
    assert body["trades"][0]["status"] == "open"
    assert body["trades"][0]["realized_pnl"] is None


def test_journal_profit_factor_none_when_no_losses(client, logged_in):
    trade = fill(client, logged_in, spread_order()).json()
    close_leg(client, logged_in, trade["id"], trade["legs"][0]["id"], 50.0)
    close_leg(client, logged_in, trade["id"], trade["legs"][1]["id"], 30.0)

    resp = client.get("/paper/journal", headers=headers(logged_in))
    body = resp.json()

    assert body["stats"]["wins"] == 1
    assert body["stats"]["win_rate"] == 1.0
    assert body["stats"]["profit_factor"] is None  # no losing trades yet
    assert body["stats"]["gross_loss"] == 0.0
    assert body["account"]["net_pnl"] == 6500.0
