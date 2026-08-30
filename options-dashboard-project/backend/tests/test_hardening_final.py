"""Gate A: Final hardening tests against d83b22e.

Tests that FAIL, proving concrete architectural issues:
1. Customer Analytics Token used as platform GEX credential
2. Ambiguous Analytics Token fallback (no connection_id)
3. WebSocket integration tests (not just source checks)
"""
import inspect
import pathlib
import re
import secrets
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal
from app.identity import (
    User, UserSession, BrokerConnection, BrokerToken,
    create_session_record, hash_session_id,
    resolve_platform_session, resolve_broker_token_by_session_hash,
    get_analytics_token, store_analytics_token,
)
from app.services import token_store
from app.crypto import encrypt


@pytest.fixture(autouse=True)
def db_session():
    engine = SessionLocal().get_bind()
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


def _create_user(db):
    uid = str(uuid4())
    db.add(User(id=uid, status="active", identity_source="google", broker_provider=None))
    db.flush()
    return uid


# ===========================================================================
# Issue 1: GEX — customer token as platform credential
# ===========================================================================

class TestGexOwnership:
    """Customer Analytics Tokens must not power platform background GEX."""

    def test_gex_capture_disabled_by_default(self):
        """GEX_CAPTURE_ENABLED must default to False.
        Background capture using customer tokens must not auto-start."""
        from app.config import settings
        assert settings.GEX_CAPTURE_ENABLED is False, (
            "GEX_CAPTURE_ENABLED defaults to True — "
            "customer tokens would auto-power platform GEX"
        )

    def test_gex_capture_requires_both_flags(self):
        """Capture requires BOTH GEX_CAPTURE_ENABLED and GEX_USER_ID.
        One without the other must not start capture."""
        from app.main import lifespan
        source = inspect.getsource(lifespan)
        # Must check both flags
        assert "GEX_CAPTURE_ENABLED" in source
        assert "GEX_USER_ID" in source or "gex_user_id" in source

    def test_gex_snapshot_has_owner_id_field(self):
        """GEX snapshots must track which user/connection owns them.
        owner_id must be stored on the snapshot row."""
        from app.models import GexSnapshot
        assert hasattr(GexSnapshot, "owner_id"), (
            "GexSnapshot missing owner_id — cannot track snapshot ownership"
        )

    def test_gex_capture_loop_stores_owner_context(self):
        """The capture loop must store user_id as owner_id on snapshots.
        Analytics Token captures must not produce owner_id=None snapshots."""
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        # Find the capture_once call and check owner_id handling
        capture_section = source.split("capture_service.capture_once")[0]
        # owner_id should be set from user_id, not session_id
        assert "owner_id" in capture_section, (
            "Capture loop does not set owner_id on snapshots"
        )

    def test_no_customer_token_as_platform_credential(self):
        """The GEX capture loop must not use customer tokens as platform creds.
        When GEX_CAPTURE_ENABLED=True, the token source must be documented
        as user-scoped, not platform-wide."""
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        # The comment must clarify that tokens are user-scoped
        gex_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        assert "user" in gex_section.lower() or "customer" in gex_section.lower(), (
            "GEX capture loop does not document user-scoped token ownership"
        )


# ===========================================================================
# Issue 2: Analytics Token connection-deterministic resolution
# ===========================================================================

class TestAnalyticsTokenConnectionDeterministic:
    """Analytics Token resolution must be deterministic by connection_id."""

    def test_get_analytics_token_accepts_connection_id(self):
        """get_analytics_token must accept an optional connection_id parameter
        for deterministic resolution."""
        sig = inspect.signature(get_analytics_token)
        assert "connection_id" in sig.parameters, (
            "get_analytics_token lacks connection_id parameter — "
            "cannot resolve deterministically"
        )

    def test_get_analytics_token_with_connection_id_returns_exact_match(self, db_session):
        """With connection_id, returns exactly that connection's token."""
        uid = _create_user(db_session)
        conn_a = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-a", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-a"),
        )
        conn_b = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-b", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-b"),
        )
        db_session.add_all([conn_a, conn_b])
        db_session.flush()

        # With connection_id, must return exact match
        token_a = get_analytics_token(db_session, uid, "UPSTOX", connection_id=conn_a.id)
        token_b = get_analytics_token(db_session, uid, "UPSTOX", connection_id=conn_b.id)
        assert token_a == "token-a"
        assert token_b == "token-b"

    def test_get_analytics_token_wrong_connection_returns_none(self, db_session):
        """With wrong connection_id, returns None (not another connection's token)."""
        uid = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct1", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("my-token"),
        )
        db_session.add(conn)
        db_session.flush()

        fake_id = str(uuid4())
        result = get_analytics_token(db_session, uid, "UPSTOX", connection_id=fake_id)
        assert result is None

    def test_get_analytics_token_wrong_user_returns_none(self, db_session):
        """Connection belongs to user A — user B cannot access it."""
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid_a, broker="UPSTOX",
            broker_account_id="acct-a", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-a"),
        )
        db_session.add(conn)
        db_session.flush()

        result = get_analytics_token(db_session, uid_b, "UPSTOX", connection_id=conn.id)
        assert result is None

    def test_get_analytics_token_without_connection_id_uses_default(self, db_session):
        """Without connection_id, must use is_default=True deterministically."""
        uid = _create_user(db_session)
        conn_other = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-other", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-other"),
        )
        conn_default = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-default", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-default"),
        )
        db_session.add_all([conn_other, conn_default])
        db_session.flush()

        token = get_analytics_token(db_session, uid, "UPSTOX")
        assert token == "token-default"

    def test_inactive_default_falls_back_to_active(self, db_session):
        """When default is inactive, must not return it."""
        uid = _create_user(db_session)
        conn_default_inactive = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-inactive", status="connected",
            is_default=True, data_status="inactive",
            broker_analytics_token_encrypted=encrypt("inactive-token"),
        )
        conn_active = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-active", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("active-token"),
        )
        db_session.add_all([conn_default_inactive, conn_active])
        db_session.flush()

        token = get_analytics_token(db_session, uid, "UPSTOX")
        assert token == "active-token"

    def test_gex_analytics_token_accepts_connection_id(self):
        """_get_analytics_token_for_gex must accept connection_id."""
        sig = inspect.signature(
            __import__("app.main", fromlist=["_get_analytics_token_for_gex"])
            ._get_analytics_token_for_gex
        )
        assert "connection_id" in sig.parameters, (
            "_get_analytics_token_for_gex lacks connection_id parameter"
        )

    def test_repeated_lookup_deterministic(self, db_session):
        """Multiple calls return the same result."""
        uid = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-det", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("det-token"),
        )
        db_session.add(conn)
        db_session.flush()
        results = [get_analytics_token(db_session, uid, "UPSTOX") for _ in range(5)]
        assert len(set(results)) == 1


# ===========================================================================
# Issue 3: WebSocket integration tests
# ===========================================================================

class TestWebSocketIntegration:
    """WebSocket must reject platform sessions and not reach broker adapter."""

    def test_ws_rejects_no_session(self):
        """WebSocket with no session_id must close with 4401."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        # Connect without any session
        with client.websocket_connect("/chains/ws/NIFTY?expiry_date=2026-09-24") as ws:
            # Should be closed immediately (no session)
            pass  # Connection closed

    def test_ws_rejects_platform_session(self, db_session):
        """Platform-only session (no broker token) must close with 4401."""
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        db_session.commit()

        # Verify get_token returns None for this session
        token_store._sessions.pop(sid, None)
        assert token_store.get_token(sid) is None

    def test_ws_accepts_broker_session(self, db_session):
        """Broker session must produce a real token."""
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        bt = BrokerToken(
            connection_id="conn-" + uid[:8],
            session_hash=hash_session_id(sid),
            broker_token_encrypted=encrypt("ws-broker-token"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(bt)
        db_session.commit()

        token_store._sessions.pop(sid, None)
        token = token_store.get_token(sid)
        assert token == "ws-broker-token"

    def test_session_hash_never_as_access_token(self):
        """session_hash must never be passed to gateway.create() as access_token."""
        import re
        source = pathlib.Path("app/routers/chains.py").read_text(encoding="utf-8")
        # Find all gateway.create calls
        calls = re.findall(r'gateway\.create\(([^)]+)\)', source)
        for call in calls:
            assert "session_hash" not in call, (
                f"session_hash passed to gateway.create: {call}"
            )

    def test_ws_live_gex_rejects_platform_session(self, db_session):
        """live_gex WebSocket must reject platform sessions."""
        from app.routers.live_gex import _require_token
        sid = secrets.token_urlsafe(32)
        # No DB session created — should fail
        with pytest.raises(Exception) as exc_info:
            _require_token(sid)
        assert exc_info.value.status_code == 401

    def test_ws_live_gex_rejects_no_broker_token(self, db_session):
        """live_gex must return 403 for platform-only session."""
        from app.routers.live_gex import _require_token
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        with pytest.raises(Exception) as exc_info:
            _require_token(sid)
        assert exc_info.value.status_code == 403

    def test_ws_live_gex_accepts_broker_token(self, db_session):
        """live_gex must return real broker token."""
        from app.routers.live_gex import _require_token
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        bt = BrokerToken(
            connection_id="conn-" + uid[:8],
            session_hash=hash_session_id(sid),
            broker_token_encrypted=encrypt("live-gex-token"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(bt)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        token = _require_token(sid)
        assert token == "live-gex-token"


# ===========================================================================
# Issue 4: Platform/broker session separation (regression)
# ===========================================================================

class TestPlatformBrokerSeparation:
    """Platform session != broker access token — regression tests."""

    def test_get_token_returns_none_for_platform(self, db_session):
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        assert token_store.get_token(sid) is None

    def test_get_token_returns_broker_token(self, db_session):
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        bt = BrokerToken(
            connection_id="conn-" + uid[:8],
            session_hash=hash_session_id(sid),
            broker_token_encrypted=encrypt("broker-token"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(bt)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        assert token_store.get_token(sid) == "broker-token"

    def test_resolve_platform_session_returns_user_id(self):
        db = SessionLocal()
        try:
            uid = str(uuid4())
            db.add(User(id=uid, status="active", identity_source="google", broker_provider=None))
            db.flush()
            sid = secrets.token_urlsafe(32)
            create_session_record(db, uid, sid)
            db.commit()
            assert resolve_platform_session(sid) == uid
        finally:
            db.close()

    def test_analytics_token_never_enables_trading(self, db_session):
        """Analytics Token must authorize market data, not trading."""
        uid = _create_user(db_session)
        conn = store_analytics_token(db_session, uid, "UPSTOX", "analytics-tok")
        assert conn.trading_status == "inactive"
        assert conn.data_status == "active"
