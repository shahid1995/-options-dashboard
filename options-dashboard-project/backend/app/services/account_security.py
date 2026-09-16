"""StrikeNova account-security services.

Owns (2026-09-16 design spec §4/§5):
- Opaque token generation: ``secrets``-based, high entropy; only the SHA-256
  digest is persisted (the raw token exists only in the returned email link).
- Single-use, expiry-bound consumption for verification / reset / email-change
  tokens; issuing a replacement invalidates prior active tokens of that kind.
- Durable, append-only SecurityEvent records with sanitized, secret-free
  metadata.
- Session helpers on the durable ``UserSession`` record — the authoritative
  account-session source.

Later tasks add recent-authentication state, account rate limiting and the
email-transport wiring here.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.identity import (
    SESSION_TTL,
    EmailVerificationToken,
    PasswordResetToken,
    PendingEmailChange,
    SecurityEvent,
    User,
    UserSession,
    create_session_record,
    revoke_session,
)

__all__ = [
    "EmailVerificationToken",
    "PasswordResetToken",
    "PendingEmailChange",
    "SecurityEvent",
    "create_opaque_token",
    "hash_token",
    "create_verification_token",
    "consume_verification_token",
    "create_reset_token",
    "consume_reset_token",
    "create_email_change_token",
    "consume_email_change_token",
    "record_security_event",
    "issue_account_session",
    "revoke_one",
    "revoke_all_for_user",
]

# Metadata keys that must never appear in a security event (defense in depth:
# the endpoint layer must not pass them either).
_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "raw_token",
        "token",
        "verification_token",
        "reset_token",
        "reset_url",
        "verification_url",
        "auth_code",
        "authorization_code",
        "code",
        "access_token",
        "refresh_token",
        "api_key",
        "api_secret",
        "broker_api_secret",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Opaque tokens
# ---------------------------------------------------------------------------


def create_opaque_token() -> str:
    """Return a new cryptographically random, opaque, high-entropy token.

    32 raw bytes → 43-char URL-safe base64 (~256 bits of entropy). The raw
    value is shown exactly once (the email link); only its digest is stored.
    """
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """SHA-256 digest of an opaque token — the only persisted form."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _consume_one(
    db: Session,
    model,
    raw_token: str,
    *,
    at: datetime | None = None,
):
    """Atomically consume a single-use token of *model*.

    Fail-closed: unknown, expired, or already-used tokens return ``None``.
    The ``used_at IS NULL`` predicate makes the consumption atomic — under
    concurrent requests exactly one transaction can claim the token.
    """
    if not raw_token:
        return None
    now = at or _utcnow()
    record = (
        db.query(model)
        .filter(
            model.token_hash == hash_token(raw_token),
            model.used_at.is_(None),
            model.expires_at > now,
        )
        .with_for_update(skip_locked=True)
        .one_or_none()
    )
    if record is None:
        return None
    record.used_at = now
    db.flush()
    return record


def _create_token(
    db: Session,
    model,
    user_id: str,
    *,
    ttl_minutes: int,
    new_email: str | None = None,
) -> tuple[str, object]:
    """Issue a replacement token, invalidating prior active ones of the kind."""
    now = _utcnow()
    # Invalidate prior active tokens for this user+kind (resend/recovery policy).
    stale = (
        db.query(model)
        .filter(model.user_id == user_id, model.used_at.is_(None))
        .all()
    )
    for record in stale:
        record.used_at = now
    db.flush()

    raw = create_opaque_token()
    kwargs = {
        "id": str(__import__("uuid").uuid4()),
        "user_id": user_id,
        "token_hash": hash_token(raw),
        "expires_at": now + timedelta(minutes=ttl_minutes),
    }
    if new_email is not None:
        kwargs["new_email"] = new_email
    record = model(**kwargs)
    db.add(record)
    db.flush()
    return raw, record


# ---------------------------------------------------------------------------
# Kind-specific wrappers
# ---------------------------------------------------------------------------


def create_verification_token(
    db: Session, user_id: str, *, ttl_minutes: int | None = None
) -> tuple[str, EmailVerificationToken]:
    return _create_token(
        db,
        EmailVerificationToken,
        user_id,
        ttl_minutes=ttl_minutes
        if ttl_minutes is not None
        else settings.EMAIL_VERIFICATION_TTL_MINUTES,
    )


def consume_verification_token(db: Session, raw_token: str) -> EmailVerificationToken | None:
    return _consume_one(db, EmailVerificationToken, raw_token)


def create_reset_token(
    db: Session, user_id: str, *, ttl_minutes: int | None = None
) -> tuple[str, PasswordResetToken]:
    return _create_token(
        db,
        PasswordResetToken,
        user_id,
        ttl_minutes=ttl_minutes
        if ttl_minutes is not None
        else settings.PASSWORD_RESET_TTL_MINUTES,
    )


def consume_reset_token(db: Session, raw_token: str) -> PasswordResetToken | None:
    return _consume_one(db, PasswordResetToken, raw_token)


def create_email_change_token(
    db: Session, user_id: str, new_email: str, *, ttl_minutes: int | None = None
) -> tuple[str, PendingEmailChange]:
    return _create_token(
        db,
        PendingEmailChange,
        user_id,
        ttl_minutes=ttl_minutes
        if ttl_minutes is not None
        else settings.EMAIL_VERIFICATION_TTL_MINUTES,
        new_email=new_email,
    )


def consume_email_change_token(db: Session, raw_token: str) -> PendingEmailChange | None:
    return _consume_one(db, PendingEmailChange, raw_token)


# ---------------------------------------------------------------------------
# Security events
# ---------------------------------------------------------------------------


def sanitize_metadata(metadata: dict | None) -> dict:
    """Return a copy of *metadata* with forbidden (secret-bearing) keys removed."""
    if not metadata:
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if str(key).lower() not in _FORBIDDEN_METADATA_KEYS
    }


def record_security_event(
    db: Session,
    *,
    user_id: str | None,
    event_type: str,
    session_id: str | None = None,
    ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    metadata: dict | None = None,
) -> SecurityEvent:
    """Persist one append-only, secret-free security event."""
    event = SecurityEvent(
        id=str(__import__("uuid").uuid4()),
        user_id=user_id,
        event_type=event_type,
        occurred_at=_utcnow(),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        session_id=session_id,
        metadata_json=sanitize_metadata(metadata),
    )
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------------------
# Sessions (durable UserSession authority)
# ---------------------------------------------------------------------------


def token_store_set(session_token: str) -> str:
    """Register a platform session token in the in-process token store."""
    from app.services.token_store import set_token

    return set_token(
        session_token,
        expires_at=_utcnow() + SESSION_TTL,
        persist_to_db=False,  # Platform sessions use UserSession, not BrokerToken
    )


def issue_account_session(db: Session, user: User) -> tuple[str, UserSession]:
    """Create a new durable account session for *user*.

    Returns ``(session_id, UserSession)``. The session id is high-entropy and
    only its SHA-256 digest is persisted (existing ``UserSession`` policy).
    """
    session_token = f"account:{user.id}:{secrets.token_urlsafe(24)}"
    session_id = token_store_set(session_token)
    record = create_session_record(db, user.id, session_id)
    return session_id, record


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
