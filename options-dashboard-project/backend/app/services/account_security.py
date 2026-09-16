"""StrikeNova account-security services.

Task 1 scope: session creation and revocation helpers built on the durable
``UserSession`` record — the authoritative account-session source. Later
tasks add token services, recent-authentication state, rate limiting and
security-event persistence here.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.identity import SESSION_TTL, User, UserSession, create_session_record, revoke_session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def issue_account_session(db: Session, user: User) -> tuple[str, UserSession]:
    """Create a new durable account session for *user*.

    Returns ``(session_id, UserSession)``. The session id is high-entropy and
    only its SHA-256 digest is persisted (existing ``UserSession`` policy).
    """
    session_token = f"account:{user.id}:{secrets.token_urlsafe(24)}"
    session_id = token_store_set(session_token)
    record = create_session_record(db, user.id, session_id)
    return session_id, record


def token_store_set(session_token: str) -> str:
    """Register the session token in the in-process token store.

    Kept as a tiny indirection so tests can intercept token creation.
    """
    from app.services.token_store import set_token

    return set_token(
        session_token,
        expires_at=_utcnow() + SESSION_TTL,
        persist_to_db=False,  # Platform sessions use UserSession, not BrokerToken
    )


def revoke_one(db: Session, session_id: str | None) -> bool:
    """Revoke a single session by its identifier. Idempotent."""
    if not session_id:
        return False
    return revoke_session(db, session_id)


def revoke_all_for_user(db: Session, user_id: str) -> int:
    """Revoke every active (non-revoked, non-expired) session for a user.

    Returns the number of sessions revoked.
    """
    now = _utcnow()
    active = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .all()
    )
    for record in active:
        record.revoked_at = now
    if active:
        db.flush()
    return len(active)


__all__ = [
    "issue_account_session",
    "revoke_one",
    "revoke_all_for_user",
]
