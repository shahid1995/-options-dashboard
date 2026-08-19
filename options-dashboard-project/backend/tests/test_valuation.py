"""Tests for Phase 6.6.6 — Live Position Valuation.

Server-authoritative live/unrealized P&L for open positions.
Reuses the existing broker option-chain infrastructure for LTP resolution.

Covers:
- Long position Live P&L
- Short position Live P&L
- Lot-size calculation
- Market value
- P&L percentage
- Zero/missing LTP
- Strategy-level aggregation
- Leg-level aggregation
- Shared instrument across two strategies
- Closed position does not appear as live P&L
- Realized P&L remains unchanged
- User isolation
- No network/broker dependency in pure unit tests
- Authentication required
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Position,
    StrategyExecution,
    StrategyLegExposure,
    PaperAccount,
)
from app.services import token_store
from app.services.valuation import (
    compute_position_pnl,
    compute_leg_pnl,
    PositionValuation,
    StrategyValuation,
    LegValuation,
    ValuationSummary,
)

LOT = 65
EXPIRY = "2026-08-21"


# ---- Pure unit tests (no DB, no broker) ------------------------------------


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
        """Long position in loss."""
        pnl, mv = compute_position_pnl(
            net_quantity=1, average_entry_price=150.0,
            current_price=120.0, lot_size=LOT,
        )
        # (120 - 150) × 1 × 65 = -30 × 65 = -1950
        assert pnl == -1950.0
        assert mv == 120.0 * 1 * LOT

    def test_short_position_loss(self):
        """Short position in loss."""
        pnl, mv = compute_position_pnl(
            net_quantity=-2, average_entry_price=100.0,
            current_price=130.0, lot_size=LOT,
        )
        # (100 - 130) × 2 × 65 = -30 × 130 = -3900
        assert pnl == -3900.0
        assert mv == 130.0 * 2 * LOT

    def test_lot_size_calculation(self):
        """Market value scales correctly with lot_size."""
        pnl, mv = compute_position_pnl(
            net_quantity=5, average_entry_price=50.0,
            current_price=60.0, lot_size=25,
        )
        assert pnl == (60 - 50) * 5 * 25  # 1250
        assert mv == 60.0 * 5 * 25  # 7500


class TestComputeLegPnl:
    """Test per-leg P&L computation."""

    def test_buy_leg_pnl(self):
        """Buy leg is long."""
        pnl = compute_leg_pnl("buy", 2, 120.0, 100.0, LOT)
        assert pnl == (120 - 100) * 2 * LOT

    def test_sell_leg_pnl(self):
        """Sell leg is short."""
        pnl = compute_leg_pnl("sell", 3, 80.0, 100.0, LOT)
        assert pnl == (100 - 80) * 3 * LOT

    def test_zero_remaining_returns_none(self):
        """Zero remaining quantity returns None."""
        assert compute_leg_pnl("buy", 0, 120.0, 100.0, LOT) is None


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
def logged_in(client):
    return token_store.set_token("tok-valuation-test")


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


# ---- Mock chain data --------------------------------------------------------


def _chain_data(strike, ltp, expiry=EXPIRY):
    """Build a simple option chain response with one strike.
    Uses the canonical adapter format: {strike, call: {ltp}, put: {ltp}}.
    """
    return {
        "chain": [{
            "strike": strike,
            "call": {"ltp": ltp},
            "put": {"ltp": ltp},
        }]
    }


def _chain_data_missing(strike, expiry=EXPIRY):
    """Chain data with no LTP for the given strike."""
    return {
        "chain": [{
            "strike": strike,
            "call": {},
            "put": {},
        }]
    }


# ============================================================================
# Router integration tests
# ============================================================================


class TestValuationEndpoint:
    """GET /paper/positions/valuation integration tests."""

    def test_auth_required(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/paper/positions/valuation")
        assert resp.status_code == 401

    def test_empty_portfolio(self, client, logged_in):
        """No positions returns empty list + zero summary."""
        resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))
        assert resp.status_code == 200
        body = resp.json()
        assert body["positions"] == []
        assert body["summary"]["open_position_count"] == 0
        assert body["summary"]["status"] == "available"

    def test_long_position_live_pnl(self, client, logged_in, db_session):
        """Long position with valid LTP computes correct Live P&L."""
        uid = logged_in
        _account(db_session, uid)
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new=_mock_gateway(25000.0, 120.0),
        ):
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
        assert pv["live_pnl_pct"] == pytest.approx(20.0, abs=0.1)

    def test_short_position_live_pnl(self, client, logged_in, db_session):
        """Short position with valid LTP computes correct Live P&L."""
        uid = logged_in
        _account(db_session, uid)
        pos = _position(db_session, uid, net_quantity=-3, average_entry_price=200.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 180.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        pv = body["positions"][0]
        assert pv["current_price"] == 180.0
        # (200 - 180) × 3 × 65 = 3900
        assert pv["live_pnl"] == 3900.0

    def test_missing_ltp_returns_unavailable(self, client, logged_in, db_session):
        """Missing LTP is marked unavailable, never zero."""
        uid = logged_in
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway_missing(25000.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        pv = body["positions"][0]
        assert pv["current_price"] is None
        assert pv["live_pnl"] is None
        assert pv["market_value"] is None
        assert pv["price_status"] == "unavailable"
        assert body["summary"]["status"] == "unavailable"

    def test_realized_pnl_unchanged(self, client, logged_in, db_session):
        """Live valuation does not alter realized P&L."""
        uid = logged_in
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, realized_pnl=500.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert pv["realized_pnl"] == 500.0

    def test_closed_position_excluded(self, client, logged_in, db_session):
        """Closed positions are not returned."""
        uid = logged_in
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, status="open")
        _position(db_session, uid, net_quantity=0, status="closed", strike=26000.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        assert body["summary"]["open_position_count"] == 1
        assert len(body["positions"]) == 1

    def test_user_isolation(self, client, logged_in, db_session):
        """Another user's positions are invisible to the authenticated user."""
        uid = logged_in
        other_uid = "other-user-isolation"
        _account(db_session, uid)
        _account(db_session, other_uid)
        pos_mine = _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        _position(db_session, other_uid, net_quantity=5, average_entry_price=200.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new=_mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        body = resp.json()
        assert body["summary"]["open_position_count"] == 1
        assert body["positions"][0]["position_id"] == pos_mine.id

    def test_strategy_aggregation(self, client, logged_in, db_session):
        """Strategy-level P&L aggregation from leg exposures."""
        uid = logged_in
        _account(db_session, uid)
        exec1 = _execution(db_session, uid, "exec-1", "Bull Call")
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0,
                        strategy_execution_id="exec-1")
        exp1 = _exposure(db_session, uid, "exec-1", pos.id,
                         action="buy", remaining_quantity=2)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        assert len(pv["strategies"]) >= 1
        sv = pv["strategies"][0]
        assert sv["strategy_tag"] == "Bull Call"
        assert sv["execution_id"] == "exec-1"
        assert sv["live_pnl"] == pytest.approx((120 - 100) * 2 * LOT, abs=1)
        assert len(sv["legs"]) == 1
        assert sv["legs"][0]["action"] == "buy"
        assert sv["legs"][0]["remaining_quantity"] == 2

    def test_leg_pnl_in_strategy(self, client, logged_in, db_session):
        """Leg-level P&L is computed within strategy aggregation."""
        uid = logged_in
        _account(db_session, uid)
        exec1 = _execution(db_session, uid, "exec-1", "Long Call")
        pos = _position(db_session, uid, net_quantity=2, average_entry_price=100.0,
                        strategy_execution_id="exec-1")
        _exposure(db_session, uid, "exec-1", pos.id, action="buy", remaining_quantity=2)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        sv = resp.json()["positions"][0]["strategies"][0]
        leg = sv["legs"][0]
        assert leg["live_pnl"] == pytest.approx((120 - 100) * 2 * LOT, abs=1)
        assert leg["market_value"] == pytest.approx(120.0 * 2 * LOT, abs=1)
        assert leg["current_price"] == 120.0

    def test_shared_instrument_two_strategies(self, client, logged_in, db_session):
        """Two strategies sharing one instrument have separate P&L."""
        uid = logged_in
        _account(db_session, uid)
        exec_a = _execution(db_session, uid, "exec-a", "Strategy A")
        exec_b = _execution(db_session, uid, "exec-b", "Strategy B")
        pos = _position(db_session, uid, net_quantity=7, average_entry_price=100.0)
        _exposure(db_session, uid, "exec-a", pos.id, action="buy",
                  original_quantity=2, remaining_quantity=2)
        _exposure(db_session, uid, "exec-b", pos.id, action="buy",
                  original_quantity=5, remaining_quantity=5)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        pv = resp.json()["positions"][0]
        strats = {s["execution_id"]: s for s in pv["strategies"]}
        # Strategy A: (120 - 100) × 2 × 65 = 2600
        assert strats["exec-a"]["live_pnl"] == pytest.approx(2600.0, abs=1)
        # Strategy B: (120 - 100) × 5 × 65 = 6500
        assert strats["exec-b"]["live_pnl"] == pytest.approx(6500.0, abs=1)
        # Position-level: 2600 + 6500 = 9100
        assert pv["live_pnl"] == pytest.approx(9100.0, abs=1)

    def test_partial_availability(self, client, logged_in, db_session):
        """Mixed LTP availability → partial status."""
        uid = logged_in
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, strike=25000.0,
                  average_entry_price=100.0)
        _position(db_session, uid, net_quantity=1, strike=26000.0,
                  average_entry_price=80.0)
        db_session.commit()

        # 25000 has LTP, 26000 has LTP → all available
        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway_multi(
                {25000.0: 120.0, 26000.0: 90.0}
            ),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))
        assert resp.json()["summary"]["status"] == "available"

    def test_deterministic_ordering(self, client, logged_in, db_session):
        """Positions are returned in a consistent order."""
        uid = logged_in
        _account(db_session, uid)
        for i in range(3):
            _position(db_session, uid, net_quantity=1, strike=24000.0 + i * 500,
                      average_entry_price=100.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway_any(),
        ):
            resp1 = client.get("/paper/positions/valuation", headers=HDR(logged_in))
            resp2 = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        ids1 = [p["position_id"] for p in resp1.json()["positions"]]
        ids2 = [p["position_id"] for p in resp2.json()["positions"]]
        assert ids1 == ids2

    def test_summary_fields(self, client, logged_in, db_session):
        """Summary has all required fields."""
        uid = logged_in
        _account(db_session, uid)
        _position(db_session, uid, net_quantity=2, average_entry_price=100.0)
        db_session.commit()

        with patch(
            "app.services.valuation.gateway",
            new_callable=lambda: _mock_gateway(25000.0, 120.0),
        ):
            resp = client.get("/paper/positions/valuation", headers=HDR(logged_in))

        summary = resp.json()["summary"]
        assert "total_live_pnl" in summary
        assert "total_market_value" in summary
        assert "total_realized_pnl" in summary
        assert "open_position_count" in summary
        assert "positions_with_price" in summary
        assert "positions_unavailable" in summary
        assert "generated_at" in summary
        assert "status" in summary
        assert summary["open_position_count"] == 1
        assert summary["positions_with_price"] == 1
        assert summary["positions_unavailable"] == 0


# ---- Mock helpers -----------------------------------------------------------


class _FakeGateway:
    """Minimal mock for the broker gateway returning predefined LTP values."""

    def __init__(self, strike_ltp_map=None, default_ltp=None, missing_strikes=None):
        self._strike_ltp_map = strike_ltp_map or {}
        self._default_ltp = default_ltp
        self._missing_strikes = missing_strikes or set()

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        chain = []
        for strike, ltp in self._strike_ltp_map.items():
            if strike in self._missing_strikes:
                chain.append({
                    "strike": strike,
                    "call": {},
                    "put": {},
                })
            else:
                chain.append({
                    "strike": strike,
                    "call": {"ltp": ltp},
                    "put": {"ltp": ltp},
                })
        if not self._strike_ltp_map and self._default_ltp is not None:
            # Single strike default
            chain.append({
                "strike": 25000.0,
                "call": {"ltp": self._default_ltp},
                "put": {"ltp": self._default_ltp},
            })
        return {"chain": chain}


class _FakeGatewayMissing:
    """Gateway where the specific strike has no LTP."""

    def __init__(self, missing_strike=25000.0):
        self._missing = missing_strike

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        return {
            "chain": [{
                "strike": self._missing,
                "call": {},
                "put": {},
            }]
        }


class _FakeGatewayAny:
    """Gateway that returns any LTP for any strike."""

    def create(self, broker_id, **kwargs):
        return self

    async def get_option_chain(self, symbol, expiry):
        return {"chain": []}


def _mock_gateway(strike, ltp):
    return _FakeGateway({strike: ltp})


def _mock_gateway_missing(strike):
    return _FakeGatewayMissing(strike)


def _mock_gateway_multi(strike_map):
    return _FakeGateway(strike_map)


def _mock_gateway_any():
    return _FakeGatewayAny()
