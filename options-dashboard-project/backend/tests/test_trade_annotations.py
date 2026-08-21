"""Phase 7.0 — Trade Annotations (tags & notes) tests."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import StrategyExecution
from app.services import token_store
from app.services.performance import _parse_tags, serialize_tags
from fastapi.testclient import TestClient


# ---- Unit tests: tag serialization / parsing ----


class TestTagSerialization:
    def test_serialize_none(self):
        assert serialize_tags(None) is None

    def test_serialize_empty_list(self):
        assert serialize_tags([]) is None

    def test_serialize_valid_tags(self):
        result = json.loads(serialize_tags(["earnings", "high-conviction"]))
        assert result == ["earnings", "high-conviction"]

    def test_serialize_strips_whitespace(self):
        result = json.loads(serialize_tags(["  earnings  ", "  "]))
        assert result == ["earnings"]

    def test_serialize_filters_empty(self):
        result = json.loads(serialize_tags(["a", "", "b", None]))
        assert result == ["a", "b"]

    def test_parse_none(self):
        assert _parse_tags(None) is None

    def test_parse_empty_string(self):
        assert _parse_tags("") is None

    def test_parse_valid_json_array(self):
        assert _parse_tags('["a", "b"]') == ["a", "b"]

    def test_parse_empty_array(self):
        assert _parse_tags("[]") == []

    def test_parse_malformed_json(self):
        assert _parse_tags("not json") is None

    def test_parse_non_array_json(self):
        assert _parse_tags('{"key": "value"}') is None

    def test_parse_filters_empty_strings(self):
        assert _parse_tags('["a", "", "b"]') == ["a", "b"]

    def test_roundtrip(self):
        tags = ["alpha", "beta"]
        serialized = serialize_tags(tags)
        parsed = _parse_tags(serialized)
        assert parsed == tags


# ---- Fixtures (local to this test file, matching test_performance.py pattern) ----


@pytest.fixture()
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


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def logged_in(client):
    return token_store.set_token("tok-phase70")


# ---- Migration tests ----


class TestMigration:
    def test_tags_column_exists(self, db_session):
        result = db_session.execute(text("PRAGMA table_info(strategy_executions)"))
        cols = [row.name for row in result]
        assert "tags" in cols

    def test_notes_column_exists(self, db_session):
        result = db_session.execute(text("PRAGMA table_info(strategy_executions)"))
        cols = [row.name for row in result]
        assert "notes" in cols

    def test_migration_idempotent(self):
        from app.db import init_db
        init_db()
        init_db()  # running twice must not fail


# ---- API tests (need fixtures from conftest) ----


@pytest.fixture()
def sample_execution(db_session, logged_in):
    """Create a sample completed strategy execution for annotation testing."""
    from app.models import Position
    from datetime import datetime, timezone

    user_id = logged_in  # logged_in fixture returns the session_id which is the user key
    exec_id = "ann-test-001"
    ex = StrategyExecution(
        user_id=user_id,
        execution_id=exec_id,
        client_order_id="ann-client-001",
        strategy_tag="Bull Call Spread",
        symbol="NIFTY",
        status="FILLED",
        entry_net=100.0,
        realized_pnl=50.0,
        entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(ex)
    db_session.flush()

    pos = Position(
        user_id=user_id,
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=25000.0,
        option_type="call",
        net_quantity=0,
        average_entry_price=100.0,
        lot_size=50,
        realized_pnl=50.0,
        status="closed",
        strategy_execution_id=exec_id,
        opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(pos)
    db_session.commit()

    return exec_id


class TestAnnotationsAPI:
    def test_update_tags(self, client, logged_in, sample_execution):  # noqa: F811
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["earnings", "high-conviction"]},
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_id"] == sample_execution
        assert data["tags"] == ["earnings", "high-conviction"]
        assert data["notes"] is None

    def test_update_notes(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"notes": "Entered at support level"},
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notes"] == "Entered at support level"
        assert data["tags"] is None

    def test_update_both(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["test"], "notes": "both fields"},
            headers=h,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == ["test"]
        assert data["notes"] == "both fields"

    def test_clear_tags(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["a"]},
            headers=h,
        )
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": []},
            headers=h,
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] is None

    def test_clear_notes(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"notes": "something"},
            headers=h,
        )
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"notes": ""},
            headers=h,
        )
        assert resp.status_code == 200
        assert resp.json()["notes"] is None

    def test_nonexistent_execution(self, client, logged_in):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            "/paper/analytics/trades/nonexistent-id/annotations",
            json={"tags": ["test"]},
            headers=h,
        )
        assert resp.status_code == 404

    def test_unauthenticated(self, client, sample_execution):
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["test"]},
        )
        assert resp.status_code == 401

    def test_another_user_cannot_modify(self, client, db_session, sample_execution):
        """User B cannot modify user A's execution."""
        other_session = token_store.set_token("other-user-token-annotations")
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["test"]},
            headers={"X-Session-Id": other_session},
        )
        assert resp.status_code == 404  # not found for this user

    def test_max_tags_limit(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": [f"tag{i}" for i in range(11)]},
            headers=h,
        )
        assert resp.status_code == 422
        assert "10 tags" in resp.json()["detail"]

    def test_tag_max_length(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["a" * 51]},
            headers=h,
        )
        assert resp.status_code == 422
        assert "50 characters" in resp.json()["detail"]

    def test_notes_max_length(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"notes": "x" * 2001},
            headers=h,
        )
        assert resp.status_code == 422  # Pydantic max_length catches it

    def test_unicode_tags(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["निफ्टी", "महत्वपूर्ण"]},
            headers=h,
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["निफ्टी", "महत्वपूर्ण"]

    def test_unicode_notes(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        resp = client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"notes": "Unicode notes: 你好世界 🎯"},
            headers=h,
        )
        assert resp.status_code == 200
        assert "你好世界" in resp.json()["notes"]

    def test_persistence(self, client, logged_in, sample_execution):
        """Tags and notes persist across requests."""
        client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["persistent"], "notes": "persist me"},
            headers={"X-Session-Id": logged_in},
        )
        resp = client.get("/paper/analytics", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        journal = resp.json()["journal"]
        matching = [j for j in journal if j["execution_id"] == sample_execution]
        assert len(matching) == 1
        assert matching[0]["tags"] == ["persistent"]
        assert matching[0]["notes"] == "persist me"


class TestAnalyticsJournalIncludesAnnotations:
    def test_journal_contains_tags_and_notes(self, client, logged_in, sample_execution):
        """The /paper/analytics journal row includes tags and notes."""
        resp = client.get("/paper/analytics", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        journal = resp.json()["journal"]
        matching = [j for j in journal if j["execution_id"] == sample_execution]
        assert len(matching) == 1
        row = matching[0]
        # Default: no tags/notes set
        assert row.get("tags") is None
        assert row.get("notes") is None

    def test_after_annotation_appears_in_analytics(self, client, logged_in, sample_execution):
        h = {"X-Session-Id": logged_in}
        client.put(
            f"/paper/analytics/trades/{sample_execution}/annotations",
            json={"tags": ["visible"], "notes": "see me"},
            headers=h,
        )
        resp = client.get("/paper/analytics", headers=h)
        journal = resp.json()["journal"]
        matching = [j for j in journal if j["execution_id"] == sample_execution]
        assert matching[0]["tags"] == ["visible"]
        assert matching[0]["notes"] == "see me"


class TestLegacyJournalUnchanged:
    def test_legacy_journal_still_works(self, client, logged_in):
        """GET /paper/journal still functions without modification."""
        resp = client.get("/paper/journal", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        data = resp.json()
        assert "account" in data
        assert "stats" in data
        assert "trades" in data
