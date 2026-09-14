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
    """Broker identity → platform user resolution is stable and user-scoped.

    Session-bound linking (UPSTOX_IDENTITY_LINKING_DESIGN.md §17.1) retired
    broker-coupled user creation: get_or_create_user_from_upstox is
    lookup-only and never creates a User. The resolver must return the
    same existing user on every sight of the broker identity and must
    never let broker profile data touch users.email.
    """
    from uuid import uuid4

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

        # The platform user must already exist (registered via email or
        # Google) and be stamped with the broker identity.
        existing = identity.User(
            id=str(uuid4()),
            email="trader@example.com",
            display_name="Platform Display",
            status="active",
            identity_source="email",
            broker_provider="UPSTOX",
            broker_user_id="UCC-123",
        )
        db.add(existing)
        db.commit()

        first = identity.get_or_create_user_from_upstox(db, profile)
        db.commit()
        second = identity.get_or_create_user_from_upstox(db, profile)

        # Lookup-only: no user creation, stable identity, users.email never
        # overwritten by the broker profile email. (display_name is
        # informational metadata the legacy helper may refresh.)
        assert first.id == existing.id
        assert second.id == existing.id
        assert second.email == "trader@example.com"
        assert second.display_name == "Trader One"

        # A broker identity with NO owning user is refused, never created.
        stranger_profile = dict(profile)
        stranger_profile["data"] = dict(profile["data"], user_id="UCC-NEW")
        try:
            identity.get_or_create_user_from_upstox(db, stranger_profile)
            raised = False
        except LookupError:
            raised = True
        assert raised, "broker OAuth must not create platform users"

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
