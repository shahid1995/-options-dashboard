"""Regression tests for the GEX provenance contract."""

from datetime import datetime, timezone
from types import SimpleNamespace

import app.db
import app.identity
from app.main import _get_oauth_token_for_gex
from app.services.gex_history import (
    DATA_SOURCE_ANALYTICS_TOKEN,
    DATA_SOURCE_API_UPLOAD,
    DATA_SOURCE_BROKER_OAUTH,
    record_gex_snapshot,
)


def _snapshot() -> dict:
    return {
        "symbol": "NIFTY",
        "expiry": "2026-08-28",
        "spot": 25512.0,
        "methodology": "GEX_STANDARD_V1",
        "signConvention": "NAIVE_DEALER_CONVENTION",
        "callGex": 1.0,
        "putGex": -1.0,
        "netGex": 0.0,
        "availabilityStatus": "available",
        "validStrikeCount": 1,
        "totalStrikeCount": 1,
        "chainAgeMs": 1000.0,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "strikeData": [],
        "expiryData": [],
        "methodologyMetadata": {},
    }


class _DummyDb:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    def commit(self):
        return None

    def rollback(self):
        return None


def test_canonical_gex_data_sources_are_stable():
    assert DATA_SOURCE_ANALYTICS_TOKEN == "analytics_token"
    assert DATA_SOURCE_BROKER_OAUTH == "broker_oauth"
    assert DATA_SOURCE_API_UPLOAD == "api_upload"


def test_unknown_gex_data_source_is_rejected():
    db = _DummyDb()
    assert record_gex_snapshot(
        db,
        _snapshot(),
        owner_id="user-a",
        connection_id="conn-a",
        data_source="oauth",
    ) == 0
    assert db.added == []


def test_user_authorized_gex_sources_require_connection_id():
    db = _DummyDb()

    assert record_gex_snapshot(
        db,
        _snapshot(),
        owner_id="user-a",
        data_source=DATA_SOURCE_ANALYTICS_TOKEN,
    ) == 0
    assert record_gex_snapshot(
        db,
        _snapshot(),
        owner_id="user-a",
        data_source=DATA_SOURCE_BROKER_OAUTH,
    ) == 0
    assert db.added == []


def test_api_upload_is_the_explicit_null_connection_case():
    db = _DummyDb()
    assert record_gex_snapshot(
        db,
        _snapshot(),
        owner_id="user-a",
        connection_id=None,
        data_source=DATA_SOURCE_API_UPLOAD,
    ) == 1
    assert db.added[0].data_source == DATA_SOURCE_API_UPLOAD
    assert db.added[0].connection_id is None


def test_oauth_gex_resolver_returns_exact_connection_id(monkeypatch):
    session = SimpleNamespace(
        user_id="user-a",
        session_hash="session-hash-a",
        broker_connection_id="connection-a",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        revoked_at=None,
    )

    class _Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return session

    class _Db:
        def query(self, *args):
            return _Query()

        def close(self):
            return None

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        app.identity,
        "resolve_broker_token_by_session_hash",
        lambda session_hash: "REAL_BROKER_TOKEN" if session_hash == session.session_hash else None,
    )

    token, connection_id = _get_oauth_token_for_gex("user-a")

    assert token == "REAL_BROKER_TOKEN"
    assert connection_id == "connection-a"


def test_oauth_gex_requires_broker_connection(monkeypatch):
    session = SimpleNamespace(
        user_id="user-a",
        session_hash="session-hash-a",
        broker_connection_id=None,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        revoked_at=None,
    )

    class _Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return session

    class _Db:
        def query(self, *args):
            return _Query()

        def close(self):
            return None

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(app.identity, "resolve_broker_token_by_session_hash", lambda _: "REAL_BROKER_TOKEN")

    result = _get_oauth_token_for_gex("user-a")
    assert result == (None, None)


def test_oauth_capture_contract_is_broker_owned(monkeypatch):
    """OAuth provenance must carry a broker connection, not a session identifier."""
    session = SimpleNamespace(
        user_id="user-a",
        session_hash="session-hash-a",
        broker_connection_id="connection-a",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        revoked_at=None,
    )

    class _Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return session

    class _Db:
        def query(self, *args):
            return _Query()

        def close(self):
            return None

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(app.identity, "resolve_broker_token_by_session_hash", lambda _: "REAL_BROKER_TOKEN")

    token, connection_id = _get_oauth_token_for_gex("user-a")

    assert token == "REAL_BROKER_TOKEN"
    assert connection_id == "connection-a"
    assert connection_id != session.session_hash
