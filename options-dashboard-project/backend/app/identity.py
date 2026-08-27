"""Phase 10 identity foundation.

This module deliberately sits beside the existing auth/session implementation
while the application migrates from broker-coupled identity to a durable
StrikeNova account. It owns only identity metadata and session ownership;
broker tokens remain in the existing token store.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, engine


SESSION_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    identity_source: Mapped[str] = mapped_column(String(32), default="upstox")
    broker_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    broker_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("broker_provider", "broker_user_id", name="uq_users_broker_identity"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def ensure_identity_schema() -> None:
    """Create only the Phase 10 identity tables if they do not exist yet.

    The application currently uses ``Base.metadata.create_all`` rather than
    Alembic migrations. This isolated create_all is intentionally limited to
    the new identity tables so Phase 10 can be introduced without touching
    existing schema objects.
    """
    Base.metadata.create_all(bind=engine, tables=[User.__table__, UserSession.__table__])


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def get_or_create_user_from_upstox(db: Session, profile: dict) -> User:
    """Map the authenticated Upstox identity to one durable StrikeNova user."""
    data = profile.get("data") if isinstance(profile, dict) else None
    data = data if isinstance(data, dict) else {}

    broker_user_id = str(data.get("user_id") or "").strip()
    if not broker_user_id:
        raise ValueError("Upstox profile did not contain a broker user_id")

    provider = str(data.get("broker") or "UPSTOX").strip().upper()
    email = str(data.get("email") or "").strip().lower() or None
    display_name = str(data.get("user_name") or "").strip() or None
    broker_active = bool(data.get("is_active", True))

    user = (
        db.query(User)
        .filter(User.broker_provider == provider, User.broker_user_id == broker_user_id)
        .one_or_none()
    )

    if user is None:
        user = User(
            id=str(uuid4()),
            email=email,
            display_name=display_name,
            status="active" if broker_active else "suspended",
            identity_source="upstox",
            broker_provider=provider,
            broker_user_id=broker_user_id,
            last_login_at=_utcnow(),
        )
        db.add(user)
    else:
        user.email = email or user.email
        user.display_name = display_name or user.display_name
        # Do not let broker login silently undo a future StrikeNova admin
        # suspension/disable action. Only an active account may be refreshed
        # by broker activity; disabled/suspended are platform-owned states.
        if user.status == "active" and not broker_active:
            user.status = "suspended"
        user.last_login_at = _utcnow()

    db.flush()
    return user


def create_session_record(db: Session, user_id: str, session_id: str) -> UserSession:
    now = _utcnow()
    record = UserSession(
        user_id=user_id,
        session_hash=hash_session_id(session_id),
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def revoke_session(db: Session, session_id: str) -> bool:
    record = (
        db.query(UserSession)
        .filter(UserSession.session_hash == hash_session_id(session_id), UserSession.revoked_at.is_(None))
        .one_or_none()
    )
    if record is None:
        return False
    record.revoked_at = _utcnow()
    db.commit()
    return True


def get_active_session(db: Session, session_id: str | None) -> UserSession | None:
    if not session_id:
        return None
    now = _utcnow()
    return (
        db.query(UserSession)
        .filter(
            UserSession.session_hash == hash_session_id(session_id),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .one_or_none()
    )
