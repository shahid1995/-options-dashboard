"""Tests for the Phase 10 identity foundation and Phase 10.1A migration integration.

Phase 10.1A changes:
- ensure_identity_schema() removed from auth path (schema managed by Alembic)
- Identity tables (users, user_sessions) created via Alembic baseline migration
- Tests use in-memory SQLite with Base.metadata.create_all for isolation
"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.identity as identity


def test_hash_session_id_is_deterministic_and_not_plaintext():
    raw = "session-example-123"
    digest = identity.hash_session_id(raw)
    assert digest == identity.hash_session_id(raw)
    assert digest != raw
    assert len(digest) == 64


def test_upstox_identity_is_stable_and_session_is_user_scoped(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    identity.Base.metadata.create_all(
        bind=engine,
        tables=[identity.User.__table__, identity.UserSession.__table__],
    )
    db = sessionmaker(bind=engine)()
    try:
        profile = {
            "status": "success",
            "data": {
                "broker": "UPSTOX",
                "user_id": "UCC-123",
                "email": "Trader@Example.com",
                "user_name": "Trader One",
                "is_active": True,
            },
        }

        first = identity.get_or_create_user_from_upstox(db, profile)
        db.commit()
        second = identity.get_or_create_user_from_upstox(db, profile)

        assert first.id == second.id
        assert second.email == "trader@example.com"
        assert second.display_name == "Trader One"

        session = identity.create_session_record(db, first.id, "session-a")
        active = identity.get_active_session(db, "session-a")
        assert active is not None
        assert active.user_id == first.id
        assert active.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)

        assert identity.get_active_session(db, "session-b") is None
        assert identity.revoke_session(db, "session-a") is True
        assert identity.get_active_session(db, "session-a") is None
    finally:
        db.close()


def test_identity_models_register_on_base_metadata():
    """Verify User and UserSession are registered on Base.metadata.

    This ensures Alembic autogenerate can detect them.
    """
    tables = set(identity.Base.metadata.tables.keys())
    assert "users" in tables
    assert "user_sessions" in tables


def test_identity_session_expires_correctly():
    """Verify session TTL is applied correctly."""
    from app.identity import SESSION_TTL
    assert SESSION_TTL.total_seconds() == 24 * 3600  # 24 hours
