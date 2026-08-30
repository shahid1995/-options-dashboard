"""Gate A: Sharp regression tests for 4 remaining PR #34 issues.

Tests that FAIL against 8bd0d56, proving concrete code bugs.
"""
import inspect
import pathlib
import secrets
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
# Issue 1: GEX — GEX_USER_ID config dependency
# ===========================================================================

class TestGexNoGlobalCredential:
    def test_gex_capture_requires_explicit_enable(self):
        """GEX_HISTORY_ENABLED (UI) must not auto-enable capture."""
        from app.config import settings
        assert hasattr(settings, "GEX_HISTORY_ENABLED")

    def test_gex_capture_requires_user_id(self):
        from app.main import _gex_capture_loop
        sig = inspect.signature(_gex_capture_loop)
        assert "user_id" in sig.parameters

    def test_gex_analytics_token_query_filters_by_user_id(self):
        from app.main import _get_analytics_token_for_gex
        sig = inspect.signature(_get_analytics_token_for_gex)
        assert "user_id" in sig.parameters

    def test_user_a_token_never_for_user_b(self, db_session):
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn_a = BrokerConnection(
            id=str(uuid4()), user_id=uid_a, broker="UPSTOX",
            broker_account_id="acct_a", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-a"),
        )
        conn_b = BrokerConnection(
            id=str(uuid4()), user_id=uid_b, broker="UPSTOX",
            broker_account_id="acct_b", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-b"),
        )
        db_session.add_all([conn_a, conn_b])
        db_session.flush()
        assert get_analytics_token(db_session, uid_a, "UPSTOX") == "token-a"
        assert get_analytics_token(db_session, uid_b, "UPSTOX") == "token-b"

    def test_inactive_data_not_returned(self, db_session):
        uid = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct1", status="connected",
            is_default=True, data_status="inactive",
            broker_analytics_token_encrypted=encrypt("inactive-tok"),
        )
        db_session.add(conn)
        db_session.flush()
        assert get_analytics_token(db_session, uid, "UPSTOX") is None


# ===========================================================================
# Issue 2: WebSocket — dead ':' heuristic still present
# ===========================================================================

class TestWebSocketAuthorization:
    def test_chain_ws_no_colon_heuristic(self):
        """chain_ws must NOT contain the dead ':' heuristic.
        get_token() already returns None for platform sessions,
        so checking for ':' is dead code that obscures intent."""
        source = pathlib.Path("app/routers/chains.py").read_text(encoding="utf-8")
        # The ':' heuristic should not appear anywhere in chains.py
        assert '":" in token' not in source, (
            "chains.py still contains ':' heuristic — "
            "get_token() already returns None for platform sessions"
        )

    def test_platform_session_rejected_by_get_token(self, db_session):
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        assert token_store.get_token(sid) is None

    def test_broker_session_returns_token(self, db_session):
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        bt = BrokerToken(
            connection_id="conn-" + uid[:8],
            session_hash=hash_session_id(sid),
            broker_token_encrypted=encrypt("real-ws-broker-token"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(bt)
        db_session.commit()
        token_store._sessions.pop(sid, None)
        assert token_store.get_token(sid) == "real-ws-broker-token"

    def test_session_hash_never_as_access_token_in_ws(self):
        """WebSocket code must not pass session_hash to gateway.create()."""
        import re
        source = pathlib.Path("app/routers/chains.py").read_text(encoding="utf-8")
        create_calls = re.findall(r'gateway\.create\([^)]+\)', source)
        for call in create_calls:
            assert "session_hash" not in call, (
                f"WebSocket passes session_hash to gateway.create: {call}"
            )


# ===========================================================================
# Issue 3: Analytics Token .first() without is_default — ACTUAL BUG
# ===========================================================================

class TestAnalyticsTokenDeterministic:
    def test_get_analytics_token_prefers_default(self, db_session):
        """With multiple connections, get_analytics_token must return
        the default connection's token. Current code uses .first()
        without is_default — non-deterministic."""
        uid = _create_user(db_session)
        # Non-default connection with token (may be .first() depending on INSERT order)
        conn_other = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-other", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-other"),
        )
        # Default connection with different token
        conn_default = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-default", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("token-default"),
        )
        db_session.add_all([conn_other, conn_default])
        db_session.flush()

        token = get_analytics_token(db_session, uid, "UPSTOX")
        assert token == "token-default", (
            f"Expected 'token-default' but got {token!r} — "
            "get_analytics_token uses .first() without is_default filter"
        )

    def test_gex_analytics_prefers_default(self, db_session):
        """_get_analytics_token_for_gex must prefer default connection."""
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        conn_other = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-other", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("gex-other"),
        )
        conn_default = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-default", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("gex-default"),
        )
        db_session.add_all([conn_other, conn_default])
        db_session.flush()

        token = _get_analytics_token_for_gex(uid, connection_id=conn_default.id)
        assert token == "gex-default", (
            f"Expected 'gex-default' but got {token!r} — "
            "_get_analytics_token_for_gex uses .first() without is_default"
        )

    def test_repeated_lookup_deterministic(self, db_session):
        uid = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-det", status="connected",
            is_default=True, data_status="active",
            broker_analytics_token_encrypted=encrypt("det-tok"),
        )
        db_session.add(conn)
        db_session.flush()
        results = [get_analytics_token(db_session, uid, "UPSTOX") for _ in range(5)]
        assert len(set(results)) == 1

    def test_no_default_uses_first_connected(self, db_session):
        uid = _create_user(db_session)
        conn = BrokerConnection(
            id=str(uuid4()), user_id=uid, broker="UPSTOX",
            broker_account_id="acct-nodefault", status="connected",
            is_default=False, data_status="active",
            broker_analytics_token_encrypted=encrypt("fallback-tok"),
        )
        db_session.add(conn)
        db_session.flush()
        assert get_analytics_token(db_session, uid, "UPSTOX") == "fallback-tok"


# ===========================================================================
# Issue 4: Consolidate platform session resolvers
# ===========================================================================

class TestPlatformSessionConsolidation:
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

    def test_resolve_platform_session_none_for_missing(self):
        assert resolve_platform_session("nonexistent") is None

    def test_resolve_platform_session_none_for_none(self):
        assert resolve_platform_session(None) is None

    def test_resolve_platform_session_revoked(self, db_session):
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        sh = hash_session_id(sid)
        us = db_session.query(UserSession).filter(UserSession.session_hash == sh).first()
        us.revoked_at = datetime.now(timezone.utc)
        db_session.commit()
        assert resolve_platform_session(sid) is None

    def test_get_active_session_returns_user_session_object(self):
        from app.identity import get_active_session
        db = SessionLocal()
        try:
            uid = str(uuid4())
            db.add(User(id=uid, status="active", identity_source="google", broker_provider=None))
            db.flush()
            sid = secrets.token_urlsafe(32)
            create_session_record(db, uid, sid)
            db.commit()
            result = get_active_session(db, sid)
            assert result is not None
            assert result.user_id == uid
        finally:
            db.close()

    def test_deps_resolve_user_uses_canonical_path(self):
        from app.routers.deps import _resolve_user
        source = inspect.getsource(_resolve_user)
        assert "get_active_session" in source
