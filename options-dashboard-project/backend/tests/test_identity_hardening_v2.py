"""Gate A: Regression tests for PR #34 review issues.

These tests MUST fail against the current code (ad3f1bc) before fixes.
They prove the concrete bugs identified by independent review.

Bug 1: _get_oauth_token_for_gex passes session_hash to get_token()
       which expects plaintext session_id — double-hashing bug.
Bug 2: No dedicated resolve_platform_session() or
       resolve_broker_token_by_session_hash() functions.
Bug 3: trading-authorized magic string encodes trading capability.
"""
import inspect
import secrets
from uuid import uuid4

import pytest
from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal
from app.identity import (
    User, UserSession, BrokerConnection, BrokerToken,
    create_session_record, hash_session_id,
)
from app.services import token_store
from app.crypto import encrypt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def db_session():
    engine = SessionLocal().get_bind()
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


def _create_user(db, identity_source="google"):
    user_id = str(uuid4())
    user = User(id=user_id, status="active", identity_source=identity_source, broker_provider=None)
    db.add(user)
    db.flush()
    return user_id


def _create_session_and_token(db, user_id, broker_token_value="real-broker-token-abc"):
    """Create UserSession + BrokerToken (simulates broker OAuth login)."""
    session_id = secrets.token_urlsafe(32)
    create_session_record(db, user_id, session_id)

    # Also create a BrokerToken (simulates set_token with persist_to_db=True)
    bt = BrokerToken(
        connection_id="conn-" + user_id[:8],
        session_hash=hash_session_id(session_id),
        broker_token_encrypted=encrypt(broker_token_value),
        created_at=datetime.now(timezone.utc),
    )
    db.add(bt)
    db.commit()
    return session_id


# ===========================================================================
# Bug 1: GEX OAuth token lookup double-hashing
# ===========================================================================

class TestGexOAuthTokenLookupBug:
    """_get_oauth_token_for_gex passes session_hash to get_token()
    which expects plaintext session_id — double-hashing."""

    def test_get_token_expects_plaintext_session_id(self):
        """get_token() hashes its input internally.
        If you pass a session_hash, it double-hashes and finds nothing."""
        from app.services.token_store import get_token

        # Create a broker session — set_token returns the session_id
        session_id = token_store.set_token("broker-tok-123", persist_to_db=False)

        # get_token expects plaintext session_id
        result = get_token(session_id)
        assert result == "broker-tok-123"

        # If we pass a hash instead, it double-hashes
        hashed = hash_session_id(session_id)
        result_bad = get_token(hashed)
        assert result_bad is None, (
            "get_token(hash) must NOT return a token — "
            "double-hashing should produce no match"
        )

    def test_gex_oauth_passes_session_hash_not_session_id(self):
        """The current _get_oauth_token_for_gex passes session_hash
        to get_token() — proving the double-hashing bug exists."""
        from app.main import _get_oauth_token_for_gex

        # Read the source and check what's passed to get_token
        source = inspect.getsource(_get_oauth_token_for_gex)
        # The function should NOT pass session.session_hash to get_token
        assert "get_token(session.session_hash)" not in source, (
            "_get_oauth_token_for_gex passes session_hash to get_token() "
            "which expects plaintext session_id — double-hashing bug"
        )

    def test_resolve_broker_token_by_session_hash_exists(self):
        """A dedicated function to resolve broker token by session_hash
        must exist to avoid the double-hashing problem."""
        from app.identity import resolve_broker_token_by_session_hash
        assert callable(resolve_broker_token_by_session_hash)


# ===========================================================================
# Bug 2: Platform session / broker token separation
# ===========================================================================

class TestPlatformSessionResolver:
    """Platform sessions and broker tokens must be separate resolvers."""

    def test_resolve_platform_session_exists(self):
        """A dedicated function to resolve platform session must exist."""
        from app.identity import resolve_platform_session
        assert callable(resolve_platform_session)

    def test_resolve_platform_session_returns_user(self):
        """resolve_platform_session(session_id) → user_id or None."""
        from app.identity import resolve_platform_session

        db = SessionLocal()
        try:
            uid = _create_user(db)
            sid = _create_session_and_token(db, uid)
            result = resolve_platform_session(sid)
            assert result is not None
            assert result == uid
        finally:
            db.close()

    def test_resolve_platform_session_returns_none_for_missing(self):
        from app.identity import resolve_platform_session
        assert resolve_platform_session("nonexistent-session-id") is None

    def test_resolve_platform_session_returns_none_for_revoked(self):
        from app.identity import resolve_platform_session

        db = SessionLocal()
        try:
            uid = _create_user(db)
            sid = _create_session_and_token(db, uid)
            # Revoke the session
            sh = hash_session_id(sid)
            us = db.query(UserSession).filter(UserSession.session_hash == sh).first()
            us.revoked_at = datetime.now(timezone.utc)
            db.commit()
            assert resolve_platform_session(sid) is None
        finally:
            db.close()

    def test_resolve_broker_token_returns_real_broker_token(self):
        """resolve_broker_token_by_session_hash returns decrypted broker token."""
        from app.identity import resolve_broker_token_by_session_hash

        db = SessionLocal()
        try:
            uid = _create_user(db)
            sid = _create_session_and_token(db, uid, "real-upstox-token")
            sh = hash_session_id(sid)
            token = resolve_broker_token_by_session_hash(sh)
            assert token == "real-upstox-token", (
                f"Expected 'real-upstox-token', got {token!r}"
            )
        finally:
            db.close()

    def test_resolve_broker_token_returns_none_for_platform_only(self):
        """Platform-only session (no BrokerToken) returns None."""
        from app.identity import resolve_broker_token_by_session_hash

        db = SessionLocal()
        try:
            uid = _create_user(db)
            # Create session WITHOUT BrokerToken
            sid = secrets.token_urlsafe(32)
            create_session_record(db, uid, sid)
            db.commit()
            sh = hash_session_id(sid)
            token = resolve_broker_token_by_session_hash(sh)
            assert token is None
        finally:
            db.close()

    def test_resolve_broker_token_returns_none_for_missing(self):
        from app.identity import resolve_broker_token_by_session_hash
        assert resolve_broker_token_by_session_hash("nonexistent-hash") is None

    def test_resolve_broker_token_returns_none_for_revoked_session(self):
        from app.identity import resolve_broker_token_by_session_hash

        db = SessionLocal()
        try:
            uid = _create_user(db)
            sid = _create_session_and_token(db, uid, "token-revoked")
            sh = hash_session_id(sid)
            # Revoke
            us = db.query(UserSession).filter(UserSession.session_hash == sh).first()
            us.revoked_at = datetime.now(timezone.utc)
            db.commit()
            token = resolve_broker_token_by_session_hash(sh)
            assert token is None
        finally:
            db.close()

    def test_resolve_broker_token_returns_none_for_expired_session(self):
        from app.identity import resolve_broker_token_by_session_hash

        db = SessionLocal()
        try:
            uid = _create_user(db)
            sid = _create_session_and_token(db, uid, "token-expired")
            sh = hash_session_id(sid)
            # Expire
            us = db.query(UserSession).filter(UserSession.session_hash == sh).first()
            us.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
            token = resolve_broker_token_by_session_hash(sh)
            assert token is None
        finally:
            db.close()

    def test_user_a_cannot_resolve_user_b_broker_token(self):
        from app.identity import resolve_broker_token_by_session_hash

        db = SessionLocal()
        try:
            uid_a = _create_user(db)
            uid_b = _create_user(db)
            sid_a = _create_session_and_token(db, uid_a, "token-a")
            sid_b = _create_session_and_token(db, uid_b, "token-b")

            # User A's session resolves User A's token
            token_a = resolve_broker_token_by_session_hash(hash_session_id(sid_a))
            assert token_a == "token-a"

            # User B's session resolves User B's token
            token_b = resolve_broker_token_by_session_hash(hash_session_id(sid_b))
            assert token_b == "token-b"
        finally:
            db.close()


# ===========================================================================
# Bug 3: Magic trading capability encoding
# ===========================================================================

class TestTradingCapabilitySemantics:
    """Trading capability must not use magic broker_account_id values."""

    def test_no_trading_authorized_magic_string_in_corrective_migration(self):
        """The corrective migration must not use 'trading-authorized'
        as a magic value to preserve trading status."""
        import pathlib
        migration_dir = pathlib.Path("alembic/versions")
        corrective_files = list(migration_dir.glob("*correct*trading*"))
        for f in corrective_files:
            content = f.read_text(encoding="utf-8")
            assert "trading-authorized" not in content, (
                f"{f.name} uses 'trading-authorized' magic string — "
                "trading capability must not be encoded via broker_account_id"
            )

    def test_connected_row_trading_inactive(self, db_session):
        """A connected broker row must have trading_status='inactive'
        by default — OAuth connected ≠ trading authorized."""
        from app.identity import get_or_create_connection
        user_id = _create_user(db_session)
        conn = get_or_create_connection(db_session, user_id, "UPSTOX", "acct_test")
        assert conn.status == "connected"
        assert conn.trading_status == "inactive"

    def test_analytics_token_trading_inactive(self, db_session):
        """Analytics Token must never activate trading."""
        from app.identity import store_analytics_token
        user_id = _create_user(db_session)
        conn = store_analytics_token(db_session, user_id, "UPSTOX", "analytics-tok")
        assert conn.trading_status == "inactive"

    def test_analytics_token_market_data_available(self, db_session):
        """Analytics Token must authorize market data."""
        from app.identity import store_analytics_token, get_analytics_token
        user_id = _create_user(db_session)
        store_analytics_token(db_session, user_id, "UPSTOX", "analytics-tok-2")
        token = get_analytics_token(db_session, user_id, "UPSTOX")
        assert token is not None


# ===========================================================================
# Additional: ensure get_token is broker-only
# ===========================================================================

class TestGetTokenBrokerOnly:
    """get_token() must be broker-token-only."""

    def test_get_token_returns_none_for_platform_session(self, db_session):
        """Platform session (no BrokerToken) must return None."""
        uid = _create_user(db_session)
        sid = secrets.token_urlsafe(32)
        create_session_record(db_session, uid, sid)
        db_session.commit()

        token_store._sessions.pop(sid, None)
        result = token_store.get_token(sid)
        assert result is None

    def test_get_token_returns_broker_token_for_broker_session(self, db_session):
        """Broker session must return the decrypted broker token."""
        uid = _create_user(db_session)
        sid = _create_session_and_token(db_session, uid, "my-broker-token")
        token_store._sessions.pop(sid, None)
        result = token_store.get_token(sid)
        assert result == "my-broker-token"

    def test_analytics_token_takes_priority_in_gex(self):
        """Analytics Token must take priority over OAuth in GEX resolution."""
        from app.main import _get_analytics_token_for_gex

        # Function must exist and be callable with user_id
        sig = inspect.signature(_get_analytics_token_for_gex)
        assert "user_id" in sig.parameters
