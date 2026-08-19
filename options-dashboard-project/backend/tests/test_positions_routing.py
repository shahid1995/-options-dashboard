"""Tests for GET /paper/positions routing behavior (Phase 6.6.4.y).

Proves:
- Legacy GET /paper/positions (no params) → open positions only (backward compat)
- GET /paper/positions?status=open → enriched, open positions only
- GET /paper/positions?status=closed → enriched, closed positions only
- GET /paper/positions?all=true → enriched, all positions (open + closed)
- GET /paper/positions?symbol=NIFTY → enriched, filtered
- GET /paper/positions?option_type=call → enriched, filtered
- GET /paper/positions?strategy_execution_id=X → enriched, filtered
- GET /paper/positions?all=true&limit=500 → correct pagination
- All tab returns both open and closed positions
- Open tab excludes closed positions
- Closed tab excludes open positions
- User isolation remains enforced
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Position, StrategyExecution, PaperOrder
from app.services import token_store


@pytest.fixture()
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


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _login():
    yield
    token_store.clear_token()


@pytest.fixture()
def logged_in(client):
    """Returns the session_id (used as user_id by require_session)."""
    return token_store.set_token("tok-xyz")


HDR = lambda tok: {"X-Session-Id": tok}


# ---- Helpers ----


def _make_position(
    db,
    user_id,
    symbol="NIFTY",
    expiry="2026-08-21",
    strike=25000.0,
    option_type="call",
    net_quantity=2,
    lot_size=65,
    average_entry_price=150.0,
    status="open",
    strategy_execution_id=None,
):
    pos = Position(
        user_id=user_id,
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        net_quantity=net_quantity,
        lot_size=lot_size,
        average_entry_price=average_entry_price,
        realized_pnl=0.0,
        status=status,
        strategy_execution_id=strategy_execution_id,
    )
    db.add(pos)
    db.flush()
    return pos


# ---- TEST 1: Legacy GET /paper/positions returns open positions only ----


def test_legacy_no_params_returns_open_only(client, logged_in, db_session):
    """No query params → legacy get_open_positions() → open only."""
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    ids = [p["id"] for p in data]
    assert open_pos.id in ids
    assert closed_pos.id not in ids


# ---- TEST 2: status=open uses enriched service ----


def test_status_open_returns_open_only(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"status": "open"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    ids = [p["id"] for p in data]
    assert open_pos.id in ids
    assert closed_pos.id not in ids


# ---- TEST 3: status=closed uses enriched service ----


def test_status_closed_returns_closed_only(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"status": "closed"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    ids = [p["id"] for p in data]
    assert closed_pos.id in ids
    assert open_pos.id not in ids


# ---- TEST 4: all=true returns all positions ----


def test_all_true_returns_all_positions(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"all": True}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    ids = [p["id"] for p in data]
    assert open_pos.id in ids
    assert closed_pos.id in ids


# ---- TEST 5: symbol filter uses enriched service ----


def test_symbol_filter(client, logged_in, db_session):
    uid = logged_in
    nifty = _make_position(db_session, user_id=uid, symbol="NIFTY", net_quantity=2, status="open")
    bank = _make_position(db_session, user_id=uid, symbol="BANKNIFTY", strike=50000.0, net_quantity=1, status="open")

    resp = client.get("/paper/positions", params={"symbol": "NIFTY"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    symbols = {p["symbol"] for p in data}
    assert "NIFTY" in symbols
    assert "BANKNIFTY" not in symbols


# ---- TEST 6: option_type filter uses enriched service ----


def test_option_type_filter(client, logged_in, db_session):
    uid = logged_in
    call = _make_position(db_session, user_id=uid, option_type="call", net_quantity=2, status="open")
    put = _make_position(db_session, user_id=uid, option_type="put", strike=24900.0, net_quantity=1, status="open")

    resp = client.get("/paper/positions", params={"option_type": "call"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    types = {p["option_type"] for p in data}
    assert "call" in types
    assert "put" not in types


# ---- TEST 7: strategy_execution_id filter uses enriched service ----


def test_strategy_execution_id_filter(client, logged_in, db_session):
    uid = logged_in
    se = StrategyExecution(
        user_id=uid, execution_id="exec-1", client_order_id="coid-1",
        strategy_tag="Bull Call Spread", symbol="NIFTY", status="FILLED",
        entry_net=0.0,
    )
    db_session.add(se)
    db_session.flush()

    pos1 = _make_position(db_session, user_id=uid, net_quantity=2, strategy_execution_id="exec-1")
    pos2 = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=1, strategy_execution_id="exec-2")

    resp = client.get("/paper/positions", params={"strategy_execution_id": "exec-1"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    exec_ids = {p.get("strategy_execution_id") for p in data}
    assert "exec-1" in exec_ids
    assert "exec-2" not in exec_ids


# ---- TEST 8: all=true with limit/offset pagination ----


def test_all_true_with_pagination(client, logged_in, db_session):
    uid = logged_in
    for i in range(5):
        _make_position(db_session, user_id=uid, strike=25000.0 + i * 100, net_quantity=i + 1, status="open")

    resp = client.get("/paper/positions", params={"all": True, "limit": 2, "offset": 0}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    resp2 = client.get("/paper/positions", params={"all": True, "limit": 2, "offset": 2}, headers=HDR(logged_in))
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2) == 2

    ids1 = {p["id"] for p in data}
    ids2 = {p["id"] for p in data2}
    assert ids1.isdisjoint(ids2)


# ---- TEST 9: All tab path returns both open and closed ----


def test_all_tab_returns_both_open_and_closed(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"all": True, "limit": 500}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    statuses = {p["status"] for p in data}
    assert "open" in statuses
    assert "closed" in statuses


# ---- TEST 10: Open tab excludes closed positions ----


def test_open_tab_excludes_closed(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"status": "open"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    assert all(p["status"] == "open" for p in data)


# ---- TEST 11: Closed tab excludes open positions ----


def test_closed_tab_excludes_open(client, logged_in, db_session):
    uid = logged_in
    open_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    closed_pos = _make_position(db_session, user_id=uid, strike=25100.0, net_quantity=0, status="closed")

    resp = client.get("/paper/positions", params={"status": "closed"}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    open_ids = {open_pos.id}
    returned_ids = {p["id"] for p in data}
    assert open_ids.isdisjoint(returned_ids)


# ---- TEST 12: User isolation ----


def test_user_isolation(client, logged_in, db_session):
    uid = logged_in
    my_pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open")
    other_pos = _make_position(db_session, user_id="user-other-xyz", strike=25100.0, net_quantity=1, status="open")

    resp = client.get("/paper/positions", params={"all": True}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    # Only our position should appear, not the other user's
    ids = {p["id"] for p in data}
    assert my_pos.id in ids
    assert other_pos.id not in ids


# ---- TEST 13: Unauthenticated request is rejected ----


def test_unauthenticated_rejected(client, db_session):
    _make_position(db_session, user_id="any-user", net_quantity=2, status="open")
    resp = client.get("/paper/positions")
    assert resp.status_code == 401


# ---- TEST 14: Enriched response includes strategy_tag ----


def test_enriched_response_includes_strategy_tag(client, logged_in, db_session):
    uid = logged_in
    se = StrategyExecution(
        user_id=uid, execution_id="exec-test", client_order_id="coid-test",
        strategy_tag="Iron Condor", symbol="NIFTY", status="FILLED",
        entry_net=0.0,
    )
    db_session.add(se)
    db_session.flush()

    pos = _make_position(db_session, user_id=uid, net_quantity=2, status="open",
                         strategy_execution_id="exec-test")

    resp = client.get("/paper/positions", params={"all": True}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    tags = {p["id"]: p.get("strategy_tag") for p in data}
    assert tags[pos.id] == "Iron Condor"


# ---- TEST 15: No credentials or broker fields leak ----


def test_no_broker_fields_leaked(client, logged_in, db_session):
    uid = logged_in
    _make_position(db_session, user_id=uid, net_quantity=2, status="open")

    resp = client.get("/paper/positions", params={"all": True}, headers=HDR(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    for pos in data:
        for key in ["access_token", "refresh_token", "instrument_key",
                     "transaction_type", "broker_order_id", "broker_position_id"]:
            assert key not in pos, f"Field '{key}' should not be in response"
