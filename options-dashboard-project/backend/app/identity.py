"""Phase 10 identity foundation.

This module deliberately sits beside the existing auth/session implementation
while the application migrates from broker-coupled identity to a durable
StrikeNova account. It owns only identity metadata and session ownership;
broker tokens remain in the existing token store.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


SESSION_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt.

    Returns a string in the format ``iterations$salt$digest``.
    """
    iterations = 480_000
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored PBKDF2 hash.

    Returns True if the password matches, False otherwise.
    """
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False
        iterations, salt_hex, expected_hex = int(parts[0]), parts[1], parts[2]
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return _hmac.compare_digest(dk.hex(), expected_hex)
    except Exception:
        return False


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    identity_source: Mapped[str] = mapped_column(String(32), default="upstox")
    broker_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    broker_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
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
    broker_connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_connections.id"), nullable=True
    )


class BrokerConnection(Base):
    """Persistent broker connection owned by a StrikeNova user. (AD-4)

    Stores the user's per-user broker credentials (encrypted) and
    connection metadata. Each row represents one broker account
    linked to one StrikeNova user. (AD-2, AD-5)

    Three independent capabilities (Phase 10.2B-6):
      1. Authentication — OAuth identity, profile, funds
      2. Market Data — option chain, quotes, Greeks, GEX, historical
      3. Trading — order placement, modification, cancellation

    Status lifecycle:
      pending  → connected → expired | disconnected
      pending:  credentials stored via POST /auth/connect, no OAuth yet
      connected: first OAuth completed, broker_account_id populated

    broker_account_id lifecycle:
      1. Initially "pending" when credentials are stored (POST /auth/connect)
         before the first OAuth completes.
      2. After first successful OAuth, updated to the broker's account ID
         (e.g. Upstox user_id, FYERS app_id).  Immutable thereafter.
      3. Required (NOT NULL) — "pending" is a sentinel for pre-OAuth rows.
      4. Part of unique constraint (user_id, broker, broker_account_id).
         "pending" allows one pre-OAuth row per (user, broker).

    is_default invariant:
      At most one connection per (user_id, broker) may have is_default=True.
      Enforced via partial unique index uq_one_default_per_user_broker.
    """

    __tablename__ = "broker_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    broker: Mapped[str] = mapped_column(String(32), index=True)
    broker_account_id: Mapped[str] = mapped_column(String(128))
    display_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(20), default="connected")
    capability_mode: Mapped[str] = mapped_column(String(20), default="trading")  # DEPRECATED: use data_status + trading_status

    # Phase 10.2B-6: Independent capability status
    data_status: Mapped[str] = mapped_column(String(20), default="inactive")  # "inactive" | "active" | "expired"
    data_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "analytics_token" | "oauth_token"
    trading_status: Mapped[str] = mapped_column(String(20), default="inactive")  # "inactive" | "active" | "expired"
    trading_static_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # per-user static IP for trading

    # Per-user broker credentials (encrypted — AD-2, AD-3)
    broker_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_api_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_analytics_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_static_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Provider-specific metadata
    app_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "broker", "broker_account_id", name="uq_broker_connection"),
        # Partial unique index: at most one default connection per (user, broker).
        # Enforced ONLY at the schema level via Alembic migration
        # (125e1807df8d).  NOT declared here because cross-dialect partial
        # indexes (PostgreSQL WHERE vs SQLite WHERE) cannot be expressed
        # portably in SQLAlchemy ORM metadata — create_all() would create
        # a plain unique index on (user_id, broker) in SQLite, blocking
        # legitimate multi-connection rows.
    )


class BrokerToken(Base):
    """Session-scoped broker token. (§5.2)

    One row per (connection, session) pair. Tokens are encrypted at rest.
    """

    __tablename__ = "broker_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE"), index=True
    )
    session_hash: Mapped[str] = mapped_column(String(64), index=True)
    broker_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    broker_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("connection_id", "session_hash", name="uq_broker_token_per_session"),
    )


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


def create_session_record(
    db: Session,
    user_id: str,
    session_id: str,
    broker_connection_id: str | None = None,
) -> UserSession:
    """Create a durable session record linking session → user.

    broker_connection_id links the session to the specific broker
    connection used for authentication (nullable for backward compat).
    """
    now = _utcnow()
    record = UserSession(
        user_id=user_id,
        session_hash=hash_session_id(session_id),
        broker_connection_id=broker_connection_id,
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    db.add(record)
    db.flush()
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
    db.flush()
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


# ---------------------------------------------------------------------------
# Platform session / broker token resolution
# ---------------------------------------------------------------------------


def resolve_platform_session(session_id: str | None) -> str | None:
    """Resolve session_id → user_id for a valid platform session.

    Returns the user_id if the session exists, is not expired, and is not
    revoked.  Returns None otherwise.

    This is the canonical platform-identity resolver — it NEVER returns a
    broker token.  Use resolve_broker_token_by_session_hash() for broker
    authorization.
    """
    if not session_id:
        return None
    try:
        from app.db import SessionLocal

        now = _utcnow()
        db = SessionLocal()
        try:
            us = (
                db.query(UserSession)
                .filter(
                    UserSession.session_hash == hash_session_id(session_id),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .first()
            )
            return us.user_id if us is not None else None
        finally:
            db.close()
    except Exception:
        return None


def resolve_broker_token_by_session_hash(session_hash: str | None) -> str | None:
    """Resolve session_hash → decrypted broker access token.

    Queries BrokerToken joined with UserSession by session_hash.
    Returns the decrypted broker token if:
      - BrokerToken exists with non-null encrypted token
      - UserSession is not expired and not revoked
    Returns None otherwise.

    This avoids the double-hashing bug of passing session_hash to
    get_token() which expects plaintext session_id.
    """
    if not session_hash:
        return None
    try:
        from app.db import SessionLocal
        from app.crypto import decrypt

        now = _utcnow()
        db = SessionLocal()
        try:
            row = (
                db.query(BrokerToken, UserSession)
                .join(
                    UserSession,
                    BrokerToken.session_hash == UserSession.session_hash,
                )
                .filter(
                    BrokerToken.session_hash == session_hash,
                    BrokerToken.broker_token_encrypted.isnot(None),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .first()
            )
            if row is not None:
                bt, _us = row
                return decrypt(bt.broker_token_encrypted)
            return None
        finally:
            db.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 10.2B-2 — BYOB Credential Management
# ---------------------------------------------------------------------------


def resolve_user_credentials(
    user_id: str, broker: str, db: Session
) -> dict:
    """Resolve a user's encrypted broker credentials from broker_connections.

    Selects the default connection (or most recent) for the given
    (user_id, broker) where credentials are available.

    Returns a dict suitable for passing to the adapter constructor:
      {"api_key": "...", "api_secret": "...", "redirect_uri": "..."}

    Raises ValueError if no credential-bearing connection exists.

    Security: this function NEVER returns platform-level credentials.
    It only returns per-user encrypted values from broker_connections.
    """
    from app.crypto import decrypt

    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker.upper(),
            BrokerConnection.broker_api_key_encrypted.isnot(None),
        )
        .order_by(
            BrokerConnection.is_default.desc(),
            BrokerConnection.created_at.desc(),
        )
        .first()
    )
    if conn is None:
        raise ValueError(
            f"No {broker} credentials found for user {user_id}. "
            f"Use POST /auth/connect to store your broker credentials first."
        )

    credentials = {}
    api_key = decrypt(conn.broker_api_key_encrypted)
    if not api_key:
        raise ValueError(
            f"Stored API key for {broker} is empty after decryption"
        )
    credentials["api_key"] = api_key

    if conn.broker_api_secret_encrypted:
        api_secret = decrypt(conn.broker_api_secret_encrypted)
        if api_secret:
            credentials["api_secret"] = api_secret

    if conn.broker_redirect_uri:
        credentials["redirect_uri"] = conn.broker_redirect_uri

    return credentials


def store_credentials(
    db: Session,
    user_id: str,
    broker: str,
    api_key: str,
    api_secret: str,
    *,
    redirect_uri: str | None = None,
    display_label: str | None = None,
) -> BrokerConnection:
    """Encrypt and store a user's broker Developer App credentials.

    Creates or updates a BrokerConnection row.  New connections are created
    with broker_account_id="pending" and status="pending" — the real
    broker_account_id is populated after the first successful OAuth.

    Returns the BrokerConnection row.
    """
    from app.crypto import encrypt

    broker_upper = broker.upper()

    # Check for existing pending OR data-only connection for this (user, broker).
    # A data-only connection (created by store_analytics_token) can be upgraded
    # to hold broker credentials without creating a duplicate row.
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.broker_account_id.in_(["pending", "data-only"]),
        )
        .first()
    )

    if conn is None:
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user_id,
            broker=broker_upper,
            broker_account_id="pending",
            status="pending",
            display_label=display_label,
            connected_at=_utcnow(),
        )
        # is_default defaults to True via ORM metadata — this is correct for
        # the first connection per (user, broker).  The partial unique index
        # uq_one_default_per_user_broker enforces at most one default per
        # (user, broker) at the schema level.
        db.add(conn)

    conn.broker_api_key_encrypted = encrypt(api_key)
    conn.broker_api_secret_encrypted = encrypt(api_secret)
    if redirect_uri:
        conn.broker_redirect_uri = redirect_uri
    if display_label:
        conn.display_label = display_label

    conn.updated_at = _utcnow()
    db.flush()
    return conn


def get_or_create_connection(
    db: Session,
    user_id: str,
    broker: str,
    broker_account_id: str,
    *,
    status: str = "connected",
) -> BrokerConnection:
    """Create or update a BrokerConnection after successful OAuth.

    Called after OAuth callback to:
      1. Replace broker_account_id="pending" with the real account ID
      2. Set status="connected"
      3. Update connected_at timestamp

    If a connection with the real broker_account_id already exists,
    it is updated (re-login scenario).

    broker_account_id must be pre-extracted by the adapter layer (AD-6).
    """
    broker_upper = broker.upper()

    # First: check if a pending row exists for this (user, broker)
    pending_conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.broker_account_id == "pending",
        )
        .first()
    )

    # Second: check if a connected row with this account ID exists
    existing_conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.broker_account_id == broker_account_id,
        )
        .first()
    )

    if existing_conn is not None:
        # Re-login to existing connection
        conn = existing_conn
    elif pending_conn is not None:
        # Transition from pending → connected
        conn = pending_conn
    else:
        # New connection (e.g. first OAuth without prior credential storage)
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user_id,
            broker=broker_upper,
            broker_account_id=broker_account_id,
            connected_at=_utcnow(),
        )
        db.add(conn)

    conn.broker_account_id = broker_account_id
    conn.status = status
    conn.disconnected_at = None
    conn.connected_at = _utcnow()
    conn.updated_at = _utcnow()
    db.flush()
    return conn


# ---------------------------------------------------------------------------
# Google OAuth identity (Phase A)
# ---------------------------------------------------------------------------


def get_or_create_user_from_google(
    db: Session,
    google_sub: str,
    email: str | None,
    display_name: str | None,
) -> User:
    """Map a Google-authenticated identity to a durable StrikeNova user.

    Account linking rules:
    1. If a user with this google_sub exists → update and return.
    2. If a user with this email exists (email/password or Upstox) → link Google.
    3. Otherwise → create a new user.

    This prevents duplicate accounts when the same person uses multiple
    sign-in methods.
    """
    email = (email or "").strip().lower() or None
    display_name = (display_name or "").strip() or None

    # 1. Existing Google user
    existing = (
        db.query(User)
        .filter(User.google_sub == google_sub)
        .one_or_none()
    )
    if existing is not None:
        existing.email = email or existing.email
        existing.display_name = display_name or existing.display_name
        existing.last_login_at = _utcnow()
        db.flush()
        return existing

    # 2. Existing user with same email — link Google to existing account
    if email:
        existing = (
            db.query(User)
            .filter(User.email == email)
            .one_or_none()
        )
        if existing is not None:
            existing.google_sub = google_sub
            existing.display_name = display_name or existing.display_name
            existing.last_login_at = _utcnow()
            # Update identity_source to reflect multi-provider
            if existing.identity_source == "email":
                existing.identity_source = "google"
            db.flush()
            return existing

    # 3. New user
    user = User(
        id=str(uuid4()),
        email=email,
        google_sub=google_sub,
        display_name=display_name,
        status="active",
        identity_source="google",
        last_login_at=_utcnow(),
    )
    db.add(user)
    db.flush()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Analytics Token management (Phase 10.2B-4)
# ---------------------------------------------------------------------------


def store_analytics_token(
    db: Session,
    user_id: str,
    broker: str,
    analytics_token: str,
) -> BrokerConnection:
    """Store an encrypted Analytics Token on the user's default connection.

    Phase 10.2B-6: Supports both data-only and full OAuth connections.
    If no connected connection exists, creates a data-only connection
    with broker_account_id='data-only' and status='connected'.

    The Analytics Token is encrypted at rest via Fernet (app.crypto).
    Only one Analytics Token per (user, broker) — overwrites existing.

    Returns the BrokerConnection row.
    """
    from app.crypto import encrypt

    broker_upper = broker.upper()

    # Try to find an existing connected default connection
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.status == "connected",
            BrokerConnection.is_default == True,
        )
        .first()
    )

    # If no connected connection exists, create a data-only connection
    # This allows users to connect market data without completing OAuth
    if conn is None:
        conn = BrokerConnection(
            id=str(uuid4()),
            user_id=user_id,
            broker=broker_upper,
            broker_account_id="data-only",
            status="connected",
            data_status="active",
            data_source="analytics_token",
            display_label=f"{broker_upper} (Data Only)",
            connected_at=_utcnow(),
        )
        db.add(conn)
        db.flush()

    conn.broker_analytics_token_encrypted = encrypt(analytics_token)
    conn.data_status = "active"
    conn.data_source = "analytics_token"
    conn.updated_at = _utcnow()
    db.flush()
    return conn


def get_analytics_token(
    db: Session,
    user_id: str,
    broker: str,
) -> str | None:
    """Retrieve and decrypt the Analytics Token for a user's broker connection.

    Phase 10.2B-6: Works with both data-only and full OAuth connections.
    Requires data_status == 'active' for explicit data authorization.
    Returns None if no Analytics Token is stored or data is inactive.
    """
    from app.crypto import decrypt

    broker_upper = broker.upper()
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.status == "connected",
            BrokerConnection.data_status == "active",
            BrokerConnection.broker_analytics_token_encrypted.isnot(None),
        )
        .first()
    )
    if conn is None:
        return None
    return decrypt(conn.broker_analytics_token_encrypted)


def remove_analytics_token(
    db: Session,
    user_id: str,
    broker: str,
) -> bool:
    """Remove the Analytics Token from a user's broker connection.

    Phase 10.2B-6: If this was a data-only connection (broker_account_id='data-only'),
    also update data_status to 'inactive'.

    Returns True if a token was removed, False if none existed.
    """
    broker_upper = broker.upper()
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker_upper,
            BrokerConnection.status == "connected",
            BrokerConnection.is_default == True,
        )
        .first()
    )
    if conn is None or conn.broker_analytics_token_encrypted is None:
        return False
    conn.broker_analytics_token_encrypted = None
    conn.data_status = "inactive"
    conn.data_source = None
    conn.updated_at = _utcnow()
    db.flush()
    return True
