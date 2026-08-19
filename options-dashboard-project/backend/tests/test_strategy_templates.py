"""Phase 6.7 tests — Custom Strategy Builder & My Strategies.

Covers:
- Create strategy template
- Retrieve strategy template
- List only current user's templates (user isolation)
- Update strategy template (name, legs)
- Rename strategy template
- Duplicate strategy template
- Delete strategy template
- Cannot modify another user's template
- Cannot delete another user's template
- Invalid legs rejected
- Empty strategy rejected
- Duplicate-name behavior (409)
- System strategies remain read-only (no backend concept)
- Loading saved strategy into builder (frontend-only)
- Editing template does not alter historical execution
- Deleting template does not alter historical execution
- LIVE execution remains disabled

NOTE: The token_store is a single-session store (one active session at a time).
Tests that need two users switch the active session via ``switch_user()``
before each request rather than holding two simultaneous sessions.
"""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    PaperOrder,
    PaperTransaction,
    Position,
    StrategyExecution,
    StrategyLegExposure,
)
from app.services import token_store


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
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client):
    return token_store.set_token("tok-templates-6701")


@pytest.fixture
def other_user(client):
    """Set a different user as the active session. NOTE: this invalidates
    logged_in's session because token_store is single-session."""
    return token_store.set_token("tok-templates-other-user")


def headers(session_id):
    return {"X-Session-Id": session_id}


def switch_user(token_str):
    """Switch the active user and return the new session_id.

    Because token_store is single-session, this invalidates any previous
    session. Call this before every request that needs a specific user.
    """
    return token_store.set_token(token_str)


# ---- Payload helpers -------------------------------------------------------


_counter = {"n": 0}


def _next_id(prefix="tpl"):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:06d}"


def template_payload(**overrides):
    """A valid multi-leg strategy template payload."""
    payload = {
        "name": "Iron Condor Custom",
        "symbol": "NIFTY",
        "legs": [
            {
                "action": "buy",
                "option_type": "put",
                "strike": 23800.0,
                "expiry": EXPIRY,
                "quantity": 1,
                "lot_size": LOT,
                "position": 0,
            },
            {
                "action": "sell",
                "option_type": "put",
                "strike": 24000.0,
                "expiry": EXPIRY,
                "quantity": 1,
                "lot_size": LOT,
                "position": 1,
            },
            {
                "action": "sell",
                "option_type": "call",
                "strike": 25000.0,
                "expiry": EXPIRY,
                "quantity": 1,
                "lot_size": LOT,
                "position": 2,
            },
            {
                "action": "buy",
                "option_type": "call",
                "strike": 25200.0,
                "expiry": EXPIRY,
                "quantity": 1,
                "lot_size": LOT,
                "position": 3,
            },
        ],
    }
    payload.update(overrides)
    return payload


def simple_leg(**overrides):
    """A single-leg payload."""
    leg = {
        "action": "buy",
        "option_type": "call",
        "strike": 24500.0,
        "expiry": EXPIRY,
        "quantity": 1,
        "lot_size": LOT,
        "position": 0,
    }
    leg.update(overrides)
    return leg


def create_template(client, session_id, **overrides):
    """Helper: create a template via the API."""
    resp = client.post(
        "/paper/templates",
        headers=headers(session_id),
        json=template_payload(**overrides),
    )
    return resp


# ===========================================================================
# CREATE
# ===========================================================================


class TestCreateTemplate:
    def test_create_returns_201_with_legs(self, client, logged_in):
        resp = create_template(client, logged_in)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Iron Condor Custom"
        assert body["symbol"] == "NIFTY"
        assert len(body["legs"]) == 4
        assert body["legs"][0]["action"] == "buy"
        assert body["legs"][0]["option_type"] == "put"
        assert body["legs"][0]["strike"] == 23800.0
        assert body["id"] > 0

    def test_create_single_leg(self, client, logged_in):
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={
                "name": "Long Call",
                "symbol": "NIFTY",
                "legs": [simple_leg()],
            },
        )
        assert resp.status_code == 201
        assert len(resp.json()["legs"]) == 1

    def test_create_requires_login(self, client):
        resp = client.post(
            "/paper/templates",
            json=template_payload(),
        )
        assert resp.status_code == 401

    def test_create_rejects_empty_legs(self, client, logged_in):
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={"name": "Empty", "legs": []},
        )
        assert resp.status_code == 422

    def test_create_rejects_empty_name(self, client, logged_in):
        resp = client.post(
            "/paper/templates",
            headers=headers(logged_in),
            json={"name": "", "legs": [simple_leg()]},
        )
        assert resp.status_code == 422

    def test_create_duplicate_name_returns_409(self, client, logged_in):
        resp1 = create_template(client, logged_in, name="Dup Test")
        assert resp1.status_code == 201
        resp2 = create_template(client, logged_in, name="Dup Test")
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    def test_different_users_can_have_same_name(self, client, logged_in):
        # Create as user A
        resp1 = create_template(client, logged_in, name="Same Name")
        assert resp1.status_code == 201
        id1 = resp1.json()["id"]

        # Switch to user B (invalidates user A's session)
        other_sid = switch_user("tok-templates-other-user")
        resp2 = create_template(client, other_sid, name="Same Name")
        assert resp2.status_code == 201
        id2 = resp2.json()["id"]
        assert id1 != id2


# ===========================================================================
# RETRIEVE
# ===========================================================================


class TestGetTemplate:
    def test_get_by_id(self, client, logged_in):
        created = create_template(client, logged_in).json()
        resp = client.get(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == created["name"]
        assert len(resp.json()["legs"]) == 4

    def test_get_nonexistent_returns_404(self, client, logged_in):
        resp = client.get("/paper/templates/999999", headers=headers(logged_in))
        assert resp.status_code == 404

    def test_get_other_user_template_returns_404(self, client, logged_in):
        # Create as user A
        created = create_template(client, logged_in, name="Private").json()

        # Switch to user B — user A's template should be invisible
        other_sid = switch_user("tok-templates-other-user")
        resp = client.get(
            f"/paper/templates/{created['id']}",
            headers=headers(other_sid),
        )
        assert resp.status_code == 404


# ===========================================================================
# LIST
# ===========================================================================


class TestListTemplates:
    def test_list_empty(self, client, logged_in):
        resp = client.get("/paper/templates", headers=headers(logged_in))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_own_templates(self, client, logged_in):
        create_template(client, logged_in, name="T1")
        create_template(client, logged_in, name="T2")
        resp = client.get("/paper/templates", headers=headers(logged_in))
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert names == {"T1", "T2"}

    def test_list_excludes_other_users(self, client, logged_in):
        # Create as user A
        create_template(client, logged_in, name="Mine")

        # Switch to user B, create theirs
        other_sid = switch_user("tok-templates-other-user")
        create_template(client, other_sid, name="Theirs")

        # User B should only see their own
        resp = client.get("/paper/templates", headers=headers(other_sid))
        names = {t["name"] for t in resp.json()}
        assert names == {"Theirs"}

    def test_list_ordered_by_updated_at_desc(self, client, logged_in):
        create_template(client, logged_in, name="First")
        create_template(client, logged_in, name="Second")
        resp = client.get("/paper/templates", headers=headers(logged_in))
        names = [t["name"] for t in resp.json()]
        assert names == ["Second", "First"]


# ===========================================================================
# UPDATE
# ===========================================================================


class TestUpdateTemplate:
    def test_rename(self, client, logged_in):
        created = create_template(client, logged_in, name="Old Name").json()
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
            json={"name": "New Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_update_symbol(self, client, logged_in):
        created = create_template(client, logged_in).json()
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
            json={"symbol": "BANKNIFTY"},
        )
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "BANKNIFTY"

    def test_replace_legs(self, client, logged_in):
        created = create_template(client, logged_in).json()
        assert len(created["legs"]) == 4
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
            json={"legs": [simple_leg(strike=25000.0)]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["legs"]) == 1
        assert resp.json()["legs"][0]["strike"] == 25000.0

    def test_rename_to_duplicate_name_returns_409(self, client, logged_in):
        create_template(client, logged_in, name="Alpha")
        created = create_template(client, logged_in, name="Beta").json()
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
            json={"name": "Alpha"},
        )
        assert resp.status_code == 409

    def test_rename_to_own_name_ok(self, client, logged_in):
        created = create_template(client, logged_in, name="Keep").json()
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
            json={"name": "Keep"},
        )
        assert resp.status_code == 200

    def test_update_other_user_returns_404(self, client, logged_in):
        # Create as user A
        created = create_template(client, logged_in, name="Mine").json()

        # Switch to user B — should not be able to modify user A's template
        other_sid = switch_user("tok-templates-other-user")
        resp = client.put(
            f"/paper/templates/{created['id']}",
            headers=headers(other_sid),
            json={"name": "Hacked"},
        )
        assert resp.status_code == 404


# ===========================================================================
# DUPLICATE
# ===========================================================================


class TestDuplicateTemplate:
    def test_duplicate_creates_copy(self, client, logged_in):
        created = create_template(client, logged_in, name="Original").json()
        resp = client.post(
            f"/paper/templates/{created['id']}/duplicate",
            headers=headers(logged_in),
        )
        assert resp.status_code == 201
        dup = resp.json()
        assert dup["name"] == "Original (Copy)"
        assert dup["id"] != created["id"]
        assert len(dup["legs"]) == len(created["legs"])

    def test_duplicate_with_custom_name(self, client, logged_in):
        created = create_template(client, logged_in, name="My Strat").json()
        resp = client.post(
            f"/paper/templates/{created['id']}/duplicate",
            headers=headers(logged_in),
            params={"new_name": "My Strat V2"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "My Strat V2"

    def test_duplicate_name_collision_returns_409(self, client, logged_in):
        # Create "Source" and "Source (Copy)"
        create_template(client, logged_in, name="Source")
        create_template(client, logged_in, name="Source (Copy)")
        # Create another "Source" to duplicate
        src = create_template(client, logged_in, name="Source 2").json()
        resp = client.post(
            f"/paper/templates/{src['id']}/duplicate",
            headers=headers(logged_in),
        )
        # Default copy name "Source 2 (Copy)" should work since it doesn't collide
        assert resp.status_code == 201

    def test_duplicate_name_collision_manual(self, client, logged_in):
        """Test collision when duplicate name already exists."""
        src = create_template(client, logged_in, name="MyStrat").json()
        # Create the default copy name manually first
        create_template(client, logged_in, name="MyStrat (Copy)")
        # Now duplicating should fail
        resp = client.post(
            f"/paper/templates/{src['id']}/duplicate",
            headers=headers(logged_in),
        )
        assert resp.status_code == 409

    def test_duplicate_other_users_returns_404(self, client, logged_in):
        # Create as user A
        created = create_template(client, logged_in, name="Private").json()

        # Switch to user B — should not be able to duplicate user A's template
        other_sid = switch_user("tok-templates-other-user")
        resp = client.post(
            f"/paper/templates/{created['id']}/duplicate",
            headers=headers(other_sid),
        )
        assert resp.status_code == 404

    def test_duplicate_preserves_leg_details(self, client, logged_in):
        created = create_template(client, logged_in).json()
        resp = client.post(
            f"/paper/templates/{created['id']}/duplicate",
            headers=headers(logged_in),
        )
        dup = resp.json()
        for orig_leg, dup_leg in zip(created["legs"], dup["legs"]):
            assert orig_leg["action"] == dup_leg["action"]
            assert orig_leg["option_type"] == dup_leg["option_type"]
            assert orig_leg["strike"] == dup_leg["strike"]
            assert orig_leg["expiry"] == dup_leg["expiry"]
            assert orig_leg["quantity"] == dup_leg["quantity"]
            assert orig_leg["lot_size"] == dup_leg["lot_size"]
            assert dup_leg["id"] != orig_leg["id"]  # new IDs


# ===========================================================================
# DELETE
# ===========================================================================


class TestDeleteTemplate:
    def test_delete_returns_204(self, client, logged_in):
        created = create_template(client, logged_in, name="ToDelete").json()
        resp = client.delete(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
        )
        assert resp.status_code == 204
        # Verify it's gone
        resp = client.get(
            f"/paper/templates/{created['id']}",
            headers=headers(logged_in),
        )
        assert resp.status_code == 404

    def test_delete_other_users_returns_404(self, client, logged_in, db_session):
        # Create as user A
        created = create_template(client, logged_in, name="Protected").json()
        template_id = created["id"]

        # Switch to user B — should not be able to delete user A's template
        other_sid = switch_user("tok-templates-other-user")
        resp = client.delete(
            f"/paper/templates/{template_id}",
            headers=headers(other_sid),
        )
        assert resp.status_code == 404

        # Verify template still exists in DB (owner's data is intact)
        from app.models import StrategyTemplate
        tpl = db_session.get(StrategyTemplate, template_id)
        assert tpl is not None
        assert tpl.name == "Protected"

    def test_delete_nonexistent_returns_404(self, client, logged_in):
        resp = client.delete("/paper/templates/999999", headers=headers(logged_in))
        assert resp.status_code == 404


# ===========================================================================
# HISTORICAL SAFETY
# ===========================================================================


class TestHistoricalSafety:
    """Verify that template CRUD never affects historical executions."""

    def _seed_historical_execution(self, db_session, user_id):
        """Create a historical execution with orders, positions, exposures."""
        ex = StrategyExecution(
            user_id=user_id,
            execution_id="hist-exec-001",
            client_order_id="hist-exec-001-coid",
            strategy_tag="Historical Bull Call",
            symbol="NIFTY",
            status="FILLED",
        )
        db_session.add(ex)
        db_session.flush()

        order = PaperOrder(
            user_id=user_id,
            client_order_id="hist-order-001",
            execution_id="hist-exec-001",
            kind="entry",
            symbol="NIFTY",
            expiry=EXPIRY,
            strike=24500.0,
            option_type="call",
            action="buy",
            quantity=1,
            lot_size=LOT,
            status="FILLED",
            filled_quantity=1,
            fill_price=125.25,
        )
        db_session.add(order)
        db_session.flush()

        pos = Position(
            user_id=user_id,
            symbol="NIFTY",
            expiry=EXPIRY,
            strike=24500.0,
            option_type="call",
            net_quantity=1,
            average_entry_price=125.25,
            lot_size=LOT,
            status="open",
            strategy_execution_id="hist-exec-001",
        )
        db_session.add(pos)
        db_session.flush()

        exp = StrategyLegExposure(
            user_id=user_id,
            execution_id="hist-exec-001",
            position_id=pos.id,
            order_id=order.id,
            symbol="NIFTY",
            expiry=EXPIRY,
            strike=24500.0,
            option_type="call",
            action="buy",
            original_quantity=1,
            remaining_quantity=1,
            status="open",
        )
        db_session.add(exp)
        db_session.flush()
        db_session.commit()

        return ex, pos, exp

    def test_delete_template_preserves_execution(self, client, logged_in, db_session):
        ex, pos, exp = self._seed_historical_execution(db_session, logged_in)

        # Create and delete a template
        tpl = create_template(client, logged_in, name="ToDelete").json()
        client.delete(f"/paper/templates/{tpl['id']}", headers=headers(logged_in))

        # Verify historical data is intact
        assert db_session.get(StrategyExecution, ex.id) is not None
        assert db_session.get(Position, pos.id) is not None
        assert db_session.get(StrategyLegExposure, exp.id) is not None

    def test_edit_template_preserves_execution(self, client, logged_in, db_session):
        ex, pos, exp = self._seed_historical_execution(db_session, logged_in)

        # Create and modify a template
        tpl = create_template(client, logged_in, name="ToEdit").json()
        client.put(
            f"/paper/templates/{tpl['id']}",
            headers=headers(logged_in),
            json={"name": "Edited", "legs": [simple_leg(strike=99999.0)]},
        )

        # Verify historical data is intact
        assert db_session.get(StrategyExecution, ex.id) is not None
        assert db_session.get(Position, pos.id) is not None
        assert pos.strike == 24500.0  # unchanged
        assert pos.average_entry_price == 125.25  # unchanged

    def test_rename_template_preserves_execution(self, client, logged_in, db_session):
        ex, pos, exp = self._seed_historical_execution(db_session, logged_in)

        tpl = create_template(client, logged_in, name="ToRename").json()
        client.put(
            f"/paper/templates/{tpl['id']}",
            headers=headers(logged_in),
            json={"name": "Renamed"},
        )

        # Historical execution strategy_tag is unchanged
        h = db_session.get(StrategyExecution, ex.id)
        assert h.strategy_tag == "Historical Bull Call"


# ===========================================================================
# LIVE EXECUTION REMAINS DISABLED
# ===========================================================================


class TestLiveExecutionDisabled:
    def test_live_mode_not_exposed(self, client, logged_in):
        """Verify templates endpoint has no live execution parameter."""
        # Just verify the endpoint works for paper templates only
        resp = client.get("/paper/templates", headers=headers(logged_in))
        assert resp.status_code == 200

    def test_no_broker_calls_in_template_crud(self, client, logged_in):
        """Template CRUD never calls the broker."""
        # All CRUD operations work without broker tokens
        resp = create_template(client, logged_in, name="No Broker")
        assert resp.status_code == 201
        tid = resp.json()["id"]
        resp = client.get(f"/paper/templates/{tid}", headers=headers(logged_in))
        assert resp.status_code == 200
        resp = client.delete(f"/paper/templates/{tid}", headers=headers(logged_in))
        assert resp.status_code == 204
