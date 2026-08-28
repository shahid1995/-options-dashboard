"""Phase 5.2 tests — bulk paper position exit (EXIT STRATEGY + EXIT ALL).

Covers the spec's §27 matrix: single-position exit unchanged, exit entire
strategy, exit entire account, multiple strategies, standalone positions, no
positions, market closed/unknown, missing chain/quote, idempotent replay,
duplicate Exit All, concurrent individual + bulk exit, cash ledger
correctness, realized P&L correctness, journal correctness, strategy
completion correctness, user isolation, partial execution reporting and
refresh/reconciliation consistency.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.routers.paper import MARKET_CLOSED_MSG, MARKET_UNKNOWN_MSG
from app.services import token_store
from tests.test_helpers import create_test_identity

LOT = 65
EXPIRY = "2026-08-27"
EXPIRY2 = "2026-09-03"

DEFAULT_CHAIN = {
    EXPIRY: {
        24350: {"call": 125.25, "put": 90.0},
        24550: {"call": 35.60, "put": 200.0},
        25000: {"call": 200.0, "put": 80.0},
    },
    EXPIRY2: {
        24350: {"call": 130.0, "put": 95.0},
        24400: {"call": 105.0, "put": 85.0},
    },
}


def chain_payload(expiry: str, quotes: dict) -> dict:
    data = []
    for strike, sides in quotes.items():
        item = {"strike_price": strike, "underlying_spot_price": 24000.0}
        item["call_options"] = {"market_data": {"ltp": sides["call"]}, "option_greeks": {}}
        item["put_options"] = {"market_data": {"ltp": sides["put"]}, "option_greeks": {}}
        data.append(item)
    return {"data": data}


@pytest.fixture(autouse=True)
def market_open_gate():
    with gate_status("open"):
        yield


def gate_status(status_value):
    status = SimpleNamespace(
        status=status_value,
        source="test",
        trade_date="2026-08-14",
        checked_at="2026-08-14T10:00:00+05:30",
        message=f"test market status: {status_value}",
        error=None,
    )
    return patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=status))


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
    session_id, _ = create_test_identity(db_session, "tok-bulk-exit")
    return session_id


def headers(session_id):
    return {"X-Session-Id": session_id}


# ---- payload builders -------------------------------------------------------


def spread_payload(**overrides):
    payload = {
        "client_order_id": "bulk-exit-spread",
        "symbol": "NIFTY",
        "strategy_tag": "Bull Call Spread",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24350,
                "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
            },
            {
                "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 24550,
                "option_type": "call", "action": "sell", "quantity": 1, "lot_size": LOT,
            },
        ],
    }
    payload.update(overrides)
    return payload


def long_call_payload(**overrides):
    payload = {
        "client_order_id": "bulk-exit-long",
        "symbol": "NIFTY",
        "strategy_tag": "Long Call",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY", "expiration_date": EXPIRY, "strike_price": 25000,
                "option_type": "call", "action": "buy", "quantity": 1, "lot_size": LOT,
            }
        ],
    }
    payload.update(overrides)
    return payload


def long_put_second_expiry_payload(**overrides):
    payload = {
        "client_order_id": "bulk-exit-put2",
        "symbol": "NIFTY",
        "strategy_tag": "Long Put",
        "starting_capital": 500000,
        "legs": [
            {
                "symbol": "NIFTY", "expiration_date": EXPIRY2, "strike_price": 24400,
                "option_type": "put", "action": "buy", "quantity": 1, "lot_size": LOT,
            }
        ],
    }
    payload.update(overrides)
    return payload


def execute(client, session_id, payload):
    return client.post("/paper/executions", headers=headers(session_id), json=payload)


def exit_strategy(client, session_id, execution_id, payload):
    return client.post(
        f"/paper/executions/{execution_id}/exit-all", headers=headers(session_id), json=payload
    )


def exit_all(client, session_id, payload):
    return client.post("/paper/positions/exit-all", headers=headers(session_id), json=payload)


def exit_one(client, session_id, position_id, payload):
    return client.post(
        f"/paper/positions/{position_id}/exit", headers=headers(session_id), json=payload
    )


def all_positions(db_session):
    from app.models import Position

    return db_session.query(Position).order_by(Position.id).all()


def open_positions(db_session):
    from app.models import Position

    return db_session.query(Position).filter(Position.status == "open").all()


def count_exit_orders(db_session):
    from app.models import PaperOrder

    return db_session.query(PaperOrder).filter(PaperOrder.kind == "exit").count()


def count_exit_txns(db_session):
    from app.models import PaperTransaction

    return db_session.query(PaperTransaction).filter(PaperTransaction.type.like("EXIT_%")).count()


# ---- 1. Single-position exit unchanged ---------------------------------------


def test_single_position_exit_endpoint_unchanged(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, long_call_payload())  # 25000 CE enters at 200.00
    pos = all_positions(db_session)[0]
    chain_quotes[EXPIRY][25000]["call"] = 135.0  # market moved down
    resp = exit_one(client, logged_in, pos.id, {"client_order_id": "bulk-single-exit", "quantity": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["duplicated"] is False
    assert body["position"]["status"] == "closed"
    assert body["order"]["realized_pnl"] == pytest.approx((135.0 - 200.0) * LOT, abs=0.01)


# ---- 2. EXIT STRATEGY ---------------------------------------------------------


def test_exit_strategy_closes_every_leg_of_one_execution(client, logged_in, db_session):
    from app.models import StrategyExecution

    resp = execute(client, logged_in, spread_payload())
    exec_id = resp.json()["execution_id"]
    assert len(open_positions(db_session)) == 2

    out = exit_strategy(
        client, logged_in, exec_id, {"client_order_id": "bulk-exit-strat-1"}
    )
    assert out.status_code == 200
    body = out.json()
    assert body["scope"] == "STRATEGY"
    assert body["status"] == "SUCCESS"
    assert body["requested_count"] == 2
    assert body["exited_count"] == 2
    assert body["failed_count"] == 0
    assert body["total_realized_pnl"] == 0.0  # flat exit at entry prices
    assert len(body["positions"]) == 2
    assert all(p["status"] == "EXITED" for p in body["positions"])
    assert len(body["groups"]) == 1
    assert body["groups"][0]["strategy_tag"] == "Bull Call Spread"
    assert body["groups"][0]["exited"] == 2

    assert len(open_positions(db_session)) == 0
    execution = db_session.query(StrategyExecution).filter_by(execution_id=exec_id).first()
    assert execution.exit_at is not None  # strategy fully closed


def test_exit_strategy_does_not_touch_other_strategies(client, logged_in, db_session):
    spread = execute(client, logged_in, spread_payload()).json()["execution_id"]
    execute(client, logged_in, long_call_payload(client_order_id="bulk-other-1"))

    body = exit_strategy(
        client, logged_in, spread, {"client_order_id": "bulk-exit-strat-scope"}
    ).json()
    assert body["status"] == "SUCCESS"
    assert body["exited_count"] == 2
    # The Long Call execution is untouched.
    remaining = open_positions(db_session)
    assert len(remaining) == 1
    assert remaining[0].strategy_execution_id != spread


def test_exit_strategy_standalone_single_leg(client, logged_in, db_session):
    resp = execute(client, logged_in, long_call_payload())
    exec_id = resp.json()["execution_id"]
    body = exit_strategy(
        client, logged_in, exec_id, {"client_order_id": "bulk-exit-strat-standalone"}
    ).json()
    assert body["status"] == "SUCCESS"
    assert body["exited_count"] == 1
    assert len(open_positions(db_session)) == 0


def test_exit_strategy_unknown_execution_404(client, logged_in):
    resp = exit_strategy(
        client, logged_in, "no-such-execution", {"client_order_id": "bulk-exit-404"}
    )
    assert resp.status_code == 404


# ---- 3/4/5. EXIT ALL — account-wide -------------------------------------------


def test_exit_all_closes_multiple_strategies_and_groups_them(client, logged_in, db_session):
    execute(client, logged_in, spread_payload())  # 2 positions, EXPIRY
    execute(client, logged_in, long_call_payload(client_order_id="bulk-all-long"))  # 1 position
    execute(client, logged_in, long_put_second_expiry_payload())  # 1 position, EXPIRY2
    assert len(open_positions(db_session)) == 4

    resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-all-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "ACCOUNT"
    assert body["status"] == "SUCCESS"
    assert body["requested_count"] == 4
    assert body["exited_count"] == 4
    assert body["failed_count"] == 0
    assert len(body["groups"]) == 3
    tags = sorted(g["strategy_tag"] for g in body["groups"])
    assert tags == ["Bull Call Spread", "Long Call", "Long Put"]
    assert len(open_positions(db_session)) == 0


def test_exit_all_uses_each_positions_own_expiry_chain(client, logged_in, db_session):
    """Positions across expiries exit at THEIR chain's price (Phase 2.1 rule)."""
    execute(client, logged_in, long_call_payload())  # EXPIRY: 25000 CE @ 200.00
    execute(client, logged_in, long_put_second_expiry_payload())  # EXPIRY2: 24400 PE @ 85.00
    body = exit_all(client, logged_in, {"client_order_id": "bulk-exit-all-multi-expiry"}).json()
    assert body["status"] == "SUCCESS"
    fills = {p["symbol"] + p["expiry"]: p["fill_price"] for p in body["positions"]}
    assert fills[f"NIFTY{EXPIRY}"] == 200.0
    assert fills[f"NIFTY{EXPIRY2}"] == 85.0


# ---- 6. No positions ----------------------------------------------------------


def test_exit_all_no_positions(client, logged_in):
    resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-none"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_POSITIONS"
    assert body["requested_count"] == 0
    assert body["exited_count"] == 0
    assert body["positions"] == []


# ---- 7/8. Market gate ---------------------------------------------------------


def test_exit_all_rejected_when_market_closed(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    with gate_status("closed"):
        resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-closed"})
    assert resp.status_code == 409
    assert MARKET_CLOSED_MSG in resp.json()["detail"]
    assert len(open_positions(db_session)) == 1  # nothing was closed


def test_exit_all_rejected_when_market_unknown(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    with gate_status("unknown"):
        resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-unknown"})
    assert resp.status_code == 409
    assert MARKET_UNKNOWN_MSG in resp.json()["detail"]
    assert len(open_positions(db_session)) == 1


def test_exit_strategy_rejected_when_market_closed(client, logged_in, db_session):
    exec_id = execute(client, logged_in, spread_payload()).json()["execution_id"]
    with gate_status("closed"):
        resp = exit_strategy(
            client, logged_in, exec_id, {"client_order_id": "bulk-exit-strat-closed"}
        )
    assert resp.status_code == 409


# ---- 9/10. Missing chain / quote blocks the WHOLE request ---------------------


def test_exit_all_missing_chain_rejects_before_mutation(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, long_call_payload())
    execute(client, logged_in, long_put_second_expiry_payload())
    chain_quotes[EXPIRY] = {}  # chain gone for EXPIRY
    resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-noc"})
    assert resp.status_code == 409
    assert "BULK_EXIT_CHAIN_DATA_MISSING" in resp.json()["detail"]
    assert len(open_positions(db_session)) == 2  # NO position was closed
    assert count_exit_orders(db_session) == 0


def test_exit_all_missing_quote_rejects_before_mutation(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, long_call_payload())
    execute(client, logged_in, long_put_second_expiry_payload())
    del chain_quotes[EXPIRY][25000]  # the Long Call strike is gone
    resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-noq"})
    assert resp.status_code == 409
    assert "BULK_EXIT_CHAIN_DATA_MISSING" in resp.json()["detail"]
    assert len(open_positions(db_session)) == 2


# ---- 11. Idempotent replay ----------------------------------------------------


def test_exit_all_idempotent_replay(client, logged_in, db_session):
    from app.models import BulkExitRecord, PaperOrder, PaperTransaction, Trade

    execute(client, logged_in, long_call_payload())
    key = "bulk-exit-idem"
    first = exit_all(client, logged_in, {"client_order_id": key})
    assert first.json()["duplicated"] is False

    replay = exit_all(client, logged_in, {"client_order_id": key})
    assert replay.status_code == 200
    body = replay.json()
    assert body["duplicated"] is True
    assert body["execution_id"] == key
    assert body["status"] == "SUCCESS"
    assert body["requested_count"] == 1
    assert body["exited_count"] == 1

    # Nothing was created twice: one bulk record, one exit order, one exit
    # ledger entry, one journal trade (closed), no duplicate realized P&L.
    assert db_session.query(BulkExitRecord).count() == 1
    assert count_exit_orders(db_session) == 1
    assert count_exit_txns(db_session) == 1
    assert db_session.query(Trade).count() == 1
    assert db_session.query(Trade).first().status == "closed"


def test_exit_strategy_idempotent_replay(client, logged_in, db_session):
    from app.models import BulkExitRecord

    exec_id = execute(client, logged_in, spread_payload()).json()["execution_id"]
    key = "bulk-exit-strat-idem"
    first = exit_strategy(client, logged_in, exec_id, {"client_order_id": key})
    assert first.json()["exited_count"] == 2
    replay = exit_strategy(client, logged_in, exec_id, {"client_order_id": key})
    assert replay.json()["duplicated"] is True
    assert replay.json()["exited_count"] == 2
    assert db_session.query(BulkExitRecord).count() == 1
    assert count_exit_orders(db_session) == 2  # exactly the two exits


def test_no_positions_result_is_also_idempotent(client, logged_in, db_session):
    from app.models import BulkExitRecord

    key = "bulk-exit-none-idem"
    first = exit_all(client, logged_in, {"client_order_id": key})
    assert first.json()["status"] == "NO_POSITIONS"
    replay = exit_all(client, logged_in, {"client_order_id": key})
    assert replay.json()["status"] == "NO_POSITIONS"
    assert replay.json()["duplicated"] is True
    assert db_session.query(BulkExitRecord).count() == 1


# ---- 12. Duplicate Exit All (distinct keys) -----------------------------------


def test_second_exit_all_with_new_key_has_nothing_to_close(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    first = exit_all(client, logged_in, {"client_order_id": "bulk-exit-dup-1"})
    assert first.json()["status"] == "SUCCESS"
    second = exit_all(client, logged_in, {"client_order_id": "bulk-exit-dup-2"})
    assert second.json()["status"] == "NO_POSITIONS"
    # No double counting: still one exit order + one exit ledger entry.
    assert count_exit_orders(db_session) == 1
    assert count_exit_txns(db_session) == 1


# ---- 13. Concurrency: individual + bulk ---------------------------------------


def test_individual_exit_then_exit_all_is_no_positions(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    pos = all_positions(db_session)[0]
    resp = exit_one(client, logged_in, pos.id, {"client_order_id": "bulk-race-ind"})
    assert resp.status_code == 200
    body = exit_all(client, logged_in, {"client_order_id": "bulk-race-all"}).json()
    assert body["status"] == "NO_POSITIONS"
    assert count_exit_orders(db_session) == 1  # only the individual exit


def test_exit_all_then_individual_exit_is_rejected(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    pos = all_positions(db_session)[0]
    body = exit_all(client, logged_in, {"client_order_id": "bulk-race-all-first"}).json()
    assert body["status"] == "SUCCESS"
    resp = exit_one(client, logged_in, pos.id, {"client_order_id": "bulk-race-ind-late"})
    assert resp.status_code == 400
    assert "INSUFFICIENT_POSITION" in resp.json()["detail"]
    assert count_exit_orders(db_session) == 1


def test_concurrent_race_reports_partial_with_already_closed(
    client, logged_in, db_session
):
    """A position that loses a genuine execution-time race is reported
    ALREADY_CLOSED; the bulk result is PARTIAL, never a fake full success."""
    from unittest.mock import patch as mock_patch

    from app.services import paper_execution as pe

    execute(client, logged_in, spread_payload(client_order_id="bulk-race-spread"))  # 2 positions
    execute(client, logged_in, long_call_payload(client_order_id="bulk-race-long"))  # 1 position

    real_exit = pe.exit_position
    state = {"raced": False}

    def racing_exit(user_id, position_id, request, db, fill_price, *, commit=True):
        # On the FIRST bulk exit, a concurrent individual exit wins the race
        # for the LAST position before the bulk loop reaches it.
        if not state["raced"]:
            state["raced"] = True
            from app.models import Position

            other = (
                db.query(Position)
                .filter(Position.id != position_id, Position.status == "open")
                .order_by(Position.id.desc())
                .first()
            )
            if other is not None:
                other.status = "closed"
                other.net_quantity = 0
                other.closed_at = pe._now()
                db.flush()
        return real_exit(user_id, position_id, request, db, fill_price, commit=commit)

    with mock_patch.object(pe, "exit_position", new=racing_exit):
        resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-race"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PARTIAL"
    assert body["exited_count"] + body["failed_count"] == body["requested_count"]
    assert body["exited_count"] >= 1
    statuses = {p["status"] for p in body["positions"]}
    assert "ALREADY_CLOSED" in statuses
    assert len(body["errors"]) == body["failed_count"]
    assert all("already closed" in e.lower() for e in body["errors"])
    # Nothing open remains (bulk exited the rest; the raced one was closed).
    assert len(open_positions(db_session)) == 0


# ---- 14. Cash ledger correctness ----------------------------------------------


def test_cash_ledger_exactly_once_per_exit(client, logged_in, db_session, chain_quotes):
    from app.models import PaperAccount, PaperTransaction

    execute(client, logged_in, spread_payload())  # 2 entry txns
    execute(client, logged_in, long_call_payload(client_order_id="bulk-cash-long"))  # 1 entry txn
    chain_quotes[EXPIRY][25000]["call"] = 140.0  # Long Call exits below entry
    body = exit_all(client, logged_in, {"client_order_id": "bulk-exit-cash"}).json()
    assert body["status"] == "SUCCESS"

    txns = db_session.query(PaperTransaction).all()
    entry_txns = [t for t in txns if t.type.startswith("ENTRY_")]
    exit_txns = [t for t in txns if t.type.startswith("EXIT_")]
    assert len(entry_txns) == 3
    assert len(exit_txns) == 3  # one per exited position — exactly once

    account = db_session.query(PaperAccount).first()
    expected_cash = 500000 + sum(t.amount for t in txns)
    assert account.starting_capital == 500000
    port = client.get("/paper/portfolio", headers=headers(logged_in)).json()
    assert port["summary"]["available_cash"] == pytest.approx(expected_cash, abs=0.01)
    # Long Call (entry 200.00) exits at 140 → (140 − 200) × LOT; spread legs flat.
    assert port["summary"]["realized_pnl"] == pytest.approx((140.0 - 200.0) * LOT, abs=0.01)


# ---- 15. Realized P&L aggregation ----------------------------------------------


def test_total_realized_pnl_matches_expected(client, logged_in, db_session, chain_quotes):
    execute(client, logged_in, long_call_payload())  # entry 200.00 (25000 CE)
    chain_quotes[EXPIRY][25000]["call"] = 150.0
    body = exit_all(client, logged_in, {"client_order_id": "bulk-exit-pnl"}).json()
    expected = (150.0 - 200.0) * LOT
    assert body["total_realized_pnl"] == pytest.approx(expected, abs=0.01)
    pos = all_positions(db_session)[0]
    assert pos.realized_pnl == pytest.approx(expected, abs=0.01)
    assert pos.status == "closed"
    # cash_change = proceeds of the exit sell (positive).
    assert body["cash_change"] == pytest.approx(150.0 * LOT, abs=0.01)


# ---- 16. Journal correctness ---------------------------------------------------


def test_journal_records_bulk_exit_without_duplicates(client, logged_in, db_session):
    from app.models import Leg, Trade

    execute(client, logged_in, spread_payload())
    key = "bulk-exit-jrnl"
    body = exit_all(client, logged_in, {"client_order_id": key}).json()
    assert body["status"] == "SUCCESS"

    trades = db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].status == "closed"
    assert trades[0].exit_at is not None
    legs = db_session.query(Leg).all()
    assert len(legs) == 2
    assert all(l.exit_at is not None for l in legs)
    assert all(l.exit_price is not None for l in legs)

    # Replay must not touch the journal again.
    exit_all(client, logged_in, {"client_order_id": key})
    assert db_session.query(Trade).count() == 1
    assert db_session.query(Leg).count() == 2


# ---- 17. Strategy completion correctness ---------------------------------------


def test_execution_exit_at_only_when_strategy_fully_closed(client, logged_in, db_session):
    from app.models import StrategyExecution

    exec_id = execute(client, logged_in, spread_payload()).json()["execution_id"]
    positions = all_positions(db_session)
    first_pos = positions[0]

    # Close only ONE leg via the single-position endpoint: the execution is
    # NOT complete yet — exit_at stays unset (regression for §11).
    resp = exit_one(
        client, logged_in, first_pos.id, {"client_order_id": "bulk-strat-partial-leg"}
    )
    assert resp.status_code == 200
    execution = db_session.query(StrategyExecution).filter_by(execution_id=exec_id).first()
    assert execution.exit_at is None

    # Bulk-exit the strategy: now complete.
    body = exit_strategy(
        client, logged_in, exec_id, {"client_order_id": "bulk-exit-strat-complete"}
    ).json()
    assert body["status"] == "SUCCESS"
    execution = db_session.query(StrategyExecution).filter_by(execution_id=exec_id).first()
    assert execution.exit_at is not None

    # Analytics now counts ONE completed trade with the exact realized sum.
    analytics = client.get("/paper/analytics", headers=headers(logged_in)).json()
    assert analytics["performance"]["total_completed_trades"] == 1
    assert analytics["summary"]["open_position_count"] == 0


def test_analytics_reflects_bulk_exit(client, logged_in, db_session):
    execute(client, logged_in, long_call_payload())
    body = exit_all(client, logged_in, {"client_order_id": "bulk-exit-anl"}).json()
    assert body["status"] == "SUCCESS"
    analytics = client.get("/paper/analytics", headers=headers(logged_in)).json()
    assert analytics["performance"]["total_completed_trades"] == 1
    # A flat exit (realized 0) classifies as BREAKEVEN, not win/loss.
    assert analytics["performance"]["breakeven_trades"] == 1
    assert analytics["performance"]["winning_trades"] == 0
    assert len(analytics["equity_curve"]) == 2  # baseline + one realized point
    assert len(analytics["journal"]) == 1


# ---- 18. User isolation ---------------------------------------------------------


def test_exit_all_isolated_per_user(client, db_session):
    session_a, user_a = create_test_identity(db_session, "tok-bulk-user-a")
    execute(client, session_a, long_call_payload())

    session_b, user_b = create_test_identity(db_session, "tok-bulk-user-b")
    resp = exit_all(client, session_b, {"client_order_id": "bulk-exit-iso-b"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_POSITIONS"

    # User A's position is untouched.
    from app.models import Position

    pos = db_session.query(Position).first()
    assert pos.user_id == user_a  # positions are keyed by the user id
    assert pos.status == "open"
    assert len(open_positions(db_session)) == 1


def test_exit_strategy_isolated_per_user(client, db_session):
    session_a, user_a2 = create_test_identity(db_session, "tok-bulk-user-a2")
    exec_id = execute(client, session_a, long_call_payload()).json()["execution_id"]

    session_b, user_b2 = create_test_identity(db_session, "tok-bulk-user-b2")
    resp = exit_strategy(
        client, session_b, exec_id, {"client_order_id": "bulk-exit-strat-iso-b"}
    )
    assert resp.status_code == 404  # execution does not belong to user B
    assert len(open_positions(db_session)) == 1


# ---- 19. Partial execution reporting --------------------------------------------


def test_partial_result_reports_each_failed_position(client, logged_in, db_session):
    """PARTIAL carries per-position outcomes + errors; the UI can show exactly
    which positions failed and why (never a blanket 'all exited')."""
    from unittest.mock import patch as mock_patch

    from app.services import paper_execution as pe

    execute(client, logged_in, spread_payload(client_order_id="bulk-part-spread"))
    real_exit = pe.exit_position
    state = {"n": 0}

    def flaky_exit(user_id, position_id, request, db, fill_price, *, commit=True):
        state["n"] += 1
        if state["n"] == 2:  # second position fails at execution time
            raise pe.PaperExecutionError("EXECUTION_FAILED", "simulated mid-flight failure")
        return real_exit(user_id, position_id, request, db, fill_price, commit=commit)

    with mock_patch.object(pe, "exit_position", new=flaky_exit):
        resp = exit_all(client, logged_in, {"client_order_id": "bulk-exit-partial"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PARTIAL"
    assert body["exited_count"] == 1
    assert body["failed_count"] == 1
    statuses = {p["status"] for p in body["positions"]}
    assert statuses == {"EXITED", "FAILED"}
    failed = [p for p in body["positions"] if p["status"] == "FAILED"][0]
    assert "simulated" in failed["error"]
    assert len(body["errors"]) == 1
    # The failed position remains OPEN and queryable (nothing fabricated).
    assert len(open_positions(db_session)) == 1


# ---- 20. Refresh / reconciliation consistency -----------------------------------


def test_reconcile_and_portfolio_consistent_after_exit_all(client, logged_in, db_session):
    execute(client, logged_in, spread_payload())
    execute(client, logged_in, long_call_payload(client_order_id="bulk-rec-long"))
    body = exit_all(client, logged_in, {"client_order_id": "bulk-exit-rec"}).json()
    assert body["status"] == "SUCCESS"

    port = client.get("/paper/portfolio", headers=headers(logged_in)).json()
    assert port["summary"]["open_position_count"] == 0
    assert port["summary"]["open_strategy_count"] == 0
    assert port["summary"]["realized_pnl"] == 0.0

    rec = client.get("/paper/reconcile", headers=headers(logged_in)).json()
    assert rec["valid"] is True, rec["discrepancies"]

    positions = client.get("/paper/positions", headers=headers(logged_in)).json()
    assert positions == []
