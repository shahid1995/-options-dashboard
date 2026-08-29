"""Shared test helpers for Phase 10.2A identity setup.

Every test that authenticates via the API must have matching ``users``
and ``user_sessions`` rows in the test database.  This module provides
the ``create_test_identity()`` helper used by affected test files.
"""

from uuid import uuid4

from app.identity import User, UserSession, create_session_record
from app.services import token_store


def create_test_identity(db, token: str = "tok-test") -> tuple[str, str]:
    """Create a User + UserSession + token_store entry for testing.

    Args:
        db: An active SQLAlchemy session for the test database.
        token: The broker token string to store in token_store.

    Returns:
        (session_id, user_id) — session_id for headers, user_id for assertions.
    """
    user_id = str(uuid4())
    session_id = token_store.set_token(token)

    user = User(
        id=user_id,
        status="active",
        identity_source="upstox",
        broker_provider="UPSTOX",
        broker_user_id=f"test-{user_id[:8]}",
    )
    db.add(user)
    db.flush()

    create_session_record(db, user_id, session_id)

    # Store user_id on the db session for test assertions
    db._test_user_id = user_id

    return session_id, user_id
