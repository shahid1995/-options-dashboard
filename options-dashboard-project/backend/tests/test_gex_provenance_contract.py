"""Regression tests for the GEX provenance contract."""

from datetime import datetime, timezone
from types import SimpleNamespace

import app.db
import app.identity
import app.services.broker_authorization
from app.main import _get_oauth_token_for_gex


class _DummySessionDb:
    """Minimal DB double: the ownership resolver is fully mocked out."""

    def close(self):
        return None
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
    """Ownership-path resolution: token + EXACT connection id (never a session hash)."""
    connection = SimpleNamespace(id="connection-a")
    authz = SimpleNamespace(access_token_plain=lambda: "REAL_BROKER_TOKEN")

    seen = {}

    def _fake_resolver(db, user_id):
        seen["user_id"] = user_id
        return connection, authz

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _DummySessionDb())
    monkeypatch.setattr(
        app.services.broker_authorization,
        "resolve_default_broker_authorization",
        _fake_resolver,
    )

    token, connection_id = _get_oauth_token_for_gex("user-a")

    assert seen["user_id"] == "user-a"
    assert token == "REAL_BROKER_TOKEN"
    assert connection_id == "connection-a"


def test_oauth_gex_requires_broker_connection(monkeypatch):
    """No connected connection / active authorization → no token, no provenance."""
    monkeypatch.setattr(app.db, "SessionLocal", lambda: _DummySessionDb())
    monkeypatch.setattr(
        app.services.broker_authorization,
        "resolve_default_broker_authorization",
        lambda db, user_id: (None, None),
    )

    result = _get_oauth_token_for_gex("user-a")
    assert result == (None, None)


def test_oauth_capture_contract_is_broker_owned(monkeypatch):
    """OAuth provenance must carry a broker connection, never a session identifier."""
    connection = SimpleNamespace(id="connection-a")
    authz = SimpleNamespace(access_token_plain=lambda: "REAL_BROKER_TOKEN")

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _DummySessionDb())
    monkeypatch.setattr(
        app.services.broker_authorization,
        "resolve_default_broker_authorization",
        lambda db, user_id: (connection, authz),
    )

    token, connection_id = _get_oauth_token_for_gex("user-a")

    assert token == "REAL_BROKER_TOKEN"
    assert connection_id == "connection-a"
    assert connection_id != "session-hash-a"
