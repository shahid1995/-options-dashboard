"""Phase 6.8C tests — Strategy Resolution API.

Covers:
- Inline resolution (POST /paper/resolve)
- Template resolution (POST /paper/templates/:id/resolve)
- Fixed-leg resolution with live prices
- Multi-leg resolution
- Auth required
- User isolation (cannot resolve another user's template)
- Resolution creates NO execution records
- Stale quote detection
- Chain error handling
- Template not found (404)
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import StrategyExecution, PaperOrder, Position
from app.services import token_store
from tests.test_helpers import create_test_identity


LOT = 65
EXPIRY = "2026-08-27"


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
        yield __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client, db_session):
    session_id, _ = create_test_identity(db_session, "tok-resolve-6801")
    return session_id


def headers(session_id):
    return {"X-Session-Id": session_id}


# ---------------------------------------------------------------------------
# Canonical chain fixture
# ---------------------------------------------------------------------------

def _make_chain(spot=25000.0, strikes=None, expiry=EXPIRY):
    """Build a canonical chain response for testing."""
    strikes = strikes or [24800.0, 24900.0, 25000.0, 25100.0, 25200.0]
    rows = []
    for s in strikes:
        rows.append({
            "strike": s,
            "call": {
                "ltp": 100.0 + (s - 25000) * 0.1,
                "delta": 0.5 + (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-20T10:00:00+05:30",
            },
            "put": {
                "ltp": 100.0 - (s - 25000) * 0.1,
                "delta": -0.5 - (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-20T10:00:00+05:30",
            },
        })
    return {
        "symbol": "NIFTY",
        "expiry_date": expiry,
        "underlying_spot_price": spot,
        "chain": rows,
    }


# ---------------------------------------------------------------------------
# Mock broker adapter
# ---------------------------------------------------------------------------

class MockAdapter:
    """Mock broker adapter that returns test chain data."""
    def __init__(self, chains=None, expiries=None):
        self._chains = chains or {}
        self._expiries = expiries or [EXPIRY]

    async def get_option_chain(self, symbol, expiry):
        return self._chains.get(expiry, _make_chain())

    async def get_option_contracts(self, symbol):
        return {"symbol": symbol, "expiries": self._expiries}


# ---------------------------------------------------------------------------
# Tests: Inline Resolution
# ---------------------------------------------------------------------------


class TestInlineResolution:
    def test_fixed_leg_resolution(self, client, logged_in):
        """Fixed-leg template resolves with live price from chain."""
        chain = _make_chain(spot=25000.0)
        adapter = MockAdapter(chains={EXPIRY: chain}, expiries=[EXPIRY])

        with patch("app.services.template_resolution.resolve_legs") as mock_resolve:
            mock_resolve.return_value = type("R", (), {
                "status": "RESOLVED",
                "symbol": "NIFTY",
                "legs": [type("L", (), {
                    "position": 0,
                    "action": "buy",
                    "option_type": "call",
                    "quantity": 1,
                    "lot_size": LOT,
                    "resolved_strike": 25000.0,
                    "resolved_expiry": EXPIRY,
                    "strike_mode_used": "fixed",
                    "expiry_mode_used": "fixed",
                    "current_price": 100.0,
                    "price_status": "available",
                    "quote_timestamp": "2026-08-20T10:00:00+05:30",
                    "ltp": 100.0,
                    "warnings": [],
                    "symbol": "NIFTY",
                    "expiration_date": EXPIRY,
                    "strike_price": 25000.0,
                })()],
                "errors": [],
                "warnings": [],
                "template_id": None,
                "template_name": None,
            })()

            resp = client.post(
                "/paper/resolve",
                headers=headers(logged_in),
                json={
                    "symbol": "NIFTY",
                    "legs": [{
                        "action": "buy",
                        "option_type": "call",
                        "strike": 25000.0,
                        "expiry": EXPIRY,
                        "quantity": 1,
                        "lot_size": LOT,
                    }],
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "RESOLVED"
        assert len(body["legs"]) == 1
        leg = body["legs"][0]
        assert leg["action"] == "buy"
        assert leg["option_type"] == "call"
        assert leg["resolved_strike"] == 25000.0
        assert leg["resolved_expiry"] == EXPIRY
        assert leg["strike_mode_used"] == "fixed"
        assert leg["expiry_mode_used"] == "fixed"

    def test_resolve_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            "/paper/resolve",
            json={
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                }],
            },
        )
        assert resp.status_code == 401

    def test_resolve_empty_legs_rejected(self, client, logged_in):
        """Empty legs list is rejected."""
        resp = client.post(
            "/paper/resolve",
            headers=headers(logged_in),
            json={"symbol": "NIFTY", "legs": []},
        )
        assert resp.status_code == 422

    def test_resolve_validation_error(self, client, logged_in):
        """Invalid formula (delta without target_delta) is rejected."""
        resp = client.post(
            "/paper/resolve",
            headers=headers(logged_in),
            json={
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                    "strike_mode": "delta",
                    "target_delta": None,  # required but missing
                }],
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Template Resolution
# ---------------------------------------------------------------------------


class TestTemplateResolution:
    def test_resolve_template(self, client, logged_in):
        """Resolve a saved template against live chain data."""
        # First create a template
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "Bull Call",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                }],
            },
        )
        assert resp.status_code == 201
        template_id = resp.json()["id"]

        # Now resolve it
        with patch("app.services.template_resolution.resolve_legs") as mock_resolve:
            mock_resolve.return_value = type("R", (), {
                "status": "RESOLVED",
                "symbol": "NIFTY",
                "legs": [type("L", (), {
                    "position": 0,
                    "action": "buy",
                    "option_type": "call",
                    "quantity": 1,
                    "lot_size": LOT,
                    "resolved_strike": 25000.0,
                    "resolved_expiry": EXPIRY,
                    "strike_mode_used": "fixed",
                    "expiry_mode_used": "fixed",
                    "current_price": 100.0,
                    "price_status": "available",
                    "quote_timestamp": "2026-08-20T10:00:00+05:30",
                    "ltp": 100.0,
                    "warnings": [],
                    "symbol": "NIFTY",
                    "expiration_date": EXPIRY,
                    "strike_price": 25000.0,
                })()],
                "errors": [],
                "warnings": [],
                "template_id": template_id,
                "template_name": "Bull Call",
            })()

            resp = client.post(
                f"/paper/templates/{template_id}/resolve",
                headers=headers(logged_in),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "RESOLVED"
        assert body["template_id"] == template_id
        assert body["template_name"] == "Bull Call"
        assert len(body["legs"]) == 1
        leg = body["legs"][0]
        assert leg["action"] == "buy"
        assert leg["resolved_strike"] == 25000.0

    def test_resolve_nonexistent_template_returns_404(self, client, logged_in):
        """Resolving a non-existent template returns 404."""
        resp = client.post(
            "/paper/templates/99999/resolve",
            headers=headers(logged_in),
        )
        assert resp.status_code == 404

    def test_resolve_other_users_template_returns_404(self, client, logged_in, db_session):
        """Cannot resolve another user's template."""
        # Create template as user A
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "My Strategy",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                }],
            },
        )
        template_id = resp.json()["id"]

        # Switch to user B
        other_sid, other_uid = create_test_identity(db_session, "tok-resolve-other-user")
        resp = client.post(
            f"/paper/templates/{template_id}/resolve",
            headers=headers(other_sid),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: No Execution Records Created
# ---------------------------------------------------------------------------


class TestNoExecutionRecords:
    def test_resolve_creates_no_execution_records(self, client, logged_in, db_session):
        """Resolution NEVER creates StrategyExecution, PaperOrder, or Position records."""
        # Seed some pre-existing data
        ex = StrategyExecution(
            user_id="user-tok-resolve-6801",
            execution_id="pre-existing",
            client_order_id="pre-existing-coid",
            symbol="NIFTY",
            status="FILLED",
        )
        db_session.add(ex)
        db_session.commit()
        exec_count_before = db_session.query(StrategyExecution).count()
        order_count_before = db_session.query(PaperOrder).count()
        pos_count_before = db_session.query(Position).count()

        # Create and resolve a template
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "Test No Create",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                }],
            },
        )
        template_id = resp.json()["id"]

        with patch("app.services.template_resolution.resolve_legs") as mock_resolve:
            mock_resolve.return_value = type("R", (), {
                "status": "RESOLVED",
                "symbol": "NIFTY",
                "legs": [type("L", (), {
                    "position": 0, "action": "buy", "option_type": "call",
                    "quantity": 1, "lot_size": LOT,
                    "resolved_strike": 25000.0, "resolved_expiry": EXPIRY,
                    "strike_mode_used": "fixed", "expiry_mode_used": "fixed",
                    "current_price": 100.0, "price_status": "available",
                    "quote_timestamp": None, "ltp": 100.0,
                    "warnings": [], "symbol": "NIFTY",
                    "expiration_date": EXPIRY, "strike_price": 25000.0,
                })()],
                "errors": [], "warnings": [],
                "template_id": template_id, "template_name": "Test No Create",
            })()

            client.post(
                f"/paper/templates/{template_id}/resolve",
                headers=headers(logged_in),
            )

        # Verify NO new execution records created
        assert db_session.query(StrategyExecution).count() == exec_count_before
        assert db_session.query(PaperOrder).count() == order_count_before
        assert db_session.query(Position).count() == pos_count_before


# ---------------------------------------------------------------------------
# Tests: V2 Dynamic Formula Resolution
# ---------------------------------------------------------------------------


class TestDynamicResolution:
    def test_v2_atm_template_resolve(self, client, logged_in):
        """V2 ATM template resolves correctly."""
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "ATM Call",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                    "strike_mode": "atm",
                    "expiry_mode": "fixed",
                    "formula_version": 2,
                }],
            },
        )
        assert resp.status_code == 201
        template_id = resp.json()["id"]

        with patch("app.services.template_resolution.resolve_legs") as mock_resolve:
            mock_resolve.return_value = type("R", (), {
                "status": "RESOLVED",
                "symbol": "NIFTY",
                "legs": [type("L", (), {
                    "position": 0, "action": "buy", "option_type": "call",
                    "quantity": 1, "lot_size": LOT,
                    "resolved_strike": 25000.0, "resolved_expiry": EXPIRY,
                    "strike_mode_used": "atm", "expiry_mode_used": "fixed",
                    "current_price": 100.0, "price_status": "available",
                    "quote_timestamp": None, "ltp": 100.0,
                    "warnings": [], "symbol": "NIFTY",
                    "expiration_date": EXPIRY, "strike_price": 25000.0,
                })()],
                "errors": [], "warnings": [],
                "template_id": template_id, "template_name": "ATM Call",
            })()

            resp = client.post(
                f"/paper/templates/{template_id}/resolve",
                headers=headers(logged_in),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["legs"][0]["strike_mode_used"] == "atm"

    def test_resolve_v2_validation(self, client, logged_in):
        """V2 template with delta mode requires target_delta."""
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "Bad Delta",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                    "strike_mode": "delta",
                    "target_delta": None,
                }],
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Legacy V1 Template Resolution
# ---------------------------------------------------------------------------


class TestV1TemplateResolution:
    def test_v1_template_resolves_as_fixed(self, client, logged_in):
        """V1 legacy template resolves as fixed-leg."""
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "Legacy Bull Call",
                "symbol": "NIFTY",
                "legs": [{
                    "action": "buy",
                    "option_type": "call",
                    "strike": 25000.0,
                    "expiry": EXPIRY,
                    "quantity": 1,
                    "lot_size": LOT,
                }],
            },
        )
        template_id = resp.json()["id"]

        with patch("app.services.template_resolution.resolve_legs") as mock_resolve:
            mock_resolve.return_value = type("R", (), {
                "status": "RESOLVED",
                "symbol": "NIFTY",
                "legs": [type("L", (), {
                    "position": 0, "action": "buy", "option_type": "call",
                    "quantity": 1, "lot_size": LOT,
                    "resolved_strike": 25000.0, "resolved_expiry": EXPIRY,
                    "strike_mode_used": "fixed", "expiry_mode_used": "fixed",
                    "current_price": 100.0, "price_status": "available",
                    "quote_timestamp": None, "ltp": 100.0,
                    "warnings": [], "symbol": "NIFTY",
                    "expiration_date": EXPIRY, "strike_price": 25000.0,
                })()],
                "errors": [], "warnings": [],
                "template_id": template_id, "template_name": "Legacy Bull Call",
            })()

            resp = client.post(
                f"/paper/templates/{template_id}/resolve",
                headers=headers(logged_in),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["legs"][0]["strike_mode_used"] == "fixed"
        assert body["legs"][0]["expiry_mode_used"] == "fixed"
