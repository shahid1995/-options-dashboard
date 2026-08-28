"""Tests for Phase 6.6.6 — Live Position Valuation.

Server-authoritative live/unrealized P&L for open positions.
Reuses the existing broker option-chain infrastructure for LTP resolution.

Covers:
- Long/short position Live P&L
- Lot-size calculation
- Market value
- P&L percentage (entry_value denominator)
- Zero/missing LTP → unavailable
- Stale LTP (quote_timestamp older than threshold)
- Strategy-level aggregation
- Leg-level aggregation with per-leg entry price (PaperOrder.fill_price)
- Shared instrument across two strategies with DIFFERENT entry prices
- Closed position excluded from live valuation
- Realized P&L unchanged
- Partial availability (mixed LTP)
- User isolation
- Authentication required
- No network/broker dependency in pure unit tests
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    PaperOrder,
    Position,
    StrategyExecution,
    StrategyLegExposure,
    PaperAccount,
)
from app.services import token_store
from tests.test_helpers import create_test_identity
from app.services.valuation import (
    STALE_THRESHOLD_SECONDS,
    _is_stale,
    compute_position_pnl,
    compute_leg_pnl,
)

LOT = 65
EXPIRY = "2026-08-21"


# ---- Pure unit tests (no DB, no broker) -----------------------------------


class TestComputePositionPnl:
    """Test the pure position P&L computation."""

    def test_long_position_pnl(self):
        """Long: (LTP − avg) × qty × lot"""
        pnl, mv = compute_position_pnl(
            net_quantity=2, average_entry_price=100.0,
            current_price=120.0, lot_size=LOT,
        )
        # (120 - 100) × 2 × 65 = 20 × 130 = 2600
        assert pnl == 2600.0
        assert mv == 120.0 * 2 * LOT  # 15600

    def test_short_position_pnl(self):
        """Short: (avg − LTP) × qty × lot"""
        pnl, mv = compute_position_pnl(
            net_quantity=-3, average_entry_price=200.0,
            current_price=180.0, lot_size=LOT,
        )
        # (200 - 180) × 3 × 65 = 20 × 195 = 3900
        assert pnl == 3900.0
        assert mv == 180.0 * 3 * LOT  # 35100

    def test_long_position_loss(self):
        pnl, mv = compute_position_pnl(
            net_quantity=1, average_entry_price=150.0,
            current_price=120.0, lot_size=LOT,
        )
        assert pnl == -1950.0
        assert mv == 120.0 * 1 * LOT

    def test_short_position_loss(self):
        pnl, mv = compute_position_pnl(
            net_quantity=-2, average_entry_price=100.0,
            current_price=130.0, lot_size=LOT,
        )
        assert pnl == -3900.0
        assert mv == 130.0 * 2 * LOT

    def test_lot_size_calculation(self):
        pnl, mv = compute_position_pnl(
            net_quantity=5, average_entry_price=50.0,
            current_price=60.0, lot_size=25,
        )
        assert pnl == (60 - 50) * 5 * 25
        assert mv == 60.0 * 5 * 25


class TestComputeLegPnl:
    """Test per-leg P&L computation."""

    def test_buy_leg_pnl(self):
        pnl = compute_leg_pnl("buy", 2, 120.0, 100.0, LOT)
        assert pnl == (120 - 100) * 2 * LOT

    def test_sell_leg_pnl(self):
        pnl = compute_leg_pnl("sell", 3, 80.0, 100.0, LOT)
        assert pnl == (100 - 80) * 3 * LOT

    def test_zero_remaining_returns_none(self):
        assert compute_leg_pnl("buy", 0, 120.0, 100.0, LOT) is None


class TestIsStale:
    """Test staleness detection."""

    def test_no_timestamp_not_stale(self):
        """No timestamp → not stale (cannot determine)."""
        now = datetime.now(timezone.utc)
        assert _is_stale(None, now) is False

    def test_recent_timestamp_not_stale(self):
        now = datetime.now(timezone.utc)
        qt = (now - timedelta(seconds=60)).isoformat()
        assert _is_stale(qt, now) is False

    def test_old_timestamp_is_stale(self):
        now = datetime.now(timezone.utc)
        qt = (now - timedelta(seconds=STALE_THRESHOLD_SECONDS + 60)).isoformat()
        assert _is_stale(qt, now) is True

    def test_exactly_at_threshold_not_stale(self):
        """Exactly at the threshold boundary is NOT stale."""
        now = datetime.now(timezone.utc)
        qt = (now - timedelta(seconds=STALE_THRESHOLD_SECONDS)).isoformat()
        assert _is_stale(qt, now) is False

    def test_invalid_timestamp_not_stale(self):
        now = datetime.now(timezone.utc)
        assert _is_stale("not-a-timestamp", now) is False


# ---- DB fixtures & helpers --------------------------------------------------


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
    session_id, user_id = create_test_identity(db_session, "tok-valuation-test")
    db_session._test_user_id = user_id
    return session_id


HDR = lambda tok: {"X-Session-Id": tok}


def _account(db, user_id):
    acc = PaperAccount(user_id=user_id, starting_capital=500000)
    db.add(acc)
    db.flush()
    return acc


def _position(db, user_id, symbol="NIFTY", expiry=EXPIRY, strike=25000.0,
              option_type="call", net_quantity=2, lot_size=LOT,
              average_entry_price=150.0, status="open",
              strategy_execution_id=None, realized_pnl=0.0):
    pos = Position(
        user_id=user_id, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, net_quantity=net_quantity, lot_size=lot_size,
        average_entry_price=average_entry_price, realized_pnl=realized_pnl,
        status=status, strategy_execution_id=strategy_execution_id,
    )
    db.add(pos)
    db.flush()
    return pos


def _execution(db, user_id, execution_id="exec-1", strategy_tag="Bull Call"):
    se = StrategyExecution(
        user_id=user_id, execution_id=execution_id,
        client_order_id=f"coid-{execution_id}",
        strategy_tag=strategy_tag, symbol="NIFTY", status="FILLED",
        entry_net=0.0,
    )
    db.add(se)
    db.flush()
    return se


_exp_counter = {"n": 0}
_order_counter = {"n": 0}


def _exposure(db, user_id, execution_id, position_id, order_id=None,
              symbol="NIFTY", expiry=EXPIRY, strike=25000.0,
              option_type="call", action="buy", original_quantity=2,
              remaining_quantity=2, status="open"):
    _exp_counter["n"] += 1
    if order_id is None:
        order_id = _exp_counter["n"]
    exp = StrategyLegExposure(
        user_id=user_id, execution_id=execution_id, position_id=position_id,
        order_id=order_id or 0, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, action=action,
        original_quantity=original_quantity,
        remaining_quantity=remaining_quantity, status=status,
    )
    db.add(exp)
    db.flush()
    return exp


def _order(db, user_id, fill_price, symbol="NIFTY", expiry=EXPIRY, strike=25000.0,
           option_type="call", action="buy", quantity=2, lot_size=LOT,
           status="FILLED", kind="entry", execution_id=None):
    _order_counter["n"] += 1
    o = PaperOrder(
        user_id=user_id, client_order_id=f"coid-order-{_order_counter['n']}",
        execution_id=execution_id, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, action=action, quantity=quantity, lot_size=lot_size,
        status=status, filled_quantity=quantity if status == "FILLED" else 0,
        fill_price=fill_price, kind=kind,
    )
    db.add(o)
    db.flush()
    return o


# ---- Mock chain data --------------------------------------------------------


class _FakeGateway:
    """Minimal mock for the broker gateway returning predefined LTP values."""

    def __init__(self, strike_ltp_map=None, default_ltp=None,
                 missing_strikes=None, quote_timestamps=None):
        self._strike_ltp_map = strike_ltp_map or {}
        self._default_ltp = default_ltp
        self._missing_strikes = missing_strikes or set()
        self._quote_timestamps = quote_timestamps or {}

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        chain = []
        for strike, ltp in self._strike_ltp_map.items():
            if strike in self._missing_strikes:
                chain.append({"strike": strike, "call": {}, "put": {}})
            else:
                qts = self._quote_timestamps.get(strike)
                chain.append({
                    "strike": strike,
                    "call": {"ltp": ltp, "quote_timestamp": qts},
                    "put": {"ltp": ltp, "quote_timestamp": qts},
                })
        if not self._strike_ltp_map and self._default_ltp is not None:
            qts = self._quote_timestamps.get(25000.0)
            chain.append({
                "strike": 25000.0,
                "call": {"ltp": self._default_ltp, "quote_timestamp": qts},
                "put": {"ltp": self._default_ltp, "quote_timestamp": qts},
            })
        return {"chain": chain}


class _FakeGatewayMissing:
    def __init__(self, missing_strike=25000.0):
        self._missing = missing_strike

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        return {"chain": [{"strike": self._missing, "call": {}, "put": {}}]}


class _FakeGatewayPartial:
    """Gateway where some strikes have LTP and others don't."""

    def __init__(self, strike_ltp_map):
        self._strike_ltp_map = strike_ltp_map

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        chain = []
        for strike, ltp in self._strike_ltp_map.items():
            if ltp is None:
                chain.append({"strike": strike, "call": {}, "put": {}})
            else:
                chain.append({
                    "strike": strike,
                    "call": {"ltp": ltp},
                    "put": {"ltp": ltp},
                })
        return {"chain": chain}


def _mock_gateway(strike, ltp):
    return _FakeGateway({strike: ltp})


def _mock_gateway_missing(strike):
    return _FakeGatewayMissing(strike)


def _mock_gateway_multi(strike_map):
    return _FakeGateway(strike_map)


def _mock_gateway_any():
    return _FakeGateway(default_ltp=120.0)


def _mock_gateway_partial(strike_ltp_map):
    """Gateway where some strikes have LTP and others don't."""
    return _FakeGatewayPartial(strike_ltp_map)


def _mock_gateway_stale(strike, ltp, stale_seconds=600):
    """Gateway with stale quote_timestamp (>5 min old)."""
    now = datetime.now(timezone.utc)
    qt = (now - timedelta(seconds=stale_seconds)).isoformat()
    return _FakeGateway({strike: ltp}, quote_timestamps={strike: qt})


def _mock_gateway_fresh(strike, ltp):
    """Gateway with fresh quote_timestamp (<1 min old)."""
    now = datetime.now(timezone.utc)
    qt = (now - timedelta(seconds=30)).isoformat()
    return _FakeGateway({strike: ltp}, quote_timestamps={strike: qt})


# ============================================================================
# Router integration tests
# ============================================================================


class TestValuationEndpoint:
    """GET /paper/positions/valuation integration tests."""

    def test_auth_required(self, client):
        resp = client.get("/paper/positions/valuation")
        assert resp.status_code == 401

    def test_empty_portfolio(self, client, logged_in):
        resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))
        assert resp.status_code == 200
        body = resp.json()
        assert body["positions"] == []
        assert body["summary"]["open_position_count"] == 0
        assert body["summary"]["status"] == "available"

    def test_long_position_live_pnl(self, client, logged_in, db_session):
        """Long position with valid LTP computes correct Live P&L."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["positions"]) == 1
        pv = body["positions"][0]
        assert pv["position_id"] == pos.id
        assert pv["current_price"] == 120.0
        assert pv["price_status"] == "available"
        # (120 - 100) × 2 × 65 = 2600
        assert pv["live_pnl"] == 2600.0
        assert pv["market_value"] == 120.0 * 2 * LOT
        # P&L % = 2600 / (100 × 2 × 65) × 100 = 20.0
        assert pv["live_pnl_pct"] == pytest.approx(20.0, abs=0.1)

    def test_short_position_live_pnl(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        pos = _position(db_session, uid, net_quantity=-3, average_entry_price=200.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 180.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        pv = body["positions"][0]
        assert pv["current_price"] == 180.0
        # (200 - 180) × 3 × 65 = 3900
        assert pv["live_pnl"] == 3900.0

    def test_missing_ltp_returns_unavailable(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway_missing(25000.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        pv = body["positions"][0]
        assert pv["current_price"] is None
        assert pv["live_pnl"] is None
        assert pv["market_value"] is None
        assert pv["price_status"] == "unavailable"
        assert body["summary"]["status"] == "unavailable"

    def test_realized_pnl_unchanged(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, realized_pnl=500.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert pv["realized_pnl"] == 500.0

    def test_closed_position_excluded(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, status="open")
        _position(db_session, uid, net_quantity=0, status="closed", strike=26000.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        assert body["summary"]["open_position_count"] == 1
        assert len(body["positions"]) == 1

    def test_user_isolation(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        pos_mine = _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        other_uid = "other-valuation-user"
        _account(db_session, other_uid)
        _position(db_session, other_uid, net_quantity=5, average_entry_price=200.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        assert body["summary"]["open_position_count"] == 1
        assert body["positions"][0]["position_id"] == pos_mine.id

    def test_strategy_aggregation(self, client, logged_in, db_session):
        """Strategy-level P&L aggregation from leg exposures."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        exec1 = _execution(db_session, uid, "exec-1", "Bull Call")
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0,
                        strategy_execution_id="exec-1")
        _exposure(db_session, uid, "exec-1", pos.id, action="buy", remaining_quantity=2)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert len(pv["strategies"]) >= 1
        sv = pv["strategies"][0]
        assert sv["strategy_tag"] == "Bull Call"
        assert sv["execution_id"] == "exec-1"
        assert len(sv["legs"]) == 1
        assert sv["legs"][0]["action"] == "buy"
        assert sv["legs"][0]["remaining_quantity"] == 2

    def test_leg_pnl_uses_order_fill_price(self, client, logged_in, db_session):
        """Leg P&L uses PaperOrder.fill_price, not position average entry.

        Strategy A: entry @ ₹100, Strategy B: entry @ ₹140
        Position avg = weighted avg, but leg P&L must use各自的 entry.
        """
        uid = db_session._test_user_id
        _account(db_session, uid)
        exec_a = _execution(db_session, uid, "exec-a", "Strategy A")
        exec_b = _execution(db_session, uid, "exec-b", "Strategy B")
        # Position avg = (100×2 + 140×2) / 4 = 120, but that's irrelevant for legs
        pos = _position(db_session, uid, net_quantity=4, average_entry_price=120.0)

        # Create orders with different fill prices
        order_a = _order(db_session, uid, fill_price=100.0, quantity=2,
                         execution_id="exec-a")
        order_b = _order(db_session, uid, fill_price=140.0, quantity=2,
                         execution_id="exec-b")

        # Create exposures referencing those orders
        exp_a = _exposure(db_session, uid, "exec-a", pos.id, order_id=order_a.id,
                          original_quantity=2, remaining_quantity=2)
        exp_b = _exposure(db_session, uid, "exec-b", pos.id, order_id=order_b.id,
                          original_quantity=2, remaining_quantity=2)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 150.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        strats = {s["execution_id"]: s for s in pv["strategies"]}

        # Strategy A: (150 - 100) × 2 × 65 = 6500
        leg_a = strats["exec-a"]["legs"][0]
        assert leg_a["entry_price"] == 100.0
        assert leg_a["live_pnl"] == pytest.approx(6500.0, abs=1)

        # Strategy B: (150 - 140) × 2 × 65 = 1300
        leg_b = strats["exec-b"]["legs"][0]
        assert leg_b["entry_price"] == 140.0
        assert leg_b["live_pnl"] == pytest.approx(1300.0, abs=1)

        # Strategy-level totals
        assert strats["exec-a"]["live_pnl"] == pytest.approx(6500.0, abs=1)
        assert strats["exec-b"]["live_pnl"] == pytest.approx(1300.0, abs=1)

    def test_shared_instrument_two_strategies_different_prices(
        self, client, logged_in, db_session
    ):
        """Two strategies with different entry prices on same instrument.

        Strategy A: BUY 2 @ ₹100, Strategy B: BUY 5 @ ₹140
        LTP ₹150
        Correct per-leg P&L:
            A = (150-100) × 2 × 65 = 6500
            B = (150-140) × 5 × 65 = 3250
        """
        uid = db_session._test_user_id
        _account(db_session, uid)
        exec_a = _execution(db_session, uid, "exec-a", "Strategy A")
        exec_b = _execution(db_session, uid, "exec-b", "Strategy B")
        pos = _position(db_session, uid, net_quantity=7, average_entry_price=125.0)

        order_a = _order(db_session, uid, fill_price=100.0, quantity=2,
                         execution_id="exec-a")
        order_b = _order(db_session, uid, fill_price=140.0, quantity=5,
                         execution_id="exec-b")

        _exposure(db_session, uid, "exec-a", pos.id, order_id=order_a.id,
                  original_quantity=2, remaining_quantity=2)
        _exposure(db_session, uid, "exec-b", pos.id, order_id=order_b.id,
                  original_quantity=5, remaining_quantity=5)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 150.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        strats = {s["execution_id"]: s for s in pv["strategies"]}

        # Strategy A: (150 - 100) × 2 × 65 = 6500
        assert strats["exec-a"]["live_pnl"] == pytest.approx(6500.0, abs=1)
        # Strategy B: (150 - 140) × 5 × 65 = 3250
        assert strats["exec-b"]["live_pnl"] == pytest.approx(3250.0, abs=1)

    def test_leg_pnl_unavailable_when_order_missing(self, client, logged_in, db_session):
        """Leg P&L is unavailable when source PaperOrder cannot be joined."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        exec1 = _execution(db_session, uid, "exec-1")
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        # Exposure references order_id=99999 which doesn't exist
        _exposure(db_session, uid, "exec-1", pos.id, order_id=99999,
                  remaining_quantity=2)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        # Position-level P&L still works (uses avg entry)
        assert pv["live_pnl"] == pytest.approx(2600.0, abs=1)
        # But leg-level P&L is unavailable (no fill_price found)
        sv = pv["strategies"][0]
        leg = sv["legs"][0]
        assert leg["live_pnl"] is None
        assert leg["entry_price"] is None
        assert leg["price_status"] == "unavailable"

    def test_stale_price_status(self, client, logged_in, db_session):
        """LTP resolved but quote_timestamp is old → stale."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway_stale(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert pv["current_price"] == 120.0
        assert pv["price_status"] == "stale"
        # P&L still calculated (price exists, just stale)
        assert pv["live_pnl"] == pytest.approx(2600.0, abs=1)

    def test_fresh_price_not_stale(self, client, logged_in, db_session):
        """LTP resolved with recent quote_timestamp → available."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway_fresh(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert pv["price_status"] == "available"

    def test_partial_availability(self, client, logged_in, db_session):
        """Position A has LTP, Position B has no LTP → partial status."""
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, strike=25000.0,
                  average_entry_price=100.0)
        _position(db_session, uid, net_quantity=1, strike=26000.0,
                  average_entry_price=80.0)
        db_session.commit()

        # 25000 has LTP=120, 26000 has NO LTP (None)
        with patch(
            "app.services.valuation.gateway",
            new=_mock_gateway_partial({25000.0: 120.0, 26000.0: None}),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        summary = resp.json()["summary"]
        assert summary["status"] == "partial"
        assert summary["positions_with_price"] == 1
        assert summary["positions_unavailable"] == 1

    def test_deterministic_ordering(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        for i in range(3):
            _position(db_session, uid, net_quantity=1, strike=24000.0 + i * 500,
                      average_entry_price=100.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway_any()):
            resp1 = client.get("/paper/positions/valuation", headers=HDR(logged_in))
            resp2 = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        ids1 = [p["position_id"] for p in resp1.json()["positions"]]
        ids2 = [p["position_id"] for p in resp2.json()["positions"]]
        assert ids1 == ids2

    def test_summary_fields(self, client, logged_in, db_session):
        uid = db_session._test_user_id
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch("app.services.valuation.gateway", new=_mock_gateway(25000.0, 120.0)):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        summary = resp.json()["summary"]
        assert summary["open_position_count"] == 1
        assert summary["positions_with_price"] == 1
        assert summary["positions_unavailable"] == 0
        assert summary["status"] == "available"
