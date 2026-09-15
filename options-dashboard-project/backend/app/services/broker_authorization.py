"""Broker-neutral authorization resolution and persistence.

THE authorization path after the broker-authorization refactor:

    authenticated StrikeNova user + broker
        → BrokerConnection (durable ownership ledger)
        → active BrokerAuthorization (encrypted token material)

Resolution NEVER consults UserSession: a brand-new StrikeNova session for
the same user resolves the same connection + active authorization, and an
expired/revoked initiating session never disconnects the broker.

Security properties:
  - Token material is decrypted ONLY in-process, never logged, never
    serialized into API responses or diagnostics.
  - Only the connection owner's user_id can resolve an authorization;
    any other user's resolution is (None, None) — fail closed.
  - Every OAuth callback supersedes the previous active authorization
    (new row inserted, old row marked superseded) — no dual source of
    truth; history is preserved for auditability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crypto import encrypt
from app.identity import BrokerAuthorization, BrokerConnection

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("active",)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def persist_connection_authorization(
    db: Session,
    *,
    connection_id: str,
    broker: str,
    access_token: str,
    expires_at: datetime | None = None,
    refresh_token: str | None = None,
    refresh_expires_at: datetime | None = None,
    method: str = "oauth_callback",
    now: datetime | None = None,
) -> BrokerAuthorization:
    """Persist a new active BrokerAuthorization for a connection.

    Supersedes any previously active authorization for the same connection
    (status -> "superseded"). Runs on the CALLER's transaction: flush only,
    commit stays with the caller so the whole broker-link write is atomic.
    Never logs token material.
    """
    now = now or _utcnow()
    broker = (broker or "").upper()

    previous = (
        db.query(BrokerAuthorization)
        .filter(
            BrokerAuthorization.connection_id == connection_id,
            BrokerAuthorization.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )
    for old in previous:
        old.status = "superseded"
    if previous:
        logger.info(
            "BrokerAuthorization superseded",
            extra={
                "event": "broker_authorization.superseded",
                "connection_id": connection_id,
                "broker": broker,
                "superseded_count": len(previous),
            },
        )

    authz = BrokerAuthorization(
        id=_new_id(),
        connection_id=connection_id,
        access_token_encrypted=encrypt(access_token) if access_token else None,
        access_token_expires_at=expires_at,
        refresh_token_encrypted=encrypt(refresh_token) if refresh_token else None,
        refresh_token_expires_at=refresh_expires_at,
        status="active",
        method=method,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(authz)
    db.flush()
    logger.info(
        "BrokerAuthorization persisted",
        extra={
            "event": "broker_authorization.persisted",
            "connection_id": connection_id,
            "broker": broker,
            "authorization_id": authz.id,
            "method": method,
            "has_refresh_token": bool(refresh_token),
        },
    )
    return authz


def _new_id() -> str:
    from uuid import uuid4

    return str(uuid4())


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize DB-loaded (possibly naive) datetimes to UTC-aware for comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_broker_authorization(
    db: Session, user_id: str, broker: str, *, now: datetime | None = None
) -> tuple[BrokerConnection | None, BrokerAuthorization | None]:
    """Resolve (connection, active authorization) for a user + broker.

    User → BrokerConnection → active BrokerAuthorization.  Pure ownership
    path — the user's CURRENT session plays no role, so new sessions and
    expired ones resolve identically.  Authorization status is honoured:
    expired/revoked/superseded rows never resolve as active.
    """
    now = now or _utcnow()
    broker = (broker or "").upper()

    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == broker,
            BrokerConnection.status.in_(("connected", "pending")),
        )
        .order_by(BrokerConnection.is_default.desc(), BrokerConnection.created_at.desc())
        .first()
    )
    if conn is None:
        return None, None

    authz = (
        db.query(BrokerAuthorization)
        .filter(
            BrokerAuthorization.connection_id == conn.id,
            BrokerAuthorization.status.in_(ACTIVE_STATUSES),
        )
        .order_by(BrokerAuthorization.issued_at.desc())
        .first()
    )
    if authz is None:
        return conn, None

    expiry = _aware(authz.access_token_expires_at)
    if expiry is not None and expiry <= now:
        # Lazy expiry: the authorization expired on its own clock. Mark it
        # (best-effort — another worker may race us) and fail closed.
        authz.status = "expired"
        try:
            db.commit()
        except Exception:
            db.rollback()
        return conn, None

    authz.last_used_at = now
    db.flush()
    return conn, authz


def resolve_default_broker_authorization(
    db: Session, user_id: str, *, now: datetime | None = None
) -> tuple[BrokerConnection | None, BrokerAuthorization | None]:
    """Resolve the user's default connected connection + active authorization.

    Broker-neutral entry point for the data plane (the session carries no
    broker hint): picks the user's default connection (is_default first,
    then most recently connected). Used by token resolution so a NEW
    StrikeNova session — which has no broker binding of its own — still
    reaches the same connection + authorization as the consenting one.
    """
    now = now or _utcnow()
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.status.in_(("connected", "pending")),
        )
        .order_by(BrokerConnection.is_default.desc(), BrokerConnection.connected_at.desc())
        .first()
    )
    if conn is None:
        return None, None
    return _active_authorization_for_connection(db, conn, now=now)


def _active_authorization_for_connection(
    db: Session, conn: BrokerConnection, *, now: datetime
) -> tuple[BrokerConnection | None, BrokerAuthorization | None]:
    authz = (
        db.query(BrokerAuthorization)
        .filter(
            BrokerAuthorization.connection_id == conn.id,
            BrokerAuthorization.status.in_(ACTIVE_STATUSES),
        )
        .order_by(BrokerAuthorization.issued_at.desc())
        .first()
    )
    if authz is None:
        return conn, None
    expiry = _aware(authz.access_token_expires_at)
    if expiry is not None and expiry <= now:
        authz.status = "expired"
        try:
            db.commit()
        except Exception:
            db.rollback()
        return conn, None
    authz.last_used_at = now
    db.flush()
    return conn, authz


def authorization_status(authz: BrokerAuthorization, *, now: datetime | None = None) -> str:
    """Honest status of an authorization row at ``now`` (no session coupling)."""
    now = now or _utcnow()
    if authz.status != "active":
        return authz.status
    expiry = _aware(authz.access_token_expires_at)
    if expiry is not None and expiry <= now:
        return "expired"
    return "active"


def revoke_connection_authorizations(
    db: Session, connection_id: str, *, reason: str = "revoked", now: datetime | None = None
) -> int:
    """Revoke all active authorizations for a connection. Returns count."""
    now = now or _utcnow()
    rows = (
        db.query(BrokerAuthorization)
        .filter(
            BrokerAuthorization.connection_id == connection_id,
            BrokerAuthorization.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )
    for row in rows:
        row.status = "revoked"
    if rows:
        logger.info(
            "BrokerAuthorization revoked",
            extra={
                "event": "broker_authorization.revoked",
                "connection_id": connection_id,
                "count": len(rows),
                "reason": reason,
            },
        )
    return len(rows)
