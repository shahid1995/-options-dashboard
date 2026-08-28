"""Phase 10.2A — Identity & Session Hardening (focused test suite).

Covers the acceptance criteria from PHASE_10_2_IDENTITY_HARDENING.md §12:
  1. Session → user resolution (valid, invalid, expired, revoked, suspended)
  2. CurrentUser dependency (DB-shared) and get_current_user (standalone)
  3. user.id (UUID) used for ownership isolation (not session_id)
  4. Historical GEX endpoints require authentication (P0)
  5. Cross-user isolation for templates, positions, GEX snapshots
  6. Same-user multi-session behavior
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.identity import (
    User,
    UserSession,
    create_session_record,
    get_active_session,
    hash_session_id,
    revoke_session,
)
from app.main import app
from app.services import token_store
from tests.test_helpers import create_test_identity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

    # Patch SessionLocal for endpoints that create their own DB session
    # (e.g. get_current_user in historical_gex).
    import app.db as db_mod
    from sqlalchemy.orm import sessionmaker as _sm
    _orig_sl = db_mod.SessionLocal
    db_mod.SessionLocal = _sm(bind=db_session.get_bind(), autocommit=False, autoflush=False)

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        db_mod.SessionLocal = _orig_sl


def _headers(session_id):
    return {"X-Session-Id": session_id}


# ===========================================================================
# §1: Session → User Resolution
# ===========================================================================


class TestResolveUser:
    """Verify _resolve_user() returns AuthenticatedUser with UUID user_id."""

    def test_valid_session_returns_authenticated_user(self, db_session):
        """A valid session resolves to the correct UUID user_id."""
        from app.routers.deps import _resolve_user

        session_id, user_id = create_test_identity(db_session, "tok-valid")
        result = _resolve_user(db_session, session_id)

        assert result.user_id == user_id
        assert result.access_token == "tok-valid"
        # user_id must be a UUID, not the session_id hash
        assert result.user_id != session_id
        assert len(result.user_id) == 36  # UUID format

    def test_missing_token_raises_401(self, db_session):
        """No token in store → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        # Create a session record but don't put token in store
        session_id = "no-token-session"
        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 401

    def test_no_session_record_raises_401(self, db_session):
        """Token exists but no UserSession row → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        token_store.set_token("tok-no-session")
        # Put a session_id that has no DB record
        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, "nonexistent-session-id")
        assert exc_info.value.status_code == 401

    def test_expired_session_raises_401(self, db_session):
        """Expired UserSession → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        user_id = str(uuid4())
        user = User(
            id=user_id, status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="exp-user",
        )
        db_session.add(user)
        db_session.flush()

        session_id = token_store.set_token("tok-expired")
        record = UserSession(
            user_id=user_id,
            session_hash=hash_session_id(session_id),
            created_at=datetime.now(timezone.utc) - timedelta(hours=48),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=24),
        )
        db_session.add(record)
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 401

    def test_revoked_session_raises_401(self, db_session):
        """Revoked UserSession → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        session_id, user_id = create_test_identity(db_session, "tok-revoked")
        revoke_session(db_session, session_id)

        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 401

    def test_suspended_user_raises_403(self, db_session):
        """Active session for a suspended user → 403."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        session_id = token_store.set_token("tok-suspended")
        user_id = str(uuid4())
        user = User(
            id=user_id, status="suspended", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="susp-user",
        )
        db_session.add(user)
        db_session.flush()
        create_session_record(db_session, user_id, session_id)

        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 403


# ===========================================================================
# §2: CurrentUser dependency (DB-shared) and get_current_user (standalone)
# ===========================================================================


class TestCurrentUserDependency:
    """Test the CurrentUser() dependency class through FastAPI DI."""

    def test_authenticated_request_returns_200(self, client, db_session):
        """Authenticated request to a CurrentUser-protected endpoint succeeds."""
        session_id, _ = create_test_identity(db_session, "tok-dep-test")
        resp = client.get("/paper/templates", headers=_headers(session_id))
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        """Request without session → 401."""
        resp = client.get("/paper/templates")
        assert resp.status_code == 401

    def test_invalid_session_returns_401(self, client):
        """Request with bogus session_id → 401."""
        resp = client.get("/paper/templates", headers=_headers("bogus-session"))
        assert resp.status_code == 401

    def test_cookie_fallback(self, client, db_session):
        """Session via cookie (not header) still resolves."""
        session_id, _ = create_test_identity(db_session, "tok-cookie")
        resp = client.get("/paper/templates", cookies={"session_id": session_id})
        assert resp.status_code == 200


# ===========================================================================
# §3: user.id (UUID) for ownership isolation
# ===========================================================================


class TestUserIdOwnership:
    """Verify user.id (UUID) is used for ownership, not session_id."""

    def test_paper_positions_use_uuid_user_id(self, client, db_session):
        """Executed positions are owned by the UUID user_id."""
        from app.models import Position

        session_id, user_id = create_test_identity(db_session, "tok-uid-test")

        # Create a position directly via DB with the UUID user_id
        pos = Position(
            user_id=user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=1,
            average_entry_price=100.0, lot_size=50, status="open",
        )
        db_session.add(pos)
        db_session.commit()

        # The user can see their own position (ownership verified via DB)
        resp = client.get("/paper/positions", headers=_headers(session_id))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        # Verify the position in DB is owned by the UUID user_id
        from app.models import Position
        pos = db_session.query(Position).first()
        assert pos.user_id == user_id

    def test_different_session_same_user_sees_same_data(self, client, db_session):
        """Two sessions for the same user see the same data."""
        from app.models import Position

        user_id = str(uuid4())
        user = User(
            id=user_id, status="active", identity_source="upstox",
            broker_provider="UPSTOX", broker_user_id="multi-sess",
        )
        db_session.add(user)
        db_session.flush()

        sid_a = token_store.set_token("tok-sess-a")
        create_session_record(db_session, user_id, sid_a)

        sid_b = token_store.set_token("tok-sess-b")
        create_session_record(db_session, user_id, sid_b)

        pos = Position(
            user_id=user_id, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=1,
            average_entry_price=100.0, lot_size=50, status="open",
        )
        db_session.add(pos)
        db_session.commit()

        # token_store is single-session (last-set wins), so we can't test
        # two simultaneous sessions with the in-memory store. But the DB
        # records confirm both sessions map to the same user.
        assert get_active_session(db_session, sid_a) is not None
        assert get_active_session(db_session, sid_b) is not None
        assert get_active_session(db_session, sid_a).user_id == user_id
        assert get_active_session(db_session, sid_b).user_id == user_id


# ===========================================================================
# §4: Historical GEX authentication (P0)
# ===========================================================================


class TestHistoricalGexAuth:
    """All historical_gex endpoints require authentication."""

    @pytest.mark.parametrize("endpoint", [
        "/gex/history",
        "/gex/regime",
        "/gex/flip",
        "/gex/walls",
        "/gex/analytics",
        "/gex/stats",
        "/gex/data-quality",
        "/gex/research",
    ])
    def test_unauthenticated_returns_401(self, client, endpoint):
        resp = client.get(endpoint)
        assert resp.status_code == 401, f"{endpoint} should require auth"

    @pytest.mark.parametrize("endpoint", [
        "/gex/history",
        "/gex/regime",
        "/gex/flip",
        "/gex/walls",
        "/gex/analytics",
        "/gex/stats",
        "/gex/data-quality",
    ])
    def test_authenticated_access_succeeds(self, client, db_session, endpoint):
        """Authenticated request to historical GEX endpoint succeeds (200)."""
        session_id, _ = create_test_identity(db_session, "tok-hgex")
        resp = client.get(endpoint, headers=_headers(session_id))
        assert resp.status_code == 200, f"{endpoint} should return 200 for auth user"


# ===========================================================================
# §5: Cross-user isolation
# ===========================================================================


class TestCrossUserIsolation:
    """User A's data is invisible to User B."""

    def test_templates_isolated(self, client, db_session):
        """User B cannot see User A's templates."""
        sid_a, uid_a = create_test_identity(db_session, "tok-iso-a")
        resp = client.post(
            "/paper/templates",
            headers=_headers(sid_a),
            json={"name": "Private A", "symbol": "NIFTY", "legs": [{
                "action": "buy", "option_type": "call", "strike": 25000,
                "expiry": "2026-08-28", "quantity": 1, "lot_size": 50,
            }]},
        )
        assert resp.status_code == 201
        tpl_id = resp.json()["id"]

        sid_b, uid_b = create_test_identity(db_session, "tok-iso-b")
        resp = client.get(f"/paper/templates/{tpl_id}", headers=_headers(sid_b))
        assert resp.status_code == 404

    def test_positions_isolated(self, client, db_session):
        """User B cannot see User A's positions."""
        from app.models import Position

        sid_a, uid_a = create_test_identity(db_session, "tok-iso-pos-a")
        pos = Position(
            user_id=uid_a, symbol="NIFTY", expiry="2026-08-28",
            strike=25000.0, option_type="call", net_quantity=1,
            average_entry_price=100.0, lot_size=50, status="open",
        )
        db_session.add(pos)
        db_session.commit()

        sid_b, uid_b = create_test_identity(db_session, "tok-iso-pos-b")
        resp = client.get("/paper/positions", headers=_headers(sid_b))
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_gex_snapshots_isolated(self, client, db_session):
        """User B cannot see User A's GEX snapshots."""
        from app.services.gex_history import record_gex_snapshot, get_gex_snapshots

        sid_a, uid_a = create_test_identity(db_session, "tok-iso-gex-a")
        snap = {
            "symbol": "NIFTY", "spot": 25000.0, "methodology": "GEX_STANDARD_V1",
            "callGex": 100.0, "putGex": -50.0, "netGex": 50.0,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
        }
        record_gex_snapshot(db_session, snap, owner_id=uid_a)
        db_session.commit()

        sid_b, uid_b = create_test_identity(db_session, "tok-iso-gex-b")
        snaps = get_gex_snapshots(db_session, symbol="NIFTY", owner_id=uid_b)
        assert len(snaps) == 0

    def test_trade_detail_isolated(self, client, db_session):
        """User B cannot see User A's trade detail."""
        from app.models import StrategyExecution

        sid_a, uid_a = create_test_identity(db_session, "tok-iso-trade-a")
        ex = StrategyExecution(
            user_id=uid_a, execution_id="iso-exec-001",
            client_order_id="iso-coid-001", symbol="NIFTY", status="FILLED",
        )
        db_session.add(ex)
        db_session.commit()

        sid_b, uid_b = create_test_identity(db_session, "tok-iso-trade-b")
        resp = client.get(
            "/paper/analytics/trades/iso-exec-001", headers=_headers(sid_b)
        )
        assert resp.status_code == 404


# ===========================================================================
# §6: Token store integration
# ===========================================================================


class TestTokenStoreIntegration:
    """Token store + UserSession work together through deps."""

    def test_token_store_and_session_both_required(self, db_session):
        """Token in store but no session record → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        token_store.set_token("tok-orphan")
        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, "orphan-session-id")
        assert exc_info.value.status_code == 401

    def test_session_record_but_no_token_raises_401(self, db_session):
        """Session record exists but no token in store → 401."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        session_id, user_id = create_test_identity(db_session, "tok-gone")
        # Clear the token (simulating restart)
        token_store.clear_token()

        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 401

    def test_revoke_session_blocks_resolution(self, db_session):
        """Revoking a session prevents future resolution."""
        from app.routers.deps import _resolve_user
        from fastapi import HTTPException

        session_id, user_id = create_test_identity(db_session, "tok-revoke")
        # Works before revocation
        result = _resolve_user(db_session, session_id)
        assert result.user_id == user_id

        # Revoke
        revoke_session(db_session, session_id)

        # Fails after revocation
        with pytest.raises(HTTPException) as exc_info:
            _resolve_user(db_session, session_id)
        assert exc_info.value.status_code == 401


# ===========================================================================
# §7: Login/logout round-trip
# ===========================================================================


class TestLoginLogoutRoundTrip:
    """Verify login creates identity and logout revokes it."""

    def test_me_endpoint_returns_user_info(self, client, db_session):
        """GET /auth/me returns the authenticated user's profile."""
        session_id, user_id = create_test_identity(db_session, "tok-me")
        resp = client.get("/auth/me", headers=_headers(session_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_id
        assert body["status"] == "active"

    def test_me_without_auth_returns_401(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_logout_revokes_session(self, client, db_session):
        """POST /auth/logout revokes the session."""
        session_id, _ = create_test_identity(db_session, "tok-logout")
        resp = client.post("/auth/logout", headers=_headers(session_id))
        assert resp.status_code == 200

        # Session should now be revoked
        assert get_active_session(db_session, session_id) is None
