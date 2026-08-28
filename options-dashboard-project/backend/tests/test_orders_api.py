"""Tests for the enhanced GET /paper/orders endpoint (Phase 6.6.3).

Covers server-side filtering, pagination, strategy-tag attachment,
backward compatibility (no filters = full list), user isolation,
and null/missing-field handling.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import PaperOrder, StrategyExecution
from app.services import token_store
from tests.test_helpers import create_test_identity


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
def logged_in(client, db_session):
    session_id, _ = create_test_identity(db_session, "tok-xyz")
    return session_id


def _make_order(
    db,
    user_id="user-1",
    client_order_id="ord-001",
    execution_id="exec-1",
    symbol="NIFTY",
    expiry="2026-08-21",
    strike=25000.0,
    option_type="call",
    action="buy",
    quantity=2,
    lot_size=65,
    status="FILLED",
    filled_quantity=2,
    fill_price=150.0,
    kind="entry",
    rejected_reason=None,
):
    order = PaperOrder(
        user_id=user_id,
        client_order_id=client_order_id,
        execution_id=execution_id,
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        action=action,
        quantity=quantity,
        lot_size=lot_size,
        status=status,
        filled_quantity=filled_quantity,
        fill_price=fill_price,
        price_source="market",
        kind=kind,
        rejected_reason=rejected_reason,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_execution(db, user_id="user-1", execution_id="exec-1", strategy_tag="Bull Call Spread"):
    se = StrategyExecution(
        user_id=user_id,
        execution_id=execution_id,
        client_order_id=f"client-{execution_id}",
        strategy_tag=strategy_tag,
        symbol="NIFTY",
        status="FILLED",
    )
    db.add(se)
    db.commit()
    return se


def _headers(sid):
    return {"X-Session-Id": sid}


# ---- Backward compatibility ----

def test_backward_compat_no_filters(db_session, client, logged_in):
    """No query params returns all orders (backward-compatible)."""
    _make_order(db_session, client_order_id="ord-1", user_id=db_session._test_user_id)
    _make_order(db_session, client_order_id="ord-2", user_id=db_session._test_user_id)
    resp = client.get("/paper/orders", headers=_headers(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ---- Status filter ----


def test_filter_by_status(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", status="FILLED")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", status="REJECTED", rejected_reason="Market closed")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-3", status="PENDING")

    resp = client.get("/paper/orders?status=FILLED", headers=_headers(logged_in))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "FILLED"

    resp = client.get("/paper/orders?status=REJECTED", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rejected_reason"] == "Market closed"


# ---- Symbol filter ----


def test_filter_by_symbol(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", symbol="NIFTY")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", symbol="BANKNIFTY")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-3", symbol="NIFTY")

    resp = client.get("/paper/orders?symbol=NIFTY", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 2
    assert all(o["symbol"] == "NIFTY" for o in data)


def test_filter_by_symbol_case_insensitive(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", symbol="NIFTY")
    resp = client.get("/paper/orders?symbol=nifty", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1


# ---- Action filter ----


def test_filter_by_action(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", action="buy")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", action="sell")

    resp = client.get("/paper/orders?action=buy", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["action"] == "buy"


# ---- Option type filter ----


def test_filter_by_option_type(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", option_type="call")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", option_type="put")

    resp = client.get("/paper/orders?option_type=put", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["option_type"] == "put"


# ---- Kind filter ----


def test_filter_by_kind(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", kind="entry")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", kind="exit")

    resp = client.get("/paper/orders?kind=exit", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["kind"] == "exit"


# ---- Strategy execution ID filter ----


def test_filter_by_strategy_execution_id(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", execution_id="exec-A")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", execution_id="exec-B")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-3", execution_id="exec-A")

    resp = client.get("/paper/orders?strategy_execution_id=exec-A", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 2
    assert all(o["execution_id"] == "exec-A" for o in data)


# ---- Combined filters ----


def test_combined_filters(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", symbol="NIFTY", action="buy", status="FILLED")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", symbol="NIFTY", action="sell", status="FILLED")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-3", symbol="BANKNIFTY", action="buy", status="FILLED")

    resp = client.get("/paper/orders?symbol=NIFTY&action=buy", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "NIFTY"
    assert data[0]["action"] == "buy"


# ---- Pagination ----


def test_limit_and_offset(db_session, client, logged_in):
    for i in range(5):
        _make_order(db_session, user_id=db_session._test_user_id, client_order_id=f"ord-{i:03d}")

    resp = client.get("/paper/orders?limit=2", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 2

    resp = client.get("/paper/orders?limit=2&offset=2", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 2

    resp = client.get("/paper/orders?limit=2&offset=4", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1


def test_limit_max_500(client, logged_in):
    resp = client.get("/paper/orders?limit=501", headers=_headers(logged_in))
    assert resp.status_code == 422


# ---- Strategy tag attachment ----


def test_strategy_tag_attached(db_session, client, logged_in):
    _make_execution(db_session, user_id=db_session._test_user_id, execution_id="exec-1", strategy_tag="Iron Condor")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1", execution_id="exec-1")
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-2", execution_id=None)

    resp = client.get("/paper/orders", headers=_headers(logged_in))
    data = resp.json()
    tagged = [o for o in data if o["execution_id"] == "exec-1"]
    untagged = [o for o in data if o["execution_id"] is None]
    assert len(tagged) == 1
    assert tagged[0]["strategy_tag"] == "Iron Condor"
    assert tagged[0]["strategy_execution_id"] == "exec-1"
    assert len(untagged) == 1
    assert untagged[0]["strategy_tag"] == "Custom"


# ---- updated_at present ----


def test_updated_at_present(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1")
    resp = client.get("/paper/orders", headers=_headers(logged_in))
    data = resp.json()
    assert "updated_at" in data[0]
    assert data[0]["updated_at"] is not None


# ---- User isolation ----


def test_user_isolation(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-mine")
    _make_order(db_session, user_id="user-2", client_order_id="ord-theirs")

    resp = client.get("/paper/orders", headers=_headers(logged_in))
    data = resp.json()
    # Only user-1's orders appear (logged_in is user-1)
    mine = [o for o in data if o["client_order_id"] == "ord-mine"]
    theirs = [o for o in data if o["client_order_id"] == "ord-theirs"]
    assert len(mine) == 1
    assert len(theirs) == 0


# ---- Authentication ----


def test_unauthenticated_rejected(client):
    resp = client.get("/paper/orders")
    assert resp.status_code == 401


def test_wrong_session_rejected(client, db_session):
    create_test_identity(db_session, "other-token")
    resp = client.get("/paper/orders", headers={"X-Session-Id": "wrong"})
    assert resp.status_code == 401


# ---- Empty result ----


def test_no_matching_orders(db_session, client, logged_in):
    resp = client.get("/paper/orders?status=NONEXISTENT", headers=_headers(logged_in))
    assert resp.status_code == 200
    assert resp.json() == []


# ---- Null / missing fields ----


def test_rejected_order_has_reason(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-rej", status="REJECTED", rejected_reason="Chain unavailable")
    resp = client.get("/paper/orders?status=REJECTED", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rejected_reason"] == "Chain unavailable"


def test_filled_order_no_rejected_reason(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-fill", status="FILLED")
    resp = client.get("/paper/orders?status=FILLED", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rejected_reason"] is None


# ---- Execution mode (PAPER) ----


def test_all_orders_are_paper(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1")
    resp = client.get("/paper/orders", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    # Paper orders — no broker_order_id, no execution_mode field needed


# ---- No broker-specific fields ----


def test_no_broker_credentials_leaked(db_session, client, logged_in):
    _make_order(db_session, user_id=db_session._test_user_id, client_order_id="ord-1")
    resp = client.get("/paper/orders", headers=_headers(logged_in))
    data = resp.json()
    order = data[0]
    forbidden_keys = {"access_token", "refresh_token", "api_key", "api_secret",
                      "client_secret", "instrument_key", "broker_order_id"}
    assert not forbidden_keys.intersection(order.keys())


# ---- Partial execution ----


def test_partial_execution_representation(db_session, client, logged_in):
    _make_order(
        db_session,
        user_id=db_session._test_user_id,
        client_order_id="ord-partial",
        quantity=10,
        filled_quantity=4,
        status="PARTIALLY_FILLED",
    )
    resp = client.get("/paper/orders?status=PARTIALLY_FILLED", headers=_headers(logged_in))
    data = resp.json()
    assert len(data) == 1
    assert data[0]["quantity"] == 10
    assert data[0]["filled_quantity"] == 4
    assert data[0]["status"] == "PARTIALLY_FILLED"
