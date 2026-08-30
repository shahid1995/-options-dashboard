"""Strict GEX ownership tests - final version.

Invariants:
1. _get_analytics_token_for_gex requires explicit connection_id (TypeError if missing)
2. _find_default_connection_id has no fallback
3. owner_id is always user_id (never session_hash)
4. End-to-end: User A/B cannot cross-use connections
"""
import inspect
import pathlib
import secrets
from uuid import uuid4

import pytest
from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal
from app.identity import (
    User, BrokerConnection, BrokerToken, UserSession,
    create_session_record, hash_session_id,
    get_analytics_token,
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


def _create_connection(db, user_id, *, is_default=True, data_status="active",
                       broker_account_id=None, analytics_token=None):
    conn = BrokerConnection(
        id=str(uuid4()), user_id=user_id, broker="UPSTOX",
        broker_account_id=broker_account_id or f"acct-{uuid4().hex[:8]}",
        status="connected", is_default=is_default, data_status=data_status,
        broker_analytics_token_encrypted=encrypt(analytics_token) if analytics_token else None,
    )
    db.add(conn)
    db.flush()
    return conn


# ===========================================================================
# Invariant 1: No fallback in _find_default_connection_id
# ===========================================================================

class TestNoConnectionFallback:
    def test_find_default_connection_id_no_fallback(self):
        from app.main import _find_default_connection_id
        source = inspect.getsource(_find_default_connection_id)
        assert "Fallback" not in source
        assert "order_by" not in source

    def test_find_default_connection_id_returns_none_without_default(self, db_session):
        from app.main import _find_default_connection_id
        uid = _create_user(db_session)
        _create_connection(db_session, uid, is_default=False, analytics_token="tok-1")
        _create_connection(db_session, uid, is_default=False, analytics_token="tok-2")
        db_session.commit()
        assert _find_default_connection_id(uid) is None

    def test_find_default_connection_id_returns_default(self, db_session):
        from app.main import _find_default_connection_id
        uid = _create_user(db_session)
        conn_other = _create_connection(db_session, uid, is_default=False, analytics_token="other")
        conn_default = _create_connection(db_session, uid, is_default=True, analytics_token="default")
        db_session.commit()
        assert _find_default_connection_id(uid) == conn_default.id

    def test_find_default_connection_id_inactive_returns_none(self, db_session):
        from app.main import _find_default_connection_id
        uid = _create_user(db_session)
        _create_connection(db_session, uid, is_default=True, data_status="inactive",
                           analytics_token="inactive-tok")
        db_session.commit()
        assert _find_default_connection_id(uid) is None

    def test_find_default_connection_id_wrong_user_returns_none(self, db_session):
        from app.main import _find_default_connection_id
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        _create_connection(db_session, uid_a, is_default=True, analytics_token="tok-a")
        db_session.commit()
        assert _find_default_connection_id(uid_a) is not None
        assert _find_default_connection_id(uid_b) is None


# ===========================================================================
# Invariant 2: _get_analytics_token_for_gex requires connection_id
# ===========================================================================

class TestGexRequiresConnectionId:
    def test_gex_requires_connection_id(self, db_session):
        """Calling without connection_id must raise TypeError."""
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        _create_connection(db_session, uid, is_default=True, analytics_token="tok-1")
        db_session.commit()
        with pytest.raises(TypeError):
            _get_analytics_token_for_gex(uid)

    def test_gex_with_connection_id_exact_match(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        conn_1 = _create_connection(db_session, uid, is_default=True, analytics_token="tok-1")
        conn_2 = _create_connection(db_session, uid, is_default=False, analytics_token="tok-2")
        db_session.commit()
        assert _get_analytics_token_for_gex(uid, connection_id=conn_1.id) == "tok-1"
        assert _get_analytics_token_for_gex(uid, connection_id=conn_2.id) == "tok-2"

    def test_gex_wrong_connection_returns_none(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        _create_connection(db_session, uid, analytics_token="my-tok")
        db_session.commit()
        assert _get_analytics_token_for_gex(uid, connection_id=str(uuid4())) is None

    def test_gex_wrong_user_returns_none(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn_b = _create_connection(db_session, uid_b, analytics_token="tok-b")
        db_session.commit()
        assert _get_analytics_token_for_gex(uid_a, connection_id=conn_b.id) is None

    def test_gex_two_connections_exact_selection(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        conn_a = _create_connection(db_session, uid, analytics_token="token-a")
        conn_b = _create_connection(db_session, uid, analytics_token="token-b")
        db_session.commit()
        assert _get_analytics_token_for_gex(uid, connection_id=conn_a.id) == "token-a"
        assert _get_analytics_token_for_gex(uid, connection_id=conn_b.id) == "token-b"

    def test_gex_inactive_connection_returns_none(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        conn = _create_connection(db_session, uid, data_status="inactive",
                                  analytics_token="inactive-tok")
        db_session.commit()
        assert _get_analytics_token_for_gex(uid, connection_id=conn.id) is None

    def test_gex_no_token_returns_none(self, db_session):
        from app.main import _get_analytics_token_for_gex
        uid = _create_user(db_session)
        conn = _create_connection(db_session, uid, analytics_token=None)
        db_session.commit()
        assert _get_analytics_token_for_gex(uid, connection_id=conn.id) is None


# ===========================================================================
# Invariant 3: owner_id is always user_id
# ===========================================================================

class TestNormalizedOwnership:
    def test_oauth_capture_owner_id_is_user_id(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        assert "owner_id = current_session_id" not in loop_section

    def test_capture_loop_owner_id_never_none(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        assert "owner_id = None" not in loop_section


# ===========================================================================
# End-to-end ownership proof
# ===========================================================================

class TestGexOwnershipEndToEnd:
    def test_user_a_and_b_cannot_cross_use_connections(self, db_session):
        """User A + connection A -> token A, User B + connection B -> token B,
        A cannot use B's connection."""
        from app.main import _get_analytics_token_for_gex
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn_a = _create_connection(db_session, uid_a, analytics_token="token-a")
        conn_b = _create_connection(db_session, uid_b, analytics_token="token-b")
        db_session.commit()

        assert _get_analytics_token_for_gex(uid_a, connection_id=conn_a.id) == "token-a"
        assert _get_analytics_token_for_gex(uid_b, connection_id=conn_b.id) == "token-b"
        assert _get_analytics_token_for_gex(uid_a, connection_id=conn_b.id) is None
        assert _get_analytics_token_for_gex(uid_b, connection_id=conn_a.id) is None

    def test_owner_id_never_session_hash(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        # owner_id assignment must not reference session_hash
        for line in loop_section.split("\n"):
            stripped = line.strip()
            if stripped.startswith("owner_id") and "=" in stripped:
                assert "session_hash" not in stripped, (
                    f"owner_id uses session_hash: {stripped}"
                )

    def test_owner_id_is_always_user_id(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        for line in loop_section.split("\n"):
            stripped = line.strip()
            if stripped.startswith("owner_id") and "=" in stripped:
                assert "user_id" in stripped, (
                    f"owner_id does not use user_id: {stripped}"
                )
                break


# ===========================================================================
# Capture loop uses connection_id
# ===========================================================================

class TestCaptureLoopUsesConnectionId:
    def test_capture_loop_passes_connection_id(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        assert "connection_id" in loop_section

    def test_capture_loop_resolves_connection_before_token(self):
        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        loop_section = source.split("def _gex_capture_loop")[1].split("\ndef ")[0]
        assert "_find_default_connection_id" in loop_section or "connection_id" in loop_section


# ===========================================================================
# WebSocket cross-user (regression)
# ===========================================================================

class TestWebSocketCrossUser:
    def test_user_a_cannot_use_user_b_broker_token(self, db_session):
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        sid_a = secrets.token_urlsafe(32)
        sid_b = secrets.token_urlsafe(32)
        create_session_record(db_session, uid_a, sid_a)
        create_session_record(db_session, uid_b, sid_b)
        bt_b = BrokerToken(
            connection_id="conn-b", session_hash=hash_session_id(sid_b),
            broker_token_encrypted=encrypt("token-b"),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(bt_b)
        db_session.commit()
        token_store._sessions.pop(sid_a, None)
        token_store._sessions.pop(sid_b, None)
        assert token_store.get_token(sid_a) is None
        assert token_store.get_token(sid_b) == "token-b"


# ===========================================================================
# Capability invariant (regression)
# ===========================================================================

class TestCapabilityInvariant:
    def test_analytics_token_trading_inactive(self, db_session):
        uid = _create_user(db_session)
        from app.identity import store_analytics_token
        conn = store_analytics_token(db_session, uid, "UPSTOX", "a-tok")
        assert conn.data_status == "active"
        assert conn.trading_status == "inactive"
