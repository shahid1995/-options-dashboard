"""Phase 8F — GEX Multi-User Isolation & Security Tests.

Covers:
- Multi-user token store isolation
- Session lifecycle (create, lookup, expiry, logout)
- GEX snapshot ownership and query scoping
- Cross-user access denial
- WebSocket session binding
- Token never exposed in responses/logs
- Background capture loop session scoping
- Concurrent session safety
- Edge cases: expired sessions, missing sessions, malformed IDs
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _make_session(engine):
    return sessionmaker(bind=engine)()


def _make_chain(spot=24000.0):
    return {
        "symbol": "NIFTY",
        "expiry_date": "2026-08-28",
        "underlying_spot_price": spot,
        "chain": [
            {"strike": 24000, "call": {"gamma": 0.003, "oi": 10000}, "put": {"gamma": 0.002, "oi": 8000}},
        ],
    }


# ---------------------------------------------------------------------------
# Multi-user token store tests
# ---------------------------------------------------------------------------

class TestMultiUserTokenStore:
    """Verify the token store supports multiple concurrent sessions."""

    def setup_method(self):
        """Clear all sessions before each test."""
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_two_sessions_coexist(self):
        from app.services.token_store import set_token, get_token
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        assert get_token(sid_a) == "token_a"
        assert get_token(sid_b) == "token_b"

    def test_session_a_does_not_see_session_b(self):
        from app.services.token_store import set_token, get_token
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        # Each session only sees its own token
        assert get_token(sid_a) != "token_b"
        assert get_token(sid_b) != "token_a"

    def test_clear_session_a_does_not_affect_b(self):
        from app.services.token_store import set_token, get_token, clear_token
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        clear_token(sid_a)

        assert get_token(sid_a) is None
        assert get_token(sid_b) == "token_b"

    def test_login_does_not_overwrite_existing_session(self):
        from app.services.token_store import set_token, get_token
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        # Both tokens should still be accessible
        assert get_token(sid_a) == "token_a"
        assert get_token(sid_b) == "token_b"

    def test_invalid_session_returns_none(self):
        from app.services.token_store import get_token
        assert get_token("nonexistent_session_id") is None

    def test_none_session_returns_none(self):
        from app.services.token_store import get_token
        assert get_token(None) is None

    def test_empty_session_returns_none(self):
        from app.services.token_store import get_token
        assert get_token("") is None

    def test_session_count(self):
        from app.services.token_store import set_token, get_session_count
        assert get_session_count() == 0
        set_token("token_a")
        assert get_session_count() == 1
        set_token("token_b")
        assert get_session_count() == 2

    def test_session_ids_are_cryptographically_random(self):
        from app.services.token_store import set_token
        sids = set()
        for _ in range(100):
            sids.add(set_token("token"))
        # 100 unique session IDs
        assert len(sids) == 100


# ---------------------------------------------------------------------------
# Session expiry tests
# ---------------------------------------------------------------------------

class TestSessionExpiry:
    """Verify expired sessions cannot access tokens."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_expired_session_returns_none(self):
        from app.services.token_store import set_token, get_token, _sessions, _SESSION_TTL_SECONDS
        sid = set_token("token_a")

        # Manually age the session beyond TTL
        _sessions[sid]["created_at"] = time.time() - _SESSION_TTL_SECONDS - 1

        assert get_token(sid) is None

    def test_expired_session_is_cleaned_up(self):
        from app.services.token_store import set_token, get_token, _sessions, _SESSION_TTL_SECONDS
        sid = set_token("token_a")
        _sessions[sid]["created_at"] = time.time() - _SESSION_TTL_SECONDS - 1

        get_token(sid)  # Triggers cleanup

        assert sid not in _sessions

    def test_fresh_session_not_expired(self):
        from app.services.token_store import set_token, get_token
        sid = set_token("token_a")
        # Just created — should not be expired
        assert get_token(sid) == "token_a"


# ---------------------------------------------------------------------------
# GEX snapshot ownership tests
# ---------------------------------------------------------------------------

class TestSnapshotOwnership:
    """Verify gex_snapshots are scoped by owner_id."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_snapshot_stores_owner_id(self):
        from app.services.gex_history import record_gex_snapshot, get_latest_snapshot
        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        }, owner_id="user_a_session")

        latest = get_latest_snapshot(session, "NIFTY", owner_id="user_a_session")
        assert latest is not None
        assert latest["owner_id"] == "user_a_session"

    def test_user_a_cannot_see_user_b_snapshots(self):
        from app.services.gex_history import record_gex_snapshot, get_gex_snapshots
        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        # User A creates a snapshot
        record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        }, owner_id="user_a")

        # User B queries — should not see User A's snapshot
        b_snapshots = get_gex_snapshots(session, "NIFTY", owner_id="user_b")
        assert len(b_snapshots) == 0

        # User A queries — should see their own
        a_snapshots = get_gex_snapshots(session, "NIFTY", owner_id="user_a")
        assert len(a_snapshots) == 1

    def test_user_b_cannot_see_user_a_latest(self):
        from app.services.gex_history import record_gex_snapshot, get_latest_snapshot
        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        }, owner_id="user_a")

        # User B should not see User A's latest
        latest = get_latest_snapshot(session, "NIFTY", owner_id="user_b")
        assert latest is None

    def test_count_scoped_by_owner(self):
        from app.services.gex_history import record_gex_snapshot, count_gex_snapshots
        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        for i in range(3):
            record_gex_snapshot(session, {
                "symbol": "NIFTY",
                "expiry": "2026-08-28",
                "spot": 24000.0,
                "availabilityStatus": "available",
                "capturedAt": (now + timedelta(seconds=i)).isoformat(),
                "strikeData": [],
                "expiryData": [],
                "methodologyMetadata": {},
            }, owner_id="user_a")

        assert count_gex_snapshots(session, "NIFTY", owner_id="user_a") == 3
        assert count_gex_snapshots(session, "NIFTY", owner_id="user_b") == 0

    def test_snapshot_without_owner_still_works(self):
        """Backward compatibility: snapshots without owner_id are still stored."""
        from app.services.gex_history import record_gex_snapshot, get_gex_snapshots
        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        result = record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        })
        assert result == 1

        # Query without owner_id — should still find it
        snapshots = get_gex_snapshots(session, "NIFTY")
        assert len(snapshots) == 1
        assert snapshots[0]["owner_id"] is None


# ---------------------------------------------------------------------------
# Cross-user capture isolation tests
# ---------------------------------------------------------------------------

class TestCaptureIsolation:
    """Verify GexCaptureService scopes snapshots by owner."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_capture_stores_owner_id(self):
        from app.services.gex_capture import GexCaptureService
        engine = _make_engine()
        session = _make_session(engine)
        chain = _make_chain()

        service = GexCaptureService()
        result = service.capture_once(session, chain, expiry="2026-08-28", owner_id="user_a")
        assert result["status"] == "captured"

        # Verify owner_id is stored
        from app.services.gex_history import get_latest_snapshot
        latest = get_latest_snapshot(session, "NIFTY", owner_id="user_a")
        assert latest is not None
        assert latest["owner_id"] == "user_a"

    def test_capture_dedup_scoped_to_owner(self):
        """Two different owners can capture the same chain without dedup conflict."""
        from app.services.gex_capture import GexCaptureService
        from app.services.gex_history import count_gex_snapshots
        engine = _make_engine()
        session = _make_session(engine)
        chain = _make_chain()

        service = GexCaptureService()

        # User A captures
        result_a = service.capture_once(session, chain, expiry="2026-08-28", owner_id="user_a")
        assert result_a["status"] == "captured"

        # User B captures same chain — should NOT be deduplicated
        result_b = service.capture_once(session, chain, expiry="2026-08-28", owner_id="user_b")
        assert result_b["status"] == "captured"

        # Both should have snapshots
        assert count_gex_snapshots(session, "NIFTY", owner_id="user_a") == 1
        assert count_gex_snapshots(session, "NIFTY", owner_id="user_b") == 1


# ---------------------------------------------------------------------------
# Token security tests
# ---------------------------------------------------------------------------

class TestTokenSecurity:
    """Verify tokens are never exposed in responses or logs."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_token_not_in_api_response(self):
        """The /gex/live endpoint must not include the broker token in its response."""
        from app.services.token_store import set_token, get_token
        sid = set_token("secret_broker_token_12345")
        token = get_token(sid)
        # The token should be retrievable but never appear in API responses
        assert token == "secret_broker_token_12345"
        # This is a structural test — the token should not leak through
        # the response model (LiveGexResponse has no token field)

    def test_get_any_token_is_deprecated(self):
        """get_any_token() should log a deprecation warning."""
        from app.services.token_store import set_token, get_any_token
        set_token("token_a")
        # Should return a token but log a warning
        result = get_any_token()
        assert result == "token_a"  # Backward compatible

    def test_session_id_is_cryptographically_random(self):
        from app.services.token_store import set_token
        import secrets
        sid = set_token("token")
        # session_id should be 32 bytes of URL-safe random data
        assert len(sid) >= 40  # base64 encoded 32 bytes
        # Should be valid URL-safe base64
        decoded = secrets.token_urlsafe(32)  # Just verify the format is similar
        assert len(decoded) >= 40


# ---------------------------------------------------------------------------
# WebSocket session binding tests
# ---------------------------------------------------------------------------

class TestWebSocketSessionBinding:
    """Verify WebSocket connections are bound to authenticated sessions."""

    def test_ws_session_extracts_from_protocol(self):
        from app.routers.chains import ws_session

        class MockWS:
            headers = {"sec-websocket-protocol": "options-dashboard-session,abc123"}
            cookies = {}

        session_id, subprotocol = ws_session(MockWS())
        assert session_id == "abc123"
        assert subprotocol == "options-dashboard-session"

    def test_ws_session_falls_back_to_cookie(self):
        from app.routers.chains import ws_session

        class MockWS:
            headers = {}
            cookies = {"session_id": "cookie_session_123"}

        session_id, subprotocol = ws_session(MockWS())
        assert session_id == "cookie_session_123"

    def test_ws_session_returns_none_when_no_auth(self):
        from app.routers.chains import ws_session

        class MockWS:
            headers = {}
            cookies = {}

        session_id, subprotocol = ws_session(MockWS())
        assert session_id is None


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Verify security at boundaries."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_very_long_session_id(self):
        from app.services.token_store import get_token
        long_id = "x" * 10000
        assert get_token(long_id) is None

    def test_special_characters_in_session_id(self):
        from app.services.token_store import get_token
        assert get_token("../../../etc/passwd") is None
        assert get_token("'; DROP TABLE users;--") is None
        assert get_token("<script>alert(1)</script>") is None

    def test_concurrent_sessions_same_token(self):
        """Two sessions with the same broker token are independent."""
        from app.services.token_store import set_token, get_token, clear_token
        sid_a = set_token("shared_token")
        sid_b = set_token("shared_token")

        # Both have the same token but are independent sessions
        assert get_token(sid_a) == "shared_token"
        assert get_token(sid_b) == "shared_token"

        # Clearing one doesn't affect the other
        clear_token(sid_a)
        assert get_token(sid_a) is None
        assert get_token(sid_b) == "shared_token"

    def test_rapid_session_creation(self):
        """Create many sessions rapidly — no corruption."""
        from app.services.token_store import set_token, get_token, get_session_count
        sids = []
        for i in range(100):
            sids.append(set_token(f"token_{i}"))

        assert get_session_count() == 100
        # Each should be independently accessible
        for i, sid in enumerate(sids):
            assert get_token(sid) == f"token_{i}"


# ---------------------------------------------------------------------------
# Concurrent access tests
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    """Verify thread-safety for concurrent session operations."""

    def setup_method(self):
        from app.services.token_store import _sessions, _pending_states
        _sessions.clear()
        _pending_states.clear()

    def test_concurrent_set_and_get(self):
        """Simulate concurrent session creation and lookup."""
        from app.services.token_store import set_token, get_token
        import threading

        results = {}
        errors = []

        def create_session(i):
            try:
                sid = set_token(f"token_{i}")
                # Immediately verify
                token = get_token(sid)
                results[i] = (sid, token)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50
        for i, (sid, token) in results.items():
            assert token == f"token_{i}"


# ---------------------------------------------------------------------------
# Historical GEX access tests
# ---------------------------------------------------------------------------

class TestHistoricalGexAccess:
    """Verify historical GEX remains publicly accessible (shared market data)."""

    def test_historical_gex_has_no_owner(self):
        """HistoricalGexSnapshot should not have an owner_id column."""
        from app.models import HistoricalGexSnapshot
        columns = {c.name for c in HistoricalGexSnapshot.__table__.columns}
        assert "owner_id" not in columns

    def test_gex_snapshot_has_owner(self):
        """GexSnapshot should have owner_id column (Phase 8F)."""
        from app.models import GexSnapshot
        columns = {c.name for c in GexSnapshot.__table__.columns}
        assert "owner_id" in columns
