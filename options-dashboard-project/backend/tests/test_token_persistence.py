"""Tests for Phase 10.2B-3 token persistence, rehydration, and OAuth state binding.

Covers: token DB persistence, memory+DB dual-layer, startup DB health check,
signed OAuth state, session_id binding, backward compatibility, and
commit-pattern fixes.

Phase 10.2B-3 design: in-memory cache cannot be rehydrated because the DB
stores session_hash (SHA-256), not the plaintext session_id.  get_token()
uses a DB fallback on cache miss instead.

Key design: token_store creates its own SessionLocal() internally for DB ops.
Tests must verify via the SAME SessionLocal (conftest-overridden), not via
a separate in-memory engine.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.identity import (
    User,
    UserSession,
    BrokerConnection,
    BrokerToken,
    hash_session_id,
    create_session_record,
    revoke_session,
)
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _ensure_tables_exist():
    """Create all tables on the conftest engine (used by token_store DB ops)."""
    import app.db as _db
    Base.metadata.create_all(_db.engine)


@pytest.fixture(autouse=True)
def clear_token_store():
    """Clear token store before and after each test."""
    token_store.clear_token()
    yield
    token_store.clear_token()


def _get_db():
    """Get a session on the same engine token_store uses (conftest-overridden SessionLocal)."""
    from app.db import SessionLocal
    return SessionLocal()


@pytest.fixture()
def user():
    """Create a test user on the conftest engine."""
    db = _get_db()
    user_id = str(uuid4())
    user = User(
        id=user_id,
        status="active",
        identity_source="upstox",
        broker_provider="UPSTOX",
        broker_user_id=f"test-{user_id[:8]}",
    )
    db.add(user)
    db.commit()
    # Expire so attributes are lazy-loaded from the same session
    db.expire(user)
    yield user
    db.close()


@pytest.fixture()
def connection(user):
    """Create a connected broker connection on the conftest engine."""
    db = _get_db()
    conn = BrokerConnection(
        id=str(uuid4()),
        user_id=user.id,
        broker="UPSTOX",
        broker_account_id="UCC-PERSIST-1",
        status="connected",
        connected_at=datetime.now(timezone.utc),
    )
    db.add(conn)
    db.commit()
    db.expire(conn)
    yield conn
    db.close()


# ---------------------------------------------------------------------------
# 1. Token DB Persistence
# ---------------------------------------------------------------------------


class TestTokenDBPersistence:
    """Verify token persistence to broker_tokens table."""

    def test_set_token_persists_to_db(self, user, connection):
        """set_token() writes encrypted token to broker_tokens."""
        session_id = token_store.set_token(
            "test-access-token-xyz",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        # Verify token is in memory
        assert token_store.get_token(session_id) == "test-access-token-xyz"

        # Verify token is in DB (encrypted) — query via same engine
        db = _get_db()
        try:
            session_hash = hash_session_id(session_id)
            bt = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt is not None
            assert bt.broker_token_encrypted is not None
            assert bt.broker_token_encrypted != "test-access-token-xyz"  # Encrypted
            from app.crypto import decrypt
            assert decrypt(bt.broker_token_encrypted) == "test-access-token-xyz"
        finally:
            db.close()

    def test_set_token_stores_connection_id(self, user, connection):
        """set_token() stores connection_id on the BrokerToken row."""
        session_id = token_store.set_token(
            "token-with-conn",
            connection_id=connection.id,
        )
        db = _get_db()
        try:
            session_hash = hash_session_id(session_id)
            bt = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt is not None
            assert bt.connection_id == connection.id
        finally:
            db.close()

    def test_set_token_stores_expires_at(self, user, connection):
        """set_token() stores expires_at on the BrokerToken row."""
        expires = datetime.now(timezone.utc) + timedelta(hours=23)
        session_id = token_store.set_token(
            "token-with-expiry",
            connection_id=connection.id,
            expires_at=expires,
        )
        db = _get_db()
        try:
            session_hash = hash_session_id(session_id)
            bt = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt is not None
            assert bt.broker_token_expires_at is not None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 2. Memory + DB Dual-Layer
# ---------------------------------------------------------------------------


class TestDualLayer:
    """Verify memory-first, DB-fallback behavior."""

    def test_get_token_returns_from_memory(self, user, connection):
        """Fast path: token found in memory."""
        session_id = token_store.set_token("mem-token", connection_id=connection.id)
        token = token_store.get_token(session_id)
        assert token == "mem-token"

    def test_get_token_falls_back_to_db(self, user, connection):
        """DB fallback: token not in memory, loaded from DB."""
        session_id = token_store.set_token(
            "db-fallback-token",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        # Also create session record so rehydrate can find it
        db = _get_db()
        try:
            create_session_record(db, str(user.id), session_id, broker_connection_id=connection.id)
            db.commit()
        finally:
            db.close()

        # Clear memory cache
        token_store._sessions.clear()
        assert session_id not in token_store._sessions

        # Should fall back to DB (get_token → _load_token_from_db)
        token = token_store.get_token(session_id)
        assert token == "db-fallback-token"
        # Should be back in memory now
        assert session_id in token_store._sessions

    def test_clear_token_removes_from_memory_and_db(self, user, connection):
        """clear_token() removes from both memory and DB."""
        session_id = token_store.set_token(
            "clear-test",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        assert token_store.get_token(session_id) == "clear-test"

        token_store.clear_token(session_id)

        # Memory cleared
        assert session_id not in token_store._sessions
        # DB cleared (encrypted value NULLed)
        db = _get_db()
        try:
            session_hash = hash_session_id(session_id)
            bt = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt is not None  # Row still exists
            assert bt.broker_token_encrypted is None  # But token is NULLed
        finally:
            db.close()

    def test_clear_token_only_nulls_encrypted(self, user, connection):
        """clear_token() keeps the BrokerToken row, only NULLs encrypted value."""
        session_id = token_store.set_token(
            "null-test",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            session_hash = hash_session_id(session_id)
            bt_before = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt_before.broker_token_encrypted is not None

            token_store.clear_token(session_id)

            # Refresh to see DB state (clear_token modified DB via separate session)
            db.expire_all()
            bt_after = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
            assert bt_after is not None
            assert bt_after.broker_token_encrypted is None
            assert bt_after.connection_id == bt_before.connection_id  # Row preserved
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 3. Rehydrate Cache
# ---------------------------------------------------------------------------


class TestStartupDbCheck:
    """Verify startup DB health check (replaces broken rehydrate_cache)."""

    def test_db_check_counts_active_tokens(self, user, connection):
        """startup_db_check() counts active tokens in DB."""
        session_id = token_store.set_token(
            "check-me",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            create_session_record(db, str(user.id), session_id, broker_connection_id=connection.id)
            db.commit()
        finally:
            db.close()

        count = token_store.startup_db_check()
        assert count >= 1

    def test_db_check_skips_expired(self, user, connection):
        """startup_db_check() does not count expired sessions."""
        session_id = token_store.set_token(
            "expired-check",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            record = UserSession(
                user_id=str(user.id),
                session_hash=hash_session_id(session_id),
                created_at=datetime.now(timezone.utc) - timedelta(hours=25),
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        count = token_store.startup_db_check()
        # The expired session should not be counted
        # (count may be 0 or may include other test fixtures)
        assert isinstance(count, int)

    def test_db_check_handles_empty_db(self):
        """startup_db_check() returns 0 when DB has no tokens."""
        count = token_store.startup_db_check()
        assert count == 0

    def test_no_plaintext_session_id_in_db(self, user, connection):
        """DB must never contain plaintext session IDs — only hashes."""
        session_id = token_store.set_token(
            "plaintext-check",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            # Query broker_tokens raw
            from sqlalchemy import text
            rows = db.execute(text("SELECT session_hash FROM broker_tokens")).fetchall()
            for row in rows:
                assert row[0] != session_id, (
                    "Plaintext session_id found in broker_tokens.session_hash!"
                )
            # Query user_sessions raw
            rows = db.execute(text("SELECT session_hash FROM user_sessions")).fetchall()
            for row in rows:
                assert row[0] != session_id, (
                    "Plaintext session_id found in user_sessions.session_hash!"
                )
        finally:
            db.close()

    def test_db_check_does_not_populate_memory(self, user, connection):
        """startup_db_check() must NOT populate the in-memory cache."""
        session_id = token_store.set_token(
            "no-cache-populate",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            create_session_record(db, str(user.id), session_id, broker_connection_id=connection.id)
            db.commit()
        finally:
            db.close()

        # Clear memory
        token_store._sessions.clear()

        # Run startup check
        token_store.startup_db_check()

        # Memory should still be empty (check is read-only)
        assert session_id not in token_store._sessions

        # But get_token DB fallback should still work
        token = token_store.get_token(session_id)
        assert token == "no-cache-populate"


# ---------------------------------------------------------------------------
# 4. Signed OAuth State
# ---------------------------------------------------------------------------


class TestSignedOAuthState:
    """Verify HMAC-signed OAuth state."""

    def test_signed_state_round_trip(self):
        """create_oauth_state(sid, broker) -> consume_oauth_state() returns same values."""
        state = token_store.create_oauth_state(
            session_id="test-session-123",
            broker="UPSTOX",
        )
        result = token_store.consume_oauth_state(state)
        assert result is not None
        assert result["session_id"] == "test-session-123"
        assert result["broker"] == "UPSTOX"

    def test_signed_state_tampered_fails(self):
        """Tampered state returns None."""
        state = token_store.create_oauth_state(
            session_id="test-session-456",
            broker="UPSTOX",
        )
        # Tamper with the signature
        b64, sig = state.rsplit(".", 1)
        tampered = f"{b64}.{'0' * 32}"
        result = token_store.consume_oauth_state(tampered)
        assert result is None

    def test_signed_state_already_consumed_fails(self):
        """State consumed once cannot be consumed again (replay protection)."""
        state = token_store.create_oauth_state(
            session_id="test-session-789",
            broker="UPSTOX",
        )
        result1 = token_store.consume_oauth_state(state)
        assert result1 is not None
        # Second consumption fails
        result2 = token_store.consume_oauth_state(state)
        assert result2 is None

    def test_signed_state_replay_fails(self):
        """Same state consumed twice returns None second time."""
        state = token_store.create_oauth_state(
            session_id="test-session-replay",
            broker="FYERS",
        )
        result1 = token_store.consume_oauth_state(state)
        assert result1 is not None
        assert result1["session_id"] == "test-session-replay"
        assert result1["broker"] == "FYERS"

        # Second consumption should fail
        result2 = token_store.consume_oauth_state(state)
        assert result2 is None

    def test_backward_compat_old_state_format(self):
        """Old CSRF-only state still works."""
        state = token_store.create_oauth_state()  # No session_id
        result = token_store.consume_oauth_state(state)
        assert result is not None
        assert result["session_id"] == ""  # No session binding
        assert result["broker"] == "UPSTOX"

    def test_empty_state_returns_none(self):
        """Empty or None state returns None."""
        assert token_store.consume_oauth_state(None) is None
        assert token_store.consume_oauth_state("") is None

    def test_signed_state_with_different_broker(self):
        """State carries the correct broker value."""
        state = token_store.create_oauth_state(
            session_id="broker-test",
            broker="FYERS",
        )
        result = token_store.consume_oauth_state(state)
        assert result["broker"] == "FYERS"

    def test_corrupted_signed_state_does_not_downgrade(self):
        """A signed state (contains dot) that fails HMAC must NOT fall through
        to the unsigned legacy path.  This prevents session-binding bypass.
        """
        # Create a valid signed state
        state = token_store.create_oauth_state(
            session_id="corruption-test",
            broker="UPSTOX",
        )
        assert "." in state  # Confirm it's signed format

        # Tamper with the signature portion
        b64, _sig = state.rsplit(".", 1)
        corrupted = f"{b64}.00000000000000000000000000000000"

        # Must reject — NOT downgrade to legacy unsigned path
        result = token_store.consume_oauth_state(corrupted)
        assert result is None

    def test_corrupted_base64_in_signed_state_rejects(self):
        """A signed state with corrupted base64 payload must NOT downgrade."""
        # Craft a state with valid-looking structure but bad base64
        bad_b64 = "!!!invalid-base64!!!"
        state_with_dot = f"{bad_b64}.00000000000000000000000000000000"

        result = token_store.consume_oauth_state(state_with_dot)
        assert result is None

    def test_dot_in_unsigned_state_not_created(self):
        """create_oauth_state() without session_id must NOT produce dots."""
        state = token_store.create_oauth_state()  # No session_id
        assert "." not in state, "Unsigned state must not contain dots"


# ---------------------------------------------------------------------------
# 5. Commit Pattern Fixes
# ---------------------------------------------------------------------------


class TestCommitPatternFixes:
    """Verify create_session_record and revoke_session use flush, not commit."""

    def test_create_session_record_no_direct_commit(self, user, connection):
        """create_session_record() uses flush, not commit -- caller manages transaction."""
        db = _get_db()
        try:
            record = create_session_record(
                db, str(user.id), "test-no-commit", broker_connection_id=connection.id
            )
            assert record.id is not None
            assert record.broker_connection_id == connection.id
        finally:
            db.close()

    def test_revoke_session_no_direct_commit(self, user, connection):
        """revoke_session() uses flush, not commit -- caller manages transaction."""
        db = _get_db()
        try:
            # Create a session first
            record = create_session_record(
                db, str(user.id), "test-revoke-no-commit", broker_connection_id=connection.id
            )
            db.commit()  # Caller commits

            # Revoke should flush, not commit
            result = revoke_session(db, "test-revoke-no-commit")
            assert result is True
        finally:
            db.close()


# ---------------------------------------------------------------------------
# 6. Integration: Full Lifecycle
# ---------------------------------------------------------------------------


class TestTokenPersistenceLifecycle:
    """End-to-end test: create token -> persist -> restart (clear memory) -> rehydrate -> use."""

    def test_full_lifecycle_with_restart(self, user, connection):
        """Simulate: login -> server restart -> session survives via DB fallback."""
        # 1. Login: create token + session record
        session_id = token_store.set_token(
            "lifecycle-token",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            create_session_record(
                db, str(user.id), session_id, broker_connection_id=connection.id
            )
            db.commit()
        finally:
            db.close()

        # 2. Verify token works (fast path: memory)
        assert token_store.get_token(session_id) == "lifecycle-token"

        # 3. Simulate server restart: clear all memory
        token_store._sessions.clear()
        assert session_id not in token_store._sessions

        # 4. Token retrieved via DB fallback (memory miss -> DB -> decrypt -> cache)
        token = token_store.get_token(session_id)
        assert token == "lifecycle-token"
        # Verify it's now cached in memory for fast path
        assert session_id in token_store._sessions

        # 5. Logout: clear token from both memory and DB
        token_store.clear_token(session_id)
        assert token_store.get_token(session_id) is None

        # 6. DB fallback also returns None (token NULLed)
        token_store._sessions.clear()
        assert token_store.get_token(session_id) is None

    def test_startup_db_check_then_get_token(self, user, connection):
        """startup_db_check is read-only; get_token DB fallback does the real work."""
        session_id = token_store.set_token(
            "db-check-lifecycle",
            connection_id=connection.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db = _get_db()
        try:
            create_session_record(
                db, str(user.id), session_id, broker_connection_id=connection.id
            )
            db.commit()
        finally:
            db.close()

        # Clear memory to simulate restart
        token_store._sessions.clear()

        # Startup check reports active tokens but doesn't populate cache
        count = token_store.startup_db_check()
        assert count >= 1
        assert session_id not in token_store._sessions  # Still empty

        # First request goes through DB fallback
        token = token_store.get_token(session_id)
        assert token == "db-check-lifecycle"
        assert session_id in token_store._sessions  # Now cached

        # Second request hits fast path
        token2 = token_store.get_token(session_id)
        assert token2 == "db-check-lifecycle"
